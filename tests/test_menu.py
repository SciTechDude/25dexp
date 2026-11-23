"""Start-menu logic that does not need a window.

The menu's entities need a graphics context, but its hit-testing and its
generated text do not, and those are the parts that can be wrong without
looking wrong.
"""

from __future__ import annotations

import pytest

from tabletop.game.whack_a_mole import DIFFICULTIES, GameConfig
from tabletop.render.menu import (
    CONTROLS,
    MENU_Z_MM,
    Row,
    controls_columns,
    rules_text,
)
from tabletop.render.projection import (
    Eye,
    glass_mm_to_plane_mm,
    plane_mm_to_glass_mm,
)


class TestRows:
    def test_a_row_contains_its_own_centre(self) -> None:
        row = Row("level", None, 0.0, 60.0, 440.0, 42.0)
        assert row.contains(0.0, 60.0)

    def test_a_row_rejects_points_outside_it(self) -> None:
        row = Row("level", None, 0.0, 60.0, 440.0, 42.0)
        assert not row.contains(0.0, 60.0 + 22.0)
        assert not row.contains(221.0, 60.0)

    def test_rows_at_the_same_height_are_told_apart_by_x(self) -> None:
        """The two info rows share a band, so x is what distinguishes them."""
        left = Row("panel", "controls", -120.0, -110.0, 200.0, 30.0)
        right = Row("panel", "rules", 120.0, -110.0, 200.0, 30.0)
        assert left.contains(-120.0, -110.0)
        assert not right.contains(-120.0, -110.0)
        assert right.contains(120.0, -110.0)


class TestControls:
    def test_the_two_columns_line_up(self) -> None:
        keys, defs = controls_columns()
        assert len(keys.splitlines()) == len(defs.splitlines()) == len(CONTROLS)

    def test_every_control_has_a_key_and_a_description(self) -> None:
        for key, what in CONTROLS:
            assert key.strip() and what.strip()


class TestRules:
    def test_rules_quote_the_config_they_are_given(self) -> None:
        """Generated, not written out, so the text cannot drift from the
        rules the game actually applies."""
        config = GameConfig(
            points_per_hit=7, points_per_miss=-3, round_length_s=20.0
        )
        text = rules_text(config)
        assert "+7" in text
        assert "-3" in text
        assert "20 s" in text

    def test_rules_follow_a_changed_config(self) -> None:
        a = rules_text(GameConfig(points_per_hit=10))
        b = rules_text(GameConfig(points_per_hit=99))
        assert a != b
        assert "+99" in b


class TestLevels:
    def test_there_is_a_number_key_for_every_level(self) -> None:
        """``input`` maps keys "1".."3"; a fourth level would be unreachable
        by keyboard."""
        assert len(DIFFICULTIES) <= 3

    def test_level_names_are_unique(self) -> None:
        names = [level.name for level in DIFFICULTIES]
        assert len(set(names)) == len(names)


def test_menu_module_imports_without_a_window() -> None:
    """Guard the guard: if importing the module needed a graphics context,
    every test above would be skipped rather than run."""
    import tabletop.render.menu as menu

    assert menu.MENU_Z_MM > 0
    # A 14 mm line is 2 mm per font pixel, the glyph being 7 pixels tall.
    assert menu.pixel_mm(14.0) == pytest.approx(2.0)


class TestAimingAtRows:
    """The menu is drawn above the glass, so a tap needs converting.

    A touch is reported on the glass plane. Testing it against the rows'
    own coordinates means every row sits a few centimetres from where it
    looks, worst at the edges of the panel -- which is a menu that appears
    to ignore clicks.
    """

    EYES = [Eye(0.0, 0.0, 700.0), Eye(-520.0, 0.0, 620.0), Eye(0.0, -420.0, 520.0)]

    ROWS = [
        Row("level", "beginner", 0.0, 60.0, 440.0, 42.0),
        Row("level", "medium", 0.0, 10.0, 440.0, 42.0),
        Row("level", "advanced", 0.0, -40.0, 440.0, 42.0),
        Row("panel", "controls", -200.0, -110.0, 170.0, 30.0),
        Row("panel", "rules", 0.0, -110.0, 170.0, 30.0),
        Row("quit", None, 200.0, -110.0, 170.0, 30.0),
    ]

    def row_under(self, x_mm: float, y_mm: float) -> Row | None:
        for row in self.ROWS:
            if row.contains(x_mm, y_mm):
                return row
        return None

    @pytest.mark.parametrize("eye", EYES, ids=lambda e: f"eye{e.x:.0f},{e.y:.0f}")
    @pytest.mark.parametrize("target", ROWS, ids=lambda r: str(r.value))
    def test_a_tap_where_a_row_looks_selects_that_row(
        self, eye: Eye, target: Row
    ) -> None:
        # Where the player sees the row's centre, on the glass.
        seen = plane_mm_to_glass_mm(target.x_mm, target.y_mm, MENU_Z_MM, eye)
        # What the view does with that tap.
        aimed = glass_mm_to_plane_mm(seen[0], seen[1], MENU_Z_MM, eye)
        assert self.row_under(*aimed) is target

    def test_without_the_conversion_the_outer_rows_are_missed(self) -> None:
        """Guard the guard: if the conversion were a no-op the test above
        would prove nothing.

        It is the rows furthest from the eye's axis that break -- the two
        info rows, 120 mm out and only 30 mm tall. The level rows sit near
        the centre, where the 16 mm error still lands inside a 42 mm row,
        which is why the menu looked like it ignored *some* clicks rather
        than all of them.
        """
        eye = Eye(0.0, 0.0, 700.0)
        for target in self.ROWS[3:]:
            seen = plane_mm_to_glass_mm(target.x_mm, target.y_mm, MENU_Z_MM, eye)
            assert self.row_under(*seen) is not target


def test_the_menu_sits_above_the_round_over_tally() -> None:
    """The tally is drawn on the table too, and it outlived its welcome:
    opening the menu left it on top, with the levels and the help panels
    behind it. Ordering the planes is what makes that impossible, rather
    than every path into the menu remembering to hide it."""
    from tabletop.apps.whack_a_mole import BANNER_Z_MM
    from tabletop.render.menu import MENU_Z_MM

    assert BANNER_Z_MM < MENU_Z_MM


class TestMenuRowLayout:
    """The rows are positioned by hand, so nothing may overlap."""

    def test_rows_in_a_shared_band_do_not_overlap(self) -> None:
        band = [r for r in TestAimingAtRows.ROWS if r.y_mm == -110.0]
        assert len(band) == 3
        band.sort(key=lambda r: r.x_mm)
        for left, right in zip(band, band[1:]):
            assert left.x_mm + left.width_mm / 2 <= right.x_mm - right.width_mm / 2

    def test_every_row_action_is_handled(self) -> None:
        """``hit`` dispatches on this, so an unknown action would silently
        do nothing."""
        actions = {row.action for row in TestAimingAtRows.ROWS}
        assert actions == {"level", "panel", "quit"}
