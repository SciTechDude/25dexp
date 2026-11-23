"""Whack-a-mole rules. Pure Python: no renderer, no Ursina, no window.

Keeping the rules renderer-free is what lets the whole game be unit-tested
headlessly, which matters here because graphics bugs are slow to diagnose:
anything verifiable without a GL context should be.

Timings are scaled for a large surface -- moles need longer to be reachable
than they do in a desktop window -- and ramp up over the round.

Motion model
------------
Mole height is a normalised 0..1 value, so the logic owns the *feel* while
the view owns the millimetres. The rise is fast with a slight overshoot and
the retract is slower: linear interpolation reads as software, whereas an
asymmetric profile with overshoot reads as something thrown upward by a
mechanism.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum

from tabletop.core.events import TouchPhase, TouchPoint

__all__ = [
    "MoleState",
    "HoleView",
    "GameConfig",
    "GameEvent",
    "WhackAMole",
    "Difficulty",
    "BEGINNER",
    "MEDIUM",
    "ADVANCED",
    "DIFFICULTIES",
    "difficulty_by_name",
]


class MoleState(str, Enum):
    DOWN = "down"
    RISING = "rising"
    UP = "up"
    DESCENDING = "descending"
    STRUCK = "struck"
    """Hit and retreating fast. Distinct from DESCENDING so the view can
    play an impact squash and the scorer cannot award the same mole twice."""


@dataclass(frozen=True)
class GameConfig:
    """Tuning. All distances in table millimetres, all times in seconds."""

    # --- layout ---
    rows: int = 3
    columns: int = 6
    """Sized to hold the hole pitch at ~130 mm, which suits arm's reach.

    This was 4x6 while the game owned the whole display. The frame and score
    band (see :class:`~tabletop.core.layout.TableLayout`) take 52 mm off
    every side, and four rows in what is left is a 94 mm pitch -- closer
    together than a mole sprite is wide, so neighbours overlap and a tap's
    70 mm tolerance reaches two holes at once. Three rows restores the
    pitch; the simultaneous-mole cap carries the difficulty instead."""

    hole_radius_mm: float = 40.0
    hole_depth_mm: float = 130.0
    """Deep enough that a resting mole's dome sits well below the rim and
    reads as lurking in shadow rather than parked at the surface."""
    # --- mole motion ---
    mole_radius_mm: float = 40.0
    mole_height_mm: float = 92.0
    peak_above_glass_mm: float = 78.0
    """How far a fully-risen mole stands proud of the glass.

    Large on purpose. At 22 mm the mole barely cleared the rim and read as
    filling the hole rather than emerging from it -- and since a 150 mm rise
    changes apparent size by under 10 percent from 700 mm up, height cannot
    be conveyed by scale. It has to be conveyed by the body standing visibly
    above the ground plane, by its shadow, and by its silhouette overlapping
    the rim.

    The cost is parallax displacement: a protruding mole appears offset
    from its hole by ``height x lateral_eye_offset / eye_height``, about
    45 mm at the field edge here, which is why taps are hit-tested against
    the hole footprint with a generous tolerance rather than against the
    rendered body.
    """

    lean_deg: float = 44.0
    """How far a fully-risen mole leans back out of its hole.

    This is the main fix for moles reading as flat. A surface of revolution
    viewed straight down its own axis projects to a circle and carries
    almost no shape information -- no amount of shading rescues it. Tilting
    the body takes its axis off the view axis, so the torso and face project
    as an elongated, asymmetric silhouette that reads unambiguously as a
    solid leaning out of a hole.
    """

    lean_starts_at: float = 0.45
    """Normalised height at which the lean begins, so the mole comes up
    roughly vertically and only settles into the lean near the top. Leaning
    from the very start looks like it is being poured out sideways."""

    rise_time_s: float = 0.11
    """Fast, like a solenoid. Slower than ~150 ms stops reading as mechanical."""
    retract_time_s: float = 0.26
    struck_retract_time_s: float = 0.12
    overshoot: float = 0.12
    """Fraction of travel the mole overshoots at the top of its rise."""

    # --- pacing ---
    round_length_s: float = 45.0
    up_time_start_s: float = 1.45
    up_time_end_s: float = 0.75
    spawn_interval_start_s: float = 0.95
    spawn_interval_end_s: float = 0.38
    max_simultaneous_start: int = 2
    max_simultaneous_end: int = 5
    """Difficulty ramps linearly from the *start* to the *end* values across
    the round. The reference game had no ramp at all."""

    # --- scoring ---
    points_per_hit: int = 10
    points_per_miss: int = -2
    hit_tolerance_mm: float = 30.0
    """Added to the hole radius when testing a tap.

    Covers the parallax displacement of a protruding mole plus ordinary
    finger imprecision. Forgiving on purpose: a strict radius feels broken
    rather than challenging."""

    hit_requires_height: float = 0.25
    """Minimum normalised height for a mole to be hittable, so taps on a
    mole still inside its hole do not count."""

    def total_holes(self) -> int:
        return self.rows * self.columns


@dataclass(frozen=True)
class Difficulty:
    """A difficulty level, as multipliers over a :class:`GameConfig`.

    Multipliers rather than absolute values, so a level scales whatever
    base config it is given instead of overwriting its tuning. :data:`MEDIUM`
    is all ones and is therefore exactly the identity.

    Each level still ramps from its own start values to its own end values
    across the round; difficulty shifts the whole curve.
    """

    name: str

    pace: float
    """Scales how long a mole stays up and how long between spawns. Below 1
    is faster."""

    motion: float
    """Scales the rise and retract durations -- how fast a mole moves, as
    opposed to how often it appears."""

    crowd: float
    """Scales the cap on simultaneous moles."""

    def apply(self, base: GameConfig) -> GameConfig:
        return replace(
            base,
            up_time_start_s=base.up_time_start_s * self.pace,
            up_time_end_s=base.up_time_end_s * self.pace,
            spawn_interval_start_s=base.spawn_interval_start_s * self.pace,
            spawn_interval_end_s=base.spawn_interval_end_s * self.pace,
            rise_time_s=base.rise_time_s * self.motion,
            retract_time_s=base.retract_time_s * self.motion,
            struck_retract_time_s=base.struck_retract_time_s * self.motion,
            max_simultaneous_start=max(
                1, round(base.max_simultaneous_start * self.crowd)
            ),
            max_simultaneous_end=max(
                1, round(base.max_simultaneous_end * self.crowd)
            ),
        )


BEGINNER = Difficulty("beginner", pace=1.55, motion=1.3, crowd=0.6)
MEDIUM = Difficulty("medium", pace=1.0, motion=1.0, crowd=1.0)
ADVANCED = Difficulty("advanced", pace=0.6, motion=0.72, crowd=1.4)

DIFFICULTIES: tuple[Difficulty, ...] = (BEGINNER, MEDIUM, ADVANCED)


def difficulty_by_name(name: str) -> Difficulty:
    for level in DIFFICULTIES:
        if level.name == name:
            return level
    raise ValueError(
        f"unknown difficulty {name!r}; available: "
        f"{[d.name for d in DIFFICULTIES]}"
    )


@dataclass(frozen=True)
class HoleView:
    """Read-only snapshot of one hole, for the renderer."""

    index: int
    x_mm: float
    y_mm: float
    state: MoleState
    height: float
    """Normalised 0..1, and may slightly exceed 1 during rise overshoot."""

    faces_right: bool = True
    """Which way this mole is looking, drawn once per spawn.

    Chosen by the rules rather than by the view so it is seeded, and
    therefore stable across a replay and across a headless capture. The view
    has no business inventing state that changes what a frame looks like.

    A coin flip, which is what stops the field from looking like a printed
    pattern: under the previous rule (flip everything on the right-hand
    side) every mole in a row faced the same way, and a row of identical
    poses reads as wallpaper rather than as animals.
    """


@dataclass(frozen=True)
class GameEvent:
    """Something worth reacting to: sound, particles, HUD flash."""

    kind: str
    """``hit``, ``miss``, ``emerged``, ``escaped``, ``round_over``."""
    hole_index: int | None = None
    player_id: int | None = None
    points: int = 0
    x_mm: float = 0.0
    y_mm: float = 0.0


@dataclass
class _Hole:
    index: int
    x_mm: float
    y_mm: float
    state: MoleState = MoleState.DOWN
    elapsed: float = 0.0
    up_duration: float = 1.0
    height: float = 0.0
    faces_right: bool = True


class WhackAMole:
    """The game. Drive it with :meth:`update`; render from :meth:`holes`.

    Deterministic for a given seed, so a scripted touch sequence replays
    identically — which is what makes the behaviour testable at all.
    """

    def __init__(
        self,
        config: GameConfig | None = None,
        field_width_mm: float = 941.0,
        field_height_mm: float = 529.0,
        seed: int | None = None,
        player_count: int = 1,
        difficulty: Difficulty | None = None,
    ) -> None:
        # The base config is kept so a difficulty change re-derives from it
        # rather than compounding multipliers on an already-scaled config.
        self.base_config = config or GameConfig()
        self.difficulty = difficulty or MEDIUM
        self.config = self.difficulty.apply(self.base_config)
        self.field_width_mm = field_width_mm
        self.field_height_mm = field_height_mm
        self.player_count = max(1, player_count)
        self._rng = random.Random(seed)

        self._holes = self._build_holes()
        self.scores: dict[int, int] = {p: 0 for p in range(self.player_count)}
        self.hits = 0
        self.taps = 0
        self.spawned = 0
        """Moles that have come up this round. The scoreboard's "moles"
        figure, and the denominator players actually care about -- hits over
        taps measures aim, hits over spawns measures how much got past
        them."""

        self.elapsed_s = 0.0
        self.running = True
        self._next_spawn_s = 0.6

        # Survives reset(), unlike everything above: a scoreboard with a
        # round counter and a high score is the whole reason to keep one
        # game object across rounds instead of constructing a new one.
        self.round_number = 1
        self.top_score = 0

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    @property
    def cell_width_mm(self) -> float:
        return self.field_width_mm / self.config.columns

    @property
    def cell_height_mm(self) -> float:
        return self.field_height_mm / self.config.rows

    def _build_holes(self) -> list[_Hole]:
        """Holes on the centres of a grid covering the whole field.

        Cell-centred rather than inset by an explicit margin, because the
        renderer builds one ground patch per cell and the patches have to
        tile the field exactly -- a separate margin would leave an untiled
        border strip. Cell-centring also yields a natural inset of half a
        cell (~78 x 66 mm here), which keeps holes clear of the bezel where
        a touchscreen is least reliable.
        """
        cfg = self.config
        holes: list[_Hole] = []
        for row in range(cfg.rows):
            for col in range(cfg.columns):
                u = (col + 0.5) / cfg.columns
                v = (row + 0.5) / cfg.rows
                holes.append(
                    _Hole(
                        index=len(holes),
                        x_mm=-self.field_width_mm / 2 + u * self.field_width_mm,
                        y_mm=-self.field_height_mm / 2 + v * self.field_height_mm,
                    )
                )
        return holes

    # ------------------------------------------------------------------
    # Difficulty
    # ------------------------------------------------------------------

    @property
    def progress(self) -> float:
        """0 at the start of the round, 1 at the end."""
        if self.config.round_length_s <= 0:
            return 1.0
        return min(1.0, self.elapsed_s / self.config.round_length_s)

    def _ramp(self, start: float, end: float) -> float:
        return start + (end - start) * self.progress

    @property
    def time_left_s(self) -> float:
        return max(0.0, self.config.round_length_s - self.elapsed_s)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def update(
        self, dt: float, touches: Sequence[TouchPoint] = ()
    ) -> list[GameEvent]:
        """Advance by ``dt`` seconds and apply any new taps.

        Only ``BEGAN`` contacts count as taps. Registering on release would
        add the player's finger-lift time to the perceived latency, which is
        exactly the wrong trade for a reaction game.
        """
        events: list[GameEvent] = []
        if not self.running:
            return events

        if dt < 0:
            raise ValueError(f"dt must not be negative, got {dt}")

        self.elapsed_s += dt
        events.extend(self._advance_moles(dt))
        events.extend(self._apply_taps(touches))
        events.extend(self._maybe_spawn(dt))

        if self.elapsed_s >= self.config.round_length_s:
            self.running = False
            # Fold in the high score here rather than in reset(), so the
            # round-over banner can show a new record immediately.
            self.top_score = max(self.top_score, self.score)
            events.append(GameEvent(kind="round_over"))

        return events

    def _advance_moles(self, dt: float) -> list[GameEvent]:
        cfg = self.config
        events: list[GameEvent] = []

        for hole in self._holes:
            if hole.state is MoleState.DOWN:
                hole.height = 0.0
                continue

            hole.elapsed += dt

            if hole.state is MoleState.RISING:
                t = _clamp01(hole.elapsed / max(cfg.rise_time_s, 1e-6))
                hole.height = _overshoot_ease(t, cfg.overshoot)
                if t >= 1.0:
                    hole.state = MoleState.UP
                    hole.elapsed = 0.0
                    hole.height = 1.0
                    events.append(
                        GameEvent("emerged", hole.index, x_mm=hole.x_mm, y_mm=hole.y_mm)
                    )

            elif hole.state is MoleState.UP:
                hole.height = 1.0
                if hole.elapsed >= hole.up_duration:
                    hole.state = MoleState.DESCENDING
                    hole.elapsed = 0.0

            elif hole.state in (MoleState.DESCENDING, MoleState.STRUCK):
                duration = (
                    cfg.struck_retract_time_s
                    if hole.state is MoleState.STRUCK
                    else cfg.retract_time_s
                )
                t = _clamp01(hole.elapsed / max(duration, 1e-6))
                hole.height = 1.0 - _ease_in(t)
                if t >= 1.0:
                    escaped = hole.state is MoleState.DESCENDING
                    hole.state = MoleState.DOWN
                    hole.elapsed = 0.0
                    hole.height = 0.0
                    if escaped:
                        # Got away un-whacked. Not penalised (the reference
                        # only penalises bad taps) but worth surfacing so the
                        # view can react.
                        events.append(
                            GameEvent(
                                "escaped", hole.index, x_mm=hole.x_mm, y_mm=hole.y_mm
                            )
                        )

        return events

    def _apply_taps(self, touches: Sequence[TouchPoint]) -> list[GameEvent]:
        cfg = self.config
        events: list[GameEvent] = []

        for touch in touches:
            if touch.phase is not TouchPhase.BEGAN:
                continue
            if not self.on_field(touch.x_mm, touch.y_mm):
                # Off the playfield: the rail, where the scores are printed.
                # Not a tap and not a miss. Once the display is wider than
                # the game area, penalising a touch there would dock a
                # player two points for resting a hand on the furniture, and
                # it would wreck the accuracy figure that the rail itself
                # displays.
                continue

            self.taps += 1
            player = touch.player_id if touch.player_id is not None else 0
            player = player if player in self.scores else 0

            hole = self._hole_hit_by(touch.x_mm, touch.y_mm)
            if hole is None:
                self.scores[player] += cfg.points_per_miss
                events.append(
                    GameEvent(
                        "miss",
                        player_id=player,
                        points=cfg.points_per_miss,
                        x_mm=touch.x_mm,
                        y_mm=touch.y_mm,
                    )
                )
                continue

            hole.state = MoleState.STRUCK
            hole.elapsed = 0.0
            self.hits += 1
            self.scores[player] += cfg.points_per_hit
            events.append(
                GameEvent(
                    "hit",
                    hole.index,
                    player_id=player,
                    points=cfg.points_per_hit,
                    x_mm=hole.x_mm,
                    y_mm=hole.y_mm,
                )
            )

        return events

    def on_field(self, x_mm: float, y_mm: float) -> bool:
        """Whether a point is inside the playfield.

        The field is centred on the table origin, so this is the boundary
        between the game and whatever surrounds it. The view draws the rail
        from the same split (:class:`~tabletop.core.layout.TableLayout`), but
        the rules do not depend on that module -- they only need to know how
        big the field they were handed is.
        """
        return (
            abs(x_mm) <= self.field_width_mm / 2.0
            and abs(y_mm) <= self.field_height_mm / 2.0
        )

    def _hole_hit_by(self, x_mm: float, y_mm: float) -> _Hole | None:
        """The hittable mole under a tap, or None.

        Testing is done in table millimetres against the hole's footprint on
        the glass plane, **not** by raycasting the mole's 3D surface. The
        glass plane projects identically regardless of projection mode or
        head position, so a tap maps to table coordinates exactly; the mole's
        rendered body does not, once it stands proud of the glass. Hit-testing
        the footprint is therefore both simpler and more honest about where
        the player's finger actually landed.

        Closest hole wins, so overlapping tolerances behave predictably.
        """
        cfg = self.config
        reach = cfg.hole_radius_mm + cfg.hit_tolerance_mm
        best: _Hole | None = None
        best_distance = float("inf")

        for hole in self._holes:
            if hole.state in (MoleState.DOWN, MoleState.STRUCK):
                continue
            if hole.height < cfg.hit_requires_height:
                continue
            dx = x_mm - hole.x_mm
            dy = y_mm - hole.y_mm
            distance = math.hypot(dx, dy)
            if distance <= reach and distance < best_distance:
                best, best_distance = hole, distance

        return best

    def _maybe_spawn(self, dt: float) -> list[GameEvent]:
        self._next_spawn_s -= dt
        if self._next_spawn_s > 0:
            return []

        cfg = self.config
        self._next_spawn_s = self._ramp(
            cfg.spawn_interval_start_s, cfg.spawn_interval_end_s
        )

        active = sum(1 for h in self._holes if h.state is not MoleState.DOWN)
        allowed = int(
            round(
                self._ramp(
                    float(cfg.max_simultaneous_start), float(cfg.max_simultaneous_end)
                )
            )
        )
        if active >= allowed:
            return []

        candidates = [h for h in self._holes if h.state is MoleState.DOWN]
        if not candidates:
            return []

        hole = self._rng.choice(candidates)
        hole.state = MoleState.RISING
        hole.elapsed = 0.0
        hole.up_duration = self._ramp(cfg.up_time_start_s, cfg.up_time_end_s)
        hole.faces_right = self._rng.random() < 0.5
        self.spawned += 1
        return []

    # ------------------------------------------------------------------
    # Rendering interface
    # ------------------------------------------------------------------

    def holes(self) -> list[HoleView]:
        return [
            HoleView(h.index, h.x_mm, h.y_mm, h.state, h.height, h.faces_right)
            for h in self._holes
        ]

    @property
    def moles_up(self) -> int:
        """Moles currently out of their holes, for the scoreboard."""
        return sum(
            1
            for h in self._holes
            if h.state in (MoleState.RISING, MoleState.UP, MoleState.DESCENDING)
        )

    def mole_z_mm(self, height: float) -> float:
        """Map normalised height to the mole base's table Z, in millimetres.

        At height 0 the mole's **top** sits at the well floor, so the floor
        and funnel wall hide it completely; at height 1 it stands
        ``peak_above_glass_mm`` proud of the glass.

        Full concealment at rest is the most important cue, and not an
        obvious one: from ~700 mm overhead a 150 mm rise changes apparent
        size by under 10 percent, far too little to notice, so the pop is
        carried by visibility rather than by perspective. An earlier version
        left the mole parked visible at the bottom of an open funnel, and a
        risen mole was nearly indistinguishable from a resting one.
        """
        cfg = self.config
        top_down = -cfg.hole_depth_mm
        top_up = cfg.peak_above_glass_mm
        top = top_down + (top_up - top_down) * height
        return top - cfg.mole_height_mm

    def lean_deg(self, height: float) -> float:
        """Lean angle for a given normalised height, in degrees."""
        cfg = self.config
        if height <= cfg.lean_starts_at:
            return 0.0
        span = max(1e-6, 1.0 - cfg.lean_starts_at)
        return cfg.lean_deg * _clamp01((height - cfg.lean_starts_at) / span)

    @property
    def score(self) -> int:
        """Combined score, for single-player and shared-score display."""
        return sum(self.scores.values())

    @property
    def accuracy(self) -> float:
        return self.hits / self.taps if self.taps else 0.0

    def set_difficulty(self, difficulty: Difficulty) -> None:
        """Switch level. Takes effect on the next round, via :meth:`reset`."""
        self.difficulty = difficulty
        self.config = difficulty.apply(self.base_config)

    def reset(self, seed: int | None = None) -> None:
        """Start a fresh round, keeping the scoreboard's running totals."""
        self.top_score = max(self.top_score, self.score)
        self.round_number += 1

        self._rng = random.Random(seed)
        self._holes = self._build_holes()
        self.scores = {p: 0 for p in range(self.player_count)}
        self.hits = 0
        self.taps = 0
        self.spawned = 0
        self.elapsed_s = 0.0
        self.running = True
        self._next_spawn_s = 0.6


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _ease_in(t: float) -> float:
    """Accelerating, for a mole dropping back under its own weight."""
    return t * t


def _overshoot_ease(t: float, overshoot: float) -> float:
    """Fast rise that passes its resting point, then settles back to it.

    The overshoot is the mechanical tell: a prop thrown upward by a solenoid
    goes past where it ends up and drops back. Without it, the motion reads
    as a software tween no matter how fast it is.

    This is the standard "ease out back" curve. An earlier attempt added a
    decaying sine bump to a sine ease-out, which *looked* like it should
    overshoot but provably cannot: the bump decays faster than the base
    curve approaches 1, so the sum peaked at exactly 1.0 and the mole never
    passed its stop. The test asserting a peak above 1.0 caught it.

    ``overshoot`` is scaled so its value is roughly the fractional excess at
    the peak -- 0.12 gives about 12 percent past the stop.
    """
    if t >= 1.0:
        return 1.0
    s = max(0.0, overshoot) * 16.0
    u = t - 1.0
    return 1.0 + (s + 1.0) * u * u * u + s * u * u
