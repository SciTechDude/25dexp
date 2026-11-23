"""What the game gets told about input.

An input source hands the game :class:`SensorFrame` snapshots and the game
knows nothing else about where they came from, so a scripted source and a
real pointer are interchangeable. That is what lets the whole game be
driven from a test, which is most of why this sits between the two.

Everything here is in millimetres, in table coordinates (see
:mod:`tabletop.core.geometry`). Device units never get this far.

Fields may be empty: no head poses and ``z_mm == 0`` on every touch is a
perfectly good frame, and the game must not care.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

__all__ = [
    "FORMAT_VERSION",
    "TouchPhase",
    "TouchKind",
    "TouchPoint",
    "HeadPose",
    "GestureEvent",
    "SensorFrame",
]

FORMAT_MAJOR = 1
FORMAT_MINOR = 0
FORMAT_VERSION = f"{FORMAT_MAJOR}.{FORMAT_MINOR}"


class TouchPhase(str, Enum):
    """Lifecycle of a single contact.

    A contact is BEGAN exactly once, MOVED zero or more times, then exactly
    one of ENDED (lifted normally) or CANCELLED (tracking lost, or the
    contact was reclassified as an obstacle mid-stream). Consumers may rely
    on that ordering; sources are responsible for guaranteeing it.
    """

    BEGAN = "began"
    MOVED = "moved"
    ENDED = "ended"
    CANCELLED = "cancelled"


class TouchKind(str, Enum):
    """What we believe a contact actually is.

    A source forwards every contact, including ones it believes are not
    fingers, so the game can decide what to do with them rather than having
    them silently dropped.
    """

    FINGER = "finger"
    PALM = "palm"
    OBSTACLE = "obstacle"  # drink, sleeve, phone left on the glass
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TouchPoint:
    """One contact, in table coordinates (mm, centre origin).

    ``major_mm``/``minor_mm`` are the contact's bounding ellipse axes, used
    for size-based filtering. Optional, because not every source reports
    size, so code that filters on it must tolerate ``None``.
    """

    touch_id: int
    """Stable for the life of the contact. Reused only after ENDED."""

    x_mm: float
    y_mm: float
    z_mm: float = 0.0
    """Height above the glass. 0 for a real touch; positive while hovering."""

    phase: TouchPhase = TouchPhase.MOVED
    kind: TouchKind = TouchKind.UNKNOWN
    major_mm: float | None = None
    minor_mm: float | None = None
    player_id: int | None = None
    """Which player this contact belongs to, when the source can tell."""

    confidence: float = 1.0
    source: str = "unknown"
    """Where it came from -- "mouse", "touch", "mock". For debugging."""

    @property
    def is_hovering(self) -> bool:
        return self.z_mm > 0.0

    def to_dict(self) -> dict[str, Any]:
        return _enum_safe(asdict(self))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TouchPoint:
        d = dict(d)
        d["phase"] = TouchPhase(d["phase"])
        d["kind"] = TouchKind(d.get("kind", TouchKind.UNKNOWN))
        return cls(**d)


@dataclass(frozen=True)
class HeadPose:
    """A player's eye position, in table coordinates (mm, centre origin).

    This feeds the off-axis projection directly, which is why it is in the
    same units and origin as everything else: the renderer needs the eye and
    the screen rectangle expressed in one consistent frame or the window
    effect comes out geometrically wrong.

    ``z_mm`` is height above the glass and should always be positive -- a
    player's eyes are above the table.
    """

    player_id: int
    x_mm: float
    y_mm: float
    z_mm: float
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    confidence: float = 1.0
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return _enum_safe(asdict(self))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HeadPose:
        return cls(**d)


@dataclass(frozen=True)
class GestureEvent:
    """A discrete, already-recognised gesture.

    Continuous state belongs in :class:`TouchPoint`; this is for things that
    happen at an instant ("flip", "reach", "hover_enter"). Recognition
    happens in the source, so the game never buffers raw motion.
    """

    gesture: str
    x_mm: float
    y_mm: float
    z_mm: float = 0.0
    player_id: int | None = None
    touch_id: int | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return _enum_safe(asdict(self))

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GestureEvent:
        return cls(**d)


@dataclass(frozen=True)
class SensorFrame:
    """One complete input snapshot.

    A full frame every time, never a delta, so a consumer that misses one
    recovers on the next instead of drifting out of step.
    """

    seq: int
    t_mono_ns: int
    touches: tuple[TouchPoint, ...] = ()
    heads: tuple[HeadPose, ...] = ()
    gestures: tuple[GestureEvent, ...] = ()
    format_version: str = FORMAT_VERSION

    @classmethod
    def now(
        cls,
        seq: int,
        touches: tuple[TouchPoint, ...] = (),
        heads: tuple[HeadPose, ...] = (),
        gestures: tuple[GestureEvent, ...] = (),
    ) -> SensorFrame:
        return cls(
            seq=seq,
            t_mono_ns=time.monotonic_ns(),
            touches=tuple(touches),
            heads=tuple(heads),
            gestures=tuple(gestures),
        )

    def head_for(self, player_id: int) -> HeadPose | None:
        for h in self.heads:
            if h.player_id == player_id:
                return h
        return None

    def fingers(self) -> tuple[TouchPoint, ...]:
        """Contacts classified as fingers, or not classified at all."""
        return tuple(
            t for t in self.touches
            if t.kind in (TouchKind.FINGER, TouchKind.UNKNOWN)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "seq": self.seq,
            "t_mono_ns": self.t_mono_ns,
            "touches": [t.to_dict() for t in self.touches],
            "heads": [h.to_dict() for h in self.heads],
            "gestures": [g.to_dict() for g in self.gestures],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SensorFrame:
        version = d.get("format_version", FORMAT_VERSION)
        major = int(str(version).split(".", 1)[0])
        if major != FORMAT_MAJOR:
            raise ValueError(
                f"incompatible frame format {version!r}: this build speaks "
                f"{FORMAT_VERSION}. A major-version mismatch means fields "
                f"were removed, renamed, or had their units changed."
            )
        return cls(
            seq=d["seq"],
            t_mono_ns=d["t_mono_ns"],
            touches=tuple(TouchPoint.from_dict(x) for x in d.get("touches", [])),
            heads=tuple(HeadPose.from_dict(x) for x in d.get("heads", [])),
            gestures=tuple(GestureEvent.from_dict(x) for x in d.get("gestures", [])),
            format_version=version,
        )


def _enum_safe(d: dict[str, Any]) -> dict[str, Any]:
    """Convert Enum values to their primitives so the dict is JSON-ready."""
    return {k: (v.value if isinstance(v, Enum) else v) for k, v in d.items()}
