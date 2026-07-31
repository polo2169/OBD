from pathlib import Path
import json
import time

from app.config import settings


def event(ts, can_id, data_hex, direction="unknown"):
    return {
        "type": "can_frame",
        "timestamp_us": ts,
        "arbitration_id": can_id,
        "extended": False,
        "data_hex": data_hex,
        "direction": direction,
    }


def main():
    settings.session_dir.mkdir(parents=True, exist_ok=True)
    session_id = "learn-demo-psa"
    path = settings.session_dir / f"{session_id}.jsonl"
    t = time.time_ns() // 1000

    events = [
        {"type": "meta", "timestamp_us": t, "source": "demo", "readonly": True},
        {"type": "marker", "timestamp_us": t + 1000, "name": "avant_lecture_vin"},
        event(t + 2000, 0x7E0, "0322F19000000000", "tx"),
        event(t + 10000, 0x7E8, "101462F190564633", "rx"),
        event(t + 12000, 0x7E0, "3000000000000000", "tx"),
        event(t + 14000, 0x7E8, "214C4A484E59574A", "rx"),
        event(t + 16000, 0x7E8, "2253313233343536", "rx"),
        {"type": "marker", "timestamp_us": t + 20000, "name": "apres_lecture_vin"},
        {"type": "marker", "timestamp_us": t + 30000, "name": "avant_lecture_dtc"},
        event(t + 32000, 0x7E0, "031902FF00000000", "tx"),
        event(t + 39000, 0x7E8, "035902FF00000000", "rx"),
        {"type": "marker", "timestamp_us": t + 45000, "name": "apres_lecture_dtc"},
    ]

    path.write_text(
        "\n".join(json.dumps(x) for x in events) + "\n",
        encoding="utf-8",
    )
    print(session_id)


if __name__ == "__main__":
    main()
