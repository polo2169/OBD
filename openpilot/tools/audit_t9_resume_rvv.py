#!/usr/bin/env python3
"""Study manual release and stock RVV deactivation in local, full rlogs.

No transport or actuator path. Resume windows are counterfactual observations,
not evidence of an EPS re-engagement or of a physical cruise cancellation.
"""
import argparse
from collections import Counter, deque
import hashlib
import json
import math
from pathlib import Path
import sys


FRESH_NS = 250_000_000
RELEASE_NS = 300_000_000  # Existing ESP32 MADS bench policy, not vehicle validation.
WINDOW_NS = 2_000_000_000


def parity(value):
    return ((value >> 4).bit_count() % 2) * 2 + (value & 15).bit_count() % 2


class Audit:
    def __init__(self):
        self.frames = {}
        self.history = deque()
        self.engine = None
        self.engine_ns = 0
        self.offs = []
        self.pending = []
        self.cuts = []
        self.current_cut = None
        self.stable_since = {}
        self.last_car_ns = 0
        self.previous_lateral_reason = None
        self.counts = Counter()

    def gap(self):
        self.frames.clear()
        self.history.clear()
        self.engine = None
        self.engine_ns = self.last_car_ns = 0
        self.pending.clear()
        self.current_cut = None
        self.stable_since.clear()
        self.previous_lateral_reason = None

    def frame(self, now, address, data, bus):
        # Keep each physical source on the side established for this harness.
        sources = {0x208: (0, 8), 0x228: (0, 8), 0x412: (2, 8),
                   0x452: (2, 6), 0x50E: (2, 8), 0x495: (0, 4), 0x3F2: (2, 8)}
        if address not in sources or sources[address][0] != bus:
            return
        if len(data) != sources[address][1]:
            self.frames.pop(address, None)
            self.counts['invalid_dlc'] += 1
            if address == 0x208:
                self.engine = None
            return
        if address == 0x50E and ((data[0] >> 4) & 3) != parity(data[6]):
            self.frames.pop(address, None)
            self.counts['invalid_50e_parity'] += 1
            return
        if address == 0x228 and (sum((b >> 4) + (b & 15) for b in data) % 16 != 3 or data[2] > 200):
            self.frames.pop(address, None)
            self.counts['invalid_pedal'] += 1
            return
        self.frames[address] = (now, bytes(data))
        self.counts[f'0x{address:X}/bus{bus}'] += 1
        if address not in (0x208, 0x228, 0x412, 0x452, 0x50E):
            return
        row = {'ns': now, 'address': hex(address), 'bus': bus, 'data_hex': data.hex()}
        if address == 0x50E:
            row.update(setpoint_kph=data[6], mode=(data[7] >> 5) & 3,
                       bit7=bool(data[7] & 128), counter=data[7] & 15)
        elif address == 0x208:
            row['engine_cruise_state'] = (data[4] >> 2) & 3
        elif address == 0x228:
            row['pedal_pct'] = data[2] / 2
        elif address == 0x412:
            row['brake'] = bool(data[0] & 32)
        self.pending = [edge for edge in self.pending if now <= edge['ns'] + WINDOW_NS]
        for edge in self.pending:
            edge['frames'].append(row)
        self.history.append(row)
        while self.history and now - self.history[0]['ns'] > WINDOW_NS:
            self.history.popleft()
        if address == 0x208:
            current = row['engine_cruise_state']
            if self.engine == 2 and current != 2 and 0 < now - self.engine_ns <= FRESH_NS:
                edge = {'ns': now, 'from': 2, 'to': current, 'frames': list(self.history)}
                self.offs.append(edge)
                self.pending.append(edge)
            self.engine, self.engine_ns = current, now

    def cut(self, now):
        if self.current_cut is not None:
            self.current_cut['next_recorded_cut_ns'] = now
        self.current_cut = {'cut_ns': now, 'first_eligible_ns': {'110': None, '130': None},
                            'blockers': Counter(), 'physical_rvv_off_ns': None}
        self.cuts.append(self.current_cut)
        self.stable_since.clear()

    def recent(self, address, now, age=FRESH_NS):
        sample, data = self.frames.get(address, (0, None))
        return data if 0 < sample <= now and now - sample <= age else None

    def car(self, now, state):
        if self.current_cut is None:
            return
        if self.last_car_ns and not 0 < now - self.last_car_ns <= FRESH_NS:
            self.stable_since.clear()
        self.last_car_ns = now
        engine = self.recent(0x208, now)
        rvv = self.recent(0x50E, now)
        off_confirmed = (engine is not None and ((engine[4] >> 2) & 3) in (0, 3)
                         and rvv is not None and ((rvv[7] >> 5) & 3) == 1
                         and not (rvv[7] & 128) and rvv[6] == 255)
        if not state['cruise_active'] and state['valid'] and off_confirmed:
            self.current_cut['physical_rvv_off_ns'] = now
            self.current_cut = None
            self.stable_since.clear()
            return
        eps = self.recent(0x495, now)
        stock = self.recent(0x3F2, now, 150_000_000)
        common = []
        if not state['cruise_active']:
            common.append('rvv_not_active')
        if not state['valid']:
            common.append('vehicle_data_invalid')
        if not all(math.isfinite(state[name]) for name in ('driver_raw', 'speed_kph')):
            common.append('nonfinite_vehicle_input')
        if abs(state['driver_raw']) > 5 or state['steering_pressed']:
            common.append('driver_still_overriding')
        if state['brake'] or state['gas'] or not state['vehicle_ready']:
            common.append('pedal_or_vehicle_inhibition')
        if eps is None or ((eps[2] >> 2) & 7) not in (1, 2):
            common.append('eps_not_fresh_and_released')
        if stock is None or ((stock[4] >> 2) & 7) not in (3, 4):
            common.append('stock_lka_not_fresh_and_authorized')
        for maximum in (110, 130):
            key = str(maximum)
            blockers = common + ([] if 67.1 <= state['speed_kph'] <= maximum else ['speed_outside_envelope'])
            self.current_cut['blockers'].update(f'{key}:{reason}' for reason in blockers)
            if blockers:
                self.stable_since.pop(key, None)
            else:
                self.stable_since.setdefault(key, now)
                if now - self.stable_since[key] >= RELEASE_NS and self.current_cut['first_eligible_ns'][key] is None:
                    self.current_cut['first_eligible_ns'][key] = now


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', type=Path, required=True)
    parser.add_argument('--logs', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import capnp
    import zstandard
    sys.path.insert(0, str(args.schema.resolve()))
    from cereal import log

    audit = Audit()
    sources, partial = [], []
    boots = set()
    previous_segment = None
    route = None
    for path in args.logs:
        if path.name != 'rlog.zst' or not path.is_file():
            parser.error('Only existing full rlog.zst files are accepted')
        current_route, number = path.parent.name.rsplit('--', 1)
        number = int(number)
        if route is not None and current_route != route:
            parser.error('Use one route per report')
        if previous_segment is not None and number <= previous_segment:
            parser.error('Segments must be in increasing order')
        if previous_segment is None or number != previous_segment + 1:
            audit.gap()
        route, previous_segment = current_route, number
        sources.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        with path.open('rb') as stream:
            raw = zstandard.ZstdDecompressor().stream_reader(stream).read()
        events = []
        try:
            for event in log.Event.read_multiple_bytes(raw):
                if event.which() in ('initData', 'can', 'carState', 'logMessage'):
                    events.append(event)
        except capnp.KjException as exc:
            partial.append({'path': str(path), 'error': str(exc).splitlines()[0]})
        events.sort(key=lambda e: int(e.logMonoTime))
        for event in events:
            now, kind = int(event.logMonoTime), event.which()
            if kind == 'initData':
                boot = str(event.initData.bootlogId)
                if boot:
                    boots.add(boot)
                if len(boots) > 1:
                    raise RuntimeError('Cannot combine boots')
            elif kind == 'can' and event.valid:
                for frame in event.can:
                    audit.frame(now, int(frame.address), bytes(frame.dat), int(frame.src))
            elif kind == 'carState':
                s = event.carState
                audit.car(now, {'valid': bool(event.valid and s.canValid and not s.canTimeout),
                    'cruise_active': bool(s.cruiseState.enabled), 'speed_kph': float(s.vEgoRaw) * 3.6,
                    'driver_raw': float(s.steeringTorque), 'steering_pressed': bool(s.steeringPressed),
                    'brake': bool(s.brakePressed), 'gas': bool(s.gasPressed),
                    'vehicle_ready': str(s.gearShifter) == 'drive' and not s.parkingBrake and not s.doorOpen
                                     and not s.seatbeltUnlatched and not s.steerFaultPermanent})
            elif kind == 'logMessage':
                try:
                    outer = json.loads(event.logMessage)
                    msg = outer.get('msg', outer.get('msg$s', ''))
                    if isinstance(msg, str) and msg.startswith('psa_t9_lateral '):
                        snapshot = json.loads(msg[len('psa_t9_lateral '):])
                        if snapshot.get('reason') == 'driver_override' and audit.previous_lateral_reason != 'driver_override':
                            audit.cut(now)
                        audit.previous_lateral_reason = snapshot.get('reason')
                except (ValueError, TypeError, AttributeError):
                    pass
        if partial and partial[-1]['path'] == str(path):
            audit.gap()
        print(f'Audited {path.parent.name}', flush=True)
    result = {'method': 'offline_observation_only', 'route': route, 'sources': sources,
        'partial_tails': partial, 'boot_ids': sorted(boots), 'counts': audit.counts,
        'manual_takeover_windows': audit.cuts, 'engine_rvv_state_exits': audit.offs,
        'release_dwell_ms': RELEASE_NS // 1_000_000, 'counterfactual_speed_caps_kph': [110, 130],
        'can_frames_emitted': 0, 'deployed': False, 'physical_cancellation_validated': False,
        'limitations': ['Eligibility is not an EPS re-engagement or permission to actuate.',
                       'Recorded soft steering faults are not treated as physical EPS faults; fresh EPS is checked separately.',
                       'CAN temporal correlations do not prove a cancellation command or power-loss behavior.',
                       'Missing segments reset history; trailing cancellation windows may be incomplete.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'manual_takeovers': len(audit.cuts), 'engine_state_exits': len(audit.offs),
        'eligible_windows': {cap: sum(c['first_eligible_ns'][cap] is not None for c in audit.cuts) for cap in ('110', '130')}}))


if __name__ == '__main__':
    main()
