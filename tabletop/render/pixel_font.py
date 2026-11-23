"""A 5x7 pixel font, built in code, for the game's own text.

Arcade text is a bitmap font with hard square pixels. Ursina's ``Text`` draws
an antialiased vector font, which reads as a desktop UI no matter what size
it is set at, and no pixel font ships with the project or with the OS -- so
the glyphs are defined here as bitmaps, baked into one texture atlas at
startup, and drawn as a quad per character.

Doing it this way also removes two problems the vector font had: the atlas
is monospaced, so columns line up without padding tricks, and a block of
several lines is centred by construction rather than hanging off its anchor.

Text is drawn upper-case. The glyph set covers A-Z, 0-9 and the punctuation
the game uses; anything else renders as a blank.
"""

from __future__ import annotations

from panda3d.core import PNMImage, SamplerState
from panda3d.core import Texture as PandaTexture
from ursina import Entity, Mesh, Texture, Vec3, color

from tabletop.render.mapping import mm_to_world, table_to_world
from tabletop.render.shaders import UNLIT_120

__all__ = [
    "GLYPH_W",
    "GLYPH_H",
    "PixelText",
    "font_texture",
    "text_mesh",
    "text_width_px",
]

GLYPH_W = 5
GLYPH_H = 7
CELL = 8
"""Atlas cell size. Larger than the glyph so neighbouring glyphs cannot
bleed into each other's edge texels."""

ADVANCE_PX = 6
"""Horizontal step per character: the glyph plus a one-pixel gap."""

LINE_PX = 9
"""Vertical step per line: the glyph plus a two-pixel gap."""

COLUMNS = 16

# One entry per glyph: seven rows of five columns, '#' for an inked pixel.
GLYPHS: dict[str, tuple[str, ...]] = {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("#####", "...#.", "..##.", "....#", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    ",": (".....", ".....", ".....", ".....", ".##..", ".##..", ".#..."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    ";": (".....", ".##..", ".##..", ".....", ".##..", ".##..", ".#..."),
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    "+": (".....", "..#..", "..#..", "#####", "..#..", "..#..", "....."),
    "=": (".....", ".....", "#####", ".....", "#####", ".....", "....."),
    "_": (".....", ".....", ".....", ".....", ".....", ".....", "#####"),
    "/": ("....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."),
    "\\": ("#....", "#....", ".#...", "..#..", "...#.", "....#", "....#"),
    "%": ("#...#", "#..#.", "...#.", "..#..", ".#...", ".#..#", "#...#"),
    "(": ("..##.", ".#...", "#....", "#....", "#....", ".#...", "..##."),
    ")": (".##..", "...#.", "....#", "....#", "....#", "...#.", ".##.."),
    "[": (".###.", ".#...", ".#...", ".#...", ".#...", ".#...", ".###."),
    "]": (".###.", "...#.", "...#.", "...#.", "...#.", "...#.", ".###."),
    "!": ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    "'": ("..#..", "..#..", ".....", ".....", ".....", ".....", "....."),
    '"': (".#.#.", ".#.#.", ".....", ".....", ".....", ".....", "....."),
    "*": (".....", "#.#.#", ".###.", "#####", ".###.", "#.#.#", "....."),
    "<": ("....#", "...#.", "..#..", ".#...", "..#..", "...#.", "....#"),
    ">": ("#....", ".#...", "..#..", "...#.", "..#..", ".#...", "#...."),
}

_ORDER = list(GLYPHS)
_INDEX = {char: i for i, char in enumerate(_ORDER)}
_ROWS = (len(_ORDER) + COLUMNS - 1) // COLUMNS

_texture: Texture | None = None


def atlas_size() -> tuple[int, int]:
    return (COLUMNS * CELL, _ROWS * CELL)


def font_texture() -> Texture:
    """The glyph atlas: white pixels, transparent background.

    Built once and cached. White on purpose: the unlit shader multiplies the
    texture by the entity's colour, so one atlas serves every colour.
    """
    global _texture
    if _texture is not None:
        return _texture

    width, height = atlas_size()
    image = PNMImage(width, height, 4)
    image.fill(1.0, 1.0, 1.0)
    image.alpha_fill(0.0)

    for char, rows in GLYPHS.items():
        index = _INDEX[char]
        ox = (index % COLUMNS) * CELL
        oy = (index // COLUMNS) * CELL
        for y, row in enumerate(rows):
            for x, cell in enumerate(row):
                if cell == "#":
                    image.set_alpha(ox + x, oy + y, 1.0)

    panda_texture = PandaTexture("pixel_font")
    panda_texture.load(image)
    # Nearest filtering, or the pixels blur into a soft vector-ish font and
    # the whole point is lost.
    panda_texture.set_magfilter(SamplerState.FT_nearest)
    panda_texture.set_minfilter(SamplerState.FT_nearest)
    _texture = Texture(panda_texture)
    return _texture


def _uv(char: str) -> tuple[float, float, float, float] | None:
    """``(u0, v0, u1, v1)`` for a glyph, or None if it is blank."""
    index = _INDEX.get(char)
    if index is None or char == " ":
        return None
    width, height = atlas_size()
    ox = (index % COLUMNS) * CELL
    oy = (index // COLUMNS) * CELL
    u0 = ox / width
    u1 = (ox + GLYPH_W) / width
    # PNMImage row 0 is the top row, texture v=0 is the bottom edge.
    v1 = 1.0 - oy / height
    v0 = 1.0 - (oy + GLYPH_H) / height
    return (u0, v0, u1, v1)


def text_width_px(text: str) -> int:
    """Width of the longest line, in font pixels."""
    lines = text.upper().split("\n")
    longest = max((len(line) for line in lines), default=0)
    return max(0, longest * ADVANCE_PX - (ADVANCE_PX - GLYPH_W))


def text_height_px(text: str) -> int:
    if not text:
        return 0
    lines = text.split("\n")
    return max(0, len(lines) * LINE_PX - (LINE_PX - GLYPH_H))


def text_mesh(
    text: str,
    pixel_mm: float,
    origin: tuple[float, float] = (0.0, 0.0),
) -> Mesh | None:
    """One quad per inked character, in the entity's local XY plane.

    ``pixel_mm`` is the size of one font pixel, so a line is
    ``GLYPH_H * pixel_mm`` tall. ``origin`` works like Ursina's: (0, 0)
    centres the whole block, (-0.5, 0) left-aligns it, (0.5, 0) right-aligns
    it. Returns None for text with nothing to draw.
    """
    lines = text.upper().split("\n")
    unit = mm_to_world(pixel_mm)

    block_w = text_width_px(text) * unit
    block_h = text_height_px(text) * unit
    # Shift so the block straddles the anchor according to origin.
    x_shift = -block_w * (0.5 + origin[0])
    y_shift = block_h * (0.5 - origin[1])

    vertices: list[Vec3] = []
    uvs: list[tuple[float, float]] = []
    triangles: list[int] = []

    for row, line in enumerate(lines):
        top = y_shift - row * LINE_PX * unit
        for column, char in enumerate(line):
            uv = _uv(char)
            if uv is None:
                continue
            u0, v0, u1, v1 = uv
            left = x_shift + column * ADVANCE_PX * unit
            right = left + GLYPH_W * unit
            bottom = top - GLYPH_H * unit

            start = len(vertices)
            vertices.extend(
                [
                    Vec3(left, bottom, 0.0),
                    Vec3(right, bottom, 0.0),
                    Vec3(right, top, 0.0),
                    Vec3(left, top, 0.0),
                ]
            )
            uvs.extend([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
            triangles.extend(
                [start, start + 1, start + 2, start, start + 2, start + 3]
            )

    if not vertices:
        return None
    return Mesh(vertices=vertices, triangles=triangles, uvs=uvs, mode="triangle")


class PixelText(Entity):
    """Arcade-style text. Set :attr:`text` to change it.

    Lies flat on the table by default, upright for a viewer at the near
    edge, which is how the rest of the scenery is oriented.
    """

    def __init__(
        self,
        text: str = "",
        pixel_mm: float = 2.0,
        origin: tuple[float, float] = (0.0, 0.0),
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        z_mm: float = 0.0,
        rotation_deg: float = 0.0,
        colour=color.white,
        **kwargs,
    ) -> None:
        super().__init__(
            position=Vec3(*table_to_world(x_mm, y_mm, z_mm)),
            rotation=(90.0, rotation_deg, 0.0),
            texture=font_texture(),
            shader=UNLIT_120,
            color=colour,
            double_sided=True,
            **kwargs,
        )
        self.pixel_mm = pixel_mm
        self.text_origin = origin
        self._text = ""
        self.text = text

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        if value == self._text:
            # Rebuilding a mesh every frame for unchanged text is the one
            # expensive mistake available here: the scoreboard updates on
            # every tick but changes only when a figure does.
            return
        self._text = value
        mesh = text_mesh(value, self.pixel_mm, self.text_origin)
        if mesh is None:
            self.visible_self = False
            return
        self.visible_self = True
        self.model = mesh
        # Assigning a model resets colour and texture on the new node.
        self.texture = font_texture()
        self.color = self.color

    def move_to(self, x_mm: float, y_mm: float, z_mm: float) -> None:
        self.position = Vec3(*table_to_world(x_mm, y_mm, z_mm))
