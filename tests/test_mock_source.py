"""Mock touch source behaviour.

The phase lifecycle is the valuable thing here. Game code is allowed to
assume BEGAN appears once, ENDED appears once, and ids are not recycled; the
mock is where that guarantee lives and therefore where it has to be proven.
A touchscreen reader has to behave the same way, and these tests are what
"the same way" means.
"""

from __future__ import annotations

import pytest

from tabletop.core.calibration import TableCalibration
from tabletop.core.events import TouchPhase
from tabletop.sensors.mock import (
    Contact,
    MockTouchSource,
    ScriptStep,
    ScriptedTouchSource,
    collinear_three_finger_script,
)


@pytest.fixture
def cal() -> TableCalibration:
    return TableCalibration.development_default()


@pytest.fixture
def source(cal: TableCalibration) -> MockTouchSource:
    s = MockTouchSource(cal)
    s.start()
    return s


class TestPhaseLifecycle:
    def test_began_then_moved(self, source: MockTouchSource) -> None:
        source.set_point("a", 10.0, 20.0)
        first = source.poll()
        assert [t.phase for t in first.touches] == [TouchPhase.BEGAN]

        second = source.poll()
        assert [t.phase for t in second.touches] == [TouchPhase.MOVED]

    def test_began_is_reported_exactly_once(self, source: MockTouchSource) -> None:
        source.set_point("a", 0.0, 0.0)
        phases = []
        for _ in range(4):
            phases += [t.phase for t in source.poll().touches]
        assert phases.count(TouchPhase.BEGAN) == 1

    def test_ended_is_reported_exactly_once_then_disappears(
        self, source: MockTouchSource
    ) -> None:
        source.set_point("a", 0.0, 0.0)
        source.poll()
        source.clear_contact("a")

        ended = source.poll()
        assert [t.phase for t in ended.touches] == [TouchPhase.ENDED]

        after = source.poll()
        assert after.touches == ()

    def test_ended_carries_the_last_known_position(
        self, source: MockTouchSource
    ) -> None:
        """A lift event at (0, 0) instead of where the finger actually was
        would make any release-position logic -- dropping a piece, finishing
        a drag -- land in the wrong place."""
        source.set_point("a", 123.0, -45.0)
        source.poll()
        source.set_point("a", 200.0, -60.0)
        source.poll()
        source.clear_contact("a")

        ended = source.poll().touches[0]
        assert ended.x_mm == pytest.approx(200.0)
        assert ended.y_mm == pytest.approx(-60.0)

    def test_ids_are_not_recycled(self, source: MockTouchSource) -> None:
        """Real touch devices reuse slot numbers; the mock deliberately does
        not, so code developed against it cannot come to depend on
        recycling."""
        source.set_point("a", 0.0, 0.0)
        first_id = source.poll().touches[0].touch_id
        source.clear_contact("a")
        source.poll()

        source.set_point("a", 0.0, 0.0)
        second_id = source.poll().touches[0].touch_id
        assert second_id != first_id

    def test_concurrent_contacts_get_distinct_ids(
        self, source: MockTouchSource
    ) -> None:
        source.set_point("a", -100.0, 0.0)
        source.set_point("b", 100.0, 0.0)
        ids = {t.touch_id for t in source.poll().touches}
        assert len(ids) == 2

    def test_lifting_one_of_two_leaves_the_other_untouched(
        self, source: MockTouchSource
    ) -> None:
        source.set_point("a", -100.0, 0.0)
        source.set_point("b", 100.0, 0.0)
        source.poll()
        b_id = {t.touch_id for t in source.poll().touches if t.x_mm > 0}

        source.clear_contact("a")
        frame = source.poll()
        by_phase = {t.phase: t for t in frame.touches}
        assert TouchPhase.ENDED in by_phase
        assert TouchPhase.MOVED in by_phase
        assert by_phase[TouchPhase.MOVED].touch_id in b_id

    def test_clear_all(self, source: MockTouchSource) -> None:
        source.set_point("a", 0.0, 0.0)
        source.set_point("b", 1.0, 1.0)
        source.poll()
        source.clear_all()
        assert all(t.phase is TouchPhase.ENDED for t in source.poll().touches)
        assert source.poll().touches == ()


class TestFrameMetadata:
    def test_sequence_increments(self, source: MockTouchSource) -> None:
        assert [source.poll().seq for _ in range(3)] == [1, 2, 3]

    def test_contact_attributes_pass_through(self, source: MockTouchSource) -> None:
        source.set_contact(
            "a", Contact(1.0, 2.0, 3.0, major_mm=20.0, minor_mm=18.0, player_id=3)
        )
        touch = source.poll().touches[0]
        assert touch.z_mm == pytest.approx(3.0)
        assert touch.major_mm == pytest.approx(20.0)
        assert touch.player_id == 3
        assert touch.source == "mock"


class TestContextManager:
    def test_start_and_stop(self, cal: TableCalibration) -> None:
        with MockTouchSource(cal) as s:
            assert s.started
            s.poll()
        assert not s.started


class TestScriptedSource:
    def test_steps_advance_with_the_clock(self, cal: TableCalibration) -> None:
        now = {"t": 0.0}
        steps = [
            ScriptStep(0.0, {"a": Contact(0.0, 0.0)}),
            ScriptStep(1.0, {"a": Contact(0.0, 0.0), "b": Contact(50.0, 0.0)}),
            ScriptStep(2.0, {}),
        ]
        src = ScriptedTouchSource(cal, steps, loop=False, clock=lambda: now["t"])
        src.start()

        assert len(src.poll().touches) == 1

        now["t"] = 1.5
        frame = src.poll()
        assert len(frame.touches) == 2

        now["t"] = 2.5
        # Both contacts lift, so both report ENDED once.
        ended = src.poll()
        assert {t.phase for t in ended.touches} == {TouchPhase.ENDED}
        assert src.poll().touches == ()

    def test_looping_wraps_around(self, cal: TableCalibration) -> None:
        now = {"t": 0.0}
        steps = [
            ScriptStep(0.0, {"a": Contact(0.0, 0.0)}),
            ScriptStep(1.0, {"a": Contact(0.0, 0.0), "b": Contact(50.0, 0.0)}),
        ]
        # Period is 1.0 + 0.5 tail = 1.5s.
        src = ScriptedTouchSource(cal, steps, loop=True, clock=lambda: now["t"])
        src.start()
        src.poll()

        # Inside the final keyframe's hold, which the tail exists to make
        # observable.
        now["t"] = 1.2
        assert len(src.poll().touches) == 2

        # Past the period: wraps back to the first keyframe.
        now["t"] = 1.6
        frame = src.poll()
        live = [t for t in frame.touches if t.phase is not TouchPhase.ENDED]
        assert len(live) == 1

    def test_final_keyframe_is_reachable_when_looping(
        self, cal: TableCalibration
    ) -> None:
        """Regression: a loop period equal to the last keyframe's timestamp
        made the final state unreachable, so a script ending in "all lifted"
        never actually lifted anything."""
        now = {"t": 0.0}
        steps = [
            ScriptStep(0.0, {"a": Contact(0.0, 0.0)}),
            ScriptStep(1.0, {}),
        ]
        src = ScriptedTouchSource(cal, steps, loop=True, clock=lambda: now["t"])
        src.start()
        src.poll()

        now["t"] = 1.1
        assert {t.phase for t in src.poll().touches} == {TouchPhase.ENDED}
        assert src.poll().touches == ()

    def test_explicit_duration_must_exceed_the_last_keyframe(
        self, cal: TableCalibration
    ) -> None:
        with pytest.raises(ValueError, match="must exceed the last keyframe"):
            ScriptedTouchSource(
                cal,
                [ScriptStep(0.0, {}), ScriptStep(2.0, {})],
                duration_s=2.0,
            )

    def test_empty_script_is_rejected(self, cal: TableCalibration) -> None:
        with pytest.raises(ValueError, match="at least one step"):
            ScriptedTouchSource(cal, [])

    def test_negative_timestamps_are_rejected(self, cal: TableCalibration) -> None:
        with pytest.raises(ValueError, match="negative timestamps"):
            ScriptedTouchSource(cal, [ScriptStep(-1.0, {})])

    def test_steps_need_not_be_supplied_in_order(self, cal: TableCalibration) -> None:
        now = {"t": 0.0}
        src = ScriptedTouchSource(
            cal,
            [
                ScriptStep(1.0, {"a": Contact(0.0, 0.0), "b": Contact(1.0, 1.0)}),
                ScriptStep(0.0, {"a": Contact(0.0, 0.0)}),
            ],
            loop=False,
            clock=lambda: now["t"],
        )
        src.start()
        assert len(src.poll().touches) == 1


class TestCollinearScript:
    def test_builds_three_contacts_on_one_row(self, cal: TableCalibration) -> None:
        """The occlusion case worth having a repeatable fixture for: three
        contacts sharing a Y row, where the middle one is the one a real
        touchscreen is most likely to lose."""
        steps = collinear_three_finger_script(cal, y_mm=25.0)
        widest = max(steps, key=lambda s: len(s.contacts))
        assert len(widest.contacts) == 3
        ys = {c.y_mm for c in widest.contacts.values()}
        assert ys == {25.0}

        xs = sorted(c.x_mm for c in widest.contacts.values())
        assert xs[0] < xs[1] < xs[2], "contacts should be distinct along X"

    def test_script_ends_with_everything_lifted(self, cal: TableCalibration) -> None:
        steps = collinear_three_finger_script(cal)
        assert steps[-1].contacts == {}
