#pragma once

#include <Arduino.h>

#if __has_include("secrets.hpp")
#include "secrets.hpp"
#endif

#ifndef READ_ONLY
#define READ_ONLY 1
#endif

#ifndef USE_MCP2515
#define USE_MCP2515 0
#endif

#ifndef MCP2515_CLOCK_MHZ
#define MCP2515_CLOCK_MHZ 8
#endif

#ifndef CAN_TX_GPIO
#define CAN_TX_GPIO 5
#endif

#ifndef CAN_RX_GPIO
#define CAN_RX_GPIO 4
#endif

#ifndef WIFI_ENABLED
#define WIFI_ENABLED 0
#endif

#ifndef WIFI_AP_SSID
#define WIFI_AP_SSID "OpenDiag-ESP32"
#endif

#ifndef WIFI_AP_PASSWORD
#define WIFI_AP_PASSWORD "opendiag-safe"
#endif

#ifndef WIFI_TCP_PORT
#define WIFI_TCP_PORT 35000
#endif

#ifndef SERIAL_FRAME_MIRROR
#define SERIAL_FRAME_MIRROR 1
#endif

namespace cfg {
constexpr gpio_num_t CAN_TX_PIN = static_cast<gpio_num_t>(CAN_TX_GPIO);
constexpr gpio_num_t CAN_RX_PIN = static_cast<gpio_num_t>(CAN_RX_GPIO);
constexpr uint8_t MCP2515_SPI_SCK_PIN = 18;
constexpr uint8_t MCP2515_SPI_MISO_PIN = 19;
constexpr uint8_t MCP2515_SPI_MOSI_PIN = 23;
constexpr uint8_t MCP2515_SPI_CS_PIN = 5;
// Deliberately conservative for external voltage translators and jumper wires.
constexpr uint32_t MCP2515_SPI_HZ = 1000000;
constexpr uint32_t SERIAL_BAUD = 921600;
constexpr uint32_t STATS_INTERVAL_MS = 1000;
constexpr uint32_t CAN_BITRATE = 500000;
constexpr size_t MAX_FILTER_IDS = 64;
constexpr bool WIFI_ACTIVE = WIFI_ENABLED != 0;
constexpr const char *WIFI_SSID = WIFI_AP_SSID;
constexpr const char *WIFI_PASSWORD = WIFI_AP_PASSWORD;
constexpr uint16_t WIFI_PORT = WIFI_TCP_PORT;
constexpr bool MIRROR_FRAMES_TO_SERIAL = SERIAL_FRAME_MIRROR != 0;
constexpr size_t WIFI_COMMAND_MAX_BYTES = 512;
}
