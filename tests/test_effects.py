"""Impact effects, tested without a graphics context.

The failures worth catching here are the ones a screenshot cannot show:
particles that never settle, lists that grow without bound, and bursts that
do not reproduce for a given seed.
"""

from __future__ import annotations

import pytest

from tabletop.game.effects import EffectConfig, ImpactEffects


def make_effects(**kwargs) -> ImpactEffects:
    return ImpactEffects(EffectConfig(**kwargs), seed=42)


class TestEmission:
    def test_a_hit_emits_droplets_and_one_splat(self) -> None:
        fx = make_effects()
        fx.emit_hit(100.0, -50.0)
        cfg = fx.config
        assert len(fx.droplets) == cfg.droplets_per_hit + cfg.gore_per_hit
        assert len(fx.splats) == 1

    def test_the_burst_starts_at_the_impact(self) -> None:
        fx = make_effects()
        fx.emit_hit(100.0, -50.0)
        assert fx.splats[0].x_mm == pytest.approx(100.0)
        assert fx.splats[0].y_mm == pytest.approx(-50.0)
        for drop in fx.droplets:
            assert abs(drop.x_mm - 100.0) < 20.0
            assert abs(drop.y_mm + 50.0) < 20.0
            assert drop.z_mm == pytest.approx(fx.config.spawn_height_mm)

    def test_both_droplets_and_gore_are_produced(self) -> None:
        fx = make_effects()
        fx.emit_hit(0.0, 0.0)
        kinds = {drop.gore for drop in fx.droplets}
        assert kinds == {False, True}

    def test_gore_is_larger_than_a_droplet(self) -> None:
        fx = make_effects()
        fx.emit_hit(0.0, 0.0)
        biggest_droplet = max(d.radius_mm for d in fx.droplets if not d.gore)
        smallest_gore = min(d.radius_mm for d in fx.droplets if d.gore)
        assert smallest_gore > biggest_droplet


class TestMotion:
    def test_droplets_rise_then_fall_and_settle(self) -> None:
        fx = make_effects()
        fx.emit_hit(0.0, 0.0)
        start = fx.droplets[0].z_mm

        peak = start
        for _ in range(30):
            fx.update(1 / 120)
            if fx.droplets:
                peak = max(peak, fx.droplets[0].z_mm)
        assert peak > start, "nothing was thrown upward"

        for _ in range(400):
            fx.update(1 / 120)
            if not fx.droplets:
                break
        assert fx.droplets == []

    def test_a_settled_droplet_stops_moving_and_stays_above_the_ground(
        self,
    ) -> None:
        fx = make_effects(droplet_life_min_s=9.0, droplet_life_max_s=9.0)
        fx.emit_hit(0.0, 0.0)
        for _ in range(200):
            fx.update(1 / 120)

        assert fx.droplets, "life was long enough that these should still exist"
        for drop in fx.droplets:
            assert drop.settled
            assert 0.0 < drop.z_mm < 5.0
            assert (drop.vx_mm_s, drop.vy_mm_s, drop.vz_mm_s) == (0.0, 0.0, 0.0)

        before = [(d.x_mm, d.y_mm) for d in fx.droplets]
        fx.update(0.2)
        assert [(d.x_mm, d.y_mm) for d in fx.droplets] == before

    def test_a_splat_grows_to_its_radius_then_holds(self) -> None:
        fx = make_effects()
        fx.emit_hit(0.0, 0.0)
        splat = fx.splats[0]
        assert splat.radius_mm == pytest.approx(0.0)

        fx.update(splat.grow_s)
        grown = splat.radius_mm
        assert grown == pytest.approx(splat.max_radius_mm, rel=1e-6)

        fx.update(0.1)
        assert splat.radius_mm == pytest.approx(grown)

    def test_everything_fades_from_one_to_zero(self) -> None:
        fx = make_effects()
        fx.emit_hit(0.0, 0.0)
        assert fx.droplets[0].remaining == pytest.approx(1.0)
        fx.update(fx.droplets[0].life_s * 0.5)
        assert 0.0 < fx.droplets[0].remaining < 1.0

    def test_negative_dt_is_rejected(self) -> None:
        fx = make_effects()
        with pytest.raises(ValueError, match="must not be negative"):
            fx.update(-0.01)


class TestBounds:
    def test_droplets_are_capped(self) -> None:
        """The view allocates one entity per droplet up front, so the cap is
        a rendering contract rather than a hint."""
        fx = make_effects(max_droplets=20)
        for _ in range(40):
            fx.emit_hit(0.0, 0.0)
        assert len(fx.droplets) <= 20

    def test_splats_are_capped(self) -> None:
        fx = make_effects(max_splats=3)
        for _ in range(10):
            fx.emit_hit(0.0, 0.0)
        assert len(fx.splats) <= 3

    def test_clear_empties_everything(self) -> None:
        fx = make_effects()
        fx.emit_hit(0.0, 0.0)
        fx.clear()
        assert fx.droplets == [] and fx.splats == []


class TestDeterminism:
    def test_same_seed_gives_the_same_burst(self) -> None:
        def run() -> list[tuple[float, float, float]]:
            fx = ImpactEffects(EffectConfig(), seed=7)
            fx.emit_hit(10.0, 20.0)
            for _ in range(10):
                fx.update(1 / 60)
            return [(d.x_mm, d.y_mm, d.z_mm) for d in fx.droplets]

        assert run() == run()

    def test_different_seeds_differ(self) -> None:
        def run(seed: int) -> list[float]:
            fx = ImpactEffects(EffectConfig(), seed=seed)
            fx.emit_hit(0.0, 0.0)
            return [d.vx_mm_s for d in fx.droplets]

        assert run(1) != run(2)
