#!/usr/bin/env python3
"""Passive validator for the two-ESP32 Peugeot 308 T9 HIL bench.

The default mode never writes to either serial port and therefore cannot ask
the controller ESP32 to transmit a CAN frame.  It only checks that the vehicle
simulator's heartbeat crosses the physical CAN bus and reaches the controller.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import threading
import time

import serial


@dataclass
class HilPortState:
    port: str
    role: str | None = None
    firmware: str | None = None
    stats: list[tuple[int, int, int, int]] = field(default_factory=list)
    frame_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    malformed_lines: int = 0

    @property
    def first_stats(self) -> tuple[int, int, int, int] | None:
        return self.stats[0] if self.stats else None

    @property
    def last_stats(self) -> tuple[int, int, int, int] | None:
        return self.stats[-1] if self.stats else None

    def counter_delta(self, index: int) -> int:
        if self.first_stats is None or self.last_stats is None:
            return 0
        return max(0, self.last_stats[index] - self.first_stats[index])


def parse_hil_line(state: HilPortState, line: str) -> None:
    """Parse one ASCII line emitted by HIL firmware 1.x."""
    parts = line.strip().split(",")
    if not parts or not parts[0]:
        return

    try:
        if parts[0] == "HELLO" and len(parts) == 3:
            state.role = parts[1]
            state.firmware = parts[2]
        elif parts[0] == "STAT" and len(parts) == 5:
            state.stats.append(tuple(int(value, 10) for value in parts[1:5]))
        elif parts[0] == "F" and len(parts) == 4:
            identifier = int(parts[1], 16)
            data_length = int(parts[2], 10)
            if len(parts[3]) != data_length * 2:
                state.malformed_lines += 1
                return
            bytes.fromhex(parts[3])
            state.frame_ids.append(identifier)
        elif parts[0] == "ERR":
            state.errors.append(",".join(parts[1:]))
    except (TypeError, ValueError):
        state.malformed_lines += 1


def evaluate_passive(states: list[HilPortState]) -> dict[str, object]:
    by_role = {state.role: state for state in states if state.role}
    vehicle = by_role.get("vehicle")
    controller = by_role.get("controller")
    findings: list[str] = []

    if vehicle is None:
        findings.append("firmware vehicle non détecté")
    if controller is None:
        findings.append("firmware controller non détecté")

    vehicle_tx_delta = vehicle.counter_delta(0) if vehicle else 0
    controller_rx_delta = controller.counter_delta(1) if controller else 0
    if vehicle and vehicle_tx_delta <= 0:
        findings.append("le simulateur véhicule n'émet pas son heartbeat")
    if controller and controller_rx_delta <= 0:
        findings.append("aucun heartbeat reçu par le contrôleur")
    if any(state.errors for state in states):
        findings.append("le firmware a signalé au moins une erreur")
    if any(state.malformed_lines for state in states):
        findings.append("au moins une ligne HIL est malformée")

    return {
        "ok": not findings,
        "mode": "passive",
        "vehicle_tx_delta": vehicle_tx_delta,
        "controller_rx_delta": controller_rx_delta,
        "controller_frame_ids": (
            sorted({f"0x{identifier:03X}" for identifier in controller.frame_ids})
            if controller
            else []
        ),
        "findings": findings,
        "ports": [
            {
                "port": state.port,
                "role": state.role,
                "firmware": state.firmware,
                "first_stats": state.first_stats,
                "last_stats": state.last_stats,
                "errors": state.errors,
                "malformed_lines": state.malformed_lines,
            }
            for state in states
        ],
    }


def _read_port(port: str, baud: int, duration: float, state: HilPortState) -> None:
    with serial.Serial(port, baudrate=baud, timeout=0.1) as connection:
        # CP2102 may reset the ESP32 when the port opens. Deassert both modem
        # lines and tolerate the ROM's 115200-baud boot bytes before the HIL
        # application switches to its 921600-baud ASCII protocol.
        connection.dtr = False
        connection.rts = False
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            raw = connection.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="ignore").strip()
            if line.startswith(("HELLO,", "STAT,", "F,", "ERR,")):
                parse_hil_line(state, line)


def run_passive(vehicle_port: str, controller_port: str, baud: int, duration: float) -> dict[str, object]:
    # The command line already assigns the physical ports. Keep that assignment
    # when the CP2102 reset makes us miss the controller's one-shot HELLO line.
    states = [HilPortState(vehicle_port, role="vehicle"), HilPortState(controller_port, role="controller")]
    threads = [
        threading.Thread(target=_read_port, args=(state.port, baud, duration, state), daemon=True)
        for state in states
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(duration + 2.0)
    return evaluate_passive(states)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vehicle-port", required=True, help="port USB de l'ESP32 vehicle")
    parser.add_argument("--controller-port", required=True, help="port USB de l'ESP32 controller")
    parser.add_argument("--baud", type=int, default=921_600)
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--report", type=Path, help="écrire aussi le rapport JSON à cet emplacement")
    args = parser.parse_args()

    report = run_passive(args.vehicle_port, args.controller_port, args.baud, args.duration)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
