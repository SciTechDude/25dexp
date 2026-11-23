"""Splits the display into a bezel, a score band, and the playfield.

Pure geometry in millimetres, no renderer: the rules are handed a playfield
smaller than the display, and the view draws the frame from the same
numbers.

Three bands, from the outer edge of the lit area inward:

    |<--------------------- display_width_mm --------------------->|
    | bezel |      score band       |        playfield ...
    0    bezel_width        bezel_width + score_band_mm

The bezel is a thin raised moulding with a chamfer on each side, so it
shades from overhead and reads as a solid edge. The score band is flat, at
the glass plane, and carries the scoreboard.

Both are subtracted from all four sides, so the playfield stays centred and
the margin is uniform; only the near (-Y) band carries text.
"""

from __future__ import annotations

from dataclasses import dataclass

from tabletop.core.geometry import RectMM

__all__ = ["TableLayout", "EXIT_BUTTON_WIDTH_MM", "EXIT_BUTTON_HEIGHT_MM"]

EXIT_BUTTON_WIDTH_MM = 76.0
EXIT_BUTTON_HEIGHT_MM = 26.0
"""Size of the quit target on the score band. Wide enough to hit with a
finger without being wide enough to hit by accident while reaching for a
mole -- it sits on the band, which is not part of the playfield."""


@dataclass(frozen=True)
class TableLayout:
    """Measured against the display's lit area, not the panel's outer bezel."""

    display_width_mm: float
    display_height_mm: float

    bezel_width_mm: float = 18.0
    """Width of the raised moulding at the display edge. Thin, because every
    millimetre comes off the playfield on both sides."""

    bezel_rise_mm: float = 10.0
    """How far the bezel's top stands above the glass. Well under the mole's
    78 mm peak, so it cannot occlude the outer row of moles."""

    bezel_inner_slope_mm: float = 6.0
    """Run of the chamfer from the bezel top down to the glass. Sloped, not
    a vertical step, which from overhead would be nearly invisible."""

    bezel_outer_slope_mm: float = 3.0
    """Run of the chamfer up from the display edge to the bezel top."""

    score_band_mm: float = 34.0
    """Width of the flat band inside the bezel. Sized to what the scoreboard
    needs: three lines of detail at ~7 mm, with margin."""

    def __post_init__(self) -> None:
        if self.bezel_width_mm < 0 or self.score_band_mm < 0:
            raise ValueError(
                f"bezel and band widths must not be negative, got "
                f"{self.bezel_width_mm} and {self.score_band_mm} mm"
            )
        if (
            self.bezel_inner_slope_mm + self.bezel_outer_slope_mm
            > self.bezel_width_mm
        ):
            raise ValueError(
                f"chamfers ({self.bezel_inner_slope_mm} + "
                f"{self.bezel_outer_slope_mm} mm) do not fit in a "
                f"{self.bezel_width_mm} mm bezel"
            )
        if 2 * self.margin_mm >= min(self.display_width_mm, self.display_height_mm):
            raise ValueError(
                f"a {self.margin_mm} mm margin on both sides leaves no "
                f"playfield in a {self.display_width_mm:.0f} x "
                f"{self.display_height_mm:.0f} mm display"
            )

    # ------------------------------------------------------------------
    # Rectangles
    # ------------------------------------------------------------------

    @property
    def margin_mm(self) -> float:
        """Everything between the display edge and the playfield."""
        return self.bezel_width_mm + self.score_band_mm

    @property
    def display_rect(self) -> RectMM:
        return RectMM(self.display_width_mm, self.display_height_mm)

    @property
    def playfield_rect(self) -> RectMM:
        return RectMM(
            self.display_width_mm - 2 * self.margin_mm,
            self.display_height_mm - 2 * self.margin_mm,
        )

    @property
    def playfield_width_mm(self) -> float:
        return self.playfield_rect.width_mm

    @property
    def playfield_height_mm(self) -> float:
        return self.playfield_rect.height_mm

    # ------------------------------------------------------------------
    # Cross-sections, as (inset_from_display_edge_mm, z_mm) profiles
    # ------------------------------------------------------------------

    def bezel_cross_section(self) -> tuple[tuple[float, float], ...]:
        """The raised moulding's profile.

        Returned rather than hardcoded in the mesh builder so the renderer
        and the tests agree on the shape by construction.
        """
        return (
            (0.0, 0.0),
            (self.bezel_outer_slope_mm, self.bezel_rise_mm),
            (self.bezel_width_mm - self.bezel_inner_slope_mm, self.bezel_rise_mm),
            (self.bezel_width_mm, 0.0),
        )

    def inlay_cross_section(self) -> tuple[tuple[float, float], ...]:
        """A stripe along the bezel's flat top, just above it.

        Inset to the middle of the flat section so the chamfers stay clear
        on both sides, which is what makes it read as an inlaid line rather
        than as the bezel being two colours.
        """
        flat_start = self.bezel_outer_slope_mm
        flat_end = self.bezel_width_mm - self.bezel_inner_slope_mm
        flat = max(flat_end - flat_start, 0.0)
        stripe = flat * 0.5
        start = flat_start + (flat - stripe) / 2.0
        z = self.bezel_rise_mm + 0.3
        return ((start, z), (start + stripe, z))

    def edge_line_cross_section(
        self, width_mm: float = 2.5
    ) -> tuple[tuple[float, float], ...]:
        """A thin line at the playfield boundary, on the inner edge of the band."""
        z = 0.5
        return ((self.margin_mm - width_mm, z), (self.margin_mm, z))

    def band_cross_section(self, z_mm: float = 0.25) -> tuple[tuple[float, float], ...]:
        """The flat band's profile: a ring just above the glass, so it cannot
        z-fight with anything else drawn on that plane."""
        return ((self.bezel_width_mm, z_mm), (self.margin_mm, z_mm))

    # ------------------------------------------------------------------
    # Scoreboard
    # ------------------------------------------------------------------

    @property
    def score_centre_offset_mm(self) -> float:
        """Distance from the display edge to the middle of the band."""
        return self.bezel_width_mm + self.score_band_mm / 2.0

    def score_anchor(self) -> tuple[float, float, float]:
        """Centre of the scoreboard, on the near (-Y) band: ``(x, y, z)`` mm.

        The near edge, because that is the direction the artwork is drawn
        upright for.
        """
        return (
            0.0,
            -self.display_height_mm / 2.0 + self.score_centre_offset_mm,
            0.8,
        )

    def exit_button_rect(self) -> RectMM:
        """The quit target, at the far end of the near band.

        Lives here rather than in the view because two things have to agree
        on it exactly -- what is drawn and what a tap is tested against --
        and a button whose box is not where it looks is worse than no
        button.
        """
        _, band_y, _ = self.score_anchor()
        return RectMM(
            EXIT_BUTTON_WIDTH_MM,
            EXIT_BUTTON_HEIGHT_MM,
            self.score_band_length_mm / 2.0 - EXIT_BUTTON_WIDTH_MM / 2.0 - 18.0,
            band_y,
        )

    @property
    def score_band_length_mm(self) -> float:
        """Room the scoreboard has along its edge."""
        return self.playfield_width_mm

    def describe(self) -> str:
        return (
            f"layout: display {self.display_width_mm:.0f} x "
            f"{self.display_height_mm:.0f} mm\n"
            f"  bezel      {self.bezel_width_mm:.0f} mm wide, "
            f"{self.bezel_rise_mm:.0f} mm proud\n"
            f"  score band {self.score_band_mm:.0f} mm\n"
            f"  playfield  {self.playfield_width_mm:.0f} x "
            f"{self.playfield_height_mm:.0f} mm"
        )
