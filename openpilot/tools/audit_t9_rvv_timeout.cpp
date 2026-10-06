// Offline observation of the existing ESP32 RVV controller's timeout.
// Compile as a desktop executable. No serial/CAN transport or firmware upload.
// The caller paths below mirror master_main.cpp's service_state and CanFrame.
#define PSA_ALLOW_RVV_CONTROL 1

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "psa_rvv_safety.hpp"

using psa_rvv_safety::Controller;
using psa_rvv_safety::FrameAction;

static Controller prepare_reduced_setpoint(uint8_t *stock, uint8_t *output) {
  // Recorded stock encoding: selected RVV, active, 85 km/h, counter 3.
  const uint8_t recorded[8] = {0x02, 0x1B, 0x00, 0x14, 0x5E, 0x42, 0x55, 0xA3};
  memcpy(stock, recorded, 8);
  Controller controller;
  controller.reset();
  assert(controller.set_command(true, 80, 100));
  controller.on_stock_frame(stock, 8, 100);
  assert(controller.begin_takeover(100));
  for (uint32_t now = 100; now <= 2600; now += 100) {
    stock[7] = static_cast<uint8_t>(0xA0U | ((now / 100) & 15U));
    assert(controller.set_command(true, 80, now));
    controller.on_stock_frame(stock, 8, now);
    assert(controller.build_from_stock(stock, 8, output, now) != FrameAction::Reject);
    assert(Controller::replacement_is_bounded(stock, output));
  }
  assert(output[6] == 80U);
  return controller;
}

int main() {
  uint8_t stock[8], output[8];
  Controller service_first = prepare_reduced_setpoint(stock, output);
  const uint8_t before = output[6];
  // Stock CAN continues, but the host's latest command is 301 ms old.
  stock[7] = 0xAD;
  service_first.on_stock_frame(stock, 8, 2901);
  assert(!service_first.tick(2901));
  assert(strcmp(service_first.reason(), "RVV host command timeout") == 0);
  // Existing service_state clears the request on this condition.
  service_first.set_command(false, psa_rvv_safety::MIN_SETPOINT_KPH, 2901);
  assert(service_first.build_from_stock(stock, 8, output, 2901) == FrameAction::PassThrough);
  const uint8_t service_after = output[6];
  const bool still_active = Controller::decode_activation(output);

  Controller frame_first = prepare_reduced_setpoint(stock, output);
  stock[7] = 0xAD;
  frame_first.on_stock_frame(stock, 8, 2901);
  assert(frame_first.build_from_stock(stock, 8, output, 2901) == FrameAction::Reject);
  // Existing CanFrame reject path clears the request and copies stock.
  frame_first.set_command(false, psa_rvv_safety::MIN_SETPOINT_KPH, 2901);
  memcpy(output, stock, 8);
  const uint8_t frame_after = output[6];

  // An original cancellation is also passed unchanged; this verifies bytes,
  // not the mechanical brake switch or a running engine ECU.
  stock[7] &= 0x7FU;
  assert(frame_first.build_from_stock(stock, 8, output, 3000) == FrameAction::PassThrough);
  assert(memcmp(output, stock, 8) == 0);
  printf("{\n"
         "  \"scope\": \"desktop_execution_existing_esp32_controller_no_can\",\n"
         "  \"stock_setpoint_kph\": 85,\n"
         "  \"reduced_setpoint_before_loss_kph\": %u,\n"
         "  \"host_command_age_ms\": 301,\n"
         "  \"service_first_after_loss_kph\": %u,\n"
         "  \"frame_first_after_loss_kph\": %u,\n"
         "  \"activation_bit_after_host_loss\": %s,\n"
         "  \"last_reduced_setpoint_retained\": %s,\n"
         "  \"original_cancellation_payload_preserved\": true,\n"
         "  \"hardware_brake_or_power_loss_tested\": false\n"
         "}\n", before, service_after, frame_after, still_active ? "true" : "false",
         service_after == before && frame_after == before ? "true" : "false");
  return 0;
}
