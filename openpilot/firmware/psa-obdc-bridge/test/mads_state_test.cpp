#include <assert.h>
#include <string.h>

#include "psa_mads.hpp"

namespace {

psa_mads::Inputs ready_inputs() {
  psa_mads::Inputs inputs;
  inputs.heartbeat_fresh = true;
  inputs.physical_enable = true;
  inputs.lateral_inputs_fresh = true;
  inputs.speed_in_envelope = true;
  return inputs;
}

}  // namespace

int main() {
  using psa_mads::Controller;
  using psa_mads::State;

  Controller mads;
  mads.reset();
  auto inputs = ready_inputs();

  mads.set_requested(true);
  mads.update(inputs, 100);
  assert(mads.state() == State::Enabled);
  assert(mads.engaged());
  assert(mads.torque_allowed());

  // Driver steering is a temporary override, not a full disengagement. Torque
  // resumes only after the release has stayed stable for 300 ms.
  inputs.driver_override = true;
  mads.update(inputs, 120);
  assert(mads.state() == State::Overriding);
  assert(mads.engaged());
  assert(!mads.torque_allowed());
  inputs.driver_override = false;
  mads.update(inputs, 150);
  mads.update(inputs, 449);
  assert(mads.state() == State::Overriding);
  mads.update(inputs, 450);
  assert(mads.state() == State::Enabled);

  // Conservative brake policy: release does not silently resume. A repeated
  // true command cannot clear the latch; false -> true is mandatory.
  inputs.brake_pressed = true;
  mads.update(inputs, 500);
  assert(mads.state() == State::Disabled);
  assert(mads.rearm_required());
  inputs.brake_pressed = false;
  mads.set_requested(true);
  mads.update(inputs, 600);
  assert(mads.state() == State::Disabled);
  mads.set_requested(false);
  mads.set_requested(true);
  mads.update(inputs, 610);
  assert(mads.state() == State::Enabled);

  // Leaving the speed envelope while engaged has the same explicit-rearm
  // behavior, whereas opening and reclosing the physical gate is itself an
  // explicit driver action and may resume without a host toggle.
  inputs.speed_in_envelope = false;
  mads.update(inputs, 700);
  assert(mads.rearm_required());
  inputs.speed_in_envelope = true;
  mads.set_requested(false);
  mads.set_requested(true);
  mads.update(inputs, 710);
  assert(mads.state() == State::Enabled);
  inputs.physical_enable = false;
  mads.update(inputs, 720);
  assert(mads.state() == State::Paused);
  inputs.physical_enable = true;
  mads.update(inputs, 800);
  assert(mads.state() == State::Enabled);

  // Heartbeat loss while engaged is latched and a firmware fault cannot be
  // cleared by host commands.
  inputs.heartbeat_fresh = false;
  mads.update(inputs, 900);
  assert(mads.state() == State::Disabled);
  assert(mads.rearm_required());
  inputs.heartbeat_fresh = true;
  mads.set_requested(false);
  mads.set_requested(true);
  mads.update(inputs, 910);
  assert(mads.state() == State::Enabled);
  mads.fault("test fault");
  mads.set_requested(false);
  mads.set_requested(true);
  mads.update(inputs, 1000);
  assert(mads.state() == State::Fault);
  assert(strcmp(mads.reason(), "test fault") == 0);

  return 0;
}
