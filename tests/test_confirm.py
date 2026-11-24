"""Confirm-dialog logic that does not need a window.

What the dialog offers, where its rows sit, and which key picks which row
are the parts that can be wrong without looking wrong -- a dialog whose
EXIT row is one row off still looks like a dialog.

The entities themselves need a graphics context and are not built here; the
geometry they are built from is the same :class:`Prompt` these tests use.
"""

from __future__ import annotations

import pytest

from tabletop.core.geometry import RectMM
from tabletop.render.confirm import (
    ACTIONS,
    CONFIRM_Z_MM,
    MAX_CHOICES,
    MENU,
    ROUND_LIVE,
    ROUND_OVER,
    ROW_HEIGHT_MM,
    ROW_STEP_MM,
    Choice,
    Prompt,
    actions_of,
    exit_prompt,
)
from tabletop.render.menu import MENU_Z_MM
from tabletop.render.projection import (
    Eye,
    glass_mm_to_plane_mm,
    plane_mm_to_glass_mm,
)

ALL_STATES = (ROUND_LIVE, ROUND_OVER, MENU)


def prompts() -> list[Prompt]:
    return [
        exit_prompt(ROUND_LIVE),
        exit_prompt(ROUND_OVER, score=240, accuracy=0.71),
        exit_prompt(MENU),
    ]


class TestWhatEachStateOffers:
    def test_a_live_round_can_be_resumed(self) -> None:
        """The whole point: EXIT mid-round must not be a one-way door."""
        actions = {c.action for c in exit_prompt(ROUND_LIVE).choices}
        assert "resume" in actions
        assert "end_round" in actions
        assert "quit" in actions

    def test_a_finished_round_offers_a_way_forward_and_out(self) -> None:
        actions = {c.action for c in exit_prompt(ROUND_OVER).choices}
        assert actions == {"play_again", "menu", "quit"}

    def test_the_menu_asks_before_closing_the_window(self) -> None:
        actions = {c.action for c in exit_prompt(MENU).choices}
        assert actions == {"quit", "cancel"}

    def test_quitting_is_never_the_only_option(self) -> None:
        """Every prompt has at least one choice that is not the quit."""
        for prompt in prompts():
            assert any(c.action != "quit" for c in prompt.choices)

    def test_quitting_is_always_offered(self) -> None:
        """EXIT was pressed; leaving has to be reachable from every state."""
        for prompt in prompts():
            assert any(c.action == "quit" for c in prompt.choices)

    def test_an_unknown_state_is_refused(self) -> None:
        with pytest.raises(ValueError):
            exit_prompt("wandering_about")


class TestRoundOverTally:
    def test_the_tally_repeats_the_score_being_decided_on(self) -> None:
        prompt = exit_prompt(ROUND_OVER, score=240, accuracy=0.715)
        assert "240" in prompt.subtitle
        assert "72%" in prompt.subtitle  # rounded, as the banner rounds

    def test_without_a_score_there_is_no_empty_tally_line(self) -> None:
        assert exit_prompt(ROUND_OVER).subtitle == ""


class TestKeys:
    def test_every_choice_has_its_own_number(self) -> None:
        for prompt in prompts():
            keys = [c.key for c in prompt.choices]
            assert keys == [str(i + 1) for i in range(len(keys))]

    def test_a_number_picks_the_row_it_is_printed_on(self) -> None:
        prompt = exit_prompt(ROUND_LIVE)
        for index, choice in enumerate(prompt.choices):
            assert prompt.choice_for_key(str(index + 1)) is choice

    def test_an_unused_key_picks_nothing(self) -> None:
        assert exit_prompt(MENU).choice_for_key("9") is None


class TestRows:
    def test_a_tap_in_the_middle_of_a_row_picks_it(self) -> None:
        prompt = exit_prompt(ROUND_LIVE)
        for index, choice in enumerate(prompt.choices):
            rect = prompt.rect_for(index)
            assert (
                prompt.choice_at(rect.centre_x_mm, rect.centre_y_mm) is choice
            )

    def test_rows_do_not_overlap(self) -> None:
        """A gap between rows, so a tap cannot land on two answers."""
        assert ROW_STEP_MM > ROW_HEIGHT_MM
        prompt = exit_prompt(ROUND_LIVE)
        for index in range(len(prompt.choices) - 1):
            upper = prompt.rect_for(index)
            lower = prompt.rect_for(index + 1)
            assert lower.max_y_mm < upper.min_y_mm

    def test_a_tap_between_rows_picks_nothing(self) -> None:
        prompt = exit_prompt(ROUND_LIVE)
        gap_y = (prompt.rect_for(0).min_y_mm + prompt.rect_for(1).max_y_mm) / 2
        assert prompt.choice_at(0.0, gap_y) is None

    def test_a_tap_beside_the_rows_picks_nothing(self) -> None:
        prompt = exit_prompt(ROUND_LIVE)
        rect = prompt.rect_for(0)
        assert prompt.choice_at(rect.max_x_mm + 10.0, rect.centre_y_mm) is None

    def test_rows_stay_on_the_display(self) -> None:
        """Every row is inside the picture, for the default table."""
        display = RectMM(941.0, 529.0)
        for prompt in prompts():
            for index in range(len(prompt.choices)):
                rect = prompt.rect_for(index)
                assert display.contains(rect.min_x_mm, rect.min_y_mm)
                assert display.contains(rect.max_x_mm, rect.max_y_mm)


class TestPromptValidation:
    def test_a_prompt_needs_a_choice(self) -> None:
        with pytest.raises(ValueError):
            Prompt("TITLE", "", ())

    def test_a_prompt_cannot_ask_for_more_rows_than_exist(self) -> None:
        too_many = tuple(
            Choice(str(i), f"ROW {i}", "cancel") for i in range(MAX_CHOICES + 1)
        )
        with pytest.raises(ValueError):
            Prompt("TITLE", "", too_many)

    def test_two_choices_cannot_share_a_key(self) -> None:
        with pytest.raises(ValueError):
            Prompt(
                "TITLE",
                "",
                (Choice("1", "ONE", "cancel"), Choice("1", "TWO", "quit")),
            )

    def test_an_unknown_action_is_refused(self) -> None:
        """The app dispatches on these strings, so a typo must not be quiet."""
        with pytest.raises(ValueError):
            Choice("1", "LAUNCH", "set_fire_to_the_cabinet")


def test_every_action_a_prompt_can_produce_is_a_known_action() -> None:
    assert actions_of(prompts()) <= ACTIONS


def test_the_app_handles_every_action() -> None:
    """Mirrors the dispatch in ``whack_a_mole.main``.

    The real dispatch cannot be imported without building a window, so this
    is the list it is written against -- and the ``else: raise`` there is
    what catches an action this list forgets.
    """
    handled = {"resume", "cancel", "play_again", "end_round", "menu", "quit"}
    assert ACTIONS == handled


def test_escape_backs_out_of_every_prompt() -> None:
    """``ESC`` must always do something harmless.

    Prompts with a resume/cancel row back out through it; a finished round
    has no such row, and :meth:`ConfirmDialog.key` synthesises a ``cancel``
    for that case -- which is only safe while ``cancel`` is in
    :data:`ACTIONS` and the app treats it as "change nothing".
    """
    assert "cancel" in ACTIONS
    for prompt in prompts():
        backs_out = [
            c for c in prompt.choices if c.action in ("resume", "cancel")
        ]
        assert len(backs_out) <= 1, "two ways back would be ambiguous"


class TestPlane:
    def test_the_dialog_sits_above_the_menu_it_covers(self) -> None:
        assert CONFIRM_Z_MM > MENU_Z_MM

    @pytest.mark.parametrize(
        "eye",
        [Eye(0.0, 0.0, 700.0), Eye(-520.0, 0.0, 620.0), Eye(0.0, -420.0, 520.0)],
        ids=lambda e: f"eye{e.x:.0f},{e.y:.0f}",
    )
    @pytest.mark.parametrize("index", range(3))
    def test_a_tap_where_a_row_looks_picks_that_row(
        self, eye: Eye, index: int
    ) -> None:
        """The same correction the menu needs, and further up.

        A touch is reported on the glass. The dialog floats
        :data:`CONFIRM_Z_MM` above it, so testing a glass point against the
        rows' own coordinates puts every row off by more than the menu's
        error -- the higher the panel, the bigger the parallax.
        """
        prompt = exit_prompt(ROUND_LIVE)
        rect = prompt.rect_for(index)
        seen = plane_mm_to_glass_mm(
            rect.centre_x_mm, rect.centre_y_mm, CONFIRM_Z_MM, eye
        )
        aimed = glass_mm_to_plane_mm(seen[0], seen[1], CONFIRM_Z_MM, eye)
        assert prompt.choice_at(*aimed) is prompt.choices[index]

    def test_without_the_conversion_an_off_axis_tap_misses(self) -> None:
        """Guard the guard: with a no-op conversion the test above is empty."""
        eye = Eye(0.0, -420.0, 520.0)
        prompt = exit_prompt(ROUND_LIVE)
        rect = prompt.rect_for(0)
        seen = plane_mm_to_glass_mm(
            rect.centre_x_mm, rect.centre_y_mm, CONFIRM_Z_MM, eye
        )
        assert prompt.choice_at(*seen) is not prompt.choices[0]
