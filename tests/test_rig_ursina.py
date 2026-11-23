"""End-to-end check that the rig drives Panda3D's lens correctly.

:mod:`tests.test_projection` proves the *maths*. This proves the *wiring*:
that the camera transform, the lens film size, the film offset sign and the
coordinate-system handedness all compose into the projection we intended.

They are separate failures. A sign flip in Ursina's left-handed ``y-up-left``
coordinate system would leave the pure maths tests passing while the actual
window effect inverted, so the invariant is re-checked here against real
Panda3D projection, not a reimplementation of it.

Marked ``ursina`` because it needs a graphics context and opens a window.
Deselect with ``-m "not ursina"``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.ursina

ursina = pytest.importorskip("ursina", reason="ursina not installed")

from panda3d.core import Point2, Point3  # noqa: E402

from tabletop.core.calibration import TableCalibration  # noqa: E402
from tabletop.render.projection import Eye, ProjectionMode  # noqa: E402

EYES = [
    Eye(0.0, 0.0, 700.0),
    Eye(300.0, 0.0, 700.0),
    Eye(-250.0, 180.0, 550.0),
    Eye(480.0, -260.0, 430.0),
]


@pytest.fixture(scope="module")
def app():
    """One Ursina instance for the module.

    Ursina keeps its camera, window and scene as module-level singletons, so
    a second instance in the same process is not safe. Session scope also
    keeps the graphics context creation cost to one.
    """
    from tabletop.render import platform_setup  # noqa: F401  (before ursina)
    from ursina import Ursina

    instance = Ursina(window_type="offscreen", development_mode=False)
    yield instance


@pytest.fixture(scope="module")
def calibration() -> TableCalibration:
    return TableCalibration.development_default()


def _ndc_of_world_point(lens, world_point) -> tuple[float, float]:
    """Project a world-space point through the live Panda lens into NDC."""
    from ursina import application

    camera_space = application.base.cam.getRelativePoint(
        application.base.render, Point3(*world_point)
    )
    out = Point2()
    if not lens.project(camera_space, out):
        raise AssertionError(f"point {world_point} failed to project")
    return (out[0], out[1])


@pytest.mark.parametrize("eye", EYES, ids=lambda e: f"eye{e.x:+.0f},{e.y:+.0f},{e.z:.0f}")
def test_display_corners_pin_to_the_viewport(app, calibration, eye: Eye) -> None:
    """The invariant, measured through real Panda3D projection.

    X is checked against exactly +-1. Y is checked against the letterbox
    fraction, because the offscreen window does not share the table's
    aspect: the table is inscribed, so its corners sit at
    ``screen_height / film_height`` rather than at the viewport edge.
    """
    from ursina import camera

    from tabletop.render.mapping import table_to_world
    from tabletop.render.table_app import TableRig

    rig = TableRig(calibration, mode=ProjectionMode.OFF_AXIS_HEAD_TRACKED)
    params = rig.apply(eye)
    app.step()

    lens = camera.perspective_lens
    expected_y = calibration.display_height_mm / params.film_height
    expected_x = calibration.display_width_mm / params.film_width

    for corner_x, corner_y in calibration.display_rect.corners_mm():
        world = table_to_world(corner_x, corner_y, 0.0)
        ndc_x, ndc_y = _ndc_of_world_point(lens, world)

        assert abs(ndc_x) == pytest.approx(expected_x, abs=1e-4), (
            f"corner ({corner_x:.0f}, {corner_y:.0f}) drifted in X to "
            f"{ndc_x:.5f} for eye {eye}. The window effect is broken: the "
            f"display edge is no longer pinned to the viewport."
        )
        assert abs(ndc_y) == pytest.approx(expected_y, abs=1e-4), (
            f"corner ({corner_x:.0f}, {corner_y:.0f}) drifted in Y to "
            f"{ndc_y:.5f} for eye {eye}."
        )


def test_film_offset_sign_is_not_inverted(app, calibration) -> None:
    """Guards the specific risk in Ursina's left-handed coordinate system.

    An inverted film offset still pins the corners when the eye is centred,
    so it would slip past a single on-axis check. Here the eye is moved and
    the *sign* of the applied offset is asserted directly.
    """
    from ursina import camera

    from tabletop.render.table_app import TableRig

    rig = TableRig(calibration, mode=ProjectionMode.OFF_AXIS_HEAD_TRACKED)
    rig.apply(Eye(300.0, 150.0, 700.0))
    app.step()

    offset = camera.perspective_lens.get_film_offset()
    assert offset[0] < 0, "eye moved +X so film offset must be negative"
    assert offset[1] < 0, "eye moved +Y so film offset must be negative"


def test_raised_and_recessed_geometry_parallax_oppositely(app, calibration) -> None:
    """The depth cue, measured through the real renderer.

    A token above the glass and a point sunk below it must move in opposite
    directions as the eye moves. Same-direction motion means the scene is
    swinging rather than behaving like a window.
    """
    from ursina import camera

    from tabletop.render.mapping import table_to_world
    from tabletop.render.table_app import TableRig

    rig = TableRig(calibration, mode=ProjectionMode.OFF_AXIS_HEAD_TRACKED)

    def ndc_x_at(eye: Eye, z_mm: float) -> float:
        rig.apply(eye)
        app.step()
        return _ndc_of_world_point(
            camera.perspective_lens, table_to_world(0.0, 0.0, z_mm)
        )[0]

    centre, right = Eye(0.0, 0.0, 700.0), Eye(300.0, 0.0, 700.0)

    raised_centre = ndc_x_at(centre, 80.0)
    raised_right = ndc_x_at(right, 80.0)
    recessed_centre = ndc_x_at(centre, -80.0)
    recessed_right = ndc_x_at(right, -80.0)

    assert raised_centre == pytest.approx(0.0, abs=1e-6)
    assert recessed_centre == pytest.approx(0.0, abs=1e-6)
    assert raised_right < -1e-5, "raised geometry must shift against the eye"
    assert recessed_right > 1e-5, "recessed geometry must shift with the eye"


def test_orthographic_mode_switch_applies_the_orthographic_lens(
    app, calibration
) -> None:
    """Covers the Ursina quirk this adapter exists to work around: the
    ``orthographic`` setter re-applies ``fov``, which overwrites film size
    and focal length. Reapplying afterwards is what keeps the film correct.
    """
    from ursina import camera

    from tabletop.render.mapping import mm_to_world
    from tabletop.render.table_app import TableRig

    rig = TableRig(calibration, mode=ProjectionMode.ORTHOGRAPHIC)
    params = rig.apply(Eye(0.0, 0.0, 700.0))
    app.step()

    assert camera.orthographic is True
    film = camera.orthographic_lens.get_film_size()
    assert film[0] == pytest.approx(mm_to_world(params.film_width), abs=1e-4)
    assert film[1] == pytest.approx(mm_to_world(params.film_height), abs=1e-4)


def test_camera_is_never_rotated_away_from_straight_down(app, calibration) -> None:
    """Re-aiming the camera is the mistake that converts a window effect
    into a swinging scene. The rig must only ever translate it."""
    from ursina import camera

    from tabletop.render.table_app import TableRig

    rig = TableRig(calibration, mode=ProjectionMode.OFF_AXIS_HEAD_TRACKED)
    for eye in EYES:
        rig.apply(eye)
        app.step()
        assert camera.rotation_x == pytest.approx(90.0)
        assert camera.rotation_y == pytest.approx(0.0)
        assert camera.rotation_z == pytest.approx(0.0)
