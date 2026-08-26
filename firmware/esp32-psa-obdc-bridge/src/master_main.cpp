#include <Arduino.h>
#include <ArduinoJson.h>
#include <driver/twai.h>
#include <esp_timer.h>

#include "bridge_config.hpp"
#include "link_protocol.hpp"
#include "psa_lka_safety.hpp"
#include "psa_rvv_safety.hpp"

#if !PSA_ROLE_MASTER
#error "master_main.cpp requires PSA_ROLE_MASTER=1"
#endif

namespace {

enum class GatewayState : uint8_t {
  Bypass,
  Preparing,
  Settling,
  Active,
  Fault,
};

HardwareSerial interboard_serial(2);
link_protocol::Link interboard(interboard_serial);
psa_lka_safety::Safety safety;
psa_rvv_safety::Controller rvv;

GatewayState state = GatewayState::Bypass;
bool can_ready = false;
bool peer_seen = false;
bool peer_can_ready = false;
bool peer_sequence_seen = false;
uint16_t peer_sequence_last = 0;
uint32_t peer_last_packet_ms = 0;
uint32_t prepare_started_ms = 0;
uint32_t relay_cut_ms = 0;
uint32_t last_keepalive_ms = 0;
uint32_t last_lka_tx_ms = 0;
uint32_t last_stats_ms = 0;
uint32_t frame_sequence = 0;
uint32_t car_rx_count = 0;
uint32_t eps_rx_count = 0;
uint32_t eps_tx_count = 0;
uint32_t eps_tx_failed = 0;
uint32_t host_frame_drops = 0;
uint32_t link_sequence_gaps = 0;
uint32_t link_decode_errors_seen = 0;
int desired_torque_raw = 0;
char host_line[bridge_cfg::HOST_RX_LINE_BYTES] = {0};
size_t host_line_length = 0;
bool host_line_discard = false;

const char *state_name() {
  switch (state) {
    case GatewayState::Bypass: return "bypass";
    case GatewayState::Preparing: return "preparing";
    case GatewayState::Settling: return "settling";
    case GatewayState::Active: return "active";
    case GatewayState::Fault: return "fault";
  }
  return "unknown";
}

void emit_json(JsonDocument &doc) {
  serializeJson(doc, Serial);
  Serial.write('\n');
}

void emit_error(const char *code, const char *message) {
  JsonDocument doc;
  doc["type"] = "error";
  doc["code"] = code;
  doc["message"] = message;
  emit_json(doc);
}

void emit_event(const char *event, const char *reason = nullptr) {
  JsonDocument doc;
  doc["type"] = "psa_event";
  doc["event"] = event;
  doc["state"] = state_name();
  if (reason != nullptr && reason[0] != '\0') doc["reason"] = reason;
  emit_json(doc);
}

void emit_hello() {
  JsonDocument doc;
  doc["type"] = "hello";
  doc["protocol"] = 8;
  doc["device"] = "psa-obdc-two-esp32";
  doc["firmware"] = "0.2.0-rvv-bench";
  doc["role"] = "master_eps_can0";
  doc["driver"] = "twai+crc-uart-twai";
  doc["can_ready"] = can_ready;
  doc["peer_can_ready"] = peer_can_ready;
  doc["readonly"] = false;
  doc["arbitrary_can_tx"] = false;
  if (bridge_cfg::ALLOW_RVV_CONTROL) {
    doc["tx_policy"] = "bench_psa_50e_rvv_40_130_ramp_limited";
  } else if (bridge_cfg::ALLOW_NONZERO_TORQUE) {
    doc["tx_policy"] = "bench_psa_3f2_only_plus_minus_10";
  } else {
    doc["tx_policy"] = "road_validation_bit_exact_zero_torque_3f2_400ms";
  }
  doc["longitudinal_tx"] = bridge_cfg::ALLOW_RVV_CONTROL;
  doc["rvv_modified_setpoint"] = bridge_cfg::ALLOW_RVV_CONTROL;
  doc["lvv_modified_setpoint"] = false;
  doc["sbu1_fail_safe"] = "low_bypass";
  doc["can0"] = "eps";
  doc["can2"] = "car_bsi";
  doc["state"] = state_name();
  emit_json(doc);
}

void emit_stats() {
  JsonDocument doc;
  doc["type"] = "stats";
  doc["state"] = state_name();
  doc["car_rx"] = car_rx_count;
  doc["eps_rx"] = eps_rx_count;
  doc["eps_tx"] = eps_tx_count;
  doc["eps_tx_failed"] = eps_tx_failed;
  doc["host_frame_drops"] = host_frame_drops;
  doc["link_rx"] = interboard.rx_packets();
  doc["link_decode_errors"] = interboard.decode_errors();
  doc["link_sequence_gaps"] = link_sequence_gaps;
  doc["peer_age_ms"] = peer_seen ? millis() - peer_last_packet_ms : 0xFFFFFFFFU;
  doc["controls_allowed"] = safety.controls_allowed();
  doc["heartbeat_engaged"] = safety.heartbeat_engaged();
  doc["cruise_engaged"] = safety.cruise_engaged();
  doc["brake_pressed"] = safety.brake_pressed();
  doc["gas_pressed"] = safety.gas_pressed();
  doc["speed_kph"] = safety.speed_kph();
  doc["driver_torque_raw"] = safety.driver_torque();
  doc["steering_angle_raw"] = safety.steering_angle();
  doc["desired_torque_raw"] = desired_torque_raw;
  doc["rvv_compile_allowed"] = bridge_cfg::ALLOW_RVV_CONTROL;
  doc["rvv_requested"] = rvv.requested();
  doc["rvv_stock_valid"] = rvv.stock_valid();
  doc["rvv_stock_mode"] = rvv.stock_mode();
  doc["rvv_stock_active"] = rvv.stock_activation();
  doc["rvv_stock_setpoint_kph"] = rvv.stock_setpoint_kph();
  doc["rvv_target_kph"] = rvv.target_kph();
  doc["rvv_applied_kph"] = rvv.applied_kph();
  doc["rvv_checksum_failures"] = rvv.checksum_failures();
  doc["rvv_controlled_frames"] = rvv.replacement_count();
  doc["rvv_reason"] = rvv.reason();
  doc["safety_reason"] = safety.reason();
  emit_json(doc);
}

void emit_host_frame(uint32_t id, bool extended, bool remote, uint8_t len, const uint8_t *data) {
  if (Serial.availableForWrite() < 96) {
    ++host_frame_drops;
    return;
  }
  char data_hex[17] = {0};
  static const char HEX_CHARS[] = "0123456789ABCDEF";
  if (!remote) {
    for (uint8_t i = 0; i < len; ++i) {
      data_hex[i * 2] = HEX_CHARS[data[i] >> 4];
      data_hex[i * 2 + 1] = HEX_CHARS[data[i] & 0xFU];
    }
  }
  const uint8_t flags = static_cast<uint8_t>((len << 2)
      | (extended ? 1U : 0U) | (remote ? 2U : 0U));
  char line[96];
  const int written = snprintf(
      line, sizeof(line), "F,%llX,%lX,%lX,%X,%s\n",
      static_cast<unsigned long long>(esp_timer_get_time()),
      static_cast<unsigned long>(frame_sequence++),
      static_cast<unsigned long>(id), flags, data_hex);
  if (written > 0 && static_cast<size_t>(written) < sizeof(line)) {
    Serial.write(reinterpret_cast<const uint8_t *>(line), written);
  } else {
    ++host_frame_drops;
  }
}

bool start_can() {
  twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT(
      bridge_cfg::CAN_TX_PIN, bridge_cfg::CAN_RX_PIN, TWAI_MODE_NORMAL);
  general.rx_queue_len = 256;
  general.tx_queue_len = 32;
  const twai_timing_config_t timing_250 = TWAI_TIMING_CONFIG_250KBITS();
  const twai_timing_config_t timing_500 = TWAI_TIMING_CONFIG_500KBITS();
  const twai_timing_config_t timing = bridge_cfg::CAN_BITRATE == 250000
      ? timing_250 : timing_500;
  const twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  if (twai_driver_install(&general, &timing, &filter) != ESP_OK) return false;
  if (twai_start() != ESP_OK) return false;
  twai_reconfigure_alerts(
      TWAI_ALERT_BUS_OFF | TWAI_ALERT_BUS_RECOVERED | TWAI_ALERT_RX_QUEUE_FULL
      | TWAI_ALERT_RX_FIFO_OVERRUN | TWAI_ALERT_TX_FAILED | TWAI_ALERT_BUS_ERROR,
      nullptr);
  return true;
}

bool transmit_eps(uint32_t id, bool extended, bool remote, uint8_t len, const uint8_t *data) {
  if (!can_ready || len > 8) return false;
  twai_message_t message{};
  message.identifier = id;
  message.extd = extended;
  message.rtr = remote;
  message.data_length_code = len;
  if (!remote) memcpy(message.data, data, len);
  if (twai_transmit(&message, 0) != ESP_OK) {
    ++eps_tx_failed;
    return false;
  }
  ++eps_tx_count;
  return true;
}

void set_sbu1(bool isolate) {
  // This GPIO drives only the input of an external fail-low 5 V source driver.
  // LOW or reset must leave OBD-C SBU1 pulled down by the harness (stock bypass).
  digitalWrite(bridge_cfg::SBU1_PIN, isolate ? HIGH : LOW);
}

void send_control(link_protocol::Type type) {
  link_protocol::Packet packet;
  packet.type = type;
  packet.flags = can_ready ? link_protocol::CanReady : 0;
  interboard.send(packet);
}

void restore_bypass(const char *reason, bool latch_fault = false) {
  const bool was_isolated = state == GatewayState::Settling || state == GatewayState::Active;
  const bool faulted = latch_fault || state == GatewayState::Fault || safety.malfunction();
  set_sbu1(false);
  send_control(link_protocol::Type::Bypass);
  safety.end_takeover(reason);
  rvv.end_takeover(reason);
  desired_torque_raw = 0;
  state = faulted ? GatewayState::Fault : GatewayState::Bypass;
  if (was_isolated || faulted) emit_event("BYPASS_RESTORED", reason);
}

bool track_peer_sequence(uint16_t sequence) {
  if (!peer_sequence_seen) {
    peer_sequence_seen = true;
    peer_sequence_last = sequence;
    return true;
  }
  const uint16_t expected = static_cast<uint16_t>(peer_sequence_last + 1U);
  peer_sequence_last = sequence;
  if (sequence == expected) return true;
  ++link_sequence_gaps;
  return false;
}

void handle_peer_packet(const link_protocol::Packet &packet, uint32_t now) {
  const bool sequence_ok = track_peer_sequence(packet.sequence);
  peer_seen = true;
  peer_last_packet_ms = now;
  peer_can_ready = (packet.flags & link_protocol::CanReady) != 0U;
  if (!sequence_ok && state != GatewayState::Bypass && state != GatewayState::Fault) {
    restore_bypass("inter-board sequence gap", true);
    return;
  }

  switch (packet.type) {
    case link_protocol::Type::Hello:
    case link_protocol::Type::Keepalive:
      return;

    case link_protocol::Type::CanFrame: {
      ++car_rx_count;
      const bool extended = (packet.flags & link_protocol::Extended) != 0U;
      const bool remote = (packet.flags & link_protocol::Remote) != 0U;
      if (!extended && !remote) {
        safety.on_car_frame(packet.identifier, packet.data, packet.length, now);
        if (packet.identifier == psa_rvv_safety::ID_RVV) {
          rvv.on_stock_frame(packet.data, packet.length, now);
        }
      }
      emit_host_frame(packet.identifier, extended, remote, packet.length, packet.data);
      if (state != GatewayState::Active || packet.identifier == psa_lka_safety::ID_LKA) return;

      const uint8_t *payload = packet.data;
      uint8_t rvv_payload[8] = {0};
      if (!extended && !remote && packet.identifier == psa_rvv_safety::ID_RVV) {
        const psa_rvv_safety::FrameAction action =
            rvv.build_from_stock(packet.data, packet.length, rvv_payload, now);
        if (action == psa_rvv_safety::FrameAction::Reject) {
          restore_bypass(rvv.reason(), true);
          return;
        }
        payload = rvv_payload;
      }
      if (!transmit_eps(packet.identifier, extended, remote, packet.length, payload)) {
        restore_bypass("EPS-side CAN forward failed", true);
      }
      return;
    }

    case link_protocol::Type::Ready:
      if (state != GatewayState::Preparing) return;
      if (!safety.begin_takeover(now)) {
        restore_bypass(safety.reason());
        return;
      }
      if (!rvv.begin_takeover(now)) {
        restore_bypass(rvv.reason());
        return;
      }
      set_sbu1(true);
      relay_cut_ms = now;
      last_lka_tx_ms = 0;
      state = GatewayState::Settling;
      emit_event("SBU1_ISOLATING");
      return;

    case link_protocol::Type::Stopped:
      return;

    case link_protocol::Type::Fault:
      restore_bypass("satellite reported a fault", true);
      return;

    case link_protocol::Type::Prepare:
    case link_protocol::Type::Active:
    case link_protocol::Type::Bypass:
      restore_bypass("unexpected inter-board control packet", true);
      return;
  }
}

void poll_interboard(uint32_t now) {
  link_protocol::Packet packet;
  for (uint16_t count = 0; count < 512 && interboard.poll(packet); ++count) {
    handle_peer_packet(packet, now);
  }
  const uint32_t errors = interboard.decode_errors();
  if (errors != link_decode_errors_seen) {
    link_decode_errors_seen = errors;
    if (state != GatewayState::Bypass && state != GatewayState::Fault) {
      restore_bypass("inter-board CRC/framing error", true);
    }
  }
}

void forward_eps_frame(const twai_message_t &message) {
  link_protocol::Packet packet;
  packet.type = link_protocol::Type::CanFrame;
  packet.identifier = message.identifier;
  packet.length = message.data_length_code;
  packet.flags = static_cast<uint8_t>(
      (message.extd ? link_protocol::Extended : 0)
      | (message.rtr ? link_protocol::Remote : 0)
      | (can_ready ? link_protocol::CanReady : 0)
      | link_protocol::BridgeActive);
  memcpy(packet.data, message.data, packet.length);
  if (!interboard.send(packet)) restore_bypass("inter-board UART TX failed", true);
}

void poll_eps_can(uint32_t now) {
  for (uint16_t count = 0; count < 256; ++count) {
    twai_message_t message{};
    if (twai_receive(&message, 0) != ESP_OK) break;
    ++eps_rx_count;
    if (!message.extd && !message.rtr) {
      safety.on_eps_frame(message.identifier, message.data_length_code, now);
    }
    if (safety.malfunction()) {
      restore_bypass(safety.reason(), true);
      return;
    }
    // 0x50E has a single validated direction: BSI/CAN2 -> engine/CAN0. Never
    // reflect a locally transmitted replacement back toward the stock BSI.
    if (state == GatewayState::Active
        && (message.extd || message.rtr || message.identifier != psa_rvv_safety::ID_RVV)) {
      forward_eps_frame(message);
    }
  }
}

void service_can_alerts() {
  uint32_t alerts = 0;
  if (twai_read_alerts(&alerts, 0) != ESP_OK) return;
  if ((alerts & TWAI_ALERT_BUS_OFF) != 0U) {
    restore_bypass("EPS-side CAN bus-off", true);
    twai_initiate_recovery();
  }
  if ((alerts & (TWAI_ALERT_RX_QUEUE_FULL | TWAI_ALERT_RX_FIFO_OVERRUN)) != 0U) {
    restore_bypass("EPS-side CAN RX overflow", true);
  }
}

void request_takeover(uint32_t now) {
  if (state == GatewayState::Fault) {
    emit_error("FAULT_LATCHED", "Reboot and diagnose before another isolation attempt");
    return;
  }
  if (state != GatewayState::Bypass) {
    emit_error("INVALID_STATE", "Gateway is not in hardware bypass");
    return;
  }
  if (!peer_seen || now - peer_last_packet_ms > bridge_cfg::LINK_TIMEOUT_MS || !peer_can_ready) {
    emit_error("PEER_NOT_READY", "CAR/CAN2 satellite is missing or stale");
    return;
  }
  if (!safety.ready_for_takeover(now)) {
    emit_error("SAFETY_NOT_READY", safety.reason());
    return;
  }
  if (!rvv.ready_for_takeover(now)) {
    emit_error("RVV_NOT_READY", rvv.reason());
    return;
  }
  send_control(link_protocol::Type::Prepare);
  state = GatewayState::Preparing;
  prepare_started_ms = now;
  emit_event("PREPARE_SENT");
}

void handle_host_command(const char *line, uint32_t now) {
  JsonDocument doc;
  const DeserializationError error = deserializeJson(doc, line);
  if (error) {
    emit_error("INVALID_JSON", error.c_str());
    return;
  }
  const char *type = doc["type"] | "";
  if (strcmp(type, "get_status") == 0) {
    emit_hello();
    emit_stats();
    return;
  }
  if (strcmp(type, "ping") == 0) {
    JsonDocument pong;
    pong["type"] = "pong";
    pong["uptime_ms"] = now;
    emit_json(pong);
    return;
  }
  if (strcmp(type, "psa_heartbeat") == 0) {
    const bool engaged = doc["engaged"] | false;
    safety.on_host_heartbeat(engaged, now);
    if (!engaged && state != GatewayState::Bypass) restore_bypass("host deadman released");
    JsonDocument ack;
    ack["type"] = "ack";
    ack["command"] = "psa_heartbeat";
    ack["engaged"] = engaged;
    emit_json(ack);
    return;
  }
  if (strcmp(type, "psa_takeover") == 0) {
    const bool enabled = doc["enabled"] | false;
    if (enabled) request_takeover(now);
    else restore_bypass("host requested bypass");
    return;
  }
  if (strcmp(type, "psa_torque") == 0) {
    if (!doc["raw"].is<int>()) {
      emit_error("INVALID_TORQUE", "raw must be an integer");
      return;
    }
    const int requested = doc["raw"].as<int>();
    if (!bridge_cfg::ALLOW_NONZERO_TORQUE && requested != 0) {
      emit_error("TORQUE_LOCKED", "This road-validation build only accepts raw=0");
      return;
    }
    if (requested < -psa_lka_safety::MAX_TORQUE_RAW
        || requested > psa_lka_safety::MAX_TORQUE_RAW) {
      emit_error("INVALID_TORQUE", "Requested torque exceeds firmware envelope");
      return;
    }
    desired_torque_raw = requested;
    JsonDocument ack;
    ack["type"] = "ack";
    ack["command"] = "psa_torque";
    ack["raw"] = desired_torque_raw;
    emit_json(ack);
    return;
  }
  if (strcmp(type, "psa_longitudinal") == 0) {
    if (!doc["enabled"].is<bool>()) {
      emit_error("INVALID_LONGITUDINAL", "enabled must be a boolean");
      return;
    }
    const bool enabled = doc["enabled"].as<bool>();
    if (!enabled) {
      rvv.set_command(false, psa_rvv_safety::MIN_SETPOINT_KPH, now);
      if (state != GatewayState::Bypass) restore_bypass("host disabled RVV control");
    } else {
      if (!bridge_cfg::ALLOW_RVV_CONTROL) {
        emit_error("LONGITUDINAL_LOCKED", "Modified 0x50E is available only in the bench RVV build");
        return;
      }
      if (!doc["target_kph"].is<int>()) {
        emit_error("INVALID_LONGITUDINAL", "target_kph must be an integer");
        return;
      }
      if (!rvv.requested() && state != GatewayState::Bypass) {
        emit_error("INVALID_STATE", "RVV control must be armed before gateway takeover");
        return;
      }
      if (!rvv.set_command(true, doc["target_kph"].as<int>(), now)) {
        emit_error("INVALID_LONGITUDINAL", rvv.reason());
        return;
      }
    }
    JsonDocument ack;
    ack["type"] = "ack";
    ack["command"] = "psa_longitudinal";
    ack["enabled"] = enabled;
    ack["target_kph"] = rvv.target_kph();
    emit_json(ack);
    return;
  }
  if (strcmp(type, "can_tx") == 0) {
    emit_error("TX_LOCKED", "Arbitrary CAN transmit is not available");
    return;
  }
  emit_error("UNKNOWN_COMMAND", "Unsupported host command");
}

void poll_host(uint32_t now) {
  size_t processed = 0;
  while (Serial.available() > 0 && processed++ < 1024) {
    const int value = Serial.read();
    if (value < 0) break;
    const char character = static_cast<char>(value);
    if (character == '\n') {
      if (!host_line_discard && host_line_length > 0) {
        if (host_line[host_line_length - 1] == '\r') --host_line_length;
        host_line[host_line_length] = '\0';
        handle_host_command(host_line, now);
      }
      host_line_length = 0;
      host_line_discard = false;
      continue;
    }
    if (host_line_discard) continue;
    if (host_line_length + 1 >= sizeof(host_line)) {
      host_line_discard = true;
      emit_error("COMMAND_TOO_LARGE", "Host command exceeds input buffer");
      continue;
    }
    host_line[host_line_length++] = character;
  }
}

void service_state(uint32_t now) {
  safety.tick(now);
  if (!rvv.tick(now)
      && (state == GatewayState::Preparing || state == GatewayState::Settling
          || state == GatewayState::Active)) {
    restore_bypass(rvv.reason(), true);
    return;
  }
  const bool peer_stale = !peer_seen || now - peer_last_packet_ms > bridge_cfg::LINK_TIMEOUT_MS;
  if (peer_stale && state != GatewayState::Bypass && state != GatewayState::Fault) {
    restore_bypass("inter-board heartbeat timeout", true);
    return;
  }
  if (!safety.controls_allowed()
      && (state == GatewayState::Preparing || state == GatewayState::Settling
          || state == GatewayState::Active)) {
    restore_bypass(safety.reason());
    return;
  }
  if (state == GatewayState::Preparing
      && now - prepare_started_ms > bridge_cfg::PREPARE_TIMEOUT_MS) {
    restore_bypass("satellite prepare timeout", true);
    return;
  }
  if (state == GatewayState::Settling
      && now - relay_cut_ms >= bridge_cfg::RELAY_SETTLE_MS) {
    send_control(link_protocol::Type::Active);
    state = GatewayState::Active;
    emit_event(rvv.requested() ? "BRIDGE_ACTIVE_RVV_BENCH" : "BRIDGE_ACTIVE_ZERO_TORQUE");
  }
  if (state == GatewayState::Active) {
    if (now - relay_cut_ms > bridge_cfg::MAX_TAKEOVER_MS) {
      restore_bypass("configured validation window complete");
      return;
    }
    if (last_lka_tx_ms == 0 || now - last_lka_tx_ms >= bridge_cfg::LKA_PERIOD_MS) {
      uint8_t lka[8] = {0};
      if (!safety.build_and_check_lka(desired_torque_raw, lka, now)) {
        restore_bypass(safety.reason());
        return;
      }
      if (!transmit_eps(psa_lka_safety::ID_LKA, false, false, 8, lka)) {
        restore_bypass("0x3F2 transmit failed", true);
        return;
      }
      last_lka_tx_ms = now;
    }
  }

  if (now - last_keepalive_ms >= bridge_cfg::LINK_KEEPALIVE_MS) {
    link_protocol::Packet keepalive;
    keepalive.type = link_protocol::Type::Keepalive;
    keepalive.flags = static_cast<uint8_t>((can_ready ? link_protocol::CanReady : 0)
        | (state == GatewayState::Active ? link_protocol::BridgeActive : 0));
    interboard.send(keepalive);
    last_keepalive_ms = now;
  }
}

}  // namespace

void setup() {
  pinMode(bridge_cfg::SBU1_PIN, OUTPUT);
  set_sbu1(false);
  safety.reset();
  rvv.reset();

  Serial.setRxBufferSize(2048);
  Serial.setTxBufferSize(8192);
  Serial.begin(bridge_cfg::HOST_SERIAL_BAUD);
  interboard.begin(bridge_cfg::LINK_BAUD, bridge_cfg::LINK_RX_PIN, bridge_cfg::LINK_TX_PIN);
  can_ready = start_can();
  send_control(link_protocol::Type::Hello);
  emit_hello();
  if (!can_ready) emit_error("CAN_INIT_FAILED", "EPS/CAN0 TWAI controller did not start");
}

void loop() {
  const uint32_t now = millis();
  poll_interboard(now);
  poll_eps_can(now);
  service_can_alerts();
  poll_host(now);
  service_state(now);
  if (now - last_stats_ms >= bridge_cfg::STATS_PERIOD_MS) {
    emit_stats();
    last_stats_ms = now;
  }
}
