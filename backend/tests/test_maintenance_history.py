from datetime import datetime, timezone
from pathlib import Path
import json

from fastapi.testclient import TestClient

from app.config import settings
from app.diagnostic.invoice_reader import parse_invoice_text
from app.main import app


client = TestClient(app)
VIN = "VF3LPHNYWJS141966"


def _create_vehicle() -> None:
    response = client.post(
        "/api/diagnostic/vehicles",
        json={"vehicle_profile": "peugeot_308_t9_2018", "vin": VIN},
    )
    assert response.status_code == 200, response.text


def _record_payload() -> dict:
    return {
        "vin": VIN,
        "vehicle_profile": "peugeot_308_t9_2018",
        "performed_at": "2026-08-21",
        "mileage_km": 105123,
        "mileage_source": "invoice",
        "title": "Remplacement caméra multifonction",
        "category": "Réparation",
        "workshop": "Atelier local",
        "invoice_number": "FAC-2026-0042",
        "invoice_total": 349.9,
        "currency": "eur",
        "labor_hours": 1.5,
        "notes": "Télécodage puis essai routier.",
        "parts": [{
            "name": "Caméra CVM",
            "manufacturer": "PSA",
            "part_number": "9808790480",
            "serial_number": "00010520",
            "removed_part_number": "9808790480",
            "removed_serial_number": "00010550",
            "quantity": 1,
            "unit_price": 299.9,
            "warranty_until": "2027-08-21",
        }],
    }


def test_create_list_update_and_archive_maintenance_record() -> None:
    _create_vehicle()
    created_response = client.post("/api/maintenance/records", json=_record_payload())
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    assert created["vin"] == VIN
    assert created["currency"] == "EUR"
    assert created["parts"][0]["serial_number"] == "00010520"
    assert created["parts"][0]["removed_serial_number"] == "00010550"
    assert created["revision"] == 1

    listed_response = client.get("/api/maintenance/records", params={"vin": VIN})
    assert listed_response.status_code == 200
    assert [item["id"] for item in listed_response.json()] == [created["id"]]

    updated_payload = _record_payload()
    updated_payload["notes"] = "Caméra validée après essai routier LKA."
    updated_response = client.put(
        f"/api/maintenance/records/{created['id']}",
        json=updated_payload,
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()
    assert updated["revision"] == 2
    assert updated["notes"].endswith("LKA.")

    revisions = list(Path(settings.diagnostic_history_dir).glob(
        f"*/{VIN}/maintenance/revisions/{created['id']}/revision-0001.json"
    ))
    assert len(revisions) == 1


def test_upload_and_download_invoice_with_hash() -> None:
    _create_vehicle()
    created = client.post("/api/maintenance/records", json=_record_payload()).json()
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    uploaded_response = client.post(
        f"/api/maintenance/records/{created['id']}/documents",
        data={"vin": VIN, "kind": "invoice"},
        files={"document": ("facture camera.pdf", pdf, "application/pdf")},
    )
    assert uploaded_response.status_code == 201, uploaded_response.text
    uploaded = uploaded_response.json()
    assert uploaded["revision"] == 2
    assert len(uploaded["documents"]) == 1
    document = uploaded["documents"][0]
    assert document["original_name"] == "facture camera.pdf"
    assert document["media_type"] == "application/pdf"
    assert len(document["sha256"]) == 64

    downloaded = client.get(document["download_url"], params={"vin": VIN})
    assert downloaded.status_code == 200
    assert downloaded.content == pdf
    assert downloaded.headers["content-type"].startswith("application/pdf")


def test_rejects_unknown_vehicle_and_disguised_attachment() -> None:
    unknown = _record_payload()
    unknown["vin"] = "VF3XXXXXXXXXXXXXX"
    response = client.post("/api/maintenance/records", json=unknown)
    assert response.status_code == 404

    _create_vehicle()
    created = client.post("/api/maintenance/records", json=_record_payload()).json()
    disguised = client.post(
        f"/api/maintenance/records/{created['id']}/documents",
        data={"vin": VIN, "kind": "invoice"},
        files={"document": ("fausse-facture.pdf", b"not a pdf", "application/pdf")},
    )
    assert disguised.status_code == 422
    assert "Formats acceptés" in disguised.json()["detail"]


def _write_replay_observation(stamp: str, observed_at: datetime, mileage_km: int) -> None:
    settings.session_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "session_id": f"learn-{stamp}-test",
        "vin": VIN,
        "start_timestamp_us": round(observed_at.timestamp() * 1_000_000),
        "duration_ms": 60_000,
        "points": [
            {"t_ms": 0, "odometer_km": float(mileage_km)},
            {"t_ms": 60_000, "odometer_km": float(mileage_km)},
        ],
    }
    (settings.session_dir / f"learn-{stamp}-test.replay.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_estimates_mileage_for_past_maintenance_date_from_can_history() -> None:
    _create_vehicle()
    _write_replay_observation(
        "20260811T120000Z",
        datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
        104_938,
    )
    _write_replay_observation(
        "20260822T120000Z",
        datetime(2026, 8, 22, 12, tzinfo=timezone.utc),
        105_246,
    )

    response = client.get(
        "/api/maintenance/mileage-estimate",
        params={"vin": VIN, "performed_at": "2026-08-21"},
    )
    assert response.status_code == 200, response.text
    estimate = response.json()
    assert estimate["method"] == "interpolated"
    assert estimate["confidence"] == "high"
    assert estimate["is_estimate"] is True
    assert 105_200 <= estimate["mileage_km"] <= 105_230
    assert len(estimate["observations"]) == 2


def test_invoice_text_prefills_editable_camera_fields() -> None:
    analysis = parse_invoice_text("""
GARAGE DES LIONS
FACTURE N° FAC-2026-0042
Date de facture : 21/08/2026
Kilométrage : 105 123 km
Remplacement caméra multifonction
Caméra CVM Réf. 9808790480 N° de série 00010520 299,90 €
TOTAL TTC 349,90 €
""")
    assert analysis.performed_at.isoformat() == "2026-08-21"
    assert analysis.mileage_km == 105_123
    assert analysis.invoice_number == "FAC-2026-0042"
    assert analysis.invoice_total == 349.9
    assert analysis.parts[0].name == "Caméra CVM"
    assert analysis.parts[0].part_number == "9808790480"
    assert analysis.parts[0].serial_number == "00010520"


def test_invoice_draft_endpoint_does_not_save_before_confirmation(monkeypatch) -> None:
    _create_vehicle()
    extracted = """GARAGE TEST
FACTURE N° F-99
Date : 21/08/2026
Caméra Réf. 9808790480 N° de série 00010520
TOTAL TTC 300,00 €
"""
    monkeypatch.setattr(
        "app.diagnostic.invoice_reader._extract_text",
        lambda _path, _media_type: (extracted, False),
    )
    response = client.post(
        "/api/maintenance/invoice-draft",
        data={"vin": VIN},
        files={"document": ("facture.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["parts"][0]["serial_number"] == "00010520"
    assert client.get("/api/maintenance/records", params={"vin": VIN}).json() == []
