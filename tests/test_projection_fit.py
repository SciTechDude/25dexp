"""Viewport fitting and the glass-plane inverse projection."""

from __future__ import annotations

import pytest

from tabletop.render.projection import (
    Eye,
    ProjectionMode,
    fit_film_to_viewport,
    lens_params_for,
    off_axis_frustum,
    project_point,
    screen_ndc_to_glass_mm,
)

SCREEN_W = 941.0
SCREEN_H = 529.0


class TestFitFilmToViewport:
    def test_matching_aspect_is_a_no_op(self) -> None:
        film = fit_film_to_viewport(SCREEN_W, SCREEN_H, SCREEN_W / SCREEN_H)
        assert film == pytest.approx((SCREEN_W, SCREEN_H))

    def test_wider_window_grows_the_film_horizontally(self) -> None:
        """A wide window must not stretch the table; it gets bars at the
        sides, so the film grows in width while height is preserved."""
        film_w, film_h = fit_film_to_viewport(SCREEN_W, SCREEN_H, 2.5)
        assert film_h == pytest.approx(SCREEN_H)
        assert film_w > SCREEN_W
        assert film_w / film_h == pytest.approx(2.5)

    def test_taller_window_grows_the_film_vertically(self) -> None:
        film_w, film_h = fit_film_to_viewport(SCREEN_W, SCREEN_H, 1.0)
        assert film_w == pytest.approx(SCREEN_W)
        assert film_h > SCREEN_H
        assert film_w / film_h == pytest.approx(1.0)

    def test_screen_is_always_contained(self) -> None:
        """The defining property: whatever the window shape, the real table
        rectangle fits inside the film rather than being cropped."""
        for aspect in [0.5, 1.0, 1.3, 16 / 9, 2.0, 3.5]:
            film_w, film_h = fit_film_to_viewport(SCREEN_W, SCREEN_H, aspect)
            assert film_w >= SCREEN_W - 1e-9, f"cropped width at aspect {aspect}"
            assert film_h >= SCREEN_H - 1e-9, f"cropped height at aspect {aspect}"

    def test_invalid_aspect_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="aspect must be positive"):
            fit_film_to_viewport(SCREEN_W, SCREEN_H, 0.0)

    def test_letterboxed_corners_land_inside_the_viewport(self) -> None:
        """With letterboxing the corners no longer touch the viewport edge,
        which is the intended, visible trade for keeping the geometry
        truthful on a mismatched dev window."""
        eye = Eye(0.0, 0.0, 700.0)
        params = lens_params_for(
            ProjectionMode.OFF_AXIS_HEAD_TRACKED,
            SCREEN_W,
            SCREEN_H,
            eye,
            viewport_aspect=1.0,
        )
        # The vertical fraction of the viewport the table occupies.
        assert SCREEN_H / params.film_height < 1.0


class TestGlassPlaneInverse:
    @pytest.mark.parametrize(
        "eye",
        [Eye(0, 0, 700), Eye(350, -200, 600), Eye(-480, 260, 900)],
        ids=lambda e: f"eye{e.x:+.0f},{e.y:+.0f}",
    )
    def test_round_trips_against_the_forward_projection(self, eye: Eye) -> None:
        """Project a point on the glass, then invert it, and get it back --
        for any eye position. This is what lets touch input be mapped
        without knowing where the player's head is."""
        params = lens_params_for(
            ProjectionMode.OFF_AXIS_HEAD_TRACKED, SCREEN_W, SCREEN_H, eye
        )
        matrix = off_axis_frustum(eye, SCREEN_W, SCREEN_H, 10.0, 5000.0)

        for x_mm, y_mm in [(0.0, 0.0), (300.0, -150.0), (-420.0, 230.0)]:
            ndc_x, ndc_y, _ = project_point(matrix, (x_mm, y_mm, 0.0), eye)
            back = screen_ndc_to_glass_mm(ndc_x, ndc_y, params)
            assert back[0] == pytest.approx(x_mm, abs=1e-6)
            assert back[1] == pytest.approx(y_mm, abs=1e-6)

    def test_is_independent_of_projection_mode(self) -> None:
        """All three modes share the same glass-plane inverse, so touch
        handling does not have to branch on the projection in use."""
        eye = Eye(200.0, -100.0, 700.0)
        results = []
        for mode in ProjectionMode:
            params = lens_params_for(mode, SCREEN_W, SCREEN_H, eye)
            results.append(screen_ndc_to_glass_mm(0.5, -0.25, params))
        assert all(r == pytest.approx(results[0]) for r in results)

    def test_viewport_corners_map_to_screen_corners(self) -> None:
        eye = Eye(0.0, 0.0, 700.0)
        params = lens_params_for(
            ProjectionMode.OFF_AXIS_HEAD_TRACKED, SCREEN_W, SCREEN_H, eye
        )
        assert screen_ndc_to_glass_mm(1.0, 1.0, params) == pytest.approx(
            (SCREEN_W / 2.0, SCREEN_H / 2.0)
        )
        assert screen_ndc_to_glass_mm(-1.0, -1.0, params) == pytest.approx(
            (-SCREEN_W / 2.0, -SCREEN_H / 2.0)
        )
