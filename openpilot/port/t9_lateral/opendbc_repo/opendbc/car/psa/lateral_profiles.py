"""Explicit, staged T9 experiments. The installed default remains unchanged.

Each experiment has its own active/probe safety pair and requires mailbox
capability 10 before pandad may select it. An environment variable alone
cannot upgrade old firmware. No experiment is selected by launch_env.sh.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LateralProfile:
  name: str = 'off'
  safety_param: int = 0
  min_speed_kph: float = 67.1
  blinker_assist: bool = False

  def stock_authorized(self, state, speed_kph, signal=0):
    return state in (3, 4) or (state == 2 and (
      self.min_speed_kph == 50. and 50. <= speed_kph < 67.1
      or self.blinker_assist and signal in (1, 2)))


DEFAULT = LateralProfile()
EXPERIMENTS = {
  'low_speed': LateralProfile('low_speed', 0x1318, 50.),
  'blinker': LateralProfile('blinker', 0x131A, 67.1, True),
  'low_speed_blinker': LateralProfile('low_speed_blinker', 0x131C, 50., True),
}
EXPERIMENT_PARAMS = tuple(p.safety_param for p in EXPERIMENTS.values())


def from_safety_param(param):
  return next((p for p in EXPERIMENTS.values() if p.safety_param == param), DEFAULT)


def selected(name):
  if name == 'off':
    return DEFAULT
  if name not in EXPERIMENTS:
    raise ValueError('Unknown PSA_T9_LATERAL_EXPERIMENT')
  return EXPERIMENTS[name]


def signal(left, right):
  """Keep hazards distinct from a single physical turn signal."""
  return int(bool(left)) | (int(bool(right)) << 1)
