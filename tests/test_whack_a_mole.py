"""Whack-a-mole rules, tested without a graphics context.

This is the payoff for keeping the rules renderer-free: the entire game is
verifiable in milliseconds. Rendering bugs in this project have been slow
and expensive to find, so anything checkable without a GL context is.
"""

from __future__ import annotations

import pytest

from tabletop.core.events import TouchPhase, TouchPoint
from tabletop.game.whack_a_mole import (
    ADVANCED,
    BEGINNER,
    DIFFICULTIES,
    MEDIUM,
    GameConfig,
    MoleState,
    WhackAMole,
    difficulty_by_name,
)

FIELD_W = 941.0
FIELD_H = 529.0


def make_game(**kwargs) -> WhackAMole:
    return WhackAMole(
        field_width_mm=FIELD_W, field_height_mm=FIELD_H, seed=1234, **kwargs
    )


def tap(x_mm: float, y_mm: float, player_id: int | None = None) -> TouchPoint:
    return TouchPoint(
        touch_id=1, x_mm=x_mm, y_mm=y_mm, phase=TouchPhase.BEGAN, player_id=player_id
    )


def raise_mole(game: WhackAMole, index: int) -> None:
    """Force one mole fully up, bypassing the spawn scheduler."""
    hole = game._holes[index]
    hole.state = MoleState.UP
    hole.height = 1.0
    hole.elapsed = 0.0
    hole.up_duration = 999.0


class TestLayout:
    def test_hole_count_matches_grid(self) -> None:
        game = make_game(config=GameConfig(rows=3, columns=5))
        assert len(game.holes()) == 15

    def test_holes_sit_inside_the_field(self) -> None:
        game = make_game()
        for hole in game.holes():
            assert abs(hole.x_mm) < FIELD_W / 2
            assert abs(hole.y_mm) < FIELD_H / 2

    def test_holes_are_cell_centred_and_clear_of_the_bezel(self) -> None:
        """Half a cell of inset, which keeps contacts away from the frame
        edge where a touchscreen is least reliable."""
        game = make_game()
        inset_x = FIELD_W / 2 - max(abs(h.x_mm) for h in game.holes())
        inset_y = FIELD_H / 2 - max(abs(h.y_mm) for h in game.holes())
        assert inset_x == pytest.approx(game.cell_width_mm / 2)
        assert inset_y == pytest.approx(game.cell_height_mm / 2)

    def test_cells_tile_the_field(self) -> None:
        """The renderer builds one ground patch per cell; if the cells did
        not tile exactly there would be visible seams or gaps."""
        game = make_game()
        cfg = game.config
        assert game.cell_width_mm * cfg.columns == pytest.approx(FIELD_W)
        assert game.cell_height_mm * cfg.rows == pytest.approx(FIELD_H)

    def test_holes_fit_within_their_cells(self) -> None:
        game = make_game()
        assert game.config.hole_radius_mm < game.cell_width_mm / 2
        assert game.config.hole_radius_mm < game.cell_height_mm / 2


class TestMoleMotion:
    def test_resting_mole_is_fully_concealed(self) -> None:
        """The whole pop depends on this. From ~700 mm overhead a 150 mm
        rise changes apparent size by under 10 percent, so the mole cannot
        be sold by perspective -- it has to be genuinely invisible at rest
        and then visible."""
        game = make_game()
        cfg = game.config
        top_at_rest = game.mole_z_mm(0.0) + cfg.mole_height_mm
        assert top_at_rest <= -cfg.hole_depth_mm + 1e-6

    def test_risen_mole_stands_proud_of_the_glass(self) -> None:
        game = make_game()
        cfg = game.config
        top_when_up = game.mole_z_mm(1.0) + cfg.mole_height_mm
        assert top_when_up == pytest.approx(cfg.peak_above_glass_mm)

    def test_height_maps_monotonically_to_z(self) -> None:
        game = make_game()
        zs = [game.mole_z_mm(h / 10) for h in range(11)]
        assert zs == sorted(zs)

    def test_rise_overshoots_then_settles(self) -> None:
        """Mechanical tell: a solenoid-thrown prop passes its resting point
        and comes back. Without overshoot the motion reads as a tween."""
        game = make_game()
        hole = game._holes[0]
        hole.state = MoleState.RISING
        hole.up_duration = 5.0

        peak = 0.0
        for _ in range(40):
            game.update(game.config.rise_time_s / 20)
            peak = max(peak, hole.height)
            if hole.state is MoleState.UP:
                break
        assert peak > 1.0, f"expected overshoot above 1.0, peaked at {peak}"
        assert hole.state is MoleState.UP
        assert hole.height == pytest.approx(1.0)

    def test_mole_retreats_and_returns_to_down(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 0)
        hole = game._holes[0]
        hole.up_duration = 0.05

        for _ in range(200):
            game.update(1 / 60)
            if hole.state is MoleState.DOWN:
                break
        assert hole.state is MoleState.DOWN
        assert hole.height == pytest.approx(0.0)

    def test_escape_is_reported(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 3)
        game._holes[3].up_duration = 0.01

        kinds: list[str] = []
        for _ in range(200):
            kinds += [e.kind for e in game.update(1 / 60)]
            if game._holes[3].state is MoleState.DOWN:
                break
        assert "escaped" in kinds


class TestHitDetection:
    def test_tap_on_a_risen_mole_scores(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 5)
        hole = game.holes()[5]

        events = game.update(1 / 60, [tap(hole.x_mm, hole.y_mm)])
        assert [e.kind for e in events if e.kind in ("hit", "miss")] == ["hit"]
        assert game.score == game.config.points_per_hit
        assert game._holes[5].state is MoleState.STRUCK

    def test_tap_on_empty_ground_is_a_miss(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        for hole in game._holes:
            hole.state = MoleState.DOWN
            hole.height = 0.0

        events = game.update(1 / 60, [tap(0.0, 0.0)])
        assert [e.kind for e in events] == ["miss"]
        assert game.score == game.config.points_per_miss

    def test_mole_still_inside_its_hole_cannot_be_hit(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        hole = game._holes[2]
        hole.state = MoleState.RISING
        hole.height = 0.05  # barely moving

        events = game.update(0.0, [tap(hole.x_mm, hole.y_mm)])
        assert [e.kind for e in events] == ["miss"]

    def test_a_mole_cannot_be_hit_twice(self) -> None:
        """Guards against double-scoring on rapid taps, which a multi-touch
        screen produces routinely."""
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 7)
        hole = game.holes()[7]

        game.update(0.0, [tap(hole.x_mm, hole.y_mm)])
        events = game.update(0.0, [tap(hole.x_mm, hole.y_mm)])
        assert [e.kind for e in events] == ["miss"]
        assert game.hits == 1

    def test_hit_tolerance_is_forgiving_but_bounded(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 9)
        hole = game.holes()[9]
        cfg = game.config

        inside = cfg.hole_radius_mm + cfg.hit_tolerance_mm - 1.0
        assert [
            e.kind for e in game.update(0.0, [tap(hole.x_mm + inside, hole.y_mm)])
        ] == ["hit"]

        game.reset(seed=1)
        raise_mole(game, 9)
        outside = cfg.hole_radius_mm + cfg.hit_tolerance_mm + 5.0
        assert [
            e.kind for e in game.update(0.0, [tap(hole.x_mm + outside, hole.y_mm)])
        ] == ["miss"]

    def test_closest_mole_wins_when_tolerances_overlap(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 0)
        raise_mole(game, 1)
        a = game.holes()[0]

        # Just off hole 0, and far from hole 1.
        events = game.update(0.0, [tap(a.x_mm + 5.0, a.y_mm)])
        hits = [e for e in events if e.kind == "hit"]
        assert len(hits) == 1
        assert hits[0].hole_index == 0

    def test_only_began_phase_counts_as_a_tap(self) -> None:
        """Registering on release would add finger-lift time to perceived
        latency, which is the wrong trade for a reaction game."""
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 4)
        hole = game.holes()[4]

        for phase in (TouchPhase.MOVED, TouchPhase.ENDED, TouchPhase.CANCELLED):
            moved = TouchPoint(
                touch_id=1, x_mm=hole.x_mm, y_mm=hole.y_mm, phase=phase
            )
            assert game.update(0.0, [moved]) == []
        assert game.taps == 0

    def test_simultaneous_taps_hit_different_moles(self) -> None:
        """A 20-point frame with several players will do this constantly."""
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 2)
        raise_mole(game, 11)
        a, b = game.holes()[2], game.holes()[11]

        events = game.update(
            0.0,
            [
                TouchPoint(1, a.x_mm, a.y_mm, phase=TouchPhase.BEGAN),
                TouchPoint(2, b.x_mm, b.y_mm, phase=TouchPhase.BEGAN),
            ],
        )
        assert [e.kind for e in events].count("hit") == 2
        assert game.hits == 2


class TestScoringAndPlayers:
    def test_per_player_scores(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0), player_count=2)
        raise_mole(game, 0)
        raise_mole(game, 1)
        a, b = game.holes()[0], game.holes()[1]

        game.update(0.0, [tap(a.x_mm, a.y_mm, player_id=0)])
        game.update(0.0, [tap(b.x_mm, b.y_mm, player_id=1)])
        assert game.scores == {0: 10, 1: 10}

    def test_unknown_player_falls_back_to_player_zero(self) -> None:
        """A touchscreen cannot tell whose finger it is, so player_id is
        often None. That must score rather than crash."""
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 0)
        hole = game.holes()[0]
        game.update(0.0, [tap(hole.x_mm, hole.y_mm, player_id=None)])
        assert game.scores[0] == 10

        # On the field but not on a mole, so it is a miss and the unknown
        # player's penalty lands on player 0 too.
        game.update(0.0, [tap(0.0, 0.0, player_id=57)])
        assert game.scores[0] == 8

    def test_accuracy(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 0)
        hole = game.holes()[0]
        game.update(0.0, [tap(hole.x_mm, hole.y_mm)])
        game.update(0.0, [tap(0.0, 0.0)])
        assert game.accuracy == pytest.approx(0.5)

    def test_accuracy_with_no_taps_is_zero_not_an_error(self) -> None:
        assert make_game().accuracy == 0.0


class TestPacing:
    def test_difficulty_ramps_from_zero_to_one(self) -> None:
        game = make_game(config=GameConfig(round_length_s=10.0))
        assert game.progress == pytest.approx(0.0)
        game.update(5.0)
        assert game.progress == pytest.approx(0.5)

    def test_up_time_shortens_as_the_round_progresses(self) -> None:
        """The reference game had no ramp; pacing is most of the feel."""
        cfg = GameConfig(round_length_s=10.0)
        game = make_game(config=cfg)
        early = game._ramp(cfg.up_time_start_s, cfg.up_time_end_s)
        game.update(9.0)
        late = game._ramp(cfg.up_time_start_s, cfg.up_time_end_s)
        assert late < early

    def test_simultaneous_mole_cap_is_respected(self) -> None:
        cfg = GameConfig(
            round_length_s=1000.0, max_simultaneous_start=2, max_simultaneous_end=2
        )
        game = make_game(config=cfg)
        for _ in range(600):
            game.update(1 / 60)
            active = sum(1 for h in game.holes() if h.state is not MoleState.DOWN)
            assert active <= 2

    def test_moles_do_appear_unprompted(self) -> None:
        game = make_game()
        emerged = 0
        for _ in range(600):
            emerged += sum(1 for e in game.update(1 / 60) if e.kind == "emerged")
        assert emerged > 0

    def test_round_ends_once(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1.0))
        kinds: list[str] = []
        for _ in range(180):
            kinds += [e.kind for e in game.update(1 / 60)]
        assert kinds.count("round_over") == 1
        assert not game.running

    def test_no_updates_after_the_round_ends(self) -> None:
        game = make_game(config=GameConfig(round_length_s=0.1))
        game.update(0.2)
        before = game.score
        raise_mole(game, 0)
        hole = game.holes()[0]
        assert game.update(1 / 60, [tap(hole.x_mm, hole.y_mm)]) == []
        assert game.score == before

    def test_negative_dt_is_rejected(self) -> None:
        game = make_game()
        with pytest.raises(ValueError, match="must not be negative"):
            game.update(-0.1)


class TestPlayfieldBounds:
    def test_a_tap_off_the_playfield_is_neither_tap_nor_miss(self) -> None:
        """The display is wider than the field: the surround carries the
        bezel and the scoreboard, and touching those must not score."""
        game = make_game(config=GameConfig(round_length_s=1000.0))
        events = game.update(0.0, [tap(FIELD_W, FIELD_H)])
        assert events == []
        assert game.taps == 0
        assert game.score == 0

    def test_a_tap_just_inside_the_edge_still_counts(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        game.update(0.0, [tap(FIELD_W / 2 - 1.0, 0.0)])
        assert game.taps == 1

    def test_on_field_matches_the_field_rectangle(self) -> None:
        game = make_game()
        assert game.on_field(0.0, 0.0)
        assert game.on_field(FIELD_W / 2, FIELD_H / 2)
        assert not game.on_field(FIELD_W / 2 + 0.1, 0.0)
        assert not game.on_field(0.0, -FIELD_H / 2 - 0.1)


class TestFacing:
    def test_spawned_moles_face_both_ways_over_a_round(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        seen: set[bool] = set()
        for _ in range(3000):
            game.update(1 / 60)
            seen.update(
                h.faces_right for h in game.holes() if h.state is not MoleState.DOWN
            )
            if len(seen) == 2:
                break
        assert seen == {True, False}

    def test_facing_is_seeded(self) -> None:
        """The view mirrors the sprite from this, so a replay or a headless
        capture has to reproduce it."""

        def run() -> list[tuple[int, bool]]:
            game = WhackAMole(
                field_width_mm=FIELD_W, field_height_mm=FIELD_H, seed=5
            )
            out: list[tuple[int, bool]] = []
            for _ in range(400):
                game.update(1 / 60)
                out += [
                    (h.index, h.faces_right)
                    for h in game.holes()
                    if h.state is MoleState.UP
                ]
            return out

        assert run() == run()


class TestScoreboardFigures:
    def test_spawn_count_rises_with_emergences(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        assert game.spawned == 0
        for _ in range(600):
            game.update(1 / 60)
        assert game.spawned > 0

    def test_moles_up_counts_only_moles_out_of_their_holes(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        assert game.moles_up == 0
        raise_mole(game, 1)
        raise_mole(game, 2)
        assert game.moles_up == 2

    def test_a_struck_mole_is_not_counted_as_up(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 1)
        hole = game.holes()[1]
        game.update(0.0, [tap(hole.x_mm, hole.y_mm)])
        assert game.moles_up == 0

    def test_round_number_and_top_score_survive_a_reset(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 0)
        hole = game.holes()[0]
        game.update(0.0, [tap(hole.x_mm, hole.y_mm)])
        assert game.round_number == 1

        game.reset(seed=1)
        assert game.round_number == 2
        assert game.top_score == 10
        assert game.score == 0
        assert game.spawned == 0

    def test_top_score_keeps_the_best_round_not_the_last(self) -> None:
        game = make_game(config=GameConfig(round_length_s=1000.0))
        raise_mole(game, 0)
        hole = game.holes()[0]
        game.update(0.0, [tap(hole.x_mm, hole.y_mm)])
        game.reset(seed=1)
        game.reset(seed=2)
        assert game.top_score == 10

    def test_top_score_is_set_when_the_round_ends(self) -> None:
        """So the round-over banner can show a new record without a reset."""
        game = make_game(config=GameConfig(round_length_s=0.5))
        raise_mole(game, 0)
        hole = game.holes()[0]
        game.update(0.0, [tap(hole.x_mm, hole.y_mm)])
        game.update(0.6)
        assert not game.running
        assert game.top_score == 10


class TestDifficulty:
    def test_medium_is_the_identity(self) -> None:
        """Levels are multipliers over a base config, so the middle one must
        leave an explicitly tuned config untouched."""
        base = GameConfig(max_simultaneous_start=2, max_simultaneous_end=2)
        assert MEDIUM.apply(base) == base

    def test_each_level_is_faster_than_the_last(self) -> None:
        base = GameConfig()
        up_times = []
        spawn_intervals = []
        rise_times = []
        for level in (BEGINNER, MEDIUM, ADVANCED):
            cfg = level.apply(base)
            up_times.append(cfg.up_time_start_s)
            spawn_intervals.append(cfg.spawn_interval_start_s)
            rise_times.append(cfg.rise_time_s)
        assert up_times == sorted(up_times, reverse=True)
        assert spawn_intervals == sorted(spawn_intervals, reverse=True)
        assert rise_times == sorted(rise_times, reverse=True)

    def test_harder_levels_allow_more_moles_at_once(self) -> None:
        base = GameConfig()
        caps = [level.apply(base).max_simultaneous_end for level in DIFFICULTIES]
        assert caps == sorted(caps)
        assert caps[0] < caps[-1]

    def test_the_cap_never_falls_below_one(self) -> None:
        """Beginner scales the cap down; at a cap of 1 that must not round to
        zero, which would stop moles appearing at all."""
        base = GameConfig(max_simultaneous_start=1, max_simultaneous_end=1)
        cfg = BEGINNER.apply(base)
        assert cfg.max_simultaneous_start >= 1
        assert cfg.max_simultaneous_end >= 1

    def test_every_level_still_ramps_within_the_round(self) -> None:
        base = GameConfig()
        for level in DIFFICULTIES:
            cfg = level.apply(base)
            assert cfg.up_time_end_s < cfg.up_time_start_s
            assert cfg.spawn_interval_end_s < cfg.spawn_interval_start_s

    def test_game_applies_the_level_it_was_given(self) -> None:
        game = make_game(difficulty=ADVANCED)
        assert game.difficulty is ADVANCED
        assert game.config == ADVANCED.apply(game.base_config)

    def test_switching_level_re_derives_from_the_base_config(self) -> None:
        """Not from the current one, or the multipliers would compound."""
        game = make_game(difficulty=ADVANCED)
        game.set_difficulty(ADVANCED)
        game.set_difficulty(ADVANCED)
        assert game.config == ADVANCED.apply(game.base_config)

        game.set_difficulty(MEDIUM)
        assert game.config == game.base_config

    def test_advanced_moles_really_do_stay_up_for_less_time(self) -> None:
        def up_frames(level) -> int:
            game = make_game(
                config=GameConfig(round_length_s=1000.0), difficulty=level
            )
            hole = game._holes[0]
            hole.state = MoleState.RISING
            hole.up_duration = game.config.up_time_start_s
            frames = 0
            for _ in range(2000):
                game.update(1 / 240)
                if hole.state is MoleState.DOWN:
                    break
                frames += 1
            return frames

        assert up_frames(ADVANCED) < up_frames(BEGINNER)

    def test_lookup_by_name(self) -> None:
        assert difficulty_by_name("beginner") is BEGINNER
        with pytest.raises(ValueError, match="unknown difficulty"):
            difficulty_by_name("impossible")


class TestDeterminism:
    def test_same_seed_gives_the_same_round(self) -> None:
        """Needed for the scripted multi-touch replays to be meaningful."""

        def run() -> list[tuple[int, str]]:
            game = WhackAMole(
                field_width_mm=FIELD_W, field_height_mm=FIELD_H, seed=99
            )
            out: list[tuple[int, str]] = []
            for _ in range(400):
                out += [(e.hole_index or -1, e.kind) for e in game.update(1 / 60)]
            return out

        assert run() == run()

    def test_reset_restores_a_clean_round(self) -> None:
        game = make_game()
        for _ in range(300):
            game.update(1 / 60)
        game.update(0.0, [tap(0.0, 0.0)])

        game.reset(seed=5)
        assert game.score == 0
        assert game.taps == 0
        assert game.hits == 0
        assert game.elapsed_s == 0.0
        assert game.running
        assert all(h.state is MoleState.DOWN for h in game.holes())


class TestPointerOwnership:
    """Who owns the pointer: the mallet, or the system cursor.

    Two bugs this pins. After a round, the cursor stayed captured by the
    mallet, so the menu could not be clicked. And during a round the mallet
    owned the pointer everywhere, including over the exit button on the
    panel, which there is no way to aim a mallet at.
    """

    def test_the_mallet_owns_it_over_the_playfield_mid_round(self) -> None:
        from tabletop.apps.whack_a_mole import mallet_owns_pointer

        assert mallet_owns_pointer(
            playing=True, round_running=True, pointer_on_field=True
        )

    def test_the_cursor_owns_it_off_the_playfield(self) -> None:
        """The furniture around the field -- the exit button -- is clicked
        with an ordinary cursor."""
        from tabletop.apps.whack_a_mole import mallet_owns_pointer

        assert not mallet_owns_pointer(
            playing=True, round_running=True, pointer_on_field=False
        )

    def test_the_cursor_comes_back_when_a_round_ends(self) -> None:
        from tabletop.apps.whack_a_mole import mallet_owns_pointer

        assert not mallet_owns_pointer(
            playing=True, round_running=False, pointer_on_field=True
        )

    def test_the_cursor_owns_it_in_the_menu(self) -> None:
        from tabletop.apps.whack_a_mole import mallet_owns_pointer

        for running in (True, False):
            for on_field in (True, False):
                assert not mallet_owns_pointer(
                    playing=False,
                    round_running=running,
                    pointer_on_field=on_field,
                )


class TestTurningInPlace:
    """Every mole turns once, partway through its time in view.

    The schedule is a fraction of that mole's own visible span -- the pop
    out, the stay and the pop back down -- so the two poses get equal time
    at every difficulty and at every point in the round's ramp.

    An earlier version rolled a probability per second of being up
    instead. Three things were wrong with it, and all three are what these
    tests pin: at beginner pace moles usually never turned at all, the
    turn landed at an arbitrary moment so the two poses were not
    symmetric, and the animation was a fixed 180 ms stapled onto stays
    that are three times that at one level and half it at another.
    """

    DT = 1 / 240
    """Fine steps: these assertions are about *when* a turn happens, and a
    coarse step blurs that by up to a frame."""

    def first_mole_life(self, game: WhackAMole):
        """Watch one mole from spawn to gone, with no taps.

        Returns ``(visible_s, turn_start_s, turn_span_s)``, all measured
        rather than read out of the model, so the schedule is checked
        against what the mole actually did.
        """
        index: int | None = None
        visible_s = 0.0
        turn_start_s: float | None = None
        turn_span_s: float | None = None

        for _ in range(20000):
            events = game.update(self.DT, [])
            states = {h.index: h.state for h in game.holes()}

            if index is None:
                rising = [i for i, st in states.items() if st is MoleState.RISING]
                if not rising:
                    continue
                index = rising[0]
                visible_s = self.DT
                continue

            for event in events:
                if event.kind == "turned" and event.hole_index == index:
                    turn_start_s = visible_s
                    turn_span_s = event.duration_s

            if states[index] is MoleState.DOWN:
                assert turn_start_s is not None, "the mole never turned"
                return visible_s, turn_start_s, turn_span_s

            visible_s += self.DT

        raise AssertionError("the mole never went back down")

    @pytest.mark.parametrize("difficulty", DIFFICULTIES, ids=lambda d: d.name)
    def test_every_level_turns_every_mole_exactly_once(self, difficulty) -> None:
        """The reported bug: at beginner pace, moles did not turn."""
        game = WhackAMole(
            field_width_mm=FIELD_W,
            field_height_mm=FIELD_H,
            seed=5,
            difficulty=difficulty,
        )
        turns = 0
        while game.running:
            turns += sum(1 for e in game.update(1 / 60, []) if e.kind == "turned")
        # Never more than one per mole, and the only mole that can miss its
        # turn is one still in the air when the round ends.
        assert game.spawned - 1 <= turns <= game.spawned
        assert turns > 0

    @pytest.mark.parametrize("difficulty", DIFFICULTIES, ids=lambda d: d.name)
    def test_the_turn_starts_at_40_percent_of_the_visible_span(
        self, difficulty
    ) -> None:
        game = WhackAMole(
            field_width_mm=FIELD_W,
            field_height_mm=FIELD_H,
            seed=2,
            difficulty=difficulty,
        )
        visible_s, turn_start_s, turn_span_s = self.first_mole_life(game)
        cfg = game.config
        assert turn_start_s == pytest.approx(
            cfg.turn_at_fraction * visible_s, abs=4 * self.DT
        )
        assert turn_span_s == pytest.approx(
            cfg.turn_span_fraction * visible_s, abs=4 * self.DT
        )

    @pytest.mark.parametrize("difficulty", DIFFICULTIES, ids=lambda d: d.name)
    def test_the_two_poses_get_equal_time(self, difficulty) -> None:
        """40 / 20 / 40, centred on the mole's life."""
        game = WhackAMole(
            field_width_mm=FIELD_W,
            field_height_mm=FIELD_H,
            seed=2,
            difficulty=difficulty,
        )
        visible_s, turn_start_s, turn_span_s = self.first_mole_life(game)
        first_side = turn_start_s
        second_side = visible_s - (turn_start_s + turn_span_s)
        assert first_side == pytest.approx(second_side, abs=8 * self.DT)
        midpoint = turn_start_s + turn_span_s / 2.0
        assert midpoint == pytest.approx(visible_s / 2.0, abs=8 * self.DT)

    @pytest.mark.parametrize("difficulty", DIFFICULTIES, ids=lambda d: d.name)
    def test_the_span_counts_the_pop_out_and_the_pop_back_down(
        self, difficulty
    ) -> None:
        """Not just the stay: the mole is visible while it is moving too.

        Scheduling against the stay alone put the turn early and left the
        second pose short by the rise plus the retract -- a fifth of the
        whole life at medium.
        """
        game = WhackAMole(
            field_width_mm=FIELD_W,
            field_height_mm=FIELD_H,
            seed=2,
            difficulty=difficulty,
        )
        visible_s, _, turn_span_s = self.first_mole_life(game)
        cfg = game.config
        implied_stay = visible_s - cfg.rise_time_s - cfg.retract_time_s
        # The stay the ramp would hand out this early in the round.
        # Tolerance for the step size the life was measured in.
        slack = 4 * self.DT
        assert cfg.up_time_end_s - slack <= implied_stay
        assert implied_stay <= cfg.up_time_start_s + slack
        # And the span is a fifth of the whole life, not a fifth of the stay.
        assert turn_span_s > cfg.turn_span_fraction * implied_stay

    def test_the_default_split_is_symmetric(self) -> None:
        """Guard the numbers: 40 + 20 + 40 has to make the whole."""
        cfg = GameConfig()
        assert 2 * cfg.turn_at_fraction + cfg.turn_span_fraction == 1.0

    def test_a_faster_level_turns_faster(self) -> None:
        """The span is a fraction, so it shrinks with the mole's life."""

        def span(difficulty) -> float:
            game = WhackAMole(
                field_width_mm=FIELD_W,
                field_height_mm=FIELD_H,
                seed=2,
                difficulty=difficulty,
            )
            return self.first_mole_life(game)[2]

        assert span(BEGINNER) > span(MEDIUM) > span(ADVANCED) > 0.0

    def test_the_turn_shortens_as_the_round_speeds_up(self) -> None:
        """The ramp applies too: a mole late in a round is out for less."""
        game = make_game()
        spans: list[float] = []
        while game.running:
            spans.extend(
                e.duration_s for e in game.update(1 / 60, []) if e.kind == "turned"
            )
        assert len(spans) > 4
        assert spans[-1] < spans[0]

    def test_the_turn_flips_the_facing(self) -> None:
        game = make_game()
        before: dict[int, bool] = {}
        for _ in range(4000):
            before = {h.index: h.faces_right for h in game.holes()}
            events = game.update(self.DT, [])
            turns = [e for e in events if e.kind == "turned"]
            if turns:
                index = turns[0].hole_index
                assert game.holes()[index].faces_right != before[index]
                return
        raise AssertionError("no mole turned")

    def test_a_struck_mole_does_not_turn_on_its_way_down(self) -> None:
        """It is being driven back down; looking around would ignore that."""
        game = make_game()
        struck: int | None = None
        for _ in range(8000):
            if struck is None:
                up = [h for h in game.holes() if h.state is MoleState.UP]
                if up:
                    hole = up[0]
                    events = game.update(self.DT, [tap(hole.x_mm, hole.y_mm)])
                    if any(e.kind == "hit" for e in events):
                        struck = hole.index
                    continue
                game.update(self.DT, [])
                continue

            if game.holes()[struck].state is not MoleState.STRUCK:
                return  # it got all the way down without turning
            events = game.update(self.DT, [])
            assert not any(
                e.kind == "turned" and e.hole_index == struck for e in events
            )
        raise AssertionError("never hit a mole")

    def test_turning_can_be_switched_off(self) -> None:
        game = make_game(config=GameConfig(turn_span_fraction=0.0))
        while game.running:
            assert not any(e.kind == "turned" for e in game.update(1 / 60, []))

    def test_turning_does_not_disturb_the_spawn_sequence(self) -> None:
        """Decoration must not shift the gameplay a seed produces.

        The schedule draws no random numbers now, so this holds by
        construction -- and this is what will catch it if some later change
        to the turn starts drawing one from the game's generator.
        """

        def spawn_order(span_fraction: float) -> list[tuple[float, int]]:
            game = WhackAMole(
                field_width_mm=FIELD_W,
                field_height_mm=FIELD_H,
                seed=99,
                config=GameConfig(turn_span_fraction=span_fraction),
            )
            order: list[tuple[float, int]] = []
            previous = {h.index: h.state for h in game.holes()}
            while game.running:
                game.update(1 / 60, [])
                for hole in game.holes():
                    if (
                        hole.state is MoleState.RISING
                        and previous[hole.index] is MoleState.DOWN
                    ):
                        order.append((round(game.elapsed_s, 4), hole.index))
                    previous[hole.index] = hole.state
            return order

        assert spawn_order(0.2) == spawn_order(0.0)

    @pytest.mark.parametrize("difficulty", DIFFICULTIES, ids=lambda d: d.name)
    def test_the_pace_of_the_round_is_untouched(self, difficulty) -> None:
        """What the player feels, and the second reported bug: medium came
        out feeling as slow as beginner.

        Turning is decoration. If adding it changed how many moles a round
        produces or how long each is out, the level would feel like a
        different level.
        """

        def pacing(span_fraction: float) -> tuple[int, int]:
            game = WhackAMole(
                field_width_mm=FIELD_W,
                field_height_mm=FIELD_H,
                seed=21,
                difficulty=difficulty,
                config=GameConfig(turn_span_fraction=span_fraction),
            )
            visible_frames = 0
            while game.running:
                game.update(1 / 60, [])
                visible_frames += sum(
                    1 for h in game.holes() if h.state is not MoleState.DOWN
                )
            return game.spawned, visible_frames

        assert pacing(0.2) == pacing(0.0)

    def test_the_same_seed_turns_the_same_way(self) -> None:
        def turns(seed: int) -> list[tuple[float, int, float]]:
            game = WhackAMole(
                field_width_mm=FIELD_W, field_height_mm=FIELD_H, seed=seed
            )
            seen: list[tuple[float, int, float]] = []
            while game.running:
                for event in game.update(1 / 60, []):
                    if event.kind == "turned":
                        seen.append(
                            (
                                round(game.elapsed_s, 4),
                                event.hole_index,
                                round(event.duration_s, 6),
                            )
                        )
            return seen

        assert turns(4) == turns(4)
        assert turns(4) != turns(5)

    def test_a_reset_round_still_turns(self) -> None:
        game = make_game()
        while game.running:
            game.update(1 / 60, [])
        game.reset(seed=77)
        turns = 0
        while game.running:
            turns += sum(1 for e in game.update(1 / 60, []) if e.kind == "turned")
        assert turns > 0


class TestTurnSpin:
    """How the view shows a turn: a card spinning about its own axis.

    The duration is the rules' (the ``turned`` event carries it), so these
    use an explicit span rather than a constant of the view's own.
    """

    SPAN = 0.3

    def test_a_mole_that_is_not_turning_keeps_its_full_width(self) -> None:
        from tabletop.apps.whack_a_mole import turn_spin_factor

        assert turn_spin_factor(0.0, self.SPAN) == pytest.approx(1.0)

    def test_a_zero_span_is_not_a_division_by_zero(self) -> None:
        """A view that never heard a span must still draw the mole."""
        from tabletop.apps.whack_a_mole import turn_spin_factor

        assert turn_spin_factor(0.1, 0.0) == pytest.approx(1.0)

    def test_the_spin_starts_on_the_old_pose(self) -> None:
        """The rules flip the facing at the start of the turn, so the
        animation has to open by showing its mirror -- otherwise the card
        snaps to the new pose and then spins, which looks like two turns."""
        from tabletop.apps.whack_a_mole import turn_spin_factor

        assert turn_spin_factor(self.SPAN, self.SPAN) == pytest.approx(-1.0)

    def test_the_card_passes_through_edge_on_at_the_midpoint(self) -> None:
        from tabletop.apps.whack_a_mole import turn_spin_factor

        assert turn_spin_factor(self.SPAN / 2, self.SPAN) == pytest.approx(
            0.0, abs=1e-9
        )

    def test_the_spin_is_monotonic(self) -> None:
        from tabletop.apps.whack_a_mole import turn_spin_factor

        steps = 20
        values = [
            turn_spin_factor(self.SPAN * (1.0 - i / steps), self.SPAN)
            for i in range(steps + 1)
        ]
        assert values == sorted(values)

    def test_the_factor_never_widens_the_card(self) -> None:
        from tabletop.apps.whack_a_mole import turn_spin_factor

        for i in range(41):
            factor = turn_spin_factor(self.SPAN * i / 40, self.SPAN)
            assert -1.0 <= factor <= 1.0

    def test_the_spin_eases_in_and_out(self) -> None:
        """Smooth at both ends: the first and last steps move the card
        least, which is what keeps a turn from starting with a jolt."""
        from tabletop.apps.whack_a_mole import turn_spin_factor

        steps = 24
        values = [
            turn_spin_factor(self.SPAN * (1.0 - i / steps), self.SPAN)
            for i in range(steps + 1)
        ]
        deltas = [b - a for a, b in zip(values, values[1:])]
        middle = deltas[len(deltas) // 2]
        assert deltas[0] < middle / 3
        assert deltas[-1] < middle / 3

    def test_no_step_of_the_spin_is_a_jump(self) -> None:
        """At 60 Hz, even the shortest span this project produces moves the
        card less than half its width per frame."""
        from tabletop.apps.whack_a_mole import turn_spin_factor

        dt = 1 / 60
        remaining = self.SPAN
        previous = turn_spin_factor(remaining, self.SPAN)
        while remaining > 0.0:
            remaining = max(0.0, remaining - dt)
            current = turn_spin_factor(remaining, self.SPAN)
            assert abs(current - previous) <= 0.5
            previous = current

    def test_the_spin_is_antisymmetric_about_its_midpoint(self) -> None:
        """What makes a second turn mid-spin continuous: the width is the
        facing times the factor, and a turn flips the facing, so the factor
        has to flip too for the card to stay where it is."""
        from tabletop.apps.whack_a_mole import turn_spin_factor

        for i in range(1, 20):
            remaining = self.SPAN * i / 20
            assert turn_spin_factor(
                self.SPAN - remaining, self.SPAN
            ) == pytest.approx(-turn_spin_factor(remaining, self.SPAN))

    def test_turning_again_mid_spin_does_not_move_the_card(self) -> None:
        """Cannot happen with one turn per mole, and kept anyway: it is the
        property that makes the spin safe to retrigger at all."""
        from tabletop.apps.whack_a_mole import turn_restart_s, turn_spin_factor

        for i in range(1, 20):
            remaining = self.SPAN * i / 20
            width_before = turn_spin_factor(remaining, self.SPAN)
            width_after = -turn_spin_factor(
                turn_restart_s(remaining, self.SPAN), self.SPAN
            )
            assert width_before == pytest.approx(width_after)

    def test_a_turn_from_rest_runs_the_whole_spin(self) -> None:
        from tabletop.apps.whack_a_mole import turn_restart_s

        assert turn_restart_s(0.0, self.SPAN) == pytest.approx(self.SPAN)

    def test_a_restart_never_asks_for_more_than_a_full_spin(self) -> None:
        from tabletop.apps.whack_a_mole import turn_restart_s

        for remaining in (-1.0, 0.0, 0.01, self.SPAN, self.SPAN * 2):
            assert 0.0 <= turn_restart_s(remaining, self.SPAN) <= self.SPAN


class TestPopShade:
    """The dark patch in a hole as a mole passes through its mouth.

    The sprite mole had no shadow at all, so its pop was a pure change of
    position: nothing said it was coming up out of something. A true cast
    shadow is wrong for it -- with the light the shaders use, a body 78 mm
    above the glass casts 52 mm away, outside the 40 mm rim and beside the
    mound the artwork paints, which reads as a dark blob with no owner. So
    this sits in the hole and says "occupied" instead.
    """

    LINGER = 0.16

    def test_a_concealed_mole_makes_the_hole_darkest(self) -> None:
        """The moment before the pop, which is the point of the cue."""
        from tabletop.apps.whack_a_mole import POP_SHADE_ALPHA, pop_shade_alpha

        assert pop_shade_alpha(True, 0.0, 0.0, self.LINGER) == pytest.approx(
            POP_SHADE_ALPHA
        )

    def test_it_is_gone_by_the_time_the_mole_is_out(self) -> None:
        """Otherwise it is a smudge under a mole that is standing clear."""
        from tabletop.apps.whack_a_mole import pop_shade_alpha

        assert pop_shade_alpha(True, 1.0, 0.0, self.LINGER) == pytest.approx(0.0)

    def test_it_fades_as_the_mole_rises(self) -> None:
        from tabletop.apps.whack_a_mole import pop_shade_alpha

        values = [pop_shade_alpha(True, i / 10, 0.0, self.LINGER) for i in range(11)]
        assert values == sorted(values, reverse=True)

    def test_it_comes_back_as_the_mole_drops(self) -> None:
        """Same function of height, so the retreat is the rise reversed."""
        from tabletop.apps.whack_a_mole import pop_shade_alpha

        assert pop_shade_alpha(True, 0.2, 0.0, self.LINGER) > pop_shade_alpha(
            True, 0.8, 0.0, self.LINGER
        )

    def test_it_lingers_after_the_hole_is_empty(self) -> None:
        """The trailing half of the cue: a retreat should not look like the
        mole was deleted."""
        from tabletop.apps.whack_a_mole import POP_SHADE_ALPHA, pop_shade_alpha

        assert pop_shade_alpha(False, 0.0, self.LINGER, self.LINGER) == pytest.approx(
            POP_SHADE_ALPHA
        )
        assert pop_shade_alpha(
            False, 0.0, self.LINGER / 2, self.LINGER
        ) == pytest.approx(POP_SHADE_ALPHA / 2)

    def test_an_empty_hole_is_not_shaded_once_the_linger_is_done(self) -> None:
        """The bug this caught: height 0 means "concealed mole" to the rise
        and "nothing there" to an empty hole, and reading it the first way
        left every idle hole on the field permanently dark."""
        from tabletop.apps.whack_a_mole import pop_shade_alpha

        assert pop_shade_alpha(False, 0.0, 0.0, self.LINGER) == 0.0

    def test_the_linger_runs_out(self) -> None:
        from tabletop.apps.whack_a_mole import pop_shade_alpha

        faded = [
            pop_shade_alpha(False, 0.0, self.LINGER * (1 - i / 10), self.LINGER)
            for i in range(10)
        ]
        assert faded == sorted(faded, reverse=True)

    def test_the_shade_never_exceeds_its_ceiling(self) -> None:
        from tabletop.apps.whack_a_mole import POP_SHADE_ALPHA, pop_shade_alpha

        for present in (True, False):
          for height in (-0.5, 0.0, 0.5, 1.0, 1.2):
            for left in (-0.1, 0.0, 0.08, 0.16, 1.0):
                alpha = pop_shade_alpha(present, height, left, self.LINGER)
                assert 0.0 <= alpha <= POP_SHADE_ALPHA

    def test_a_zero_linger_is_not_a_division_by_zero(self) -> None:
        from tabletop.apps.whack_a_mole import pop_shade_alpha

        assert pop_shade_alpha(False, 0.0, 0.05, 0.0) >= 0.0


class TestTurnFrames:
    """Turning by picking a frame, instead of mirroring the card.

    The artwork paints the mole and its dirt mound on one sheet, so
    mirroring the card to face the mole the other way mirrored the earth
    with it -- the mound jumped sides -- and the turn's squeeze flattened
    the dirt along with the animal. The strip bakes the pair together per
    frame, so the mound is the same pixels throughout and cannot move.
    """

    def test_full_width_picks_the_end_frames(self) -> None:
        from tabletop.apps.whack_a_mole import turn_frame
        from tabletop.render.assets import MOLE_TURN_FRAME_WIDTHS as widths

        assert turn_frame(1.0) == 0
        assert turn_frame(-1.0) == len(widths) - 1

    def test_edge_on_picks_the_middle_frame(self) -> None:
        from tabletop.apps.whack_a_mole import turn_frame
        from tabletop.render.assets import MOLE_TURN_FRAME_WIDTHS as widths

        assert turn_frame(0.0) == len(widths) // 2

    def test_the_frame_follows_the_spin_monotonically(self) -> None:
        """Sweeping a turn walks the strip one way, never back and forth."""
        from tabletop.apps.whack_a_mole import turn_frame

        frames = [turn_frame(1.0 - 2.0 * i / 40) for i in range(41)]
        assert frames == sorted(frames)
        assert frames[0] == 0
        assert frames[-1] == len(set(frames)) - 1

    def test_every_frame_is_reachable(self) -> None:
        """A frame no signed width selects is a frame baked for nothing."""
        from tabletop.apps.whack_a_mole import turn_frame
        from tabletop.render.assets import MOLE_TURN_FRAME_WIDTHS as widths

        picked = {turn_frame(1.0 - 2.0 * i / 200) for i in range(201)}
        assert picked == set(range(len(widths)))

    def test_the_ladder_is_symmetric(self) -> None:
        """The two rest poses have to be equal and opposite, or the mole
        ends a turn narrower than it started."""
        from tabletop.render.assets import MOLE_TURN_FRAME_WIDTHS as widths

        assert widths[0] == 1.0
        assert widths[-1] == -1.0
        assert [-x for x in reversed(widths)] == list(widths)


class TestTurnStripAsset:
    """The baked strip itself. Needs Pillow, which the dev extra brings in."""

    @pytest.fixture(scope="class")
    @classmethod
    def frames(cls):
        np = pytest.importorskip("numpy")
        Image = pytest.importorskip("PIL.Image")
        from tabletop.render import assets

        path = assets.ASSETS_DIR / assets.MOLE_TURN_STRIP
        if not path.is_file():
            pytest.skip("turn strip not baked")
        strip = np.asarray(Image.open(path).convert("RGBA"))
        count = len(assets.MOLE_TURN_FRAME_WIDTHS)
        assert strip.shape[1] % count == 0, "strip is not a whole number of frames"
        w = strip.shape[1] // count
        return [strip[:, i * w : (i + 1) * w] for i in range(count)]

    def test_the_mound_is_identical_in_every_frame(self, frames) -> None:
        """The whole point. A band near the bottom is mound only -- the
        mole's lowest claw is well above it -- so if the dirt ever moves or
        mirrors, these rows stop matching.
        """
        import numpy as np

        h = frames[0].shape[0]
        band = slice(int(h * 0.88), h)
        first = frames[0][band]
        for i, frame in enumerate(frames[1:], start=1):
            assert np.array_equal(frame[band], first), f"frame {i} moved the mound"

    def test_the_mound_band_is_not_symmetric(self, frames) -> None:
        """Teeth for the test above: a left-right symmetric mound would
        survive being mirrored, and prove nothing."""
        import numpy as np

        h = frames[0].shape[0]
        band = frames[0][int(h * 0.88) : h]
        assert not np.array_equal(band, band[:, ::-1])

    def test_the_mole_does_change_between_frames(self, frames) -> None:
        """Otherwise the strip is seven copies of one pose."""
        import numpy as np

        assert not np.array_equal(frames[0], frames[-1])
        # The end frames face opposite ways, so one is roughly the mirror
        # of the other where the mole is.
        assert np.array_equal(frames[0].shape, frames[-1].shape)

    def test_the_edge_on_frame_has_no_mole(self, frames) -> None:
        """At zero width a card with no thickness shows nothing, so that
        frame is the mound alone -- which is also what makes it the
        reference for the mound's own pixels."""
        from tabletop.render.assets import MOLE_TURN_FRAME_WIDTHS as widths

        middle = frames[len(widths) // 2]
        # The mole's own colours: blue-grey body and peach muzzle.
        rgb = middle[..., :3].astype(int)
        opaque = middle[..., 3] > 128
        bluish = opaque & (rgb[..., 2] > rgb[..., 0] + 15)
        assert bluish.mean() < 0.005, "mole body left in the edge-on frame"

    def test_the_mound_encloses_no_transparent_pockets(self, frames) -> None:
        """Holes in the dirt only show once the mole turns away from them.

        Colour separation left the tips of both claws as transparent
        pockets in the mound -- a few dozen pixels each, hidden behind the
        mole in the pose it was drawn in, and a pair of pale specks in the
        dirt in every other frame. A pocket is transparency unreachable
        from the border, which is what distinguishes it from the sky.
        """
        import numpy as np

        for i, frame in enumerate(frames):
            holes = frame[..., 3] <= 128
            reach = np.zeros_like(holes)
            front = np.zeros_like(holes)
            front[0, :] = front[-1, :] = True
            front[:, 0] = front[:, -1] = True
            front &= holes
            while front.any():
                reach |= front
                grow = np.zeros_like(front)
                grow[1:, :] |= front[:-1, :]
                grow[:-1, :] |= front[1:, :]
                grow[:, 1:] |= front[:, :-1]
                grow[:, :-1] |= front[:, 1:]
                front = grow & holes & ~reach
            pockets = int((holes & ~reach).sum())
            assert pockets == 0, f"frame {i} has {pockets} px of holes in the dirt"

    def test_no_pale_specks_in_the_dirt(self, frames) -> None:
        """Page white must not survive into the mound.

        Two ways it got there, and both showed as light specks in the dirt
        once the mole turned off them: flecks the separation took as mud,
        and -- less obviously -- donor pixels that the scrub had emptied
        but whose RGB was still white, copied into the rebuild as opaque
        white.

        Measured on the edge-on frame, which is the mound with no mole on
        it, and on the mound-only band of every other frame. Not on a
        whole frame: the mole's eye is legitimately white, and a test that
        banned pale pixels outright would demand it be painted out.
        """
        mound = frames[len(frames) // 2]
        h = mound.shape[0]
        regions = [("edge-on frame", mound)] + [
            (f"frame {i} dirt band", f[int(h * 0.88) :])
            for i, f in enumerate(frames)
        ]
        for name, region in regions:
            opaque = region[..., 3] > 128
            pale = int((opaque & (region[..., :3].min(2) > 170)).sum())
            assert pale == 0, f"{name} has {pale} pale px"

    def test_the_two_poses_do_not_drift(self, frames) -> None:
        """A mole that changes direction must not appear to step sideways.

        Both poses are mirrored about the card's centre, which is where the
        mole's centre of mass was moved to, so the animal's weight stays
        over the hole either way. The mole is whatever differs from the
        edge-on frame, since that frame is the mound alone.
        """
        import numpy as np

        mound = frames[len(frames) // 2]

        def centroid(frame):
            differs = (frame != mound).any(2)
            ys, xs = np.nonzero(differs)
            assert xs.size, "no mole in this frame"
            return xs.mean()

        right, left = centroid(frames[0]), centroid(frames[-1])
        assert right == pytest.approx(left, abs=1.5), (
            f"the mole shifts {abs(right - left):.1f} px when it turns"
        )

    def test_the_mole_sits_over_the_hole(self, frames) -> None:
        """Centred on the card, because the card is centred on the hole."""
        import numpy as np

        mound = frames[len(frames) // 2]
        width = mound.shape[1]
        differs = (frames[0] != mound).any(2)
        xs = np.nonzero(differs)[1]
        assert xs.mean() == pytest.approx(width / 2, abs=width * 0.02)

    def test_only_the_mole_moves(self, frames) -> None:
        """Nothing in the dirt may travel with the mole.

        What used to: loose clods and short arcs of the mound's own outline
        that the claw rule claimed by proximity, and blades of grass at the
        edge. Three or four specks sliding across the earth as the mole
        turns, which reads as the picture coming apart.

        The mole is whatever differs from the edge-on frame. If that is one
        connected piece, everything moving is the animal; islands are
        scenery that got dragged along.
        """
        import numpy as np

        mound = frames[len(frames) // 2]
        differs = (frames[0] != mound).any(2)
        h, w = differs.shape

        seen = np.zeros_like(differs)
        sizes = []
        for y in range(h):
            for x in range(w):
                if not differs[y, x] or seen[y, x]:
                    continue
                stack = [(y, x)]
                seen[y, x] = True
                n = 0
                while stack:
                    cy, cx = stack.pop()
                    n += 1
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if (
                            0 <= ny < h
                            and 0 <= nx < w
                            and differs[ny, nx]
                            and not seen[ny, nx]
                        ):
                            seen[ny, nx] = True
                            stack.append((ny, nx))
                sizes.append(n)

        sizes.sort(reverse=True)
        assert sizes, "nothing moves at all"
        strays = [n for n in sizes[1:] if n > 20]
        assert not strays, f"scenery travels with the mole: {strays} px islands"
        assert sizes[0] / sum(sizes) > 0.99

    def test_no_grass_travels_with_the_mole(self, frames) -> None:
        """Grass grows out of the mound, so it stays with the mound."""
        import numpy as np

        mound = frames[len(frames) // 2]
        moving = (frames[0] != mound).any(2) | (frames[-1] != mound).any(2)
        rgb = frames[0][..., :3].astype(int)
        green = (
            moving
            & (rgb[..., 1] > rgb[..., 0] + 10)
            & (rgb[..., 1] > rgb[..., 2] + 10)
        )
        assert int(green.sum()) < 100, f"{int(green.sum())} green px move"

    def test_the_claws_travel_with_the_mole(self, frames) -> None:
        """Five to a paw, drawn over the dirt in dark brown and black.

        Split between the layers, their black strokes went with the mole
        and their brown fill stayed in the mud, so turning left a wedge of
        claw behind in the dirt. The mole's own dark marks should outnumber
        what is left under its paws by a wide margin.
        """
        import numpy as np

        mound = frames[len(frames) // 2]
        paws = slice(185, 300)
        differs = (frames[0] != mound).any(2)[paws]
        mole_band = frames[0][paws]
        dirt_band = mound[paws]

        def dark(band, mask=None):
            d = (band[..., 3] > 128) & (band[..., :3].max(2) < 110)
            return int((d & mask).sum()) if mask is not None else int(d.sum())

        on_mole = dark(mole_band, differs)
        in_dirt = dark(dirt_band)
        assert on_mole > in_dirt, (
            f"only {on_mole} px of dark detail on the paws against "
            f"{in_dirt} px left in the dirt"
        )
