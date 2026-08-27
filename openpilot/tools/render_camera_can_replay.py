#!/usr/bin/env python3
"""Render a synchronized Peugeot T9 camera/CAN recording with telemetry.

The recorder stores camera capture timestamps in ``frames.jsonl`` and ESP32
boot-relative CAN timestamps in ``can.jsonl``.  The MP4 nominal frame rate is
not a reliable synchronization source: webcams can deliver fewer frames than
requested while OpenCV still writes a constant-rate video.  This tool therefore
selects the CAN state independently for every recorded camera frame, then maps
that frame to its MP4 frame index for rendering.

This is an offline, read-only tool.  It never opens a serial port and never
transmits a CAN frame.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterator, TextIO

import cantools
from cantools.database.can import Database, Message


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DBC = REPO_ROOT / "database/psa/dbc/peugeot_308_t9_2018.dbc"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "data/runtime/camera_can_replays"


@dataclass(frozen=True)
class CameraFrame:
    index: int
    timestamp_us: int


@dataclass(frozen=True)
class CanFrame:
    timestamp_us: int
    wall_timestamp_us: int
    address: int
    data: bytes


@dataclass
class DecodeCounters:
    raw_lines: int = 0
    can_frames: int = 0
    known_frames: int = 0
    decoded_frames: int = 0
    decode_errors: int = 0


class SampleStats:
    def __init__(self) -> None:
        self.sample_count: dict[str, int] = defaultdict(int)
        self.minimum: dict[str, float] = {}
        self.maximum: dict[str, float] = {}
        self.transitions: dict[str, int] = defaultdict(int)
        self._previous: dict[str, Any] = {}

    def observe(self, state: dict[str, Any]) -> None:
        for name, value in state.items():
            if name.startswith("_") or value is None:
                continue
            self.sample_count[name] += 1
            if name in self._previous and self._previous[name] != value:
                self.transitions[name] += 1
            self._previous[name] = value
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            number = float(value)
            if not math.isfinite(number):
                continue
            self.minimum[name] = min(self.minimum.get(name, number), number)
            self.maximum[name] = max(self.maximum.get(name, number), number)

    def report(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name in sorted(self.sample_count):
            item: dict[str, Any] = {
                "sample_count": self.sample_count[name],
                "transitions": self.transitions[name],
            }
            if name in self.minimum:
                item["minimum"] = round(self.minimum[name], 6)
                item["maximum"] = round(self.maximum[name], 6)
            result[name] = item
        return result


def load_camera_frames(path: Path) -> list[CameraFrame]:
    frames: list[CameraFrame] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                frame = CameraFrame(
                    index=int(payload["frame_index"]),
                    timestamp_us=int(payload["timestamp_us"]),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path}:{line_number}: image horodatée invalide") from exc
            if frames and frame.index != frames[-1].index + 1:
                raise ValueError(
                    f"{path}:{line_number}: index image non continu "
                    f"({frames[-1].index} puis {frame.index})"
                )
            if frames and frame.timestamp_us <= frames[-1].timestamp_us:
                raise ValueError(f"{path}:{line_number}: horodatage image non croissant")
            frames.append(frame)
    if not frames:
        raise ValueError(f"Aucune image horodatée dans {path}")
    return frames


def iter_can_frames(
    path: Path,
    first_can_timestamp_us: int,
    first_can_wall_epoch: float,
    counters: DecodeCounters,
) -> Iterator[CanFrame]:
    """Yield valid compact ``F,...`` records and ignore serial startup noise."""
    first_wall_us = round(first_can_wall_epoch * 1_000_000)
    with path.open("rb") as stream:
        for raw_line in stream:
            counters.raw_lines += 1
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line.startswith("F,"):
                continue
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                timestamp_us = int(parts[1], 16)
                address = int(parts[3], 16)
                data = bytes.fromhex(parts[5])
            except ValueError:
                continue
            counters.can_frames += 1
            yield CanFrame(
                timestamp_us=timestamp_us,
                wall_timestamp_us=first_wall_us + timestamp_us - first_can_timestamp_us,
                address=address,
                data=data,
            )


def _number(values: dict[str, Any], name: str) -> float | None:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _integer(values: dict[str, Any], name: str) -> int | None:
    value = _number(values, name)
    return int(value) if value is not None else None


def _boolean(values: dict[str, Any], name: str) -> bool | None:
    value = _number(values, name)
    return bool(value) if value is not None else None


def update_state(address: int, values: dict[str, Any], state: dict[str, Any]) -> None:
    """Map the vehicle-specific DBC fields to stable overlay names."""
    if address == 0x208:
        state["engine_rpm"] = _number(values, "EngineRPM")
        state["engine_torque_nm"] = _number(values, "EngineTorqueNm")
        state["accelerator_pct"] = _number(values, "AcceleratorPositionPct")
        state["cruise_xvv_state"] = _integer(values, "CruiseStateCandidate")
        state["cruise_active"] = state["cruise_xvv_state"] == 2
    elif address == 0x228:
        state["accelerator_secondary_pct"] = _number(values, "AcceleratorPositionSecondaryPct")
    elif address == 0x2F5:
        state["driver_torque_raw"] = _integer(values, "DriverTorqueRaw")
    elif address == 0x305:
        state["steering_angle_deg"] = _number(values, "SteeringAngleDeg")
        rate = _number(values, "SteeringRateMagnitudeDegS")
        sign = _boolean(values, "SteeringRateSign")
        state["steering_rate_deg_s"] = -rate if rate is not None and sign else rate
    elif address == 0x30D:
        state["wheel_front_left_kph"] = _number(values, "WheelSpeedFrontLeftKph")
        state["wheel_front_right_kph"] = _number(values, "WheelSpeedFrontRightKph")
        state["wheel_rear_left_kph"] = _number(values, "WheelSpeedRearLeftKph")
        state["wheel_rear_right_kph"] = _number(values, "WheelSpeedRearRightKph")
    elif address == 0x329:
        state["gearbox_fault"] = _boolean(values, "GearboxFaultCandidate")
    elif address == 0x348:
        state["current_gear"] = _integer(values, "CurrentGear")
        state["esp_acknowledged"] = _boolean(values, "ESPAcknowledgedCandidate")
        state["esp_fault_state"] = _integer(values, "ESPFaultStateCandidate")
    elif address == 0x349:
        state["target_gear"] = _integer(values, "TargetGear")
    elif address == 0x34D:
        state["esp_intervention_state"] = _integer(values, "ESPInterventionStateRaw")
        state["esp_intervention"] = _boolean(values, "ESPInterventionActiveCandidate")
        state["tcs_intervention"] = _boolean(values, "TCSInterventionActiveCandidate")
        state["esp_exclusive_intervention"] = _boolean(
            values, "ESPExclusiveInterventionActiveCandidate"
        )
    elif address == 0x38D:
        state["speed_kph"] = _number(values, "VehicleSpeedKph")
        state["longitudinal_accel_ms2"] = _number(values, "LongitudinalAccelerationMs2")
    elif address == 0x3AD:
        parking_state = _integer(values, "ParkingBrakeState")
        state["parking_brake_state"] = parking_state
        state["parking_brake"] = parking_state in {1, 3} if parking_state is not None else None
    elif address == 0x3CD:
        state["brake_system_state"] = _integer(values, "BrakeSystemState")
        state["brake_pressure_raw"] = _number(values, "BrakePressureRelativeRaw")
        state["lateral_accel_ms2"] = _number(values, "LateralAccelerationMs2")
        state["yaw_rate_deg_s"] = _number(values, "YawRateDegS")
    elif address == 0x3F2:
        state["lka_unknown_byte2_raw"] = _integer(values, "LKAUnknownByte2Raw")
        state["lka_torque_command_raw"] = _integer(values, "LKATorqueCommandRaw")
        state["lka_state"] = _integer(values, "LKAState")
        state["lane_departure"] = _integer(values, "LaneDeparture")
        state["lxa_mode"] = _integer(values, "LXAMode")
        state["lka_torque_factor_raw"] = _integer(values, "LKATorqueFactorRaw")
        state["column_angle_setpoint_deg"] = _number(values, "ColumnAngleSetpointDeg")
    elif address == 0x412:
        state["reverse"] = _boolean(values, "ReverseGearActive")
        state["brake_active"] = _boolean(values, "BrakePedalActive")
        parking_brake = _boolean(values, "ParkingBrakeActive")
        state["parking_brake_body"] = parking_brake
        if parking_brake is not None:
            state["parking_brake"] = parking_brake
        state["driver_door"] = _boolean(values, "DriverDoorOpen")
        state["passenger_door"] = _boolean(values, "PassengerDoorOpen")
        state["rear_left_door"] = _boolean(values, "RearLeftDoorOpen")
        state["rear_right_door"] = _boolean(values, "RearRightDoorOpen")
    elif address == 0x452:
        state["turn_signal"] = _integer(values, "TurnSignalStatus")
        state["acc_mode"] = _integer(values, "LongitudinalRegulationType")
        state["speed_setpoint_camera_kph"] = _number(values, "SpeedSetpointKph")
        state["acc_requested"] = _boolean(values, "CruiseACCActivationRequest")
        state["limiter_requested"] = _boolean(values, "LimiterActivationRequest")
    elif address == 0x488:
        state["coolant_temperature_c"] = _number(values, "CoolantTemperatureC")
        state["idle_setpoint_rpm"] = _number(values, "IdleSetpointRPM")
        state["oil_temperature_c"] = _number(values, "OilTemperatureC")
        state["intake_air_temperature_c"] = _number(values, "IntakeAirTemperatureC")
    elif address == 0x50D:
        state["abs_intervention"] = _boolean(values, "ABSInterventionActiveCandidate")
    elif address == 0x50E:
        setpoint = _number(values, "CruiseSetpointKph")
        state["cruise_setpoint_kph"] = setpoint if setpoint is not None and setpoint < 255 else None
        state["cruise_mode"] = _integer(values, "CruiseMode")
        state["cruise_activation_request"] = _boolean(values, "CruiseActivationRequest")
    elif address == 0x572:
        state["driver_seatbelt_state"] = _integer(values, "DriverSeatbeltState")
        state["passenger_seatbelt_state"] = _integer(values, "PassengerSeatbeltState")
    elif address == 0x588:
        state["oil_pressure_switch"] = _boolean(values, "OilPressureSwitch")
        state["atmospheric_pressure_hpa"] = _number(values, "AtmosphericPressureHpa")
    elif address == 0x592:
        state["battery_charge_pct"] = _number(values, "BatteryChargePct")
        state["battery_temperature_c"] = _number(values, "BatteryTemperatureC")
        state["battery_voltage_v"] = _number(values, "BatteryVoltageV")
    elif address == 0x5B2:
        state["ambient_temperature_c"] = _number(values, "AmbientTemperatureC")
    elif address == 0x612:
        state["fuel_liters_raw"] = _number(values, "FuelLevelLitersRaw")


def decode_can_frame(
    frame: CanFrame,
    messages: dict[int, Message],
    state: dict[str, Any],
    counters: DecodeCounters,
) -> None:
    message = messages.get(frame.address)
    if message is None:
        return
    counters.known_frames += 1
    try:
        values = message.decode(frame.data, decode_choices=False, allow_truncated=False)
    except (ValueError, cantools.database.errors.DecodeError):
        counters.decode_errors += 1
        return
    counters.decoded_frames += 1
    update_state(frame.address, values, state)


def probe_video(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,nb_frames:format=duration,size",
        "-of",
        "json",
        str(path),
    ]
    try:
        payload = json.loads(subprocess.check_output(command, text=True))
        stream = payload["streams"][0]
    except (FileNotFoundError, subprocess.CalledProcessError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Impossible d'analyser la vidéo {path} avec ffprobe") from exc
    fraction = Fraction(str(stream["avg_frame_rate"]))
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": float(fraction),
        "frame_count": int(stream["nb_frames"]),
        "duration_s": float(payload["format"]["duration"]),
        "size_bytes": int(payload["format"]["size"]),
    }


def find_video(session_dir: Path) -> Path:
    preferred = session_dir / "road.mp4"
    if preferred.is_file():
        return preferred
    candidates = sorted(session_dir.glob("*.mp4"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise FileNotFoundError(f"Aucune vidéo MP4 dans {session_dir}")
    raise ValueError(f"Plusieurs vidéos dans {session_dir}; précise --video")


def ass_timestamp(centiseconds: int) -> str:
    centiseconds = max(0, centiseconds)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{fraction:02d}"


def ass_header(width: int, height: int) -> str:
    return f"""[Script Info]
Title: Peugeot 308 T9 synchronized camera CAN replay
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Speed,DejaVu Sans Mono,58,&H00FFFFFF,&H00FFFFFF,&H00101010,&H9A101010,-1,0,0,0,100,100,0,0,3,2,0,7,42,42,34,1
Style: Left,DejaVu Sans Mono,29,&H00FFFFFF,&H00FFFFFF,&H00101010,&H9A101010,0,0,0,0,100,100,0,0,3,2,0,7,42,42,112,1
Style: Right,DejaVu Sans Mono,28,&H00FFFFFF,&H00FFFFFF,&H00101010,&H9A101010,0,0,0,0,100,100,0,0,3,2,0,9,42,42,34,1
Style: Safety,DejaVu Sans Mono,27,&H00FFFFFF,&H00FFFFFF,&H00101010,&H9A101010,0,0,0,0,100,100,0,0,3,2,0,3,42,42,35,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""


WHITE = r"{\c&H00FFFFFF&}"
GREEN = r"{\c&H009AE362&}"
AMBER = r"{\c&H0060CCF2&}"
RED = r"{\c&H00656BFF&}"
CYAN = r"{\c&H00E6E663&}"


def value_text(value: Any, digits: int = 1, missing: str = "--") -> str:
    if value is None:
        return missing
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def bool_text(value: bool | None, on: str = "OUI", off: str = "NON") -> str:
    if value is None:
        return "--"
    return on if value else off


def gear_text(value: Any) -> str:
    if value is None:
        return "--"
    gear = int(value)
    if gear == 0:
        return "N"
    if gear == 9:
        return "R"
    if 1 <= gear <= 6:
        return f"D{gear}"
    return str(gear)


def transmission_text(state: dict[str, Any]) -> str:
    """Show both EAT6 channels when the engaged-gear field is unavailable.

    In this particular 2026-08-07 recording, 0x348 mostly reports zero while
    the independently decoded 0x349 target follows the actual shifts.  Keeping
    the ``T`` prefix avoids presenting a target as a measured engaged ratio.
    """
    if state.get("reverse"):
        return "R"
    current = state.get("current_gear")
    target = state.get("target_gear")
    if current is not None and 1 <= int(current) <= 6:
        return gear_text(current)
    if target is not None and 1 <= int(target) <= 6 and (state.get("speed_kph") or 0) > 0.5:
        return f"cible {int(target)}"
    return gear_text(current)


def cruise_mode_text(value: Any) -> str:
    return {0: "OFF", 1: "RVV", 2: "LVV", 3: "RESERVE"}.get(value, "--")


def cruise_state_text(value: Any) -> str:
    return {0: "INACTIF", 2: "ACTIF", 3: "TRANSITOIRE"}.get(value, "--")


def turn_signal_text(value: Any) -> str:
    return {0: "OFF", 1: "DROITE", 2: "GAUCHE", 3: "WARNING"}.get(value, "--")


def seatbelt_text(value: Any) -> str:
    return {1: "DETACHEE", 2: "BOUCLEE"}.get(value, "--" if value is None else f"ETAT {value}")


def door_text(state: dict[str, Any]) -> tuple[str, bool | None]:
    fields = (
        ("driver_door", "AVG"),
        ("passenger_door", "AVD"),
        ("rear_left_door", "ARG"),
        ("rear_right_door", "ARD"),
    )
    known = [state.get(name) for name, _label in fields]
    if not any(value is not None for value in known):
        return "--", None
    opened = [label for (name, label) in fields if state.get(name)]
    return ("OUVERTE " + "/".join(opened), True) if opened else ("FERMEES", False)


def elapsed_text(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{remainder:04.1f}"


def weighted_lka_torque_text(state: dict[str, Any]) -> str:
    torque = state.get("lka_torque_command_raw")
    factor = state.get("lka_torque_factor_raw")
    if (
        isinstance(torque, (int, float))
        and not isinstance(torque, bool)
        and isinstance(factor, (int, float))
        and not isinstance(factor, bool)
    ):
        return f"{float(torque) * float(factor) / 100.0:.1f}"
    return "--"


def overlay_blocks(state: dict[str, Any], elapsed_s: float) -> tuple[str, str, str, str]:
    speed = state.get("speed_kph")
    speed_color = GREEN if speed is not None else AMBER
    speed_block = (
        f"{speed_color}{value_text(speed, 1)} km/h{WHITE}  "
        f"{CYAN}EAT6 {transmission_text(state)}{WHITE}  "
        f"{elapsed_text(elapsed_s)}"
    )

    brake = state.get("brake_active")
    brake_color = RED if brake else GREEN
    accelerator = state.get("accelerator_pct")
    left_block = r"\N".join((
        f"Moteur       {value_text(state.get('engine_rpm'), 0)} tr/min",
        f"Accelerateur {value_text(accelerator, 1)} %",
        f"{brake_color}Frein         {bool_text(brake, 'ACTIF', 'relache')}{WHITE}",
        f"Pression     {value_text(state.get('brake_pressure_raw'), 0)} brut",
        f"Volant       {value_text(state.get('steering_angle_deg'), 1)} deg  "
        f"{value_text(state.get('steering_rate_deg_s'), 0)} deg/s",
        f"Accel. long. {value_text(state.get('longitudinal_accel_ms2'), 2)} m/s2",
    ))

    cruise_active = state.get("cruise_active")
    cruise_color = GREEN if cruise_active else WHITE
    right_block = r"\N".join((
        f"{cruise_color}RVV {cruise_mode_text(state.get('cruise_mode'))} / "
        f"{cruise_state_text(state.get('cruise_xvv_state'))}{WHITE}",
        f"Consigne     {value_text(state.get('cruise_setpoint_kph'), 0)} km/h",
        f"Clignotant   {turn_signal_text(state.get('turn_signal'))}",
        f"Demande RVV  {bool_text(state.get('cruise_activation_request'))}",
        f"LKA etat     {value_text(state.get('lka_state'), 0)}  "
        f"facteur {value_text(state.get('lka_torque_factor_raw'), 0)} %",
        f"Cmd LKA      {value_text(state.get('lka_torque_command_raw'), 0)} brut  "
        f"ponderee {weighted_lka_torque_text(state)}",
        f"Effort cond. {value_text(state.get('driver_torque_raw'), 0)} brut",
        f"Lacet        {value_text(state.get('yaw_rate_deg_s'), 1)} deg/s",
        f"ESP/ABS      {bool_text(bool(state.get('esp_intervention') or state.get('abs_intervention')), 'ACTIF', 'veille')}",
    ))

    doors, door_open = door_text(state)
    doors_color = RED if door_open else GREEN if door_open is False else AMBER
    seatbelt = state.get("driver_seatbelt_state")
    seatbelt_color = GREEN if seatbelt == 2 else RED if seatbelt == 1 else AMBER
    parking = state.get("parking_brake")
    parking_color = RED if parking else GREEN
    safety_block = r"\N".join((
        f"{doors_color}Portes {doors}{WHITE}",
        f"{seatbelt_color}Ceinture conducteur {seatbelt_text(seatbelt)}{WHITE}",
        f"{parking_color}Frein parking {bool_text(parking, 'SERRE', 'relache')}{WHITE}",
    ))
    return speed_block, left_block, right_block, safety_block


def write_dialogue(
    stream: TextIO,
    start_cs: int,
    end_cs: int,
    style: str,
    text: str,
) -> None:
    stream.write(
        f"Dialogue: 0,{ass_timestamp(start_cs)},{ass_timestamp(end_cs)},"
        f"{style},,0,0,0,,{text}\n"
    )


def render_video(
    source: Path,
    telemetry: Path,
    output: Path,
    start_frame: int,
    frame_count: int,
    width: int,
    height: int,
    fps: float,
    renderer_python: Path,
    preset: str,
    crf: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    renderer = subprocess.Popen(
        [
            str(renderer_python),
            str(Path(__file__).with_name("render_telemetry_frames.py")),
            "--video",
            str(source),
            "--telemetry",
            str(telemetry),
            "--start-frame",
            str(start_frame),
            "--frame-count",
            str(frame_count),
        ],
        stdout=subprocess.PIPE,
    )
    assert renderer.stdout is not None
    duration_s = frame_count / fps
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        "bgr24",
        "-video_size",
        f"{width}x{height}",
        "-framerate",
        f"{fps:.9f}",
        "-i",
        "pipe:0",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-frames:v",
        str(frame_count),
        "-progress",
        "pipe:1",
        "-nostats",
        str(output),
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=renderer.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError as exc:
        renderer.terminate()
        raise RuntimeError("ffmpeg est requis pour produire la vidéo annotée") from exc
    renderer.stdout.close()

    assert process.stdout is not None
    next_progress = 10
    tail: list[str] = []
    for line in process.stdout:
        line = line.strip()
        tail.append(line)
        tail = tail[-30:]
        if line.startswith("out_time_us="):
            try:
                progress = float(line.split("=", 1)[1]) / 1_000_000 / duration_s * 100
            except (ValueError, ZeroDivisionError):
                continue
            if progress >= next_progress:
                print(f"[video] encodage {min(progress, 100):.0f} %", flush=True)
                next_progress += 10
    return_code = process.wait()
    renderer_return_code = renderer.wait()
    if return_code or renderer_return_code:
        details = "\n".join(tail)
        raise RuntimeError(
            f"rendu vidéo échoué (OpenCV={renderer_return_code}, ffmpeg={return_code})\n{details}"
        )


def find_renderer_python(explicit: Path | None) -> Path:
    candidates = [
        explicit,
        REPO_ROOT.parent / "openpilot/.venv/bin/python",
        Path(sys.executable),
    ]
    checked: list[str] = []
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        checked.append(str(candidate))
        result = subprocess.run(
            [str(candidate), "-c", "import cv2"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            # Do not resolve the venv's ``python`` symlink: executing the
            # resolved base interpreter would discard the virtualenv and its
            # OpenCV installation.
            return candidate.absolute()
    raise RuntimeError(
        "Aucun Python avec OpenCV trouvé pour le rendu. Candidats: " + ", ".join(checked)
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--dbc", type=Path, default=DEFAULT_DBC)
    parser.add_argument("--video", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--subtitles", type=Path)
    parser.add_argument("--telemetry", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--renderer-python", type=Path)
    parser.add_argument("--no-render", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    session_dir = args.session_dir.resolve()
    meta_path = session_dir / "meta.json"
    can_path = session_dir / "can.jsonl"
    frames_path = session_dir / "frames.jsonl"
    for required in (meta_path, can_path, frames_path, args.dbc):
        if not required.is_file():
            raise FileNotFoundError(required)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sync_anchor = meta.get("sync_anchor") or {}
    first_can_timestamp_us = int(sync_anchor["can_first_frame_ts_us"])
    first_can_wall_epoch = float(sync_anchor["can_first_frame_wall_epoch"])

    video_path = (args.video or find_video(session_dir)).resolve()
    video_info = probe_video(video_path)
    camera_frames = load_camera_frames(frames_path)
    if video_info["frame_count"] != len(camera_frames):
        raise ValueError(
            f"La vidéo contient {video_info['frame_count']} images mais frames.jsonl "
            f"en décrit {len(camera_frames)}"
        )

    start_frame = max(0, args.start_frame)
    if start_frame >= len(camera_frames):
        raise ValueError(f"--start-frame doit être inférieur à {len(camera_frames)}")
    stop_frame = len(camera_frames)
    if args.max_frames is not None:
        if args.max_frames <= 0:
            raise ValueError("--max-frames doit être positif")
        stop_frame = min(stop_frame, start_frame + args.max_frames)
    selected_frames = camera_frames[start_frame:stop_frame]

    output_root = DEFAULT_OUTPUT_ROOT / session_dir.name
    output_root.mkdir(parents=True, exist_ok=True)
    suffix = "" if start_frame == 0 and stop_frame == len(camera_frames) else f"-{start_frame}-{stop_frame}"
    output_path = (args.output or output_root / f"{session_dir.name}-can-overlay{suffix}.mp4").resolve()
    subtitles_path = (args.subtitles or output_root / f"telemetry{suffix}.ass").resolve()
    telemetry_path = (args.telemetry or output_root / f"telemetry{suffix}.jsonl").resolve()
    report_path = (args.report or output_root / f"report{suffix}.json").resolve()
    for path in (subtitles_path, telemetry_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    database: Database = cantools.database.load_file(args.dbc, strict=False)
    messages = {message.frame_id: message for message in database.messages}
    counters = DecodeCounters()
    can_iterator = iter_can_frames(
        can_path,
        first_can_timestamp_us,
        first_can_wall_epoch,
        counters,
    )
    next_can = next(can_iterator, None)
    state: dict[str, Any] = {}
    stats = SampleStats()
    media_fps = float(video_info["fps"])
    first_camera_wall_us = camera_frames[0].timestamp_us

    print(
        f"[sync] {len(selected_frames)} images, {media_fps:.3f} i/s MP4; "
        f"horodatages caméra réels utilisés pour le CAN",
        flush=True,
    )
    with subtitles_path.open("w", encoding="utf-8") as subtitles, telemetry_path.open(
        "w", encoding="utf-8"
    ) as telemetry:
        subtitles.write(ass_header(video_info["width"], video_info["height"]))
        for output_index, frame in enumerate(selected_frames):
            while next_can is not None and next_can.wall_timestamp_us <= frame.timestamp_us:
                decode_can_frame(next_can, messages, state, counters)
                next_can = next(can_iterator, None)

            capture_elapsed_s = (frame.timestamp_us - first_camera_wall_us) / 1_000_000
            media_elapsed_s = output_index / media_fps
            snapshot = {
                "frame_index": frame.index,
                "output_frame_index": output_index,
                "wall_timestamp_us": frame.timestamp_us,
                "capture_elapsed_s": round(capture_elapsed_s, 6),
                "media_elapsed_s": round(media_elapsed_s, 6),
                **{key: value for key, value in sorted(state.items()) if not key.startswith("_")},
            }
            telemetry.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
            stats.observe(state)

            start_cs = round(output_index / media_fps * 100)
            end_cs = max(start_cs + 1, round((output_index + 1) / media_fps * 100))
            blocks = overlay_blocks(state, capture_elapsed_s)
            for style, text in zip(("Speed", "Left", "Right", "Safety"), blocks, strict=True):
                write_dialogue(subtitles, start_cs, end_cs, style, text)

    # ``next_can`` is the one-frame look-ahead just after the final selected
    # camera image.  Drain the source so the report can distinguish the full
    # capture size from the portion usable by the camera timeline.
    can_frames_through_last_image = counters.can_frames - (1 if next_can is not None else 0)
    for _remaining_frame in can_iterator:
        pass

    capture_duration_s = (
        selected_frames[-1].timestamp_us - selected_frames[0].timestamp_us
    ) / 1_000_000
    output_media_duration_s = len(selected_frames) / media_fps
    camera_meta = meta.get("camera")
    if isinstance(camera_meta, dict):
        measured_camera_fps = (
            (camera_meta.get("measured_timing") or {}).get("actual_fps")
        )
    else:
        measured_camera_fps = (
            ((meta.get("video_timing") or {}).get("road") or {}).get("measured_fps")
        )

    report = {
        "session_id": meta.get("session_id") or session_dir.name,
        "readonly": True,
        "source": {
            "session_dir": str(session_dir),
            "video": str(video_path),
            "can": str(can_path),
            "frames": str(frames_path),
            "dbc": str(args.dbc.resolve()),
        },
        "synchronization": {
            "method": "camera frame wall timestamp + ESP32 first-frame wall anchor",
            "camera_frame_count": len(camera_frames),
            "selected_start_frame": start_frame,
            "selected_stop_frame_exclusive": stop_frame,
            "selected_frame_count": len(selected_frames),
            "capture_duration_s": round(capture_duration_s, 6),
            "output_media_duration_s": round(output_media_duration_s, 6),
            "nominal_media_fps": media_fps,
            "measured_camera_fps": measured_camera_fps,
            "first_camera_to_first_can_ms": round(
                (round(first_can_wall_epoch * 1_000_000) - first_camera_wall_us) / 1000,
                3,
            ),
        },
        "video": video_info,
        "can": {
            "raw_lines_total": counters.raw_lines,
            "can_frames_total": counters.can_frames,
            "can_frames_processed_through_last_image": can_frames_through_last_image,
            "trailing_can_frames_after_last_image": counters.can_frames - can_frames_through_last_image,
            "known_frames_decoded_on_timeline": counters.known_frames,
            "decoded_frames": counters.decoded_frames,
            "decode_errors": counters.decode_errors,
        },
        "signals": stats.report(),
        "outputs": {
            "video": str(output_path) if not args.no_render or output_path.is_file() else None,
            "video_rendered_this_run": not args.no_render,
            "subtitles": str(subtitles_path),
            "telemetry": str(telemetry_path),
            "report": str(report_path),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"[can] {can_frames_through_last_image}/{counters.can_frames} trames alignées/total, "
        f"{counters.decoded_frames} décodées, "
        f"{counters.decode_errors} erreurs DBC",
        flush=True,
    )
    print(f"[data] télémétrie: {telemetry_path}", flush=True)
    print(f"[data] rapport: {report_path}", flush=True)
    if not args.no_render:
        renderer_python = find_renderer_python(args.renderer_python)
        render_video(
            source=video_path,
            telemetry=telemetry_path,
            output=output_path,
            start_frame=start_frame,
            frame_count=len(selected_frames),
            width=video_info["width"],
            height=video_info["height"],
            fps=media_fps,
            renderer_python=renderer_python,
            preset=args.preset,
            crf=args.crf,
        )
        print(f"[video] terminé: {output_path}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, KeyError, RuntimeError, ValueError) as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
