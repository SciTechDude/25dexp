"""Art asset loading.

Textures live in ``assets/`` at the repo root, not beside the app modules.
Ursina resolves bare texture names against its own asset folders, which
``python -m tabletop.apps.X`` sets to that module's directory -- so a plain
name or an absolute path string both silently fail to bind, leaving the
surface untextured and flat-coloured. Constructing ``Texture(Path)``
explicitly is what actually works, which is why loading goes through here
rather than through ``Entity(texture=...)`` strings.
"""

from __future__ import annotations

from pathlib import Path

from panda3d.core import Texture as PandaTexture
from ursina import Texture

__all__ = [
    "ASSETS_DIR",
    "load",
    "MOLE_SPRITE",
    "MOLE_TURN_STRIP",
    "MOLE_TURN_FRAME_WIDTHS",
    "FIELD_TEXTURE",
    "available",
]

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"

MOLE_SPRITE = "mole_full.png"
FIELD_TEXTURE = "field_grass.jpg"

MOLE_TURN_STRIP = "mole_turn_strip.png"
"""Frames of the mole turning, over a mound that never moves.

Baked by ``tools/bake_mole_turn_strip.py`` from :data:`MOLE_SPRITE`. The
single sheet paints mole and mound together, so mirroring the card to face
the mole the other way mirrored the earth with it -- and the turn's spin
squeezed the dirt along with the animal. Separate quads cannot fix that
honestly, because the mound lies on the ground while the mole rises above
it, so from overhead the mole is always the nearer surface and no z value
puts the mound in front of it. Baking the pair together per frame does
fix it: the mound is the same pixels in every frame, so it cannot move.
"""

MOLE_TURN_FRAME_WIDTHS: tuple[float, ...] = (
    1.0,
    0.62,
    0.22,
    0.0,
    -0.22,
    -0.62,
    -1.0,
)
"""Signed width of the mole in each frame of :data:`MOLE_TURN_STRIP`.

The contract between the baked asset and the renderer, kept here so the
two cannot drift: the baking tool reads it to decide what to draw, and the
view reads it to decide which frame a given point in a turn wants.

Positive is the way the source artwork faces, negative is mirrored, and
the magnitude is how much of its width a card with no thickness shows at
that angle -- so 0.0 is edge-on and shows no mole at all.
"""


def available(name: str) -> bool:
    return (ASSETS_DIR / name).is_file()


def load(name: str, tile: bool = False) -> Texture | None:
    """Load a texture by file name, or return None if it is not present.

    Returning None rather than raising lets the game fall back to procedural
    geometry, so a missing asset degrades the look instead of preventing the
    thing from running at all.
    """
    path = ASSETS_DIR / name
    if not path.is_file():
        return None
    texture = Texture(path)
    if tile:
        # Explicitly repeat. Without this the wrap mode clamps, so every UV
        # past 1.0 samples the texture's edge pixel -- a tiled ground came
        # out as one flat dark colour across the whole field while rendering
        # perfectly in isolation at repeat=1.0, which is a confusing way to
        # lose two hours.
        texture._texture.set_wrap_u(PandaTexture.WM_repeat)
        texture._texture.set_wrap_v(PandaTexture.WM_repeat)
    return texture
