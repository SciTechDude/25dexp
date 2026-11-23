"""Touch sources that need no touchscreen.

:class:`MockTouchSource` is driven imperatively: the game pushes the mouse
position into it, tests push exact millimetre coordinates. It owns the id
allocation and the BEGAN/MOVED/ENDED bookkeeping, so that fiddly part is
written and tested in one place.

:class:`ScriptedTouchSource` replays a timed sequence of contacts, which is
what makes awkward multi-touch situations reproducible without a
touchscreen and without a pair of hands: three fingers in a line, a palm
resting while a finger taps, something left on the glass alongside live
touches.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass

from tabletop.core.calibration import TableCalibration
from tabletop.core.events import (
    HeadPose,
    SensorFrame,
    TouchKind,
    TouchPhase,
    TouchPoint,
)
from tabletop.sensors.base import TouchSource

__all__ = [
    "MockTouchSource",
    "ScriptedTouchSource",
    "Contact",
    "ScriptStep",
    "collinear_three_finger_script",
]


@dataclass(frozen=True)
class Contact:
    """A contact as a caller describes it, before phase bookkeeping."""

    x_mm: float
    y_mm: float
    z_mm: float = 0.0
    major_mm: float | None = None
    minor_mm: float | None = None
    player_id: int | None = None
    kind: TouchKind = TouchKind.UNKNOWN


class MockTouchSource(TouchSource):
    """An imperatively-driven touch source.

    Callers identify contacts by an arbitrary hashable key (``"mouse"``, a
    finger index, a test label). The source maps keys to stable integer
    touch ids and derives phases by diffing against the previous poll.

    Touch ids are never reused within a run even after a contact ends. Real
    touch devices do recycle slot numbers, and a game that keys animations off
    a touch id will glitch when an id comes back. Not reusing them here
    means the mock is *stricter* than a real panel, so code written
    against it does not acquire a dependency on recycling behaviour.
    """

    name = "mock"

    def __init__(self, calibration: TableCalibration) -> None:
        super().__init__()
        self.calibration = calibration
        self._contacts: dict[Hashable, Contact] = {}
        self._ids: dict[Hashable, int] = {}
        self._seen: set[Hashable] = set()
        self._heads: dict[int, HeadPose] = {}
        self._next_touch_id = 1
        # Last reported position per contact, so an ENDED event can carry the
        # place the finger actually lifted from rather than the origin.
        self._last_known: dict[Hashable, tuple[float, float, float]] = {}

    # -- driving the source ---------------------------------------------

    def set_contact(self, key: Hashable, contact: Contact) -> None:
        """Add or update a contact. Phase is derived automatically."""
        self._contacts[key] = contact

    def set_point(
        self, key: Hashable, x_mm: float, y_mm: float, z_mm: float = 0.0
    ) -> None:
        """Convenience for the common case of a bare position."""
        self.set_contact(key, Contact(x_mm=x_mm, y_mm=y_mm, z_mm=z_mm))

    def clear_contact(self, key: Hashable) -> None:
        """Lift a contact. It is reported ENDED on the next poll, once."""
        self._contacts.pop(key, None)

    def clear_all(self) -> None:
        for key in list(self._contacts):
            self.clear_contact(key)

    def set_head(self, head: HeadPose) -> None:
        self._heads[head.player_id] = head

    def clear_heads(self) -> None:
        self._heads.clear()

    # -- reading --------------------------------------------------------

    def poll(self) -> SensorFrame:
        touches: list[TouchPoint] = []

        # Contacts that disappeared since the last poll end exactly once.
        for key in list(self._seen):
            if key not in self._contacts:
                touch_id = self._ids.pop(key)
                self._seen.discard(key)
                last_x, last_y, last_z = self._last_known.get(key, (0.0, 0.0, 0.0))
                touches.append(
                    TouchPoint(
                        touch_id=touch_id,
                        x_mm=last_x,
                        y_mm=last_y,
                        z_mm=last_z,
                        phase=TouchPhase.ENDED,
                        source=self.name,
                    )
                )

        for key, contact in self._contacts.items():
            if key in self._seen:
                phase = TouchPhase.MOVED
            else:
                phase = TouchPhase.BEGAN
                self._seen.add(key)
                self._ids[key] = self._next_touch_id
                self._next_touch_id += 1

            touches.append(
                TouchPoint(
                    touch_id=self._ids[key],
                    x_mm=contact.x_mm,
                    y_mm=contact.y_mm,
                    z_mm=contact.z_mm,
                    phase=phase,
                    kind=contact.kind,
                    major_mm=contact.major_mm,
                    minor_mm=contact.minor_mm,
                    player_id=contact.player_id,
                    source=self.name,
                )
            )
            self._last_known[key] = (contact.x_mm, contact.y_mm, contact.z_mm)

        # Forget positions for contacts that have now been reported ended.
        for key in list(self._last_known):
            if key not in self._contacts:
                self._last_known.pop(key, None)

        return SensorFrame.now(
            seq=self._next_seq(),
            touches=tuple(touches),
            heads=tuple(self._heads.values()),
        )

    def active_keys(self) -> frozenset[Hashable]:
        """Contacts currently down. Exposed for the scripted source."""
        return frozenset(self._contacts)


@dataclass(frozen=True)
class ScriptStep:
    """Contacts that should be present at a point in time.

    ``at_s`` is seconds from the start of the script. Contacts not listed in
    a step are lifted, which is how a script expresses a release.
    """

    at_s: float
    contacts: Mapping[Hashable, Contact]


class ScriptedTouchSource(TouchSource):
    """Replays a timed script of contacts.

    Wraps a :class:`MockTouchSource` so phase bookkeeping stays in one
    place. Time advances from a monotonic clock by default; pass an explicit
    ``clock`` in tests to step through a script deterministically instead of
    sleeping.

    Loop timing
    -----------
    The loop period is ``duration_s``, defaulting to the last keyframe's
    timestamp **plus** ``tail_s``. That tail is not cosmetic: were the period
    equal to the last keyframe's timestamp, that keyframe would be reached
    only at the exact instant the script wrapped, so the final state --
    typically "all contacts lifted" -- would never be observed at all.
    """

    name = "scripted"
    DEFAULT_TAIL_S = 0.5

    def __init__(
        self,
        calibration: TableCalibration,
        steps: Sequence[ScriptStep],
        loop: bool = True,
        clock: Callable[[], float] | None = None,
        tail_s: float | None = None,
        duration_s: float | None = None,
    ) -> None:
        super().__init__()
        if not steps:
            raise ValueError("a script needs at least one step")
        self._steps = sorted(steps, key=lambda s: s.at_s)
        if self._steps[0].at_s < 0:
            raise ValueError("script steps cannot have negative timestamps")

        last_at = self._steps[-1].at_s
        tail = self.DEFAULT_TAIL_S if tail_s is None else tail_s
        if duration_s is None:
            duration_s = last_at + tail
        elif duration_s <= last_at:
            raise ValueError(
                f"duration_s={duration_s} must exceed the last keyframe at "
                f"{last_at}s, or that keyframe can never be observed"
            )
        self._duration = duration_s

        self._inner = MockTouchSource(calibration)
        self._loop = loop
        self._clock: Callable[[], float] = clock or time.monotonic
        self._t0: float | None = None

    @property
    def calibration(self) -> TableCalibration:
        return self._inner.calibration

    def start(self) -> None:
        super().start()
        self._t0 = self._clock()

    def poll(self) -> SensorFrame:
        if self._t0 is None:
            self._t0 = self._clock()

        elapsed = self._clock() - self._t0
        if self._loop and self._duration > 0:
            elapsed = elapsed % self._duration

        # The active step is the last one whose time has passed.
        active = self._steps[0]
        for step in self._steps:
            if step.at_s <= elapsed:
                active = step
            else:
                break

        for key in self._inner.active_keys():
            if key not in active.contacts:
                self._inner.clear_contact(key)
        for key, contact in active.contacts.items():
            self._inner.set_contact(key, contact)

        return self._inner.poll()


def collinear_three_finger_script(
    calibration: TableCalibration, y_mm: float = 0.0
) -> list[ScriptStep]:
    """Three contacts in a straight line, the middle one between the others.

    The awkward case for any touchscreen that senses along two axes: the
    middle contact can be shadowed by the outer two. Replaying this against
    a real panel shows straight away whether that middle contact jitters or
    drops, and it costs nothing to write the script now.
    """
    rect = calibration.display_rect
    xs = (-rect.width_mm * 0.25, 0.0, rect.width_mm * 0.25)
    return [
        ScriptStep(0.0, {"f0": Contact(xs[0], y_mm)}),
        ScriptStep(0.5, {"f0": Contact(xs[0], y_mm), "f1": Contact(xs[1], y_mm)}),
        ScriptStep(
            1.0,
            {
                "f0": Contact(xs[0], y_mm),
                "f1": Contact(xs[1], y_mm),
                "f2": Contact(xs[2], y_mm),
            },
        ),
        ScriptStep(2.0, {"f0": Contact(xs[0], y_mm), "f2": Contact(xs[2], y_mm)}),
        ScriptStep(2.5, {}),
    ]
