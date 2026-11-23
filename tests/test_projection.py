"""The off-axis projection invariant.

The whole depth illusion rests on one property: **the four physical screen
corners must land exactly on the four corners of the viewport, for every
eye position.** If that holds, the display behaves like a window onto a
scene. If it drifts, the image swims when the player moves and the effect
collapses into "the world is wobbling".

These tests pin that property down numerically, independently of Panda3D,
so a renderer regression can be distinguished from a maths regression.
"""

from __future__ import annotations

import numpy as np
import pytest

from tabletop.render.projection import (
    glass_mm_to_plane_mm,
    lens_eye,
    plane_mm_to_glass_mm,
    Eye,
    ProjectionMode,
    effective_vertical_fov_deg,
    lens_params_for,
    off_axis_frustum,
    project_point,
)

# A 43-inch 4K panel's lit area, in millimetres.
SCREEN_W = 941.0
SCREEN_H = 529.0
NEAR = 10.0
FAR = 5000.0

# Eye positions to check: directly overhead, shifted to each side, leaning
# in low over one edge, and well off the corner -- i.e. the range a seated
# player's head actually covers around a table.
EYE_POSITIONS = [
    Eye(0.0, 0.0, 700.0),
    Eye(300.0, 0.0, 700.0),
    Eye(-300.0, 0.0, 700.0),
    Eye(0.0, 250.0, 700.0),
    Eye(0.0, -250.0, 700.0),
    Eye(420.0, -260.0, 450.0),
    Eye(-500.0, 300.0, 900.0),
]


def screen_corners_mm() -> list[tuple[float, float, float]]:
    """The four corners of the lit area, on the glass plane (z = 0)."""
    hw, hh = SCREEN_W / 2.0, SCREEN_H / 2.0
    return [(-hw, -hh, 0.0), (hw, -hh, 0.0), (hw, hh, 0.0), (-hw, hh, 0.0)]


@pytest.mark.parametrize("eye", EYE_POSITIONS, ids=lambda e: f"eye{e.x:+.0f},{e.y:+.0f},{e.z:.0f}")
def test_screen_corners_pin_to_viewport_corners(eye: Eye) -> None:
    """The defining invariant: corners stay nailed to the viewport edges."""
    matrix = off_axis_frustum(eye, SCREEN_W, SCREEN_H, NEAR, FAR)

    for corner in screen_corners_mm():
        ndc_x, ndc_y, _ = project_point(matrix, corner, eye)
        assert abs(abs(ndc_x) - 1.0) < 1e-9, (
            f"corner {corner} projected to ndc_x={ndc_x}, expected +-1. "
            f"The screen rectangle is not filling the viewport, so the "
            f"window illusion is broken for eye {eye}."
        )
        assert abs(abs(ndc_y) - 1.0) < 1e-9, (
            f"corner {corner} projected to ndc_y={ndc_y}, expected +-1."
        )


@pytest.mark.parametrize("eye", EYE_POSITIONS, ids=lambda e: f"eye{e.x:+.0f},{e.y:+.0f},{e.z:.0f}")
def test_screen_centre_stays_centred(eye: Eye) -> None:
    """The glass plane is parallel to the image plane, so its projection is
    affine: the centre of the screen maps to the centre of the viewport no
    matter where the eye is."""
    matrix = off_axis_frustum(eye, SCREEN_W, SCREEN_H, NEAR, FAR)
    ndc_x, ndc_y, _ = project_point(matrix, (0.0, 0.0, 0.0), eye)
    assert abs(ndc_x) < 1e-9
    assert abs(ndc_y) < 1e-9


def test_on_axis_eye_gives_symmetric_frustum() -> None:
    """With the eye centred, the sheared frustum degenerates to the ordinary
    symmetric one -- which is why PERSPECTIVE_FIXED needs no separate code
    path."""
    eye = Eye(0.0, 0.0, 700.0)
    matrix = off_axis_frustum(eye, SCREEN_W, SCREEN_H, NEAR, FAR)
    # Columns 2 of rows 0 and 1 carry the shear; both must vanish.
    assert abs(matrix[0, 2]) < 1e-12
    assert abs(matrix[1, 2]) < 1e-12


def test_raised_geometry_parallaxes_against_the_eye() -> None:
    """A token standing *above* the glass should slide opposite to head
    motion, the way a real object in front of a window does.

    This is the cue that sells "sticking out of the screen".
    """
    raised = (0.0, 0.0, 80.0)  # 80 mm proud of the glass

    centre = Eye(0.0, 0.0, 700.0)
    right = Eye(300.0, 0.0, 700.0)

    x_centre, _, _ = project_point(
        off_axis_frustum(centre, SCREEN_W, SCREEN_H, NEAR, FAR), raised, centre
    )
    x_right, _, _ = project_point(
        off_axis_frustum(right, SCREEN_W, SCREEN_H, NEAR, FAR), raised, right
    )

    assert abs(x_centre) < 1e-9, "on-axis eye should see it dead centre"
    assert x_right < -1e-6, (
        f"eye moved +x, so a raised object must shift -x in the image "
        f"(got {x_right}). Same-direction motion means the frustum shear "
        f"has the wrong sign."
    )


def test_recessed_geometry_parallaxes_with_the_eye() -> None:
    """A sunken board *below* the glass should slide with head motion -- the
    opposite sense to raised geometry. The two together are what makes the
    glass read as a window rather than a painting."""
    recessed = (0.0, 0.0, -80.0)

    centre = Eye(0.0, 0.0, 700.0)
    right = Eye(300.0, 0.0, 700.0)

    x_centre, _, _ = project_point(
        off_axis_frustum(centre, SCREEN_W, SCREEN_H, NEAR, FAR), recessed, centre
    )
    x_right, _, _ = project_point(
        off_axis_frustum(right, SCREEN_W, SCREEN_H, NEAR, FAR), recessed, right
    )

    assert abs(x_centre) < 1e-9
    assert x_right > 1e-6, (
        f"eye moved +x, so a recessed object must shift +x in the image "
        f"(got {x_right})."
    )


def test_eye_must_be_in_front_of_the_screen() -> None:
    with pytest.raises(ValueError, match="in front of the screen"):
        Eye(0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="in front of the screen"):
        Eye(0.0, 0.0, -100.0)


def test_near_far_validation() -> None:
    eye = Eye(0.0, 0.0, 700.0)
    with pytest.raises(ValueError, match="near < far"):
        off_axis_frustum(eye, SCREEN_W, SCREEN_H, 100.0, 50.0)


class TestLensParams:
    """Panda3D lens settings derived from the same geometry."""

    def test_off_axis_cancels_the_eye_offset(self) -> None:
        eye = Eye(120.0, -45.0, 650.0)
        p = lens_params_for(
            ProjectionMode.OFF_AXIS_HEAD_TRACKED, SCREEN_W, SCREEN_H, eye
        )
        assert p.film_offset_x == pytest.approx(-120.0)
        assert p.film_offset_y == pytest.approx(45.0)
        assert p.focal_length == pytest.approx(650.0)
        assert p.film_width == pytest.approx(SCREEN_W)
        assert p.film_height == pytest.approx(SCREEN_H)
        assert not p.orthographic

    def test_fixed_perspective_ignores_lateral_eye_motion(self) -> None:
        """So that a mode switch isolates the variable under test: only the
        projection changes, not the viewing distance or the scene."""
        eye = Eye(400.0, 200.0, 650.0)
        p = lens_params_for(
            ProjectionMode.PERSPECTIVE_FIXED, SCREEN_W, SCREEN_H, eye
        )
        assert p.film_offset_x == 0.0
        assert p.film_offset_y == 0.0
        assert p.focal_length == pytest.approx(650.0)

    def test_orthographic_ignores_the_eye_entirely(self) -> None:
        eye = Eye(400.0, 200.0, 650.0)
        p = lens_params_for(ProjectionMode.ORTHOGRAPHIC, SCREEN_W, SCREEN_H, eye)
        assert p.orthographic
        assert p.film_offset_x == 0.0
        assert p.film_offset_y == 0.0
        assert p.film_width == pytest.approx(SCREEN_W)

    def test_fixed_eye_height_override(self) -> None:
        eye = Eye(0.0, 0.0, 650.0)
        p = lens_params_for(
            ProjectionMode.PERSPECTIVE_FIXED, SCREEN_W, SCREEN_H, eye,
            fixed_eye_height=1200.0,
        )
        assert p.focal_length == pytest.approx(1200.0)

    def test_fov_readout_is_plausible_for_a_tabletop(self) -> None:
        """Sanity-check the physical numbers against intuition: a 43-inch
        panel seen from 700 mm is a fairly narrow lens, matching the
        'narrow FOV = clean tabletop look' guidance."""
        eye = Eye(0.0, 0.0, 700.0)
        p = lens_params_for(ProjectionMode.PERSPECTIVE_FIXED, SCREEN_W, SCREEN_H, eye)
        fov = effective_vertical_fov_deg(p)
        assert 35.0 < fov < 45.0, f"expected a ~40 degree vertical lens, got {fov}"

    def test_orthographic_fov_is_meaningless_and_reported_as_zero(self) -> None:
        eye = Eye(0.0, 0.0, 700.0)
        p = lens_params_for(ProjectionMode.ORTHOGRAPHIC, SCREEN_W, SCREEN_H, eye)
        assert effective_vertical_fov_deg(p) == 0.0


def test_matrix_is_finite_across_extreme_but_legal_eyes() -> None:
    """Head tracking will occasionally report an eye almost on the glass or
    far off to the side. Those must still produce usable matrices rather
    than NaNs that silently blank the screen."""
    for eye in [Eye(0.0, 0.0, 15.0), Eye(2000.0, -2000.0, 2000.0)]:
        matrix = off_axis_frustum(eye, SCREEN_W, SCREEN_H, NEAR, FAR)
        assert np.all(np.isfinite(matrix)), f"non-finite matrix for {eye}"


class TestPlaneAndGlass:
    """Content drawn above the glass appears displaced from where it is."""

    def test_a_point_on_the_glass_is_unmoved(self) -> None:
        eye = Eye(0.0, 0.0, 700.0)
        assert plane_mm_to_glass_mm(120.0, -40.0, 0.0, eye) == pytest.approx(
            (120.0, -40.0)
        )

    def test_height_pushes_a_point_away_from_the_eye_axis(self) -> None:
        eye = Eye(0.0, 0.0, 700.0)
        x, y = plane_mm_to_glass_mm(100.0, 0.0, 150.0, eye)
        assert x == pytest.approx(100.0 * 700.0 / 550.0)
        assert y == pytest.approx(0.0)

    def test_a_point_on_the_eye_axis_does_not_move(self) -> None:
        eye = Eye(-300.0, 120.0, 700.0)
        assert plane_mm_to_glass_mm(-300.0, 120.0, 200.0, eye) == pytest.approx(
            (-300.0, 120.0)
        )

    @pytest.mark.parametrize(
        "eye",
        [Eye(0.0, 0.0, 700.0), Eye(-520.0, 260.0, 520.0), Eye(300.0, -100.0, 1200.0)],
    )
    @pytest.mark.parametrize("z_mm", [0.0, 60.0, 150.0, 300.0])
    def test_the_two_directions_round_trip(self, eye: Eye, z_mm: float) -> None:
        point = (210.0, -75.0)
        seen = plane_mm_to_glass_mm(point[0], point[1], z_mm, eye)
        back = glass_mm_to_plane_mm(seen[0], seen[1], z_mm, eye)
        assert back == pytest.approx(point)

    def test_a_plane_at_or_above_the_eye_is_rejected(self) -> None:
        eye = Eye(0.0, 0.0, 700.0)
        with pytest.raises(ValueError, match="not above"):
            plane_mm_to_glass_mm(0.0, 0.0, 700.0, eye)
        with pytest.raises(ValueError, match="not above"):
            glass_mm_to_plane_mm(0.0, 0.0, 900.0, eye)


class TestLensEye:
    """Which eye the lens projects from, which is not always the viewer's.

    The bug this pins: apparent-position maths used the tracked head while
    the lens projected from above the table centre, so the pointer's mallet
    was drawn short of the hand and, near the home edge, landed on the
    surrounding panel.
    """

    HEAD = Eye(-300.0, -260.0, 650.0)

    def test_head_tracked_mode_projects_from_the_head(self) -> None:
        assert (
            lens_eye(ProjectionMode.OFF_AXIS_HEAD_TRACKED, self.HEAD, 700.0)
            is self.HEAD
        )

    @pytest.mark.parametrize(
        "mode", [ProjectionMode.PERSPECTIVE_FIXED, ProjectionMode.ORTHOGRAPHIC]
    )
    def test_fixed_modes_project_from_above_the_centre(
        self, mode: ProjectionMode
    ) -> None:
        eye = lens_eye(mode, self.HEAD, 700.0)
        assert (eye.x, eye.y, eye.z) == (0.0, 0.0, 700.0)

    def test_the_eye_is_what_apparent_position_must_use(self) -> None:
        """Using the head instead, in a fixed mode, is wrong by centimetres
        -- which is the size of the bug it caused."""
        point = (0.0, -200.0)
        with_lens = glass_mm_to_plane_mm(
            point[0],
            point[1],
            150.0,
            lens_eye(ProjectionMode.PERSPECTIVE_FIXED, self.HEAD, 700.0),
        )
        with_head = glass_mm_to_plane_mm(point[0], point[1], 150.0, self.HEAD)
        assert abs(with_lens[1] - with_head[1]) > 40.0
