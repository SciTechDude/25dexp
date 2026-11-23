"""How big the screen actually is, in millimetres.

Measure the screen once; everything downstream reads these numbers. The
2.5D projection needs them: it works out the frustum from the *physical*
size of the lit area and the viewer's distance from it, so guessing the
size makes the whole window effect geometrically wrong. Touch input needs
them too, to turn device coordinates into millimetres on the glass.

Two rectangles, not one
-----------------------
A touch overlay's active area is not the same rectangle as the picture: it
is usually a few millimetres larger and rarely perfectly concentric. Fold
them into one rectangle and touches land with a small, consistent offset
towards the edges, which looks like tracking drift and is maddening to
chase. So both are stored, plus the offset between their centres.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tabletop.core.geometry import RectMM

__all__ = ["TableCalibration"]

CALIBRATION_VERSION = 1


@dataclass(frozen=True)
class TableCalibration:
    """Everything measured about one screen and its touch area.

    All distances in millimetres. No angles: the screen is assumed flat and
    the touch area square to the picture.
    """

    # --- display -------------------------------------------------------
    display_width_mm: float
    display_height_mm: float
    """Visible image, not the outer bezel. Measure the lit area."""

    display_width_px: int
    display_height_px: int

    # --- touch area ----------------------------------------------------
    touch_width_mm: float
    touch_height_mm: float
    """The touch-sensitive area, which is not the picture (see above)."""

    touch_offset_x_mm: float = 0.0
    touch_offset_y_mm: float = 0.0
    """Centre of the touch area relative to the centre of the picture."""

    raw_x_min: int = 0
    raw_x_max: int = 32767
    raw_y_min: int = 0
    raw_y_max: int = 32767
    """Device-native coordinate range. Read it from the device rather than
    assuming: 0..32767 is common but far from universal."""

    invert_x: bool = False
    invert_y: bool = True
    """Touch devices usually put the origin at the top-left with Y running
    downward, while table +Y runs away from the player, so Y usually flips."""

    raw_major_max: int | None = None
    """Device range of the contact-size axis, if the device reports one.
    ``None`` means no size data, so anything that filters on size has to be
    switched off rather than left silently wrong."""

    label: str = "untitled table"
    version: int = CALIBRATION_VERSION

    # ------------------------------------------------------------------
    # Derived rectangles
    # ------------------------------------------------------------------

    @property
    def display_rect(self) -> RectMM:
        """The display's visible image. Defines the table origin."""
        return RectMM(self.display_width_mm, self.display_height_mm, 0.0, 0.0)

    @property
    def touch_rect(self) -> RectMM:
        """The touch area, positioned relative to the picture."""
        return RectMM(
            self.touch_width_mm,
            self.touch_height_mm,
            self.touch_offset_x_mm,
            self.touch_offset_y_mm,
        )

    @property
    def px_per_mm_x(self) -> float:
        return self.display_width_px / self.display_width_mm

    @property
    def px_per_mm_y(self) -> float:
        return self.display_height_px / self.display_height_mm

    @property
    def reports_contact_size(self) -> bool:
        """Whether the device reports contact size at all."""
        return self.raw_major_max is not None

    # ------------------------------------------------------------------
    # Device units -> table millimetres
    # ------------------------------------------------------------------

    def raw_to_table_mm(self, raw_x: float, raw_y: float) -> tuple[float, float]:
        """Map a raw contact coordinate into table millimetres.

        Raw units -> normalised -> touch rectangle -> table coordinates,
        which are centred on the picture. Out-of-range values are not
        clamped: a contact reported outside the touch area means the
        calibration is wrong, and silently clamping hides that.
        """
        u = _safe_norm(raw_x, self.raw_x_min, self.raw_x_max)
        v = _safe_norm(raw_y, self.raw_y_min, self.raw_y_max)
        if self.invert_x:
            u = 1.0 - u
        if self.invert_y:
            v = 1.0 - v
        return self.touch_rect.denormalise(u, v)

    def raw_major_to_mm(self, raw_major: float | None) -> float | None:
        """Convert a raw contact-size value to millimetres.

        ``None`` when the device reports no size, so callers have to handle
        its absence rather than reading 0 as "very small finger".
        """
        if raw_major is None or self.raw_major_max is None:
            return None
        if self.raw_major_max <= 0:
            return None
        # The size axis uses the same units as the X position axis, so
        # scale it by the X axis' millimetres-per-unit.
        span = self.raw_x_max - self.raw_x_min
        if span <= 0:
            return None
        return float(raw_major) / span * self.touch_width_mm

    # ------------------------------------------------------------------
    # Table millimetres <-> display pixels
    # ------------------------------------------------------------------

    def table_mm_to_px(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        """Table millimetres to display pixels (origin top-left, Y down)."""
        u, v = self.display_rect.normalise(x_mm, y_mm)
        return (u * self.display_width_px, (1.0 - v) * self.display_height_px)

    def px_to_table_mm(self, px_x: float, px_y: float) -> tuple[float, float]:
        """Display pixels (origin top-left, Y down) to table millimetres."""
        u = px_x / self.display_width_px
        v = 1.0 - (px_y / self.display_height_px)
        return self.display_rect.denormalise(u, v)

    # ------------------------------------------------------------------
    # Sanity checking
    # ------------------------------------------------------------------

    def problems(self) -> list[str]:
        """Physically implausible measurements, as human-readable strings.

        Deliberately returns findings rather than raising: a slightly odd
        calibration should still run, with the oddity visible on screen.
        """
        out: list[str] = []

        if self.touch_width_mm < self.display_width_mm - 1.0:
            out.append(
                f"touch width ({self.touch_width_mm:.0f} mm) is narrower "
                f"than the picture ({self.display_width_mm:.0f} mm): the "
                f"left and right edges will be untouchable."
            )
        if self.touch_height_mm < self.display_height_mm - 1.0:
            out.append(
                f"touch height ({self.touch_height_mm:.0f} mm) is shorter "
                f"than the picture ({self.display_height_mm:.0f} mm): the "
                f"top and bottom edges will be untouchable."
            )

        display_aspect = self.display_rect.aspect
        px_aspect = self.display_width_px / self.display_height_px
        if abs(display_aspect - px_aspect) / px_aspect > 0.02:
            out.append(
                f"measured aspect ({display_aspect:.3f}) disagrees with "
                f"pixel aspect ({px_aspect:.3f}) by more than 2%: non-square "
                f"pixels are unlikely, so re-measure the lit area."
            )

        if not self.reports_contact_size:
            out.append(
                "no contact size reported (raw_major_max is unset): "
                "size-based filtering is unavailable."
            )

        return out

    def describe(self) -> str:
        lines = [
            f"table: {self.label}",
            f"  image      {self.display_width_mm:.0f} x "
            f"{self.display_height_mm:.0f} mm "
            f"({self.display_width_px} x {self.display_height_px} px, "
            f"{self.px_per_mm_x:.2f} px/mm)",
            f"  touch      {self.touch_width_mm:.0f} x {self.touch_height_mm:.0f} mm "
            f"@ offset ({self.touch_offset_x_mm:+.1f}, {self.touch_offset_y_mm:+.1f}) mm",
            f"  raw        x[{self.raw_x_min}..{self.raw_x_max}] "
            f"y[{self.raw_y_min}..{self.raw_y_max}] "
            f"invert_x={self.invert_x} invert_y={self.invert_y}",
            f"  size data  {'yes' if self.reports_contact_size else 'NO'}",
        ]
        for p in self.problems():
            lines.append(f"  ! {p}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TableCalibration:
        d = dict(d)
        got = d.pop("version", CALIBRATION_VERSION)
        if got != CALIBRATION_VERSION:
            raise ValueError(
                f"calibration file is version {got}, this build reads "
                f"{CALIBRATION_VERSION}"
            )
        known = {f for f in cls.__dataclass_fields__ if f != "version"}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown calibration fields: {sorted(unknown)}")
        return cls(**d)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> TableCalibration:
        return cls.from_dict(json.loads(Path(path).read_text()))

    # ------------------------------------------------------------------

    @classmethod
    def development_default(cls) -> TableCalibration:
        """A plausible 43-inch screen, for working without one to hand.

        A real 43" 16:9 panel's lit area (~941 x 529 mm), with a touch area
        6 mm larger on each axis and a 2 mm offset -- the kind of
        imperfection the two rectangles exist to carry. Measure your own
        screen before trusting any of it.
        """
        return cls(
            display_width_mm=941.0,
            display_height_mm=529.0,
            display_width_px=3840,
            display_height_px=2160,
            touch_width_mm=953.0,
            touch_height_mm=541.0,
            touch_offset_x_mm=2.0,
            touch_offset_y_mm=-1.0,
            raw_major_max=32767,
            label="default (43in 16:9, not measured)",
        )


def _safe_norm(value: float, lo: float, hi: float) -> float:
    span = hi - lo
    if span == 0:
        raise ValueError(f"degenerate device axis range [{lo}, {hi}]")
    return (value - lo) / span
