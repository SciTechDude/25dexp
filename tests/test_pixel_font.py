"""The 5x7 pixel font: glyph table, metrics and mesh layout."""

from __future__ import annotations

import pytest

from tabletop.render.mapping import mm_to_world
from tabletop.render.pixel_font import (
    ADVANCE_PX,
    GLYPH_H,
    GLYPH_W,
    GLYPHS,
    LINE_PX,
    text_height_px,
    text_mesh,
    text_width_px,
)

REQUIRED = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:/-+%()[]"


class TestGlyphTable:
    @pytest.mark.parametrize("char", list(REQUIRED), ids=lambda c: repr(c))
    def test_every_character_the_game_uses_has_a_glyph(self, char: str) -> None:
        assert char in GLYPHS

    @pytest.mark.parametrize("char", sorted(GLYPHS), ids=lambda c: repr(c))
    def test_every_glyph_is_exactly_5_by_7(self, char: str) -> None:
        rows = GLYPHS[char]
        assert len(rows) == GLYPH_H
        for row in rows:
            assert len(row) == GLYPH_W
            assert set(row) <= {"#", "."}

    def test_space_is_blank_and_letters_are_not(self) -> None:
        assert all(cell == "." for row in GLYPHS[" "] for cell in row)
        assert any(cell == "#" for row in GLYPHS["A"] for cell in row)


class TestMetrics:
    def test_one_character_is_one_glyph_wide(self) -> None:
        assert text_width_px("A") == GLYPH_W

    def test_characters_advance_with_a_gap_between_them(self) -> None:
        assert text_width_px("AB") == ADVANCE_PX + GLYPH_W

    def test_width_follows_the_longest_line(self) -> None:
        assert text_width_px("A\nABC") == text_width_px("ABC")

    def test_height_grows_by_a_line_at_a_time(self) -> None:
        assert text_height_px("A") == GLYPH_H
        assert text_height_px("A\nB") == GLYPH_H + LINE_PX

    def test_empty_text_has_no_extent(self) -> None:
        assert text_width_px("") == 0
        assert text_height_px("") == 0


class TestMesh:
    def test_one_quad_per_inked_character(self) -> None:
        mesh = text_mesh("AB", pixel_mm=2.0)
        assert mesh is not None
        assert len(mesh.vertices) == 2 * 4
        assert len(mesh.uvs) == len(mesh.vertices)
        assert len(mesh.triangles) == 2 * 6

    def test_blank_characters_cost_nothing(self) -> None:
        """Spaces still advance the cursor but emit no geometry."""
        spaced = text_mesh("A B", pixel_mm=2.0)
        assert spaced is not None
        assert len(spaced.vertices) == 2 * 4

    def test_text_with_nothing_to_draw_has_no_mesh(self) -> None:
        assert text_mesh("   ", pixel_mm=2.0) is None
        assert text_mesh("", pixel_mm=2.0) is None

    def test_lower_case_is_drawn_as_capitals(self) -> None:
        upper = text_mesh("AB", pixel_mm=2.0)
        lower = text_mesh("ab", pixel_mm=2.0)
        assert lower is not None and upper is not None
        assert len(lower.vertices) == len(upper.vertices)

    def test_a_centred_block_straddles_its_anchor(self) -> None:
        mesh = text_mesh("MM", pixel_mm=2.0, origin=(0, 0))
        xs = [v[0] for v in mesh.vertices]
        assert min(xs) == pytest.approx(-max(xs), abs=1e-6)

    def test_left_aligned_text_starts_at_its_anchor(self) -> None:
        mesh = text_mesh("MM", pixel_mm=2.0, origin=(-0.5, 0))
        xs = [v[0] for v in mesh.vertices]
        assert min(xs) == pytest.approx(0.0, abs=1e-6)

    def test_right_aligned_text_ends_at_its_anchor(self) -> None:
        mesh = text_mesh("MM", pixel_mm=2.0, origin=(0.5, 0))
        xs = [v[0] for v in mesh.vertices]
        assert max(xs) == pytest.approx(0.0, abs=1e-6)

    def test_a_glyph_is_the_size_the_pixel_scale_asks_for(self) -> None:
        mesh = text_mesh("A", pixel_mm=3.0)
        xs = [v[0] for v in mesh.vertices]
        ys = [v[1] for v in mesh.vertices]
        assert max(xs) - min(xs) == pytest.approx(mm_to_world(GLYPH_W * 3.0))
        assert max(ys) - min(ys) == pytest.approx(mm_to_world(GLYPH_H * 3.0))

    def test_later_lines_sit_below_earlier_ones(self) -> None:
        mesh = text_mesh("A\nA", pixel_mm=2.0)
        ys = sorted({round(v[1], 6) for v in mesh.vertices})
        assert len(ys) == 4  # two quads, two distinct edges each

    def test_uvs_stay_inside_the_atlas(self) -> None:
        mesh = text_mesh("WHACK-A-MOLE 1234567890", pixel_mm=2.0)
        for u, v in mesh.uvs:
            assert 0.0 <= u <= 1.0
            assert 0.0 <= v <= 1.0
