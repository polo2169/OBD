#pragma once

#include <Arduino.h>

#ifndef PSA_CAN_BITRATE
#define PSA_CAN_BITRATE 500000
#endif

#ifndef PSA_CAN_TX_GPIO
#define PSA_CAN_TX_GPIO 5
#endif

#ifndef PSA_CAN_RX_GPIO
#define PSA_CAN_RX_GPIO 4
#endif

#ifndef PSA_LINK_RX_GPIO
#define PSA_LINK_RX_GPIO 16
#endif

#ifndef PSA_LINK_TX_GPIO
#define PSA_LINK_TX_GPIO 17
#endif

#ifndef PSA_LINK_BAUD
#define PSA_LINK_BAUD 2000000
#endif

#ifndef PSA_SBU1_GPIO
#define PSA_SBU1_GPIO 32
#endif

#ifndef PSA_MADS_ENABLE_GPIO
#define PSA_MADS_ENABLE_GPIO 33
#endif

#ifndef PSA_ALLOW_NONZERO_TORQUE
#define PSA_ALLOW_NONZERO_TORQUE 0
#endif

#ifndef PSA_BENCH_ONLY
#define PSA_BENCH_ONLY 0
#endif

#ifndef PSA_ALLOW_RVV_CONTROL
#define PSA_ALLOW_RVV_CONTROL 0
#endif

#ifndef PSA_MAX_TAKEOVER_MS
#define PSA_MAX_TAKEOVER_MS 400
#endif

#ifndef PSA_MIN_CONTROL_SPEED_KPH
#define PSA_MIN_CONTROL_SPEED_KPH 40
#endif

#ifndef PSA_MAX_CONTROL_SPEED_KPH
#define PSA_MAX_CONTROL_SPEED_KPH 90
#endif

#if PSA_ALLOW_NONZERO_TORQUE && !PSA_BENCH_ONLY
#error "Non-zero torque is only available in an explicitly isolated bench build"
#endif

#if PSA_ALLOW_RVV_CONTROL && !PSA_BENCH_ONLY
#error "Modified RVV setpoints require an explicitly isolated bench build"
#endif

namespace bridge_cfg {

constexpr gpio_num_t CAN_TX_PIN = static_cast<gpio_num_t>(PSA_CAN_TX_GPIO);
constexpr gpio_num_t CAN_RX_PIN = static_cast<gpio_num_t>(PSA_CAN_RX_GPIO);
constexpr int8_t LINK_RX_PIN = PSA_LINK_RX_GPIO;
constexpr int8_t LINK_TX_PIN = PSA_LINK_TX_GPIO;
constexpr uint32_t LINK_BAUD = PSA_LINK_BAUD;
constexpr uint32_t CAN_BITRATE = PSA_CAN_BITRATE;
constexpr gpio_num_t SBU1_PIN = static_cast<gpio_num_t>(PSA_SBU1_GPIO);
constexpr gpio_num_t MADS_ENABLE_PIN = static_cast<gpio_num_t>(PSA_MADS_ENABLE_GPIO);

constexpr uint32_t HOST_SERIAL_BAUD = 921600;
constexpr size_t HOST_RX_LINE_BYTES = 384;
constexpr uint32_t LINK_KEEPALIVE_MS = 40;
constexpr uint32_t LINK_TIMEOUT_MS = 140;
constexpr uint32_t TORQUE_COMMAND_TIMEOUT_MS = 150;
constexpr uint32_t PREPARE_TIMEOUT_MS = 150;
constexpr uint32_t RELAY_SETTLE_MS = 10;
constexpr uint32_t MAX_TAKEOVER_MS = PSA_MAX_TAKEOVER_MS;
constexpr uint32_t LKA_PERIOD_MS = 50;
constexpr uint32_t STATS_PERIOD_MS = 1000;
constexpr uint32_t MADS_PHYSICAL_DEBOUNCE_MS = 50;
constexpr float MIN_CONTROL_SPEED_KPH = PSA_MIN_CONTROL_SPEED_KPH;
constexpr float MAX_CONTROL_SPEED_KPH = PSA_MAX_CONTROL_SPEED_KPH;

constexpr bool ALLOW_NONZERO_TORQUE = PSA_ALLOW_NONZERO_TORQUE != 0;
constexpr bool ALLOW_RVV_CONTROL = PSA_ALLOW_RVV_CONTROL != 0;
constexpr bool BENCH_ONLY = PSA_BENCH_ONLY != 0;

}  // namespace bridge_cfg
