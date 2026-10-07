"""Passive T9 experiment telemetry, independent of all actuator processes.

Only subscribes to existing services and writes bounded diagnostic logs. No
carState reader (its msgq slots are scarce), publisher, Panda or Params access.
The proposed profiles are assessed from received CAN; EPS command acceptance
is always unknown because this observer never sends an experiment command.
"""
from collections import Counter
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from types import SimpleNamespace as NS

from opendbc.car.psa.lateral_profiles import EXPERIMENTS
from opendbc.car.psa.values import CAR
from openpilot.selfdrive.controls.lib.t9_lane_change import T9LaneChangePreview

SERVICES = ('can', 'modelV2', 'carControl', 'carParams', 'pandaStates', 'deviceState', 'sendcan')
LOG_ROOT = Path('/data/psa-observation')
FRESH_NS = 250_000_000
LENGTHS = {0x3F2: 8, 0x495: 4, 0x2F5: 7, 0x30D: 8, 0x348: 8,
           0x412: 8, 0x3AD: 8, 0x572: 8, 0x228: 8, 0x452: 6, 0x50E: 8, 0x208: 8}
COMMON = (0x2F5, 0x30D, 0x348, 0x412, 0x3AD, 0x572, 0x228, 0x452, 0x50E, 0x208)


def fresh(now, timestamp, limit=FRESH_NS):
  return 0 < timestamp <= now and now - timestamp <= limit


def safe_json(value):
  if isinstance(value, float) and not math.isfinite(value):
    return None
  if isinstance(value, dict):
    return {k: safe_json(v) for k, v in value.items()}
  if isinstance(value, (list, tuple)):
    return [safe_json(v) for v in value]
  return value


class T9ExperimentObservation:
  def __init__(self):
    self.frames = {}
    self.last_invalid_can = self.last_valid_can = 0
    self.wrong_side_ns = 0
    self.latest = {}
    self.counts = Counter()
    self.lane = T9LaneChangePreview(50.)
    self.last_signal = self.signal_started = 0
    self.deadline_sample = None
    self.last_sendcan = None

  def observe(self, event):
    kind, now = event.which(), int(event.logMonoTime)
    self.counts[kind] += 1
    if kind == 'can':
      if event.valid:
        self.last_valid_can = max(self.last_valid_can, now)
      else:
        self.last_invalid_can = max(self.last_invalid_can, now)
      for frame in event.can:
        addr, bus, data = int(frame.address), int(frame.src), bytes(frame.dat)
        if bus not in (0, 2) or addr not in LENGTHS:
          continue
        if ((addr in (0x495, 0x208) and bus != 0) or (addr in (0x3F2, 0x50E) and bus != 2)):
          self.wrong_side_ns = max(self.wrong_side_ns, now)
          continue
        previous = self.frames.get(addr)
        if previous and now < previous[0]:
          self.frames[addr] = (previous[0], False, previous[2])
          continue
        valid = bool(event.valid and now > 0 and len(data) == LENGTHS[addr])
        if valid and addr in (0x2F5, 0x228, 0x3AD):
          valid = sum((b >> 4) + (b & 15) for b in data) % 16 == {0x2F5: 11, 0x228: 3, 0x3AD: 13}[addr]
        if valid and addr == 0x50E:
          p = data[6]
          parity = (((p >> 4).bit_count() % 2) << 1) | ((p & 15).bit_count() % 2)
          valid = ((data[0] >> 4) & 3) == parity
        self.frames[addr] = (now, valid, data)
    elif kind == 'sendcan':
      for frame in event.sendcan:
        if frame.address == 0x3F2 and frame.src == 0 and len(frame.dat) == 8:
          data = bytes(frame.dat)
          raw = (data[3] << 3) | (data[4] >> 5)
          self.last_sendcan = {'ns': now, 'valid': bool(event.valid), 'state': (data[4] >> 2) & 7,
            'factor': data[5] >> 1, 'torque_raw': raw - 2048 if raw & 1024 else raw,
            'source': 'existing_controller_sendcan_request', 'physical_torque_proven': False}
    elif kind in SERVICES:
      payload = getattr(event, kind)
      if kind == 'pandaStates':
        payload = list(payload)
      self.latest[kind] = (now, bool(event.valid), payload)

  def data(self, addr, now, limit=FRESH_NS):
    timestamp, valid, data = self.frames.get(addr, (0, False, b''))
    return data if valid and fresh(now, timestamp, limit) else None

  def service(self, name, now, limit=FRESH_NS):
    timestamp, valid, payload = self.latest.get(name, (0, False, None))
    return payload if valid and (limit is None or fresh(now, timestamp, limit)) else None

  def snapshot(self, now):
    data = {addr: self.data(addr, now, 150_000_000 if addr == 0x3F2 else FRESH_NS) for addr in LENGTHS}
    wheels = data[0x30D]
    speeds = [int.from_bytes(wheels[i:i+2], 'big') / 100. for i in range(0, 8, 2)] if wheels else []
    consistent = bool(speeds and max(speeds) - min(speeds) <= 5.)
    speed = sum(speeds) / 4. if consistent else None
    torque = int.from_bytes(data[0x2F5][1:2], 'big', signed=True) if data[0x2F5] else None
    body, gear, park, belt, gas = (data[a] for a in (0x412, 0x348, 0x3AD, 0x572, 0x228))
    raw_turn = ((data[0x452][0] >> 4) & 3) if data[0x452] else None
    # PSA wire values: 1=right, 2=left; the preview uses 1=left, 2=right.
    turn = {0: 0, 1: 2, 2: 1, 3: 3}.get(raw_turn)
    stock, eps = data[0x3F2], data[0x495]
    stock_state = ((stock[4] >> 2) & 7) if stock else None
    eps_state = ((eps[2] >> 2) & 7) if eps else None
    bsi, engine = data[0x50E], data[0x208]
    cruise = bool(bsi and engine and ((bsi[7] >> 5) & 3) == 1 and bsi[7] & 128
                  and bsi[6] < 255 and ((engine[4] >> 2) & 3) == 2)
    ready_vehicle = bool(gear and 1 <= gear[0] >> 4 <= 6 and gear[6] & 64
      and body and not body[0] & 4 and not body[6] & 0x78
      and park and (park[3] & 7) == 0 and belt and belt[0] >> 6 == 2)
    can_ready = (all(data[a] is not None for a in COMMON) and consistent
      and fresh(now, self.last_valid_can) and self.last_invalid_can < self.last_valid_can
      and (not self.wrong_side_ns or now - self.wrong_side_ns >= 2_000_000_000))
    cp = self.service('carParams', now, None)
    matched = bool(cp is not None and cp.carFingerprint == CAR.PSA_PEUGEOT_308_T9)
    device = self.service('deviceState', now, 5_000_000_000)
    onroad = bool(device is not None and device.started)
    cc = self.service('carControl', now, 150_000_000)
    model = self.service('modelV2', now, 150_000_000)
    model_ns = self.latest.get('modelV2', (0,))[0]
    model_fresh = bool(model is not None and fresh(now, int(model.timestampEof), 150_000_000))
    brake, pedal = bool(body and body[0] & 32), bool(gas and gas[2] > 0)
    driver = torque is not None and abs(torque) > 15
    pandas = self.service('pandaStates', now, 1_000_000_000) or []
    safety_rx_healthy = bool(pandas and all(not p.safetyRxChecksInvalid for p in pandas))
    common_ready = bool(matched and onroad and can_ready and ready_vehicle and cruise
                        and safety_rx_healthy and not brake and not pedal and torque is not None and not driver)
    profiles = {}
    for name, profile in EXPERIMENTS.items():
      speed_ok = speed is not None and profile.min_speed_kph <= round(speed, 4) <= 140.
      stock_ok = bool(stock is not None and profile.stock_authorized(stock_state, speed or 0., turn)
                      and stock[5] >> 1 <= 100 and not stock[5] & 1 and stock[6] == 0 and not stock[7] & 0xFC)
      signal_ok = turn in (0, 1, 2) if profile.blinker_assist else turn == 0
      eps_available = eps_state in (1, 2, 3)
      problems = [reason for reason, good in (
        ('physical_inputs_unavailable', common_ready), ('speed_outside_profile', speed_ok),
        ('stock_lka_unavailable', stock_ok), ('signal_unavailable_or_inhibited', signal_ok),
        ('eps_unavailable', eps_available), ('model_unavailable', model_fresh)) if not good]
      profiles[name] = {'passive_conditions_ready': not problems, 'reasons': problems,
        'would_prepare_if_explicitly_armed': not problems and eps_state in (1, 2),
        'eps_command_acceptance': 'not_tested', 'experiment_command_sent': False}
    car = NS(vEgo=(speed or 0.) / 3.6, steeringTorque=float(torque or 0), steeringPressed=driver,
      brakePressed=brake, gasPressed=pedal, leftBlinker=turn in (1, 3), rightBlinker=turn in (2, 3),
      leftBlindspot=False, rightBlindspot=False)
    candidate_ready = profiles['low_speed_blinker']['passive_conditions_ready']
    if not onroad:
      self.lane = T9LaneChangePreview(50.)
    probabilities = model.meta.desireState if model is not None else []
    probability = float(probabilities[3]) + float(probabilities[4]) if len(probabilities) >= 5 else float('nan')
    lane = self.lane.update(now, car, candidate_ready, model, int(model.timestampEof) if model else 0,
                            model_fresh, probability)
    if turn != self.last_signal:
      self.last_signal, self.signal_started = turn, now if turn in (1, 2) else 0
      self.deadline_sample = None
    elapsed = now - self.signal_started if self.signal_started else None
    if elapsed is not None and elapsed >= 2_000_000_000 and self.deadline_sample is None:
      self.deadline_sample = {'ns': now, 'elapsed_ns': elapsed,
        'adjacent_lane_candidate': lane['adjacent_lane_candidate'], 'model_fresh': model_fresh,
        'eps_state': eps_state, 'stock_lka_state': stock_state, 'speed_kph': speed,
        'road_and_rear_context': 'unknown', 'start_authorized': False}
    observed_pandas = [{'model': str(p.safetyModel), 'param': int(p.safetyParam),
      'controls_allowed': bool(p.controlsAllowed), 'safety_rx_invalid': bool(p.safetyRxChecksInvalid),
      'tx_blocked': int(p.safetyTxBlocked), 'spi_errors': int(p.spiErrorCount)} for p in pandas]
    return safe_json({'mono_ns': now, 'observation_only': True, 'experiment_transmission_allowed': False,
      'physical_acceptance_validated': False, 'car_matched': matched, 'onroad': onroad,
      'speed_kph': speed, 'wheel_speeds_kph': speeds, 'can_inputs_fresh': bool(can_ready),
      'driver_torque_raw': torque, 'brake_pressed': brake, 'gas_pressed': pedal,
      'physical_cruise_enabled': cruise, 'physical_signal': turn, 'physical_signal_raw': raw_turn,
      'signal_side': {0: 'off', 1: 'left', 2: 'right', 3: 'hazards'}.get(turn, 'unknown'),
      'signal_elapsed_ns': elapsed,
      'stock_lka_state': stock_state, 'stock_lka_factor': stock[5] >> 1 if stock else None,
      'eps_state': eps_state, 'eps_feedback_age_ns': now - self.frames[0x495][0] if eps else None,
      'actual_cc_enabled': bool(cc and cc.enabled), 'actual_lateral_active': bool(cc and cc.latActive),
      'actual_torque_request': float(cc.actuators.torque) if cc else None,
      'model_fresh': model_fresh, 'model_service_age_ns': now - model_ns if model_ns else None,
      'profiles': profiles, 'timed_lane_change_counterfactual': lane,
      'signal_two_second_sample': self.deadline_sample,
      'road_and_rear_context': 'unknown', 'blindspot_sensor_status': 'unknown',
      'existing_controller_sendcan': self.last_sendcan, 'pandas': observed_pandas})


class ObservationJournal:
  def __init__(self, root, segment_bytes=16*1024*1024, max_segments=8, min_free_bytes=1024**3):
    self.root = Path(root)
    self.root.mkdir(parents=True, exist_ok=True)
    self.lock = (self.root / '.observer.lock').open('a')
    try:
      fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
      self.lock.close()
      raise
    self.segment_bytes, self.max_segments, self.min_free_bytes = segment_bytes, max_segments, min_free_bytes
    self.file, self.size = None, 0
    self.sequence = max((int(p.stem.split('-')[1]) for p in self.files()), default=0) + 1

  def files(self):
    return sorted(p for p in self.root.iterdir() if p.is_file() and not p.is_symlink()
                  and re.fullmatch(r'observation-\d{8,}\.jsonl', p.name))

  def write(self, row):
    payload = json.dumps(safe_json(row), separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(payload) > self.segment_bytes or shutil.disk_usage(self.root).free < self.min_free_bytes + self.segment_bytes:
      return False
    if self.file is None or self.size + len(payload) > self.segment_bytes:
      if self.file is not None:
        self.file.close()
      for old in self.files()[:max(0, len(self.files()) - self.max_segments + 1)]:
        old.unlink()
      self.file = (self.root / f'observation-{self.sequence:08d}.jsonl').open('xb')
      self.sequence += 1
      self.size = 0
    self.file.write(payload)
    self.file.flush()
    self.size += len(payload)
    return True

  def status(self, row):
    temporary = self.root / 'status.json.tmp'
    temporary.write_text(json.dumps(safe_json(row), indent=2, allow_nan=False) + '\n')
    temporary.replace(self.root / 'status.json')

  def close(self):
    if self.file is not None:
      self.file.close()
    self.lock.close()


def run(root=LOG_ROOT, duration=None):
  from cereal import messaging
  from openpilot.common.swaglog import cloudlog

  journal = ObservationJournal(root)
  observation = T9ExperimentObservation()
  poller = messaging.Poller()
  for service in SERVICES:
    messaging.sub_sock(service, poller=poller, conflate=service != 'can')
  started, last_emit, last_status, last_tick = time.monotonic_ns(), 0, 0, 0
  key = None
  cloudlog.bind(daemon='psa_t9_experiment_observer')
  code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
  rows = drops = 0
  try:
    while duration is None or time.monotonic_ns() - started < duration * 1e9:
      for sock in poller.poll(25):
        for _ in range(100):
          payload = sock.receive(non_blocking=True)
          if payload is None:
            break
          observation.observe(messaging.log_from_bytes(payload))
      now = time.monotonic_ns()
      if now - last_tick < 50_000_000:
        continue
      last_tick = now
      row = observation.snapshot(now)
      new_key = (row['onroad'], row['stock_lka_state'], row['eps_state'], row['physical_signal'],
        row['gas_pressed'], row['brake_pressed'], row['timed_lane_change_counterfactual']['phase'],
        row['timed_lane_change_counterfactual']['reason'], bool(row['signal_two_second_sample']),
        tuple(p['passive_conditions_ready'] for p in row['profiles'].values()))
      interval = 1_000_000_000 if row['onroad'] else 10_000_000_000
      if new_key != key or now - last_emit >= interval:
        rows += 1
        drops += not journal.write(row)
        # Existing logMessage/rlogs retain the same decisions beside raw CAN/model.
        cloudlog.info('psa_t9_observation ' + json.dumps(row, separators=(',', ':'), allow_nan=False))
        key, last_emit = new_key, now
      if now - last_status >= 1_000_000_000:
        journal.status({'pid': os.getpid(), 'mono_ns': now, 'uptime_s': (now-started)/1e9,
          'source_sha256': code_hash, 'observation_only': True, 'experiment_transmission_allowed': False,
          'onroad': row['onroad'], 'messages_received': dict(observation.counts), 'rows_written': rows-drops,
          'storage_drops': drops, 'carState_subscription': False, 'services': SERVICES,
          'current_file': Path(journal.file.name).name if journal.file else None})
        last_status = now
  finally:
    journal.close()


def main():
  if os.getenv('PSA_T9_OBSERVE', '1') != '1':
    return
  while True:
    try:
      run()
    except OSError as error:
      print(f'T9 observation storage unavailable: {error}', flush=True)
      time.sleep(10)


if __name__ == '__main__':
  main()
