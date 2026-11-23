"""Procedural mesh geometry, checked without a graphics context.

Mesh construction needs Panda3D but not a window, so these run with the
fast tests. Worth having: geometry faults here are silent -- the scene draws
something, just not the right thing.
"""

from __future__ import annotations

import pytest

from tabletop.core.layout import TableLayout
from tabletop.render.mapping import world_to_table
from tabletop.render.meshes import field_patch_mesh, ring_mesh

CELL_W = 131.5
CELL_H = 125.7
HOLE_R = 40.0

TOL_MM = 1e-3
"""Vertices are float32, so millimetre values come back a few ten-thousandths
off. Tighter than this tests the storage format, not the geometry."""


def table_points(mesh) -> list[tuple[float, float, float]]:
    return [world_to_table(v[0], v[1], v[2]) for v in mesh.vertices]


class TestFieldPatch:
    """The patches tile the playfield, so their boundaries must be exact.

    A patch whose outer ring only approximates its cell rectangle leaves a
    diamond-shaped gap at every shared corner, and the window background
    shows through the ground. Whether it happens depends on the cell's
    aspect ratio, which is exactly the kind of fault that reappears when the
    grid is re-tuned.
    """

    @pytest.mark.parametrize(
        "cell_w,cell_h",
        [
            (131.5, 125.7),  # near-square: corners fall between samples
            (156.8, 132.2),
            (200.0, 100.0),
            (100.0, 200.0),
        ],
    )
    def test_outer_ring_lies_on_the_cell_rectangle(
        self, cell_w: float, cell_h: float
    ) -> None:
        mesh = field_patch_mesh(
            cell_width_mm=cell_w,
            cell_height_mm=cell_h,
            hole_radius_mm=HOLE_R,
            segments=18,
        )
        half_w, half_h = cell_w / 2.0, cell_h / 2.0

        outer = [
            (x, y)
            for x, y, _ in table_points(mesh)
            if abs(x) > HOLE_R + TOL_MM or abs(y) > HOLE_R + TOL_MM
        ]
        assert outer, "patch has no boundary vertices"
        for x, y in outer:
            on_edge = (
                abs(abs(x) - half_w) < TOL_MM or abs(abs(y) - half_h) < TOL_MM
            )
            assert on_edge, f"vertex ({x:.3f}, {y:.3f}) is off the cell edge"
            assert abs(x) <= half_w + TOL_MM
            assert abs(y) <= half_h + TOL_MM

    @pytest.mark.parametrize(
        "cell_w,cell_h", [(131.5, 125.7), (156.8, 132.2), (200.0, 100.0)]
    )
    def test_all_four_cell_corners_are_present(
        self, cell_w: float, cell_h: float
    ) -> None:
        mesh = field_patch_mesh(
            cell_width_mm=cell_w,
            cell_height_mm=cell_h,
            hole_radius_mm=HOLE_R,
            segments=18,
        )
        points = [(x, y) for x, y, _ in table_points(mesh)]
        half_w, half_h = cell_w / 2.0, cell_h / 2.0
        for sx in (-1, 1):
            for sy in (-1, 1):
                corner = (sx * half_w, sy * half_h)
                nearest = min(
                    max(abs(x - corner[0]), abs(y - corner[1]))
                    for x, y in points
                )
                assert nearest < TOL_MM, f"missing corner {corner}"

    def test_patch_is_offset_with_its_hole(self) -> None:
        mesh = field_patch_mesh(
            cell_width_mm=CELL_W,
            cell_height_mm=CELL_H,
            hole_radius_mm=HOLE_R,
            centre_xy_mm=(300.0, -120.0),
            segments=12,
        )
        xs = [x for x, _, _ in table_points(mesh)]
        assert min(xs) == pytest.approx(300.0 - CELL_W / 2)
        assert max(xs) == pytest.approx(300.0 + CELL_W / 2)

    def test_a_hole_too_big_for_its_cell_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not fit"):
            field_patch_mesh(
                cell_width_mm=60.0, cell_height_mm=60.0, hole_radius_mm=40.0
            )


class TestRing:
    def test_profile_z_values_are_the_only_heights(self) -> None:
        layout = TableLayout(941.0, 529.0)
        profile = layout.bezel_cross_section()
        mesh = ring_mesh(941.0, 529.0, profile)
        heights = {round(z, 6) for _, _, z in table_points(mesh)}
        assert heights == {round(z, 6) for _, z in profile}

    def test_outer_edge_is_the_display_edge(self) -> None:
        mesh = ring_mesh(941.0, 529.0, ((0.0, 0.0), (18.0, 10.0)))
        xs = [x for x, _, _ in table_points(mesh)]
        ys = [y for _, y, _ in table_points(mesh)]
        assert max(xs) == pytest.approx(941.0 / 2)
        assert max(ys) == pytest.approx(529.0 / 2)

    def test_inner_edge_is_inset_by_the_last_profile_point(self) -> None:
        mesh = ring_mesh(941.0, 529.0, ((0.0, 0.0), (18.0, 10.0)))
        ys = sorted({round(y, 4) for _, y, _ in table_points(mesh)})
        # Two rings: the display edge and one 18 mm in, top and bottom.
        assert ys == [
            pytest.approx(-529.0 / 2),
            pytest.approx(-529.0 / 2 + 18.0),
            pytest.approx(529.0 / 2 - 18.0),
            pytest.approx(529.0 / 2),
        ]

    def test_band_ring_is_flat(self) -> None:
        layout = TableLayout(941.0, 529.0)
        mesh = ring_mesh(941.0, 529.0, layout.band_cross_section())
        heights = {round(z, 6) for _, _, z in table_points(mesh)}
        assert len(heights) == 1

    def test_a_short_profile_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least 2 points"):
            ring_mesh(941.0, 529.0, ((0.0, 0.0),))

    def test_an_inset_past_the_centre_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="leaves no rectangle"):
            ring_mesh(941.0, 529.0, ((0.0, 0.0), (400.0, 10.0)))
