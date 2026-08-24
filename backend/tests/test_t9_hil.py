from tools.test_t9_hil import HilPortState, evaluate_passive, parse_hil_line, run_passive


def test_parse_hil_protocol() -> None:
    state = HilPortState("/dev/test")
    parse_hil_line(state, "HELLO,controller,hil-1.0")
    parse_hil_line(state, "STAT,20,40,12,0")
    parse_hil_line(state, "F,495,8,0102030405060708")

    assert state.role == "controller"
    assert state.firmware == "hil-1.0"
    assert state.last_stats == (20, 40, 12, 0)
    assert state.frame_ids == [0x495]
    assert state.malformed_lines == 0


def test_passive_evaluation_passes_for_working_loop() -> None:
    vehicle = HilPortState("/dev/vehicle", role="vehicle", firmware="hil-1.0")
    vehicle.stats = [(20, 0, 0, 0), (120, 0, 0, 0)]
    controller = HilPortState("/dev/controller", role="controller", firmware="hil-1.0")
    controller.stats = [(0, 20, 0, 0), (0, 120, 0, 0)]
    controller.frame_ids = [0x495]

    report = evaluate_passive([vehicle, controller])

    assert report["ok"] is True
    assert report["vehicle_tx_delta"] == 100
    assert report["controller_rx_delta"] == 100
    assert report["controller_frame_ids"] == ["0x495"]


def test_passive_evaluation_reports_open_can_loop() -> None:
    vehicle = HilPortState("/dev/vehicle", role="vehicle", firmware="hil-1.0")
    vehicle.stats = [(20, 0, 0, 0), (120, 0, 0, 0)]
    controller = HilPortState("/dev/controller", role="controller", firmware="hil-1.0")
    controller.stats = [(0, 0, 4_294_967_295, 0), (0, 0, 4_294_967_295, 0)]

    report = evaluate_passive([vehicle, controller])

    assert report["ok"] is False
    assert report["vehicle_tx_delta"] == 100
    assert report["controller_rx_delta"] == 0
    assert "aucun heartbeat reçu par le contrôleur" in report["findings"]


def test_run_passive_keeps_explicit_roles_when_hello_is_missed(monkeypatch) -> None:
    def fake_read(_port, _baud, _duration, state):
        state.stats = [(0, 0, 4_294_967_295, 0), (20, 0, 4_294_967_295, 0)]

    monkeypatch.setattr("tools.test_t9_hil._read_port", fake_read)

    report = run_passive("/dev/vehicle", "/dev/controller", 921_600, 0.01)

    assert [port["role"] for port in report["ports"]] == ["vehicle", "controller"]
    assert "firmware controller non détecté" not in report["findings"]
