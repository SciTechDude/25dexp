"""Ursina adapter: the camera rig and the reference scenery.

This is the only module that both imports Ursina and knows about table
geometry. Everything above it works in millimetres; everything below it is
Panda3D's problem.

Notes on driving Ursina's camera, learned from reading its source rather
than guessing -- both of these will silently break the projection if
ignored:

1. ``camera.lens`` always refers to the *perspective* lens, even after
   ``camera.orthographic = True``. The orthographic setter swaps the lens on
   the underlying Panda camera node but leaves ``camera.lens`` pointing at
   the old object. So this module addresses ``camera.perspective_lens`` and
   ``camera.orthographic_lens`` explicitly and never reads ``camera.lens``.

2. Ursina's ``orthographic`` setter ends with ``self.fov = self.fov``, and
   the ``fov`` setter calls ``set_fov()`` / ``set_film_size()``. Both
   overwrite exactly the film size and focal length the off-axis projection
   depends on. Panda also resets the lens aspect ratio on window resize, for
   the same reason. The fix is simply to reapply our lens parameters every
   frame, after any mode change, and to never touch ``camera.fov``.
"""

from __future__ import annotations

# Must precede the Ursina import: Ursina configures Panda3D at import time,
# so platform settings applied afterwards are silently ignored.
from tabletop.render import platform_setup  # noqa: F401  (import for effect)
from ursina import (
    Entity,
    Mesh,
    Vec3,
    camera,
    color,
    window,
)

from tabletop.core.calibration import TableCalibration
from tabletop.render.mapping import (
    TOP_DOWN_CAMERA_ROTATION,
    mm_to_world,
    table_to_world,
)
from tabletop.render.projection import (
    Eye,
    LensParams,
    ProjectionMode,
    effective_vertical_fov_deg,
    lens_eye,
    lens_params_for,
)

__all__ = ["TableRig", "build_table_scenery"]

NEAR_PLANE_MM = 20.0
"""Close enough to never clip a hand hovering just above the glass."""

FAR_PLANE_MARGIN_MM = 3000.0
"""Added behind the eye's distance so recessed content is never clipped."""


class TableRig:
    """Owns the camera and lens, and keeps them consistent with an eye pose.

    The camera is positioned at the eye and aimed straight down, once. It is
    never re-aimed: the lens shear does all the work of following the
    viewer. Re-aiming is the mistake that converts a window into a swinging
    scene, so there is deliberately no code path here that can rotate it.
    """

    def __init__(
        self,
        calibration: TableCalibration,
        mode: ProjectionMode = ProjectionMode.OFF_AXIS_HEAD_TRACKED,
        fixed_eye_height_mm: float = 700.0,
    ) -> None:
        self.calibration = calibration
        self.mode = mode
        self.fixed_eye_height_mm = fixed_eye_height_mm
        self._applied_orthographic: bool | None = None
        self.last_params: LensParams | None = None
        self.last_eye: Eye | None = None
        """The eye the lens projected from on the last :meth:`apply`.

        Not the eye passed in: only the head-tracked mode projects from the
        viewer. Anything working out where content above the glass will
        appear needs this one."""

    @property
    def screen_width_mm(self) -> float:
        return self.calibration.display_width_mm

    @property
    def screen_height_mm(self) -> float:
        return self.calibration.display_height_mm

    def apply(self, eye: Eye) -> LensParams:
        """Point the rig at ``eye``. Call once per frame.

        Returns the :class:`LensParams` actually used, so a HUD can display
        the real numbers rather than a guess at them.
        """
        params = lens_params_for(
            self.mode,
            self.screen_width_mm,
            self.screen_height_mm,
            eye,
            fixed_eye_height=self.fixed_eye_height_mm,
            viewport_aspect=window.aspect_ratio,
        )

        # Swap lenses only on an actual change: the setter has side effects.
        if self._applied_orthographic != params.orthographic:
            camera.orthographic = params.orthographic
            self._applied_orthographic = params.orthographic

        lens = (
            camera.orthographic_lens
            if params.orthographic
            else camera.perspective_lens
        )

        # Film size before focal length: in Panda these are interdependent,
        # and setting size first then focal leaves both as specified.
        lens.set_film_size(
            mm_to_world(params.film_width), mm_to_world(params.film_height)
        )
        if not params.orthographic:
            lens.set_focal_length(mm_to_world(params.focal_length))
        lens.set_film_offset(
            mm_to_world(params.film_offset_x), mm_to_world(params.film_offset_y)
        )

        far_mm = eye.z + FAR_PLANE_MARGIN_MM
        lens.set_near_far(mm_to_world(NEAR_PLANE_MM), mm_to_world(far_mm))

        # The camera sits at the eye for head-tracked mode; for the fixed
        # modes it hangs above the table centre. In every case it looks
        # straight down and is never re-aimed.
        cam = lens_eye(self.mode, eye, self.fixed_eye_height_mm)
        camera.position = Vec3(*table_to_world(cam.x, cam.y, cam.z))
        camera.rotation = TOP_DOWN_CAMERA_ROTATION

        self.last_params = params
        self.last_eye = cam
        return params

    def status_text(self, eye: Eye) -> str:
        """A human-readable readout of the current projection state."""
        p = self.last_params
        if p is None:
            return "rig not yet applied"
        fov = effective_vertical_fov_deg(p)
        fov_text = "n/a (parallel)" if p.orthographic else f"{fov:.1f} deg vertical"
        return (
            f"mode        {self.mode.value}\n"
            f"eye (mm)    x={eye.x:+7.1f}  y={eye.y:+7.1f}  z={eye.z:7.1f}\n"
            f"film (mm)   {p.film_width:.0f} x {p.film_height:.0f}\n"
            f"offset (mm) {p.film_offset_x:+.1f}, {p.film_offset_y:+.1f}\n"
            f"focal (mm)  {p.focal_length:.1f}\n"
            f"lens        {fov_text}"
        )


def build_table_scenery(
    calibration: TableCalibration,
    grid_spacing_mm: float = 50.0,
    include_surface: bool = True,
    include_grid: bool = True,
) -> dict[str, Entity]:
    """The physical reference scenery: the glass plane and its boundary.

    The corner markers matter more than they look. They sit exactly on the
    four corners of the display's lit area, so they are the visible test of
    the projection invariant: if the off-axis maths is right they stay
    welded to the corners of the viewport however the eye moves, and if it
    is wrong they visibly drift inward or outward. That turns a subtle
    geometry bug into something you can see without instrumentation.
    """
    rect = calibration.display_rect
    entities: dict[str, Entity] = {}

    # The translucent surface and the dense grid are *calibration aids*.
    # They are drawn at the glass plane, so over a deep scene they sit on
    # top of everything and wash it out badly. Scenes that need to be judged
    # on their own contrast (the sky view) switch them off and keep only the
    # boundary and corner markers, which carry the projection invariant.
    if include_surface:
        # Glass surface, very slightly below z=0 so coplanar content drawn at
        # exactly 0 does not z-fight with it.
        entities["surface"] = Entity(
            model="quad",
            scale=(mm_to_world(rect.width_mm), mm_to_world(rect.height_mm)),
            position=Vec3(*table_to_world(0.0, 0.0, -0.4)),
            rotation=(90, 0, 0),
            # Very low alpha on purpose. This quad only marks where the
            # z=0 plane is; the grid already carries scale. At high alpha
            # it is composited over every recessed solid and washes the
            # depth cues out until they read as flat outlines.
            color=color.rgba32(40, 70, 95, 45),
            double_sided=True,
        )

    # A millimetre-accurate grid, so depth and scale are judged against
    # known distances rather than vibes.
    grid_lines: list[Vec3] = []
    x = -rect.half_width_mm
    while x <= rect.half_width_mm + 1e-6:
        grid_lines.append(Vec3(*table_to_world(x, -rect.half_height_mm, 0.0)))
        grid_lines.append(Vec3(*table_to_world(x, rect.half_height_mm, 0.0)))
        x += grid_spacing_mm
    y = -rect.half_height_mm
    while y <= rect.half_height_mm + 1e-6:
        grid_lines.append(Vec3(*table_to_world(-rect.half_width_mm, y, 0.0)))
        grid_lines.append(Vec3(*table_to_world(rect.half_width_mm, y, 0.0)))
        y += grid_spacing_mm

    # Ursina maps mode="line" to Panda's GeomLinestrips, which joins every
    # vertex into one continuous path. The grid is a set of *disjoint*
    # segments, so without explicit index pairs the end of each line gets
    # connected to the start of the next and the grid is criss-crossed by
    # spurious diagonals.
    grid_segments = tuple(
        (i, i + 1) for i in range(0, len(grid_lines) - 1, 2)
    )
    if include_grid:
        entities["grid"] = Entity(
            model=Mesh(
                vertices=grid_lines,
                triangles=grid_segments,
                mode="line",
                thickness=1,
            ),
            color=color.rgba32(120, 190, 235, 70),
        )

    # Boundary of the lit area. This one genuinely is a single closed path,
    # so a line strip is the right primitive and needs no index pairs.
    corners = [table_to_world(cx, cy, 0.0) for cx, cy in rect.corners_mm()]
    outline = [Vec3(*corners[i % 4]) for i in range(5)]
    entities["boundary"] = Entity(
        model=Mesh(vertices=outline, mode="line", thickness=3),
        color=color.rgba32(255, 210, 120, 220),
    )

    # Corner markers: the visible proof of the projection invariant.
    for index, (cx, cy) in enumerate(rect.corners_mm()):
        entities[f"corner_{index}"] = Entity(
            model="sphere",
            scale=mm_to_world(14.0),
            position=Vec3(*table_to_world(cx, cy, 0.0)),
            color=color.rgba32(255, 170, 60, 255),
        )

    return entities
