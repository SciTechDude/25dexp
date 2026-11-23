"""Static guard against Ursina's 0-1 vs 0-255 colour trap.

This is the bug that produced blank-looking demos, and it is worth a test
because it fails *silently and catastrophically*: there is no exception, no
warning, and the only symptom is a wrong picture.

In Ursina 8.3::

    color.rgb   is an alias for color.rgba   -> expects 0.0-1.0 floats
    color.rgb32 is an alias for color.rgba32 -> expects 0-255 integers

Passing 0-255 values to ``color.rgb`` yields e.g. ``Color(40.0, 70.0, 95.0,
190.0)``, which clamps to opaque white. A table surface written that way
becomes a large white quad covering the whole board, which is
indistinguishable from "the renderer is broken" and sent earlier debugging
down entirely the wrong path (a core OpenGL profile, Ursina's macOS
support) before the real cause was found.

So: scan the source for the 0-1 variants being handed obviously-0-255
arguments. No graphics context required, which is the point -- this catches
the mistake in milliseconds instead of via a screenshot.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "tabletop"

# color.rgb( / color.rgba( but NOT color.rgb32( / color.rgba32(
UNSCALED_CALL = re.compile(r"color\.rgba?\(\s*([^)]*)\)")


def source_files() -> list[Path]:
    return sorted(SOURCE_DIR.rglob("*.py"))


def test_source_tree_was_found() -> None:
    """Guard the guard: a path typo would make every assertion below pass
    trivially by scanning nothing."""
    files = source_files()
    assert len(files) >= 10, f"expected the package, found {len(files)} files"


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_no_0_255_values_passed_to_0_1_colour_helpers(path: Path) -> None:
    text = path.read_text()

    for match in UNSCALED_CALL.finditer(text):
        args = match.group(1)
        numbers = [
            float(n) for n in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)", args)
        ]
        offenders = [n for n in numbers if n > 1.0]
        assert not offenders, (
            f"{path.relative_to(PROJECT_ROOT)}: "
            f"`color.rgb(...)`/`color.rgba(...)` expect 0.0-1.0 floats, but "
            f"got {offenders} in `{match.group(0)}`. Values above 1 clamp to "
            f"opaque white, which silently renders a blank-looking scene. "
            f"Use color.rgb32(...) / color.rgba32(...) for 0-255 values."
        )


def test_project_uses_the_0_255_variants_somewhere() -> None:
    """Sanity check that the fix is actually in place, rather than the test
    passing because all colour calls were removed."""
    combined = "\n".join(p.read_text() for p in source_files())
    assert "color.rgb32(" in combined or "color.rgba32(" in combined
