from datetime import datetime, timezone
from pathlib import Path
import json

import cv2
import numpy as np
import pymupdf
from fastapi.testclient import TestClient

from app.config import settings
from app.diagnostic.invoice_reader import parse_invoice_text
from app.main import app
from app.maintenance.document_normalizer import _orientation_score, _scanline_document_quad


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
    assert downloaded.headers["content-disposition"].startswith("inline;")


def test_photo_is_cropped_and_exposed_as_normalized_pdf(monkeypatch) -> None:
    _create_vehicle()
    created = client.post("/api/maintenance/records", json=_record_payload()).json()
    image = np.full((900, 700, 3), 25, dtype=np.uint8)
    cv2.rectangle(image, (80, 45), (635, 850), (245, 245, 245), thickness=-1)
    cv2.putText(image, "FACTURE TEST", (150, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 3)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    monkeypatch.setattr("app.maintenance.document_normalizer.detect_orientation", lambda _image: 0)

    response = client.post(
        f"/api/maintenance/records/{created['id']}/documents",
        data={"vin": VIN, "kind": "invoice"},
        files={"document": ("photo facture.jpg", encoded.tobytes(), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    document = response.json()["documents"][0]
    assert document["normalized"] is True
    assert document["media_type"] == "application/pdf"
    assert document["page_count"] == 1
    assert document["source_names"] == ["photo facture.jpg"]
    downloaded = client.get(document["download_url"], params={"vin": VIN})
    assert downloaded.content.startswith(b"%PDF-")
    with pymupdf.open(stream=downloaded.content, filetype="pdf") as normalized:
        assert normalized.page_count == 1


def test_orientation_score_accepts_rapidocr_numpy_arrays() -> None:
    result = type("OCRResult", (), {
        "boxes": np.array([[[0, 0], [100, 0], [100, 20], [0, 20]]], dtype=float),
        "txts": np.array(["FACTURE"]),
        "scores": np.array([0.9]),
    })()

    assert _orientation_score(result) > 0


def test_scanline_crop_recovers_page_with_hidden_corner_and_light_table() -> None:
    image = np.full((1_000, 750, 3), 25, dtype=np.uint8)
    page = np.array([[125, 195], [620, 180], [655, 950], [90, 965]], dtype=np.int32)
    cv2.fillConvexPoly(image, page, (240, 240, 240))
    cv2.putText(image, "FACTURE", (190, 330), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (25, 25, 25), 3)
    for y in range(390, 850, 55):
        cv2.line(image, (160, y), (575, y - 8), (45, 45, 45), 3)

    # A second sheet hides the upper-left corner and the light worktop touches
    # the lower edge, so the main page no longer has one closed outer contour.
    overlay = np.array([[0, 0], [350, 0], [270, 260], [0, 360]], dtype=np.int32)
    cv2.fillConvexPoly(image, overlay, (245, 245, 245))
    cv2.rectangle(image, (0, 975), (749, 999), (235, 235, 235), thickness=-1)

    points = _scanline_document_quad(image)

    assert points is not None
    assert cv2.contourArea(points.astype(np.float32)) > 0.40 * image.shape[0] * image.shape[1]
    assert points[:, 0].min() > 40
    assert points[:, 0].max() < 700
    assert points[:, 1].min() < 260
    assert points[:, 1].max() > 900


def test_later_repair_automatically_completes_matching_recommendation() -> None:
    _create_vehicle()
    inspection = _record_payload()
    inspection.update({
        "event_type": "inspection",
        "performed_at": "2024-02-15",
        "mileage_km": 63_606,
        "title": "Contrôle des freins arrière",
        "category": "Contrôle",
        "parts": [],
        "recommendations": [{
            "title": "Plaquettes arrière à prévoir dans 7000 km",
            "status": "open",
            "source": "document",
            "recommended_at_km": 63_606,
            "due_mileage_km": 70_606,
            "confidence": "high",
        }],
    })
    source = client.post("/api/maintenance/records", json=inspection).json()
    repair = _record_payload()
    repair.update({
        "event_type": "repair",
        "performed_at": "2025-02-28",
        "mileage_km": 78_206,
        "title": "Remplacement des plaquettes arrière",
        "parts": [{
            "name": "Jeu de plaquettes de frein arrière",
            "usage": "installed",
            "quantity": 1,
        }],
    })
    completion = client.post("/api/maintenance/records", json=repair).json()
    updated_source = client.get(
        f"/api/maintenance/records/{source['id']}",
        params={"vin": VIN},
    ).json()
    recommendation = updated_source["recommendations"][0]
    assert recommendation["status"] == "completed"
    assert recommendation["auto_managed"] is True
    assert recommendation["completed_by_record_id"] == completion["id"]
    assert "Clôturée automatiquement" in recommendation["completion_reason"]


def test_later_front_brake_job_auto_completes_disc_recommendation() -> None:
    _create_vehicle()
    inspection = _record_payload()
    inspection.update({
        "event_type": "technical_inspection",
        "performed_at": "2026-06-09",
        "mileage_km": 102_906,
        "title": "Contrôle technique",
        "parts": [],
        "recommendations": [{
            "title": "Disques de frein avant légèrement usés : AVD, AVG",
            "source": "document",
        }],
    })
    source = client.post("/api/maintenance/records", json=inspection).json()
    repair = _record_payload()
    repair.update({
        "event_type": "repair",
        "performed_at": "2026-08-22",
        "mileage_km": 105_248,
        "title": "Remplacement des disques et plaquettes avant",
        "parts": [{
            "name": "Disque av",
            "system_code": "brakes",
            "usage": "installed",
            "quantity": 1,
        }],
    })
    completion = client.post("/api/maintenance/records", json=repair).json()

    recommendation = client.get(
        f"/api/maintenance/records/{source['id']}",
        params={"vin": VIN},
    ).json()["recommendations"][0]
    assert recommendation["status"] == "completed"
    assert recommendation["auto_managed"] is True
    assert recommendation["completed_by_record_id"] == completion["id"]


def test_elapsed_brake_bedding_advice_is_completed_automatically() -> None:
    _create_vehicle()
    maintenance = _record_payload()
    maintenance.update({
        "performed_at": "2025-02-28",
        "mileage_km": 78_206,
        "title": "Remplacement des plaquettes arrière",
        "recommendations": [{
            "title": "Observer une période de rodage des freins pendant 500 km",
            "source": "document",
            "recommended_at_km": 78_206,
            "follow_up_after_km": 500,
            "due_mileage_km": 78_706,
        }],
    })
    source = client.post("/api/maintenance/records", json=maintenance).json()
    later = _record_payload()
    later.update({
        "performed_at": "2025-07-07",
        "mileage_km": 85_241,
        "title": "Montage des pneumatiques",
    })
    client.post("/api/maintenance/records", json=later)

    recommendation = client.get(
        f"/api/maintenance/records/{source['id']}", params={"vin": VIN}
    ).json()["recommendations"][0]
    assert recommendation["status"] == "completed"
    assert recommendation["auto_managed"] is True
    assert "seuil de 78 706 km dépassé" in recommendation["completion_reason"]


def test_recommendation_can_be_completed_and_reopened_manually() -> None:
    _create_vehicle()
    payload = _record_payload()
    payload["recommendations"] = [{
        "title": "Remplacer les pneus arrière",
        "source": "manual",
        "recommended_at_km": 105_000,
    }]
    source = client.post("/api/maintenance/records", json=payload).json()
    url = f"/api/maintenance/records/{source['id']}/recommendations/0"

    completed = client.patch(
        url,
        params={"vin": VIN},
        json={"status": "completed", "note": "Pneus remplacés à domicile."},
    )
    assert completed.status_code == 200, completed.text
    recommendation = completed.json()["recommendations"][0]
    assert recommendation["status"] == "completed"
    assert recommendation["auto_managed"] is False
    assert recommendation["completion_reason"] == "Pneus remplacés à domicile."

    reopened = client.patch(
        url,
        params={"vin": VIN},
        json={"status": "open"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["recommendations"][0]["status"] == "open"


def test_forecast_projects_recurring_parts_dates_and_costs_to_500000_km() -> None:
    _create_vehicle()
    rear_brakes = _record_payload()
    rear_brakes.update({
        "event_type": "repair",
        "performed_at": "2025-02-28",
        "mileage_km": 78_206,
        "title": "Remplacement des plaquettes arrière",
        "parts": [{
            "name": "Plaquettes de frein arrière",
            "usage": "installed",
            "quantity": 1,
        }],
    })
    client.post("/api/maintenance/records", json=rear_brakes)
    current = _record_payload()
    current.update({
        "event_type": "repair",
        "performed_at": "2026-08-22",
        "mileage_km": 105_248,
        "title": "Remplacement des disques et plaquettes avant",
        "recommendations": [{
            "title": "Remplacer les deux pneus arrière",
            "source": "manual",
            "recommended_at_km": 105_248,
            "due_mileage_km": 105_248,
        }],
    })
    client.post("/api/maintenance/records", json=current)

    response = client.get("/api/maintenance/forecast", params={
        "vin": VIN,
        "horizon_mileage_km": 500_000,
        "annual_mileage_km": 18_000,
    })
    assert response.status_code == 200, response.text
    forecast = response.json()
    assert forecast["current_mileage_km"] == 105_248
    assert forecast["annual_mileage_km"] == 18_000
    rear_pad_events = [
        item for item in forecast["items"]
        if item.get("component_code") == "brakes.pads.rear"
    ]
    assert rear_pad_events[0]["mileage_km"] == 138_206
    assert rear_pad_events[0]["estimated_cost_min"] > 0
    assert rear_pad_events[-1]["mileage_km"] <= 500_000
    rear_tires = next(
        item for item in forecast["items"]
        if item["kind"] == "recommendation" and "pneus arrière" in item["title"]
    )
    assert rear_tires["status"] == "due"
    assert rear_tires["mileage_km"] == 105_248
    assert rear_tires["estimated_cost_max"] == 500


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


def test_parts_supplier_invoice_keeps_purchase_date_without_inventing_installation() -> None:
    analysis = parse_invoice_text("""
OSCARO
Facture : VFT0060166688
Date : 18/08/2026
Disques de frein Réf. 0-986-479-C33 63,82 €
Total TTC 76,58 €
""")
    assert analysis.purchased_at.isoformat() == "2026-08-18"
    assert analysis.performed_at is None
    assert analysis.performed_at_source is None
    assert analysis.provider_candidate is not None
    assert analysis.provider_candidate.kind == "parts_supplier"
    assert any("date de pose" in warning for warning in analysis.warnings)


def test_provider_links_draft_lines_recommendations_and_import_idempotency() -> None:
    _create_vehicle()
    provider_response = client.post("/api/maintenance/providers", json={
        "kind": "garage",
        "legal_name": "Garage des Lions SAS",
        "display_name": "Garage des Lions",
        "siret": "123 456 789 00012",
        "address_line1": "1 rue de l'Atelier",
        "postal_code": "31000",
        "city": "Toulouse",
        "country_code": "FR",
        "phone": "05 00 00 00 00",
        "aliases": ["Garage des Lions"],
        "verified_by_user": True,
    })
    assert provider_response.status_code == 201, provider_response.text
    provider = provider_response.json()
    assert provider["siret"] == "12345678900012"

    payload = {
        "vin": VIN,
        "vehicle_profile": "peugeot_308_t9_2018",
        "record_status": "draft",
        "source_system": "test_import",
        "source_import_key": "test_import:invoice-42",
        "event_type": "diagnostic",
        "purchased_at": "2026-08-18",
        "mileage_km": 105_000,
        "mileage_source": "invoice",
        "title": "Diagnostic train avant",
        "category": "Diagnostic",
        "performed_by": "unknown",
        "seller_provider_id": provider["id"],
        "invoice_issuer_provider_id": provider["id"],
        "invoice_number": "F-42",
        "document_client_name": "Thomas Mireille",
        "document_page_count": 2,
        "document_pagination_status": "complete",
        "invoice_subtotal": 100,
        "invoice_tax": 20,
        "invoice_total": 120,
        "currency": "EUR",
        "parts": [],
        "cost_lines": [{
            "line_type": "service",
            "description": "Diagnostic train avant",
            "quantity": 1,
            "amount_excl_tax": 100,
            "confidence": "high",
            "source_text": ["Diagnostic train avant 100,00"],
        }],
        "recommendations": [{
            "title": "Contrôler les rotules après 500 km",
            "status": "open",
            "source": "diagnostic",
            "recommended_at_km": 105000,
            "follow_up_after_km": 500,
            "confidence": "high",
        }],
    }
    first = client.post("/api/maintenance/records", json=payload)
    second = client.post("/api/maintenance/records", json=payload)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["performed_at"] is None
    assert first.json()["document_client_name"] == "Thomas Mireille"
    assert first.json()["recommendations"][0]["follow_up_after_km"] == 500
    assert len(client.get("/api/maintenance/records", params={"vin": VIN}).json()) == 1

    duplicate_provider = client.post("/api/maintenance/providers", json={
        "kind": "garage", "legal_name": "Autre nom", "siret": "12345678900012",
        "country_code": "FR", "aliases": [], "verified_by_user": False,
    })
    assert duplicate_provider.status_code == 422
