#define PSA_ALLOW_NONZERO_TORQUE 1
#define PSA_BENCH_ONLY 1
#define PSA_MIN_CONTROL_SPEED_KPH 40
#define PSA_MAX_CONTROL_SPEED_KPH 90

#include <assert.h>
#include <stdint.h>

#include "psa_lka_safety.hpp"

namespace {

void feed_lateral_inputs(psa_lka_safety::Safety &safety, uint32_t now) {
  const uint8_t steering[2] = {0, 0};
  const uint8_t angle[2] = {0, 0};
  // 50.00 km/h with the locally validated 0x38D nibble checksum.
  const uint8_t speed[6] = {0x13, 0x88, 0, 0, 0, 0x03};
  const uint8_t brake[1] = {0};
  safety.on_car_frame(psa_lka_safety::ID_STEERING, steering, sizeof(steering), now);
  safety.on_car_frame(psa_lka_safety::ID_STEERING_ALT, angle, sizeof(angle), now);
  safety.on_car_frame(psa_lka_safety::ID_SPEED, speed, sizeof(speed), now);
  safety.on_car_frame(psa_lka_safety::ID_DAT_BSI, brake, sizeof(brake), now);
}

int decode_lka_torque(const uint8_t *data) {
  const uint16_t raw = (static_cast<uint16_t>(data[3]) << 3) | (data[4] >> 5);
  return (raw & 0x400U) != 0U ? static_cast<int>(raw) - 0x800 : raw;
}

}  // namespace

int main() {
  psa_lka_safety::Safety safety;
  safety.reset();
  safety.on_physical_mads_enable(true, 100);
  safety.on_host_heartbeat(true, 100);
  safety.on_mads_command(true, 100);
  feed_lateral_inputs(safety, 100);

  // State 4 / factor 100 seed, zero stock torque and angle.
  const uint8_t lka[8] = {0, 0, 0x0D, 0, 0x10, 0xC8, 0, 0};
  safety.on_car_frame(psa_lka_safety::ID_LKA, lka, sizeof(lka), 100);

  // Accelerator pressed and RVV inactive must not affect lateral MADS.
  const uint8_t powertrain[5] = {0, 0, 0, 1, 0};
  safety.on_car_frame(
      psa_lka_safety::ID_DYN_CMM, powertrain, sizeof(powertrain), 100);
  assert(safety.controls_allowed());
  assert(!safety.cruise_engaged());
  assert(safety.gas_pressed());
  assert(safety.ready_for_takeover(100));
  assert(safety.begin_takeover(100));

  uint8_t output[8] = {0};
  assert(safety.build_and_check_lka(1, output, 120));
  assert(decode_lka_torque(output) == 1);

  // Driver torque pauses generated torque without dropping the lateral
  // engagement or requiring RVV. Stable release resumes after 300 ms.
  const uint8_t override_frame[2] = {0, 9};
  safety.on_car_frame(
      psa_lka_safety::ID_STEERING, override_frame, sizeof(override_frame), 130);
  assert(safety.mads_engaged());
  assert(!safety.controls_allowed());
  assert(safety.build_and_check_lka(2, output, 140));
  assert(decode_lka_torque(output) == 0);

  const uint8_t release_frame[2] = {0, 0};
  safety.on_car_frame(
      psa_lka_safety::ID_STEERING, release_frame, sizeof(release_frame), 150);
  safety.on_host_heartbeat(true, 430);
  safety.tick(449);
  assert(!safety.controls_allowed());
  safety.tick(450);
  assert(safety.controls_allowed());

  // Brake mode is Disengage and requires an explicit false -> true rearm.
  const uint8_t brake_frame[1] = {0x20};
  safety.on_car_frame(
      psa_lka_safety::ID_DAT_BSI, brake_frame, sizeof(brake_frame), 460);
  assert(!safety.mads_engaged());
  assert(safety.mads_rearm_required());

  return 0;
}
