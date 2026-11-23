"""Projection maths for a horizontal display viewed from above.

Pure, scale-free numerics -- no renderer imports, no units baked in. Feed it
consistent numbers (all millimetres, or all world units) and it works.

The point of this module
------------------------
Making a flat tabletop panel look like it has depth is *not* achieved by
moving a camera around and re-aiming it. That produces a scene that swings
when the viewer moves, which reads as "the world is rotating", not "I am
looking through a window".

The window effect requires an **off-axis (sheared) frustum**: the screen
rectangle stays pinned in world space, the eye point moves freely, and the
frustum is sheared so that the four physical screen corners always land
exactly on the four corners of the viewport. The camera never rotates.

That invariant -- corners pin to the viewport edges for *any* eye position --
is the definition of correctness here, and it is what
``tests/test_projection.py`` asserts.

Three modes, one formula
------------------------
:class:`ProjectionMode` offers orthographic, on-axis perspective, and
head-tracked off-axis. The middle one is not a separate code path: it is the
off-axis case with the eye pinned to ``(0, 0, h)``. Worth knowing, because
it means the "narrow-FOV top-down perspective" look is just the degenerate
on-axis instance of the general solution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

__all__ = [
    "ProjectionMode",
    "Eye",
    "LensParams",
    "off_axis_frustum",
    "lens_params_for",
    "project_point",
    "fit_film_to_viewport",
    "effective_vertical_fov_deg",
    "screen_ndc_to_glass_mm",
    "lens_eye",
    "glass_mm_to_plane_mm",
    "plane_mm_to_glass_mm",
]


class ProjectionMode(str, Enum):
    ORTHOGRAPHIC = "orthographic"
    """Parallel projection. No perspective depth at all: an extruded shape's
    side walls are invisible and a shape at z=-50 looks identical to one at
    z=0. Depth must come entirely from shading, shadows and occlusion.
    Reads the same from every direction, which is why a flat board uses
    it."""

    PERSPECTIVE_FIXED = "perspective_fixed"
    """On-axis perspective from a fixed point above the table centre.
    Recessed geometry reads as recessed, but only a viewer directly above
    the centre sees it undistorted."""

    OFF_AXIS_HEAD_TRACKED = "off_axis_head_tracked"
    """Sheared frustum driven by a tracked eye position. The window
    effect. Geometrically correct for exactly one viewer at a time."""


@dataclass(frozen=True)
class Eye:
    """An eye position relative to the screen centre, on the screen's axes.

    ``z`` is the perpendicular distance in front of the screen and must be
    positive -- an eye at or behind the screen plane has no valid frustum.
    """

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if self.z <= 0:
            raise ValueError(
                f"eye must be in front of the screen plane (z > 0), got z={self.z}"
            )


@dataclass(frozen=True)
class LensParams:
    """Panda3D lens settings equivalent to an off-axis frustum.

    Panda expresses a sheared frustum as film size + film offset + focal
    length rather than as left/right/bottom/top planes. The mapping, with
    the eye at ``(ex, ey, ez)`` relative to a ``w x h`` screen, is:

    * ``film_size   = (w, h)``   -- the screen rectangle, in world units
    * ``focal_length = ez``      -- eye distance to the screen plane
    * ``film_offset = (-ex, -ey)``

    The offset signs were established empirically against Panda's
    ``Lens.project``: a film offset of ``+a`` makes the camera-space point
    at ``+a`` project to the viewport centre, so cancelling an eye shift of
    ``+ex`` requires an offset of ``-ex``.
    """

    film_width: float
    film_height: float
    film_offset_x: float
    film_offset_y: float
    focal_length: float
    orthographic: bool

    def as_dict(self) -> dict[str, float | bool]:
        return {
            "film_width": self.film_width,
            "film_height": self.film_height,
            "film_offset_x": self.film_offset_x,
            "film_offset_y": self.film_offset_y,
            "focal_length": self.focal_length,
            "orthographic": self.orthographic,
        }


def off_axis_frustum(
    eye: Eye,
    screen_width: float,
    screen_height: float,
    near: float,
    far: float,
) -> np.ndarray:
    """Build an OpenGL-convention off-axis projection matrix.

    Reference implementation, used by the tests to pin down the invariant
    independently of Panda3D. The renderer itself goes through
    :func:`lens_params_for`, since Panda wants film/offset/focal rather than
    a raw matrix.

    Eye space is the conventional GL one: origin at the eye, ``+x`` right,
    ``+y`` up (table ``+Y``), looking down ``-z`` at the screen plane, which
    therefore sits at ``z = -eye.z``.

    Returns a 4x4 matrix for column vectors (``M @ v``).
    """
    if not (0 < near < far):
        raise ValueError(f"require 0 < near < far, got near={near} far={far}")

    scale = near / eye.z
    left = (-screen_width / 2.0 - eye.x) * scale
    right = (screen_width / 2.0 - eye.x) * scale
    bottom = (-screen_height / 2.0 - eye.y) * scale
    top = (screen_height / 2.0 - eye.y) * scale

    return _frustum(left, right, bottom, top, near, far)


def _frustum(
    left: float, right: float, bottom: float, top: float, near: float, far: float
) -> np.ndarray:
    rl = right - left
    tb = top - bottom
    fn = far - near
    return np.array(
        [
            [2.0 * near / rl, 0.0, (right + left) / rl, 0.0],
            [0.0, 2.0 * near / tb, (top + bottom) / tb, 0.0],
            [0.0, 0.0, -(far + near) / fn, -2.0 * far * near / fn],
            [0.0, 0.0, -1.0, 0.0],
        ],
        dtype=float,
    )


def project_point(
    matrix: np.ndarray, point_world: tuple[float, float, float], eye: Eye
) -> tuple[float, float, float]:
    """Project a point on the table through ``matrix`` into NDC.

    ``point_world`` is in screen-centred coordinates on the table's axes:
    ``(x right, y away from the home edge, z up out of the glass)``. The
    eye-space conversion mirrors :func:`off_axis_frustum`: translate by the
    eye, then flip Z so that "up out of the glass" becomes "toward the
    viewer", i.e. ``-z`` in GL eye space.
    """
    x, y, z = point_world
    eye_space = np.array([x - eye.x, y - eye.y, z - eye.z, 1.0], dtype=float)
    clip = matrix @ eye_space
    if clip[3] == 0:
        raise ValueError(f"point {point_world} projects to w=0 (on the eye plane)")
    return (clip[0] / clip[3], clip[1] / clip[3], clip[2] / clip[3])


def fit_film_to_viewport(
    screen_width: float, screen_height: float, viewport_aspect: float
) -> tuple[float, float]:
    """Grow the film so the physical screen rectangle is *inscribed* in it.

    On the real table the window aspect equals the panel aspect and this is
    a no-op. On a development machine the window is an arbitrary shape, and
    something has to give. The options are to stretch the table to the
    window (which silently falsifies the geometry the whole depth illusion
    depends on), or to keep the table's true proportions and letterbox.

    This does the latter: the returned film is the smallest rectangle with
    the viewport's aspect that still contains the screen rectangle. The
    table keeps its real millimetre dimensions everywhere -- one coordinate
    system, no dev-only fork -- and the cost is visible bars on a mismatched
    window, which is a far better failure mode than a subtly wrong frustum.
    """
    if viewport_aspect <= 0:
        raise ValueError(f"viewport aspect must be positive, got {viewport_aspect}")

    screen_aspect = screen_width / screen_height
    if viewport_aspect > screen_aspect:
        # Window is wider than the table: fit height, bars left and right.
        return (screen_height * viewport_aspect, screen_height)
    # Window is taller than the table: fit width, bars top and bottom.
    return (screen_width, screen_width / viewport_aspect)


def lens_params_for(
    mode: ProjectionMode,
    screen_width: float,
    screen_height: float,
    eye: Eye,
    fixed_eye_height: float | None = None,
    viewport_aspect: float | None = None,
) -> LensParams:
    """Lens settings for a projection mode.

    ``eye`` is the tracked eye position, used only by
    :attr:`ProjectionMode.OFF_AXIS_HEAD_TRACKED`. The other two modes ignore
    its lateral components on purpose, so the caller can feed live tracking
    data in every mode and switch between them without touching the camera
    rig -- which is exactly what the depth demo does when comparing them.

    ``fixed_eye_height`` overrides the viewing distance for the non-tracked
    modes; it defaults to the tracked eye's height so a mode switch does not
    also change the apparent zoom.

    ``viewport_aspect`` letterboxes the screen rectangle into a window of a
    different shape (see :func:`fit_film_to_viewport`). Leave it ``None`` on
    a window that matches the screen's own proportions.
    """
    height = fixed_eye_height if fixed_eye_height is not None else eye.z

    if viewport_aspect is None:
        film_w, film_h = screen_width, screen_height
    else:
        film_w, film_h = fit_film_to_viewport(
            screen_width, screen_height, viewport_aspect
        )

    if mode is ProjectionMode.ORTHOGRAPHIC:
        # Film size is the screen rectangle, so the board fills the viewport
        # 1:1. Focal length is irrelevant to an orthographic lens but is
        # carried so the camera rig can still be positioned sensibly.
        return LensParams(
            film_width=film_w,
            film_height=film_h,
            film_offset_x=0.0,
            film_offset_y=0.0,
            focal_length=height,
            orthographic=True,
        )

    if mode is ProjectionMode.PERSPECTIVE_FIXED:
        return LensParams(
            film_width=film_w,
            film_height=film_h,
            film_offset_x=0.0,
            film_offset_y=0.0,
            focal_length=height,
            orthographic=False,
        )

    if mode is ProjectionMode.OFF_AXIS_HEAD_TRACKED:
        return LensParams(
            film_width=film_w,
            film_height=film_h,
            film_offset_x=-eye.x,
            film_offset_y=-eye.y,
            focal_length=eye.z,
            orthographic=False,
        )

    raise ValueError(f"unhandled projection mode: {mode!r}")


def lens_eye(
    mode: ProjectionMode, head: Eye, fixed_eye_height_mm: float
) -> Eye:
    """The eye the lens actually projects from.

    Only the head-tracked mode projects from the tracked head. The fixed
    modes project from a point above the table centre, however far the
    viewer has walked around it, so anything that reasons about *apparent*
    position -- where content drawn above the glass will look like it is --
    has to use this rather than the head.

    Getting that wrong is not a small error. The pointer's mallet was
    corrected toward the head while the lens projected from the centre, so
    the mallet was drawn well short of the hand and, near the home edge,
    appeared over the surrounding panel instead of on the playfield.
    """
    if mode is ProjectionMode.OFF_AXIS_HEAD_TRACKED:
        return head
    return Eye(0.0, 0.0, fixed_eye_height_mm)


def screen_ndc_to_glass_mm(
    ndc_x: float, ndc_y: float, params: LensParams
) -> tuple[float, float]:
    """Invert the projection for points on the glass plane (``z = 0``).

    Pleasingly, this is the same formula in all three projection modes and
    is independent of where the eye is. The glass plane is parallel to the
    image plane, so its projection is affine; and in the off-axis case the
    film offset exactly cancels the eye offset for points on that plane::

        ndc_x = (x - eye_x - film_offset_x) * 2/film_w * (focal/eye_z)
              = (x - eye_x + eye_x) * 2/film_w          [offset = -eye_x,
              = 2x / film_w                              focal = eye_z]

    Which is why a touch can be mapped to table coordinates without knowing
    the head position -- the thing you would otherwise have to feed back
    into input handling, and a likely source of head-tracking-dependent
    touch offsets if it were not true.
    """
    return (ndc_x * params.film_width / 2.0, ndc_y * params.film_height / 2.0)


def effective_vertical_fov_deg(params: LensParams) -> float:
    """Vertical field of view implied by a perspective lens, for display.

    Handy for the on-screen readout: it connects these physical film/focal
    numbers back to the FOV figure the design notes talk about, so you can
    see that a 43-inch panel viewed from ~700 mm really is a ~40 degree lens
    rather than guessing a number that "looks tabletop".
    """
    if params.orthographic:
        return 0.0
    return float(
        2.0 * np.degrees(np.arctan2(params.film_height / 2.0, params.focal_length))
    )


def plane_mm_to_glass_mm(
    x_mm: float, y_mm: float, z_mm: float, eye: Eye
) -> tuple[float, float]:
    """Where a point above the glass *appears* to be, on the glass plane.

    Content drawn at height ``z_mm`` is seen along the ray from the eye, so
    it appears displaced away from the eye's axis by ``eye.z / (eye.z -
    z_mm)``. This is the same parallax displacement that offsets a risen
    mole from its hole.
    """
    if eye.z <= z_mm:
        raise ValueError(
            f"eye at {eye.z} mm is not above a plane at {z_mm} mm"
        )
    scale = eye.z / (eye.z - z_mm)
    return (
        eye.x + (x_mm - eye.x) * scale,
        eye.y + (y_mm - eye.y) * scale,
    )


def glass_mm_to_plane_mm(
    glass_x_mm: float, glass_y_mm: float, z_mm: float, eye: Eye
) -> tuple[float, float]:
    """Inverse of :func:`plane_mm_to_glass_mm`.

    What a tap means for content that is not on the glass. A touch is
    reported on the glass plane, so hit-testing anything drawn above it --
    a menu panel, say -- against its own coordinates is wrong by exactly
    this factor, and the error grows with distance from the eye's axis: the
    rows nearest the edge of a panel become the hardest to hit.
    """
    if eye.z <= z_mm:
        raise ValueError(
            f"eye at {eye.z} mm is not above a plane at {z_mm} mm"
        )
    shrink = (eye.z - z_mm) / eye.z
    return (
        eye.x + (glass_x_mm - eye.x) * shrink,
        eye.y + (glass_y_mm - eye.y) * shrink,
    )
