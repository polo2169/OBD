#pragma once

#include <Arduino.h>
#include <HardwareSerial.h>
#include <string.h>

namespace link_protocol {

constexpr uint8_t MAGIC_0 = 0xA5;
constexpr uint8_t MAGIC_1 = 0x5A;
constexpr uint8_t VERSION = 1;
constexpr size_t WIRE_SIZE = 22;

enum class Type : uint8_t {
  Hello = 1,
  Keepalive = 2,
  CanFrame = 3,
  Prepare = 4,
  Ready = 5,
  Active = 6,
  Bypass = 7,
  Stopped = 8,
  Fault = 9,
};

enum Flag : uint8_t {
  Extended = 1U << 0,
  Remote = 1U << 1,
  CanReady = 1U << 2,
  BridgeActive = 1U << 3,
};

struct Packet {
  Type type = Type::Hello;
  uint16_t sequence = 0;
  uint32_t identifier = 0;
  uint8_t length = 0;
  uint8_t flags = 0;
  uint8_t data[8] = {0};
};

static uint16_t crc16_ccitt(const uint8_t *bytes, size_t length) {
  uint16_t crc = 0xFFFFU;
  for (size_t i = 0; i < length; ++i) {
    crc ^= static_cast<uint16_t>(bytes[i]) << 8;
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x8000U) != 0U
          ? static_cast<uint16_t>((crc << 1) ^ 0x1021U)
          : static_cast<uint16_t>(crc << 1);
    }
  }
  return crc;
}

static void encode(const Packet &packet, uint8_t *wire) {
  memset(wire, 0, WIRE_SIZE);
  wire[0] = MAGIC_0;
  wire[1] = MAGIC_1;
  wire[2] = VERSION;
  wire[3] = static_cast<uint8_t>(packet.type);
  wire[4] = static_cast<uint8_t>(packet.sequence & 0xFFU);
  wire[5] = static_cast<uint8_t>(packet.sequence >> 8);
  wire[6] = static_cast<uint8_t>(packet.identifier & 0xFFU);
  wire[7] = static_cast<uint8_t>((packet.identifier >> 8) & 0xFFU);
  wire[8] = static_cast<uint8_t>((packet.identifier >> 16) & 0xFFU);
  wire[9] = static_cast<uint8_t>((packet.identifier >> 24) & 0xFFU);
  wire[10] = packet.length;
  wire[11] = packet.flags;
  memcpy(wire + 12, packet.data, sizeof(packet.data));
  const uint16_t crc = crc16_ccitt(wire, 20);
  wire[20] = static_cast<uint8_t>(crc & 0xFFU);
  wire[21] = static_cast<uint8_t>(crc >> 8);
}

static bool decode(const uint8_t *wire, Packet &packet) {
  if (wire[0] != MAGIC_0 || wire[1] != MAGIC_1 || wire[2] != VERSION) return false;
  const uint16_t received = static_cast<uint16_t>(wire[20])
      | (static_cast<uint16_t>(wire[21]) << 8);
  if (received != crc16_ccitt(wire, 20)) return false;
  if (wire[10] > 8U) return false;
  const uint8_t raw_type = wire[3];
  if (raw_type < static_cast<uint8_t>(Type::Hello)
      || raw_type > static_cast<uint8_t>(Type::Fault)) return false;

  packet.type = static_cast<Type>(raw_type);
  packet.sequence = static_cast<uint16_t>(wire[4])
      | (static_cast<uint16_t>(wire[5]) << 8);
  packet.identifier = static_cast<uint32_t>(wire[6])
      | (static_cast<uint32_t>(wire[7]) << 8)
      | (static_cast<uint32_t>(wire[8]) << 16)
      | (static_cast<uint32_t>(wire[9]) << 24);
  packet.length = wire[10];
  packet.flags = wire[11];
  memcpy(packet.data, wire + 12, sizeof(packet.data));
  return true;
}

class Link {
 public:
  explicit Link(HardwareSerial &serial) : serial_(serial) {}

  void begin(uint32_t baud, int8_t rx_pin, int8_t tx_pin) {
    serial_.setRxBufferSize(8192);
    serial_.setTxBufferSize(4096);
    serial_.begin(baud, SERIAL_8N1, rx_pin, tx_pin);
  }

  bool send(Packet packet) {
    packet.sequence = tx_sequence_++;
    uint8_t wire[WIRE_SIZE];
    encode(packet, wire);
    return serial_.write(wire, sizeof(wire)) == sizeof(wire);
  }

  bool poll(Packet &packet) {
    while (serial_.available() > 0) {
      const int value = serial_.read();
      if (value < 0) break;
      if (length_ == 0 && static_cast<uint8_t>(value) != MAGIC_0) continue;
      if (length_ == 1 && static_cast<uint8_t>(value) != MAGIC_1) {
        length_ = static_cast<uint8_t>(value) == MAGIC_0 ? 1 : 0;
        continue;
      }
      buffer_[length_++] = static_cast<uint8_t>(value);
      if (length_ != WIRE_SIZE) continue;
      length_ = 0;
      if (!decode(buffer_, packet)) {
        ++decode_errors_;
        return false;
      }
      ++rx_packets_;
      return true;
    }
    return false;
  }

  uint32_t decode_errors() const { return decode_errors_; }
  uint32_t rx_packets() const { return rx_packets_; }

 private:
  HardwareSerial &serial_;
  uint16_t tx_sequence_ = 0;
  uint8_t buffer_[WIRE_SIZE] = {0};
  size_t length_ = 0;
  uint32_t decode_errors_ = 0;
  uint32_t rx_packets_ = 0;
};

}  // namespace link_protocol
