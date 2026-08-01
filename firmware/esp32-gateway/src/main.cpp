#include <Arduino.h>
#include <ArduinoJson.h>
#include <esp_system.h>
#include "config.hpp"

#if WIFI_ENABLED
#include <WiFi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#endif

#if USE_MCP2515 || DUAL_CAN
#include <SPI.h>
#include <mcp2515.h>
#endif

#if !USE_MCP2515 || DUAL_CAN
#include <driver/twai.h>
#endif

static uint32_t rx_count = 0;
static uint32_t tx_count = 0;
static uint32_t tx_failed_count = 0;
static uint32_t tx_policy_blocked_count = 0;
static uint32_t dropped_count = 0;
static uint32_t filtered_count = 0;
static uint32_t bus_off_count = 0;
static uint32_t bus_recovered_count = 0;
static uint32_t frame_sequence = 0;
static uint32_t last_alerts = 0;
static uint32_t last_stats_ms = 0;
static bool can_ready = false;
static bool live_can_ready = false;
static bool diagnostic_can_ready = false;

#if UART_DUAL_CAN_MASTER || UART_DUAL_CAN_SATELLITE
static HardwareSerial interboard_uart(2);
static char interboard_rx_line[1536]{};
static size_t interboard_rx_length = 0;
static bool interboard_rx_discard = false;
static uint32_t interboard_overflow_count = 0;
#endif

#if UART_DUAL_CAN_MASTER
static bool satellite_connected = false;
static bool satellite_diagnostic_read_only = false;
static bool satellite_psa_lab = false;
static uint32_t satellite_last_message_ms = 0;
static uint32_t satellite_last_request_ms = 0;
static uint32_t satellite_rx_count = 0;
static uint32_t satellite_tx_count = 0;
static uint32_t satellite_dropped_count = 0;
static char satellite_tx_policy[48] = "unavailable";
#endif

#if USE_MCP2515 || DUAL_CAN
// 0 not started, 1 reset, 2 bitrate, 3 operating mode, 4 ready.
static uint8_t mcp2515_init_stage = 0;
static int8_t mcp2515_init_error = 0;
#endif

#if DUAL_CAN
static uint32_t live_rx_count = 0;
static uint32_t diagnostic_rx_count = 0;
static uint32_t live_dropped_count = 0;
static uint32_t diagnostic_dropped_count = 0;
static uint32_t live_filtered_count = 0;
static uint32_t diagnostic_tx_count = 0;
static uint32_t diagnostic_tx_failed_count = 0;
static uint32_t live_last_alerts = 0;
static uint8_t diagnostic_last_error_flags = 0;
#endif

#if PSA_LAB
static bool psa_deadman_armed = false;
static uint32_t psa_deadman_deadline_ms = 0;
static uint8_t psa_deadman_attempts = 0;
static uint8_t psa_deadman_stop_data[8]{};
static uint8_t psa_deadman_stop_length = 0;
constexpr uint32_t PSA_DEADMAN_MS = 3500;
constexpr uint8_t PSA_DEADMAN_MAX_ATTEMPTS = 30;
#endif

namespace {
// Dual-CAN hello/stats packets include per-bus health and SPI wiring metadata.
// Leave enough room for the complete JSON object so the backend can diagnose a
// failed MCP2515 instead of receiving HELLO_OVERFLOW/JSON_OVERFLOW.
constexpr size_t OUTPUT_PACKET_MAX_BYTES = 1536;

enum class CanChannel : uint8_t {
  Live = 0,
  Diagnostic = 1,
};

static const char *channel_name(CanChannel channel) {
  return channel == CanChannel::Diagnostic ? "diagnostic" : "live";
}

static constexpr CanChannel native_can_channel() {
  return cfg::NATIVE_CAN_IS_DIAGNOSTIC
      ? CanChannel::Diagnostic
      : CanChannel::Live;
}

#if DIAGNOSTIC_READ_ONLY || PSA_LAB
// Peugeot 308 T9 diagnostic request identifiers documented in the selected
// vehicle profile. No broadcast, extended or arbitrary CAN identifiers.
constexpr uint16_t DIAGNOSTIC_REQUEST_IDS[] = {
    0x6A8, 0x6A9, 0x6AA, 0x6AD, 0x6AF, 0x6B5, 0x6B6,
    0x730, 0x744, 0x74A, 0x752, 0x75D, 0x75F, 0x764,
    0x76D, 0x796, 0x7B0, 0x7E0,
};

static bool diagnostic_request_id_allowed(uint32_t id) {
  for (const uint16_t allowed : DIAGNOSTIC_REQUEST_IDS) {
    if (id == allowed) return true;
  }
  return false;
}

#if PSA_LAB
static bool psa_lab_payload_equals(
    const uint8_t *payload,
    uint8_t application_length,
    const uint8_t *expected,
    size_t expected_length) {
  return application_length == expected_length
      && memcmp(payload + 1, expected, expected_length) == 0;
}

static bool psa_lab_named_action_allowed(
    uint32_t id,
    const uint8_t *payload,
    uint8_t application_length) {
  if (id != 0x764) return false;
  static const uint8_t ACTIONS[][5] = {
      {0x2F, 0xD6, 0x00, 0x03, 0x00},
      {0x2F, 0xD6, 0x70, 0x03, 0x30},
      {0x2F, 0xD6, 0x70, 0x03, 0x40},
      {0x2F, 0xD6, 0x70, 0x03, 0x50},
  };
  for (const auto &action : ACTIONS) {
    if (psa_lab_payload_equals(payload, application_length, action, sizeof(action))) return true;
  }
  static const uint8_t SHORT_ACTIONS[][4] = {
      {0x2F, 0xD6, 0x00, 0x00},
      {0x2F, 0xD6, 0x60, 0x03},
      {0x2F, 0xD6, 0x60, 0x00},
  };
  for (const auto &action : SHORT_ACTIONS) {
    if (psa_lab_payload_equals(payload, application_length, action, sizeof(action))) return true;
  }
  return false;
}
#endif

static const char *diagnostic_tx_rejection(
    uint32_t id,
    bool extended,
    const uint8_t *payload,
    size_t length) {
  if (extended) return "extended CAN identifiers are locked";
  if (!diagnostic_request_id_allowed(id)) return "CAN identifier is not a known diagnostic request";
  if (length == 0 || length > 8) return "invalid ISO-TP frame length";

  const uint8_t pci_type = payload[0] >> 4;
  if (pci_type == 0x3) {
    // Flow-control frames are needed to receive long identification/DTC
    // responses. They do not carry a diagnostic service.
    if (length < 3 || (payload[0] & 0x0F) > 0x02) {
      return "invalid ISO-TP flow-control frame";
    }
    return nullptr;
  }
  // Read requests used here fit in one CAN frame. Blocking host-originated
  // first/consecutive frames prevents a forbidden service being fragmented.
  if (pci_type != 0x0) return "multi-frame diagnostic requests are locked";

  const uint8_t application_length = payload[0] & 0x0F;
  if (application_length == 0 || application_length > 7 || length < application_length + 1) {
    return "invalid ISO-TP single frame";
  }
  const uint8_t service = payload[1];
  if (id == 0x7E0) {
    if ((service == 0x01 || service == 0x09) && application_length == 2) return nullptr;
    return "only OBD sensor and vehicle-information reads are allowed on 0x7E0";
  }

  switch (service) {
    case 0x10: {
      if (application_length != 2) return "invalid DiagnosticSessionControl request";
      const uint8_t session = payload[2] & 0x7F;
      return (session == 0x01 || session == 0x03)
          ? nullptr
          : "programming or supplier sessions are locked";
    }
    case 0x19:
      return application_length >= 2 ? nullptr : "invalid ReadDTCInformation request";
    case 0x22:
      return application_length == 3 ? nullptr : "invalid ReadDataByIdentifier request";
    case 0x3E:
      return application_length == 2 && (payload[2] == 0x00 || payload[2] == 0x80)
          ? nullptr
          : "invalid TesterPresent request";
#if PSA_LAB
    case 0x27:
      if (id != 0x752 && id != 0x764) return "security access is limited to BSI and telematics";
      if (application_length == 2 && payload[2] == 0x03) return nullptr;
      if (application_length == 6 && payload[2] == 0x04) return nullptr;
      return "only PSA configuration security access 0x27/03-04 is allowed";
    case 0x2F:
      return psa_lab_named_action_allowed(id, payload, application_length)
          ? nullptr
          : "IOControl payload is not a named PSA lab action";
#endif
    default:
      return "diagnostic service is locked by firmware";
  }
}
#endif
}

#if WIFI_ENABLED
namespace {
constexpr size_t WIFI_PACKET_QUEUE_LENGTH = 64;
constexpr size_t WIFI_COMMAND_QUEUE_LENGTH = 8;

struct WifiPacket {
  uint16_t length;
  char bytes[OUTPUT_PACKET_MAX_BYTES];
};

struct WifiCommand {
  char json[cfg::WIFI_COMMAND_MAX_BYTES + 1];
};
}

static WiFiServer wifi_server(cfg::WIFI_PORT);
static QueueHandle_t wifi_packet_queue = nullptr;
static QueueHandle_t wifi_command_queue = nullptr;
static TaskHandle_t wifi_task_handle = nullptr;
static volatile bool wifi_ready = false;
static volatile bool wifi_client_connected = false;
static volatile uint32_t wifi_connections = 0;
static volatile uint32_t wifi_dropped_messages = 0;
static volatile uint32_t wifi_write_failures = 0;
static volatile uint32_t wifi_command_overflows = 0;
static char wifi_ip[16] = "0.0.0.0";
#endif

#if USE_MCP2515 || DUAL_CAN
static MCP2515 mcp2515(cfg::MCP2515_SPI_CS_PIN, cfg::MCP2515_SPI_HZ);
static uint8_t last_mcp_error_flags = 0;
#endif

static uint32_t filter_ids[cfg::MAX_FILTER_IDS];
static size_t filter_count = 0;

static size_t format_hello(char *output, size_t capacity);
static void parse_command(const String &line);

#if UART_DUAL_CAN_MASTER || UART_DUAL_CAN_SATELLITE
static void poll_interboard_uart();
static void start_interboard_uart();
#endif

static void emit_line(const char *line, bool frame = false) {
  if (!frame || cfg::MIRROR_FRAMES_TO_SERIAL) {
    Serial.println(line);
  }
#if UART_DUAL_CAN_SATELLITE
  interboard_uart.println(line);
#endif
#if WIFI_ENABLED
  if (!wifi_client_connected || wifi_packet_queue == nullptr) return;
  const size_t length = strlen(line);
  if (length + 1 > OUTPUT_PACKET_MAX_BYTES) {
    ++wifi_dropped_messages;
    return;
  }
  WifiPacket packet{};
  packet.length = static_cast<uint16_t>(length + 1);
  memcpy(packet.bytes, line, length);
  packet.bytes[length] = '\n';
  if (xQueueSend(wifi_packet_queue, &packet, 0) != pdTRUE) {
    ++wifi_dropped_messages;
  }
#else
  (void)frame;
#endif
}

static void emit_json(JsonDocument &doc, bool frame = false) {
  char output[OUTPUT_PACKET_MAX_BYTES];
  const size_t length = serializeJson(doc, output, sizeof(output));
  if (length == 0 || length >= sizeof(output)) {
#if WIFI_ENABLED
    ++wifi_dropped_messages;
#endif
    Serial.println("{\"type\":\"error\",\"code\":\"JSON_OVERFLOW\"}");
    return;
  }
  emit_line(output, frame);
}

static bool id_allowed(uint32_t id) {
  if (filter_count == 0) return true;
  for (size_t i = 0; i < filter_count; ++i) {
    if (filter_ids[i] == id) return true;
  }
  return false;
}

static size_t format_hello(char *output, size_t capacity) {
  JsonDocument doc;
  doc["type"] = "hello";
  doc["protocol"] = (DUAL_CAN || cfg::UART_MASTER) ? 7 : 6;
  doc["device"] = "opendiag-esp32";
  doc["firmware"] = READ_ONLY
      ? "0.9.0-passive"
      : (DIAGNOSTIC_READ_ONLY
          ? "0.9.0-multibrand-readonly"
          : (PSA_LAB ? "0.9.0-psa-lab-allowlist" : "0.9.0-active"));
  doc["driver"] = DUAL_CAN
      ? "twai+mcp2515"
      : (cfg::UART_MASTER ? "twai+uart-twai" : (USE_MCP2515 ? "mcp2515" : "twai"));
  doc["can_ready"] = can_ready;
  doc["dual_can"] = (DUAL_CAN != 0) || cfg::UART_MASTER;
#if UART_DUAL_CAN_MASTER
  doc["live_can_ready"] = live_can_ready;
  doc["diagnostic_can_ready"] = diagnostic_can_ready;
  doc["live_listen_only"] = true;
  doc["live_bus"] = "obd_6_14";
  doc["diagnostic_bus"] = "obd_3_8";
  doc["satellite_connected"] = satellite_connected;
  doc["readonly"] = false;
  doc["diagnostic_read_only"] = satellite_diagnostic_read_only;
  doc["psa_lab"] = satellite_psa_lab;
  doc["write_services_locked"] = true;
  doc["tx_policy"] = satellite_tx_policy;
#elif !DUAL_CAN && !USE_MCP2515
  doc["bus_role"] = channel_name(native_can_channel());
  doc["obd_bus"] = cfg::NATIVE_CAN_IS_DIAGNOSTIC ? "obd_3_8" : "obd_6_14";
  doc["live_can_ready"] = cfg::NATIVE_CAN_IS_DIAGNOSTIC ? false : can_ready;
  doc["diagnostic_can_ready"] = cfg::NATIVE_CAN_IS_DIAGNOSTIC ? can_ready : false;
#endif
#if DUAL_CAN
  doc["live_can_ready"] = live_can_ready;
  doc["diagnostic_can_ready"] = diagnostic_can_ready;
  doc["live_listen_only"] = true;
  doc["live_bus"] = "obd_6_14";
  doc["diagnostic_bus"] = "obd_3_8";
#endif
  doc["readonly"] = READ_ONLY != 0;
  doc["diagnostic_read_only"] = DIAGNOSTIC_READ_ONLY != 0;
  doc["psa_lab"] = PSA_LAB != 0;
  doc["write_services_locked"] = (READ_ONLY != 0) || (DIAGNOSTIC_READ_ONLY != 0) || (PSA_LAB != 0);
  doc["tx_policy"] = READ_ONLY
      ? "strict_passive"
      : (DIAGNOSTIC_READ_ONLY
          ? "read_only_diagnostics"
          : (PSA_LAB ? "psa_lab_named_actions" : "unrestricted"));
#if UART_DUAL_CAN_MASTER
  // The main board is passive on 6/14; the satellite's hardware-enforced
  // policy is the capability exposed to the PC for diagnostic transmissions.
  doc["readonly"] = false;
  doc["diagnostic_read_only"] = satellite_diagnostic_read_only;
  doc["psa_lab"] = satellite_psa_lab;
  doc["write_services_locked"] = true;
  doc["tx_policy"] = satellite_tx_policy;
#endif
#if PSA_LAB
  doc["deadman_ms"] = PSA_DEADMAN_MS;
#endif
  doc["bitrate"] = cfg::CAN_BITRATE;
#if USE_MCP2515 || DUAL_CAN
  doc["spi_sck_pin"] = cfg::MCP2515_SPI_SCK_PIN;
  doc["spi_miso_pin"] = cfg::MCP2515_SPI_MISO_PIN;
  doc["spi_mosi_pin"] = cfg::MCP2515_SPI_MOSI_PIN;
  doc["spi_cs_pin"] = cfg::MCP2515_SPI_CS_PIN;
  doc["spi_int_pin"] = cfg::MCP2515_INTERRUPT_PIN;
  doc["spi_hz"] = cfg::MCP2515_SPI_HZ;
  doc["oscillator_mhz"] = MCP2515_CLOCK_MHZ;
  doc["mcp2515_init_stage"] = mcp2515_init_stage;
  doc["mcp2515_init_error"] = mcp2515_init_error;
#endif
#if !USE_MCP2515 || DUAL_CAN
  doc["tx_pin"] = static_cast<int>(cfg::CAN_TX_PIN);
  doc["rx_pin"] = static_cast<int>(cfg::CAN_RX_PIN);
#endif
#if UART_DUAL_CAN_MASTER || UART_DUAL_CAN_SATELLITE
  doc["interboard_uart"] = cfg::UART_MASTER ? "master" : "satellite";
  doc["interboard_rx_pin"] = cfg::INTERBOARD_RX_PIN;
  doc["interboard_tx_pin"] = cfg::INTERBOARD_TX_PIN;
  doc["interboard_baud"] = cfg::INTERBOARD_BAUD;
#endif
  doc["reset_reason"] = static_cast<int>(esp_reset_reason());
#if WIFI_ENABLED
  doc["wifi_enabled"] = true;
  doc["wifi_ready"] = wifi_ready;
  doc["wifi_mode"] = "access_point";
  doc["wifi_ssid"] = cfg::WIFI_SSID;
  doc["wifi_ip"] = wifi_ip;
  doc["wifi_port"] = cfg::WIFI_PORT;
#else
  doc["wifi_enabled"] = false;
#endif
  return serializeJson(doc, output, capacity);
}

static void emit_hello() {
  char output[OUTPUT_PACKET_MAX_BYTES];
  const size_t length = format_hello(output, sizeof(output));
  if (length == 0 || length >= sizeof(output)) {
    emit_line("{\"type\":\"error\",\"code\":\"HELLO_OVERFLOW\"}");
    return;
  }
  emit_line(output);
}

static void emit_error(const char *code, const char *message) {
  JsonDocument doc;
  doc["type"] = "error";
  doc["code"] = code;
  doc["message"] = message;
  emit_json(doc);
}

static void emit_stats() {
  JsonDocument doc;
  doc["type"] = "stats";
  doc["rx"] = rx_count;
  doc["tx"] = tx_count;
  doc["tx_policy_blocked"] = tx_policy_blocked_count;
  doc["filtered"] = filtered_count;
  doc["bus_off"] = bus_off_count;
  doc["bus_recovered"] = bus_recovered_count;
#if DUAL_CAN
  twai_status_info_t live_status{};
  const esp_err_t live_status_result = live_can_ready
      ? twai_get_status_info(&live_status)
      : ESP_ERR_INVALID_STATE;
  const uint8_t diagnostic_error_flags = diagnostic_can_ready ? mcp2515.getErrorFlags() : 0;
  doc["live_rx"] = live_rx_count;
  doc["diagnostic_rx"] = diagnostic_rx_count;
  doc["live_filtered"] = live_filtered_count;
  doc["live_dropped"] = live_dropped_count
      + live_status.rx_missed_count
      + live_status.rx_overrun_count;
  doc["diagnostic_dropped"] = diagnostic_dropped_count;
  doc["diagnostic_tx"] = diagnostic_tx_count;
  doc["diagnostic_tx_failed"] = diagnostic_tx_failed_count;
  doc["tx_failed"] = diagnostic_tx_failed_count;
  doc["dropped"] = doc["live_dropped"].as<uint32_t>() + diagnostic_dropped_count;
  doc["state"] = static_cast<int>(live_status.state);
  doc["rx_queue"] = live_status.msgs_to_rx;
  doc["tx_queue"] = 0;
  doc["rx_error_counter"] = live_status.rx_error_counter;
  doc["tx_error_counter"] = live_status.tx_error_counter;
  doc["bus_error_count"] = live_status.bus_error_count;
  doc["arb_lost_count"] = live_status.arb_lost_count;
  doc["last_alerts"] = live_last_alerts;
  doc["mcp2515_error_flags"] = diagnostic_error_flags;
  doc["diagnostic_rx_error_counter"] = diagnostic_can_ready ? mcp2515.errorCountRX() : 0;
  doc["diagnostic_tx_error_counter"] = diagnostic_can_ready ? mcp2515.errorCountTX() : 0;
  doc["live_status_result"] = static_cast<int>(live_status_result);
  doc["diagnostic_status_result"] = diagnostic_can_ready ? 0 : -1;
  doc["mcp2515_init_stage"] = mcp2515_init_stage;
  doc["mcp2515_init_error"] = mcp2515_init_error;
#elif USE_MCP2515
  const uint8_t error_flags = can_ready ? mcp2515.getErrorFlags() : 0;
  const uint8_t rx_error_counter = can_ready ? mcp2515.errorCountRX() : 0;
  const uint8_t tx_error_counter = can_ready ? mcp2515.errorCountTX() : 0;
  doc["tx_failed"] = tx_failed_count;
  doc["dropped"] = dropped_count;
  doc["state"] = can_ready ? ((error_flags & MCP2515::EFLG_TXBO) ? 3 : 1) : 0;
  doc["rx_queue"] = 0;
  doc["tx_queue"] = 0;
  doc["rx_error_counter"] = rx_error_counter;
  doc["tx_error_counter"] = tx_error_counter;
  doc["bus_error_count"] = error_flags ? 1 : 0;
  doc["arb_lost_count"] = 0;
  doc["last_alerts"] = last_alerts;
  doc["mcp2515_error_flags"] = error_flags;
  doc["status_result"] = can_ready ? 0 : -1;
#else
  twai_status_info_t status{};
  const esp_err_t status_result = can_ready
      ? twai_get_status_info(&status)
      : ESP_ERR_INVALID_STATE;
  doc["tx_failed"] = tx_failed_count + status.tx_failed_count;
  doc["dropped"] = dropped_count + status.rx_missed_count + status.rx_overrun_count;
  doc["state"] = static_cast<int>(status.state);
  doc["rx_queue"] = status.msgs_to_rx;
  doc["tx_queue"] = status.msgs_to_tx;
  doc["rx_error_counter"] = status.rx_error_counter;
  doc["tx_error_counter"] = status.tx_error_counter;
  doc["bus_error_count"] = status.bus_error_count;
  doc["arb_lost_count"] = status.arb_lost_count;
  doc["last_alerts"] = last_alerts;
  doc["status_result"] = static_cast<int>(status_result);
#endif
  doc["free_heap"] = ESP.getFreeHeap();
  doc["uptime_ms"] = millis();
#if UART_DUAL_CAN_MASTER
  doc["live_rx"] = rx_count;
  doc["diagnostic_rx"] = satellite_rx_count;
  doc["diagnostic_tx"] = satellite_tx_count;
  doc["diagnostic_dropped"] = satellite_dropped_count;
  doc["diagnostic_can_ready"] = diagnostic_can_ready;
  doc["satellite_connected"] = satellite_connected;
  doc["interboard_overflow"] = interboard_overflow_count;
#elif UART_DUAL_CAN_SATELLITE
  doc["interboard_overflow"] = interboard_overflow_count;
#endif
#if WIFI_ENABLED
  doc["wifi_ready"] = wifi_ready;
  doc["wifi_client"] = wifi_client_connected;
  doc["wifi_connections"] = wifi_connections;
  doc["wifi_dropped_messages"] = wifi_dropped_messages;
  doc["wifi_write_failures"] = wifi_write_failures;
  doc["wifi_command_overflows"] = wifi_command_overflows;
  doc["wifi_queue"] = wifi_packet_queue == nullptr
      ? 0
      : static_cast<uint32_t>(uxQueueMessagesWaiting(wifi_packet_queue));
#endif
  emit_json(doc);
}

static void emit_can_status(CanChannel channel, const char *reason, uint32_t alerts) {
#if DUAL_CAN
  JsonDocument doc;
  doc["type"] = "can_status";
  doc["bus"] = channel_name(channel);
  doc["reason"] = reason;
  doc["alerts"] = alerts;
  if (channel == CanChannel::Diagnostic) {
    doc["driver"] = "mcp2515";
    doc["state"] = (alerts & MCP2515::EFLG_TXBO) ? 3 : 1;
    doc["rx_error_counter"] = mcp2515.errorCountRX();
    doc["tx_error_counter"] = mcp2515.errorCountTX();
  } else {
    twai_status_info_t status{};
    twai_get_status_info(&status);
    doc["driver"] = "twai";
    doc["state"] = static_cast<int>(status.state);
    doc["rx_queue"] = status.msgs_to_rx;
    doc["tx_queue"] = status.msgs_to_tx;
    doc["rx_error_counter"] = status.rx_error_counter;
    doc["tx_error_counter"] = status.tx_error_counter;
  }
#elif USE_MCP2515
  JsonDocument doc;
  doc["type"] = "can_status";
  doc["bus"] = channel_name(channel);
  doc["driver"] = "mcp2515";
  doc["reason"] = reason;
  doc["alerts"] = alerts;
  doc["state"] = (alerts & MCP2515::EFLG_TXBO) ? 3 : 1;
  doc["rx_error_counter"] = mcp2515.errorCountRX();
  doc["tx_error_counter"] = mcp2515.errorCountTX();
#else
  twai_status_info_t status{};
  twai_get_status_info(&status);
  JsonDocument doc;
  doc["type"] = "can_status";
  doc["bus"] = channel_name(channel);
  doc["driver"] = "twai";
  doc["reason"] = reason;
  doc["alerts"] = alerts;
  doc["state"] = static_cast<int>(status.state);
  doc["rx_queue"] = status.msgs_to_rx;
  doc["tx_queue"] = status.msgs_to_tx;
  doc["rx_error_counter"] = status.rx_error_counter;
  doc["tx_error_counter"] = status.tx_error_counter;
#endif
  emit_json(doc);
}

static void emit_frame(
    CanChannel channel,
    uint32_t identifier,
    bool extended,
    uint8_t data_length,
    bool remote,
    const uint8_t *data) {
  char data_hex[17]{};
  if (!remote) {
    for (uint8_t i = 0; i < data_length; ++i) {
      static const char hex[] = "0123456789ABCDEF";
      data_hex[i * 2] = hex[(data[i] >> 4) & 0x0F];
      data_hex[i * 2 + 1] = hex[data[i] & 0x0F];
    }
  }
  // Protocol v6 uses a compact, hexadecimal transport line for CAN frames:
  // F,timestamp,sequence,id,flags,data. Protocol v7 reserves flag 0x40 for
  // the diagnostic MCP2515 channel; older parsers still accept live frames.
  const uint8_t flags = static_cast<uint8_t>(
      (data_length << 2)
      | (extended ? 0x01 : 0x00)
      | (remote ? 0x02 : 0x00)
      | (channel == CanChannel::Diagnostic ? 0x40 : 0x00));
  char output[96];
  const int length = snprintf(
      output,
      sizeof(output),
      "F,%llX,%lX,%lX,%X,%s",
      static_cast<unsigned long long>(esp_timer_get_time()),
      static_cast<unsigned long>(frame_sequence++),
      static_cast<unsigned long>(identifier),
      flags,
      data_hex);
  if (length <= 0 || static_cast<size_t>(length) >= sizeof(output)) {
    emit_error("FRAME_OVERFLOW", "Compact CAN frame exceeds output buffer");
    return;
  }
  emit_line(output, true);
}

static int hex_nibble(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  return -1;
}

static bool decode_hex(const char *text, uint8_t *output, size_t &length) {
  const size_t chars = strlen(text);
  if (chars > 16 || (chars % 2) != 0) return false;
  length = chars / 2;
  for (size_t index = 0; index < length; ++index) {
    const int high = hex_nibble(text[index * 2]);
    const int low = hex_nibble(text[index * 2 + 1]);
    if (high < 0 || low < 0) return false;
    output[index] = static_cast<uint8_t>((high << 4) | low);
  }
  return true;
}

#if PSA_LAB
static void psa_lab_disarm_deadman() {
  psa_deadman_armed = false;
  psa_deadman_deadline_ms = 0;
  psa_deadman_attempts = 0;
  psa_deadman_stop_length = 0;
  memset(psa_deadman_stop_data, 0, sizeof(psa_deadman_stop_data));
}

static void psa_lab_arm_deadman(const uint8_t *stop_uds, size_t stop_uds_length) {
  memset(psa_deadman_stop_data, 0, sizeof(psa_deadman_stop_data));
  psa_deadman_stop_data[0] = static_cast<uint8_t>(stop_uds_length);
  memcpy(psa_deadman_stop_data + 1, stop_uds, stop_uds_length);
  // Match the padded ISO-TP frames emitted by the PC stack.
  psa_deadman_stop_length = 8;
  psa_deadman_deadline_ms = millis() + PSA_DEADMAN_MS;
  psa_deadman_attempts = 0;
  psa_deadman_armed = true;
}

static void psa_lab_update_deadman_after_host_tx(
    uint32_t id,
    const uint8_t *payload,
    size_t length) {
  if (id != 0x764 || length < 2 || (payload[0] >> 4) != 0x0) return;
  const uint8_t application_length = payload[0] & 0x0F;
  static const uint8_t SCREEN_START[] = {0x2F, 0xD6, 0x00, 0x03, 0x00};
  static const uint8_t SCREEN_STOP[] = {0x2F, 0xD6, 0x00, 0x00};
  static const uint8_t CAMERA_START[] = {0x2F, 0xD6, 0x60, 0x03};
  static const uint8_t CAMERA_STOP[] = {0x2F, 0xD6, 0x60, 0x00};
  static const uint8_t CAMERA_STANDARD[] = {0x2F, 0xD6, 0x70, 0x03, 0x30};
  static const uint8_t CAMERA_ZOOM[] = {0x2F, 0xD6, 0x70, 0x03, 0x40};
  static const uint8_t CAMERA_LATERAL[] = {0x2F, 0xD6, 0x70, 0x03, 0x50};

  if (psa_lab_payload_equals(payload, application_length, SCREEN_START, sizeof(SCREEN_START))) {
    psa_lab_arm_deadman(SCREEN_STOP, sizeof(SCREEN_STOP));
    return;
  }
  if (
      psa_lab_payload_equals(payload, application_length, CAMERA_START, sizeof(CAMERA_START))
      || psa_lab_payload_equals(payload, application_length, CAMERA_STANDARD, sizeof(CAMERA_STANDARD))
      || psa_lab_payload_equals(payload, application_length, CAMERA_ZOOM, sizeof(CAMERA_ZOOM))
      || psa_lab_payload_equals(payload, application_length, CAMERA_LATERAL, sizeof(CAMERA_LATERAL))) {
    psa_lab_arm_deadman(CAMERA_STOP, sizeof(CAMERA_STOP));
    return;
  }
  if (
      psa_lab_payload_equals(payload, application_length, SCREEN_STOP, sizeof(SCREEN_STOP))
      || psa_lab_payload_equals(payload, application_length, CAMERA_STOP, sizeof(CAMERA_STOP))) {
    psa_lab_disarm_deadman();
  }
}

static bool psa_lab_transmit_deadman_stop() {
#if USE_MCP2515 || DUAL_CAN
  struct can_frame frame{};
  frame.can_id = 0x764;
  frame.can_dlc = psa_deadman_stop_length;
  memcpy(frame.data, psa_deadman_stop_data, psa_deadman_stop_length);
  const bool sent = mcp2515.sendMessage(&frame) == MCP2515::ERROR_OK;
#else
  twai_message_t message{};
  message.identifier = 0x764;
  message.extd = false;
  message.data_length_code = psa_deadman_stop_length;
  memcpy(message.data, psa_deadman_stop_data, psa_deadman_stop_length);
  const bool sent = twai_transmit(&message, pdMS_TO_TICKS(50)) == ESP_OK;
#endif
  if (!sent) {
    ++tx_failed_count;
#if DUAL_CAN
    ++diagnostic_tx_failed_count;
#endif
    return false;
  }
  ++tx_count;
#if DUAL_CAN
  ++diagnostic_tx_count;
#endif
  JsonDocument ack;
  ack["type"] = "ack";
  ack["command"] = "psa_deadman_stop";
  ack["id"] = 0x764;
  ack["attempt"] = psa_deadman_attempts + 1;
  ack["bus"] = "diagnostic";
  ack["ts_us"] = esp_timer_get_time();
  emit_json(ack);
  return true;
}

static void service_psa_deadman() {
  if (!psa_deadman_armed) return;
  const uint32_t now = millis();
  if (static_cast<int32_t>(now - psa_deadman_deadline_ms) < 0) return;
  if (psa_lab_transmit_deadman_stop()) {
    psa_lab_disarm_deadman();
    return;
  }
  ++psa_deadman_attempts;
  if (psa_deadman_attempts >= PSA_DEADMAN_MAX_ATTEMPTS) {
    emit_error("PSA_DEADMAN_FAILED", "Unable to transmit the automatic NAC stop frame");
    psa_lab_disarm_deadman();
    return;
  }
  psa_deadman_deadline_ms = now + 100;
}
#endif

static void transmit_can(JsonDocument &doc) {
#if READ_ONLY
  emit_error("READ_ONLY", "CAN TX blocked by firmware build");
#else
  const char *requested_bus = doc["bus"]
      | ((DUAL_CAN || cfg::NATIVE_CAN_IS_DIAGNOSTIC) ? "diagnostic" : "default");
#if DUAL_CAN
  if (strcmp(requested_bus, "diagnostic") != 0) {
    ++tx_policy_blocked_count;
    emit_error("LIVE_BUS_TX_LOCKED", "OBD 6/14 is permanently receive-only in dual-CAN mode");
    return;
  }
  if (!diagnostic_can_ready) {
    emit_error("DIAGNOSTIC_CAN_NOT_READY", "MCP2515 diagnostic controller is not initialized");
    return;
  }
#else
  if (cfg::NATIVE_CAN_IS_DIAGNOSTIC
      && strcmp(requested_bus, "default") != 0
      && strcmp(requested_bus, "diagnostic") != 0) {
    ++tx_policy_blocked_count;
    emit_error("LIVE_BUS_TX_LOCKED", "This ESP32 is dedicated to OBD 3/8 diagnostics");
    return;
  }
  if (!can_ready) {
    emit_error("CAN_NOT_READY", "CAN controller is not initialized");
    return;
  }
#endif
  if (!doc["id"].is<uint32_t>()) {
    emit_error("INVALID_ID", "Missing or invalid CAN identifier");
    return;
  }
  const uint32_t id = doc["id"].as<uint32_t>();
  const bool extended = doc["ext"] | false;
  if ((!extended && id > 0x7FF) || (extended && id > 0x1FFFFFFF)) {
    emit_error("INVALID_ID", "CAN identifier outside selected format");
    return;
  }

  const char *data_hex = doc["data"] | "";
  uint8_t payload[8]{};
  size_t length = 0;
  if (!decode_hex(data_hex, payload, length)) {
    emit_error("INVALID_DATA", "CAN data must contain 0 to 8 hexadecimal bytes");
    return;
  }

#if DIAGNOSTIC_READ_ONLY || PSA_LAB
  const char *rejection = diagnostic_tx_rejection(id, extended, payload, length);
  if (rejection != nullptr) {
    ++tx_policy_blocked_count;
    JsonDocument error;
    error["type"] = "error";
    error["code"] = "TX_POLICY_BLOCKED";
    error["message"] = rejection;
    error["id"] = id;
    error["service"] = length > 1 ? payload[1] : 0;
    emit_json(error);
    return;
  }
#endif

#if USE_MCP2515 || DUAL_CAN
  struct can_frame frame{};
  frame.can_id = id | (extended ? CAN_EFF_FLAG : 0);
  frame.can_dlc = static_cast<uint8_t>(length);
  memcpy(frame.data, payload, length);
  const MCP2515::ERROR result = mcp2515.sendMessage(&frame);
  if (result != MCP2515::ERROR_OK) {
    ++tx_failed_count;
#if DUAL_CAN
    ++diagnostic_tx_failed_count;
#endif
    JsonDocument error;
    error["type"] = "error";
    error["code"] = "TX_FAILED";
    error["message"] = "MCP2515 transmit failed";
    error["driver_error"] = static_cast<int>(result);
    error["id"] = id;
    error["bus"] = DUAL_CAN ? "diagnostic" : requested_bus;
    emit_json(error);
    return;
  }
#else
  twai_message_t message{};
  message.identifier = id;
  message.extd = extended;
  message.data_length_code = static_cast<uint8_t>(length);
  memcpy(message.data, payload, length);
  const esp_err_t result = twai_transmit(&message, pdMS_TO_TICKS(50));
  if (result != ESP_OK) {
    ++tx_failed_count;
    JsonDocument error;
    error["type"] = "error";
    error["code"] = "TX_FAILED";
    error["message"] = "TWAI transmit failed";
    error["esp_err"] = static_cast<int>(result);
    error["id"] = id;
    emit_json(error);
    return;
  }
#endif
  ++tx_count;
#if DUAL_CAN
  ++diagnostic_tx_count;
#endif

#if PSA_LAB
  psa_lab_update_deadman_after_host_tx(id, payload, length);
#endif

  JsonDocument ack;
  ack["type"] = "ack";
  ack["command"] = "can_tx";
  ack["id"] = id;
  ack["bus"] = (DUAL_CAN || cfg::NATIVE_CAN_IS_DIAGNOSTIC)
      ? "diagnostic"
      : requested_bus;
  ack["ts_us"] = esp_timer_get_time();
  ack["tx_count"] = tx_count;
  emit_json(ack);
#endif
}

static void parse_command(const String &line) {
  if (line.length() > 512) {
    emit_error("COMMAND_TOO_LARGE", "JSON command exceeds 512 bytes");
    return;
  }

  JsonDocument doc;
  const DeserializationError error = deserializeJson(doc, line);
  if (error) {
    emit_error("INVALID_JSON", error.c_str());
    return;
  }
  const char *type = doc["type"] | "";

  if (strcmp(type, "ping") == 0) {
    JsonDocument pong;
    pong["type"] = "pong";
    pong["uptime_ms"] = millis();
    emit_json(pong);
    return;
  }

  if (strcmp(type, "get_status") == 0) {
#if UART_DUAL_CAN_MASTER
    interboard_uart.println("{\"type\":\"get_status\"}");
    satellite_last_request_ms = millis();
#endif
    emit_hello();
    emit_stats();
    return;
  }

  if (strcmp(type, "clear_filter") == 0) {
    filter_count = 0;
#if UART_DUAL_CAN_MASTER
    interboard_uart.println(line);
#endif
    emit_line("{\"type\":\"ack\",\"command\":\"clear_filter\"}");
    return;
  }

  if (strcmp(type, "set_filter") == 0) {
    JsonArray ids = doc["ids"].as<JsonArray>();
    if (ids.isNull() || ids.size() > cfg::MAX_FILTER_IDS) {
      emit_error("INVALID_FILTER", "ids must be an array within the configured limit");
      return;
    }
    filter_count = 0;
    for (JsonVariant id : ids) {
      if (!id.is<uint32_t>()) {
        filter_count = 0;
        emit_error("INVALID_FILTER", "Every filter identifier must be an integer");
        return;
      }
      filter_ids[filter_count++] = id.as<uint32_t>();
    }
#if UART_DUAL_CAN_MASTER
    interboard_uart.println(line);
#endif
    JsonDocument ack;
    ack["type"] = "ack";
    ack["command"] = "set_filter";
    ack["count"] = filter_count;
    emit_json(ack);
    return;
  }

  if (strcmp(type, "can_tx") == 0) {
#if UART_DUAL_CAN_MASTER
    const char *requested_bus = doc["bus"] | "diagnostic";
    if (strcmp(requested_bus, "diagnostic") != 0) {
      ++tx_policy_blocked_count;
      emit_error("LIVE_BUS_TX_LOCKED", "OBD 6/14 is permanently receive-only");
      return;
    }
    if (!satellite_connected || !diagnostic_can_ready) {
      emit_error("DIAGNOSTIC_CAN_NOT_READY", "The UART diagnostic ESP32 is unavailable");
      return;
    }
    interboard_uart.println(line);
    return;
#else
    transmit_can(doc);
    return;
#endif
  }

  emit_error("UNKNOWN_COMMAND", "Unsupported command type");
}

#if UART_DUAL_CAN_MASTER || UART_DUAL_CAN_SATELLITE
static void handle_interboard_line(const char *line) {
#if UART_DUAL_CAN_SATELLITE
  parse_command(String(line));
#else
  satellite_last_message_ms = millis();
  if (strncmp(line, "F,", 2) == 0) {
    emit_line(line, true);
    return;
  }

  JsonDocument doc;
  if (deserializeJson(doc, line)) {
    ++interboard_overflow_count;
    return;
  }
  const char *type = doc["type"] | "";
  if (strcmp(type, "hello") == 0) {
    const char *role = doc["bus_role"] | "";
    // Ignore an unexpected/echoed hello instead of momentarily disabling a
    // healthy satellite. Actual link loss is handled by the heartbeat timeout.
    if (strcmp(role, "diagnostic") != 0) {
      ++interboard_overflow_count;
      return;
    }
    const bool was_connected = satellite_connected;
    satellite_connected = true;
    diagnostic_can_ready = satellite_connected && (doc["can_ready"] | false);
    satellite_diagnostic_read_only = doc["diagnostic_read_only"] | false;
    satellite_psa_lab = doc["psa_lab"] | false;
    const char *policy = doc["tx_policy"] | "unavailable";
    strlcpy(satellite_tx_policy, policy, sizeof(satellite_tx_policy));
    if (satellite_connected != was_connected) emit_hello();
    return;
  }
  if (strcmp(type, "stats") == 0) {
    satellite_rx_count = doc["rx"] | satellite_rx_count;
    satellite_tx_count = doc["tx"] | satellite_tx_count;
    satellite_dropped_count = doc["dropped"] | satellite_dropped_count;
    return;
  }
  if (strcmp(type, "status") == 0 || strcmp(type, "pong") == 0) return;
  emit_line(line);
#endif
}

static void poll_interboard_uart() {
  size_t processed = 0;
  while (interboard_uart.available() > 0 && processed < 8192) {
    ++processed;
    const int value = interboard_uart.read();
    if (value < 0) break;
    const char character = static_cast<char>(value);
    if (character == '\n') {
      if (!interboard_rx_discard && interboard_rx_length > 0) {
        if (interboard_rx_line[interboard_rx_length - 1] == '\r') --interboard_rx_length;
        interboard_rx_line[interboard_rx_length] = '\0';
        if (interboard_rx_length > 0) handle_interboard_line(interboard_rx_line);
      }
      interboard_rx_length = 0;
      interboard_rx_discard = false;
      continue;
    }
    if (interboard_rx_discard) continue;
    if (interboard_rx_length + 1 >= sizeof(interboard_rx_line)) {
      interboard_rx_discard = true;
      ++interboard_overflow_count;
      continue;
    }
    interboard_rx_line[interboard_rx_length++] = character;
  }
}

static void start_interboard_uart() {
  interboard_uart.setRxBufferSize(8192);
  interboard_uart.begin(
      cfg::INTERBOARD_BAUD,
      SERIAL_8N1,
      cfg::INTERBOARD_RX_PIN,
      cfg::INTERBOARD_TX_PIN);
  interboard_uart.setTimeout(5);
}
#endif

#if WIFI_ENABLED
static void wifi_disconnect_client(WiFiClient &client) {
  if (client) client.stop();
  wifi_client_connected = false;
  if (wifi_packet_queue != nullptr) xQueueReset(wifi_packet_queue);
}

static bool wifi_send_hello(WiFiClient &client) {
  WifiPacket packet{};
  const size_t length = format_hello(packet.bytes, sizeof(packet.bytes) - 1);
  if (length == 0 || length + 1 > sizeof(packet.bytes)) return false;
  packet.bytes[length] = '\n';
  packet.length = static_cast<uint16_t>(length + 1);
  return client.write(
      reinterpret_cast<const uint8_t *>(packet.bytes), packet.length) == packet.length;
}

static void wifi_gateway_task(void *) {
  WiFiClient client;
  WifiCommand command{};
  size_t command_length = 0;
  bool discard_command = false;

  for (;;) {
    WiFiClient candidate = wifi_server.available();
    if (candidate) {
      wifi_disconnect_client(client);
      client = candidate;
      client.setNoDelay(false);
      command_length = 0;
      discard_command = false;
      wifi_client_connected = true;
      ++wifi_connections;
      if (!wifi_send_hello(client)) {
        ++wifi_write_failures;
        wifi_disconnect_client(client);
      }
    }

    if (wifi_client_connected && !client.connected()) {
      wifi_disconnect_client(client);
    }

    if (wifi_client_connected) {
      while (client.available() > 0) {
        const int value = client.read();
        if (value < 0) break;
        const char character = static_cast<char>(value);
        if (character == '\n') {
          if (!discard_command && command_length > 0) {
            if (command.json[command_length - 1] == '\r') --command_length;
            command.json[command_length] = '\0';
            if (command_length > 0 &&
                xQueueSend(wifi_command_queue, &command, 0) != pdTRUE) {
              ++wifi_command_overflows;
            }
          }
          command_length = 0;
          discard_command = false;
          continue;
        }
        if (discard_command) continue;
        if (command_length >= cfg::WIFI_COMMAND_MAX_BYTES) {
          discard_command = true;
          ++wifi_command_overflows;
          continue;
        }
        command.json[command_length++] = character;
      }

      WifiPacket packet{};
      if (xQueueReceive(wifi_packet_queue, &packet, pdMS_TO_TICKS(2)) == pdTRUE) {
        const size_t written = client.write(
            reinterpret_cast<const uint8_t *>(packet.bytes), packet.length);
        if (written != packet.length) {
          ++wifi_write_failures;
          ++wifi_dropped_messages;
          wifi_disconnect_client(client);
        }
      }
    } else {
      vTaskDelay(pdMS_TO_TICKS(10));
    }
  }
}

static bool start_wifi() {
  if (strlen(cfg::WIFI_PASSWORD) < 8) {
    Serial.println("{\"type\":\"error\",\"code\":\"WIFI_PASSWORD_TOO_SHORT\"}");
    return false;
  }
  wifi_packet_queue = xQueueCreate(WIFI_PACKET_QUEUE_LENGTH, sizeof(WifiPacket));
  wifi_command_queue = xQueueCreate(WIFI_COMMAND_QUEUE_LENGTH, sizeof(WifiCommand));
  if (wifi_packet_queue == nullptr || wifi_command_queue == nullptr) {
    Serial.println("{\"type\":\"error\",\"code\":\"WIFI_QUEUE_ALLOCATION_FAILED\"}");
    return false;
  }

  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);
  if (!WiFi.softAP(cfg::WIFI_SSID, cfg::WIFI_PASSWORD, 1, false, 1)) {
    Serial.println("{\"type\":\"error\",\"code\":\"WIFI_AP_START_FAILED\"}");
    return false;
  }
  const String address = WiFi.softAPIP().toString();
  strlcpy(wifi_ip, address.c_str(), sizeof(wifi_ip));
  wifi_server.begin();
  wifi_server.setNoDelay(false);
  const BaseType_t task_result = xTaskCreatePinnedToCore(
      wifi_gateway_task,
      "opendiag_wifi",
      6144,
      nullptr,
      1,
      &wifi_task_handle,
      0);
  wifi_ready = task_result == pdPASS;
  if (!wifi_ready) {
    WiFi.softAPdisconnect(true);
    Serial.println("{\"type\":\"error\",\"code\":\"WIFI_TASK_START_FAILED\"}");
  }
  return wifi_ready;
}

static void poll_wifi_commands() {
  if (wifi_command_queue == nullptr) return;
  WifiCommand command{};
  while (xQueueReceive(wifi_command_queue, &command, 0) == pdTRUE) {
    parse_command(String(command.json));
  }
}
#endif

static bool start_mcp2515() {
#if USE_MCP2515 || DUAL_CAN
  mcp2515_init_stage = 0;
  mcp2515_init_error = 0;
  SPI.begin(
      cfg::MCP2515_SPI_SCK_PIN,
      cfg::MCP2515_SPI_MISO_PIN,
      cfg::MCP2515_SPI_MOSI_PIN,
      cfg::MCP2515_SPI_CS_PIN);
  pinMode(cfg::MCP2515_INTERRUPT_PIN, INPUT_PULLUP);
  mcp2515_init_stage = 1;
  MCP2515::ERROR result = mcp2515.reset();
  mcp2515_init_error = static_cast<int8_t>(result);
  if (result != MCP2515::ERROR_OK) return false;

#if MCP2515_CLOCK_MHZ == 8
  constexpr CAN_CLOCK clock = MCP_8MHZ;
#elif MCP2515_CLOCK_MHZ == 16
  constexpr CAN_CLOCK clock = MCP_16MHZ;
#else
#error "MCP2515_CLOCK_MHZ must be 8 or 16"
#endif

  mcp2515_init_stage = 2;
  result = mcp2515.setBitrate(CAN_500KBPS, clock);
  mcp2515_init_error = static_cast<int8_t>(result);
  if (result != MCP2515::ERROR_OK) return false;
  mcp2515_init_stage = 3;
  result = READ_ONLY
      ? mcp2515.setListenOnlyMode()
      : mcp2515.setNormalMode();
  mcp2515_init_error = static_cast<int8_t>(result);
  if (result != MCP2515::ERROR_OK) return false;
  mcp2515_init_stage = 4;
  return true;
#else
  return false;
#endif
}

static bool start_twai(bool force_listen_only = false) {
#if !USE_MCP2515 || DUAL_CAN
  const bool listen_only = force_listen_only || (READ_ONLY != 0);
  twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT(
      cfg::CAN_TX_PIN,
      cfg::CAN_RX_PIN,
      listen_only ? TWAI_MODE_LISTEN_ONLY : TWAI_MODE_NORMAL);
  general.rx_queue_len = 256;
  general.tx_queue_len = listen_only ? 0 : 16;
  const twai_timing_config_t timing = TWAI_TIMING_CONFIG_500KBITS();
  const twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();

  if (twai_driver_install(&general, &timing, &filter) != ESP_OK) return false;
  if (twai_start() != ESP_OK) return false;

  twai_reconfigure_alerts(
      TWAI_ALERT_BUS_OFF |
      TWAI_ALERT_BUS_RECOVERED |
      TWAI_ALERT_RX_QUEUE_FULL |
      TWAI_ALERT_BUS_ERROR |
      TWAI_ALERT_ARB_LOST |
      TWAI_ALERT_TX_FAILED |
      TWAI_ALERT_ERR_PASS |
      TWAI_ALERT_ABOVE_ERR_WARN,
      nullptr);
  return true;
#else
  (void)force_listen_only;
  return false;
#endif
}

static bool start_can() {
#if DUAL_CAN
  // OBD 6/14 never transmits in this build. All approved diagnostic requests
  // are routed exclusively through the MCP2515 on OBD 3/8.
  live_can_ready = start_twai(true);
  diagnostic_can_ready = start_mcp2515();
  can_ready = live_can_ready;
  return can_ready;
#elif USE_MCP2515
  diagnostic_can_ready = start_mcp2515();
  can_ready = diagnostic_can_ready;
  return can_ready;
#else
  // In the UART dual-CAN architecture the main ESP32 must never transmit on
  // the live vehicle network, even though diagnostics are enabled globally.
  live_can_ready = start_twai(cfg::UART_MASTER);
  can_ready = live_can_ready;
  return can_ready;
#endif
}

void setup() {
  Serial.setTxBufferSize(cfg::SERIAL_TX_BUFFER_BYTES);
  Serial.begin(cfg::SERIAL_BAUD);
  Serial.setTimeout(25);
#if UART_DUAL_CAN_MASTER || UART_DUAL_CAN_SATELLITE
  start_interboard_uart();
#endif
  delay(500);
  can_ready = start_can();
#if UART_DUAL_CAN_MASTER
  const uint32_t satellite_deadline = millis() + 2000;
  while (!satellite_connected
      && static_cast<int32_t>(millis() - satellite_deadline) < 0) {
    const uint32_t now = millis();
    if (now - satellite_last_request_ms >= 200) {
      interboard_uart.println("{\"type\":\"get_status\"}");
      satellite_last_request_ms = now;
    }
    poll_interboard_uart();
    delay(1);
  }
#endif
#if WIFI_ENABLED
  start_wifi();
#endif
  emit_hello();

  if (!can_ready) {
    JsonDocument fatal;
    fatal["type"] = "fatal";
    fatal["code"] = (USE_MCP2515 && !DUAL_CAN) ? "MCP2515_INIT_FAILED" : "TWAI_INIT_FAILED";
    emit_json(fatal);
  } else {
    JsonDocument status;
    status["type"] = "status";
    status["can"] = READ_ONLY
        ? "listen_only"
        : (DIAGNOSTIC_READ_ONLY
            ? "read_only_diagnostics"
            : (PSA_LAB ? "psa_lab_named_actions" : "active"));
    status["driver"] = DUAL_CAN
        ? "twai+mcp2515"
        : (cfg::UART_MASTER ? "twai+uart-twai" : (USE_MCP2515 ? "mcp2515" : "twai"));
    status["bitrate"] = cfg::CAN_BITRATE;
#if DUAL_CAN
    status["live_bus"] = "listen_only";
    status["diagnostic_bus"] = diagnostic_can_ready ? "read_only_diagnostics" : "unavailable";
#elif UART_DUAL_CAN_MASTER
    status["live_bus"] = "listen_only";
    status["diagnostic_bus"] = diagnostic_can_ready ? "uart_read_only_diagnostics" : "unavailable";
#endif
    emit_json(status);
  }
#if DUAL_CAN
  if (!diagnostic_can_ready) {
    JsonDocument error;
    error["type"] = "fatal";
    error["code"] = "MCP2515_DIAGNOSTIC_INIT_FAILED";
    error["message"] = "Live OBD 6/14 remains available; diagnostic OBD 3/8 is unavailable";
    emit_json(error);
  }
#elif UART_DUAL_CAN_MASTER
  if (!diagnostic_can_ready) {
    emit_error(
        "UART_DIAGNOSTIC_SATELLITE_UNAVAILABLE",
        "Live OBD 6/14 remains available; check UART GPIO 16/17 and the second ESP32");
  }
#endif
}

static void drain_mcp2515(CanChannel channel, uint8_t limit) {
#if USE_MCP2515 || DUAL_CAN
  if (!diagnostic_can_ready) return;
  for (uint8_t drained = 0; drained < limit; ++drained) {
    struct can_frame frame{};
    if (mcp2515.readMessage(&frame) != MCP2515::ERROR_OK) break;

    const bool extended = (frame.can_id & CAN_EFF_FLAG) != 0;
    const bool remote = (frame.can_id & CAN_RTR_FLAG) != 0;
    const uint32_t identifier = frame.can_id & (extended ? CAN_EFF_MASK : CAN_SFF_MASK);
    const uint8_t data_length = min<uint8_t>(frame.can_dlc, 8);
    ++rx_count;
#if DUAL_CAN
    ++diagnostic_rx_count;
    // Host filters are intended for the high-volume live bus. Diagnostic
    // responses must always reach ISO-TP, including during a filtered capture.
    emit_frame(channel, identifier, extended, data_length, remote, frame.data);
#else
    if (id_allowed(identifier)) {
      emit_frame(channel, identifier, extended, data_length, remote, frame.data);
    } else {
      ++filtered_count;
    }
#endif
  }
#else
  (void)channel;
  (void)limit;
#endif
}

static void service_mcp2515_errors(CanChannel channel) {
#if USE_MCP2515 || DUAL_CAN
  if (!diagnostic_can_ready) return;
  uint8_t error_flags = mcp2515.getErrorFlags();
  last_alerts = error_flags;
#if DUAL_CAN
  uint8_t &previous_flags = diagnostic_last_error_flags;
#else
  uint8_t &previous_flags = last_mcp_error_flags;
#endif
  if ((error_flags & MCP2515::EFLG_TXBO) && !(previous_flags & MCP2515::EFLG_TXBO)) {
    ++bus_off_count;
    emit_can_status(channel, "bus_off", error_flags);
  }
  if (!(error_flags & MCP2515::EFLG_TXBO) && (previous_flags & MCP2515::EFLG_TXBO)) {
    ++bus_recovered_count;
    emit_can_status(channel, "bus_recovered", error_flags);
  }
  const uint8_t overflow_flags = MCP2515::EFLG_RX0OVR | MCP2515::EFLG_RX1OVR;
  if (error_flags & overflow_flags) {
    ++dropped_count;
#if DUAL_CAN
    ++diagnostic_dropped_count;
#endif
    emit_can_status(channel, "rx_overflow", error_flags);
    mcp2515.clearRXnOVRFlags();
    error_flags &= ~overflow_flags;
  }
  const uint8_t passive_flags = MCP2515::EFLG_TXEP | MCP2515::EFLG_RXEP;
  if ((error_flags & passive_flags) && !(previous_flags & passive_flags)) {
    emit_can_status(channel, "error_passive", error_flags);
  }
  const uint8_t warning_flags = MCP2515::EFLG_TXWAR | MCP2515::EFLG_RXWAR | MCP2515::EFLG_EWARN;
  if ((error_flags & warning_flags) && !(previous_flags & warning_flags)) {
    emit_can_status(channel, "above_error_warning", error_flags);
  }
  previous_flags = error_flags;
#else
  (void)channel;
#endif
}

static void drain_twai(uint8_t limit) {
#if !USE_MCP2515 || DUAL_CAN
  if (!live_can_ready) return;
  for (uint8_t drained = 0; drained < limit; ++drained) {
    twai_message_t message{};
    if (twai_receive(&message, 0) != ESP_OK) break;
    ++rx_count;
#if DUAL_CAN
    ++live_rx_count;
#endif
    if (id_allowed(message.identifier)) {
      emit_frame(
          native_can_channel(),
          message.identifier,
          message.extd,
          message.data_length_code,
          message.rtr,
          message.data);
    } else {
      ++filtered_count;
#if DUAL_CAN
      ++live_filtered_count;
#endif
    }
  }
#else
  (void)limit;
#endif
}

static void service_twai_alerts() {
#if !USE_MCP2515 || DUAL_CAN
  if (!live_can_ready) return;
  uint32_t alerts = 0;
  if (twai_read_alerts(&alerts, 0) == ESP_OK) {
    last_alerts = alerts;
#if DUAL_CAN
    live_last_alerts = alerts;
#endif
    if (alerts & TWAI_ALERT_BUS_OFF) ++bus_off_count;
    if (alerts & TWAI_ALERT_BUS_RECOVERED) ++bus_recovered_count;
    if (alerts & TWAI_ALERT_RX_QUEUE_FULL) {
      ++dropped_count;
#if DUAL_CAN
      ++live_dropped_count;
#endif
    }
    if (alerts & TWAI_ALERT_BUS_OFF) emit_can_status(native_can_channel(), "bus_off", alerts);
    if (alerts & TWAI_ALERT_BUS_RECOVERED) emit_can_status(native_can_channel(), "bus_recovered", alerts);
    if (alerts & TWAI_ALERT_RX_QUEUE_FULL) emit_can_status(native_can_channel(), "rx_queue_full", alerts);
    if (alerts & TWAI_ALERT_BUS_ERROR) emit_can_status(native_can_channel(), "bus_error", alerts);
    if (alerts & TWAI_ALERT_ARB_LOST) emit_can_status(native_can_channel(), "arbitration_lost", alerts);
    if (alerts & TWAI_ALERT_TX_FAILED) emit_can_status(native_can_channel(), "tx_failed", alerts);
    if (alerts & TWAI_ALERT_ERR_PASS) emit_can_status(native_can_channel(), "error_passive", alerts);
    if (alerts & TWAI_ALERT_ABOVE_ERR_WARN) emit_can_status(native_can_channel(), "above_error_warning", alerts);
  }
#endif
}

void loop() {
#if PSA_LAB
  service_psa_deadman();
#endif
#if WIFI_ENABLED
  poll_wifi_commands();
#endif
#if UART_DUAL_CAN_MASTER || UART_DUAL_CAN_SATELLITE
  poll_interboard_uart();
#endif

#if DUAL_CAN
  // Drain TWAI first on every pass so adding diagnostics never reduces the
  // sampling priority of steering, speed, lamps and gearbox frames.
  drain_twai(64);
  drain_mcp2515(CanChannel::Diagnostic, 32);
  service_twai_alerts();
  service_mcp2515_errors(CanChannel::Diagnostic);
#elif USE_MCP2515
  drain_mcp2515(CanChannel::Live, 32);
  service_mcp2515_errors(CanChannel::Live);
#else
  drain_twai(64);
  service_twai_alerts();
#endif

  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (!line.isEmpty()) parse_command(line);
  }

  const uint32_t now = millis();
#if UART_DUAL_CAN_MASTER
  if (satellite_connected && now - satellite_last_message_ms > 3000) {
    satellite_connected = false;
    diagnostic_can_ready = false;
    satellite_diagnostic_read_only = false;
    satellite_psa_lab = false;
    strlcpy(satellite_tx_policy, "unavailable", sizeof(satellite_tx_policy));
    emit_error("UART_DIAGNOSTIC_SATELLITE_LOST", "No heartbeat from the diagnostic ESP32");
    emit_hello();
  }
  if (!satellite_connected && now - satellite_last_request_ms >= 500) {
    interboard_uart.println("{\"type\":\"get_status\"}");
    satellite_last_request_ms = now;
  }
#endif
  if (now - last_stats_ms >= cfg::STATS_INTERVAL_MS) {
    last_stats_ms = now;
    emit_stats();
  }
}
