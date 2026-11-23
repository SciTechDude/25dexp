"""Report what an attached touchscreen can actually do (Linux only).

    python -m tabletop.apps.probe_touch

Answers, from the device rather than from assumptions:

* which ``/dev/input/event*`` node it is
* its real coordinate ranges, which go straight into the calibration
  instead of the assumed ``0..32767``
* how many simultaneous contacts it supports, versus the advertised number
* **whether it reports contact size at all**, which decides whether
  size-based filtering is possible

Needs read access to ``/dev/input/*``, which usually means the ``input``
group or running under sudo.
"""

from __future__ import annotations

import sys

from tabletop.sensors.evdev_source import EvdevUnavailable, probe_devices


def main() -> int:
    try:
        reports = probe_devices()
    except EvdevUnavailable as exc:
        print(f"cannot probe: {exc}", file=sys.stderr)
        return 2
    except PermissionError:
        print(
            "permission denied reading /dev/input/*. Add your user to the "
            "'input' group (then log out and back in), or re-run with sudo.",
            file=sys.stderr,
        )
        return 2

    multitouch = [r for r in reports if r.is_multitouch]

    if not multitouch:
        print(f"found {len(reports)} input devices, none of them multitouch.")
        print("If it is plugged in, check `dmesg | tail` for how the")
        print("kernel bound it -- some frames enumerate as plain HID mice.")
        return 1

    print(f"found {len(multitouch)} multitouch device(s):\n")
    for report in multitouch:
        print(report.summary())
        print()

    sized = [r for r in multitouch if r.reports_size]
    if sized:
        print(
            "Contact size IS reported; feed raw_major_max into the "
            "calibration."
        )
    else:
        print(
            "Contact size is NOT reported by any device, so anything "
            "that filters on it has to be switched off."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
