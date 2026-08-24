from datetime import date
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.diagnostic.maintenance_history import (
    AttachmentTooLargeError,
    MaintenanceRecord,
    MaintenanceRecordInput,
    add_maintenance_document,
    create_maintenance_record,
    get_maintenance_record,
    list_maintenance_records,
    maintenance_document_file,
    update_maintenance_record,
)
from app.diagnostic.invoice_reader import InvoiceAnalysis, analyze_invoice_upload
from app.diagnostic.history import vehicle_storage_dir
from app.diagnostic.mileage_history import MileageEstimate, estimate_mileage


router = APIRouter(prefix="/api/maintenance", tags=["Maintenance history"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=exc.args[0])
    if isinstance(exc, AttachmentTooLargeError):
        return HTTPException(status_code=413, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/records", response_model=list[MaintenanceRecord])
def maintenance_records(vin: str | None = Query(default=None)) -> list[MaintenanceRecord]:
    try:
        return list_maintenance_records(vin)
    except (KeyError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/mileage-estimate", response_model=MileageEstimate)
def maintenance_mileage_estimate(
    vin: str = Query(min_length=17, max_length=17),
    performed_at: date = Query(),
) -> MileageEstimate:
    try:
        return estimate_mileage(vin, performed_at)
    except (KeyError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post("/invoice-draft", response_model=InvoiceAnalysis)
async def maintenance_invoice_draft(
    vin: str = Form(min_length=17, max_length=17),
    document: UploadFile = File(),
) -> InvoiceAnalysis:
    try:
        # Le VIN est validé ici même si l'analyse reste un brouillon non sauvegardé.
        vehicle_storage_dir(vin)
        return await analyze_invoice_upload(document)
    except (KeyError, ValueError, AttachmentTooLargeError) as exc:
        raise _http_error(exc) from exc


@router.get("/records/{record_id}", response_model=MaintenanceRecord)
def maintenance_record(
    record_id: str,
    vin: str = Query(min_length=17, max_length=17),
) -> MaintenanceRecord:
    try:
        return get_maintenance_record(vin, record_id)
    except (KeyError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/records",
    response_model=MaintenanceRecord,
    status_code=status.HTTP_201_CREATED,
)
def add_maintenance_record(entry: MaintenanceRecordInput) -> MaintenanceRecord:
    try:
        return create_maintenance_record(entry)
    except (KeyError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.put("/records/{record_id}", response_model=MaintenanceRecord)
def edit_maintenance_record(
    record_id: str,
    entry: MaintenanceRecordInput,
) -> MaintenanceRecord:
    try:
        return update_maintenance_record(record_id, entry)
    except (KeyError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.post(
    "/records/{record_id}/documents",
    response_model=MaintenanceRecord,
    status_code=status.HTTP_201_CREATED,
)
async def upload_maintenance_document(
    record_id: str,
    vin: str = Form(min_length=17, max_length=17),
    kind: Literal["invoice", "receipt", "photo", "warranty", "other"] = Form(default="invoice"),
    document: UploadFile = File(),
) -> MaintenanceRecord:
    try:
        return await add_maintenance_document(vin, record_id, document, kind)
    except (KeyError, ValueError) as exc:
        raise _http_error(exc) from exc


@router.get("/records/{record_id}/documents/{document_id}")
def download_maintenance_document(
    record_id: str,
    document_id: str,
    vin: str = Query(min_length=17, max_length=17),
) -> FileResponse:
    try:
        path, document = maintenance_document_file(vin, record_id, document_id)
    except (KeyError, ValueError) as exc:
        raise _http_error(exc) from exc
    return FileResponse(
        path,
        media_type=document.media_type,
        filename=document.original_name,
    )
