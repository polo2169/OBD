import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from cereal import messaging
from opendbc.car.psa.values import CAR
from openpilot.system.psa_t9_experiment_observer import SERVICES, ObservationJournal, T9ExperimentObservation, run

BASE = 1_000_000_000


def event(kind, now, size=None):
  msg = messaging.new_message(kind, size, valid=True) if size is not None else messaging.new_message(kind, valid=True)
  msg.logMonoTime = now
  return msg


def checksum(data, seed, index):
  data = bytearray(data)
  data[index] |= (seed - sum((b >> 4) + (b & 15) for b in data)) & 15
  return bytes(data)


def messages(now, speed=55., eps=2, stock=2, turn=0, gas=0, driver=0, cruise=True):
  wheel = round(speed * 100).to_bytes(2, 'big') * 4
  point = 75 if cruise else 255
  parity = (((point >> 4).bit_count() % 2) << 1) | ((point & 15).bit_count() % 2)
  frames = [
    (0x3F2, bytes([0, 0, 0x12, 0, stock << 2, 0, 0, 0]), 2),
    (0x495, bytes([0, 0, eps << 2, 0]), 0),
    (0x30D, wheel, 0), (0x2F5, checksum([0, driver & 255, 0, 0, 0, 0, 0], 11, 6), 0),
    (0x348, bytes([0x40, 0, 0, 0, 0, 0, 0x40, 0]), 0),
    (0x412, bytes(8), 2), (0x3AD, checksum(bytes(8), 13, 7), 0),
    (0x572, bytes([128, 0, 0, 0, 0, 0, 0, 0]), 2),
    (0x228, checksum([0, 0, gas * 2, 0, 0, 0, 0, 0], 3, 3), 0),
    (0x452, bytes([{0: 0, 1: 2, 2: 1, 3: 3}[turn] << 4, 0, 0, 0, 0, 0]), 2),
    (0x50E, bytes([parity << 4, 0, 0, 0, 0, 0, point, 0xA0 if cruise else 0x20]), 2),
    (0x208, bytes([0, 0, 0, 0, 8 if cruise else 0, 0, 0, 0]), 0),
  ]
  can = event('can', now, len(frames))
  for output, (addr, data, bus) in zip(can.can, frames, strict=True):
    output.address, output.dat, output.src = addr, data, bus
  cp = event('carParams', now)
  cp.carParams.carFingerprint = CAR.PSA_PEUGEOT_308_T9
  device = event('deviceState', now)
  device.deviceState.started = True
  cc = event('carControl', now)
  cc.carControl.enabled = cc.carControl.latActive = False
  panda = event('pandaStates', now, 1)
  panda.pandaStates[0].safetyModel = 'psa'
  panda.pandaStates[0].safetyParam = 0x1316
  model = event('modelV2', now)
  model.modelV2.timestampEof = now
  model.modelV2.laneLineProbs = [.95] * 4
  for line, y in zip(model.modelV2.init('laneLines', 4), (-5.4, -1.8, 1.8, 5.4), strict=True):
    line.x, line.y = [0., 10., 20.], [y]*3
  model.modelV2.meta.desireState = [0.] * 7
  return [can, cp, device, cc, panda, model]


class TestT9PassiveObservation(unittest.TestCase):
  def tick(self, observation, ms=0, **kwargs):
    now = BASE + ms * 1_000_000
    for msg in messages(now, **kwargs):
      observation.observe(msg)
    return observation.snapshot(now)

  def test_below_67_conditions_are_counterfactual_without_invented_eps_acceptance(self):
    observer = T9ExperimentObservation()
    row = self.tick(observer)
    self.assertTrue(row['profiles']['low_speed']['passive_conditions_ready'])
    self.assertFalse(row['profiles']['blinker']['passive_conditions_ready'])
    self.assertFalse(row['actual_lateral_active'])
    self.assertEqual(row['eps_state'], 2)
    self.assertFalse(row['physical_acceptance_validated'])
    for assessment in row['profiles'].values():
      self.assertFalse(assessment['experiment_command_sent'])
      self.assertEqual(assessment['eps_command_acceptance'], 'not_tested')

  def test_eps_loss_pedal_and_driver_effort_refuse_the_hypothesis(self):
    for change in ({'eps': 0}, {'eps': 4}, {'gas': 1}, {'driver': 16}, {'speed': 49.99}, {'turn': 3}):
      row = self.tick(T9ExperimentObservation(), **change)
      self.assertFalse(row['profiles']['low_speed_blinker']['passive_conditions_ready'], change)

  def test_two_second_recording_works_while_actual_assistance_is_inactive(self):
    observer = T9ExperimentObservation()
    for ms in range(0, 2051, 50):
      row = self.tick(observer, ms, turn=1)
    self.assertTrue(row['signal_two_second_sample']['adjacent_lane_candidate'])
    self.assertEqual(row['signal_two_second_sample']['elapsed_ns'], 2_000_000_000)
    self.assertFalse(row['signal_two_second_sample']['start_authorized'])
    self.assertEqual(row['timed_lane_change_counterfactual']['reason'], 'road_and_rear_context_unknown_or_stale')
    self.assertFalse(row['actual_lateral_active'])

  def test_psa_signal_wire_direction_selects_the_correct_adjacent_lane(self):
    for raw, direction, side in ((1, 2, 'right'), (2, 1, 'left')):
      observer = T9ExperimentObservation()
      events = messages(BASE)
      events[0].can[9].dat = bytes([raw << 4, 0, 0, 0, 0, 0])
      # Only the left adjacent lane is plausible.
      events[-1].modelV2.laneLines[3].y = [8., 8., 8.]
      for msg in events: observer.observe(msg)
      row = observer.snapshot(BASE)
      self.assertEqual(row['signal_side'], side)
      self.assertEqual(row['physical_signal'], direction)
      self.assertEqual(row['timed_lane_change_counterfactual']['adjacent_lane_candidate'], side == 'left')

  def test_stale_checksum_or_panda_rx_invalid_inputs_are_not_validated(self):
    observer = T9ExperimentObservation()
    self.tick(observer)
    self.assertFalse(observer.snapshot(BASE + 300_000_000)['profiles']['low_speed']['passive_conditions_ready'])
    bad = messages(BASE + 50_000_000)
    bad[0].can[3].dat = bytes(7)
    for msg in bad: observer.observe(msg)
    self.assertFalse(observer.snapshot(BASE + 50_000_000)['can_inputs_fresh'])
    self.tick(observer, 100)
    panda = event('pandaStates', BASE + 100_000_000, 1)
    panda.pandaStates[0].safetyRxChecksInvalid = True
    observer.observe(panda)
    self.assertFalse(observer.snapshot(BASE + 100_000_000)['profiles']['low_speed']['passive_conditions_ready'])

  def test_wrong_side_and_unknown_vehicle_are_not_admitted(self):
    observer = T9ExperimentObservation()
    events = messages(BASE)
    events[0].can[0].src = 0
    for msg in events: observer.observe(msg)
    self.assertFalse(observer.snapshot(BASE)['profiles']['low_speed']['passive_conditions_ready'])
    cp = event('carParams', BASE)
    cp.carParams.carFingerprint = 'unknown'
    observer.observe(cp)
    self.assertFalse(observer.snapshot(BASE)['car_matched'])

  def test_runtime_has_no_publisher_or_carstate_reader_and_does_not_mutate_inputs(self):
    events = messages(BASE)
    before = [e.to_bytes() for e in events]
    pending = []
    for payload in before:
      sock = MagicMock()
      sock.receive.side_effect = [payload, None]
      pending.append(sock)
    def poll(_timeout):
      result = pending.copy()
      pending.clear()
      return result
    with tempfile.TemporaryDirectory() as directory, \
         patch.object(messaging, 'sub_sock') as subscribe, patch.object(messaging, 'PubMaster') as publisher, \
         patch.object(messaging, 'Poller') as poller, patch('openpilot.common.swaglog.cloudlog') as logger, \
         patch('openpilot.system.psa_t9_experiment_observer.shutil.disk_usage') as usage:
      usage.return_value.free = 10 * 1024**3
      poller.return_value.poll.side_effect = poll
      run(directory, duration=.06)
      self.assertEqual([c.args[0] for c in subscribe.call_args_list], list(SERVICES))
      self.assertNotIn('carState', SERVICES)
      publisher.assert_not_called()
      status = json.loads((Path(directory) / 'status.json').read_text())
      self.assertFalse(status['experiment_transmission_allowed'])
      self.assertTrue(list(Path(directory).glob('observation-*.jsonl')))
    for msg in events: msg.clear_write_flag()
    self.assertEqual(before, [e.to_bytes() for e in events])


class TestObservationJournal(unittest.TestCase):
  def test_bounded_retention_lock_and_low_disk_preserve_other_files(self):
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      (root / 'notes.txt').write_text('keep')
      writer = ObservationJournal(root, segment_bytes=30, max_segments=2, min_free_bytes=0)
      try:
        with self.assertRaises(BlockingIOError): ObservationJournal(root)
        for i in range(5): self.assertTrue(writer.write({'i': i, 'x': 'abcdef'}))
        self.assertEqual(len(writer.files()), 2)
        with patch('openpilot.system.psa_t9_experiment_observer.shutil.disk_usage') as usage:
          usage.return_value.free = 0
          self.assertFalse(writer.write({'i': 99}))
      finally:
        writer.close()
      self.assertEqual((root / 'notes.txt').read_text(), 'keep')
