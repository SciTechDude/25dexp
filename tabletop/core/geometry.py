"""Units, coordinate conventions, and rectangle math.

Everything in `tabletop.core` works in **millimetres**, with a
**centre origin**. This module is the single place those conventions are
defined; nothing here imports a renderer.

Table coordinate system
-----------------------
Origin is the centre of the display's visible image, on the glass surface.

    +X  to the right, looking down at the table from above
    +Y  away from the "home" edge (toward the far side of the table)
    +Z  up, out of the glass, toward the players

So a finger resting on the glass is ``z_mm == 0``, a hand hovering 80 mm
above it is ``z_mm == 80``, and content rendered *into* the display is at
negative Z. There is no such thing as a touch with negative Z.

Rendering uses a different handedness (see `tabletop.render.mapping`); the
conversion happens there and only there.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["RectMM", "Point3MM"]


@dataclass(frozen=True)
class Point3MM:
    """A point in table coordinates, millimetres."""

    x_mm: float
    y_mm: float
    z_mm: float = 0.0

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x_mm, self.y_mm, self.z_mm)


@dataclass(frozen=True)
class RectMM:
    """An axis-aligned rectangle in table coordinates, millimetres.

    ``centre_x_mm``/``centre_y_mm`` locate the rectangle's centre relative to
    the table origin. For the display rectangle these are 0 by definition --
    the display *is* the origin. For a touch area they are usually small
    non-zero values, because it is rarely perfectly concentric with the
    picture.
    """

    width_mm: float
    height_mm: float
    centre_x_mm: float = 0.0
    centre_y_mm: float = 0.0

    def __post_init__(self) -> None:
        if self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError(
                f"rectangle must have positive extent, got "
                f"{self.width_mm}x{self.height_mm} mm"
            )

    @property
    def half_width_mm(self) -> float:
        return self.width_mm / 2.0

    @property
    def half_height_mm(self) -> float:
        return self.height_mm / 2.0

    @property
    def aspect(self) -> float:
        return self.width_mm / self.height_mm

    @property
    def min_x_mm(self) -> float:
        return self.centre_x_mm - self.half_width_mm

    @property
    def max_x_mm(self) -> float:
        return self.centre_x_mm + self.half_width_mm

    @property
    def min_y_mm(self) -> float:
        return self.centre_y_mm - self.half_height_mm

    @property
    def max_y_mm(self) -> float:
        return self.centre_y_mm + self.half_height_mm

    def corners_mm(self) -> tuple[tuple[float, float], ...]:
        """The four corners, counter-clockwise from bottom-left."""
        return (
            (self.min_x_mm, self.min_y_mm),
            (self.max_x_mm, self.min_y_mm),
            (self.max_x_mm, self.max_y_mm),
            (self.min_x_mm, self.max_y_mm),
        )

    def contains(self, x_mm: float, y_mm: float) -> bool:
        return (
            self.min_x_mm <= x_mm <= self.max_x_mm
            and self.min_y_mm <= y_mm <= self.max_y_mm
        )

    def distance_to(self, x_mm: float, y_mm: float) -> float:
        """Distance from a point to this rectangle; 0 if inside it.

        For deciding whether a round thing overlaps a rectangular one --
        a mallet head and a button -- which is a comparison against the
        head's radius rather than a containment test.
        """
        dx = max(self.min_x_mm - x_mm, 0.0, x_mm - self.max_x_mm)
        dy = max(self.min_y_mm - y_mm, 0.0, y_mm - self.max_y_mm)
        return math.hypot(dx, dy)

    def normalise(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """Map a point inside this rectangle to [0, 1] x [0, 1].

        (0, 0) is the bottom-left corner. Values outside the rectangle are
        returned unclamped, so callers can detect out-of-range input.
        """
        u = (x_mm - self.min_x_mm) / self.width_mm
        v = (y_mm - self.min_y_mm) / self.height_mm
        return (u, v)

    def denormalise(self, u: float, v: float) -> tuple[float, float]:
        """Inverse of :meth:`normalise`."""
        x_mm = self.min_x_mm + u * self.width_mm
        y_mm = self.min_y_mm + v * self.height_mm
        return (x_mm, y_mm)
