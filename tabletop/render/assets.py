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

__all__ = ["ASSETS_DIR", "load", "MOLE_SPRITE", "FIELD_TEXTURE", "available"]

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"

MOLE_SPRITE = "mole_full.png"
FIELD_TEXTURE = "field_grass.jpg"


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
