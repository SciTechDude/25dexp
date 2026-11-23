"""Layout maths: bezel, score band, playfield."""

from __future__ import annotations

import pytest

from tabletop.core.layout import TableLayout

DISPLAY_W = 941.0
DISPLAY_H = 529.0


def make_layout(**kwargs) -> TableLayout:
    return TableLayout(DISPLAY_W, DISPLAY_H, **kwargs)


class TestPlayfield:
    def test_margin_is_bezel_plus_band(self) -> None:
        layout = make_layout(bezel_width_mm=18.0, score_band_mm=34.0)
        assert layout.margin_mm == pytest.approx(52.0)

    def test_playfield_is_inset_on_all_four_sides(self) -> None:
        layout = make_layout()
        assert layout.playfield_width_mm == pytest.approx(
            DISPLAY_W - 2 * layout.margin_mm
        )
        assert layout.playfield_height_mm == pytest.approx(
            DISPLAY_H - 2 * layout.margin_mm
        )

    def test_playfield_stays_centred_on_the_table_origin(self) -> None:
        rect = make_layout().playfield_rect
        assert rect.centre_x_mm == pytest.approx(0.0)
        assert rect.centre_y_mm == pytest.approx(0.0)

    def test_zero_margin_leaves_the_whole_display(self) -> None:
        layout = make_layout(
            bezel_width_mm=0.0,
            bezel_inner_slope_mm=0.0,
            bezel_outer_slope_mm=0.0,
            score_band_mm=0.0,
        )
        assert layout.playfield_width_mm == pytest.approx(DISPLAY_W)


class TestValidation:
    def test_a_margin_wider_than_the_display_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="leaves no playfield"):
            make_layout(score_band_mm=300.0)

    def test_chamfers_wider_than_the_bezel_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="do not fit"):
            make_layout(
                bezel_width_mm=8.0,
                bezel_inner_slope_mm=6.0,
                bezel_outer_slope_mm=4.0,
            )

    def test_negative_widths_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be negative"):
            make_layout(score_band_mm=-1.0)


class TestCrossSections:
    def test_bezel_profile_starts_and_ends_at_the_glass(self) -> None:
        """Both ends at z=0, so the moulding meets the display edge and the
        playfield flush rather than as a step."""
        profile = make_layout().bezel_cross_section()
        assert profile[0] == (0.0, 0.0)
        assert profile[-1][1] == pytest.approx(0.0)

    def test_bezel_profile_insets_are_monotonic(self) -> None:
        insets = [inset for inset, _ in make_layout().bezel_cross_section()]
        assert insets == sorted(insets)

    def test_bezel_profile_reaches_full_rise(self) -> None:
        layout = make_layout()
        heights = [z for _, z in layout.bezel_cross_section()]
        assert max(heights) == pytest.approx(layout.bezel_rise_mm)

    def test_bezel_profile_never_exceeds_its_width(self) -> None:
        layout = make_layout()
        assert max(i for i, _ in layout.bezel_cross_section()) == pytest.approx(
            layout.bezel_width_mm
        )

    def test_band_profile_is_flat_and_off_the_glass_plane(self) -> None:
        """Coplanar with the field it would z-fight."""
        layout = make_layout()
        (i0, z0), (i1, z1) = layout.band_cross_section()
        assert z0 == z1 > 0.0
        assert i0 == pytest.approx(layout.bezel_width_mm)
        assert i1 == pytest.approx(layout.margin_mm)


class TestScoreboard:
    def test_anchor_sits_on_the_near_band(self) -> None:
        layout = make_layout()
        x_mm, y_mm, z_mm = layout.score_anchor()
        assert x_mm == pytest.approx(0.0)
        assert y_mm == pytest.approx(
            -DISPLAY_H / 2 + layout.score_centre_offset_mm
        )
        assert z_mm > 0.0

    def test_anchor_is_between_the_bezel_and_the_playfield(self) -> None:
        layout = make_layout()
        _, y_mm, _ = layout.score_anchor()
        assert y_mm < layout.playfield_rect.min_y_mm
        assert y_mm > -DISPLAY_H / 2 + layout.bezel_width_mm

    def test_band_length_tracks_the_playfield_width(self) -> None:
        layout = make_layout()
        assert layout.score_band_length_mm == pytest.approx(
            layout.playfield_width_mm
        )


class TestExitButton:
    def test_it_sits_on_the_near_band(self) -> None:
        layout = make_layout()
        rect = layout.exit_button_rect()
        _, band_y, _ = layout.score_anchor()
        assert rect.centre_y_mm == pytest.approx(band_y)
        assert rect.centre_y_mm < layout.playfield_rect.min_y_mm

    def test_it_is_not_on_the_playfield(self) -> None:
        """A tap meant for the exit must never be a tap meant for a mole,
        and vice versa."""
        layout = make_layout()
        rect = layout.exit_button_rect()
        assert rect.max_y_mm < layout.playfield_rect.min_y_mm

    def test_it_stays_within_the_band(self) -> None:
        layout = make_layout()
        rect = layout.exit_button_rect()
        assert rect.max_x_mm <= layout.score_band_length_mm / 2.0
        assert rect.min_y_mm > -layout.display_height_mm / 2.0
        assert rect.max_y_mm < layout.playfield_rect.min_y_mm

    def test_it_is_big_enough_to_hit_with_a_finger(self) -> None:
        rect = make_layout().exit_button_rect()
        assert rect.width_mm >= 40.0
        assert rect.height_mm >= 20.0

    def test_it_is_clear_of_the_readouts_and_the_resting_mallet(self) -> None:
        """Everything on the band is positioned by hand, so this is the
        check that two of them have not been put in the same place."""
        from tabletop.apps.whack_a_mole import (
            MALLET_REST_MARGIN_MM,
            SCORE_X_MM,
            STATS_X_MM,
            TIME_X_MM,
        )

        layout = make_layout()
        rect = layout.exit_button_rect()
        mallet_x = -layout.score_band_length_mm / 2.0 + MALLET_REST_MARGIN_MM

        for x in (TIME_X_MM, SCORE_X_MM, STATS_X_MM, mallet_x):
            assert not rect.contains(x, rect.centre_y_mm), x
            # And a readout's text extends either side of its anchor, so
            # require real clearance rather than just a miss at the centre.
            assert abs(x - rect.centre_x_mm) > rect.width_mm
