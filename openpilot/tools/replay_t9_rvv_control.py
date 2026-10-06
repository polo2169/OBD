#!/usr/bin/env python3
"""Replay local full rlogs through RVV vision planning and frame preparation.

No network, messaging subscription or CAN transport. The request to evaluate
following is SYNTHETIC while the recorded stock RVV is active. This is an
open-loop replay: the recorded trajectory cannot react to our proposals.
"""
import argparse
from collections import Counter
from dataclasses import asdict
import gzip
import hashlib
import json
from pathlib import Path
import sys

import capnp
import zstandard


def sha(path):
  with path.open('rb') as stream:
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--schema', type=Path, required=True, help='Local openpilot checkout containing cereal')
  parser.add_argument('--opendbc', type=Path, required=True, help='Local staged opendbc with the RVV integration')
  parser.add_argument('--logs', type=Path, nargs='+', required=True, help='Full rlogs, in chronological segment order, ONE boot only')
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  source_hashes = {name: sha(args.opendbc/'opendbc/car/psa'/name) for name in ('rvv.py', 'rvv_control.py', 'rvv_following.py')}
  sys.path[:0] = [str(args.opendbc.resolve()), str(args.schema.resolve())]
  from cereal import log
  from opendbc.car.psa.rvv import RvvInputs
  from opendbc.car.psa.rvv_control import T9RvvControl, decode_stock
  from opendbc.car.psa.rvv_following import RvvLead, T9RvvFollowing
  from opendbc.car.psa.lka import fresh

  for path in args.logs:
    if not path.is_file() or path.name != 'rlog.zst':
      parser.error('Use existing full rlog.zst files, not sampled qlogs')
  args.output.mkdir(parents=True, exist_ok=True)
  control, planner = T9RvvControl(), T9RvvFollowing()
  car = None
  car_ns = calibration_ns = pedal_ns = 0
  calibrated = False
  pedal_pressed = True
  observation = RvvLead()
  counters, reasons, host_reasons, parity, buses = (Counter() for _ in range(5))
  last_trace = 0
  trace_key = None
  sources, tails, windows, physical_frames = [], [], [], []
  boot_ids = set()
  # CAN sources needed by the existing RVV inputs; no inferred engine-demand pedal.
  safety_rx = {address: 0 for address in (0x208, 0x228, 0x2F5, 0x305, 0x3CD, 0x30D, 0x348, 0x412, 0x3AD, 0x572)}
  latest_clock = 0
  last_following_target = last_candidate = None

  with gzip.open(args.output/'decisions.jsonl.gz', 'wt') as trace:
    for path in args.logs:
      sources.append({'path': str(path), 'sha256': sha(path)})
      with path.open('rb') as stream:
        raw = zstandard.ZstdDecompressor().stream_reader(stream).read()
      # rlogs interleave publishers: sort selected events by monotonic time,
      # never interpret disk arrival order as a controller clock reversal.
      events = []
      try:
        for event in log.Event.read_multiple_bytes(raw):
          if event.which() in ('initData', 'can', 'pandaStates', 'carState', 'radarState', 'liveCalibration', 'carControl'):
            events.append(event)
      except capnp.KjException as exc:
        tails.append({'path': str(path), 'error': str(exc).splitlines()[0]})
      events.sort(key=lambda e: int(e.logMonoTime))
      for event in events:
        now = int(event.logMonoTime)
        kind = event.which()
        if kind == 'initData':
          boot = str(event.initData.bootlogId)
          if boot:
            boot_ids.add(boot)
          if len(boot_ids) > 1:
            raise RuntimeError('Cannot combine different boots in one replay')
        elif kind == 'pandaStates':
          for panda in event.pandaStates:
            key = (str(panda.safetyModel), int(panda.safetyParam))
            if not windows or windows[-1]['key'] != key:
              windows.append({'key': key, 'first_ns': now, 'last_ns': now})
            else:
              windows[-1]['last_ns'] = now
        elif kind == 'can':
          if not event.valid:
            counters['invalid_can_envelopes'] += 1
            continue
          frames = [(int(f.address), bytes(f.dat), int(f.src)) for f in event.can]
          control.observe([(now, frames)])
          for address, data, bus in frames:
            if address in (0x50E, 0x208):
              buses[f'0x{address:X}/bus{bus}'] += 1
              physical_frames.append((now, address, bus))
            if bus not in (0, 2):
              continue
            if address in safety_rx:
              safety_rx[address] = now
            if address == 0x228:
              valid = len(data) == 8 and sum((b >> 4) + (b & 15) for b in data) % 16 == 3 and data[2] <= 200
              pedal_ns = now if valid else 0
              pedal_pressed = not valid or data[2] > 0
            if address == 0x50E:
              try:
                stock = decode_stock(data)
                parity['valid'] += 1
                parity['rvv_selected_and_activation_bit'] += stock.mode == 1 and stock.activation
              except ValueError:
                parity['invalid'] += 1
        elif kind == 'carState':
          car = event.carState.as_builder()
          car_ns = now if event.valid else 0
        elif kind == 'liveCalibration':
          calibrated = bool(event.valid and str(event.liveCalibration.calStatus) == 'calibrated')
          calibration_ns = now
        elif kind == 'radarState':
          rs, lead = event.radarState, event.radarState.leadOne
          observation = RvvLead(bool(lead.status), float(lead.dRel), float(lead.vLead), float(lead.vRel),
                                float(lead.modelProb), now, int(rs.mdMonoTime), bool(event.valid), bool(lead.radar))
        elif kind == 'carControl' and car is not None:
          if now <= latest_clock:
            counters['overlapping_or_reversed_control_timestamps'] += 1
            continue
          latest_clock = now
          counters['native_control_ticks'] += 1
          active = bool(car.cruiseState.enabled)
          counters['stock_rvv_active_ticks'] += active
          following = planner.update(now, active=active, car_valid=bool(car.canValid and not car.canTimeout),
            car_ns=car_ns, speed_kph=float(car.vEgoRaw)*3.6, stock_setpoint_kph=float(car.cruiseState.speed)*3.6,
            calibrated=calibrated, calibration_ns=calibration_ns, lead=observation)
          reasons[following.reason] += 1
          counters['following_target_ticks'] += following.target_kph is not None
          counters['following_target_increase_ticks'] += (following.target_kph is not None
            and last_following_target is not None and following.target_kph > last_following_target)
          last_following_target = following.target_kph
          counters['target_below_driver_ceiling_ticks'] += following.target_kph is not None and following.target_kph < car.cruiseState.speed*3.6 - .01
          rvv_inputs = RvvInputs(requested=active, speed_kph=float(car.vEgoRaw)*3.6,
            stock_setpoint_kph=float(car.cruiseState.speed)*3.6, cruise_active=active,
            cruise_available=bool(car.cruiseState.available), brake_pressed=bool(car.brakePressed),
            gas_pressed=pedal_pressed or not fresh(now, pedal_ns), cancel=bool(event.carControl.cruiseControl.cancel),
            vehicle_ready=bool(str(car.gearShifter) == 'drive' and not car.parkingBrake and not car.doorOpen and not car.seatbeltUnlatched),
            can_valid=bool(car.canValid and not car.canTimeout and fresh(now, car_ns)),
            safety_rx_nanos=min(safety_rx.values()), stock_rx_nanos=min(control.stock_ns, safety_rx[0x208]))
          status = control.update_following(now, rvv_inputs, following)
          host_reasons[status['reason']] += 1
          counters['prepared_payloads'] += control.candidate is not None
          candidate = status['candidate_setpoint_kph']
          counters['prepared_setpoint_increase_ticks'] += (candidate is not None
            and last_candidate is not None and candidate > last_candidate)
          last_candidate = candidate
          assert not status['tx_allowed']
          key = (following.reason, following.target_kph, status['reason'], status['candidate_setpoint_kph'])
          if key != trace_key or now-last_trace >= 500_000_000:
            trace_key, last_trace = key, now
            trace.write(json.dumps({'mono_ns': now, 'following': asdict(following), 'host': status,
                                    'lead': asdict(observation), 'inputs': asdict(rvv_inputs)})+'\n')
      print(f'Replayed {path.parent.name}', flush=True)

  topology = []
  for window in windows:
    lo, hi = window['first_ns']+200_000_000, window['last_ns']-200_000_000
    if hi <= lo:
      continue
    counts = Counter(f'0x{address:X}/bus{bus}' for ns, address, bus in physical_frames if lo <= ns <= hi)
    topology.append({'safety_model': window['key'][0], 'safety_param': window['key'][1],
                     'start_ns': lo, 'end_ns': hi, 'counts': counts})
  if any(sha(args.opendbc/'opendbc/car/psa'/name) != digest for name, digest in source_hashes.items()):
    raise RuntimeError('RVV sources changed during replay')
  result = {'source_logs': sources, 'bootlog_ids': sorted(boot_ids), 'partial_tails': tails,
    'control_request_source': 'synthetic_evaluation_while_recorded_stock_rvv_active',
    'native_can_validity': 'recorded_carState_not_recomputed_by_parser',
    'pedal_source': 'raw_0x228_with_nibble_checksum_and_age_check',
    'trajectory': 'recorded_open_loop_no_vehicle_response_to_candidates',
    'can_frames_emitted': 0, 'counters': counters, 'following_reasons': reasons,
    'host_reasons': host_reasons, 'stock_50e_parity_physical_rx': parity,
    'buses_including_tx_echoes': buses, 'stable_topology_windows': topology,
    'source_hashes': source_hashes}
  (args.output/'report.json').write_text(json.dumps(result, indent=2)+'\n')
  print(json.dumps({'counters': counters, 'following_reasons': reasons, 'host_reasons': host_reasons}, indent=2))


if __name__ == '__main__':
  main()
