"""Measure your screen once, write it to JSON.

    python -m tabletop.apps.calibrate --out calibration/my_screen.json

Asks for the handful of measurements the projection depends on, checks they
are plausible, and writes a file the games read.

What to measure, and how
------------------------
* **Picture size** -- the *lit* area, not the outer bezel. Hold a tape
  measure against the glass and measure the bright rectangle. The off-axis
  projection treats this as the window, so bezel millimetres counted in
  here come straight back as a wrong frustum.

* **Touch area** -- if there is a touchscreen, the rectangle it actually
  senses, which is usually a little larger than the picture.

* **Touch offset** -- how far the touch rectangle's centre sits from the
  centre of the picture. Measure the gap on opposite sides; half the
  difference is the offset. Non-zero is normal, and carrying it here is
  what stops it looking like touch drift later.

On Linux, run ``python -m tabletop.apps.probe_touch`` first for the device's
real coordinate ranges, rather than guessing them.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tabletop.core.calibration import TableCalibration


def _ask_float(prompt: str, default: float | None = None) -> float:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  please enter a number")


def _ask_int(prompt: str, default: int | None = None) -> int:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("  please enter a whole number")


def _ask_yes_no(prompt: str, default: bool) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    while True:
        raw = input(f"{prompt}{suffix}: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  please answer y or n")


def run_wizard() -> TableCalibration:
    reference = TableCalibration.development_default()

    print(__doc__)
    print("-" * 70)
    print("Display (the lit area, not the bezel)")
    display_w = _ask_float("  image width in mm", reference.display_width_mm)
    display_h = _ask_float("  image height in mm", reference.display_height_mm)
    px_w = _ask_int("  horizontal resolution in pixels", reference.display_width_px)
    px_h = _ask_int("  vertical resolution in pixels", reference.display_height_px)

    print("\nTouch area (the rectangle the screen actually senses)")
    touch_w = _ask_float("  active width in mm", display_w)
    touch_h = _ask_float("  active height in mm", display_h)
    touch_dx = _ask_float("  centre offset X in mm (+ = frame sits right)", 0.0)
    touch_dy = _ask_float("  centre offset Y in mm (+ = frame sits away)", 0.0)

    print("\nDevice coordinate ranges (from probe_touch on Linux)")
    raw_x_max = _ask_int("  max raw X", reference.raw_x_max)
    raw_y_max = _ask_int("  max raw Y", reference.raw_y_max)
    invert_y = _ask_yes_no(
        "  does it report Y increasing downward (usual)?", True
    )
    has_size = _ask_yes_no("  does it report contact size?", True)
    raw_major_max = (
        _ask_int("  max raw contact size", raw_x_max) if has_size else None
    )

    label = input("\nLabel for this table [prototype]: ").strip() or "prototype"

    return TableCalibration(
        display_width_mm=display_w,
        display_height_mm=display_h,
        display_width_px=px_w,
        display_height_px=px_h,
        touch_width_mm=touch_w,
        touch_height_mm=touch_h,
        touch_offset_x_mm=touch_dx,
        touch_offset_y_mm=touch_dy,
        raw_x_max=raw_x_max,
        raw_y_max=raw_y_max,
        invert_y=invert_y,
        raw_major_max=raw_major_max,
        label=label,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure and save a table calibration")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("calibration/table.json"),
        help="where to write the calibration JSON",
    )
    parser.add_argument(
        "--show",
        type=Path,
        default=None,
        help="print an existing calibration instead of creating one",
    )
    args = parser.parse_args()

    if args.show:
        print(TableCalibration.load(args.show).describe())
        return

    calibration = run_wizard()

    print("\n" + "-" * 70)
    print(calibration.describe())

    problems = calibration.problems()
    if problems:
        print(
            "\nThe measurements above are usable but worth a second look. "
            "Saving anyway; re-run to correct them."
        )

    calibration.save(args.out)
    print(f"\nwrote {args.out}")
    print(f"use it with: python -m tabletop.apps.depth_demo --calibration {args.out}")


if __name__ == "__main__":
    main()
