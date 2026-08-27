#include <Arduino.h>
#include <ArduinoJson.h>
#include <driver/twai.h>

#include "bridge_config.hpp"
#include "link_protocol.hpp"
#include "psa_lka_safety.hpp"
#include "psa_rvv_safety.hpp"

#if !PSA_ROLE_SATELLITE
#error "satellite_main.cpp requires PSA_ROLE_SATELLITE=1"
#endif

namespace {

enum class SatelliteState : uint8_t {
  Bypass,
  Prepared,
  Active,
  Fault,
};

HardwareSerial interboard_serial(2);
link_protocol::Link interboard(interboard_serial);
SatelliteState state = SatelliteState::Bypass;
bool can_ready = false;
bool peer_seen = false;
bool peer_sequence_seen = false;
uint16_t peer_sequence_last = 0;
uint32_t peer_last_packet_ms = 0;
uint32_t prepared_ms = 0;
uint32_t last_keepalive_ms = 0;
uint32_t last_stats_ms = 0;
uint32_t car_rx_count = 0;
uint32_t car_tx_count = 0;
uint32_t car_tx_failed = 0;
uint32_t link_sequence_gaps = 0;
uint32_t link_decode_errors_seen = 0;

const char *state_name() {
  switch (state) {
    case SatelliteState::Bypass: return "bypass";
    case SatelliteState::Prepared: return "prepared";
    case SatelliteState::Active: return "active";
    case SatelliteState::Fault: return "fault";
  }
  return "unknown";
}

void emit_status() {
  JsonDocument doc;
  doc["type"] = "psa_satellite_stats";
  doc["role"] = "satellite_car_can2";
  doc["state"] = state_name();
  doc["can_ready"] = can_ready;
  doc["car_rx"] = car_rx_count;
  doc["car_tx"] = car_tx_count;
  doc["car_tx_failed"] = car_tx_failed;
  doc["link_rx"] = interboard.rx_packets();
  doc["link_decode_errors"] = interboard.decode_errors();
  doc["link_sequence_gaps"] = link_sequence_gaps;
  serializeJson(doc, Serial);
  Serial.write('\n');
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

void send_control(link_protocol::Type type) {
  link_protocol::Packet packet;
  packet.type = type;
  packet.flags = static_cast<uint8_t>((can_ready ? link_protocol::CanReady : 0)
      | (state == SatelliteState::Active ? link_protocol::BridgeActive : 0));
  interboard.send(packet);
}

void stop_forwarding(bool fault) {
  const bool faulted = fault || state == SatelliteState::Fault;
  state = faulted ? SatelliteState::Fault : SatelliteState::Bypass;
  send_control(fault ? link_protocol::Type::Fault : link_protocol::Type::Stopped);
}

bool transmit_car(const link_protocol::Packet &packet) {
  if (!can_ready || packet.length > 8) return false;
  twai_message_t message{};
  message.identifier = packet.identifier;
  message.extd = (packet.flags & link_protocol::Extended) != 0U;
  message.rtr = (packet.flags & link_protocol::Remote) != 0U;
  message.data_length_code = packet.length;
  if (!message.rtr) memcpy(message.data, packet.data, packet.length);
  if (twai_transmit(&message, 0) != ESP_OK) {
    ++car_tx_failed;
    return false;
  }
  ++car_tx_count;
  return true;
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
  if (!sequence_ok && state != SatelliteState::Bypass && state != SatelliteState::Fault) {
    stop_forwarding(true);
    return;
  }

  switch (packet.type) {
    case link_protocol::Type::Hello:
    case link_protocol::Type::Keepalive:
      return;

    case link_protocol::Type::Prepare:
      if (state != SatelliteState::Bypass || !can_ready) {
        stop_forwarding(true);
        return;
      }
      state = SatelliteState::Prepared;
      prepared_ms = now;
      send_control(link_protocol::Type::Ready);
      return;

    case link_protocol::Type::Active:
      if (state != SatelliteState::Prepared
          || now - prepared_ms > bridge_cfg::PREPARE_TIMEOUT_MS) {
        stop_forwarding(true);
        return;
      }
      state = SatelliteState::Active;
      return;

    case link_protocol::Type::Bypass:
      stop_forwarding(false);
      return;

    case link_protocol::Type::CanFrame:
      if (state != SatelliteState::Active) return;
      // Stock BSI remains the only producer of 0x3F2 and 0x50E on CAN2. Their
      // checked replacements are permitted only on CAN0 and never reflected
      // toward the BSI.
      if (packet.identifier == psa_lka_safety::ID_LKA
          || packet.identifier == psa_rvv_safety::ID_RVV) {
        stop_forwarding(true);
        return;
      }
      if (!transmit_car(packet)) stop_forwarding(true);
      return;

    case link_protocol::Type::Fault:
    case link_protocol::Type::Ready:
    case link_protocol::Type::Stopped:
      stop_forwarding(true);
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
    if (state == SatelliteState::Prepared || state == SatelliteState::Active) {
      stop_forwarding(true);
    }
  }
}

void send_car_frame(const twai_message_t &message) {
  link_protocol::Packet packet;
  packet.type = link_protocol::Type::CanFrame;
  packet.identifier = message.identifier;
  packet.length = message.data_length_code;
  packet.flags = static_cast<uint8_t>(
      (message.extd ? link_protocol::Extended : 0)
      | (message.rtr ? link_protocol::Remote : 0)
      | (can_ready ? link_protocol::CanReady : 0)
      | (state == SatelliteState::Active ? link_protocol::BridgeActive : 0));
  memcpy(packet.data, message.data, packet.length);
  if (!interboard.send(packet) && state == SatelliteState::Active) stop_forwarding(true);
}

void poll_car_can() {
  for (uint16_t count = 0; count < 256; ++count) {
    twai_message_t message{};
    if (twai_receive(&message, 0) != ESP_OK) break;
    ++car_rx_count;
    send_car_frame(message);
  }
}

void service_can_alerts() {
  uint32_t alerts = 0;
  if (twai_read_alerts(&alerts, 0) != ESP_OK) return;
  if ((alerts & TWAI_ALERT_BUS_OFF) != 0U) {
    stop_forwarding(true);
    twai_initiate_recovery();
  }
  if ((alerts & (TWAI_ALERT_RX_QUEUE_FULL | TWAI_ALERT_RX_FIFO_OVERRUN)) != 0U) {
    stop_forwarding(true);
  }
}

void service_state(uint32_t now) {
  if ((state == SatelliteState::Prepared || state == SatelliteState::Active)
      && (!peer_seen || now - peer_last_packet_ms > bridge_cfg::LINK_TIMEOUT_MS)) {
    stop_forwarding(true);
  }
  if (state == SatelliteState::Prepared
      && now - prepared_ms > bridge_cfg::PREPARE_TIMEOUT_MS) {
    stop_forwarding(true);
  }
  if (now - last_keepalive_ms >= bridge_cfg::LINK_KEEPALIVE_MS) {
    send_control(link_protocol::Type::Keepalive);
    last_keepalive_ms = now;
  }
}

}  // namespace

void setup() {
  Serial.setTxBufferSize(2048);
  Serial.begin(bridge_cfg::HOST_SERIAL_BAUD);
  interboard.begin(bridge_cfg::LINK_BAUD, bridge_cfg::LINK_RX_PIN, bridge_cfg::LINK_TX_PIN);
  can_ready = start_can();
  send_control(link_protocol::Type::Hello);
  emit_status();
}

void loop() {
  const uint32_t now = millis();
  poll_interboard(now);
  poll_car_can();
  service_can_alerts();
  service_state(now);
  if (now - last_stats_ms >= bridge_cfg::STATS_PERIOD_MS) {
    emit_status();
    last_stats_ms = now;
  }
}
