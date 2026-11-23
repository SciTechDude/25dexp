"""Input demo: a touch source, the event snapshots, and the contacts drawn.

    python -m tabletop.apps.touch_demo

Exercises the whole input path with nothing attached but a mouse. The mouse
drives a contact, number keys pin extra stationary ones, and a scripted
sequence replays three fingers in a line. Everything goes through the same
:class:`~tabletop.core.events.SensorFrame` snapshots the game reads, so
swapping in a touchscreen changes only which
:class:`~tabletop.sensors.base.TouchSource` ``main`` builds.

The on-screen log shows the frames as they go past.

Controls
--------
``left mouse``   drag a contact across the glass
``1``-``4``      pin / unpin a stationary contact at a preset position
``P``            play the scripted collinear three-finger sequence
``C``            clear all contacts
``ESC``          quit
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Must precede the Ursina import -- see tabletop.render.platform_setup.
from tabletop.render import platform_setup  # noqa: F401
from ursina import (
    Entity,
    Text,
    Ursina,
    Vec2,
    Vec3,
    color,
    mouse,
    window,
)

from tabletop.core.calibration import TableCalibration
from tabletop.core.events import SensorFrame, TouchPhase, TouchPoint
from tabletop.render.mapping import mm_to_world, table_to_world
from tabletop.render.projection import (
    Eye,
    ProjectionMode,
    screen_ndc_to_glass_mm,
)
from tabletop.render.shaders import install_project_shaders
from tabletop.render.table_app import TableRig, build_table_scenery
from tabletop.sensors.base import TouchSource
from tabletop.sensors.mock import (
    Contact,
    MockTouchSource,
    ScriptedTouchSource,
    collinear_three_finger_script,
)

MARKER_DIAMETER_MM = 26.0
LOG_LINES = 8


class TouchDemo(Entity):
    """Renders whatever the attached touch source reports."""

    def __init__(
        self,
        calibration: TableCalibration,
        source: MockTouchSource,
    ) -> None:
        super().__init__()
        self.calibration = calibration
        self.source = source
        self.scripted: ScriptedTouchSource | None = None
        self.eye = Eye(0.0, 0.0, 900.0)

        self.rig = TableRig(
            calibration,
            mode=ProjectionMode.PERSPECTIVE_FIXED,
            fixed_eye_height_mm=self.eye.z,
        )
        self.scenery = build_table_scenery(calibration)

        self._markers: dict[int, Entity] = {}
        self._labels: dict[int, Text] = {}
        self._log: list[str] = []
        self._pinned: set[str] = set()

        self.hud = Text(
            text="",
            origin=(-0.5, 0.5),
            position=window.top_left + Vec2(0.02, -0.02),
            scale=0.7,
            background=True,
        )
        self.help = Text(
            text=(
                "[drag] move a contact   [1-4] pin contacts   "
                "[P] scripted 3-finger   [C] clear   [ESC] quit"
            ),
            origin=(0, -0.5),
            position=Vec2(0, -0.47),
            scale=0.7,
            background=True,
        )

    # -- input ----------------------------------------------------------

    def mouse_table_mm(self) -> tuple[float, float] | None:
        """Where the mouse is pointing, in table millimetres.

        Uses the analytic inverse rather than Ursina's raycasting, because
        the rig installs a custom lens that Ursina's mouse picking does not
        know about.
        """
        params = self.rig.last_params
        if params is None:
            return None
        # Ursina reports mouse.x in +-0.5*aspect and mouse.y in +-0.5.
        aspect = window.aspect_ratio
        if aspect <= 0:
            return None
        return screen_ndc_to_glass_mm(mouse.x * 2.0 / aspect, mouse.y * 2.0, params)

    def preset_positions(self) -> dict[str, tuple[float, float]]:
        rect = self.calibration.display_rect
        return {
            "1": (-rect.half_width_mm * 0.5, rect.half_height_mm * 0.5),
            "2": (rect.half_width_mm * 0.5, rect.half_height_mm * 0.5),
            "3": (rect.half_width_mm * 0.5, -rect.half_height_mm * 0.5),
            "4": (-rect.half_width_mm * 0.5, -rect.half_height_mm * 0.5),
        }

    def input(self, key: str) -> None:
        presets = self.preset_positions()

        if key in presets:
            if key in self._pinned:
                self._pinned.discard(key)
                self.source.clear_contact(f"pin{key}")
            else:
                self._pinned.add(key)
                x_mm, y_mm = presets[key]
                self.source.set_contact(
                    f"pin{key}",
                    Contact(x_mm=x_mm, y_mm=y_mm, major_mm=14.0, minor_mm=12.0),
                )
        elif key == "c":
            self.source.clear_all()
            self._pinned.clear()
            self.scripted = None
        elif key == "p":
            self.scripted = ScriptedTouchSource(
                self.calibration,
                collinear_three_finger_script(self.calibration),
                loop=True,
            )
            self.scripted.start()
            self._note("scripted collinear 3-finger sequence started")

    # -- per-frame ------------------------------------------------------

    def update(self) -> None:
        self.rig.apply(self.eye)

        if mouse.left:
            pos = self.mouse_table_mm()
            if pos is not None:
                self.source.set_contact(
                    "mouse",
                    Contact(x_mm=pos[0], y_mm=pos[1], major_mm=11.0, minor_mm=10.0),
                )
        else:
            self.source.clear_contact("mouse")

        active_source: TouchSource = self.scripted or self.source
        frame = active_source.poll()
        self._render_frame(frame)
        self._update_hud(frame)

    def _render_frame(self, frame: SensorFrame) -> None:
        live: set[int] = set()

        for touch in frame.touches:
            if touch.phase in (TouchPhase.ENDED, TouchPhase.CANCELLED):
                self._note(
                    f"#{touch.touch_id} {touch.phase.value} "
                    f"at ({touch.x_mm:+.0f}, {touch.y_mm:+.0f})"
                )
                continue

            live.add(touch.touch_id)
            if touch.phase is TouchPhase.BEGAN:
                self._note(
                    f"#{touch.touch_id} began at "
                    f"({touch.x_mm:+.0f}, {touch.y_mm:+.0f}) mm"
                )

            self._place_marker(touch)

        # Retire markers for contacts no longer present.
        for touch_id in list(self._markers):
            if touch_id not in live:
                self._markers.pop(touch_id).disable()
                label = self._labels.pop(touch_id, None)
                if label is not None:
                    label.disable()

    def _place_marker(self, touch: TouchPoint) -> None:
        marker = self._markers.get(touch.touch_id)
        if marker is None:
            marker = Entity(
                model="sphere",
                scale=mm_to_world(MARKER_DIAMETER_MM),
                color=color.rgba32(120, 230, 160, 230),
            )
            self._markers[touch.touch_id] = marker
            self._labels[touch.touch_id] = Text(
                text=str(touch.touch_id),
                scale=0.6,
                origin=(0, 0),
                billboard=True,
            )

        marker.position = Vec3(*table_to_world(touch.x_mm, touch.y_mm, touch.z_mm))
        label = self._labels.get(touch.touch_id)
        if label is not None:
            label.position = Vec3(
                *table_to_world(touch.x_mm, touch.y_mm, touch.z_mm + 30.0)
            )

    def _update_hud(self, frame: SensorFrame) -> None:
        payload = json.dumps(frame.to_dict())
        size_desc = f"{len(payload)} bytes of JSON"

        contacts = "\n".join(
            f"  #{t.touch_id:<3} {t.phase.value:<7} "
            f"({t.x_mm:+7.1f}, {t.y_mm:+7.1f}, {t.z_mm:5.1f}) mm  "
            f"size={'n/a' if t.major_mm is None else f'{t.major_mm:.1f}mm'}"
            for t in frame.touches
        ) or "  (no contacts)"

        log = "\n".join(f"  {line}" for line in self._log[-LOG_LINES:])

        self.hud.text = (
            f"source      {('scripted' if self.scripted else self.source.name)}\n"
            f"frame       seq={frame.seq}  format={frame.format_version}\n"
            f"wire size   {size_desc}\n"
            f"\ncontacts\n{contacts}\n"
            f"\nevents\n{log}"
        )

    def _note(self, message: str) -> None:
        self._log.append(message)
        del self._log[:-50]


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

    # Before Ursina() builds its own internal entities (UI overlay,
    # editor widgets), so they pick up our GLSL 120 default too.
    # Ursina's default is GLSL 130, which macOS cannot compile at all.
    install_project_shaders()

    app = Ursina(
        title="tabletop touch demo",
        icon=platform_setup.window_icon_path(),
        vsync=True,
    )
    window.color = color.rgb32(14, 17, 22)

    # The one line to change for a real touchscreen: construct an
    # EvdevTouchSource(calibration, "/dev/input/eventN") instead.
    source = MockTouchSource(calibration)
    source.start()

    TouchDemo(calibration, source)
    app.run()


if __name__ == "__main__":
    main()
