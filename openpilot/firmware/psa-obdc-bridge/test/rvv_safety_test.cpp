#define PSA_ALLOW_RVV_CONTROL 1

#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "psa_rvv_safety.hpp"

namespace {

uint8_t reference_parity4(uint8_t value) {
  uint8_t ones = 0;
  for (uint8_t bit = 0; bit < 4U; ++bit) ones += (value >> bit) & 1U;
  return ones & 1U;
}

uint8_t reference_checksum(uint8_t setpoint) {
  return static_cast<uint8_t>(
      (reference_parity4(setpoint >> 4) << 1)
      | reference_parity4(setpoint & 0x0FU));
}

}  // namespace

int main() {
  using psa_rvv_safety::Controller;
  using psa_rvv_safety::FrameAction;

  for (int setpoint = 0; setpoint <= 255; ++setpoint) {
    assert(Controller::checksum_for_setpoint(static_cast<uint8_t>(setpoint))
        == reference_checksum(static_cast<uint8_t>(setpoint)));
  }

  // Captured active RVV frame: mode 1, active, 85 km/h, counter 3.
  const uint8_t captured[8] = {0x02, 0x1B, 0x00, 0x14, 0x5E, 0x42, 0x55, 0xA3};
  assert(Controller::decode_checksum(captured) == 0U);
  assert(Controller::checksum_for_setpoint(85U) == 0U);
  assert(Controller::decode_mode(captured) == 1U);
  assert(Controller::decode_activation(captured));

  Controller controller;
  controller.reset();
  assert(controller.set_command(true, 80, 100));
  controller.on_stock_frame(captured, sizeof(captured), 100);
  assert(controller.ready_for_takeover(100));
  assert(controller.begin_takeover(100));

  uint8_t output[8] = {0};
  assert(controller.build_from_stock(captured, sizeof(captured), output, 100)
      == FrameAction::PassThrough);
  assert(memcmp(captured, output, sizeof(captured)) == 0);

  // Rate limiting permits only one km/h after 500 ms. Counter, activation,
  // mode and all unrelated bits remain copied from the stock BSI frame.
  assert(controller.set_command(true, 80, 600));
  controller.on_stock_frame(captured, sizeof(captured), 600);
  assert(controller.build_from_stock(captured, sizeof(captured), output, 600)
      == FrameAction::Replaced);
  assert(output[6] == 84U);
  assert(Controller::decode_checksum(output) == Controller::checksum_for_setpoint(84U));
  assert(output[7] == captured[7]);
  assert(Controller::replacement_is_bounded(captured, output));

  uint8_t forbidden[8];
  memcpy(forbidden, output, sizeof(forbidden));
  forbidden[3] ^= 1U;
  assert(!Controller::replacement_is_bounded(captured, forbidden));

  // A host command older than 300 ms invalidates longitudinal control.
  assert(!controller.tick(901));

  // LVV (mode 2) and an inactive RVV request can never arm the controller.
  uint8_t lvv[8];
  memcpy(lvv, captured, sizeof(lvv));
  lvv[7] = 0xC3;  // active bit plus mode 2, counter preserved
  Controller lvv_controller;
  lvv_controller.reset();
  assert(lvv_controller.set_command(true, 80, 10));
  lvv_controller.on_stock_frame(lvv, sizeof(lvv), 10);
  assert(!lvv_controller.ready_for_takeover(10));

  uint8_t inactive[8];
  memcpy(inactive, captured, sizeof(inactive));
  inactive[7] = 0x23;  // RVV selected, activation cleared, counter preserved
  Controller inactive_controller;
  inactive_controller.reset();
  assert(inactive_controller.set_command(true, 80, 10));
  inactive_controller.on_stock_frame(inactive, sizeof(inactive), 10);
  assert(!inactive_controller.ready_for_takeover(10));

  return 0;
}
