from tools.audit_t9_resume_rvv import Audit


BASE = 1_000_000_000


def sample(audit, ms, *, eps=1, driver=0, speed=85, **changes):
    now = BASE + ms * 1_000_000
    audit.frame(now, 0x495, bytes([0, 0, eps << 2, 0]), 0)
    audit.frame(now, 0x3F2, bytes.fromhex('000012000c000000'), 2)
    state = dict(valid=True, cruise_active=True, speed_kph=speed, driver_raw=driver,
                 steering_pressed=False, brake=False, gas=False, vehicle_ready=True)
    state.update(changes)
    audit.car(now, state)


def test_release_needs_continuous_300_ms_and_fresh_eps_release():
    audit = Audit()
    audit.cut(BASE)
    for ms in range(0, 401, 10):
        sample(audit, ms, eps=3)
    assert audit.cuts[0]['first_eligible_ns']['110'] is None
    for ms in range(410, 701, 10):
        sample(audit, ms)
    assert audit.cuts[0]['first_eligible_ns']['110'] is None
    sample(audit, 710)
    assert audit.cuts[0]['first_eligible_ns']['110'] == BASE + 710_000_000


def test_renewed_driver_effort_resets_stability_and_records_both_caps():
    audit = Audit()
    audit.cut(BASE)
    for ms in range(0, 301, 10):
        sample(audit, ms, speed=120, driver=6 if ms == 200 else 0)
    assert audit.cuts[0]['first_eligible_ns']['130'] is None
    for ms in range(310, 511, 10):
        sample(audit, ms, speed=120)
    assert audit.cuts[0]['first_eligible_ns']['130'] == BASE + 510_000_000
    assert audit.cuts[0]['first_eligible_ns']['110'] is None


def test_gap_or_stale_eps_is_not_stable_release():
    audit = Audit()
    audit.cut(BASE)
    sample(audit, 0)
    sample(audit, 500)
    assert audit.cuts[0]['first_eligible_ns']['110'] is None
    for ms in range(510, 801, 10):
        sample(audit, ms, eps=4)
    assert audit.cuts[0]['first_eligible_ns']['110'] is None
    audit.gap()
    sample(audit, 1000)
    assert audit.current_cut is None


def test_nonfinite_driver_signal_never_counts_as_release():
    audit = Audit()
    audit.cut(BASE)
    for ms in range(0, 501, 10):
        sample(audit, ms, driver=float('nan'))
    assert audit.cuts[0]['first_eligible_ns']['110'] is None


def test_brake_and_physical_cruise_off_are_distinct():
    audit = Audit()
    audit.cut(BASE)
    for ms in range(0, 501, 10):
        sample(audit, ms, brake=True)
    assert audit.cuts[0]['first_eligible_ns']['110'] is None
    now = BASE + 510_000_000
    audit.frame(now, 0x208, bytes([0, 0, 0, 0, 4, 0, 0, 0]), 0)
    audit.frame(now, 0x50E, bytes.fromhex('32000014224282af'), 2)
    sample(audit, 510, cruise_active=False, gas=True)
    assert audit.current_cut is not None
    assert audit.cuts[0]['physical_rvv_off_ns'] is None
    now = BASE + 520_000_000
    audit.frame(now, 0x208, bytes(8), 0)
    audit.frame(now, 0x50E, bytes.fromhex('020000141c42ff2f'), 2)
    sample(audit, 520, cruise_active=False)
    assert audit.current_cut is None
    assert audit.cuts[0]['physical_rvv_off_ns'] == now


def test_rvv_off_requires_fresh_physical_engine_transition():
    audit = Audit()
    active = bytes([0, 0, 0, 0, 8, 0, 0, 0])
    inactive = bytes(8)
    audit.frame(BASE, 0x208, active, 128)
    audit.frame(BASE + 10_000_000, 0x208, inactive, 0)
    assert audit.offs == []
    audit.frame(BASE + 20_000_000, 0x208, active, 0)
    audit.frame(BASE + 30_000_000, 0x208, inactive, 0)
    assert len(audit.offs) == 1
    audit.frame(BASE + 40_000_000, 0x208, active, 0)
    audit.frame(BASE + 500_000_000, 0x208, inactive, 0)
    assert len(audit.offs) == 1


def test_corrupt_setpoint_is_excluded_and_raw_switch_bits_preserved():
    audit = Audit()
    stock = bytes.fromhex('32000014224282af')
    audit.frame(BASE, 0x50E, stock, 2)
    assert audit.history[-1]['bit7']
    assert audit.history[-1]['setpoint_kph'] == 130
    bad = bytearray(stock)
    bad[6] ^= 1
    audit.frame(BASE + 10_000_000, 0x50E, bad, 2)
    assert audit.counts['invalid_50e_parity'] == 1
    assert audit.recent(0x50E, BASE + 20_000_000) is None
