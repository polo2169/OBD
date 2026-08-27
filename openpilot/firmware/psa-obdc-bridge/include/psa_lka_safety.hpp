#pragma once

#include <Arduino.h>
#include <string.h>

#include "bridge_config.hpp"
#include "psa_mads.hpp"

// Safety core specific to the locally observed Peugeot 308 II T9 messages.
// It has two distinct RX entry points: car-side stock 0x3F2 is expected after
// isolation, while an EPS-side 0x3F2 after settling means isolation failed.
namespace psa_lka_safety {

constexpr uint32_t ID_DYN_CMM = 0x208;
constexpr uint32_t ID_STEERING = 0x2F5;
constexpr uint32_t ID_STEERING_ALT = 0x305;
constexpr uint32_t ID_SPEED = 0x38D;
constexpr uint32_t ID_DAT_BSI = 0x412;
constexpr uint32_t ID_LKA = 0x3F2;

constexpr uint32_t HEARTBEAT_TIMEOUT_MS = 300;
constexpr uint32_t RX_TIMEOUT_MS = 500;
constexpr uint32_t STOCK_TIMEOUT_MS = 150;
constexpr int DRIVER_OVERRIDE_RAW = 8;
constexpr int MAX_STEERING_ANGLE_RAW = 900;
constexpr float MIN_SPEED_KPH = bridge_cfg::MIN_CONTROL_SPEED_KPH;
constexpr float MAX_SPEED_KPH = bridge_cfg::MAX_CONTROL_SPEED_KPH;
constexpr int MAX_TORQUE_RAW = 10;
constexpr int MAX_TORQUE_RATE_UP = 1;
constexpr int MAX_TORQUE_RATE_DOWN = 3;
constexpr int MAX_RT_DELTA = 4;
constexpr uint32_t RT_INTERVAL_MS = 250;

struct LiveValue {
  uint32_t last_seen_ms = 0;
  bool seen = false;
};

class Safety {
 public:
  void reset() {
    heartbeat_engaged_ = false;
    cruise_engaged_ = false;
    brake_pressed_ = false;
    gas_pressed_ = false;
    physical_mads_enable_ = false;
    relay_cut_ = false;
    relay_malfunction_ = false;
    stock_seen_ = false;
    takeover_template_valid_ = false;
    last_heartbeat_ms_ = 0;
    relay_cut_ms_ = 0;
    desired_torque_last_ = 0;
    rt_torque_last_ = 0;
    rt_torque_ms_ = 0;
    speed_kph_ = 0.0f;
    driver_torque_ = 0;
    steering_angle_ = 0;
    speed_checksum_failures_ = 0;
    driver_live_ = LiveValue{};
    angle_live_ = LiveValue{};
    speed_live_ = LiveValue{};
    powertrain_live_ = LiveValue{};
    brake_live_ = LiveValue{};
    memset(stock_template_, 0, sizeof(stock_template_));
    memset(takeover_template_, 0, sizeof(takeover_template_));
    mads_.reset();
    set_reason("not armed");
  }

  void on_host_heartbeat(bool engaged, uint32_t now) {
    heartbeat_engaged_ = engaged;
    last_heartbeat_ms_ = now;
    if (!engaged) disengage("host deadman released");
    refresh_mads(now);
  }

  void on_physical_mads_enable(bool enabled, uint32_t now) {
    physical_mads_enable_ = enabled;
    refresh_mads(now);
  }

  void on_mads_command(bool enabled, uint32_t now) {
    mads_.set_requested(enabled);
    refresh_mads(now);
  }

  void on_car_frame(uint32_t id, const uint8_t *data, uint8_t len, uint32_t now) {
    if (id == ID_LKA) {
      if (!relay_cut_ && len == 8 && stock_template_usable(data)) {
        memcpy(stock_template_, data, 8);
        stock_last_seen_ms_ = now;
        stock_seen_ = true;
      }
      return;
    }

    if (id == ID_STEERING && len >= 2) {
      driver_torque_ = signed_value(data[1], 8);
      mark(driver_live_, now);
      if (abs_int(driver_torque_) > DRIVER_OVERRIDE_RAW) reset_torque_history();
      refresh_mads(now);
      return;
    }

    if (id == ID_STEERING_ALT && len >= 2) {
      steering_angle_ = signed_value(
          (static_cast<uint32_t>(data[0]) << 8) | data[1], 16);
      mark(angle_live_, now);
      if (abs_int(steering_angle_) > MAX_STEERING_ANGLE_RAW) {
        disengage("steering angle outside initial envelope");
      }
      refresh_mads(now);
      return;
    }

    if (id == ID_SPEED && len >= 6) {
      const uint8_t expected = nibble_checksum(data, len, 0x7, 5);
      if (expected != (data[5] & 0xFU)) {
        if (++speed_checksum_failures_ >= 3) disengage("0x38D checksum failures");
        return;
      }
      speed_checksum_failures_ = 0;
      speed_kph_ = static_cast<float>((static_cast<uint16_t>(data[0]) << 8) | data[1]) * 0.01f;
      mark(speed_live_, now);
      refresh_mads(now);
      return;
    }

    if (id == ID_DAT_BSI && len >= 1) {
      brake_pressed_ = ((data[0] >> 5) & 1U) != 0U;
      mark(brake_live_, now);
      refresh_mads(now);
      return;
    }

    if (id == ID_DYN_CMM && len >= 5) {
      gas_pressed_ = data[3] > 0U;
      cruise_engaged_ = ((data[4] >> 2) & 0x3U) == 2U;
      mark(powertrain_live_, now);
      // Deliberately do not alter MADS here: accelerator and RVV state are
      // longitudinal inputs, not lateral engagement inputs.
    }
  }

  void on_eps_frame(uint32_t id, uint8_t len, uint32_t now) {
    if (id == ID_LKA && len == 8 && relay_cut_
        && now - relay_cut_ms_ > bridge_cfg::RELAY_SETTLE_MS) {
      relay_malfunction_ = true;
      disengage("stock 0x3F2 still visible on EPS side after isolation");
    }
  }

  bool ready_for_takeover(uint32_t now) {
    tick(now);
    if (relay_malfunction_) return reject("relay malfunction latched");
    if (!heartbeat_engaged_) return reject("host heartbeat not engaged");
    if (!mads_.torque_allowed()) return reject(mads_.reason());
    if (!lateral_inputs_fresh(now)) return reject("lateral safety CAN inputs stale or missing");
    if (!stock_fresh(now)) return reject("fresh usable stock 0x3F2 missing");
    if (brake_pressed_) return reject("physical brake blocks takeover");
    if (!speed_in_envelope()) return reject("speed outside configured control envelope");
    if (abs_int(driver_torque_) > DRIVER_OVERRIDE_RAW) return reject("driver torque override");
    return true;
  }

  bool begin_takeover(uint32_t now) {
    if (!ready_for_takeover(now)) return false;
    memcpy(takeover_template_, stock_template_, 8);
    takeover_template_valid_ = true;
    relay_cut_ = true;
    relay_cut_ms_ = now;
    desired_torque_last_ = 0;
    rt_torque_last_ = 0;
    rt_torque_ms_ = now;
    return true;
  }

  void end_takeover(const char *reason = "hardware bypass restored") {
    relay_cut_ = false;
    takeover_template_valid_ = false;
    mads_.force_disengage(reason);
    reset_torque_history();
    set_reason(reason);
  }

  void fault(const char *reason) {
    mads_.fault(reason);
    reset_torque_history();
    set_reason(reason);
  }

  void tick(uint32_t now) {
    if (relay_cut_ && now - relay_cut_ms_ > bridge_cfg::MAX_TAKEOVER_MS) {
      disengage("takeover duration exceeded configured limit");
    }
    if (!heartbeat_engaged_ || now - last_heartbeat_ms_ > HEARTBEAT_TIMEOUT_MS) {
      heartbeat_engaged_ = false;
      disengage("host heartbeat timeout");
    }
    refresh_mads(now);
  }

  bool build_and_check_lka(int desired_torque, uint8_t *output, uint32_t now) {
    if (!relay_cut_ || !takeover_template_valid_) return reject("relay/template not active");
    if (now - relay_cut_ms_ <= bridge_cfg::RELAY_SETTLE_MS) return reject("relay has not settled");
    if (now - relay_cut_ms_ > bridge_cfg::MAX_TAKEOVER_MS) return reject("takeover duration exceeded");
    if (!ready_during_takeover(now)) return false;

    memcpy(output, takeover_template_, 8);
    const int gated_torque = mads_.torque_allowed() ? desired_torque : 0;
    if (!bridge_cfg::ALLOW_NONZERO_TORQUE && gated_torque != 0) {
      return reject("road-validation build is zero-torque only");
    }
    if (gated_torque != 0
        && (decode_state(takeover_template_) != 4 || decode_factor(takeover_template_) != 100)) {
      return reject("non-zero torque requires stock state 4 / factor 100 seed");
    }
    if (abs_int(gated_torque) > MAX_TORQUE_RAW) return reject("torque exceeds +/-10 raw");

    const int delta = gated_torque - desired_torque_last_;
    const bool increasing = abs_int(gated_torque) > abs_int(desired_torque_last_);
    if (abs_int(delta) > (increasing ? MAX_TORQUE_RATE_UP : MAX_TORQUE_RATE_DOWN)) {
      return reject("torque rate exceeds initial limit");
    }
    if (now - rt_torque_ms_ >= RT_INTERVAL_MS) {
      rt_torque_last_ = gated_torque;
      rt_torque_ms_ = now;
    } else if (abs_int(gated_torque - rt_torque_last_) > MAX_RT_DELTA) {
      return reject("real-time torque delta exceeds limit");
    }

    const uint16_t raw = static_cast<uint16_t>(gated_torque) & 0x7FFU;
    output[3] = static_cast<uint8_t>(raw >> 3);
    output[4] = static_cast<uint8_t>((output[4] & 0x1FU) | ((raw & 0x7U) << 5));
    if (!bridge_cfg::ALLOW_NONZERO_TORQUE
        && memcmp(output, takeover_template_, 8) != 0) {
      return reject("zero-torque frame must be bit-exact stock payload");
    }
    desired_torque_last_ = gated_torque;
    set_reason("");
    return true;
  }

  bool relay_cut() const { return relay_cut_; }
  bool malfunction() const { return relay_malfunction_; }
  bool controls_allowed() const { return mads_.torque_allowed(); }
  bool mads_engaged() const { return mads_.engaged(); }
  bool mads_requested() const { return mads_.requested(); }
  bool mads_rearm_required() const { return mads_.rearm_required(); }
  const char *mads_state_name() const { return psa_mads::Controller::state_name(mads_.state()); }
  const char *mads_reason() const { return mads_.reason(); }
  bool heartbeat_engaged() const { return heartbeat_engaged_; }
  bool physical_mads_enable() const { return physical_mads_enable_; }
  bool cruise_engaged() const { return cruise_engaged_; }
  bool brake_pressed() const { return brake_pressed_; }
  bool gas_pressed() const { return gas_pressed_; }
  float speed_kph() const { return speed_kph_; }
  int driver_torque() const { return driver_torque_; }
  int steering_angle() const { return steering_angle_; }
  const char *reason() const { return reason_; }

  bool longitudinal_inputs_ok(uint32_t now) const {
    return fresh(powertrain_live_, now) && cruise_engaged_ && !brake_pressed_ && !gas_pressed_;
  }

 private:
  static int abs_int(int value) { return value < 0 ? -value : value; }

  static int signed_value(uint32_t raw, uint8_t bits) {
    const uint32_t sign = 1UL << (bits - 1U);
    return (raw & sign) != 0U
        ? static_cast<int>(raw) - static_cast<int>(1UL << bits)
        : static_cast<int>(raw);
  }

  static uint8_t nibble_checksum(
      const uint8_t *data, uint8_t len, uint8_t initial, int checksum_byte) {
    uint8_t sum = 0;
    for (uint8_t i = 0; i < len; ++i) {
      uint8_t value = data[i];
      if (i == checksum_byte) value &= 0xF0U;
      sum = static_cast<uint8_t>(sum + (value >> 4) + (value & 0xFU));
    }
    return static_cast<uint8_t>((initial - sum) & 0xFU);
  }

  static int decode_torque(const uint8_t *data) {
    return signed_value((static_cast<uint16_t>(data[3]) << 3) | (data[4] >> 5), 11);
  }

  static int decode_angle(const uint8_t *data) {
    return signed_value((static_cast<uint16_t>(data[6]) << 6) | (data[7] >> 2), 14);
  }

  static uint8_t decode_state(const uint8_t *data) { return (data[4] >> 2) & 0x7U; }
  static uint8_t decode_factor(const uint8_t *data) { return data[5] >> 1; }

  static void mark(LiveValue &value, uint32_t now) {
    value.seen = true;
    value.last_seen_ms = now;
  }

  static bool fresh(const LiveValue &value, uint32_t now) {
    return value.seen && now - value.last_seen_ms <= RX_TIMEOUT_MS;
  }

  bool lateral_inputs_fresh(uint32_t now) const {
    return fresh(driver_live_, now) && fresh(angle_live_, now) && fresh(speed_live_, now)
        && fresh(brake_live_, now);
  }

  bool speed_in_envelope() const {
    return speed_kph_ >= MIN_SPEED_KPH && speed_kph_ <= MAX_SPEED_KPH;
  }

  bool stock_template_usable(const uint8_t *data) const {
    const uint8_t state = decode_state(data);
    return (state == 2 || state == 3 || state == 4)
        && decode_factor(data) <= 100
        && (data[5] & 1U) == 0U
        && decode_angle(data) == 0
        && (bridge_cfg::ALLOW_NONZERO_TORQUE || decode_torque(data) == 0);
  }

  bool stock_fresh(uint32_t now) const {
    return stock_seen_ && now - stock_last_seen_ms_ <= STOCK_TIMEOUT_MS
        && stock_template_usable(stock_template_);
  }

  bool ready_during_takeover(uint32_t now) {
    tick(now);
    if (!relay_cut_ || !mads_.engaged() || !heartbeat_engaged_) return reject("MADS lateral control not engaged");
    if (!lateral_inputs_fresh(now)) return reject("lateral safety CAN inputs stale or missing");
    if (brake_pressed_) return reject("physical brake blocks steering");
    if (!speed_in_envelope()) return reject("speed outside initial envelope");
    return true;
  }

  bool reject(const char *reason) {
    set_reason(reason);
    return false;
  }

  void disengage(const char *reason) {
    mads_.force_disengage(reason);
    reset_torque_history();
    set_reason(reason);
  }

  void reset_torque_history() {
    desired_torque_last_ = 0;
    rt_torque_last_ = 0;
  }

  void refresh_mads(uint32_t now) {
    psa_mads::Inputs inputs;
    inputs.heartbeat_fresh = heartbeat_engaged_
        && now - last_heartbeat_ms_ <= HEARTBEAT_TIMEOUT_MS;
    inputs.physical_enable = physical_mads_enable_;
    inputs.lateral_inputs_fresh = lateral_inputs_fresh(now);
    inputs.speed_in_envelope = speed_in_envelope();
    inputs.brake_pressed = brake_pressed_;
    inputs.driver_override = abs_int(driver_torque_) > DRIVER_OVERRIDE_RAW;
    mads_.update(inputs, now);
    if (!mads_.torque_allowed()) reset_torque_history();
  }

  void set_reason(const char *reason) {
    strlcpy(reason_, reason, sizeof(reason_));
  }

  bool heartbeat_engaged_ = false;
  bool cruise_engaged_ = false;
  bool brake_pressed_ = false;
  bool gas_pressed_ = false;
  bool physical_mads_enable_ = false;
  bool relay_cut_ = false;
  bool relay_malfunction_ = false;
  bool stock_seen_ = false;
  bool takeover_template_valid_ = false;
  uint8_t speed_checksum_failures_ = 0;
  uint32_t last_heartbeat_ms_ = 0;
  uint32_t relay_cut_ms_ = 0;
  uint32_t stock_last_seen_ms_ = 0;
  uint32_t rt_torque_ms_ = 0;
  float speed_kph_ = 0.0f;
  int driver_torque_ = 0;
  int steering_angle_ = 0;
  int desired_torque_last_ = 0;
  int rt_torque_last_ = 0;
  LiveValue driver_live_;
  LiveValue angle_live_;
  LiveValue speed_live_;
  LiveValue powertrain_live_;
  LiveValue brake_live_;
  psa_mads::Controller mads_;
  uint8_t stock_template_[8] = {0};
  uint8_t takeover_template_[8] = {0};
  char reason_[112] = "not armed";
};

}  // namespace psa_lka_safety
