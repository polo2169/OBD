"""Raw, receive-only T9 lifecycle observations on the current logical bus 0.

This bus convention is for the existing capture/HIL profile. It is not proof
of the comma four harness mapping. Keep observed EPS state separate from any
candidate command; malformed frames invalidate rather than refresh feedback.
"""

from dataclasses import replace

from opendbc.car.psa.lka import LkaFeedback


class T9LkaCanObserver:
  def __init__(self):
    self.feedback = LkaFeedback()

  def update(self, can_packets):
    for timestamp, frames in can_packets:
      for address, data, bus in frames:
        if bus != 0:
          continue
        if address == 0x3F2:
          valid = len(data) == 8 and timestamp > 0 and timestamp >= self.feedback.stock_nanos
          self.feedback = replace(
            self.feedback,
            stock_state=(data[4] >> 2) & 7 if valid else None,
            stock_factor=data[5] >> 1 if valid else 0,
            stock_angle_raw=(data[6] << 6) | (data[7] >> 2) if valid else 0,
            stock_lxa=data[5] & 1 if valid else 0,
            stock_nanos=max(timestamp, self.feedback.stock_nanos),
          )
        elif address == 0x495:
          valid = len(data) == 4 and timestamp > 0 and timestamp >= self.feedback.eps_nanos
          self.feedback = replace(
            self.feedback,
            eps_state=(data[2] >> 2) & 7 if valid else None,
            eps_nanos=max(timestamp, self.feedback.eps_nanos),
          )
