# Peugeot 308 T9 active-control overlay

This directory contains the reviewed source overlay used by the experimental
Peugeot 308 II T9 configuration based on openpilot commit
`6c928b70b499fae53c3791384e44886f4c352842`.

The default startup profile enables the separate lateral/RVV transport. The
EPS renewal cycle remains controlled by the persistent `PsaT9EpsCycleTest`
setting and defaults to OFF.

Current behavior:

- driver pause above ±15 raw units; ±15 itself remains accepted;
- lateral pause for either turn signal, with zero commanded torque;
- automatic lateral resume after 0.5 seconds of fresh, plausible lane data;
- RVV availability from 40 km/h and lateral availability from 67.1 km/h;
- RVV setpoint anticipation for a closing lead, without a two-second target
  deadline and without brake control;
- optional EPS deactivate/reactivate cycle after at least 12 seconds, only
  when its additional straight-road and fresh-feedback gates pass.

`base-sha256.json` pins every source file that the overlay replaces. Build an
archive only against that exact base:

```sh
python3 openpilot/tools/build_t9_lateral_bundle.py \
  --base /path/to/openpilot \
  --output data/runtime/t9-lateral-package
```

The public release notes, validation scope and dataset workflow are in
[`../../docs/COMMA_308_T9_RELEASE_2026-09-21.md`](../../docs/COMMA_308_T9_RELEASE_2026-09-21.md).

This is development code for one recorded vehicle configuration. Passing
software and USB tests does not validate active control on public roads.
