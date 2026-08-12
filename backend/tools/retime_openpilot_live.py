#!/usr/bin/env python3
"""Create correctly timed copies of an existing openpilot live recording."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any

from run_openpilot_live import measured_frame_rate, retime_video_in_place


def timeline(path: Path) -> tuple[int, int, int]:
    count = 0
    first: int | None = None
    last: int | None = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            timestamp = int(json.loads(line)["timestamp_us"])
            if first is None:
                first = timestamp
            if last is not None and timestamp <= last:
                raise ValueError(f"Chronologie non croissante dans {path}")
            last = timestamp
            count += 1
    if count < 2 or first is None or last is None:
        raise ValueError(f"Chronologie insuffisante dans {path}")
    return count, first, last


def retime_copy(session: Path, stem: str, timeline_name: str, nominal_fps: float) -> dict[str, Any] | None:
    source = session / f"{stem}.mp4"
    timestamps = session / timeline_name
    if not source.is_file() or not timestamps.is_file():
        return None
    count, first, last = timeline(timestamps)
    output = session / f"{stem}-realtime.mp4"
    shutil.copyfile(source, output)
    result = retime_video_in_place(output, count, first, last, nominal_fps)
    return {
        "source": str(source),
        "output": str(output),
        "frame_count": count,
        "capture_duration_s": round((last - first) / 1_000_000.0, 6),
        "measured_fps": round(measured_frame_rate(count, first, last), 6),
        "retime": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    session = args.session.resolve()
    meta_path = session / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    nominal_fps = float(meta.get("requested_fps") or 30.0)
    report = {
        "session": session.name,
        "nominal_fps": nominal_fps,
        "road": retime_copy(session, "road", "frames.jsonl", nominal_fps),
        "overlay": retime_copy(session, "overlay", "overlay_frames.jsonl", nominal_fps),
    }
    output = session / "retime-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
