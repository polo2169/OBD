#pragma once

#include <stdint.h>
#include <string.h>

// Conservative MADS-inspired engagement layer for the Peugeot 308 T9 bridge.
// It intentionally keeps lateral control independent from RVV/longitudinal
// control. Brake mode is fixed to Disengage for this first implementation:
// after a brake, stale safety input, heartbeat loss or speed-envelope exit, a
// false -> true host command is required before lateral control can arm again.
namespace psa_mads {

constexpr uint32_t DRIVER_RELEASE_HOLD_MS = 300;

enum class State : uint8_t {
  Disabled,
  Paused,
  Enabled,
  Overriding,
  Fault,
};

struct Inputs {
  bool heartbeat_fresh = false;
  bool physical_enable = false;
  bool lateral_inputs_fresh = false;
  bool speed_in_envelope = false;
  bool brake_pressed = false;
  bool driver_override = false;
};

class Controller {
 public:
  void reset() {
    state_ = State::Disabled;
    requested_ = false;
    rearm_required_ = false;
    fault_latched_ = false;
    driver_release_started_ = false;
    driver_release_started_ms_ = 0;
    set_reason("not requested");
  }

  void set_requested(bool requested) {
    if (!requested) {
      requested_ = false;
      rearm_required_ = false;
      driver_release_started_ = false;
      if (!fault_latched_) {
        state_ = State::Disabled;
        set_reason("not requested");
      }
      return;
    }

    // A repeated true command never clears a safety disengagement. The host
    // must acknowledge it with false before issuing a new rising edge.
    if (!requested_) {
      requested_ = true;
      rearm_required_ = false;
      driver_release_started_ = false;
      if (!fault_latched_) {
        state_ = State::Paused;
        set_reason("waiting for lateral preconditions");
      }
    }
  }

  void update(const Inputs &inputs, uint32_t now) {
    if (fault_latched_) {
      state_ = State::Fault;
      return;
    }
    if (!requested_) {
      state_ = State::Disabled;
      set_reason("not requested");
      return;
    }
    if (rearm_required_) {
      state_ = State::Disabled;
      return;
    }

    if (!inputs.physical_enable) {
      pause("physical MADS enable is open");
      return;
    }
    if (!inputs.heartbeat_fresh) {
      inhibit_if_engaged("host heartbeat lost");
      return;
    }
    if (!inputs.lateral_inputs_fresh) {
      inhibit_if_engaged("lateral safety inputs stale or missing");
      return;
    }
    if (!inputs.speed_in_envelope) {
      inhibit_if_engaged("speed outside lateral envelope");
      return;
    }
    if (inputs.brake_pressed) {
      inhibit_if_engaged("physical brake disengaged MADS");
      return;
    }

    if (inputs.driver_override) {
      state_ = State::Overriding;
      driver_release_started_ = false;
      set_reason("driver steering override");
      return;
    }

    if (state_ == State::Overriding) {
      if (!driver_release_started_) {
        driver_release_started_ = true;
        driver_release_started_ms_ = now;
        set_reason("waiting for stable driver release");
        return;
      }
      if (now - driver_release_started_ms_ < DRIVER_RELEASE_HOLD_MS) return;
    }

    state_ = State::Enabled;
    driver_release_started_ = false;
    set_reason("");
  }

  void force_disengage(const char *reason) {
    rearm_required_ = true;
    state_ = State::Disabled;
    driver_release_started_ = false;
    set_reason(reason);
  }

  void fault(const char *reason) {
    fault_latched_ = true;
    rearm_required_ = true;
    state_ = State::Fault;
    driver_release_started_ = false;
    set_reason(reason);
  }

  State state() const { return state_; }
  bool requested() const { return requested_; }
  bool rearm_required() const { return rearm_required_; }
  bool fault_latched() const { return fault_latched_; }
  bool engaged() const {
    return state_ == State::Enabled || state_ == State::Overriding;
  }
  bool torque_allowed() const { return state_ == State::Enabled; }
  const char *reason() const { return reason_; }

  static const char *state_name(State state) {
    switch (state) {
      case State::Disabled: return "disabled";
      case State::Paused: return "paused";
      case State::Enabled: return "enabled";
      case State::Overriding: return "overriding";
      case State::Fault: return "fault";
    }
    return "unknown";
  }

 private:
  void pause(const char *reason) {
    state_ = State::Paused;
    driver_release_started_ = false;
    set_reason(reason);
  }

  void inhibit_if_engaged(const char *reason) {
    if (engaged()) {
      force_disengage(reason);
    } else {
      pause(reason);
    }
  }

  void set_reason(const char *reason) {
    if (reason == nullptr) reason = "";
    strncpy(reason_, reason, sizeof(reason_) - 1U);
    reason_[sizeof(reason_) - 1U] = '\0';
  }

  State state_ = State::Disabled;
  bool requested_ = false;
  bool rearm_required_ = false;
  bool fault_latched_ = false;
  bool driver_release_started_ = false;
  uint32_t driver_release_started_ms_ = 0;
  char reason_[112] = "not requested";
};

}  // namespace psa_mads
