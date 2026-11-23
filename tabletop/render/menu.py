"""Start menu: pick a difficulty, or read the controls and the rules.

Drawn on the table, in millimetres, like the scoreboard rather than like a
screen-space HUD. Two reasons: a menu on the glass is what a player reaches
for on a touch table, and world-space geometry is the only thing the
headless capture can verify -- UI-space text does not appear in the
framebuffer copy at all, so a screen-space menu could not be checked.

The menu owns its layout but not the pointer: :meth:`hit` takes a point in
table millimetres and returns the row under it, so whatever converts a
contact into table coordinates stays in one place.

Rules text is generated from :class:`~tabletop.game.whack_a_mole.GameConfig`
so scoring and round length cannot drift from what the game does.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ursina import Entity, Vec3, Vec4

from tabletop.game.whack_a_mole import DIFFICULTIES, Difficulty, GameConfig
from tabletop.render.theme import ARCADE, BezelFinish
from tabletop.render.mapping import mm_to_world, table_to_world
from tabletop.render.pixel_font import PixelText
from tabletop.render.shaders import UNLIT_120

__all__ = ["StartMenu", "controls_columns", "rules_text"]

MENU_Z_MM = 150.0
"""Height of the menu plane above the glass: clear of the bezel and of a
fully risen mole, so nothing pokes through it."""

def pixel_mm(line_height_mm: float) -> float:
    """Font-pixel size that gives a glyph of this height, for
    :class:`~tabletop.render.pixel_font.PixelText`."""
    return line_height_mm / 7.0


LEVEL_BLURBS = {
    "beginner": "moles linger, few at a time",
    "medium": "the standard pace",
    "advanced": "fast, and crowded",
}

CONTROLS = [
    ("click", "swing the mallet"),
    ("right-drag", "move the viewer around the table"),
    ("arrows", "walk the viewer / eye height"),
    ("P", "head-parallax view"),
    ("D", "next difficulty (restarts the round)"),
    ("T", "theme: day / dusk / night"),
    ("B", "bezel finish"),
    ("F", "mole facing"),
    ("M", "sprite mirroring"),
    ("R", "restart the round"),
    ("TAB", "back to this menu"),
    ("ESC", "quit, or tap EXIT on the panel"),
]


def controls_columns() -> tuple[str, str]:
    """Keys and their descriptions, as two blocks for two aligned columns.

    Two columns rather than one padded string: the font is proportional, so
    space-padding a key column leaves it visibly ragged.
    """
    return (
        "\n".join(key for key, _ in CONTROLS),
        "\n".join(what for _, what in CONTROLS),
    )


def rules_text(config: GameConfig) -> str:
    return "\n".join(
        [
            "Moles pop out of the holes.",
            "Hit one before it drops back.",
            "",
            f"+{config.points_per_hit} for a hit.",
            f"{config.points_per_miss} for a tap on empty ground.",
            "Taps on the bezel and scoreboard do not count.",
            "",
            "A mole can be hit only once, and a mole still",
            "inside its hole cannot be hit at all.",
            "",
            f"A round lasts {config.round_length_s:.0f} s and gets faster",
            "and busier as it runs.",
            "",
            "TOP keeps the best score across rounds.",
        ]
    )


def _role_for(finish: BezelFinish, colour) -> str:
    """Which finish role a colour came from, so it can follow a change."""
    if colour is None or colour == finish.text:
        return "text"
    if colour == finish.inlay:
        return "inlay"
    if colour == finish.surface:
        return "surface"
    if colour == finish.band:
        return "band"
    return "dim_text"


@dataclass(frozen=True)
class Row:
    """A tappable row, as a rectangle in table millimetres."""

    action: str
    """``level`` or ``panel``."""

    value: object
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    def contains(self, x_mm: float, y_mm: float) -> bool:
        return (
            abs(x_mm - self.x_mm) <= self.width_mm / 2.0
            and abs(y_mm - self.y_mm) <= self.height_mm / 2.0
        )


class StartMenu(Entity):
    """The menu. Call :meth:`show` / :meth:`hide`; it holds no game state.

    ``on_start`` is called with the chosen :class:`Difficulty`.
    """

    ROW_WIDTH_MM = 440.0
    ROW_HEIGHT_MM = 42.0

    def __init__(
        self,
        config: GameConfig,
        on_start: Callable[[Difficulty], None],
        display_width_mm: float = 941.0,
        display_height_mm: float = 529.0,
        finish: BezelFinish = ARCADE,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.finish = finish
        """Palette, shared with the bezel so the menu matches the frame."""

        self.on_start = on_start
        self.on_quit = on_quit
        self.panel_mode: str | None = None
        """``controls``, ``rules``, or None for the level list."""

        self._list_parts: list[Entity] = []
        self._panel_parts: list[Entity] = []
        self.rows: list[Row] = []
        self._tinted: list[tuple[Entity, str]] = []
        """Each coloured part with the finish role it takes, so switching
        finish is a re-colour rather than a rebuild."""

        def flat_text(
            text: str,
            y_mm: float,
            line_mm: float,
            colour=None,
            origin=(0, 0),
            x_mm: float = 0.0,
        ) -> PixelText:
            role = _role_for(self.finish, colour)
            text_entity = PixelText(
                text=text,
                pixel_mm=pixel_mm(line_mm),
                origin=origin,
                x_mm=x_mm,
                y_mm=y_mm,
                z_mm=MENU_Z_MM + 1.0,
                colour=self.finish.text if colour is None else colour,
            )
            self._tinted.append((text_entity, role))
            return text_entity

        self.backdrop = Entity(
            model="quad",
            scale=(
                mm_to_world(display_width_mm),
                mm_to_world(display_height_mm),
            ),
            position=Vec3(*table_to_world(0.0, 0.0, MENU_Z_MM)),
            rotation=(90.0, 0.0, 0.0),
            # Nearly opaque: the menu is read, not played through.
            color=Vec4(
                self.finish.band[0],
                self.finish.band[1],
                self.finish.band[2],
                0.95,
            ),
            shader=UNLIT_120,
            double_sided=True,
        )

        self._list_parts.append(
            flat_text("WHACK-A-MOLE", 150.0, 26.0, self.finish.inlay)
        )
        self._list_parts.append(
            flat_text(
                "pick a difficulty",
                118.0,
                11.0,
                self.finish.dim_text,
            )
        )

        for index, level in enumerate(DIFFICULTIES):
            y = 60.0 - index * 50.0
            self.rows.append(
                Row(
                    "level",
                    level,
                    0.0,
                    y,
                    self.ROW_WIDTH_MM,
                    self.ROW_HEIGHT_MM,
                )
            )
            self._list_parts.append(
                Entity(
                    model="quad",
                    scale=(
                        mm_to_world(self.ROW_WIDTH_MM),
                        mm_to_world(self.ROW_HEIGHT_MM),
                    ),
                    position=Vec3(*table_to_world(0.0, y, MENU_Z_MM + 0.5)),
                    rotation=(90.0, 0.0, 0.0),
                    color=self.finish.surface,
                    shader=UNLIT_120,
                    double_sided=True,
                )
            )
            self._tinted.append((self._list_parts[-1], "surface"))
            self._list_parts.append(
                flat_text(
                    f"{index + 1}   {level.name.upper()}",
                    y,
                    16.0,
                    origin=(-0.5, 0),
                    x_mm=-self.ROW_WIDTH_MM / 2 + 18.0,
                )
            )
            self._list_parts.append(
                flat_text(
                    LEVEL_BLURBS.get(level.name, ""),
                    y,
                    9.0,
                    self.finish.dim_text,
                    origin=(0.5, 0),
                    x_mm=self.ROW_WIDTH_MM / 2 - 18.0,
                )
            )

        for label, action, value, x in (
            ("H   CONTROLS", "panel", "controls", -200.0),
            ("G   RULES", "panel", "rules", 0.0),
            ("ESC   EXIT", "quit", None, 200.0),
        ):
            colour = self.finish.inlay if action == "quit" else self.finish.text
            self._list_parts.append(
                flat_text(label, -110.0, 11.0, colour, x_mm=x)
            )
            self.rows.append(Row(action, value, x, -110.0, 170.0, 30.0))

        self._list_parts.append(
            flat_text(
                "[1] [2] [3] start      or tap a row",
                -152.0,
                9.0,
                self.finish.dim_text,
            )
        )

        self.panel_title = flat_text("", 150.0, 18.0, self.finish.inlay)
        self.panel_body = flat_text("", 112.0, 9.5, origin=(0, 0.5))
        self.panel_keys = flat_text(
            "",
            112.0,
            9.5,
            self.finish.dim_text,
            origin=(0.5, 0.5),
            x_mm=-8.0,
        )
        self.panel_defs = flat_text(
            "", 112.0, 9.5, origin=(-0.5, 0.5), x_mm=8.0
        )
        self.panel_footer = flat_text(
            "[any key] back", -158.0, 9.0, self.finish.dim_text
        )
        self._panel_parts = [
            self.panel_title,
            self.panel_body,
            self.panel_keys,
            self.panel_defs,
            self.panel_footer,
        ]

        self.hide()

    # ------------------------------------------------------------------

    def set_finish(self, finish: BezelFinish) -> None:
        """Re-colour to a new finish, so the menu matches the frame."""
        self.finish = finish
        for entity, role in self._tinted:
            entity.color = getattr(finish, role)
        self.backdrop.color = Vec4(
            finish.band[0], finish.band[1], finish.band[2], 0.95
        )

    @property
    def plane_z_mm(self) -> float:
        """Height of the menu above the glass, for hit-testing a tap."""
        return MENU_Z_MM

    @property
    def visible(self) -> bool:
        return self.backdrop.enabled

    def show(self) -> None:
        self.backdrop.enabled = True
        self.close_panel()

    def hide(self) -> None:
        self.backdrop.enabled = False
        for part in (*self._list_parts, *self._panel_parts):
            part.enabled = False

    def start(self, level: Difficulty) -> None:
        self.hide()
        self.on_start(level)

    # ------------------------------------------------------------------

    def open_panel(self, mode: str) -> None:
        self.panel_mode = mode
        self.backdrop.enabled = True
        for part in self._list_parts:
            part.enabled = False
        controls = mode == "controls"
        self.panel_title.text = "CONTROLS" if controls else "GAME RULES"
        if controls:
            self.panel_keys.text, self.panel_defs.text = controls_columns()
            self.panel_body.text = ""
        else:
            self.panel_body.text = rules_text(self.config)
            self.panel_keys.text = self.panel_defs.text = ""

        for part in self._panel_parts:
            part.enabled = True
        self.panel_body.enabled = not controls
        self.panel_keys.enabled = controls
        self.panel_defs.enabled = controls

    def close_panel(self) -> None:
        self.panel_mode = None
        for part in self._panel_parts:
            part.enabled = False
        for part in self._list_parts:
            part.enabled = True

    # ------------------------------------------------------------------

    def hit(self, x_mm: float, y_mm: float) -> bool:
        """Apply a tap at a table position. True if it did something."""
        if not self.visible:
            return False
        if self.panel_mode is not None:
            self.close_panel()
            return True

        for row in self.rows:
            if not row.contains(x_mm, y_mm):
                continue
            if row.action == "level":
                self.start(row.value)
            elif row.action == "quit":
                if self.on_quit:
                    self.on_quit()
            else:
                self.open_panel(row.value)
            return True
        return False

    def input(self, key: str) -> None:
        if not self.visible:
            return

        if self.panel_mode is not None:
            if key == "escape":
                if self.on_quit:
                    self.on_quit()
            elif not key.endswith(" up") and key != "left mouse down":
                self.close_panel()
            return

        if key in ("1", "2", "3"):
            index = int(key) - 1
            if index < len(DIFFICULTIES):
                self.start(DIFFICULTIES[index])
        elif key == "h":
            self.open_panel("controls")
        elif key == "g":
            self.open_panel("rules")
        elif key == "escape" and self.on_quit:
            self.on_quit()
