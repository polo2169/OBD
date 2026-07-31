from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.learn.analyzer import analyze_behavior, analyze_session, list_sessions
from app.learn.capture import capture_manager
from app.learn.exporter import export_proposals
from app.learn.models import (
    AnalysisReport,
    BehavioralAnalysisReport,
    CaptureMarker,
    CaptureStart,
    CaptureStatus,
    CorrelationOptions,
    DiscoverySessionSummary,
    OpendbcCatalog,
    UdsCandidate,
)
from app.learn.opendbc import get_opendbc_decoder

router = APIRouter(prefix="/api/learn", tags=["OpenDiag Learn"])


@router.post("/capture/start", response_model=CaptureStatus)
def start_capture(capture: CaptureStart | None = None) -> CaptureStatus:
    capture = capture or CaptureStart()
    return capture_manager.start(capture.name, capture.note)


@router.post("/capture/marker", response_model=CaptureStatus)
def add_marker(marker: CaptureMarker) -> CaptureStatus:
    try:
        return capture_manager.marker(marker.name, marker.note)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/capture/stop", response_model=CaptureStatus)
def stop_capture() -> CaptureStatus:
    return capture_manager.stop()


@router.get("/capture/status", response_model=CaptureStatus)
def capture_status() -> CaptureStatus:
    return capture_manager.status()


@router.get("/sessions", response_model=list[DiscoverySessionSummary])
def sessions() -> list[DiscoverySessionSummary]:
    return list_sessions()


@router.get("/opendbc/catalog", response_model=OpendbcCatalog)
def opendbc_catalog() -> OpendbcCatalog:
    return get_opendbc_decoder().catalog()


@router.post("/analyze/{session_id}", response_model=AnalysisReport)
def analyze(session_id: str) -> AnalysisReport:
    try:
        return analyze_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/proposals/{session_id}", response_model=list[UdsCandidate])
def proposals(session_id: str) -> list[UdsCandidate]:
    try:
        return analyze_session(session_id).candidates
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/correlate/{session_id}", response_model=BehavioralAnalysisReport)
def correlate(
    session_id: str,
    options: CorrelationOptions | None = None,
) -> BehavioralAnalysisReport:
    try:
        report = analyze_behavior(session_id, options)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = settings.session_dir / f"{session_id}.correlations.json"
    report.analysis_path = str(path)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


@router.get("/correlations/{session_id}", response_model=BehavioralAnalysisReport)
def saved_correlations(session_id: str) -> BehavioralAnalysisReport:
    if not session_id.startswith("learn-") or session_id != Path(session_id).name:
        raise HTTPException(status_code=404, detail="Identifiant de session invalide.")
    path = settings.session_dir / f"{session_id}.correlations.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Analyse post-traitement introuvable.")
    try:
        return BehavioralAnalysisReport.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Analyse illisible : {exc}") from exc


@router.post("/export/{session_id}")
def export(session_id: str):
    try:
        path = export_proposals(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, filename=path.name, media_type="application/x-yaml")
