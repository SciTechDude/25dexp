"""Confirmation dialog for leaving a round or the application.

Why this exists
---------------
The EXIT button sits on the glass, inside the playfield's reach, and a
swing that lands on it used to close the window outright -- mid-round, with
the score gone. No arcade cabinet behaves that way: a live game asks before
it ends, and the cabinet's own exit is a second, separate confirmation.

So EXIT (and ``ESC``) now opens this dialog, and what it offers depends on
what is happening:

* a round in progress  -> resume, end the round, or leave the game
* a finished round      -> play again, back to the menu, or leave the game
* the start menu        -> leave the game, or go back

Drawn on the table in millimetres like :mod:`tabletop.render.menu`, for the
same two reasons: a panel on the glass is what a player reaches for on a
touch table, and world-space geometry is the only thing the headless
capture can verify.

The split here is deliberate: :func:`exit_prompt` and :class:`Prompt` are
plain data with no Ursina in them, so what the dialog offers and where its
rows are can be tested without a graphics context.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ursina import Entity, Vec3, Vec4

from tabletop.core.geometry import RectMM
from tabletop.render.mapping import mm_to_world, table_to_world
from tabletop.render.menu import MENU_Z_MM, pixel_mm
from tabletop.render.pixel_font import PixelText
from tabletop.render.shaders import UNLIT_120
from tabletop.render.theme import ARCADE, BezelFinish

__all__ = [
    "Choice",
    "Prompt",
    "ConfirmDialog",
    "exit_prompt",
    "actions_of",
    "ACTIONS",
    "ROUND_LIVE",
    "ROUND_OVER",
    "MENU",
    "CONFIRM_Z_MM",
]

CONFIRM_Z_MM = MENU_Z_MM + 40.0
"""Height of the dialog plane above the glass.

Above :data:`~tabletop.render.menu.MENU_Z_MM` on purpose: the dialog is
asked for from the menu as well as from a round, and a modal panel that
intersected the menu it covers would be worse than useless.
"""

ROW_WIDTH_MM = 460.0
ROW_HEIGHT_MM = 44.0
ROW_TOP_Y_MM = 34.0
"""Centre height of the first choice row."""
ROW_STEP_MM = 54.0
"""Centre-to-centre spacing, so rows have 10 mm between them."""

MAX_CHOICES = 3
"""Rows the dialog has geometry for.

Three is also as many as a player should have to read with a mallet in
hand, so this is a design limit rather than only a technical one.
"""

ROUND_LIVE = "round_live"
ROUND_OVER = "round_over"
MENU = "menu"
"""The three states EXIT can be pressed in."""

ACTIONS = frozenset(
    {"resume", "cancel", "end_round", "play_again", "menu", "quit"}
)
"""Every action a choice can carry, so a caller's dispatch can be checked
for completeness. ``resume`` and ``cancel`` both mean "close this and
change nothing" -- they are separate only because the row that does it
reads differently in a round than in the menu."""


@dataclass(frozen=True)
class Choice:
    """One row: a number to press, what it says, and what it does."""

    key: str
    label: str
    action: str
    blurb: str = ""

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action {self.action!r}")


@dataclass(frozen=True)
class Prompt:
    """What the dialog shows, and where its rows are."""

    title: str
    subtitle: str
    choices: tuple[Choice, ...]

    def __post_init__(self) -> None:
        if not self.choices:
            raise ValueError("a prompt needs at least one choice")
        if len(self.choices) > MAX_CHOICES:
            raise ValueError(
                f"the dialog has {MAX_CHOICES} rows, got {len(self.choices)}"
            )
        keys = [choice.key for choice in self.choices]
        if len(set(keys)) != len(keys):
            raise ValueError(f"two choices share a key: {keys}")

    def rect_for(self, index: int) -> RectMM:
        """The tappable rectangle of the row at ``index``, in table mm."""
        return RectMM(
            ROW_WIDTH_MM,
            ROW_HEIGHT_MM,
            0.0,
            ROW_TOP_Y_MM - index * ROW_STEP_MM,
        )

    def choice_for_key(self, key: str) -> Choice | None:
        for choice in self.choices:
            if choice.key == key:
                return choice
        return None

    def choice_at(self, x_mm: float, y_mm: float) -> Choice | None:
        """The choice under a point in table millimetres, if any."""
        for index, choice in enumerate(self.choices):
            if self.rect_for(index).contains(x_mm, y_mm):
                return choice
        return None


def exit_prompt(
    state: str,
    *,
    score: int | None = None,
    accuracy: float | None = None,
) -> Prompt:
    """The prompt for pressing EXIT in ``state``.

    ``score`` and ``accuracy`` are only read for :data:`ROUND_OVER`, where
    the dialog repeats the tally it is covering -- the player is deciding
    whether to go again, and that is the number they decide on.
    """
    if state == ROUND_LIVE:
        return Prompt(
            title="PAUSED",
            subtitle="THE ROUND IS WAITING",
            choices=(
                Choice("1", "RESUME ROUND", "resume", "back to the moles"),
                Choice("2", "END ROUND", "end_round", "stop, back to the menu"),
                Choice("3", "EXIT GAME", "quit", "close the application"),
            ),
        )
    if state == ROUND_OVER:
        tally = ""
        if score is not None:
            tally = f"SCORE {score}"
            if accuracy is not None:
                tally += f"   ACCURACY {accuracy * 100:.0f}%"
        return Prompt(
            title="ROUND OVER",
            subtitle=tally,
            choices=(
                Choice("1", "PLAY AGAIN", "play_again", "same difficulty"),
                Choice("2", "BACK TO MENU", "menu", "pick a difficulty"),
                Choice("3", "EXIT GAME", "quit", "close the application"),
            ),
        )
    if state == MENU:
        return Prompt(
            title="EXIT GAME?",
            subtitle="THE TOP SCORE IS NOT KEPT",
            choices=(
                Choice("1", "EXIT GAME", "quit", "close the application"),
                Choice("2", "BACK", "cancel", "stay in the menu"),
            ),
        )
    raise ValueError(f"unknown state {state!r}")


class ConfirmDialog(Entity):
    """The dialog itself. :meth:`ask` shows it, :meth:`close` takes it away.

    Geometry for :data:`MAX_CHOICES` rows is built once and re-used, because
    a dialog that rebuilt its text entities would churn meshes on a frame
    the player is waiting through.
    """

    def __init__(
        self,
        display_width_mm: float = 941.0,
        display_height_mm: float = 529.0,
        finish: BezelFinish = ARCADE,
    ) -> None:
        super().__init__()
        self.finish = finish
        self.prompt: Prompt | None = None
        self._on_choice: Callable[[str], None] | None = None

        self._armed = False
        """Whether input is accepted yet.

        False for the frame the dialog opens on. The key or tap that asks
        for the dialog is still being dispatched when it appears, and
        without this the ``ESC`` that opened it would also dismiss it.
        """

        def text(
            line_mm: float,
            y_mm: float,
            colour,
            origin: tuple[float, float] = (0.0, 0.0),
            x_mm: float = 0.0,
        ) -> PixelText:
            return PixelText(
                text="",
                pixel_mm=pixel_mm(line_mm),
                origin=origin,
                x_mm=x_mm,
                y_mm=y_mm,
                z_mm=CONFIRM_Z_MM + 1.0,
                colour=colour,
            )

        self.backdrop = Entity(
            model="quad",
            scale=(
                mm_to_world(display_width_mm),
                mm_to_world(display_height_mm),
            ),
            position=Vec3(*table_to_world(0.0, 0.0, CONFIRM_Z_MM)),
            rotation=(90.0, 0.0, 0.0),
            # More opaque than the menu's: this one is a stop, and the
            # field behind it must not read as still playable.
            color=self._backdrop_color(),
            shader=UNLIT_120,
            double_sided=True,
        )

        self.title = text(24.0, 120.0, finish.inlay)
        self.subtitle = text(10.0, 86.0, finish.dim_text)
        self.footer = text(9.0, -132.0, finish.dim_text)

        self._plates: list[Entity] = []
        self._labels: list[PixelText] = []
        self._blurbs: list[PixelText] = []
        for index in range(MAX_CHOICES):
            y = ROW_TOP_Y_MM - index * ROW_STEP_MM
            self._plates.append(
                Entity(
                    model="quad",
                    scale=(
                        mm_to_world(ROW_WIDTH_MM),
                        mm_to_world(ROW_HEIGHT_MM),
                    ),
                    position=Vec3(*table_to_world(0.0, y, CONFIRM_Z_MM + 0.5)),
                    rotation=(90.0, 0.0, 0.0),
                    color=finish.surface,
                    shader=UNLIT_120,
                    double_sided=True,
                )
            )
            self._labels.append(
                text(
                    16.0,
                    y,
                    finish.text,
                    origin=(-0.5, 0.0),
                    x_mm=-ROW_WIDTH_MM / 2.0 + 18.0,
                )
            )
            self._blurbs.append(
                text(
                    9.0,
                    y,
                    finish.dim_text,
                    origin=(0.5, 0.0),
                    x_mm=ROW_WIDTH_MM / 2.0 - 18.0,
                )
            )

        self.close()

    # ------------------------------------------------------------------

    def _backdrop_color(self) -> Vec4:
        band = self.finish.band
        return Vec4(band[0], band[1], band[2], 0.97)

    @property
    def visible(self) -> bool:
        return self.backdrop.enabled

    @property
    def plane_z_mm(self) -> float:
        """Height of the dialog above the glass, for hit-testing a tap."""
        return CONFIRM_Z_MM

    def set_finish(self, finish: BezelFinish) -> None:
        """Re-colour to a new bezel finish, like the menu does."""
        self.finish = finish
        self.backdrop.color = self._backdrop_color()
        self.title.color = finish.inlay
        self.subtitle.color = finish.dim_text
        self.footer.color = finish.dim_text
        for plate in self._plates:
            plate.color = finish.surface
        for blurb in self._blurbs:
            blurb.color = finish.dim_text
        self._paint_labels()

    def _paint_labels(self) -> None:
        """Colour each label by what its row does.

        ``quit`` takes the inlay colour, the same flag the menu puts on its
        exit row, so the irreversible choice does not look like the others.
        """
        if self.prompt is None:
            return
        for index, choice in enumerate(self.prompt.choices):
            self._labels[index].color = (
                self.finish.inlay if choice.action == "quit" else self.finish.text
            )

    # ------------------------------------------------------------------

    def ask(self, prompt: Prompt, on_choice: Callable[[str], None]) -> None:
        """Show ``prompt``; call ``on_choice`` with the chosen action."""
        self.prompt = prompt
        self._on_choice = on_choice
        self._armed = False

        self.title.text = prompt.title
        self.subtitle.text = prompt.subtitle
        self.footer.text = "TAP A ROW OR PRESS ITS NUMBER      [ESC] BACK"

        for index in range(MAX_CHOICES):
            used = index < len(prompt.choices)
            self._plates[index].enabled = used
            self._labels[index].enabled = used
            self._blurbs[index].enabled = used
            if used:
                choice = prompt.choices[index]
                self._labels[index].text = f"{choice.key}   {choice.label}"
                self._blurbs[index].text = choice.blurb
        self._paint_labels()

        self.backdrop.enabled = True
        self.title.enabled = True
        self.subtitle.enabled = bool(prompt.subtitle)
        self.footer.enabled = True

    def close(self) -> None:
        self.prompt = None
        self._on_choice = None
        self._armed = False
        self.backdrop.enabled = False
        for part in (
            self.title,
            self.subtitle,
            self.footer,
            *self._plates,
            *self._labels,
            *self._blurbs,
        ):
            part.enabled = False

    def update(self) -> None:
        # One frame of deafness after opening; see `_armed`.
        if self.visible:
            self._armed = True

    # ------------------------------------------------------------------

    def _choose(self, choice: Choice | None) -> bool:
        if choice is None:
            return False
        on_choice = self._on_choice
        # Read before closing: close() drops the callback, and a handler
        # that re-opens the dialog must not be undone by this one.
        self.close()
        if on_choice is not None:
            on_choice(choice.action)
        return True

    def key(self, key: str) -> bool:
        """Apply a keypress. True if the dialog consumed it.

        Everything is consumed while the dialog is up, including keys it
        does nothing with: a modal panel that let ``T`` change the theme
        underneath it would not be modal.
        """
        if not self.visible or self.prompt is None:
            return False
        if not self._armed:
            # Consumed, but too early to act on: this is the keypress that
            # asked for the dialog, still being dispatched.
            return True
        if key.endswith(" up"):
            return True
        if key == "escape":
            # Escape takes the gentlest way out: back to the round, or back
            # to the menu. Never the quit -- that has to be chosen.
            #
            # A prompt without such a row (a finished round offers only
            # ways forward) still backs out, through a choice made here, so
            # that the caller always hears something and can undo whatever
            # it did to put the dialog up -- the pause, in particular.
            cancels = [
                choice
                for choice in self.prompt.choices
                if choice.action in ("resume", "cancel")
            ]
            return self._choose(
                cancels[0]
                if cancels
                else Choice("escape", "BACK", "cancel")
            )
        self._choose(self.prompt.choice_for_key(key))
        return True

    def hit(self, x_mm: float, y_mm: float) -> bool:
        """Apply a tap at a point on the dialog's plane, in table mm."""
        if not self.visible or self.prompt is None or not self._armed:
            return False
        return self._choose(self.prompt.choice_at(x_mm, y_mm))

    def ask_for_state(
        self,
        state: str,
        on_choice: Callable[[str], None],
        *,
        score: int | None = None,
        accuracy: float | None = None,
    ) -> None:
        """:meth:`ask` with the prompt :func:`exit_prompt` gives for ``state``."""
        self.ask(exit_prompt(state, score=score, accuracy=accuracy), on_choice)


def actions_of(prompts: Sequence[Prompt]) -> set[str]:
    """Every action these prompts can produce. For checking a dispatch."""
    return {choice.action for prompt in prompts for choice in prompt.choices}
