"""Panda3D configuration that must be applied *before* Ursina is imported.

Import this module first in anything that touches the renderer::

    from tabletop.render import platform_setup  # noqa: F401
    from ursina import ...

Ursina configures Panda3D at import time (it calls ``loadPrcFileData`` from
``ursina/window.py``), so any setting we need has to be in place before that
happens. Importing out of order fails silently -- you get a window, and
subtly worse rendering, with no error.

macOS and GLSL versions
-----------------------
We deliberately **do not** request an OpenGL core profile here, even though
it would unlock newer GLSL. The reasoning is worth recording, because the
obvious change is the wrong one:

Apple never shipped GL 3.0 or 3.1, so on macOS the only GLSL versions that
exist are 120 (legacy 2.1 compatibility context) and 150 (3.2+ core
context). GLSL 130 and 140 can never compile. Ursina's shaders are mostly
130/140 -- including ``unlit_with_fog_shader``, the default for every
``Entity``, and the ``text_shader`` that ``Text`` hardcodes.

In a compatibility context those failures are survivable: Panda3D falls
back to the fixed-function pipeline and the geometry still draws. Requesting
a core profile to get GLSL 150 *removes that safety net* -- core has no
fixed-function pipeline, so anything whose shader fails to compile draws
nothing at all. Asking for a core profile therefore blanks most of the
scene, which is exactly what it did here before this was understood.

The fix lives in :mod:`tabletop.render.shaders` instead: the project ships
its own GLSL 120 shaders and installs them as the default. 120 is the
common denominator across macOS 2.1 and Linux compatibility contexts, so
both platforms run identical shader code.
"""

from __future__ import annotations

import sys
from pathlib import Path

from panda3d.core import loadPrcFileData

__all__ = ["configure_panda", "PLATFORM_NOTES", "window_icon_path"]

PLATFORM_NOTES: list[str] = []
_configured = False


def configure_panda() -> list[str]:
    """Apply platform-specific Panda3D settings. Idempotent.

    Returns human-readable notes about what was applied, so an app can
    show them rather than leaving the user guessing why rendering differs
    between platforms.
    """
    global _configured
    if _configured:
        return PLATFORM_NOTES

    if sys.platform == "darwin":
        PLATFORM_NOTES.append(
            "macOS: using the OpenGL 2.1 compatibility context (GLSL 120). "
            "A core profile would allow newer GLSL but removes the "
            "fixed-function fallback, blanking anything whose shader fails "
            "to compile. Project shaders are GLSL 120 for this reason."
        )

    # Ursina ships a window icon it cannot always locate once the asset
    # folder points at an app module's directory; the resulting error is
    # pure noise. Suppressing the loader's complaints keeps genuine shader
    # and display errors visible.
    loadPrcFileData("tabletop", "notify-level-util error")
    loadPrcFileData("tabletop", "notify-level-pnmimage error")

    _configured = True
    return PLATFORM_NOTES


def window_icon_path() -> str:
    """Absolute path to Ursina's window icon, or "" if unavailable.

    Ursina's default is the relative path ``textures/ursina.ico``, resolved
    against the asset folder. Launching with ``python -m tabletop.apps.X``
    sets the asset folder to that module's directory, where the icon is not,
    so Panda logs a load error on every start. Passing an absolute path
    removes the noise.
    """
    try:
        import ursina  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return ""

    icon = Path(ursina.__file__).parent / "textures" / "ursina.ico"
    return str(icon) if icon.exists() else ""


# Applied on import, because the whole purpose is to run before Ursina's own
# import-time configuration.
configure_panda()
