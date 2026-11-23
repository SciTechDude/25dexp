"""Reads a touchscreen on Linux, through the kernel's multitouch protocol.

Status: **written but never run against a touchscreen.** It cannot run on
macOS at all, so every line is reasoned from the protocol docs rather than
observed. :func:`probe_devices` reports what a given device actually
supports, which is the thing to run first.

Why evdev rather than raw HID
-----------------------------
Reading the panel as a raw HID device means fighting the OS for exclusive
access to something it has already claimed. The kernel's multitouch
protocol is the friendlier interface and hands over more than parsing HID
reports would:

* ``ABS_MT_POSITION_X/Y``        -- contact position
* ``ABS_MT_TRACKING_ID``         -- stable contact identity, kernel-maintained
* ``ABS_MT_TOUCH_MAJOR/MINOR``   -- contact size, where reported
* ``ABS_MT_SLOT``                -- which contact subsequent values apply to

Not every panel reports contact size. Here it either arrives as a kernel
axis or is verifiably absent, which :meth:`probe_devices` reports.

Exclusive access
----------------
``EVIOCGRAB`` (``device.grab()``) takes the device away from the desktop,
so a tap on a mole does not also click whatever is behind the window.
"""

from __future__ import annotations

import select
from dataclasses import dataclass

from tabletop.core.calibration import TableCalibration
from tabletop.core.events import SensorFrame, TouchPhase, TouchPoint
from tabletop.sensors.base import TouchSource

__all__ = ["EvdevTouchSource", "DeviceReport", "probe_devices", "EvdevUnavailable"]


class EvdevUnavailable(RuntimeError):
    """evdev is not importable, or this is not Linux."""


def _import_evdev():  # type: ignore[no-untyped-def]
    try:
        import evdev  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise EvdevUnavailable(
            "python-evdev is unavailable. It is Linux-only; on macOS use "
            "MockTouchSource. Install with: pip install '.[linux]'"
        ) from exc
    return evdev


@dataclass
class DeviceReport:
    """What a probe found out about one input device."""

    path: str
    name: str
    is_multitouch: bool
    reports_size: bool
    raw_x_range: tuple[int, int] | None = None
    raw_y_range: tuple[int, int] | None = None
    raw_major_max: int | None = None
    max_slots: int | None = None

    def summary(self) -> str:
        if not self.is_multitouch:
            return f"{self.path}  {self.name!r}  (not multitouch)"
        size = (
            f"size up to {self.raw_major_max}"
            if self.reports_size
            else "NO SIZE DATA -> size-based filtering unavailable"
        )
        slots = f"{self.max_slots} slots" if self.max_slots else "slots unknown"
        return (
            f"{self.path}  {self.name!r}\n"
            f"    x{self.raw_x_range}  y{self.raw_y_range}  {slots}\n"
            f"    {size}"
        )


def probe_devices() -> list[DeviceReport]:
    """List input devices and report their multitouch capabilities.

    Reports what an attached device supports. It answers,
    with no guessing: which ``/dev/input/event*`` it is, what its
    coordinate ranges are (feed these into the calibration instead of
    assuming 0..32767), how many simultaneous contacts it supports, and
    whether it reports contact size at all.
    """
    evdev = _import_evdev()
    reports: list[DeviceReport] = []

    for path in evdev.list_devices():
        device = evdev.InputDevice(path)
        try:
            caps = device.capabilities(absinfo=True)
            abs_caps = dict(caps.get(evdev.ecodes.EV_ABS, []))

            has_x = evdev.ecodes.ABS_MT_POSITION_X in abs_caps
            has_y = evdev.ecodes.ABS_MT_POSITION_Y in abs_caps
            major = abs_caps.get(evdev.ecodes.ABS_MT_TOUCH_MAJOR)
            slot = abs_caps.get(evdev.ecodes.ABS_MT_SLOT)

            reports.append(
                DeviceReport(
                    path=path,
                    name=device.name,
                    is_multitouch=has_x and has_y,
                    reports_size=major is not None,
                    raw_x_range=(
                        (abs_caps[evdev.ecodes.ABS_MT_POSITION_X].min,
                         abs_caps[evdev.ecodes.ABS_MT_POSITION_X].max)
                        if has_x else None
                    ),
                    raw_y_range=(
                        (abs_caps[evdev.ecodes.ABS_MT_POSITION_Y].min,
                         abs_caps[evdev.ecodes.ABS_MT_POSITION_Y].max)
                        if has_y else None
                    ),
                    raw_major_max=major.max if major is not None else None,
                    max_slots=(slot.max + 1) if slot is not None else None,
                )
            )
        finally:
            device.close()

    return reports


@dataclass
class _Slot:
    """Mutable per-slot state, mirroring the kernel's slot model."""

    tracking_id: int | None = None
    raw_x: float = 0.0
    raw_y: float = 0.0
    raw_major: float | None = None
    raw_minor: float | None = None
    began: bool = False
    dirty: bool = False


class EvdevTouchSource(TouchSource):
    """Reads a touchscreen through the kernel multitouch protocol.

    Non-blocking: :meth:`poll` drains whatever is pending and returns the
    current contact set. It never waits on the device, so the render loop
    sets the rate rather than the panel.
    """

    name = "evdev"

    def __init__(
        self,
        calibration: TableCalibration,
        device_path: str,
        grab: bool = True,
    ) -> None:
        super().__init__()
        self.calibration = calibration
        self.device_path = device_path
        self._grab = grab
        self._device = None
        self._slots: dict[int, _Slot] = {}
        self._current_slot = 0
        self._ended: list[TouchPoint] = []

    # -- lifecycle ------------------------------------------------------

    def start(self) -> None:
        evdev = _import_evdev()
        self._device = evdev.InputDevice(self.device_path)
        if self._grab:
            # Take the device from the compositor so rejected contacts do not
            # also drive the system pointer.
            self._device.grab()
        super().start()

    def stop(self) -> None:
        if self._device is not None:
            try:
                if self._grab:
                    self._device.ungrab()
            except (OSError, RuntimeError):
                # Ungrab fails if we never successfully grabbed; closing the
                # device releases it regardless, so this is not worth raising
                # during cleanup.
                pass
            self._device.close()
            self._device = None
        super().stop()

    # -- reading --------------------------------------------------------

    def poll(self) -> SensorFrame:
        if self._device is None:
            raise RuntimeError("poll() before start()")

        evdev = _import_evdev()
        ecodes = evdev.ecodes

        # Drain only what is already buffered.
        while True:
            ready, _, _ = select.select([self._device.fd], [], [], 0)
            if not ready:
                break
            try:
                events = list(self._device.read())
            except BlockingIOError:
                break
            if not events:
                break
            for event in events:
                self._apply(event, ecodes)

        return SensorFrame.now(seq=self._next_seq(), touches=self._snapshot())

    def _apply(self, event, ecodes) -> None:  # type: ignore[no-untyped-def]
        if event.type != ecodes.EV_ABS:
            return

        if event.code == ecodes.ABS_MT_SLOT:
            self._current_slot = event.value
            return

        slot = self._slots.setdefault(self._current_slot, _Slot())

        if event.code == ecodes.ABS_MT_TRACKING_ID:
            if event.value == -1:
                # Contact lifted. Emit one ENDED, then drop the slot state.
                if slot.tracking_id is not None:
                    self._ended.append(self._to_touch(slot, TouchPhase.ENDED))
                self._slots.pop(self._current_slot, None)
            else:
                slot.tracking_id = event.value
                slot.began = False
                slot.dirty = True
        elif event.code == ecodes.ABS_MT_POSITION_X:
            slot.raw_x = event.value
            slot.dirty = True
        elif event.code == ecodes.ABS_MT_POSITION_Y:
            slot.raw_y = event.value
            slot.dirty = True
        elif event.code == ecodes.ABS_MT_TOUCH_MAJOR:
            slot.raw_major = event.value
        elif event.code == ecodes.ABS_MT_TOUCH_MINOR:
            slot.raw_minor = event.value

    def _snapshot(self) -> tuple[TouchPoint, ...]:
        touches = list(self._ended)
        self._ended.clear()

        for slot in self._slots.values():
            if slot.tracking_id is None:
                continue
            phase = TouchPhase.MOVED if slot.began else TouchPhase.BEGAN
            slot.began = True
            touches.append(self._to_touch(slot, phase))

        return tuple(touches)

    def _to_touch(self, slot: _Slot, phase: TouchPhase) -> TouchPoint:
        x_mm, y_mm = self.calibration.raw_to_table_mm(slot.raw_x, slot.raw_y)
        return TouchPoint(
            touch_id=slot.tracking_id if slot.tracking_id is not None else -1,
            x_mm=x_mm,
            y_mm=y_mm,
            z_mm=0.0,  # The device only sees contacts on the glass plane.
            phase=phase,
            major_mm=self.calibration.raw_major_to_mm(slot.raw_major),
            minor_mm=self.calibration.raw_major_to_mm(slot.raw_minor),
            source=self.name,
        )
