#pragma once

#include <stdint.h>
#include <string.h>

#ifndef PSA_ALLOW_RVV_CONTROL
#define PSA_ALLOW_RVV_CONTROL 0
#endif

// Controller for the locally observed Peugeot 308 II T9 classic cruise frame.
// 0x50E is produced by the BSI at 10 Hz and consumed by the engine ECU. During
// gateway isolation, the stock counter, mode, activation request and all
// unrelated payload bits remain sourced by the BSI. Only the setpoint byte and
// its two-bit parity code may be replaced.
namespace psa_rvv_safety {

constexpr uint32_t ID_RVV = 0x50E;
constexpr uint32_t STOCK_TIMEOUT_MS = 250;
constexpr uint32_t COMMAND_TIMEOUT_MS = 300;
constexpr uint32_t SETPOINT_STEP_INTERVAL_MS = 500;
constexpr uint8_t MIN_SETPOINT_KPH = 40;
constexpr uint8_t MAX_SETPOINT_KPH = 130;
constexpr uint8_t MODE_RVV = 1;
constexpr bool CONTROL_COMPILED = PSA_ALLOW_RVV_CONTROL != 0;

enum class FrameAction : uint8_t {
  PassThrough,
  Replaced,
  Reject,
};

class Controller {
 public:
  void reset() {
    requested_ = false;
    takeover_active_ = false;
    command_seen_ = false;
    stock_seen_ = false;
    stock_valid_ = false;
    applied_valid_ = false;
    target_kph_ = MIN_SETPOINT_KPH;
    applied_kph_ = MIN_SETPOINT_KPH;
    stock_setpoint_kph_ = 0xFFU;
    stock_mode_ = 0;
    stock_activation_ = false;
    last_command_ms_ = 0;
    last_stock_ms_ = 0;
    last_step_ms_ = 0;
    checksum_failures_ = 0;
    replacement_count_ = 0;
    set_reason("not requested");
  }

  bool set_command(bool enabled, int target_kph, uint32_t now) {
    if (!enabled) {
      requested_ = false;
      command_seen_ = true;
      last_command_ms_ = now;
      set_reason("not requested");
      return true;
    }
    if (!CONTROL_COMPILED) {
      return reject("modified RVV setpoints are compile-locked");
    }
    if (target_kph < MIN_SETPOINT_KPH || target_kph > MAX_SETPOINT_KPH) {
      return reject("RVV target outside 40..130 km/h");
    }
    requested_ = true;
    command_seen_ = true;
    target_kph_ = static_cast<uint8_t>(target_kph);
    last_command_ms_ = now;
    set_reason("");
    return true;
  }

  void on_stock_frame(const uint8_t *data, uint8_t len, uint32_t now) {
    if (len != 8U) {
      stock_valid_ = false;
      set_reason("0x50E DLC is not 8");
      return;
    }
    const uint8_t setpoint = data[6];
    if (decode_checksum(data) != checksum_for_setpoint(setpoint)) {
      stock_valid_ = false;
      ++checksum_failures_;
      set_reason("stock 0x50E setpoint checksum invalid");
      return;
    }
    stock_seen_ = true;
    stock_valid_ = true;
    stock_setpoint_kph_ = setpoint;
    stock_mode_ = decode_mode(data);
    stock_activation_ = decode_activation(data);
    last_stock_ms_ = now;
  }

  bool ready_for_takeover(uint32_t now) {
    if (!requested_) return true;
    if (!CONTROL_COMPILED) return reject("modified RVV setpoints are compile-locked");
    if (!command_fresh(now)) return reject("RVV host command stale or missing");
    if (!stock_fresh(now)) return reject("fresh valid stock 0x50E missing");
    if (stock_mode_ != MODE_RVV) return reject("RVV requested while selector is not in RVV mode");
    if (!stock_activation_) return reject("RVV must already be active before takeover");
    if (!setpoint_in_range(stock_setpoint_kph_)) return reject("stock RVV setpoint outside 40..130 km/h");
    return true;
  }

  bool begin_takeover(uint32_t now) {
    if (!ready_for_takeover(now)) return false;
    takeover_active_ = true;
    applied_valid_ = requested_;
    applied_kph_ = stock_setpoint_kph_;
    last_step_ms_ = now;
    return true;
  }

  void end_takeover(const char *reason = "hardware bypass restored") {
    takeover_active_ = false;
    applied_valid_ = false;
    set_reason(reason);
  }

  bool tick(uint32_t now) {
    if (!takeover_active_ || !requested_) return true;
    if (!command_fresh(now)) return reject("RVV host command timeout");
    if (!stock_fresh(now)) return reject("stock 0x50E timeout");
    return true;
  }

  FrameAction build_from_stock(
      const uint8_t *stock, uint8_t len, uint8_t *output, uint32_t now) {
    if (len != 8U) return reject_action("0x50E DLC is not 8");
    memcpy(output, stock, 8);
    if (!requested_) return FrameAction::PassThrough;
    if (!takeover_active_) return reject_action("RVV takeover is not active");
    if (!tick(now)) return FrameAction::Reject;
    if (decode_checksum(stock) != checksum_for_setpoint(stock[6])) {
      return reject_action("stock 0x50E checksum invalid during takeover");
    }
    if (decode_mode(stock) != MODE_RVV || !decode_activation(stock)) {
      return reject_action("stock RVV mode or activation disappeared");
    }
    if (!setpoint_in_range(stock[6])) {
      return reject_action("stock RVV setpoint outside 40..130 km/h");
    }
    if (!applied_valid_) {
      applied_kph_ = stock[6];
      applied_valid_ = true;
      last_step_ms_ = now;
    }
    if (now - last_step_ms_ >= SETPOINT_STEP_INTERVAL_MS) {
      if (applied_kph_ < target_kph_) ++applied_kph_;
      else if (applied_kph_ > target_kph_) --applied_kph_;
      last_step_ms_ = now;
    }

    output[6] = applied_kph_;
    output[0] = static_cast<uint8_t>(
        (output[0] & 0xCFU) | (checksum_for_setpoint(applied_kph_) << 4));
    if (!replacement_is_bounded(stock, output)) {
      return reject_action("0x50E replacement changed forbidden payload bits");
    }
    if (decode_checksum(output) != checksum_for_setpoint(output[6])) {
      return reject_action("generated 0x50E checksum invalid");
    }
    ++replacement_count_;
    set_reason("");
    return memcmp(stock, output, 8) == 0
        ? FrameAction::PassThrough : FrameAction::Replaced;
  }

  static uint8_t checksum_for_setpoint(uint8_t setpoint) {
    const uint8_t high_parity = parity4(setpoint >> 4);
    const uint8_t low_parity = parity4(setpoint & 0x0FU);
    return static_cast<uint8_t>((high_parity << 1) | low_parity);
  }

  static uint8_t decode_checksum(const uint8_t *data) {
    return static_cast<uint8_t>((data[0] >> 4) & 0x3U);
  }

  static uint8_t decode_mode(const uint8_t *data) {
    return static_cast<uint8_t>((data[7] >> 5) & 0x3U);
  }

  static bool decode_activation(const uint8_t *data) {
    return (data[7] & 0x80U) != 0U;
  }

  static bool replacement_is_bounded(const uint8_t *stock, const uint8_t *replacement) {
    for (uint8_t i = 0; i < 8U; ++i) {
      if (i == 6U) continue;
      if (i == 0U) {
        if ((stock[i] & 0xCFU) != (replacement[i] & 0xCFU)) return false;
        continue;
      }
      if (stock[i] != replacement[i]) return false;
    }
    return true;
  }

  bool requested() const { return requested_; }
  bool takeover_active() const { return takeover_active_; }
  bool stock_valid() const { return stock_valid_; }
  bool stock_activation() const { return stock_activation_; }
  uint8_t target_kph() const { return target_kph_; }
  uint8_t applied_kph() const { return applied_kph_; }
  uint8_t stock_setpoint_kph() const { return stock_setpoint_kph_; }
  uint8_t stock_mode() const { return stock_mode_; }
  uint32_t checksum_failures() const { return checksum_failures_; }
  uint32_t replacement_count() const { return replacement_count_; }
  const char *reason() const { return reason_; }

 private:
  static uint8_t parity4(uint8_t value) {
    value &= 0x0FU;
    value ^= static_cast<uint8_t>(value >> 2);
    value ^= static_cast<uint8_t>(value >> 1);
    return value & 1U;
  }

  static bool setpoint_in_range(uint8_t setpoint) {
    return setpoint >= MIN_SETPOINT_KPH && setpoint <= MAX_SETPOINT_KPH;
  }

  bool command_fresh(uint32_t now) const {
    return command_seen_ && now - last_command_ms_ <= COMMAND_TIMEOUT_MS;
  }

  bool stock_fresh(uint32_t now) const {
    return stock_seen_ && stock_valid_ && now - last_stock_ms_ <= STOCK_TIMEOUT_MS;
  }

  bool reject(const char *reason) {
    set_reason(reason);
    return false;
  }

  FrameAction reject_action(const char *reason) {
    set_reason(reason);
    return FrameAction::Reject;
  }

  void set_reason(const char *reason) {
    if (reason == nullptr) reason = "";
    strncpy(reason_, reason, sizeof(reason_) - 1U);
    reason_[sizeof(reason_) - 1U] = '\0';
  }

  bool requested_ = false;
  bool takeover_active_ = false;
  bool command_seen_ = false;
  bool stock_seen_ = false;
  bool stock_valid_ = false;
  bool applied_valid_ = false;
  uint8_t target_kph_ = MIN_SETPOINT_KPH;
  uint8_t applied_kph_ = MIN_SETPOINT_KPH;
  uint8_t stock_setpoint_kph_ = 0xFFU;
  uint8_t stock_mode_ = 0;
  bool stock_activation_ = false;
  uint32_t last_command_ms_ = 0;
  uint32_t last_stock_ms_ = 0;
  uint32_t last_step_ms_ = 0;
  uint32_t checksum_failures_ = 0;
  uint32_t replacement_count_ = 0;
  char reason_[112] = "not requested";
};

}  // namespace psa_rvv_safety
