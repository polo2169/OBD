// Desktop execution of the ESP32 RVV controller. No vehicle or CAN transport.
// A synthetic BSI source supplies each frame; this is not an engine simulator.
#define PSA_ALLOW_RVV_CONTROL 1

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "psa_rvv_safety.hpp"

using psa_rvv_safety::Controller;
using psa_rvv_safety::FrameAction;

static void stock_frame(uint8_t *data, uint8_t setpoint, bool active, uint32_t now) {
  const uint8_t recorded[8] = {0x02, 0x1B, 0x00, 0x14, 0x5E, 0x42, 0x55, 0xA3};
  memcpy(data, recorded, 8);
  data[6] = setpoint;
  data[0] = static_cast<uint8_t>((data[0] & 0xCFU) | (Controller::checksum_for_setpoint(setpoint) << 4));
  data[7] = static_cast<uint8_t>((active ? 0xA0U : 0x20U) | ((now / 50) & 15U));
}

static void print_row(const char *phase, uint32_t now, int target, const uint8_t *stock,
                      const uint8_t *output, const char *action) {
  printf("{\"phase\":\"%s\",\"time_ms\":%u,\"host_target_kph\":%d,"
         "\"stock_setpoint_kph\":%u,\"output_setpoint_kph\":%u,"
         "\"stock_activation\":%s,\"output_activation\":%s,\"action\":\"%s\","
         "\"output_hex\":\"", phase, now, target, stock[6], output[6],
         Controller::decode_activation(stock) ? "true" : "false",
         Controller::decode_activation(output) ? "true" : "false", action);
  for (int i = 0; i < 8; i++) printf("%02X", output[i]);
  puts("\",\"can_transmitted\":false}");
}

int main() {
  Controller control;
  control.reset();
  uint8_t stock[8], output[8];
  stock_frame(stock, 50, true, 100);
  assert(control.set_command(true, 48, 100));
  control.on_stock_frame(stock, 8, 100);
  assert(control.begin_takeover(100));
  int minimum = 50;
  for (uint32_t now = 100; now <= 2600; now += 100) {
    const int target = now < 1600 ? 48 : 50;
    stock_frame(stock, 50, true, now);
    assert(control.set_command(true, target, now));
    control.on_stock_frame(stock, 8, now);
    const FrameAction action = control.build_from_stock(stock, 8, output, now);
    assert(action != FrameAction::Reject);
    assert(output[6] <= 50U);
    assert(Controller::replacement_is_bounded(stock, output));
    assert(Controller::decode_checksum(output) == Controller::checksum_for_setpoint(output[6]));
    if (output[6] < minimum) minimum = output[6];
    print_row(now < 1600 ? "reduction" : "recovery", now, target, stock, output,
              action == FrameAction::Replaced ? "replaced_in_memory" : "stock_in_memory");
  }
  assert(minimum == 48 && output[6] == 50U);

  // Manual 45 km/h ceiling arrives between two 500 ms adjustment ticks.
  stock_frame(stock, 45, true, 2650);
  assert(control.set_command(true, 50, 2650));
  control.on_stock_frame(stock, 8, 2650);
  assert(control.build_from_stock(stock, 8, output, 2650) != FrameAction::Reject);
  assert(output[6] == 45U);
  print_row("lower_manual_ceiling", 2650, 50, stock, output, "stock_in_memory");

  // Cancellation here is injected into the source, not a tested brake switch.
  stock_frame(stock, 255, false, 2700);
  control.on_stock_frame(stock, 8, 2700);
  assert(control.build_from_stock(stock, 8, output, 2700) == FrameAction::Reject);
  assert(control.set_command(false, 40, 2700));
  assert(control.build_from_stock(stock, 8, output, 2700) == FrameAction::PassThrough);
  assert(memcmp(stock, output, 8) == 0);
  print_row("synthetic_stock_cancel", 2700, 40, stock, output, "stock_in_memory");

  // New independent scenario: the lowest allowed setpoint is preserved.
  control.reset();
  stock_frame(stock, 40, true, 3000);
  assert(control.set_command(true, 40, 3000));
  control.on_stock_frame(stock, 8, 3000);
  assert(control.begin_takeover(3000));
  assert(control.build_from_stock(stock, 8, output, 3000) == FrameAction::PassThrough);
  assert(output[6] == 40U);
  print_row("minimum_setpoint", 3000, 40, stock, output, "stock_in_memory");
  assert(!control.set_command(true, 39, 3010));

  // Verify the received frame is rejected before producing a replacement.
  stock[0] ^= 0x10U;
  control.on_stock_frame(stock, 8, 3020);
  assert(!control.ready_for_takeover(3020));
  assert(control.build_from_stock(stock, 8, output, 3020) == FrameAction::Reject);
  return 0;
}
