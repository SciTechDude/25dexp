"""A round mallet that follows the player's hand and swings when it strikes.

Driven by a position in **table millimetres** rather than by the mouse,
because a contact is a contact: the mouse and a finger on a touchscreen go
down the same path, and whichever it is, the mallet goes there and a tap
swings it.

Drawn flat, from overhead: a round striking face about the size of a hole,
with a handle running back toward the player. A circle and a stick read
unambiguously from directly above, where a rectangular head reads as a
paddle, and keeping it procedural means no art to load.

The swing is mostly a **dip in Z**. From directly above, rotation alone is
weak -- the mallet sweeps sideways and nothing says it came down -- while a
drop toward the glass and back is the one motion an overhead view reads as
a strike.
"""

from __future__ import annotations

import math

from ursina import Entity, Mesh, Vec3, color

from tabletop.render.mapping import mm_to_world, table_to_world
from tabletop.render.shaders import UNLIT_120

__all__ = ["MalletCursor", "swing_profile", "disc_xy_mesh", "SWING_TIME_S"]

HANDLE_LENGTH_MM = 62.0
HANDLE_WIDTH_MM = 11.0
HEAD_RADIUS_MM = 15.0
"""Striking face, well under half a hole across.

Deliberately smaller than the hole it hits. Sized to the hole, the head
covered the whole impact -- the splat and most of the droplets landed
underneath it and the hit looked like nothing had happened. A pointer only
has to say *where*, so it loses the argument with the effect it triggers,
and a short handle keeps the whole thing from sweeping across neighbouring
holes as it swings."""

OUTLINE_MM = 3.0


def disc_xy_mesh(radius_mm: float, segments: int = 24) -> Mesh:
    """A filled circle in the entity's local XY plane.

    Not :func:`tabletop.render.meshes.disc_mesh`, which builds a disc already
    oriented to the table: this one is local geometry, so the parent's
    rotation swings it.
    """
    radius = mm_to_world(radius_mm)
    centre = Vec3(0.0, 0.0, 0.0)
    rim = [
        Vec3(
            radius * math.cos(2.0 * math.pi * i / segments),
            radius * math.sin(2.0 * math.pi * i / segments),
            0.0,
        )
        for i in range(segments)
    ]

    vertices: list[Vec3] = []
    triangles: list[int] = []
    for i in range(segments):
        start = len(vertices)
        vertices.extend([centre, rim[i], rim[(i + 1) % segments]])
        triangles.extend([start, start + 1, start + 2])
    return Mesh(vertices=vertices, triangles=triangles, mode="triangle")

REST_Z_MM = 150.0
"""Height the mallet hovers at, held over the table."""

STRIKE_Z_MM = 86.0
"""Height at the bottom of the swing.

Still above a fully risen mole (78 mm) rather than down at the glass: the
mallet is in the player's hand, so it has to pass *over* the mole it hits.
Taken lower, the mole's own sprite draws on top of it and the strike looks
like the mallet went underneath.

The dip is 64 mm, which from a 700 mm eye also scales the mallet by about
10 percent -- a second cue that it came down, on top of the Z motion."""

REST_ANGLE_DEG = -24.0
"""In-plane angle at rest. Off-axis so the handle reads as a handle and not
as part of the head."""

STRIKE_ANGLE_DEG = 14.0

SWING_TIME_S = 0.17
"""Whole swing, down and back. Shorter than the struck mole's 120 ms
retract would hide the hit; much longer and the mallet lags the tap."""

DOWN_FRACTION = 0.42
"""Share of the swing spent travelling down. Faster down than up, which is
how a swung mass actually moves."""


def swing_profile(t: float) -> tuple[float, float]:
    """``(angle_deg, z_mm)`` at normalised swing time ``t``.

    Separate from the entity so the motion is testable without a window.
    """
    if t <= 0.0 or t >= 1.0:
        return (REST_ANGLE_DEG, REST_Z_MM)

    if t < DOWN_FRACTION:
        # Accelerating down, under the weight of the head.
        progress = (t / DOWN_FRACTION) ** 2
    else:
        # Lifting back, decelerating.
        up = (t - DOWN_FRACTION) / (1.0 - DOWN_FRACTION)
        progress = 1.0 - up * up

    angle = REST_ANGLE_DEG + (STRIKE_ANGLE_DEG - REST_ANGLE_DEG) * progress
    z = REST_Z_MM + (STRIKE_Z_MM - REST_Z_MM) * progress
    return (angle, z)


class MalletCursor(Entity):
    """The mallet. Call :meth:`move_to` each frame and :meth:`strike` on a tap."""

    def __init__(
        self,
        head_color=color.rgb32(222, 56, 60),
        handle_color=color.rgb32(188, 132, 72),
        outline_color=color.rgb32(16, 14, 20),
    ) -> None:
        super().__init__()
        self._swing_s: float | None = None
        self.x_mm = 0.0
        self.y_mm = 0.0

        def plate(
            length_mm: float,
            width_mm: float,
            offset_mm: float,
            colour,
            depth: float,
        ) -> Entity:
            # Local XY, so the parent's rotation swings the whole mallet in
            # the plane of the glass. Offset along local Y puts the handle
            # behind the head, which is where a hand would be.
            return Entity(
                parent=self,
                model="quad",
                scale=(mm_to_world(width_mm), mm_to_world(length_mm)),
                position=(0.0, mm_to_world(offset_mm), depth),
                color=colour,
                shader=UNLIT_120,
                double_sided=True,
            )

        def disc(radius_mm: float, colour, depth: float) -> Entity:
            return Entity(
                parent=self,
                model=disc_xy_mesh(radius_mm),
                position=(0.0, 0.0, depth),
                color=colour,
                shader=UNLIT_120,
                double_sided=True,
            )

        # Outlines are the same shapes, slightly larger and drawn behind, so
        # the mallet keeps a hard edge against grass or soil.
        plate(
            HANDLE_LENGTH_MM + OUTLINE_MM,
            HANDLE_WIDTH_MM + OUTLINE_MM,
            -HANDLE_LENGTH_MM / 2.0,
            outline_color,
            0.02,
        )
        self.handle = plate(
            HANDLE_LENGTH_MM,
            HANDLE_WIDTH_MM,
            -HANDLE_LENGTH_MM / 2.0,
            handle_color,
            0.0,
        )
        disc(HEAD_RADIUS_MM + OUTLINE_MM, outline_color, -0.01)
        self.head = disc(HEAD_RADIUS_MM, head_color, -0.02)
        # A lighter crown, so the face reads as a domed mallet head rather
        # than as a flat counter.
        self.crown = disc(
            HEAD_RADIUS_MM * 0.52, color.rgb32(255, 128, 120), -0.03
        )

        self.move_to(0.0, 0.0)
        self._place(REST_ANGLE_DEG, REST_Z_MM)

    # ------------------------------------------------------------------

    @property
    def swinging(self) -> bool:
        return self._swing_s is not None

    def move_to(self, x_mm: float, y_mm: float) -> None:
        """Put the head at a table position."""
        self.x_mm = x_mm
        self.y_mm = y_mm

    def strike(self) -> None:
        """Start a swing, restarting one already in progress."""
        self._swing_s = 0.0

    def update_swing(self, dt: float) -> None:
        """Advance the swing and apply the pose. Call once per frame."""
        if self._swing_s is not None:
            self._swing_s += dt
            if self._swing_s >= SWING_TIME_S:
                self._swing_s = None

        t = 0.0 if self._swing_s is None else self._swing_s / SWING_TIME_S
        angle, z = swing_profile(t)
        self._place(angle, z)

    def pose(self, x_mm: float, y_mm: float, z_mm: float, angle_deg: float) -> None:
        """Place the mallet explicitly, outside the swing.

        Used while it is being put away: the retract drives position, height
        and angle together, which the swing does not do.
        """
        self.x_mm = x_mm
        self.y_mm = y_mm
        self._swing_s = None
        self._place(angle_deg, z_mm)

    def _place(self, angle_deg: float, z_mm: float) -> None:
        self.position = Vec3(*table_to_world(self.x_mm, self.y_mm, z_mm))
        self.rotation = (90.0, angle_deg, 0.0)

    def set_colors(self, head, handle) -> None:
        self.head.color = head
        self.handle.color = handle
