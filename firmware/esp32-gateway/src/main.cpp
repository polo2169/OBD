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

#if USE_MCP2515
#include <SPI.h>
#include <mcp2515.h>
#else
#include <driver/twai.h>
#endif

static uint32_t rx_count = 0;
static uint32_t tx_count = 0;
static uint32_t tx_failed_count = 0;
static uint32_t dropped_count = 0;
static uint32_t filtered_count = 0;
static uint32_t bus_off_count = 0;
static uint32_t bus_recovered_count = 0;
static uint32_t frame_sequence = 0;
static uint32_t last_alerts = 0;
static uint32_t last_stats_ms = 0;
static bool can_ready = false;

namespace {
constexpr size_t OUTPUT_PACKET_MAX_BYTES = 512;
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

#if USE_MCP2515
static MCP2515 mcp2515(cfg::MCP2515_SPI_CS_PIN, cfg::MCP2515_SPI_HZ);
static uint8_t last_mcp_error_flags = 0;
#endif

static uint32_t filter_ids[cfg::MAX_FILTER_IDS];
static size_t filter_count = 0;

static size_t format_hello(char *output, size_t capacity);

static void emit_line(const char *line, bool frame = false) {
  if (!frame || cfg::MIRROR_FRAMES_TO_SERIAL) {
    Serial.println(line);
  }
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
  doc["protocol"] = 3;
  doc["device"] = "opendiag-esp32";
  doc["firmware"] = "0.6.0-wifi";
  doc["driver"] = USE_MCP2515 ? "mcp2515" : "twai";
  doc["can_ready"] = can_ready;
  doc["readonly"] = READ_ONLY != 0;
  doc["bitrate"] = cfg::CAN_BITRATE;
#if USE_MCP2515
  doc["spi_sck_pin"] = cfg::MCP2515_SPI_SCK_PIN;
  doc["spi_miso_pin"] = cfg::MCP2515_SPI_MISO_PIN;
  doc["spi_mosi_pin"] = cfg::MCP2515_SPI_MOSI_PIN;
  doc["spi_cs_pin"] = cfg::MCP2515_SPI_CS_PIN;
  doc["oscillator_mhz"] = MCP2515_CLOCK_MHZ;
#else
  doc["tx_pin"] = static_cast<int>(cfg::CAN_TX_PIN);
  doc["rx_pin"] = static_cast<int>(cfg::CAN_RX_PIN);
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
  doc["filtered"] = filtered_count;
  doc["bus_off"] = bus_off_count;
  doc["bus_recovered"] = bus_recovered_count;
#if USE_MCP2515
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

static void emit_can_status(const char *reason, uint32_t alerts) {
#if USE_MCP2515
  JsonDocument doc;
  doc["type"] = "can_status";
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
  JsonDocument doc;
  doc["type"] = "can_rx";
  doc["ts_us"] = esp_timer_get_time();
  doc["seq"] = frame_sequence++;
  doc["id"] = identifier;
  doc["ext"] = extended;
  doc["dlc"] = data_length;
  doc["rtr"] = remote;
  doc["ss"] = false;
  doc["data"] = data_hex;
  emit_json(doc, true);
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

static void transmit_can(JsonDocument &doc) {
#if READ_ONLY
  emit_error("READ_ONLY", "CAN TX blocked by firmware build");
#else
  if (!can_ready) {
    emit_error("CAN_NOT_READY", "CAN controller is not initialized");
    return;
  }
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

#if USE_MCP2515
  struct can_frame frame{};
  frame.can_id = id | (extended ? CAN_EFF_FLAG : 0);
  frame.can_dlc = static_cast<uint8_t>(length);
  memcpy(frame.data, payload, length);
  const MCP2515::ERROR result = mcp2515.sendMessage(&frame);
  if (result != MCP2515::ERROR_OK) {
    ++tx_failed_count;
    JsonDocument error;
    error["type"] = "error";
    error["code"] = "TX_FAILED";
    error["message"] = "MCP2515 transmit failed";
    error["driver_error"] = static_cast<int>(result);
    error["id"] = id;
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

  JsonDocument ack;
  ack["type"] = "ack";
  ack["command"] = "can_tx";
  ack["id"] = id;
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
    emit_hello();
    emit_stats();
    return;
  }

  if (strcmp(type, "clear_filter") == 0) {
    filter_count = 0;
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
    JsonDocument ack;
    ack["type"] = "ack";
    ack["command"] = "set_filter";
    ack["count"] = filter_count;
    emit_json(ack);
    return;
  }

  if (strcmp(type, "can_tx") == 0) {
    transmit_can(doc);
    return;
  }

  emit_error("UNKNOWN_COMMAND", "Unsupported command type");
}

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

static bool start_can() {
#if USE_MCP2515
  SPI.begin(
      cfg::MCP2515_SPI_SCK_PIN,
      cfg::MCP2515_SPI_MISO_PIN,
      cfg::MCP2515_SPI_MOSI_PIN,
      cfg::MCP2515_SPI_CS_PIN);
  if (mcp2515.reset() != MCP2515::ERROR_OK) return false;

#if MCP2515_CLOCK_MHZ == 8
  constexpr CAN_CLOCK clock = MCP_8MHZ;
#elif MCP2515_CLOCK_MHZ == 16
  constexpr CAN_CLOCK clock = MCP_16MHZ;
#else
#error "MCP2515_CLOCK_MHZ must be 8 or 16"
#endif

  if (mcp2515.setBitrate(CAN_500KBPS, clock) != MCP2515::ERROR_OK) return false;
  const MCP2515::ERROR mode_result = READ_ONLY
      ? mcp2515.setListenOnlyMode()
      : mcp2515.setNormalMode();
  return mode_result == MCP2515::ERROR_OK;
#else
  twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT(
      cfg::CAN_TX_PIN,
      cfg::CAN_RX_PIN,
      READ_ONLY ? TWAI_MODE_LISTEN_ONLY : TWAI_MODE_NORMAL);
  general.rx_queue_len = 256;
  general.tx_queue_len = READ_ONLY ? 0 : 16;
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
#endif
}

void setup() {
  Serial.begin(cfg::SERIAL_BAUD);
  delay(500);
  can_ready = start_can();
#if WIFI_ENABLED
  start_wifi();
#endif
  emit_hello();

  if (!can_ready) {
    JsonDocument fatal;
    fatal["type"] = "fatal";
    fatal["code"] = USE_MCP2515 ? "MCP2515_INIT_FAILED" : "TWAI_INIT_FAILED";
    emit_json(fatal);
  } else {
    JsonDocument status;
    status["type"] = "status";
    status["can"] = READ_ONLY ? "listen_only" : "active";
    status["driver"] = USE_MCP2515 ? "mcp2515" : "twai";
    status["bitrate"] = cfg::CAN_BITRATE;
    emit_json(status);
  }
}

void loop() {
#if WIFI_ENABLED
  poll_wifi_commands();
#endif
  if (can_ready) {
#if USE_MCP2515
  for (uint8_t drained = 0; drained < 32; ++drained) {
    struct can_frame frame{};
    if (mcp2515.readMessage(&frame) != MCP2515::ERROR_OK) break;

    const bool extended = (frame.can_id & CAN_EFF_FLAG) != 0;
    const bool remote = (frame.can_id & CAN_RTR_FLAG) != 0;
    const uint32_t identifier = frame.can_id & (extended ? CAN_EFF_MASK : CAN_SFF_MASK);
    const uint8_t data_length = min<uint8_t>(frame.can_dlc, 8);
    ++rx_count;
    if (id_allowed(identifier)) {
      emit_frame(identifier, extended, data_length, remote, frame.data);
    } else {
      ++filtered_count;
    }
  }

  uint8_t error_flags = mcp2515.getErrorFlags();
  last_alerts = error_flags;
  if ((error_flags & MCP2515::EFLG_TXBO) && !(last_mcp_error_flags & MCP2515::EFLG_TXBO)) {
    ++bus_off_count;
    emit_can_status("bus_off", error_flags);
  }
  if (!(error_flags & MCP2515::EFLG_TXBO) && (last_mcp_error_flags & MCP2515::EFLG_TXBO)) {
    ++bus_recovered_count;
    emit_can_status("bus_recovered", error_flags);
  }
  const uint8_t overflow_flags = MCP2515::EFLG_RX0OVR | MCP2515::EFLG_RX1OVR;
  if (error_flags & overflow_flags) {
    ++dropped_count;
    emit_can_status("rx_overflow", error_flags);
    mcp2515.clearRXnOVRFlags();
    error_flags &= ~overflow_flags;
  }
  const uint8_t passive_flags = MCP2515::EFLG_TXEP | MCP2515::EFLG_RXEP;
  if ((error_flags & passive_flags) && !(last_mcp_error_flags & passive_flags)) {
    emit_can_status("error_passive", error_flags);
  }
  const uint8_t warning_flags = MCP2515::EFLG_TXWAR | MCP2515::EFLG_RXWAR | MCP2515::EFLG_EWARN;
  if ((error_flags & warning_flags) && !(last_mcp_error_flags & warning_flags)) {
    emit_can_status("above_error_warning", error_flags);
  }
  last_mcp_error_flags = error_flags;
#else
  for (uint8_t drained = 0; drained < 64; ++drained) {
    twai_message_t message{};
    const TickType_t wait = drained == 0 ? pdMS_TO_TICKS(2) : 0;
    if (twai_receive(&message, wait) != ESP_OK) break;
    ++rx_count;
    if (id_allowed(message.identifier)) {
      emit_frame(
          message.identifier,
          message.extd,
          message.data_length_code,
          message.rtr,
          message.data);
    } else {
      ++filtered_count;
    }
  }

  uint32_t alerts = 0;
  if (twai_read_alerts(&alerts, 0) == ESP_OK) {
    last_alerts = alerts;
    if (alerts & TWAI_ALERT_BUS_OFF) ++bus_off_count;
    if (alerts & TWAI_ALERT_BUS_RECOVERED) ++bus_recovered_count;
    if (alerts & TWAI_ALERT_RX_QUEUE_FULL) ++dropped_count;
    if (alerts & TWAI_ALERT_BUS_OFF) emit_can_status("bus_off", alerts);
    if (alerts & TWAI_ALERT_BUS_RECOVERED) emit_can_status("bus_recovered", alerts);
    if (alerts & TWAI_ALERT_RX_QUEUE_FULL) emit_can_status("rx_queue_full", alerts);
    if (alerts & TWAI_ALERT_BUS_ERROR) emit_can_status("bus_error", alerts);
    if (alerts & TWAI_ALERT_ARB_LOST) emit_can_status("arbitration_lost", alerts);
    if (alerts & TWAI_ALERT_TX_FAILED) emit_can_status("tx_failed", alerts);
    if (alerts & TWAI_ALERT_ERR_PASS) emit_can_status("error_passive", alerts);
    if (alerts & TWAI_ALERT_ABOVE_ERR_WARN) emit_can_status("above_error_warning", alerts);
  }
#endif
  }

  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (!line.isEmpty()) parse_command(line);
  }

  const uint32_t now = millis();
  if (now - last_stats_ms >= cfg::STATS_INTERVAL_MS) {
    last_stats_ms = now;
    emit_stats();
  }
}
