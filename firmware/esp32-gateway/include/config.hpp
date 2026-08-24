#pragma once

#include <Arduino.h>

#if __has_include("secrets.hpp")
#include "secrets.hpp"
#endif

#ifndef READ_ONLY
#define READ_ONLY 1
#endif

// Allows CAN transmission, but only for a small, firmware-enforced set of
// read-only ISO-TP/UDS/OBD requests. This is intentionally independent from
// the PC-side safety filter.
#ifndef DIAGNOSTIC_READ_ONLY
#define DIAGNOSTIC_READ_ONLY 0
#endif

// Experimental PSA profile: read-only diagnostics plus an exact allowlist of
// named NAC actions, PSA configuration security access and DTC clear FFFFFF.
// It never permits a raw 0x2F/0x27/0x14 payload chosen by the host.
#ifndef PSA_LAB
#define PSA_LAB 0
#endif

#if READ_ONLY && (DIAGNOSTIC_READ_ONLY || PSA_LAB)
#error "READ_ONLY is mutually exclusive with diagnostic transmit modes"
#endif

#if DIAGNOSTIC_READ_ONLY && PSA_LAB
#error "DIAGNOSTIC_READ_ONLY and PSA_LAB are mutually exclusive firmware modes"
#endif

#ifndef USE_MCP2515
#define USE_MCP2515 0
#endif

// Keep the native ESP32 TWAI controller on the vehicle CAN (OBD 6/14) and
// add an external MCP2515 for the PSA diagnostic CAN (OBD 3/8).
#ifndef DUAL_CAN
#define DUAL_CAN 0
#endif

// A standalone ESP32 can be assigned to either physical vehicle network.
// The role is announced in the hello packet and stamped on every received
// frame so two USB gateways can be merged safely by the PC backend.
#ifndef CAN_BUS_ROLE_DIAGNOSTIC
#define CAN_BUS_ROLE_DIAGNOSTIC 0
#endif

// Enables the native OBD 6/14 controller in normal mode while retaining a
// firmware allowlist limited to standardized 11-bit and 29-bit functional and
// engine-physical OBD Mode 01/03/07/09 reads. ISO-TP flow control remains physical.
// All UDS, clear-DTC and actuator traffic remains locked there.
#ifndef LIVE_OBD_READ_ONLY
#define LIVE_OBD_READ_ONLY 0
#endif

#if LIVE_OBD_READ_ONLY && READ_ONLY
#error "LIVE_OBD_READ_ONLY requires a TX-capable, firmware-filtered build"
#endif

#if LIVE_OBD_READ_ONLY && CAN_BUS_ROLE_DIAGNOSTIC
#error "LIVE_OBD_READ_ONLY must only be enabled on the OBD 6/14 controller"
#endif

// Two native ESP32/TWAI controllers can form one logical dual-CAN gateway.
// The main board owns OBD 6/14 and the PC USB link; the satellite owns OBD 3/8.
#ifndef UART_DUAL_CAN_MASTER
#define UART_DUAL_CAN_MASTER 0
#endif

#ifndef UART_DUAL_CAN_SATELLITE
#define UART_DUAL_CAN_SATELLITE 0
#endif

#if UART_DUAL_CAN_MASTER && UART_DUAL_CAN_SATELLITE
#error "An ESP32 cannot be both UART dual-CAN master and satellite"
#endif

#if UART_DUAL_CAN_MASTER && (DUAL_CAN || USE_MCP2515)
#error "UART dual-CAN master uses native TWAI only; disable MCP2515/DUAL_CAN"
#endif

#if UART_DUAL_CAN_SATELLITE && !CAN_BUS_ROLE_DIAGNOSTIC
#error "UART dual-CAN satellite must use CAN_BUS_ROLE_DIAGNOSTIC=1"
#endif

#if DUAL_CAN && USE_MCP2515
#error "DUAL_CAN already enables the MCP2515 next to TWAI; do not set USE_MCP2515"
#endif

#ifndef MCP2515_CLOCK_MHZ
#define MCP2515_CLOCK_MHZ 8
#endif

#ifndef MCP2515_SPI_CS_GPIO
#if DUAL_CAN
#define MCP2515_SPI_CS_GPIO 27
#else
#define MCP2515_SPI_CS_GPIO 5
#endif
#endif

#ifndef MCP2515_INT_GPIO
#define MCP2515_INT_GPIO 26
#endif

#ifndef MCP2515_SPI_SPEED_HZ
#define MCP2515_SPI_SPEED_HZ 1000000
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

#ifndef INTERBOARD_UART_RX_GPIO
#define INTERBOARD_UART_RX_GPIO 16
#endif

#ifndef INTERBOARD_UART_TX_GPIO
#define INTERBOARD_UART_TX_GPIO 17
#endif

#ifndef INTERBOARD_UART_BAUD
#define INTERBOARD_UART_BAUD 2000000
#endif

namespace cfg {
constexpr gpio_num_t CAN_TX_PIN = static_cast<gpio_num_t>(CAN_TX_GPIO);
constexpr gpio_num_t CAN_RX_PIN = static_cast<gpio_num_t>(CAN_RX_GPIO);
constexpr bool NATIVE_CAN_IS_DIAGNOSTIC = CAN_BUS_ROLE_DIAGNOSTIC != 0;
constexpr bool LIVE_OBD_READ_ENABLED = LIVE_OBD_READ_ONLY != 0;
constexpr bool UART_MASTER = UART_DUAL_CAN_MASTER != 0;
constexpr bool UART_SATELLITE = UART_DUAL_CAN_SATELLITE != 0;
constexpr int8_t INTERBOARD_RX_PIN = INTERBOARD_UART_RX_GPIO;
constexpr int8_t INTERBOARD_TX_PIN = INTERBOARD_UART_TX_GPIO;
constexpr uint32_t INTERBOARD_BAUD = INTERBOARD_UART_BAUD;
constexpr uint8_t MCP2515_SPI_SCK_PIN = 18;
constexpr uint8_t MCP2515_SPI_MISO_PIN = 19;
constexpr uint8_t MCP2515_SPI_MOSI_PIN = 23;
constexpr uint8_t MCP2515_SPI_CS_PIN = MCP2515_SPI_CS_GPIO;
constexpr uint8_t MCP2515_INTERRUPT_PIN = MCP2515_INT_GPIO;
constexpr uint32_t MCP2515_SPI_HZ = MCP2515_SPI_SPEED_HZ;
constexpr uint32_t SERIAL_BAUD = 921600;
constexpr size_t SERIAL_TX_BUFFER_BYTES = 8192;
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
