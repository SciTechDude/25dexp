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
