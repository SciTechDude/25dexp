"""The one place table coordinates become renderer coordinates.

Keeping this conversion in a single module is what lets the rest of the
codebase stay renderer-agnostic. :mod:`tabletop.core` never imports Ursina;
it speaks millimetres on the table's axes. Ursina speaks world units on
Panda3D's axes. The translation happens here and nowhere else, so swapping
Ursina out later means rewriting this file and the adapter beside it, not
hunting axis flips through game logic.

Axis mapping
------------
The table's coordinate system (see :mod:`tabletop.core.geometry`) is
Z-up-out-of-the-glass. Panda3D and Ursina are Y-up with +Z forward. For a
display lying flat and viewed from above:

    table +X (right)             -> world +X
    table +Y (away from player)  -> world +Z
    table +Z (up out of glass)   -> world +Y

So the glass surface is the world ``y = 0`` plane, recessed content lives at
negative world Y, and the camera sits at positive world Y looking straight
down. That matches the convention the design notes arrived at, just stated
once, formally, instead of in a comment.

Scale
-----
Working in raw millimetres inside the engine makes for awkward numbers
(a table is ~941 units wide, lights and default entity scales are tuned for
single digits). One world unit is therefore 100 mm, which puts a table at
roughly 9 x 5 world units -- comfortable for Ursina's defaults.
"""

from __future__ import annotations

__all__ = [
    "MM_PER_WORLD_UNIT",
    "mm_to_world",
    "world_to_mm",
    "table_to_world",
    "world_to_table",
    "TOP_DOWN_CAMERA_ROTATION",
]

MM_PER_WORLD_UNIT = 100.0

TOP_DOWN_CAMERA_ROTATION = (90.0, 0.0, 0.0)
"""Pitch that aims the camera straight down at the glass.

With this rotation the camera's own axes line up with the table's: its
right-hand axis is table +X and its up axis is table +Y. That alignment is
what lets the lens film offset be fed table-space eye coordinates directly
(see :class:`tabletop.render.projection.LensParams`).

**The camera must never be re-aimed.** No ``look_at`` in the update loop:
rotating the camera to follow the viewer is precisely the mistake that turns
a window effect into a swinging scene. The eye moves, the lens shears, the
aim stays fixed.
"""


def mm_to_world(mm: float) -> float:
    return mm / MM_PER_WORLD_UNIT


def world_to_mm(units: float) -> float:
    return units * MM_PER_WORLD_UNIT


def table_to_world(
    x_mm: float, y_mm: float, z_mm: float = 0.0
) -> tuple[float, float, float]:
    """Table millimetres to Ursina world units.

    Returns ``(world_x, world_y, world_z)`` ready for an Ursina ``Vec3``.
    Note the swap: the table's height axis becomes world Y, and the table's
    "away" axis becomes world Z.
    """
    return (
        mm_to_world(x_mm),
        mm_to_world(z_mm),
        mm_to_world(y_mm),
    )


def world_to_table(
    world_x: float, world_y: float, world_z: float
) -> tuple[float, float, float]:
    """Inverse of :func:`table_to_world`, returning ``(x_mm, y_mm, z_mm)``."""
    return (
        world_to_mm(world_x),
        world_to_mm(world_z),
        world_to_mm(world_y),
    )
