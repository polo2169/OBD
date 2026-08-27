#!/usr/bin/env python3
"""Draw camera/CAN telemetry on video frames and emit raw BGR frames.

This helper intentionally depends only on OpenCV.  The main replay tool runs in
the backend environment (which owns cantools) and pipes this helper's raw frames
to the system ffmpeg encoder.  Keeping stdout binary-only is essential.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Iterator

import cv2 as cv


WHITE = (245, 245, 245)
GREEN = (154, 227, 98)
AMBER = (96, 204, 242)
RED = (101, 107, 255)
CYAN = (230, 230, 99)
PANEL = (15, 18, 20)


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
    if state.get("reverse"):
        return "R"
    current = state.get("current_gear")
    target = state.get("target_gear")
    if current is not None and 1 <= int(current) <= 6:
        return gear_text(current)
    if target is not None and 1 <= int(target) <= 6 and (state.get("speed_kph") or 0) > 0.5:
        return f"cible {int(target)}"
    return gear_text(current)


def elapsed_text(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{remainder:04.1f}"


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
    opened = [label for name, label in fields if state.get(name)]
    return ("OUVERTE " + "/".join(opened), True) if opened else ("FERMEES", False)


def seatbelt_text(value: Any) -> str:
    return {1: "DETACHEE", 2: "BOUCLEE"}.get(value, "--" if value is None else f"ETAT {value}")


def cruise_mode_text(value: Any) -> str:
    return {0: "OFF", 1: "RVV", 2: "LVV", 3: "RESERVE"}.get(value, "--")


def cruise_state_text(value: Any) -> str:
    return {0: "INACTIF", 2: "ACTIF", 3: "TRANSITOIRE"}.get(value, "--")


def panel(frame: Any, x: int, y: int, width: int, height: int, alpha: float = 0.72) -> None:
    x2 = min(frame.shape[1], x + width)
    y2 = min(frame.shape[0], y + height)
    region = frame[y:y2, x:x2]
    if region.size == 0:
        return
    background = region.copy()
    background[:] = PANEL
    cv.addWeighted(background, alpha, region, 1 - alpha, 0, region)


def text(
    frame: Any,
    value: str,
    x: int,
    y: int,
    scale: float = 0.78,
    color: tuple[int, int, int] = WHITE,
    thickness: int = 2,
) -> None:
    cv.putText(frame, value, (x, y), cv.FONT_HERSHEY_DUPLEX, scale, (0, 0, 0), thickness + 3, cv.LINE_AA)
    cv.putText(frame, value, (x, y), cv.FONT_HERSHEY_DUPLEX, scale, color, thickness, cv.LINE_AA)


def draw_overlay(frame: Any, state: dict[str, Any]) -> None:
    height, width = frame.shape[:2]
    margin = 28
    left_y = 126

    # Keep the top-left openpilot perception banner visible when this renderer
    # is used as the second pass of a combined perception + CAN overlay.
    panel(frame, margin, left_y, 650, 285)
    speed = state.get("speed_kph")
    text(
        frame,
        f"{value_text(speed, 1)} km/h",
        margin + 20,
        left_y + 65,
        1.55,
        GREEN if speed is not None else AMBER,
        3,
    )
    text(frame, f"EAT6 {transmission_text(state)}", margin + 390, left_y + 62, 0.82, CYAN, 2)
    text(frame, elapsed_text(float(state.get("capture_elapsed_s") or 0)), margin + 20, left_y + 96, 0.55)

    brake = state.get("brake_active")
    lines = (
        (f"Moteur       {value_text(state.get('engine_rpm'), 0)} tr/min", WHITE),
        (f"Accelerateur {value_text(state.get('accelerator_pct'), 1)} %", GREEN),
        (f"Frein        {bool_text(brake, 'ACTIF', 'relache')}", RED if brake else GREEN),
        (f"Pression     {value_text(state.get('brake_pressure_raw'), 0)} brut", WHITE),
        (
            f"Volant       {value_text(state.get('steering_angle_deg'), 1)} deg  "
            f"{value_text(state.get('steering_rate_deg_s'), 0)} deg/s",
            WHITE,
        ),
        (f"Accel. long. {value_text(state.get('longitudinal_accel_ms2'), 2)} m/s2", WHITE),
    )
    for row, (label, color) in enumerate(lines):
        text(frame, label, margin + 20, left_y + 128 + row * 27, 0.63, color, 1)

    right_width = 620
    right_x = width - margin - right_width
    panel(frame, right_x, margin, right_width, 295)
    cruise_active = state.get("cruise_active")
    lka_torque = state.get("lka_torque_command_raw")
    lka_factor = state.get("lka_torque_factor_raw")
    weighted_lka_torque = (
        float(lka_torque) * float(lka_factor) / 100.0
        if (
            isinstance(lka_torque, (int, float))
            and not isinstance(lka_torque, bool)
            and isinstance(lka_factor, (int, float))
            and not isinstance(lka_factor, bool)
        )
        else None
    )
    right_lines = (
        (
            f"RVV {cruise_mode_text(state.get('cruise_mode'))} / "
            f"{cruise_state_text(state.get('cruise_xvv_state'))}",
            GREEN if cruise_active else WHITE,
        ),
        (f"Consigne     {value_text(state.get('cruise_setpoint_kph'), 0)} km/h", WHITE),
        (f"Demande RVV  {bool_text(state.get('cruise_activation_request'))}", WHITE),
        (
            f"LKA etat     {value_text(state.get('lka_state'), 0)}  "
            f"facteur {value_text(lka_factor, 0)} %",
            WHITE,
        ),
        (
            f"Cmd LKA      {value_text(lka_torque, 0)} brut  "
            f"ponderee {value_text(weighted_lka_torque, 1)}",
            WHITE,
        ),
        (f"Effort cond. {value_text(state.get('driver_torque_raw'), 0)} brut", WHITE),
        (f"Lacet        {value_text(state.get('yaw_rate_deg_s'), 1)} deg/s", WHITE),
        (
            f"ESP / ABS    {bool_text(bool(state.get('esp_intervention') or state.get('abs_intervention')), 'ACTIF', 'veille')}",
            AMBER if state.get("esp_intervention") or state.get("abs_intervention") else GREEN,
        ),
    )
    for row, (label, color) in enumerate(right_lines):
        text(frame, label, right_x + 20, margin + 38 + row * 30, 0.65, color, 1)

    doors, door_open = door_text(state)
    seatbelt = state.get("driver_seatbelt_state")
    parking = state.get("parking_brake")
    safety_lines = (
        (f"Portes {doors}", RED if door_open else GREEN if door_open is False else AMBER),
        (
            f"Ceinture conducteur {seatbelt_text(seatbelt)}",
            GREEN if seatbelt == 2 else RED if seatbelt == 1 else AMBER,
        ),
        (f"Frein parking {bool_text(parking, 'SERRE', 'relache')}", RED if parking else GREEN),
    )
    safety_height = 120
    safety_y = height - margin - safety_height
    panel(frame, right_x, safety_y, right_width, safety_height)
    for row, (label, color) in enumerate(safety_lines):
        text(frame, label, right_x + 20, safety_y + 33 + row * 34, 0.66, color, 1)


def iter_telemetry(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: télémétrie JSON invalide") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--telemetry", type=Path, required=True)
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--frame-count", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    capture = cv.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"Impossible d'ouvrir {args.video}")
    if args.start_frame:
        capture.set(cv.CAP_PROP_POS_FRAMES, args.start_frame)

    output = sys.stdout.buffer
    next_progress = 10
    written = 0
    for state in iter_telemetry(args.telemetry):
        if written >= args.frame_count:
            break
        ok, frame = capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"Lecture vidéo interrompue à l'image {args.start_frame + written}")
        draw_overlay(frame, state)
        try:
            output.write(frame.tobytes())
        except BrokenPipeError:
            return 1
        written += 1
        progress = written / args.frame_count * 100
        if progress >= next_progress:
            print(f"[frames] dessin {progress:.0f} %", file=sys.stderr, flush=True)
            next_progress += 10
    capture.release()
    if written != args.frame_count:
        raise RuntimeError(f"{written} images rendues sur {args.frame_count} attendues")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"Erreur rendu: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
