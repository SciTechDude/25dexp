"""The input snapshots the game reads.

Everything here is about not losing information: a frame has to survive
being written out and read back unchanged, enums included, or a recorded
session replays as something subtly different from what happened.
"""

from __future__ import annotations

import json

import pytest

from tabletop.core.events import (
    FORMAT_VERSION,
    GestureEvent,
    HeadPose,
    SensorFrame,
    TouchKind,
    TouchPhase,
    TouchPoint,
)


def sample_frame() -> SensorFrame:
    return SensorFrame(
        seq=7,
        t_mono_ns=123_456_789,
        touches=(
            TouchPoint(
                touch_id=1,
                x_mm=12.5,
                y_mm=-30.0,
                phase=TouchPhase.BEGAN,
                kind=TouchKind.FINGER,
                major_mm=11.0,
                minor_mm=9.5,
                player_id=2,
                source="touch",
            ),
            TouchPoint(
                touch_id=2,
                x_mm=0.0,
                y_mm=0.0,
                z_mm=65.0,
                phase=TouchPhase.MOVED,
                kind=TouchKind.OBSTACLE,
                source="fused",
            ),
        ),
        heads=(HeadPose(player_id=2, x_mm=-100.0, y_mm=-350.0, z_mm=620.0),),
        gestures=(GestureEvent(gesture="flip", x_mm=5.0, y_mm=6.0, touch_id=1),),
    )


class TestSerialisation:
    def test_frame_round_trip(self) -> None:
        frame = sample_frame()
        assert SensorFrame.from_dict(frame.to_dict()) == frame

    def test_survives_a_json_hop(self) -> None:
        """Frames get written out as JSON, so the dict has to be made of
        JSON primitives -- no Enum objects leaking through."""
        frame = sample_frame()
        payload = json.dumps(frame.to_dict())
        assert SensorFrame.from_dict(json.loads(payload)) == frame

    def test_enums_serialise_as_plain_strings(self) -> None:
        d = sample_frame().to_dict()
        assert d["touches"][0]["phase"] == "began"
        assert d["touches"][0]["kind"] == "finger"
        assert isinstance(d["touches"][0]["phase"], str)

    def test_optional_size_survives_as_null(self) -> None:
        d = sample_frame().to_dict()
        assert d["touches"][1]["major_mm"] is None
        restored = SensorFrame.from_dict(json.loads(json.dumps(d)))
        assert restored.touches[1].major_mm is None

    def test_missing_kind_defaults_rather_than_failing(self) -> None:
        """Forward compatibility within a major version: a producer that
        predates the ``kind`` field must still be readable."""
        d = sample_frame().to_dict()
        del d["touches"][0]["kind"]
        restored = SensorFrame.from_dict(d)
        assert restored.touches[0].kind is TouchKind.UNKNOWN


class TestVersionGating:
    def test_same_major_is_accepted(self) -> None:
        d = sample_frame().to_dict()
        d["format_version"] = "1.99"
        assert SensorFrame.from_dict(d).seq == 7

    def test_different_major_is_rejected(self) -> None:
        d = sample_frame().to_dict()
        d["format_version"] = "2.0"
        with pytest.raises(ValueError, match="incompatible frame format"):
            SensorFrame.from_dict(d)

    def test_default_version_is_current(self) -> None:
        assert SensorFrame.now(seq=1).format_version == FORMAT_VERSION


class TestQueries:
    def test_head_lookup(self) -> None:
        frame = sample_frame()
        assert frame.head_for(2) is not None
        assert frame.head_for(99) is None

    def test_fingers_excludes_obstacles_but_keeps_unknown(self) -> None:
        """Unknown contacts are kept: with no contact size reported
        size nothing can be classified, and dropping unknowns there would
        discard every touch."""
        frame = sample_frame()
        ids = {t.touch_id for t in frame.fingers()}
        assert ids == {1}

        unknown = TouchPoint(touch_id=3, x_mm=0, y_mm=0, kind=TouchKind.UNKNOWN)
        frame2 = SensorFrame(seq=1, t_mono_ns=0, touches=(unknown,))
        assert len(frame2.fingers()) == 1

    def test_hover_detection(self) -> None:
        frame = sample_frame()
        assert not frame.touches[0].is_hovering
        assert frame.touches[1].is_hovering

    def test_now_uses_a_monotonic_timestamp(self) -> None:
        a = SensorFrame.now(seq=1)
        b = SensorFrame.now(seq=2)
        assert b.t_mono_ns >= a.t_mono_ns


def test_frames_are_immutable() -> None:
    """Frames are passed to game code; accidental mutation of sensor history
    should not be possible."""
    frame = sample_frame()
    with pytest.raises((AttributeError, TypeError)):
        frame.seq = 9  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        frame.touches[0].x_mm = 0.0  # type: ignore[misc]
