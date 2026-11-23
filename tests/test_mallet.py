"""The mallet's swing and geometry, without a window."""

from __future__ import annotations

import pytest

from tabletop.render.mallet import (
    DOWN_FRACTION,
    REST_ANGLE_DEG,
    REST_Z_MM,
    STRIKE_ANGLE_DEG,
    STRIKE_Z_MM,
    disc_xy_mesh,
    swing_profile,
)
from tabletop.render.mapping import mm_to_world
from tabletop.render.projection import (
    Eye,
    glass_mm_to_plane_mm,
    plane_mm_to_glass_mm,
)


class TestSwing:
    def test_at_rest_before_and_after_the_swing(self) -> None:
        for t in (-1.0, 0.0, 1.0, 2.0):
            assert swing_profile(t) == (REST_ANGLE_DEG, REST_Z_MM)

    def test_the_mallet_comes_down(self) -> None:
        """The dip in Z is the cue an overhead view actually reads."""
        _, z = swing_profile(DOWN_FRACTION)
        assert z == pytest.approx(STRIKE_Z_MM)
        assert z < REST_Z_MM

    def test_z_falls_then_rises(self) -> None:
        heights = [swing_profile(i / 40)[1] for i in range(41)]
        lowest = min(range(len(heights)), key=lambda i: heights[i])
        assert heights[:lowest] == sorted(heights[:lowest], reverse=True)
        assert heights[lowest:] == sorted(heights[lowest:])

    def test_it_never_goes_below_the_glass(self) -> None:
        for i in range(101):
            assert swing_profile(i / 100)[1] > 0.0

    def test_the_angle_follows_the_same_arc(self) -> None:
        angle, _ = swing_profile(DOWN_FRACTION)
        assert angle == pytest.approx(STRIKE_ANGLE_DEG)
        mid_angle, _ = swing_profile(DOWN_FRACTION / 2)
        assert REST_ANGLE_DEG < mid_angle < STRIKE_ANGLE_DEG

    def test_the_downswing_is_faster_than_the_recovery(self) -> None:
        assert DOWN_FRACTION < 0.5


class TestDisc:
    def test_it_is_flat_in_the_local_xy_plane(self) -> None:
        """Local geometry, so the parent's rotation swings it; a disc already
        oriented to the table would be rotated twice."""
        mesh = disc_xy_mesh(38.0, segments=12)
        assert all(v[2] == pytest.approx(0.0) for v in mesh.vertices)

    def test_it_spans_its_diameter(self) -> None:
        mesh = disc_xy_mesh(38.0, segments=64)
        xs = [v[0] for v in mesh.vertices]
        ys = [v[1] for v in mesh.vertices]
        assert max(xs) == pytest.approx(mm_to_world(38.0), rel=1e-3)
        assert max(ys) == pytest.approx(mm_to_world(38.0), rel=1e-3)
        assert min(xs) == pytest.approx(-mm_to_world(38.0), rel=1e-3)

    def test_one_triangle_per_segment(self) -> None:
        mesh = disc_xy_mesh(10.0, segments=16)
        assert len(mesh.triangles) == 16 * 3


class TestAiming:
    """The mallet rides 150 mm above the glass, so where it is drawn and
    where it appears are not the same point."""

    EYE = Eye(0.0, 0.0, 700.0)
    TARGETS = [(0.0, 0.0), (300.0, -150.0), (-400.0, 180.0), (0.0, -200.0)]

    @pytest.mark.parametrize("target", TARGETS, ids=str)
    def test_the_head_appears_over_the_point_it_is_aimed_at(
        self, target: tuple[float, float]
    ) -> None:
        drawn = glass_mm_to_plane_mm(target[0], target[1], REST_Z_MM, self.EYE)
        appears = plane_mm_to_glass_mm(drawn[0], drawn[1], REST_Z_MM, self.EYE)
        assert appears == pytest.approx(target)

    def test_drawing_it_at_the_contact_point_misses_by_centimetres(self) -> None:
        """Which is what it did: the head sat outward of the hole being
        clicked, and at the near edge it could not reach the panel at all."""
        target = (300.0, -200.0)
        appears = plane_mm_to_glass_mm(target[0], target[1], REST_Z_MM, self.EYE)
        error = max(abs(appears[0] - target[0]), abs(appears[1] - target[1]))
        assert error > 50.0

    def test_the_correction_pulls_the_mallet_inward(self) -> None:
        drawn = glass_mm_to_plane_mm(300.0, -200.0, REST_Z_MM, self.EYE)
        assert abs(drawn[0]) < 300.0
        assert abs(drawn[1]) < 200.0


class TestWhatCountsAsTheMalletsPosition:
    """The head is the pointer; the handle is allowed to hang off the field.

    The head is a circle about a third of a hole across and the handle runs
    62 mm back from it, so near the near edge the handle crosses onto the
    panel. That is how a mallet held by a hand off the table looks, and it
    must not count as the mallet having left the playfield -- otherwise the
    bottom row of holes becomes unplayable, the pointer flipping between
    mallet and cursor as the player reaches for it.
    """

    def test_the_handle_reaches_further_than_the_head(self) -> None:
        from tabletop.render.mallet import HANDLE_LENGTH_MM, HEAD_RADIUS_MM

        assert HANDLE_LENGTH_MM > HEAD_RADIUS_MM * 2

    def test_a_head_just_inside_the_edge_is_on_the_field(self) -> None:
        from tabletop.game.whack_a_mole import WhackAMole

        game = WhackAMole(field_width_mm=837.0, field_height_mm=425.0, seed=1)
        near_edge = -425.0 / 2 + 2.0
        assert game.on_field(0.0, near_edge)
        # The handle, 62 mm behind the head, is well off the field here --
        # and that is fine, because only the head is tested.
        assert not game.on_field(0.0, near_edge - 62.0)
