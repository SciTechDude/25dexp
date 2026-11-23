"""The touch source interface.

Two implementations: :class:`~tabletop.sensors.mock.MockTouchSource`, which
runs anywhere, and :class:`~tabletop.sensors.evdev_source.EvdevTouchSource`,
which needs Linux. The game only ever sees :class:`SensorFrame`, so
swapping one for the other is a line at startup.

macOS gives no way to read raw contacts from an external touchscreen -- it
keeps them to itself -- so on a Mac the mock source is the only option, and
it is written to be relied on rather than thrown away.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType

from tabletop.core.events import SensorFrame

__all__ = ["TouchSource"]


class TouchSource(ABC):
    """A source of :class:`SensorFrame` snapshots.

    Implementations must guarantee the touch phase ordering documented on
    :class:`~tabletop.core.events.TouchPhase`: each contact appears BEGAN
    once, MOVED any number of times, then ENDED or CANCELLED exactly once.
    Consumers are allowed to rely on that, so getting it right belongs here
    rather than in every game that reads the stream.
    """

    name: str = "unnamed"

    def __init__(self) -> None:
        self._seq = 0
        self._started = False

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Acquire the device. Idempotent."""
        self._started = True

    def stop(self) -> None:
        """Release the device. Idempotent, and safe to call after a failed
        :meth:`start` -- cleanup paths run during exception handling."""
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def __enter__(self) -> TouchSource:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    # -- data -----------------------------------------------------------

    @abstractmethod
    def poll(self) -> SensorFrame:
        """Return the current snapshot.

        Must be non-blocking: this is called once per render frame, and a
        source that stalls waiting for a device would pin the frame rate to
        the sensor rather than the display. A source with nothing new to
        report returns a frame describing the unchanged current state.
        """

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq
