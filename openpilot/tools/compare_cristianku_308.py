#!/usr/bin/env python3
"""Offline replay of locally saved PSA recorder CAN through an exact opendbc tree.

Use separate processes for export and each fork: their Cap'n Proto schemas differ.
Never imports messaging/Panda, opens a device, or calls CarInterface.apply().
The optional all-on-bus0 variant changes parser bus selection only and is an
explicit counterfactual, not a vehicle configuration or a compatibility claim.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, namedtuple
import csv
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

SESSION_FILES = {"short_before": [11], "long": list(range(12, 19)), "short_after": [19]}
HEADER = struct.Struct('<QH')
FRAME = struct.Struct('<IBB')


def save_json(path, value):
  path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def packets(path):
  with gzip.open(path, 'rb') as f:
    while header := f.read(HEADER.size):
      ns, count = HEADER.unpack(header)
      frames = []
      for _ in range(count):
        address, bus, size = FRAME.unpack(f.read(FRAME.size))
        data = f.read(size)
        if len(data) != size:
          raise ValueError('Truncated neutral CAN input')
        frames.append((address, data, bus))
      yield ns, frames


def export(args):
  sys.path.insert(0, str(args.source.resolve()))
  from cereal import log
  manifest = {}
  for session, indices in SESSION_FILES.items():
    inventory = defaultdict(lambda: {'count': 0, 'lengths': Counter(), 'first_ns': None, 'last_ns': None, 'max_gap_ns': 0})
    result = {'files': [], 'batches': 0, 'can_frames': 0}
    with gzip.open(args.output / f'{session}.can.gz', 'wb', compresslevel=1) as target:
      for i in indices:
        path = args.captures / f'capture-{i:08d}.rlog'
        raw = path.read_bytes()
        entry = {'name': path.name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'tail_error': None}
        try:
          for event in log.Event.read_multiple_bytes(raw):
            if event.which() != 'can':
              continue
            if not event.valid:
              raise ValueError('Invalid CAN envelope; review before replay')
            ns = int(event.logMonoTime)
            frames = [(int(c.address), bytes(c.dat), int(c.src)) for c in event.can]
            target.write(HEADER.pack(ns, len(frames)))
            for address, data, bus in frames:
              target.write(FRAME.pack(address, bus, len(data)))
              target.write(data)
              stat = inventory[f'{bus}:0x{address:03X}']
              stat['count'] += 1
              stat['lengths'][len(data)] += 1
              if stat['first_ns'] is None:
                stat['first_ns'] = ns
              if stat['last_ns'] is not None:
                stat['max_gap_ns'] = max(stat['max_gap_ns'], ns - stat['last_ns'])
              stat['last_ns'] = ns
            result['batches'] += 1
            result['can_frames'] += len(frames)
        except Exception as exc:
          # Preserve the already audited partial tails as an explicit limitation.
          entry['tail_error'] = str(exc).splitlines()[0]
          if i not in (11, 18, 19):
            raise
        result['files'].append(entry)
    result['inventory'] = dict(sorted(inventory.items()))
    manifest[session] = result
    print(session, result['batches'], result['can_frames'], flush=True)
  save_json(args.output / 'input-manifest.json', manifest)


TRACE_FIELDS = ['ns', 't_s', 't15', 'engine_state', 'rpm', 'canValid', 'canTimeout',
                'vEgoRawKph', 'steeringAngleDeg', 'steeringRateDeg', 'steeringTorque',
                'steeringTorqueEps', 'steeringPressed', 'gasPressed', 'brakePressed',
                'parkingBrake', 'leftBlinker', 'rightBlinker', 'doorOpen',
                'seatbeltUnlatched', 'gearShifter', 'yawRate', 'cruiseAvailable',
                'cruiseEnabled', 'cruiseSpeedKph', 'nonAdaptive', 'accFaulted', 'eps_state_lka']


def replay(args):
  sys.path.insert(0, str(args.source.resolve()))
  from opendbc.car import gen_empty_fingerprint
  from opendbc.car.carlog import carlog
  from opendbc.car.car_helpers import can_fingerprint
  from opendbc.car.psa.interface import CarInterface
  from opendbc.car.psa.values import CAR

  # Missing messages are counted in the report; avoid thousands of duplicate logs.
  carlog.setLevel(50)
  data_path = args.output / f'{args.session}.can.gz'
  inventory = json.loads((args.output / 'input-manifest.json').read_text())[args.session]['inventory']
  CanData = namedtuple('CanData', 'address dat src')
  packet_iter = iter(packets(data_path))
  fingerprint_batches = 0

  def recv(wait_for_one=False):
    nonlocal fingerprint_batches
    _, frames = next(packet_iter)
    fingerprint_batches += 1
    return [[CanData(*frame) for frame in frames]]

  candidate, finger = can_fingerprint(recv)
  platform = CAR[args.platform]
  cp = CarInterface.get_params(platform, finger, [], False, False, False)
  if args.fork == 'reference':
    sp = CarInterface.get_params_sp(cp, platform, finger, [], False, False, False)
    ci = CarInterface(cp, sp)
  else:
    ci = CarInterface(cp)
  if args.all_on_bus0:
    for parser in ci.can_parsers.values():
      parser.bus = 0
  if args.adapt_observed_buses:
    from opendbc.car import Bus
    ci.can_parsers[Bus.cam].bus = 0

  name = f'{args.fork}-{args.platform}-{args.session}' + ('-all-on-bus0' if args.all_on_bus0 else '')
  if args.adapt_observed_buses:
    name += '-adapt-observed-buses'
  result = {'name': name, 'automatic_can_fingerprint': candidate, 'fingerprint_batches': fingerprint_batches,
            'forced_offline_platform': str(platform), 'all_on_bus0_counterfactual': args.all_on_bus0,
            'adapt_observed_buses_counterfactual': args.adapt_observed_buses,
            'params': {'dashcamOnly': bool(cp.dashcamOnly), 'steerControlType': str(cp.steerControlType),
                       'minSteerSpeedKph': cp.minSteerSpeed * 3.6, 'mass': cp.mass, 'wheelbase': cp.wheelbase,
                       'steerRatio': cp.steerRatio, 'openpilotLongitudinalControl': bool(cp.openpilotLongitudinalControl)},
            'samples': 0, 'valid_samples': 0, 't15_on_samples': 0, 't15_on_valid_samples': 0,
            'valid_after_10s': 0, 'samples_after_10s': 0}
  counters = defaultdict(Counter)
  ranges = {}
  accepted = Counter()
  last_stamp = {}
  first_ns = None
  t15 = engine = rpm = None
  with gzip.open(args.output / f'{name}.csv.gz', 'wt') as out:
    writer = csv.DictWriter(out, fieldnames=TRACE_FIELDS)
    writer.writeheader()
    for ns, frames in packets(data_path):
      first_ns = ns if first_ns is None else first_ns
      for address, data, bus in frames:
        if bus == 0 and len(data) == 8:
          if address == 0x348:
            t15, engine = bool(data[6] & 0x40), data[5] & 15
          elif address == 0x208:
            rpm = int.from_bytes(data[:2], 'big') / 8
      input_frames = frames
      if args.adapt_observed_buses:
        # Offline hypothesis only: keep ADAS bus 1, read camera status on bus 0,
        # and supply the bus-0 0x452 to the ADAS parser as if routed there.
        input_frames = frames + [(a, d, 1) for a, d, b in frames if b == 0 and a == 0x452]
      state = ci.update([(ns, input_frames)])
      if args.fork == 'reference':
        state, _ = state
      row = {'ns': ns, 't_s': (ns-first_ns)/1e9, 't15': t15, 'engine_state': engine, 'rpm': rpm,
             'vEgoRawKph': state.vEgoRaw * 3.6, 'gearShifter': str(state.gearShifter),
             'cruiseAvailable': bool(state.cruiseState.available), 'cruiseEnabled': bool(state.cruiseState.enabled),
             'cruiseSpeedKph': state.cruiseState.speed*3.6, 'nonAdaptive': bool(state.cruiseState.nonAdaptive),
             'eps_state_lka': getattr(ci.CS, 'eps_state_lka', None)}
      for key in TRACE_FIELDS:
        if key not in row:
          row[key] = getattr(state, key)
      writer.writerow(row)
      for key, value in row.items():
        if key not in ('ns', 't_s') and value is not None:
          if isinstance(value, bool) or key in ('gearShifter', 'engine_state', 'eps_state_lka'):
            counters[key][str(value)] += 1
          elif isinstance(value, (float, int)):
            lo, hi = ranges.get(key, (value, value))
            ranges[key] = (min(lo, value), max(hi, value))
      result['samples'] += 1
      result['valid_samples'] += bool(state.canValid)
      if t15:
        result['t15_on_samples'] += 1
        result['t15_on_valid_samples'] += bool(state.canValid)
      if ns-first_ns >= 10_000_000_000:
        result['samples_after_10s'] += 1
        result['valid_after_10s'] += bool(state.canValid)
      for bus_name, parser in ci.can_parsers.items():
        for address, st in parser.message_states.items():
          key = f'{bus_name}:{parser.bus}:0x{address:03X}'
          stamp = st.timestamps[-1] if st.timestamps else 0
          if stamp and stamp != last_stamp.get(key):
            accepted[key] += 1
          last_stamp[key] = stamp
      if result['samples'] % 30000 == 0:
        print(name, result['samples'], 'updates', round(row['t_s'], 1), 's', flush=True)

  result['ranges'] = ranges
  result['state_samples'] = dict(counters)
  result['messages'] = []
  for bus_name, parser in ci.can_parsers.items():
    for address, st in parser.message_states.items():
      input_bus = 0 if args.adapt_observed_buses and parser.bus == 1 and address == 0x452 else parser.bus
      observed = inventory.get(f'{input_bus}:0x{address:03X}', {})
      result['messages'].append({'parser': str(bus_name), 'bus': parser.bus, 'address': f'0x{address:03X}',
                                 'name': st.name, 'required': not st.ignore_alive, 'dbc_size': st.size,
                                 'recorded_input_bus': input_bus,
                                 'raw_frames': observed.get('count', 0), 'lengths': observed.get('lengths', {}),
                                 'decoded_batches': accepted[f'{bus_name}:{parser.bus}:0x{address:03X}'],
                                 'learned_frequency_hz': st.frequency,
                                 'counter_fail_at_end': st.counter_fail,
                                 'last_good_t_s': (st.timestamps[-1]-first_ns)/1e9 if st.timestamps else None,
                                 'present_on_buses': [b for b in range(3) if f'{b}:0x{address:03X}' in inventory]})
  save_json(args.output / f'{name}.json', result)
  print(name, 'done', result['valid_samples'], '/', result['samples'], 'canValid', flush=True)


def safety(args):
  """Run reference C receive checks and ignition hook, never the TX hook."""
  sys.path.insert(0, str(args.source.resolve()))
  from opendbc.safety.tests.libsafety import libsafety_py as lib
  from opendbc.car.structs import CarParams
  shared = args.output / 'reference-safety.so'
  if not shared.exists():
    subprocess.run(['cc', '-shared', '-fPIC', '-std=gnu11', '-O1', '-DALLOW_DEBUG',
                    '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    '-I', str(args.source.resolve()), str(Path(__file__).with_suffix('').with_name('compare_cristianku_308_safety.c')),
                    '-o', str(shared)], check=True)
  lib.ffi.cdef('''
    unsigned int audit_rx_len(void);
    unsigned int audit_rx_field(unsigned int, unsigned int);
    unsigned int audit_received_checksum(const CANPacket_t *);
    unsigned int audit_computed_checksum(const CANPacket_t *);
    unsigned int audit_counter(const CANPacket_t *);
  ''')
  lib.load(shared.resolve())
  so = lib.libsafety
  assert so.set_safety_hooks(CarParams.SafetyModel.psa, args.safety_param) == 0
  so.init_tests()
  checksum_ids = {0x305, 0x452, 0x38D, 0x2F5, 0x2B6, 0x2F6, 0x42D}
  counts = defaultdict(Counter)
  seen_counter = {}
  result = {'session': args.session, 'safety_param': args.safety_param,
            'rx_rejected': Counter(), 'safety_valid_batches': 0, 'batches': 0,
            'ignition_edges': [], 'ignition_t15_mismatch_batches': 0,
            'ignition_false_stopstart_batches': 0, 'stopstart_batches': 0,
            'ignition_t15_mismatch_s': 0.0, 'ignition_false_stopstart_s': 0.0}
  first_ns = previous_ns = None
  previous_comparison = None
  last_ignition = False
  t15 = engine = None
  last_tick = -1
  for ns, frames in packets(args.output / f'{args.session}.can.gz'):
    first_ns = ns if first_ns is None else first_ns
    elapsed = ns-first_ns
    so.set_timer((elapsed // 1000) & 0xFFFFFFFF)
    for address, data, bus in frames:
      if bus >= 3:
        continue
      p = lib.make_CANPacket(address, bus, data)
      if not so.safety_rx_hook(p):
        result['rx_rejected'][f'{bus}:0x{address:03X}'] += 1
      so.ignition_can_hook(p)
      ignition = bool(so.get_ignition_can())
      if ignition != last_ignition:
        result['ignition_edges'].append({'t_s': elapsed/1e9, 'value': ignition, 'trigger': f'{bus}:0x{address:03X}'})
        last_ignition = ignition
      if bus == 0 and address == 0x348 and len(data) == 8:
        t15, engine = bool(data[6] & 0x40), data[5] & 15
      if address in checksum_ids:
        key = f'{bus}:0x{address:03X}'
        counts[key]['frames'] += 1
        counts[key]['checksum_ok'] += so.audit_received_checksum(p) == so.audit_computed_checksum(p)
        counter = so.audit_counter(p)
        if key in seen_counter:
          counts[key]['counter_pairs'] += 1
          counts[key]['counter_consecutive'] += counter == (seen_counter[key]+1) % 16
        seen_counter[key] = counter
    if elapsed // 1_000_000_000 != last_tick:
      so.safety_tick_current_safety_config()
      last_tick = elapsed // 1_000_000_000
    result['batches'] += 1
    result['safety_valid_batches'] += bool(so.safety_config_valid())
    ignition = bool(so.get_ignition_can())
    comparison = (t15 is not None and ignition != t15, engine in (4, 5) and not ignition)
    result['ignition_t15_mismatch_batches'] += comparison[0]
    result['stopstart_batches'] += engine in (4, 5)
    result['ignition_false_stopstart_batches'] += comparison[1]
    if previous_ns is not None:
      dt = (ns-previous_ns)/1e9
      result['ignition_t15_mismatch_s'] += dt * previous_comparison[0]
      result['ignition_false_stopstart_s'] += dt * previous_comparison[1]
    previous_ns, previous_comparison = ns, comparison
  result['checksums'] = dict(counts)
  fields = ['address','bus','length','frequency_hz','seen','lagging_at_end','checksum_valid_at_end','wrong_counters_at_end']
  result['rx_checks_end'] = [{k: int(so.audit_rx_field(i, j)) for j,k in enumerate(fields)} for i in range(so.audit_rx_len())]
  result['relay_malfunction_at_end'] = bool(so.get_relay_malfunction())
  result['note'] = ('Receive-side replay only; controller transmit hook never called. Firmware ignition hook replayed at CAN receipt times; '
                    'outer firmware timeout not simulated. End-of-session lag can reflect contact off.')
  save_json(args.output / f'safety-{args.session}-param{args.safety_param}.json', result)
  print('safety',args.session,args.safety_param,'valid',result['safety_valid_batches'],'/',result['batches'],flush=True)


def signals(args):
  """Inspect selected raw fields with the reference DBC; no validity claim."""
  sys.path.insert(0, str(args.source.resolve()))
  from opendbc.can.dbc import DBC
  from opendbc.can.parser import get_raw_value
  dbc = DBC('psa_aee2010_r3')
  selected = {
    0x452: ['LONGITUDINAL_REGULATION_TYPE','SPEED_SETPOINT','RVV_ACC_ACTIVATION_REQ','COUNTER','CHECKSUM'],
    0x3F2: ['DRIVE','STATUS','LXA_ACTIVATION','TORQUE_FACTOR','TORQUE','SET_ANGLE','unknown2'],
    0x495: ['EPS_STATE_LKA','EPS_TORQUE','TRQ_LIMIT_STATE','STEERWHL_HOLD_BY_DRV'],
    0x348: ['P152_Gearbx_stGear'],
  }
  stats = defaultdict(lambda: {'frames': 0, 'fields': defaultdict(Counter), 'first_examples': []})
  for ns, frames in packets(args.output / f'{args.session}.can.gz'):
    for address, data, bus in frames:
      if address not in selected or bus >= 3:
        continue
      stat = stats[f'{bus}:0x{address:03X}']
      stat['frames'] += 1
      if len(stat['first_examples']) < 3:
        stat['first_examples'].append({'ns': ns, 'hex': data.hex()})
      for name in selected[address]:
        sig = dbc.addr_to_msg[address].sigs[name]
        raw = get_raw_value(data, sig)
        if sig.is_signed and raw & (1 << (sig.size-1)):
          raw -= 1 << sig.size
        stat['fields'][name][str(raw*sig.factor+sig.offset)] += 1
  save_json(args.output / f'raw-reference-fields-{args.session}.json', dict(stats))


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('phase', choices=['export', 'replay', 'safety', 'signals'])
  parser.add_argument('--source', type=Path, required=True, help='openpilot root for export, opendbc package parent for replay')
  parser.add_argument('--captures', type=Path)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--session', choices=SESSION_FILES)
  parser.add_argument('--fork', choices=['reference', 'installed'])
  parser.add_argument('--platform', default='PSA_PEUGEOT_3008')
  parser.add_argument('--all-on-bus0', action='store_true')
  parser.add_argument('--adapt-observed-buses', action='store_true')
  parser.add_argument('--safety-param', type=int, choices=[0, 1], default=0)
  args = parser.parse_args()
  args.output.mkdir(parents=True, exist_ok=True)
  if args.phase == 'export':
    export(args)
  elif args.phase == 'safety':
    safety(args)
  elif args.phase == 'signals':
    signals(args)
  else:
    replay(args)


if __name__ == '__main__':
  main()
