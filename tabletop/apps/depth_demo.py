"""Depth-perception comparison on a flat panel.

    python -m tabletop.apps.depth_demo

Answers the question the hardware cannot yet answer: does recessed-into-the-
glass depth actually read convincingly on a flat display, and how much does
head-tracked off-axis projection add over a plain top-down view?

Three modes on one key, so the comparison is direct:

* **orthographic** -- parallel projection. The pyramid's side walls vanish
  entirely; all depth comes from shading and occlusion.
* **perspective_fixed** -- on-axis perspective from above the centre. Side
  walls converge, recessed geometry reads as recessed, but only for a viewer
  directly overhead.
* **off_axis_head_tracked** -- sheared frustum following the tracked eye.
  Move the mouse (standing in for a moving viewer) and the scene parallaxes
  as though you were looking through a window.

The main solid is a square-based pyramid with its apex at the glass
pointing at the viewer and its broad base recessed, so it tapers away
along Z.

The scene deliberately contains geometry both *below* the glass (that
pyramid) and *above* it (a floating token). They parallax in opposite
directions, which is the strongest available cue that the projection is
geometrically right rather than merely moving.

Controls
--------
``SPACE``        cycle projection mode
``mouse``        move the simulated head position
``W`` / ``S``    make the pyramid shallower / deeper
``T``            flip the taper (tip at you / funnel receding away)
``G``            cycle the depth gradient (flat / medium / strong)
``Q`` / ``E``    lower / raise the simulated eye height
``H``            toggle head motion (freeze the eye to inspect one view)
``R``            reset
``ESC``          quit
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Must precede the Ursina import -- see tabletop.render.platform_setup.
from tabletop.render import platform_setup
from ursina import (
    Entity,
    Mesh,
    Text,
    Ursina,
    Vec2,
    Vec3,
    camera,
    clamp,
    color,
    held_keys,
    mouse,
    time,
    window,
)

from tabletop.core.calibration import TableCalibration
from tabletop.render.mapping import mm_to_world, table_to_world
from tabletop.render.meshes import extruded_polygon_mesh, tapered_pyramid_mesh
from tabletop.render.projection import Eye, ProjectionMode
from tabletop.render.shaders import LIT_120, install_project_shaders
from tabletop.render.table_app import TableRig, build_table_scenery

MODES = [
    ProjectionMode.ORTHOGRAPHIC,
    ProjectionMode.PERSPECTIVE_FIXED,
    ProjectionMode.OFF_AXIS_HEAD_TRACKED,
]

EYE_HEIGHT_DEFAULT_MM = 700.0
EYE_HEIGHT_MIN_MM = 250.0
EYE_HEIGHT_MAX_MM = 2000.0

HEAD_SWING_X_MM = 600.0
"""How far the simulated head travels laterally at full mouse deflection.
Roughly what a viewer's head covers when leaning across the table."""
HEAD_SWING_Y_MM = 400.0

DEPTH_GRADIENT_AMOUNTS = [0.0, 0.45, 0.75]
"""Strength of the depth-keyed darkening, cycled with ``G``.

0.0 is flat per-face shading only, which is the regime where the apex
visually collapses into the base. The higher settings fade geometry toward
the background as it recedes, so the tip reads as nearest."""

PRISM_DEPTH_MIN_MM = -220.0
PRISM_DEPTH_MAX_MM = 0.0
WELL_DEPTH_MM = 200.0


class DepthDemo(Entity):
    """Scene controller. Implemented as an Entity so Ursina calls
    ``update``/``input`` regardless of how the module is launched."""

    def __init__(self, calibration: TableCalibration) -> None:
        super().__init__()
        self.calibration = calibration
        self.mode_index = len(MODES) - 1  # start on the interesting one
        self.eye_height_mm = EYE_HEIGHT_DEFAULT_MM
        self.prism_depth_mm = -120.0
        # True  = apex at the glass, broad base deep   (tip points at you)
        # False = broad base at the glass, apex deep   (funnel receding away)
        self.tip_toward_viewer = True
        # Depth gradient strength. Flat per-face shading gives each facet a
        # single uniform tone, so from straight overhead the apex has nothing
        # to distinguish it from the base and the solid collapses into a flat
        # square with diagonals. A per-pixel gradient keyed to depth is what
        # separates near from far along every facet.
        self.gradient_index = 1
        self.head_motion = True
        self._frozen_eye = Eye(0.0, 0.0, EYE_HEIGHT_DEFAULT_MM)

        self.rig = TableRig(
            calibration,
            mode=MODES[self.mode_index],
            fixed_eye_height_mm=self.eye_height_mm,
        )

        self.scenery = build_table_scenery(calibration)
        self._build_content()
        self._apply_depth_gradient()
        self._build_hud()

    # -- scene ----------------------------------------------------------

    def _build_content(self) -> None:
        rect = self.calibration.display_rect

        # A square-based pyramid pointing *at the viewer*: apex at the
        # glass, broad base recessed into the display. The tip-to-base axis
        # runs along Z rather than across the screen, so the shape tapers
        # away from the player instead of lying flat.
        #
        # Square base, not triangular: a pyramid is any polygon base plus an
        # apex, but the everyday meaning of the word is the 4-sided Giza
        # form. A triangular base would be a tetrahedron, and from straight
        # overhead its 3 radiating faces read ambiguously -- 4-fold symmetry
        # about the centre apex is much easier to see as a peak.
        base_half = min(rect.half_width_mm * 0.30, rect.half_height_mm * 0.52)
        self._pyramid_base = [
            (-base_half, -base_half),
            (base_half, -base_half),
            (base_half, base_half),
            (-base_half, base_half),
        ]
        # Apex over the base centroid, so the taper is symmetric and the
        # shape does not appear to lean when the head is centred.
        count = len(self._pyramid_base)
        self._pyramid_apex = (
            sum(p[0] for p in self._pyramid_base) / count,
            sum(p[1] for p in self._pyramid_base) / count,
        )
        self.prism = Entity(
            model=self._pyramid_model(),
            color=color.rgb32(120, 195, 255),
            shader=LIT_120,
            # Normals are explicitly outward (see _face_normal), so drawing
            # both sides is safe and means no face can be lost to a winding
            # mistake in the mesh builder.
            double_sided=True,
        )

        # A square well sunk deeper still, to judge how far content can
        # recede before text and pieces inside it become unreadable.
        well_half = 90.0
        self.well = Entity(
            model=extruded_polygon_mesh(
                [
                    (-rect.half_width_mm * 0.62 - well_half, -well_half),
                    (-rect.half_width_mm * 0.62 + well_half, -well_half),
                    (-rect.half_width_mm * 0.62 + well_half, well_half),
                    (-rect.half_width_mm * 0.62 - well_half, well_half),
                ],
                0.0,
                -WELL_DEPTH_MM,
            ),
            color=color.rgb32(185, 120, 220),
            shader=LIT_120,
            double_sided=True,
        )

        # A token standing proud of the glass. Parallaxes opposite to the
        # recessed geometry, which is the clearest signal the frustum shear
        # is correct rather than merely animated.
        self.token = Entity(
            model="cube",
            scale=(mm_to_world(70), mm_to_world(70), mm_to_world(70)),
            position=Vec3(*table_to_world(rect.half_width_mm * 0.60, 0.0, 35.0)),
            color=color.rgb32(235, 190, 90),
            shader=LIT_120,
        )

        # No DirectionalLight: LIT_120 carries its own light direction as a
        # shader input, which keeps lighting identical on macOS and Linux
        # instead of depending on Panda's light plumbing and the GLSL
        # version available on each.

    def _build_hud(self) -> None:
        self.hud = Text(
            text="",
            origin=(-0.5, 0.5),
            position=window.top_left + Vec2(0.02, -0.02),
            scale=0.75,
            background=True,
        )
        self.help = Text(
            text=(
                "[SPACE] mode  [mouse] head  [W/S] depth  [T] flip taper  "
                "[G] depth gradient  [Q/E] eye height  [H] freeze  [R] reset"
                "[Q/E] eye height   [H] freeze head   [R] reset   [ESC] quit"
            ),
            origin=(0, -0.5),
            position=Vec2(0, -0.47),
            scale=0.7,
            background=True,
        )

    # -- per-frame ------------------------------------------------------

    def current_eye(self) -> Eye:
        """The simulated eye position, in table millimetres.

        The mouse stands in for a tracked head.
        Ursina reports ``mouse.x`` in +-0.5*aspect and ``mouse.y`` in +-0.5,
        so each is normalised to +-1 first. Without that the horizontal
        swing would scale with window shape and the HEAD_SWING constants
        would not mean the millimetres they claim.
        """
        if not self.head_motion:
            return self._frozen_eye

        aspect = window.aspect_ratio or 1.0
        unit_x = clamp(mouse.x / (0.5 * aspect), -1.0, 1.0)
        unit_y = clamp(mouse.y / 0.5, -1.0, 1.0)

        return Eye(
            x=unit_x * HEAD_SWING_X_MM,
            y=unit_y * HEAD_SWING_Y_MM,
            z=self.eye_height_mm,
        )

    def update(self) -> None:
        if held_keys["w"]:
            self._set_prism_depth(self.prism_depth_mm + 90.0 * time.dt)
        if held_keys["s"]:
            self._set_prism_depth(self.prism_depth_mm - 90.0 * time.dt)
        if held_keys["q"]:
            self.eye_height_mm = clamp(
                self.eye_height_mm - 400.0 * time.dt,
                EYE_HEIGHT_MIN_MM,
                EYE_HEIGHT_MAX_MM,
            )
        if held_keys["e"]:
            self.eye_height_mm = clamp(
                self.eye_height_mm + 400.0 * time.dt,
                EYE_HEIGHT_MIN_MM,
                EYE_HEIGHT_MAX_MM,
            )

        self.rig.fixed_eye_height_mm = self.eye_height_mm
        eye = self.current_eye()
        self.rig.apply(eye)

        self.hud.text = (
            self.rig.status_text(eye)
            + f"\npyramid depth {self.prism_depth_mm:+.0f} mm  "
            + ("tip toward viewer" if self.tip_toward_viewer else "funnel receding away")
            + f"\ndepth gradient {DEPTH_GRADIENT_AMOUNTS[self.gradient_index]:.2f}"
            + ("" if self.head_motion else "\nHEAD FROZEN")
            + "\n\nthe 4 orange dots sit on the display corners:"
            + "\nthey must stay welded to the viewport corners"
        )

    def _pyramid_model(self) -> Mesh:
        """Build the pyramid for the current taper direction.

        Both orientations keep one end exactly on the glass plane and push
        the other to ``prism_depth_mm``; only which end is the point
        changes. Whether a tip aimed at the viewer or a funnel receding from
        the viewer reads as deeper is a perceptual question, not a
        geometric one, so the demo offers both rather than assuming.
        """
        if self.tip_toward_viewer:
            return tapered_pyramid_mesh(
                self._pyramid_base, self._pyramid_apex,
                apex_z_mm=0.0, base_z_mm=self.prism_depth_mm,
            )
        return tapered_pyramid_mesh(
            self._pyramid_base, self._pyramid_apex,
            apex_z_mm=self.prism_depth_mm, base_z_mm=0.0,
        )

    def _rebuild_pyramid(self) -> None:
        self.prism.model = self._pyramid_model()
        self.prism.shader = LIT_120
        self._apply_depth_gradient()

    def _apply_depth_gradient(self) -> None:
        """Key brightness to depth on the recessed solids.

        ``fog_depth`` is set to each solid's own depth rather than a global
        constant, so the gradient always spans exactly that shape. A fixed
        depth would make a shallow pyramid use only a sliver of the ramp and
        look flat again as soon as W/S reduced its depth.
        """
        amount = DEPTH_GRADIENT_AMOUNTS[self.gradient_index]

        prism_span_mm = max(abs(self.prism_depth_mm), 1.0)
        self.prism.set_shader_input("fog_depth", mm_to_world(prism_span_mm))
        self.prism.set_shader_input("fog_amount", amount)

        self.well.set_shader_input("fog_depth", mm_to_world(WELL_DEPTH_MM))
        self.well.set_shader_input("fog_amount", amount)

    def _set_prism_depth(self, depth_mm: float) -> None:
        depth_mm = clamp(depth_mm, PRISM_DEPTH_MIN_MM, PRISM_DEPTH_MAX_MM)
        if abs(depth_mm - self.prism_depth_mm) < 1e-6:
            return
        self.prism_depth_mm = depth_mm
        # Rebuilding the mesh (rather than scaling the entity) keeps the apex
        # pinned exactly to the glass plane while only the base depth moves,
        # so W/S changes how sharply the solid tapers away rather than
        # sliding the whole shape through the glass.
        self._rebuild_pyramid()

    def input(self, key: str) -> None:
        if key == "space":
            self.mode_index = (self.mode_index + 1) % len(MODES)
            self.rig.mode = MODES[self.mode_index]
        elif key == "g":
            self.gradient_index = (self.gradient_index + 1) % len(
                DEPTH_GRADIENT_AMOUNTS
            )
            self._apply_depth_gradient()
        elif key == "t":
            self.tip_toward_viewer = not self.tip_toward_viewer
            self._rebuild_pyramid()
        elif key == "h":
            if self.head_motion:
                self._frozen_eye = self.current_eye()
            self.head_motion = not self.head_motion
        elif key == "r":
            self.mode_index = len(MODES) - 1
            self.rig.mode = MODES[self.mode_index]
            self.eye_height_mm = EYE_HEIGHT_DEFAULT_MM
            self.head_motion = True
            self._set_prism_depth(-120.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--calibration",
        type=Path,
        default=None,
        help="path to a calibration JSON; defaults to the synthetic dev table",
    )
    args = parser.parse_args()

    calibration = (
        TableCalibration.load(args.calibration)
        if args.calibration
        else TableCalibration.development_default()
    )
    print(calibration.describe())
    for note in platform_setup.PLATFORM_NOTES:
        print(f"note: {note}")

    # Before Ursina() builds its own internal entities (UI overlay,
    # editor widgets), so they pick up our GLSL 120 default too.
    # Ursina's default is GLSL 130, which macOS cannot compile at all.
    install_project_shaders()

    app = Ursina(
        title="tabletop depth demo",
        icon=platform_setup.window_icon_path(),
        borderless=False,
        vsync=True,
    )
    window.color = color.rgb32(14, 17, 22)
    camera.orthographic = False

    DepthDemo(calibration)
    app.run()


if __name__ == "__main__":
    main()
