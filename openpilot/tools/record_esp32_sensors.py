#!/usr/bin/env python3
"""Record passive ESP32 GNSS/IMU telemetry as host-timestamped JSONL."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import signal
import time

import serial


def nmea_degrees(value: str, hemisphere: str) -> float | None:
    if not value or not hemisphere:
        return None
    degrees_width = 2 if hemisphere in ("N", "S") else 3
    result = float(value[:degrees_width]) + float(value[degrees_width:]) / 60.0
    return -result if hemisphere in ("S", "W") else result


def decode_nmea(sentence: str) -> dict[str, object]:
    fields = sentence.split("*")[0].split(",")
    kind = fields[0][-3:]
    result: dict[str, object] = {"sentence_type": kind}
    if kind == "RMC" and len(fields) >= 10:
        result.update({
            "utc": fields[1] or None,
            "fix_valid": fields[2] == "A",
            "latitude_deg": nmea_degrees(fields[3], fields[4]),
            "longitude_deg": nmea_degrees(fields[5], fields[6]),
            "speed_mps": round(float(fields[7]) * 0.514444, 4) if fields[7] else None,
            "course_deg": float(fields[8]) if fields[8] else None,
            "date_ddmmyy": fields[9] or None,
        })
    elif kind == "GGA" and len(fields) >= 10:
        result.update({
            "utc": fields[1] or None,
            "latitude_deg": nmea_degrees(fields[2], fields[3]),
            "longitude_deg": nmea_degrees(fields[4], fields[5]),
            "fix_quality": int(fields[6]) if fields[6] else 0,
            "satellites": int(fields[7]) if fields[7] else 0,
            "hdop": float(fields[8]) if fields[8] else None,
            "altitude_m": float(fields[9]) if fields[9] else None,
        })
    elif kind == "VTG" and len(fields) >= 8:
        result.update({
            "course_deg": float(fields[1]) if fields[1] else None,
            "speed_mps": round(float(fields[7]) / 3.6, 4) if fields[7] else None,
        })
    return result


def parse_line(line: str, received_wall_us: int, received_monotonic_ns: int) -> dict[str, object]:
    base: dict[str, object] = {
        "received_timestamp_us": received_wall_us,
        "received_monotonic_ns": received_monotonic_ns,
    }
    if line.startswith("GPS,"):
        prefix, esp_us, baud, sentence = line.split(",", 3)
        return base | {
            "type": prefix.lower(), "esp_timestamp_us": int(esp_us),
            "gps_baud": int(baud), "nmea": sentence,
        } | decode_nmea(sentence)
    if line.startswith("IMU,"):
        prefix, esp_us, x, y, z = line.split(",", 4)
        return base | {
            "type": prefix.lower(), "esp_timestamp_us": int(esp_us),
            "raw_x": int(x), "raw_y": int(y), "raw_z": int(z),
            "scale_g_per_lsb": 0.0039,
        }
    if line.startswith("STAT,"):
        fields = line.split(",")
        if len(fields) == 8:
            return base | {
                "type": "status", "uptime_ms": int(fields[1]), "gps_baud": int(fields[2]),
                "valid_nmea": int(fields[3]), "invalid_nmea": int(fields[4]),
                "gps_age_ms": None if fields[5] == "4294967295" else int(fields[5]),
                "adxl345_present": fields[6] == "1", "magnetometer_present": fields[7] == "1",
            }
    return base | {"type": "device", "line": line}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.output.open("w", encoding="utf-8") as output, serial.Serial(args.port, args.baud, timeout=0.1) as device:
        print(f"[sensors] lecture passive {args.port} -> {args.output}", flush=True)
        while not stop:
            raw = device.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="replace").strip()
            if not line:
                continue
            try:
                record = parse_line(line, time.time_ns() // 1000, time.monotonic_ns())
            except (ValueError, IndexError):
                record = {
                    "type": "malformed", "received_timestamp_us": time.time_ns() // 1000,
                    "received_monotonic_ns": time.monotonic_ns(), "line": line,
                }
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            if count % 20 == 0:
                output.flush()
    print(f"[sensors] terminé: {count} lignes", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
