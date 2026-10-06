"""Join the existing lateral lifecycle and RVV adapter without an output path."""

from dataclasses import asdict

from opendbc.car import structs
from opendbc.car.psa.lka import LkaInputs, T9LkaLifecycle
from opendbc.car.psa.lka_feedback import T9LkaCanObserver
from opendbc.car.psa.rvv import RvvInputs, T9RvvAdapter


class T9ShadowController:
  def __init__(self):
    self.observer = T9LkaCanObserver()
    self.lateral = T9LkaLifecycle()
    self.longitudinal = T9RvvAdapter()
    self.status = {}

  def update(self, CC, CS, now_nanos):
    state = CS.out
    drive_confirmed = state.gearShifter == structs.CarState.GearShifter.drive
    ready = (drive_confirmed and not state.parkingBrake and not state.doorOpen
             and not state.seatbeltUnlatched)
    rx_min = getattr(CS, 't9_shadow_safety_rx_nanos', 0)
    rx_max = getattr(CS, 't9_shadow_latest_rx_nanos', 0)
    can_valid = bool(state.canValid and not state.canTimeout and 0 < rx_max <= now_nanos)
    lat_input = LkaInputs(
      requested=bool(CC.enabled and CC.latActive), torque=float(CC.actuators.torque),
      speed_kph=float(state.vEgoRaw) * 3.6, driver_torque_raw=float(state.steeringTorque),
      driver_override=bool(state.steeringPressed), brake_pressed=bool(state.brakePressed),
      vehicle_ready=bool(ready and not state.steerFaultTemporary and not state.steerFaultPermanent),
      can_valid=can_valid, safety_rx_nanos=rx_min, feedback=self.observer.feedback,
    )
    long_input = RvvInputs(
      requested=bool(CC.enabled and CC.longActive), requested_accel_ms2=float(CC.actuators.accel),
      speed_kph=float(state.vEgoRaw) * 3.6, stock_setpoint_kph=float(state.cruiseState.speed) * 3.6,
      cruise_active=bool(state.cruiseState.enabled), cruise_available=bool(state.cruiseState.available),
      brake_pressed=bool(state.brakePressed), gas_pressed=bool(state.gasPressed),
      cancel=bool(CC.cruiseControl.cancel), vehicle_ready=bool(ready), can_valid=can_valid,
      safety_rx_nanos=rx_min, stock_rx_nanos=getattr(CS, 't9_shadow_rvv_rx_nanos', 0),
    )
    lateral = self.lateral.update(now_nanos, lat_input)
    longitudinal = self.longitudinal.update(now_nanos, long_input)
    self.status = {
      'mode': 'observation_only', 'tx_allowed': False,
      'drive_gear_confirmed': drive_confirmed,
      'pedal_valid': getattr(CS, 't9_pedal_valid', False),
      'pedal_pct': getattr(CS, 't9_pedal_pct', None),
      'engine_accelerator_demand_pct': getattr(CS, 't9_engine_accelerator_demand_pct', None),
      'current_gear': getattr(CS, 't9_current_gear_raw', None),
      'target_gear': getattr(CS, 't9_target_gear', None),
      'target_gear_raw': getattr(CS, 't9_target_gear_raw', None),
      'lateral': asdict(lateral) | {'tx_allowed': lateral.tx_allowed},
      'longitudinal': asdict(longitudinal),
      # These explain eligibility even when the passive comma requests nothing.
      'lateral_readiness_problem': (self.lateral._feedback_problem(now_nanos, lat_input)
                                    or self.lateral._engagement_problem(lat_input)),
      'longitudinal_readiness_problem': self.longitudinal.problem(now_nanos, long_input),
      'observed_feedback': asdict(self.observer.feedback),
      'requested_torque_normalized': float(CC.actuators.torque),
      'requested_accel_ms2': float(CC.actuators.accel),
      'observed_stock_setpoint_kph': float(state.cruiseState.speed) * 3.6,
    }
    return self.status
