#!/usr/bin/env python3
"""Audit recorded EPS availability; no CAN/serial/network transport is present."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

MAX_AGE_US = 250_000
LENGTHS = {0x2F5: 7, 0x305: 7, 0x30D: 8, 0x38D: 8, 0x3F2: 8, 0x412: 8, 0x495: 4}


@dataclass(frozen=True)
class Frame:
    timestamp_us: int
    address: int
    flags: int
    data: bytes


def parse_compact(raw: bytes) -> Frame:
    """PSA gateway v6/v7: flags carry DLC, extended/RTR and diagnostic bus."""
    fields = raw.decode("ascii").strip().split(",")
    if len(fields) != 6 or fields[0] != "F":
        raise ValueError("Invalid compact frame")
    timestamp, sequence, address, flags = (int(value, 16) for value in fields[1:5])
    data = bytes.fromhex(fields[5])
    dlc = (flags >> 2) & 0xF
    if min(timestamp, sequence, address, flags) < 0 or flags > 0x7F or dlc > 8:
        raise ValueError("Invalid header")
    if address > (0x1FFFFFFF if flags & 1 else 0x7FF):
        raise ValueError("Invalid identifier")
    if len(data) != (0 if flags & 2 else dlc):
        raise ValueError("DLC mismatch")
    return Frame(timestamp, address, flags, data)


def speed_checksum_valid(data: bytes) -> bool:
    # Locally validated 0x38D checksum: low nibble of byte 5, initial 0x7.
    if len(data) != 8:
        return False
    total = sum((value >> 4) + (0 if i == 5 else value & 15) for i, value in enumerate(data))
    return ((7 - total) & 15) == (data[5] & 15)


def speed_bin(speed: float) -> str:
    if speed <= 0.1:
        return "stationary"
    for limit, label in ((50.0, "below_50"), (65.0, "50_to_65"), (67.1, "65_to_67.1")):
        if speed < limit:
            return label
    return "at_least_67.1"


class AvailabilityAudit:
    def __init__(self) -> None:
        self.counters: Counter = Counter()
        self.bins: dict[str, Counter] = defaultdict(Counter)
        self.latest: dict[int, Frame] = {}
        self.last_timestamp: int | None = None
        self.previous_eps: tuple[int, int] | None = None
        self.transitions: list[dict] = []

    def clear_history(self) -> None:
        self.latest.clear()
        self.previous_eps = None
        self.last_timestamp = None

    def fresh(self, address: int, now: int) -> bytes | None:
        frame = self.latest.get(address)
        if frame is not None and 0 <= now - frame.timestamp_us <= MAX_AGE_US:
            return frame.data
        return None

    def context(self, now: int) -> dict:
        result: dict = {}
        speed = self.fresh(0x38D, now)
        result["speed_kph"] = int.from_bytes(speed[:2], "big") / 100 if speed else None
        wheels = self.fresh(0x30D, now)
        result["wheel_speeds_kph"] = [int.from_bytes(wheels[i:i+2], "big") / 100 for i in range(0, 8, 2)] if wheels else None
        angle = self.fresh(0x305, now)
        result["angle_deg"] = int.from_bytes(angle[:2], "big", signed=True) / 10 if angle else None
        result["steering_rate_deg_s"] = angle[2] * (-1 if angle[3] & 0x80 else 1) if angle else None
        driver = self.fresh(0x2F5, now)
        result["driver_torque_raw"] = int.from_bytes(driver[1:2], "big", signed=True) if driver else None
        body = self.fresh(0x412, now)
        result["brake_pressed"] = bool(body[0] & 0x20) if body else None
        lka = self.fresh(0x3F2, now)
        result["bsi_lka_state"] = (lka[4] >> 2) & 7 if lka else None
        result["lka_factor_raw"] = (lka[5] >> 1) & 127 if lka else None
        result["ages_us"] = {f"0x{address:03X}": now - frame.timestamp_us for address, frame in self.latest.items()}
        return result

    def observe(self, frame: Frame) -> None:
        self.counters["parsed_frames"] += 1
        # Never associate diagnostic-bus or extended/RTR data with live HS1.
        if frame.flags & 0x43:
            self.counters["other_bus_or_frame_type"] += 1
            return
        now, address, data = frame.timestamp_us, frame.address, frame.data
        if self.last_timestamp is not None and now < self.last_timestamp:
            self.counters["timestamp_reversals"] += 1
            self.clear_history()
        self.last_timestamp = now
        if address not in LENGTHS:
            return
        if len(data) != LENGTHS[address]:
            self.counters["wrong_target_dlc"] += 1
            self.latest.pop(address, None)
            self.previous_eps = None
            return
        if address == 0x38D and (not speed_checksum_valid(data) or int.from_bytes(data[:2], "big") > 30000):
            self.counters["invalid_speed"] += 1
            self.latest.pop(address, None)
            self.previous_eps = None
            return
        self.latest[address] = frame
        if address != 0x495:
            return
        context = self.context(now)
        speed = context["speed_kph"]
        if speed is None:
            self.counters["eps_without_fresh_speed"] += 1
            self.previous_eps = None
            return
        state = (data[2] >> 2) & 7
        self.bins[speed_bin(speed)][str(state)] += 1
        wheels = context["wheel_speeds_kph"]
        if speed <= 0.1 and wheels is not None and all(value <= 0.1 for value in wheels):
            self.counters["eps_stationary_confirmed_by_four_wheels"] += 1
        previous = self.previous_eps
        if previous and 0 < now - previous[0] <= MAX_AGE_US and previous[1] != state:
            self.transitions.append({"timestamp_us": now, "from": previous[1], "to": state,
                                     "eps_raw_hex": data.hex().upper(), **context})
        self.previous_eps = now, state


def audit_capture(path: Path) -> dict:
    audit = AvailabilityAudit()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            if not raw.startswith(b"F,"):
                if raw.startswith(b"{"):
                    try:
                        if json.loads(raw).get("type") == "hello":
                            audit.clear_history()
                    except (ValueError, UnicodeDecodeError, AttributeError):
                        pass
                continue
            try:
                frame = parse_compact(raw)
            except (ValueError, UnicodeDecodeError):
                audit.counters["malformed_compact_lines"] += 1
                audit.clear_history()
                continue
            audit.observe(frame)
    return {"capture": str(path.resolve()), "sha256": digest.hexdigest(),
            "counters": dict(audit.counters), "eps_states_by_speed": dict(audit.bins),
            "transitions": audit.transitions}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = {"mode": "offline_received_data", "vehicle_tx": False, "max_age_us": MAX_AGE_US,
              "limits": ["Only the 0x38D checksum is checked; EPS/other signal protection is not qualified here.",
                         "State correlations do not prove causation or acceptance of injected commands.",
                         "CAN wheel speeds corroborate reported standstill, not an independent physical measurement."],
              "captures": [audit_capture(path) for path in args.captures]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "availability.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Disponibilité EPS T9 — audit des captures", "", "Analyse hors ligne, aucune émission CAN.", "",
             "| Capture | EPS avec vitesse nulle et quatre roues à zéro | Vitesse invalide | Transitions |",
             "|---|---:|---:|---:|"]
    for item in result["captures"]:
        count = item["counters"]
        lines.append(f"| {Path(item['capture']).parent.name} | {count.get('eps_stationary_confirmed_by_four_wheels', 0)} | {count.get('invalid_speed', 0)} | {len(item['transitions'])} |")
    lines.extend(["", "Les transitions détaillées et leurs signaux contemporains sont dans `availability.json`.",
                  "Le checksum de vitesse est vérifié. Les autres signaux restent des observations diagnostiques.",
                  "Aucune de ces corrélations ne valide un contournement des conditions de fonctionnement."])
    (args.output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(args.output_dir / "report.md")


if __name__ == "__main__":
    main()
