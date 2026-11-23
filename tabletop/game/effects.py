"""Impact effects: airborne droplets and the splats they leave.

Pure Python in table millimetres, like the rules, and for the same reason:
a particle system looks right in a screenshot while being subtly wrong --
particles that never settle, or lists that leak until the frame rate dies --
and all of that is checkable without a GL context. The view owns a fixed
pool of entities and copies state out of here each frame.

An impact produces two things:

* **A splat**, flat on the ground, which expands fast and lingers long
  enough to still be there when the player looks back.
* **Droplets**, thrown outward and upward under gravity, which settle onto
  the ground and fade where they land.

The mole's own squash is the view's business, since it is a property of the
sprite rather than of the world.

Counts are modest and lifetimes short: this plays several times a second
late in a round, and anything longer overlaps itself.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

__all__ = ["Droplet", "Splat", "EffectConfig", "ImpactEffects"]


@dataclass
class Droplet:
    """One airborne dot, in table millimetres."""

    x_mm: float
    y_mm: float
    z_mm: float
    vx_mm_s: float
    vy_mm_s: float
    vz_mm_s: float
    radius_mm: float
    age_s: float = 0.0
    life_s: float = 0.5
    settled: bool = False
    """Landed on the glass. It stops moving and only fades from here, which
    is what turns a shower of dots into spatter *on* the field."""

    gore: bool = False
    """A chunk of mole rather than a droplet: bigger, slower, browner."""

    @property
    def remaining(self) -> float:
        """1 at birth, 0 at death. The view uses this for alpha."""
        if self.life_s <= 0:
            return 0.0
        return max(0.0, 1.0 - self.age_s / self.life_s)

    @property
    def alive(self) -> bool:
        return self.age_s < self.life_s


@dataclass
class Splat:
    """The flat mark left on the ground at the point of impact."""

    x_mm: float
    y_mm: float
    radius_mm: float
    """Current radius. Grows quickly, then holds."""

    max_radius_mm: float
    age_s: float = 0.0
    life_s: float = 1.1
    grow_s: float = 0.09

    @property
    def remaining(self) -> float:
        if self.life_s <= 0:
            return 0.0
        return max(0.0, 1.0 - self.age_s / self.life_s)

    @property
    def alive(self) -> bool:
        return self.age_s < self.life_s


@dataclass(frozen=True)
class EffectConfig:
    """Tuning for one impact. Millimetres and seconds throughout."""

    droplets_per_hit: int = 11
    gore_per_hit: int = 3

    speed_min_mm_s: float = 220.0
    speed_max_mm_s: float = 640.0
    lift_min_mm_s: float = 420.0
    lift_max_mm_s: float = 1000.0
    gravity_mm_s2: float = -3200.0
    """Strong on purpose: real gravity (-9810) over a 150 mm throw is a
    400 ms arc, which outlasts the mole's retract and reads as floating
    debris."""

    droplet_radius_min_mm: float = 3.0
    droplet_radius_max_mm: float = 7.5
    gore_radius_min_mm: float = 8.0
    gore_radius_max_mm: float = 13.0

    droplet_life_min_s: float = 0.45
    droplet_life_max_s: float = 0.85
    splat_life_s: float = 1.15
    splat_radius_mm: float = 58.0

    spawn_height_mm: float = 60.0
    """Where the burst originates above the glass -- roughly the middle of a
    risen mole, so the spray appears to come off the body rather than out of
    the ground."""

    max_droplets: int = 160
    """Hard cap. The view allocates exactly this many entities once, so the
    cap is a rendering contract, not a hint: exceeding it would need entity
    churn mid-round. Oldest droplets are dropped first."""

    max_splats: int = 24


class ImpactEffects:
    """Droplets and splats for the current round.

    Deterministic for a given seed, so a captured frame is reproducible --
    which is what makes the headless render check meaningful for an effect
    whose whole character is randomness.
    """

    def __init__(
        self, config: EffectConfig | None = None, seed: int | None = None
    ) -> None:
        self.config = config or EffectConfig()
        self._rng = random.Random(seed)
        self.droplets: list[Droplet] = []
        self.splats: list[Splat] = []
        self.hits = 0

    # ------------------------------------------------------------------

    def emit_hit(self, x_mm: float, y_mm: float) -> None:
        """Burst at one struck mole."""
        cfg = self.config
        rng = self._rng
        self.hits += 1

        self.splats.append(
            Splat(
                x_mm=x_mm,
                y_mm=y_mm,
                radius_mm=0.0,
                # Varied so repeated hits on the same hole do not stamp an
                # identical mark, which reads as a texture bug.
                max_radius_mm=cfg.splat_radius_mm * rng.uniform(0.8, 1.15),
                life_s=cfg.splat_life_s,
            )
        )
        if len(self.splats) > cfg.max_splats:
            del self.splats[: len(self.splats) - cfg.max_splats]

        for gore in (False,) * cfg.droplets_per_hit + (True,) * cfg.gore_per_hit:
            angle = rng.uniform(0.0, 2.0 * math.pi)
            speed = rng.uniform(cfg.speed_min_mm_s, cfg.speed_max_mm_s)
            lift = rng.uniform(cfg.lift_min_mm_s, cfg.lift_max_mm_s)
            if gore:
                # Chunks are heavier: less sideways throw, more hang time.
                speed *= 0.6
                lift *= 0.85
            self.droplets.append(
                Droplet(
                    x_mm=x_mm + math.cos(angle) * rng.uniform(0.0, 12.0),
                    y_mm=y_mm + math.sin(angle) * rng.uniform(0.0, 12.0),
                    z_mm=cfg.spawn_height_mm,
                    vx_mm_s=math.cos(angle) * speed,
                    vy_mm_s=math.sin(angle) * speed,
                    vz_mm_s=lift,
                    radius_mm=rng.uniform(
                        cfg.gore_radius_min_mm if gore else cfg.droplet_radius_min_mm,
                        cfg.gore_radius_max_mm if gore else cfg.droplet_radius_max_mm,
                    ),
                    life_s=rng.uniform(cfg.droplet_life_min_s, cfg.droplet_life_max_s),
                    gore=gore,
                )
            )

        if len(self.droplets) > cfg.max_droplets:
            del self.droplets[: len(self.droplets) - cfg.max_droplets]

    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        if dt < 0:
            raise ValueError(f"dt must not be negative, got {dt}")
        cfg = self.config

        for d in self.droplets:
            d.age_s += dt
            if d.settled:
                continue
            d.vz_mm_s += cfg.gravity_mm_s2 * dt
            d.x_mm += d.vx_mm_s * dt
            d.y_mm += d.vy_mm_s * dt
            d.z_mm += d.vz_mm_s * dt
            if d.z_mm <= 0.0:
                # Land rather than bounce, and park just clear of the ground
                # so the dot is not coplanar with the field patches.
                d.settled = True
                d.z_mm = 0.8
                d.vx_mm_s = d.vy_mm_s = d.vz_mm_s = 0.0

        for s in self.splats:
            s.age_s += dt
            grow = 1.0 if s.grow_s <= 0 else min(1.0, s.age_s / s.grow_s)
            # Ease out, so it snaps open and then stops rather than
            # inflating steadily like a balloon.
            s.radius_mm = s.max_radius_mm * (1.0 - (1.0 - grow) ** 2)

        self.droplets = [d for d in self.droplets if d.alive]
        self.splats = [s for s in self.splats if s.alive]

    def clear(self) -> None:
        self.droplets.clear()
        self.splats.clear()
