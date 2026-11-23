"""Sky view: the glass as a window onto a world far below.

    python -m tabletop.apps.sky_demo

The mental model is that the player's eye is high in the sky and the display
shows the ground seen from up there. The projection needed for that is
already the off-axis frustum used everywhere else in this project -- it
treats the glass as a window with the world behind it, so looking down
through it *is* looking down from altitude. Nothing about the optics changes
here.

What makes it *feel* like altitude is scale and atmosphere, not projection:

1. **World scale.** ``MM_PER_VIRTUAL_METRE`` fixes how much of the virtual
   world one millimetre of table covers. This is the main altitude dial.
2. **Content depth.** How far below the glass the ground sits.
3. **Aerial perspective.** Haze with depth (``fog_amount`` on
   :data:`~tabletop.render.shaders.LIT_120`), plus vertical structures whose
   convergence the eye reads as height.

The constraint worth understanding
----------------------------------
A physically honest window only reveals a *cone* of what lies behind it. Put
a landscape ten real metres below the glass and you see a tiny patch of it,
as though peering through a skylight -- and almost all of it falls outside
the frustum. So a convincing sky view is a **scaled miniature world sitting
fairly close to the glass**, not geometry pushed physically far away.

Concretely: the towers below are a few hundred millimetres down, but at
``MM_PER_VIRTUAL_METRE = 4`` they represent structures tens of virtual
metres tall, seen from a virtual altitude of roughly::

    eye_height_mm / MM_PER_VIRTUAL_METRE  ->  700 / 4  ~=  175 virtual metres

Keeping the optics true to the real eye position while scaling the world is
what preserves the window illusion. Faking the optics to force a wider view
is what breaks it.

Controls
--------
``mouse``      move the simulated head
``Q`` / ``E``  lower / raise eye height
``F``          cycle fog amount (off / subtle / strong)
``G``          cycle ground depth (shallow / mid / deep)
``H``          freeze head motion
``ESC``        quit
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

# Must precede the Ursina import -- see tabletop.render.platform_setup.
from tabletop.render import platform_setup
from ursina import (
    Entity,
    Text,
    Ursina,
    Vec2,
    Vec3,
    camera,
    clamp,
    color,
    held_keys,
    time,
    mouse,
    window,
)

from tabletop.core.calibration import TableCalibration
from tabletop.render.mapping import mm_to_world, table_to_world
from tabletop.render.projection import Eye, ProjectionMode
from tabletop.render.shaders import LIT_120, install_project_shaders
from tabletop.render.table_app import TableRig, build_table_scenery

MM_PER_VIRTUAL_METRE = 4.0
"""Table millimetres per virtual metre. The primary altitude dial: lower it
and the same physical depth represents a larger, further-away world."""

GROUND_DEPTHS_MM = [-250.0, -600.0, -1100.0]
FOG_AMOUNTS = [0.0, 0.55, 0.9]

EYE_HEIGHT_DEFAULT_MM = 700.0
EYE_HEIGHT_MIN_MM = 250.0
EYE_HEIGHT_MAX_MM = 2000.0
HEAD_SWING_X_MM = 600.0
HEAD_SWING_Y_MM = 400.0


def box_mesh_entity(
    x_mm: float,
    y_mm: float,
    top_z_mm: float,
    bottom_z_mm: float,
    half_mm: float,
    shade: float,
) -> Entity:
    """A vertical column between two depths.

    Columns rather than flat tiles on purpose: their vertical edges converge
    under perspective, and that convergence is what the eye reads as looking
    *down* at something with height, rather than at a flat picture.
    """
    height_mm = top_z_mm - bottom_z_mm
    centre_z = (top_z_mm + bottom_z_mm) / 2.0
    return Entity(
        model="cube",
        position=Vec3(*table_to_world(x_mm, y_mm, centre_z)),
        scale=(mm_to_world(half_mm * 2), mm_to_world(height_mm), mm_to_world(half_mm * 2)),
        color=color.rgb32(
            min(255, int(95 * shade)),
            min(255, int(135 * shade)),
            min(255, int(180 * shade)),
        ),
        shader=LIT_120,
    )


class SkyDemo(Entity):
    def __init__(self, calibration: TableCalibration) -> None:
        super().__init__()
        self.calibration = calibration
        self.eye_height_mm = EYE_HEIGHT_DEFAULT_MM
        self.head_motion = True
        self._frozen_eye = Eye(0.0, 0.0, EYE_HEIGHT_DEFAULT_MM)
        self.fog_index = 1
        self.ground_index = 1

        self.rig = TableRig(
            calibration,
            mode=ProjectionMode.OFF_AXIS_HEAD_TRACKED,
            fixed_eye_height_mm=self.eye_height_mm,
        )
        # Keep only the boundary + corner markers: the translucent glass quad
        # and the dense grid would be drawn over the whole deep world.
        self.scenery = build_table_scenery(
            calibration, include_surface=False, include_grid=False
        )
        self.towers: list[Entity] = []
        self.ground: Entity | None = None
        self._build_world()
        self._apply_fog()

        self.hud = Text(
            text="", origin=(-0.5, 0.5),
            position=window.top_left + Vec2(0.02, -0.02),
            scale=0.75, background=True,
        )
        Text(
            text="[mouse] head  [Q/E] eye height  [F] fog  [G] ground depth  "
                 "[H] freeze  [ESC] quit",
            origin=(0, -0.5), position=Vec2(0, -0.47), scale=0.7, background=True,
        )

    # -- world ----------------------------------------------------------

    @property
    def ground_depth_mm(self) -> float:
        return GROUND_DEPTHS_MM[self.ground_index]

    def _build_world(self) -> None:
        for t in self.towers:
            t.disable()
        self.towers.clear()
        if self.ground is not None:
            self.ground.disable()

        rect = self.calibration.display_rect
        depth = self.ground_depth_mm

        # Size the world to the viewing cone, not to the display.
        #
        # A window of half-width W/2, seen from height h, widens to
        # (W/2) * (h + d) / h at depth d below the glass. Anything smaller
        # than that leaves the edge of the ground plane -- and the void
        # beyond it -- inside the frustum, which is immediately visible in
        # deep or oblique views. The worst case is the lowest eye height and
        # the largest head offset, so both are used here.
        cone = (abs(depth) + EYE_HEIGHT_MIN_MM) / EYE_HEIGHT_MIN_MM
        ground_half_w = rect.half_width_mm * cone + HEAD_SWING_X_MM
        ground_half_h = rect.half_height_mm * cone + HEAD_SWING_Y_MM

        # The ground far below, as a flat plane at the bottom of the world.
        self.ground = Entity(
            model="quad",
            scale=(mm_to_world(ground_half_w * 2), mm_to_world(ground_half_h * 2)),
            position=Vec3(*table_to_world(0.0, 0.0, depth)),
            rotation=(90, 0, 0),
            color=color.rgb32(18, 24, 34),
            shader=LIT_120,
            double_sided=True,
        )

        # A grid of towers of varied height rising from the ground toward
        # the glass. Deterministic layout so runs are comparable.
        # Spread towers across the same cone as the ground, so leaning to
        # one side reveals more city rather than bare ground.
        tower_span_x = min(ground_half_w, rect.half_width_mm * 2.6) * 2
        tower_span_y = min(ground_half_h, rect.half_height_mm * 2.6) * 2
        across = max(7, int(tower_span_x / 130))
        along = max(5, int(tower_span_y / 130))
        for ix in range(across):
            for iy in range(along):
                u = (ix + 0.5) / across
                v = (iy + 0.5) / along
                x_mm = -tower_span_x / 2 + u * tower_span_x
                y_mm = -tower_span_y / 2 + v * tower_span_y

                # Smooth pseudo-random heights, stable across runs.
                wave = (
                    math.sin(ix * 1.7 + iy * 0.9)
                    + math.sin(ix * 0.5 - iy * 2.1)
                ) * 0.5
                fraction = 0.25 + 0.6 * (wave + 1.0) / 2.0
                top_z = depth + abs(depth) * fraction

                self.towers.append(
                    box_mesh_entity(
                        x_mm, y_mm,
                        top_z_mm=min(top_z, -10.0),
                        bottom_z_mm=depth,
                        half_mm=26.0,
                        shade=0.75 + 0.5 * fraction,
                    )
                )

    def _apply_fog(self) -> None:
        amount = FOG_AMOUNTS[self.fog_index]
        for entity in [*self.towers, self.ground]:
            if entity is not None:
                entity.set_shader_input("fog_amount", amount)

    # -- per-frame ------------------------------------------------------

    def current_eye(self) -> Eye:
        if not self.head_motion:
            return self._frozen_eye
        aspect = window.aspect_ratio or 1.0
        return Eye(
            x=clamp(mouse.x / (0.5 * aspect), -1.0, 1.0) * HEAD_SWING_X_MM,
            y=clamp(mouse.y / 0.5, -1.0, 1.0) * HEAD_SWING_Y_MM,
            z=self.eye_height_mm,
        )

    def update(self) -> None:
        if held_keys["q"]:
            self.eye_height_mm = clamp(
                self.eye_height_mm - 400.0 * time.dt,
                EYE_HEIGHT_MIN_MM, EYE_HEIGHT_MAX_MM,
            )
        if held_keys["e"]:
            self.eye_height_mm = clamp(
                self.eye_height_mm + 400.0 * time.dt,
                EYE_HEIGHT_MIN_MM, EYE_HEIGHT_MAX_MM,
            )

        self.rig.fixed_eye_height_mm = self.eye_height_mm
        eye = self.current_eye()
        self.rig.apply(eye)

        virtual_altitude = eye.z / MM_PER_VIRTUAL_METRE
        world_depth_m = abs(self.ground_depth_mm) / MM_PER_VIRTUAL_METRE
        self.hud.text = (
            self.rig.status_text(eye)
            + f"\n\nworld scale  1 mm = {1 / MM_PER_VIRTUAL_METRE:.2f} virtual m"
            + f"\nvirtual altitude  ~{virtual_altitude:.0f} m"
            + f"\nground depth  {self.ground_depth_mm:.0f} mm "
              f"(~{world_depth_m:.0f} virtual m below the glass)"
            + f"\nfog  {FOG_AMOUNTS[self.fog_index]:.2f}"
            + ("" if self.head_motion else "\nHEAD FROZEN")
        )

    def input(self, key: str) -> None:
        if key == "f":
            self.fog_index = (self.fog_index + 1) % len(FOG_AMOUNTS)
            self._apply_fog()
        elif key == "g":
            self.ground_index = (self.ground_index + 1) % len(GROUND_DEPTHS_MM)
            self._build_world()
            self._apply_fog()
        elif key == "h":
            if self.head_motion:
                self._frozen_eye = self.current_eye()
            self.head_motion = not self.head_motion


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, default=None)
    args = parser.parse_args()

    calibration = (
        TableCalibration.load(args.calibration)
        if args.calibration
        else TableCalibration.development_default()
    )
    print(calibration.describe())
    for note in platform_setup.PLATFORM_NOTES:
        print(f"note: {note}")

    install_project_shaders()
    app = Ursina(
        title="tabletop sky view",
        icon=platform_setup.window_icon_path(),
        vsync=True,
    )
    window.color = color.rgb32(14, 17, 22)
    camera.orthographic = False

    SkyDemo(calibration)
    app.run()


if __name__ == "__main__":
    main()
