# Peugeot 308 T9 active-control overlay

This directory contains the reviewed source overlay used by the experimental
Peugeot 308 II T9 configuration based on openpilot commit
`6c928b70b499fae53c3791384e44886f4c352842`.

The default startup profile enables the separate lateral/RVV transport. The
EPS renewal cycle remains controlled by the persistent `PsaT9EpsCycleTest`
setting and defaults to OFF.

Current behavior:

- driver pause above ±15 raw units; ±15 itself remains accepted;
- lateral release for either turn signal, accepting either CAN order
  (`0x3F2` state 2 or `0x452` first), with zero commanded torque throughout;
- automatic lateral resume after 0.3 seconds of fresh, plausible lane data,
  followed by the bounded EPS handshake and torque ramp;
- RVV availability from 40 km/h and lateral availability from 67.1 km/h;
- T9 feedback gains reduced progressively above 90 km/h, with a progressive
  one-count CAN yaw-rate deadzone and about 0.5 raw friction compensation;
- requested curvature bounded by the experimental 0.82 m/s² / ±20 raw envelope,
  so the minimum commanded radius grows with the square of vehicle speed;
- RVV gap held at 2.0 seconds at every speed, plus the fixed 5 m offset
  (about 77 m at 130 km/h); closing-lead anticipation rises progressively
  from 4 seconds through 80 km/h to 6 seconds at 130 km/h, without a target
  deadline or brake control;
- optional cristianku-style EPS renewal at 12 seconds of confirmed activation,
  with earlier renewal from 3 seconds when current lateral acceleration is
  at most 0.30 m/s² and a curve of at least 0.50 m/s² is predicted within 5 s;
  the 12 s deadline does not require a straight-road permission or driver
  activity bit. Driver intervention, blinkers and hard faults retain priority.
  A takeover warning appears during the last 2 seconds before the deadline.
  The T9 handshake still requires the `3 -> 2 -> 0 -> 1/2 -> 3` EPS
  sequence within 3 seconds and a fresh acknowledgement before restoring torque.
- optional private home uploader preserved in the overlay; it remains inert
  without `/data/comma_home_upload.json` and only uploads completed files over
  Wi-Fi while the device is offroad.

`base-sha256.json` pins every source file that the overlay replaces. Build an
archive only against that exact base:

```sh
python3 openpilot/tools/build_t9_lateral_bundle.py \
  --base /path/to/openpilot \
  --output data/runtime/t9-lateral-package
```

The code behavior and limitations are described in
[`../../docs/ETAT_308_T9.md`](../../docs/ETAT_308_T9.md).

This is development code for one recorded vehicle configuration. Passing
software and USB tests does not validate active control on public roads.

On the comma, use **Settings → toggles → cycle EPS cristianku (essai)** while
offroad and disengaged. Changing ON/OFF saves `PsaT9EpsCycleTest` and restarts
the device so the controller and Panda use the same mode. OFF remains the
default; it selects the existing split-axes profile without periodic renewal.
ON requires firmware capability 9; older EPS-cycle firmware is rejected.

The reference is `cristianku/opendbc` commit
`78ce42a7d844620cae7cc921db002afd664e499a`, referenced by openpilot branch
`psa-torque-sunny-testing`. This port adopts its 3/12 s schedule and curve
thresholds while retaining the T9 handshake, zero-torque transition,
bounded timeout and torque ramp. Physical EPS activity remains a receive-only
diagnostic; the reference's synthetic wheel-holding indication is not emitted.
