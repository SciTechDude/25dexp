"""Screen measurements: the mapping, and the round-trips.

The two-rectangle model -- picture and touch area -- is the part most likely
to be quietly wrong, because a constant few-millimetre error looks like
tracking drift rather than a measurement bug. These tests pin the mapping at
known points.
"""

from __future__ import annotations

import json

import pytest

from tabletop.core.calibration import TableCalibration
from tabletop.core.geometry import RectMM


@pytest.fixture
def cal() -> TableCalibration:
    """A deliberately imperfect screen: touch area larger than the picture and
    offset from it, which is the normal physical situation."""
    return TableCalibration(
        display_width_mm=1000.0,
        display_height_mm=500.0,
        display_width_px=2000,
        display_height_px=1000,
        touch_width_mm=1010.0,
        touch_height_mm=510.0,
        touch_offset_x_mm=4.0,
        touch_offset_y_mm=-2.0,
        raw_x_max=1000,
        raw_y_max=1000,
        invert_y=True,
        raw_major_max=1000,
        label="test",
    )


class TestIrMapping:
    def test_centre_of_device_maps_to_ir_centre_not_screen_centre(
        self, cal: TableCalibration
    ) -> None:
        """The midpoint of the device's range is the centre of the *touch*
        rectangle, which is offset from the image centre. Collapsing the two
        rectangles would wrongly put this at (0, 0)."""
        x_mm, y_mm = cal.raw_to_table_mm(500, 500)
        assert x_mm == pytest.approx(4.0)
        assert y_mm == pytest.approx(-2.0)

    def test_corners_map_to_touch_rectangle_corners(self, cal: TableCalibration) -> None:
        # Raw (0, 0) is the device's top-left; with Y inverted that is the
        # table's bottom-left in the touch rectangle.
        x_mm, y_mm = cal.raw_to_table_mm(0, 0)
        assert x_mm == pytest.approx(4.0 - 505.0)
        assert y_mm == pytest.approx(-2.0 + 255.0)

        x_mm, y_mm = cal.raw_to_table_mm(1000, 1000)
        assert x_mm == pytest.approx(4.0 + 505.0)
        assert y_mm == pytest.approx(-2.0 - 255.0)

    def test_y_inversion_can_be_disabled(self, cal: TableCalibration) -> None:
        flipped = TableCalibration(**{**cal.to_dict(), "invert_y": False})
        _, y_up = flipped.raw_to_table_mm(500, 0)
        _, y_down = cal.raw_to_table_mm(500, 0)
        assert y_up == pytest.approx(-y_down - 4.0, abs=1e-6)

    def test_x_inversion(self, cal: TableCalibration) -> None:
        flipped = TableCalibration(**{**cal.to_dict(), "invert_x": True})
        x_normal, _ = cal.raw_to_table_mm(0, 500)
        x_flipped, _ = flipped.raw_to_table_mm(0, 500)
        assert x_normal < 0 < x_flipped

    def test_out_of_range_raw_is_not_clamped(self, cal: TableCalibration) -> None:
        """A contact reported outside the active area means the calibration
        or the frame is wrong. Silently clamping would hide that."""
        x_mm, _ = cal.raw_to_table_mm(1200, 500)
        assert x_mm > cal.touch_rect.max_x_mm

    def test_degenerate_axis_range_is_rejected(self) -> None:
        bad = TableCalibration(
            display_width_mm=1000.0,
            display_height_mm=500.0,
            display_width_px=2000,
            display_height_px=1000,
            touch_width_mm=1000.0,
            touch_height_mm=500.0,
            raw_x_min=5,
            raw_x_max=5,
        )
        with pytest.raises(ValueError, match="degenerate device axis"):
            bad.raw_to_table_mm(5, 5)


class TestContactSize:
    def test_size_scales_by_the_x_axis(self, cal: TableCalibration) -> None:
        # Half the device range across a 1010 mm active width.
        assert cal.raw_major_to_mm(500) == pytest.approx(505.0)

    def test_absent_size_stays_none(self, cal: TableCalibration) -> None:
        """None must survive the conversion. Returning 0.0 instead would be
        read downstream as 'a very small contact', which is how size-based
        size-based filtering ends up silently inverted on a device with no
        size at all."""
        assert cal.raw_major_to_mm(None) is None

    def test_frame_without_size_support_returns_none(
        self, cal: TableCalibration
    ) -> None:
        no_size = TableCalibration(**{**cal.to_dict(), "raw_major_max": None})
        assert not no_size.reports_contact_size
        assert no_size.raw_major_to_mm(500) is None


class TestPixelMapping:
    def test_round_trip(self, cal: TableCalibration) -> None:
        for x_mm, y_mm in [(0.0, 0.0), (-500.0, 250.0), (123.4, -56.7)]:
            px = cal.table_mm_to_px(x_mm, y_mm)
            back = cal.px_to_table_mm(*px)
            assert back[0] == pytest.approx(x_mm)
            assert back[1] == pytest.approx(y_mm)

    def test_table_origin_is_image_centre(self, cal: TableCalibration) -> None:
        assert cal.table_mm_to_px(0.0, 0.0) == pytest.approx((1000.0, 500.0))

    def test_pixel_y_increases_downward_while_table_y_increases_away(
        self, cal: TableCalibration
    ) -> None:
        _, py_far = cal.table_mm_to_px(0.0, 200.0)
        _, py_near = cal.table_mm_to_px(0.0, -200.0)
        assert py_far < py_near

    def test_px_per_mm(self, cal: TableCalibration) -> None:
        assert cal.px_per_mm_x == pytest.approx(2.0)
        assert cal.px_per_mm_y == pytest.approx(2.0)


class TestPlausibilityChecks:
    def test_clean_calibration_has_no_complaints(self, cal: TableCalibration) -> None:
        assert cal.problems() == []

    def test_ir_smaller_than_image_is_flagged(self, cal: TableCalibration) -> None:
        bad = TableCalibration(**{**cal.to_dict(), "touch_width_mm": 900.0})
        assert any("untouchable" in p for p in bad.problems())

    def test_aspect_mismatch_is_flagged(self, cal: TableCalibration) -> None:
        bad = TableCalibration(**{**cal.to_dict(), "display_height_mm": 400.0})
        assert any("aspect" in p for p in bad.problems())

    def test_missing_size_support_is_flagged(self, cal: TableCalibration) -> None:
        bad = TableCalibration(**{**cal.to_dict(), "raw_major_max": None})
        assert any("no contact size" in p for p in bad.problems())

    def test_describe_mentions_problems(self, cal: TableCalibration) -> None:
        bad = TableCalibration(**{**cal.to_dict(), "touch_width_mm": 900.0})
        assert "!" in bad.describe()


class TestPersistence:
    def test_save_load_round_trip(self, cal: TableCalibration, tmp_path) -> None:
        path = tmp_path / "nested" / "cal.json"
        cal.save(path)
        assert TableCalibration.load(path) == cal

    def test_unknown_field_is_rejected(self, cal: TableCalibration, tmp_path) -> None:
        """Better to fail loudly than to load a file whose extra key was
        meant to change behaviour and is being ignored."""
        path = tmp_path / "cal.json"
        payload = cal.to_dict()
        payload["touch_rotation_deg"] = 1.5
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError, match="unknown calibration fields"):
            TableCalibration.load(path)

    def test_version_mismatch_is_rejected(self, cal: TableCalibration, tmp_path) -> None:
        path = tmp_path / "cal.json"
        payload = cal.to_dict()
        payload["version"] = 99
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError, match="version 99"):
            TableCalibration.load(path)


class TestGeometry:
    def test_rect_rejects_zero_extent(self) -> None:
        with pytest.raises(ValueError, match="positive extent"):
            RectMM(0.0, 10.0)

    def test_normalise_round_trip(self) -> None:
        rect = RectMM(100.0, 50.0, 10.0, -5.0)
        u, v = rect.normalise(35.0, 12.0)
        assert rect.denormalise(u, v) == pytest.approx((35.0, 12.0))

    def test_normalise_corners(self) -> None:
        rect = RectMM(100.0, 50.0)
        assert rect.normalise(-50.0, -25.0) == pytest.approx((0.0, 0.0))
        assert rect.normalise(50.0, 25.0) == pytest.approx((1.0, 1.0))

    def test_contains(self) -> None:
        rect = RectMM(100.0, 50.0, 10.0, 0.0)
        assert rect.contains(10.0, 0.0)
        assert not rect.contains(-45.0, 0.0)

    def test_corners_are_counter_clockwise_from_bottom_left(self) -> None:
        rect = RectMM(100.0, 50.0)
        assert rect.corners_mm() == (
            (-50.0, -25.0),
            (50.0, -25.0),
            (50.0, 25.0),
            (-50.0, 25.0),
        )

    def test_development_default_is_self_consistent(self) -> None:
        cal = TableCalibration.development_default()
        assert cal.problems() == []


class TestRectDistance:
    """Used to decide whether the mallet's head overlaps the exit button."""

    RECT = RectMM(76.0, 26.0, 362.5, -229.5)

    def test_a_point_inside_is_zero_away(self) -> None:
        assert self.RECT.distance_to(362.5, -229.5) == 0.0
        assert self.RECT.distance_to(400.0, -220.0) == 0.0

    def test_distance_is_measured_to_the_nearest_edge(self) -> None:
        assert self.RECT.distance_to(362.5, -200.0) == pytest.approx(16.5)
        assert self.RECT.distance_to(420.5, -229.5) == pytest.approx(20.0)

    def test_corners_measure_diagonally(self) -> None:
        assert self.RECT.distance_to(
            self.RECT.max_x_mm + 3.0, self.RECT.max_y_mm + 4.0
        ) == pytest.approx(5.0)

    def test_it_never_returns_a_negative(self) -> None:
        for x in (-500.0, 0.0, 362.5, 500.0):
            for y in (-500.0, -229.5, 0.0, 500.0):
                assert self.RECT.distance_to(x, y) >= 0.0
