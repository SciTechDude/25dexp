"""Render the depth demo to PNG files, for verification without eyeballing.

    python -m tabletop.apps.capture --out /tmp/shots

Exists because there was no feedback loop otherwise. On macOS,
``base.win.saveScreenshot()`` returns a blank image, so it silently reports
nothing useful -- early debugging here wasted effort on captures that were
uniformly white regardless of what the scene contained.

What works instead is attaching a render texture to the window with
``RTMCopyRam`` and explicitly asking for the colour bitplane, then storing
that texture to a ``PNMImage``. That performs a real framebuffer-to-RAM copy
and produces the actual pixels.

``--census`` additionally prints the distinct colours in each frame, which
is what makes this checkable by a script rather than by a human: if a
recognised shape colour is absent the render is broken, no matter how the
window happens to look.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Must precede the Ursina import -- see tabletop.render.platform_setup.
from tabletop.render import platform_setup
from panda3d.core import (
    Filename,
    GraphicsOutput,
    LColor,
    PNMImage,
    Texture,
)
from ursina import Ursina, application, color, window

from tabletop.core.calibration import TableCalibration
from tabletop.render.projection import Eye, ProjectionMode
from tabletop.render.shaders import install_project_shaders

GAME_VIEWS: list[tuple[str, ProjectionMode, Eye]] = [
    ("game_1_fixed", ProjectionMode.PERSPECTIVE_FIXED, Eye(0.0, 0.0, 700.0)),
    ("game_2_offaxis_near", ProjectionMode.OFF_AXIS_HEAD_TRACKED, Eye(0.0, -420.0, 520.0)),
    ("game_3_offaxis_left", ProjectionMode.OFF_AXIS_HEAD_TRACKED, Eye(-520.0, 0.0, 620.0)),
    ("game_4_round_over", ProjectionMode.PERSPECTIVE_FIXED, Eye(0.0, 0.0, 700.0)),
]

VIEWS: list[tuple[str, ProjectionMode, Eye]] = [
    ("1_orthographic", ProjectionMode.ORTHOGRAPHIC, Eye(0.0, 0.0, 700.0)),
    ("2_perspective", ProjectionMode.PERSPECTIVE_FIXED, Eye(0.0, 0.0, 700.0)),
    ("3_offaxis_centre", ProjectionMode.OFF_AXIS_HEAD_TRACKED, Eye(0.0, 0.0, 700.0)),
    ("4_offaxis_left", ProjectionMode.OFF_AXIS_HEAD_TRACKED, Eye(-520.0, 0.0, 650.0)),
    ("5_offaxis_right", ProjectionMode.OFF_AXIS_HEAD_TRACKED, Eye(520.0, 0.0, 650.0)),
    ("6_offaxis_near_low", ProjectionMode.OFF_AXIS_HEAD_TRACKED, Eye(0.0, -380.0, 430.0)),
]

SETTLE_FRAMES = 45
"""Frames to run before capturing.

Generous on purpose. Shader compilation, the first framebuffer copy and
**texture upload** all lag the first frames: capturing after only 5-8 steps
produced images where a bright grass texture came out dark olive, which
looks exactly like a lighting or tint bug and is not one."""


def attach_capture_texture() -> Texture:
    """Attach a RAM-copy colour render texture to the main window."""
    tex = Texture()
    application.base.win.addRenderTexture(
        tex, GraphicsOutput.RTMCopyRam, GraphicsOutput.RTPColor
    )
    return tex


def capture_to(tex: Texture, path: Path) -> PNMImage:
    image = PNMImage()
    if not tex.store(image):
        raise RuntimeError(
            f"framebuffer copy failed; cannot capture to {path}. "
            "Without this there is no way to verify rendering headlessly."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.write(Filename(str(path)))
    return image


def census(image: PNMImage, top: int = 8) -> list[tuple[int, tuple[int, int, int]]]:
    """Count distinct 8-bit colours in a frame, most common first."""
    counts: dict[tuple[int, int, int], int] = {}
    for y in range(image.get_y_size()):
        for x in range(image.get_x_size()):
            rgb = (
                int(image.get_red(x, y) * 255 + 0.5),
                int(image.get_green(x, y) * 255 + 0.5),
                int(image.get_blue(x, y) * 255 + 0.5),
            )
            counts[rgb] = counts.get(rgb, 0) + 1
    return sorted(((n, c) for c, n in counts.items()), reverse=True)[:top]


def build_depth_scene(calibration: TableCalibration):
    """The depth demo, plus the (name, mode, eye) views to capture."""
    from tabletop.apps.depth_demo import DepthDemo

    demo = DepthDemo(calibration)
    demo.head_motion = False

    def pose(name: str, mode: ProjectionMode, eye: Eye) -> None:
        demo.rig.mode = mode
        demo._frozen_eye = eye

    return VIEWS, pose, None


MENU_VIEWS: list[tuple[str, ProjectionMode, Eye]] = [
    ("menu_1_levels", ProjectionMode.PERSPECTIVE_FIXED, Eye(0.0, 0.0, 700.0)),
    ("menu_2_controls", ProjectionMode.PERSPECTIVE_FIXED, Eye(0.0, 0.0, 700.0)),
    ("menu_3_rules", ProjectionMode.PERSPECTIVE_FIXED, Eye(0.0, 0.0, 700.0)),
]


def build_menu_scene(calibration: TableCalibration):
    """The start menu over the game scene, in each of its three states."""
    from ursina import scene

    from tabletop.apps.whack_a_mole import WhackAMoleView
    from tabletop.game.whack_a_mole import GameConfig
    from tabletop.render.menu import StartMenu

    _, pose, _ = build_game_scene(calibration)
    # A round-over tally left showing underneath, so the frame proves the
    # menu covers it rather than ending up behind it.
    view = next(e for e in scene.children if isinstance(e, WhackAMoleView))
    view._show_banner("ROUND OVER\nSCORE 240\nACCURACY 71%")
    menu = StartMenu(
        GameConfig(),
        on_start=lambda level: None,
        display_width_mm=calibration.display_width_mm,
        display_height_mm=calibration.display_height_mm,
    )
    menu.show()

    def menu_pose(name: str, mode: ProjectionMode, eye: Eye) -> None:
        pose(name, mode, eye)
        if name.endswith("controls"):
            menu.open_panel("controls")
        elif name.endswith("rules"):
            menu.open_panel("rules")
        else:
            menu.close_panel()

    return MENU_VIEWS, menu_pose, None


def build_game_scene(calibration: TableCalibration, seed: int = 7):
    """The game, with moles up and one impact burst in flight.

    Forces state rather than waiting for the round to produce it: the frame
    has to contain a risen mole and a splat for the capture to be worth
    anything, and a 45-frame settle is not long enough to rely on the spawn
    scheduler for either.
    """
    from tabletop.apps import whack_a_mole as whack
    from tabletop.apps.whack_a_mole import WhackAMoleView
    from tabletop.render import mallet
    from tabletop.core.layout import TableLayout
    from tabletop.game.effects import EffectConfig, ImpactEffects
    from tabletop.game.whack_a_mole import MoleState, WhackAMole
    from tabletop.sensors.mock import MockTouchSource

    layout = TableLayout(
        calibration.display_width_mm, calibration.display_height_mm
    )
    game = WhackAMole(
        field_width_mm=layout.playfield_width_mm,
        field_height_mm=layout.playfield_height_mm,
        seed=seed,
    )
    source = MockTouchSource(calibration)
    source.start()
    view = WhackAMoleView(
        calibration,
        game,
        source,
        layout=layout,
        effects=ImpactEffects(EffectConfig(), seed=seed),
    )

    # No pointer in a headless run, so the mallet is posed by hand below.
    view.pointer_drives_mallet = False

    for index in (0, 4, 8, 13, 17):
        hole = game._holes[index]
        hole.state = MoleState.UP
        hole.height = 1.0
        hole.up_duration = 999.0
    game.scores[0] = 120
    game.hits, game.taps, game.spawned, game.top_score = 12, 17, 31, 240

    def pose(name: str, mode: ProjectionMode, eye: Eye) -> None:
        view.rig.mode = mode
        view.parallax_mode = mode is ProjectionMode.OFF_AXIS_HEAD_TRACKED
        view.marker_angle = 180.0 if "left" in name else -90.0
        view.eye_height_mm = eye.z
        view._place_camera_marker()

    def before_capture(name: str) -> None:
        # Burst here rather than at build time: droplets live under a
        # second, so anything emitted before the settle loop has expired by
        # the time the frame is grabbed.
        struck = game._holes[8]
        struck.state = MoleState.STRUCK
        struck.height = 0.8
        view.effects.emit_hit(struck.x_mm, struck.y_mm)

        # The mallet mid-swing over the mole it just hit. Posed directly
        # because there is no pointer in a headless run.
        view.mallet.enabled = True
        view.mallet.move_to(struck.x_mm, struck.y_mm)
        view.mallet.strike()
        view.mallet.update_swing(mallet.SWING_TIME_S * 0.35)

        if name.endswith("round_over"):
            view._show_banner(
                "ROUND OVER\nSCORE 240\nACCURACY 71%\n[R] AGAIN  [TAB] MENU"
            )
            # Through the real retract, so the frame shows where the mallet
            # actually comes to rest rather than where it is assumed to.
            view.start_retract(struck.x_mm, struck.y_mm)
            view._retract(whack.MALLET_RETRACT_S)
        else:
            view._hide_banner()

    return GAME_VIEWS, pose, before_capture


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a scene to PNGs")
    parser.add_argument("--out", type=Path, default=Path("/tmp/tabletop_shots"))
    parser.add_argument(
        "--scene",
        default="depth",
        choices=("depth", "game", "menu"),
        help="depth: projection-mode comparison. game: whack-a-mole. "
             "menu: the start menu over the game.",
    )
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--census", action="store_true", help="print colour census")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if any frame looks blank (too few distinct colours)",
    )
    parser.add_argument("--min-colours", type=int, default=6)
    parser.add_argument("--calibration", type=Path, default=None)
    args = parser.parse_args()

    calibration = (
        TableCalibration.load(args.calibration)
        if args.calibration
        else TableCalibration.development_default()
    )

    install_project_shaders()
    app = Ursina(
        title="tabletop capture",
        size=(args.width, args.height),
        icon=platform_setup.window_icon_path(),
        development_mode=False,
        show_ursina_splash=False,
        vsync=False,
    )
    window.color = color.rgb32(14, 17, 22)
    # Set the clear colour through Panda as well: it is the one value we can
    # recognise in a census to confirm the capture is the real colour buffer.
    application.base.win.set_clear_color(LColor(14 / 255, 17 / 255, 22 / 255, 1))
    application.base.win.set_clear_color_active(True)

    tex = attach_capture_texture()

    # Scenes are built here, after the shader install above is in force.
    builders = {
        "depth": build_depth_scene,
        "game": build_game_scene,
        "menu": build_menu_scene,
    }
    views, pose, before_capture = builders[args.scene](calibration)

    failures: list[tuple[str, int, tuple[int, int, int] | None]] = []

    for name, mode, eye in views:
        pose(name, mode, eye)
        for _ in range(SETTLE_FRAMES):
            app.step()
        if before_capture is not None:
            before_capture(name)
            # A few frames so the scene picks the new state up.
            for _ in range(3):
                app.step()
        # Deliberately no extra graphicsEngine.render_frame() here: an
        # out-of-band frame leaves the RAM copy stale, and the capture comes
        # back uniformly white. Let app.step() be the only thing that draws.

        path = args.out / f"{name}.png"
        image = capture_to(tex, path)
        counts = census(image, top=64)
        print(f"wrote {path}  ({len(counts)} distinct colours)")
        if args.census:
            for count, rgb in census(image):
                print(f"    {count:8d}  rgb{rgb}")

        if args.check and len(counts) < args.min_colours:
            failures.append((name, len(counts), counts[0][1] if counts else None))

    if failures:
        print("\nBLANK-FRAME CHECK FAILED")
        for name, n, dominant in failures:
            print(
                f"  {name}: only {n} distinct colours, dominated by "
                f"rgb{dominant}. A near-uniform frame means nothing drew -- "
                f"a uniform white frame in particular is the signature of "
                f"0-255 values passed to color.rgb()/rgba(), which expect "
                f"0.0-1.0 and clamp to opaque white."
            )
        return 1

    print(f"\n{len(views)} frames written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
