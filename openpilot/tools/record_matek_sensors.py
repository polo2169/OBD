#!/usr/bin/env python3
"""Record Matek F722-SE IMU, attitude and GNSS through read-only MSP polls."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import signal
import struct
import time
from typing import BinaryIO

import serial


STANDARD_GRAVITY_MS2 = 9.80665

MSP_API_VERSION = 1
MSP_FC_VARIANT = 2
MSP_FC_VERSION = 3
MSP_BOARD_INFO = 4
MSP_STATUS = 101
MSP_RAW_IMU = 102
MSP_RAW_GPS = 106
MSP_ATTITUDE = 108


@dataclass(frozen=True)
class MspFrame:
    direction: str
    command: int
    payload: bytes


def encode_msp_v1_request(command: int, payload: bytes = b"") -> bytes:
    """Build one MSP v1 request without any configuration side effect."""
    if not 0 <= command <= 0xFF or len(payload) > 0xFF:
        raise ValueError("Commande ou charge MSP v1 hors plage")
    checksum = len(payload) ^ command
    for value in payload:
        checksum ^= value
    return b"$M<" + bytes((len(payload), command)) + payload + bytes((checksum,))


class MspV1Parser:
    """Incremental parser which tolerates partial and unrelated serial bytes."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[MspFrame]:
        self._buffer.extend(data)
        frames: list[MspFrame] = []
        while True:
            start = self._buffer.find(b"$M")
            if start < 0:
                self._buffer[:] = self._buffer[-1:] if self._buffer.endswith(b"$") else b""
                break
            if start:
                del self._buffer[:start]
            if len(self._buffer) < 6:
                break
            direction_byte = self._buffer[2]
            if direction_byte not in (ord(">"), ord("!"), ord("<")):
                del self._buffer[0]
                continue
            payload_length = self._buffer[3]
            frame_length = 6 + payload_length
            if len(self._buffer) < frame_length:
                break
            candidate = bytes(self._buffer[:frame_length])
            del self._buffer[:frame_length]
            checksum = 0
            for value in candidate[3:-1]:
                checksum ^= value
            if checksum != candidate[-1]:
                continue
            frames.append(MspFrame(chr(direction_byte), candidate[4], candidate[5:-1]))
        return frames


class MspClient:
    def __init__(self, device: BinaryIO) -> None:
        self.device = device
        self.parser = MspV1Parser()

    def request(self, command: int, timeout_s: float = 0.12) -> tuple[bytes, int, int]:
        sent_monotonic_ns = time.monotonic_ns()
        self.device.write(encode_msp_v1_request(command))
        if hasattr(self.device, "flush"):
            self.device.flush()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            waiting = int(getattr(self.device, "in_waiting", 0) or 0)
            # read(256) waits for 256 bytes or the serial timeout even though an
            # MSP response is only a few dozen bytes. Read one byte while
            # waiting for the frame, then drain everything already buffered.
            chunk = self.device.read(max(1, min(256, waiting)))
            if not chunk:
                continue
            for frame in self.parser.feed(chunk):
                if frame.command != command:
                    continue
                if frame.direction == "!":
                    raise RuntimeError(f"Commande MSP {command} refusée par le contrôleur")
                if frame.direction == ">":
                    return frame.payload, sent_monotonic_ns, time.monotonic_ns()
        raise TimeoutError(f"Aucune réponse MSP {command}")


def _text(payload: bytes, maximum: int | None = None) -> str:
    selected = payload if maximum is None else payload[:maximum]
    return selected.split(b"\0", 1)[0].decode("ascii", errors="replace")


def decode_identity(responses: dict[int, bytes]) -> dict[str, object]:
    api = responses.get(MSP_API_VERSION, b"")
    version = responses.get(MSP_FC_VERSION, b"")
    variant = _text(responses.get(MSP_FC_VARIANT, b""), 4)
    board = _text(responses.get(MSP_BOARD_INFO, b""), 4)
    return {
        "type": "device",
        "source": "matek_f722_se_msp",
        "protocol": "msp_v1_readonly_polling",
        "fc_variant": variant or None,
        "fc_version": ".".join(str(value) for value in version[:3]) if len(version) >= 3 else None,
        "msp_protocol_version": api[0] if len(api) >= 1 else None,
        "msp_api_version": f"{api[1]}.{api[2]}" if len(api) >= 3 else None,
        "board_identifier": board or None,
    }


def _accel_lsb_per_g(fc_variant: str, override: float | None) -> float:
    if override is not None:
        if not math.isfinite(override) or override <= 0:
            raise ValueError("--accel-lsb-per-g doit être strictement positif")
        return override
    # INAV normalizes MSP_RAW_IMU acceleration to 512 LSB/g. Betaflight keeps
    # the MPU6000/ICM20602 16 g representation used by this board (2048 LSB/g).
    return 512.0 if fc_variant.upper() == "INAV" else 2048.0


def _rotate_flat_mount(x: float, y: float, mounting_yaw_deg: int) -> tuple[float, float]:
    """Map FC X/Y to vehicle forward/right for a flat, yaw-only mounting."""
    radians = math.radians(mounting_yaw_deg)
    cosine = round(math.cos(radians))
    sine = round(math.sin(radians))
    return cosine * x - sine * y, sine * x + cosine * y


def decode_raw_imu(
    payload: bytes,
    *,
    fc_variant: str,
    mounting_yaw_deg: int,
    accel_lsb_per_g: float | None = None,
) -> dict[str, object]:
    if len(payload) < 18:
        raise ValueError(f"MSP_RAW_IMU trop court: {len(payload)} octets")
    values = struct.unpack_from("<9h", payload)
    raw_accel = values[:3]
    raw_gyro = values[3:6]
    raw_magnetometer = values[6:9]
    scale = _accel_lsb_per_g(fc_variant, accel_lsb_per_g)
    acceleration = tuple(value / scale * STANDARD_GRAVITY_MS2 for value in raw_accel)
    forward_acceleration, right_acceleration = _rotate_flat_mount(
        acceleration[0], acceleration[1], mounting_yaw_deg
    )
    roll_rate, pitch_rate = _rotate_flat_mount(
        float(raw_gyro[0]), float(raw_gyro[1]), mounting_yaw_deg
    )
    return {
        "type": "imu",
        "source": "matek_f722_se_msp",
        "fc_variant": fc_variant or None,
        "mounting_yaw_deg": mounting_yaw_deg,
        "mounting_assumption": "flat_fc_arrow_yaw_clockwise_from_vehicle_forward",
        "raw_acceleration_xyz": list(raw_accel),
        "raw_gyroscope_xyz": list(raw_gyro),
        "raw_magnetometer_xyz": list(raw_magnetometer),
        "accel_lsb_per_g": scale,
        "acceleration_x_ms2": acceleration[0],
        "acceleration_y_ms2": acceleration[1],
        "acceleration_z_ms2": acceleration[2],
        "acceleration_forward_ms2": forward_acceleration,
        "acceleration_right_ms2": right_acceleration,
        "acceleration_vertical_sensor_ms2": acceleration[2],
        "roll_rate_deg_s": roll_rate,
        "pitch_rate_deg_s": pitch_rate,
        "yaw_rate_right_deg_s": float(raw_gyro[2]),
        "gyro_scale_note": "MSP gyroRateDps integer output",
    }


def decode_attitude(payload: bytes, mounting_yaw_deg: int) -> dict[str, object]:
    if len(payload) < 6:
        raise ValueError(f"MSP_ATTITUDE trop court: {len(payload)} octets")
    roll_raw, pitch_raw, heading_raw = struct.unpack_from("<hhh", payload)
    roll_deg, pitch_deg = _rotate_flat_mount(
        roll_raw / 10.0, pitch_raw / 10.0, mounting_yaw_deg
    )
    return {
        "type": "attitude",
        "source": "matek_f722_se_msp",
        "mounting_yaw_deg": mounting_yaw_deg,
        "roll_deg": roll_deg,
        "pitch_deg": pitch_deg,
        "heading_deg": float(heading_raw % 360),
    }


def decode_raw_gps(payload: bytes) -> dict[str, object]:
    if len(payload) < 16:
        raise ValueError(f"MSP_RAW_GPS trop court: {len(payload)} octets")
    fix_type, satellites, latitude, longitude, altitude, speed, course = struct.unpack_from(
        "<BBiiHHH", payload
    )
    pdop_raw = struct.unpack_from("<H", payload, 16)[0] if len(payload) >= 18 else None
    return {
        "type": "gps",
        "source": "matek_f722_se_msp",
        "fix_type": fix_type,
        "fix_valid": fix_type > 0,
        "satellites": satellites,
        "latitude_deg": latitude / 10_000_000.0,
        "longitude_deg": longitude / 10_000_000.0,
        "altitude_m": float(altitude),
        "speed_mps": speed / 100.0,
        "course_deg": course / 10.0,
        "pdop_raw": pdop_raw,
        "pdop": pdop_raw / 100.0 if pdop_raw is not None else None,
    }


def decode_status(payload: bytes) -> dict[str, object]:
    if len(payload) < 6:
        raise ValueError(f"MSP_STATUS trop court: {len(payload)} octets")
    cycle_time_us, i2c_errors, sensor_mask = struct.unpack_from("<HHH", payload)
    return {
        "type": "status",
        "source": "matek_f722_se_msp",
        "cycle_time_us": cycle_time_us,
        "i2c_errors": i2c_errors,
        "sensor_mask": sensor_mask,
        "accelerometer_present": bool(sensor_mask & (1 << 0)),
        "barometer_present": bool(sensor_mask & (1 << 1)),
        "magnetometer_present": bool(sensor_mask & (1 << 2)),
        "gps_present": bool(sensor_mask & (1 << 3)),
    }


def _timestamped(record: dict[str, object], sent_ns: int, received_ns: int) -> dict[str, object]:
    return {
        **record,
        "received_timestamp_us": time.time_ns() // 1000,
        "received_monotonic_ns": received_ns,
        "request_monotonic_ns": sent_ns,
        "serial_round_trip_us": round((received_ns - sent_ns) / 1000.0, 1),
    }


def _write_record(output: BinaryIO, record: dict[str, object]) -> None:
    output.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Port USB/MSP de la Matek")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imu-hz", type=float, default=50.0)
    parser.add_argument("--attitude-hz", type=float, default=20.0)
    parser.add_argument("--gps-hz", type=float, default=5.0)
    parser.add_argument(
        "--mount-yaw-deg",
        type=int,
        choices=(0, 90, 180, 270),
        default=0,
        help="Orientation horaire de la flèche FC par rapport à l'avant du véhicule",
    )
    parser.add_argument(
        "--accel-lsb-per-g",
        type=float,
        help="Échelle manuelle; utile uniquement pour un firmware MSP atypique",
    )
    args = parser.parse_args()
    if min(args.imu_hz, args.attitude_hz, args.gps_hz) <= 0:
        raise SystemExit("Les cadences MSP doivent être strictement positives")

    stop = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    counts = {"imu": 0, "attitude": 0, "gps": 0, "status": 0, "timeouts": 0, "malformed": 0}
    with serial.Serial(
        args.port,
        args.baud,
        timeout=0.015,
        write_timeout=0.1,
    ) as device, args.output.open("wb") as output:
        client = MspClient(device)
        identity_responses: dict[int, bytes] = {}
        for command in (MSP_API_VERSION, MSP_FC_VARIANT, MSP_FC_VERSION, MSP_BOARD_INFO):
            try:
                identity_responses[command] = client.request(command, timeout_s=0.5)[0]
            except TimeoutError:
                if command in (MSP_API_VERSION, MSP_FC_VARIANT):
                    raise SystemExit(
                        "La carte ne répond pas en MSP. Fermer Betaflight/iNav Configurator "
                        "et vérifier le port USB/MSP."
                    )
        identity = decode_identity(identity_responses)
        variant = str(identity.get("fc_variant") or "")
        identity.update({
            "received_timestamp_us": time.time_ns() // 1000,
            "received_monotonic_ns": time.monotonic_ns(),
            "mounting_yaw_deg": args.mount_yaw_deg,
            "accel_lsb_per_g": _accel_lsb_per_g(variant, args.accel_lsb_per_g),
            "readonly_commands": [
                MSP_API_VERSION, MSP_FC_VARIANT, MSP_FC_VERSION, MSP_BOARD_INFO,
                MSP_STATUS, MSP_RAW_IMU, MSP_RAW_GPS, MSP_ATTITUDE,
            ],
        })
        _write_record(output, identity)
        output.flush()
        print(
            f"[matek] {identity.get('fc_variant') or '?'} {identity.get('fc_version') or '?'} "
            f"sur {args.port} -> {args.output}",
            flush=True,
        )

        schedule = {
            MSP_RAW_IMU: [0.0, 1.0 / args.imu_hz],
            MSP_ATTITUDE: [0.0, 1.0 / args.attitude_hz],
            MSP_RAW_GPS: [0.0, 1.0 / args.gps_hz],
            MSP_STATUS: [0.0, 1.0],
        }
        started = time.monotonic()
        last_summary = started
        while not stop:
            now = time.monotonic()
            due = min(schedule, key=lambda command: schedule[command][0])
            due_at, period = schedule[due]
            if now - started < due_at:
                time.sleep(min(0.002, started + due_at - now))
                continue
            schedule[due][0] = max(due_at + period, now - started + period * 0.25)
            try:
                payload, sent_ns, received_ns = client.request(due)
                if due == MSP_RAW_IMU:
                    record = decode_raw_imu(
                        payload,
                        fc_variant=variant,
                        mounting_yaw_deg=args.mount_yaw_deg,
                        accel_lsb_per_g=args.accel_lsb_per_g,
                    )
                    key = "imu"
                elif due == MSP_ATTITUDE:
                    record = decode_attitude(payload, args.mount_yaw_deg)
                    key = "attitude"
                elif due == MSP_RAW_GPS:
                    record = decode_raw_gps(payload)
                    key = "gps"
                else:
                    record = decode_status(payload)
                    key = "status"
                _write_record(output, _timestamped(record, sent_ns, received_ns))
                counts[key] += 1
            except TimeoutError:
                counts["timeouts"] += 1
            except (ValueError, struct.error) as exc:
                counts["malformed"] += 1
                _write_record(output, {
                    "type": "malformed",
                    "source": "matek_f722_se_msp",
                    "received_timestamp_us": time.time_ns() // 1000,
                    "received_monotonic_ns": time.monotonic_ns(),
                    "command": due,
                    "error": str(exc),
                })

            if time.monotonic() - last_summary >= 1.0:
                output.flush()
                last_summary = time.monotonic()

        output.flush()
    print(
        "[matek] terminé: " + ", ".join(f"{key}={value}" for key, value in counts.items()),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
