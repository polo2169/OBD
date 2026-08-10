from app.diagnostic.dtc_status import apply_dtc_classification, summarize_dtcs
from app.diagnostic.history import (
    active_vehicle,
    finalize_scan,
    latest_report,
    list_reports,
    list_vehicles,
    report_html,
    save_identity,
    select_vehicle,
)
from app.models import (
    DtcReadResult,
    EcuScanResult,
    ScanReport,
    VehicleIdentityResult,
)


VIN = "VF3LJHNYWJS123456"


def _dtc(code: str, raw_hex: str, status: int) -> DtcReadResult:
    return apply_dtc_classification(DtcReadResult(
        code=code,
        raw_hex=raw_hex,
        failure_type=int(raw_hex[-2:], 16),
        status=status,
        status_hex=f"{status:02X}",
    ))


def _report(status: int, not_tested_status: int) -> ScanReport:
    ecu = EcuScanResult(
        key="abs_esp",
        name="ABS / ESP",
        detected=True,
        request_id=0x75D,
        response_id=0x65D,
        dtc_status_availability_mask=0xFF,
        dtcs=[
            _dtc("U1009", "D00987", status),
            _dtc("C0031", "403101", not_tested_status),
        ],
    )
    return ScanReport(
        vehicle_profile="peugeot_308_t9_2018",
        transport="virtual",
        readonly=True,
        ecus=[ecu],
        dtc_summary=summarize_dtcs([ecu]),
    )


def test_history_is_per_vin_and_compares_only_meaningful_fault_states():
    save_identity(VehicleIdentityResult(
        vehicle_profile="peugeot_308_t9_2018",
        manufacturer="Peugeot",
        detected_manufacturer="Peugeot",
        model="308 T9",
        year=2018,
        transport="virtual",
        found=True,
        vin=VIN,
        wmi="VF3",
    ))

    before = finalize_scan(_report(0x22, 0x40), VIN)
    after = finalize_scan(_report(0x20, 0x50), VIN)

    assert before.comparison is None
    assert after.comparison is not None
    assert [(item.code, item.before_state, item.after_state) for item in after.comparison.changed] == [
        ("U1009", "active", "historical")
    ]
    assert after.comparison.appeared == []
    assert after.comparison.resolved == []
    assert after.dtc_summary.active == 0
    assert after.dtc_summary.historical == 1
    assert after.dtc_summary.not_tested == 1
    assert latest_report(vin=VIN).scan_id == after.scan_id
    assert list_vehicles()[0]["vin"] == VIN
    assert len(list_reports(vin=VIN)) == 2
    assert "Tests non exécutés" in report_html(after)


def test_vehicle_selection_is_persisted_server_side():
    save_identity(VehicleIdentityResult(
        vehicle_profile="peugeot_308_t9_2018",
        manufacturer="Peugeot",
        detected_manufacturer="Peugeot",
        model="308 T9",
        year=2018,
        transport="virtual",
        found=True,
        vin=VIN,
        wmi="VF3",
    ))

    selected = select_vehicle(VIN)

    assert selected["vin"] == VIN
    assert active_vehicle()["vin"] == VIN
    assert list_vehicles()[0]["is_active"] is True
