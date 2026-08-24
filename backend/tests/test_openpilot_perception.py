import json
from pathlib import Path

import pytest

from tools.run_openpilot_perception import (
    current_lead,
    find_video,
    lead_speed_estimate,
    load_camera_frames,
    load_speed_by_frame,
    openpilot_lead_distance,
)


def test_camera_timeline_must_start_at_zero_and_stay_contiguous(tmp_path: Path) -> None:
    timeline = tmp_path / "frames.jsonl"
    timeline.write_text(
        '{"frame_index":0,"timestamp_us":1000000}\n'
        '{"frame_index":1,"timestamp_us":1033333}\n',
        encoding="utf-8",
    )

    frames = load_camera_frames(timeline)

    assert [(frame.index, frame.timestamp_us) for frame in frames] == [
        (0, 1_000_000),
        (1, 1_033_333),
    ]

    timeline.write_text(
        '{"frame_index":1,"timestamp_us":1000000}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="commencer.*0"):
        load_camera_frames(timeline)


def test_can_speed_is_converted_to_metres_per_second(tmp_path: Path) -> None:
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text(
        "\n".join(
            [
                json.dumps({"frame_index": 4, "speed_kph": 36.0}),
                json.dumps({"frame_index": 5, "speed_kph": None}),
                json.dumps({"frame_index": 6, "speed_kph": -2.0}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert load_speed_by_frame(telemetry) == {4: 10.0, 6: 0.0}
    assert load_speed_by_frame(None) == {}


def test_video_discovery_prefers_canonical_road_name(tmp_path: Path) -> None:
    canonical = tmp_path / "road.mp4"
    canonical.touch()
    (tmp_path / "backup.mp4").touch()

    assert find_video(tmp_path) == canonical


def test_openpilot_lead_distance_matches_radard_origin() -> None:
    assert openpilot_lead_distance(20.0) == pytest.approx(18.48)
    assert openpilot_lead_distance(1.0) == 0.0


def test_current_lead_is_zero_second_horizon_not_highest_probability() -> None:
    leads = [
        {"time_offset_s": 0.0, "prob": 0.70},
        {"time_offset_s": 2.0, "prob": 0.99},
        {"time_offset_s": 4.0, "prob": 0.95},
    ]

    assert current_lead(leads) is leads[0]


def test_lead_speed_estimate_matches_openpilot_vision_only_radar_math() -> None:
    # Model: lead=22 m/s and ego=18 m/s => relative speed=+4 m/s.
    # Correct it with the actual CAN ego speed (20 m/s) => lead=24 m/s.
    assert lead_speed_estimate({"v": [22.0]}, 20.0, 18.0) == pytest.approx((24.0, 4.0))


def test_lead_speed_estimate_ignores_missing_or_invalid_model_values() -> None:
    assert lead_speed_estimate({}, 20.0, 18.0) is None
    assert lead_speed_estimate({"v": [float("nan")]}, 20.0, 18.0) is None
