from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
import json
import math

from app.config import settings
from app.learn.isotp import (
    is_negative_response,
    is_positive_response,
    parse_isotp_frame,
    uds_service,
)
from app.learn.models import (
    AnalysisReport,
    BehavioralAnalysisReport,
    ByteProfile,
    CanIdProfile,
    CorrelationOptions,
    DiscoverySessionSummary,
    MarkerCorrelation,
    SignalCandidate,
    UdsCandidate,
)
from app.learn.opendbc import OpendbcDecoder, get_opendbc_decoder


READ_ONLY_SERVICES = {0x10, 0x19, 0x22, 0x3E}
SENSITIVE_SERVICES = {0x11, 0x14, 0x27, 0x2E, 0x2F, 0x31, 0x34, 0x36, 0x37}


def load_events(session_id: str) -> list[dict]:
    if Path(session_id).name != session_id or not session_id.startswith("learn-"):
        raise FileNotFoundError(f"Identifiant de session invalide : {session_id}")
    path = settings.session_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Session introuvable : {session_id}")
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def list_sessions() -> list[DiscoverySessionSummary]:
    settings.session_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[DiscoverySessionSummary] = []
    for path in sorted(settings.session_dir.glob("learn-*.jsonl"), reverse=True):
        name = path.stem
        source = ""
        started_at_us: int | None = None
        timestamps: list[int] = []
        markers: list[str] = []
        frame_count = 0
        error: str | None = None
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                event = json.loads(line)
                timestamp = int(event.get("timestamp_us", 0) or 0)
                # Les anciennes captures mélangeaient parfois temps ESP32 et temps hôte.
                if timestamp > 1_000_000_000_000:
                    timestamps.append(timestamp)
                if event.get("type") == "meta":
                    name = str(event.get("name") or name)
                    source = str(event.get("source") or source)
                    if started_at_us is None and timestamp:
                        started_at_us = timestamp
                    if event.get("event") == "capture_error":
                        error = str(event.get("error") or "Erreur de capture")
                elif event.get("type") == "can_frame":
                    frame_count += 1
                elif event.get("type") == "marker":
                    marker = str(event.get("name") or "").strip()
                    if marker:
                        markers.append(marker)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            error = f"Session illisible : {exc}"

        duration_ms = 0.0
        if len(timestamps) >= 2:
            duration_ms = max(0.0, (max(timestamps) - min(timestamps)) / 1000)
        summaries.append(DiscoverySessionSummary(
            session_id=path.stem,
            name=name,
            source=source,
            started_at_us=started_at_us,
            duration_ms=round(duration_ms, 1),
            frame_count=frame_count,
            marker_count=len(markers),
            markers=list(dict.fromkeys(markers)),
            size_bytes=path.stat().st_size,
            analyzed=(settings.session_dir / f"{path.stem}.correlations.json").exists(),
            error=error,
        ))
    return summaries


def _frame_events(events: list[dict]) -> list[dict]:
    frames: list[dict] = []
    for event in events:
        if event.get("type") != "can_frame":
            continue
        try:
            data = bytes.fromhex(str(event.get("data_hex", "")))
            timestamp_us = int(event["timestamp_us"])
            arbitration_id = int(event["arbitration_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(data) > 8 or arbitration_id < 0 or arbitration_id > 0x1FFFFFFF:
            continue
        frames.append({
            "timestamp_us": timestamp_us,
            "id": arbitration_id,
            "extended": bool(event.get("extended", arbitration_id > 0x7FF)),
            "data": data,
        })
    frames.sort(key=lambda item: item["timestamp_us"])
    return frames


def _decorate_with_opendbc(
    frames: list[dict],
    decoder: OpendbcDecoder,
):
    observed_messages: set[str] = set()
    decoded_frame_count = 0
    decode_error_count = 0
    for frame in frames:
        message, values, error = decoder.decode_frame(
            frame["id"],
            frame["extended"],
            frame["data"],
        )
        if message is None:
            continue
        observed_messages.add(message.name)
        frame["opendbc_message"] = message.name
        frame["opendbc_signal_names"] = [signal.name for signal in message.signals]
        if error is not None:
            decode_error_count += 1
            frame["opendbc_error"] = error
            continue
        frame["opendbc_values"] = values or {}
        decoded_frame_count += 1
    return decoder.source_info(
        observed_messages=observed_messages,
        decoded_frame_count=decoded_frame_count,
        decode_error_count=decode_error_count,
    )


def _entropy(values: list[int]) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    total = len(values)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _inventory(frames: list[dict]) -> list[CanIdProfile]:
    grouped: dict[tuple[int, bool], list[dict]] = defaultdict(list)
    for frame in frames:
        grouped[(frame["id"], frame["extended"])].append(frame)

    profiles: list[CanIdProfile] = []
    for (arbitration_id, extended), items in grouped.items():
        first = items[0]["timestamp_us"]
        last = items[-1]["timestamp_us"]
        elapsed_s = max(0.0, (last - first) / 1_000_000)
        frequency = (len(items) - 1) / elapsed_s if elapsed_s > 0 and len(items) > 1 else 0.0
        max_length = max((len(item["data"]) for item in items), default=0)
        byte_profiles: list[ByteProfile] = []
        changing_bytes: list[int] = []
        for index in range(max_length):
            values = [item["data"][index] for item in items if len(item["data"]) > index]
            if not values:
                continue
            toggles = sum(current != previous for previous, current in zip(values, values[1:]))
            distinct = len(set(values))
            if distinct > 1:
                changing_bytes.append(index)
            byte_profiles.append(ByteProfile(
                index=index,
                distinct_values=distinct,
                minimum=min(values),
                maximum=max(values),
                toggle_count=toggles,
                entropy=round(_entropy(values), 3),
            ))
        dlcs = Counter(str(len(item["data"])) for item in items)
        profiles.append(CanIdProfile(
            arbitration_id=arbitration_id,
            extended=extended,
            frame_count=len(items),
            frequency_hz=round(frequency, 2),
            dlc_counts=dict(sorted(dlcs.items())),
            changing_bytes=changing_bytes,
            byte_profiles=byte_profiles,
            opendbc_message=next(
                (item.get("opendbc_message") for item in items if item.get("opendbc_message")),
                None,
            ),
            opendbc_signals=next(
                (
                    item.get("opendbc_signal_names", [])
                    for item in items
                    if item.get("opendbc_signal_names")
                ),
                [],
            ),
        ))
    return sorted(profiles, key=lambda item: item.frame_count, reverse=True)


def _confidence(score: float) -> str:
    if score >= 0.82:
        return "forte"
    if score >= 0.68:
        return "moyenne"
    return "faible"


def _total_variation(before: list[Any], after: list[Any]) -> float:
    before_counts = Counter(before)
    after_counts = Counter(after)
    values = set(before_counts) | set(after_counts)
    return 0.5 * sum(
        abs(before_counts[value] / len(before) - after_counts[value] / len(after))
        for value in values
    )


def _format_signal_value(value: Any, unit: str | None) -> str:
    if isinstance(value, bool):
        text = "1" if value else "0"
    elif isinstance(value, float):
        text = f"{value:.4g}"
    else:
        text = str(value)
    return f"{text} {unit}".strip() if unit else text


def _opendbc_candidates(
    arbitration_id: int,
    extended: bool,
    before_frames: list[dict],
    after_frames: list[dict],
    marker_occurrences: int,
    options: CorrelationOptions,
    source_url: str,
) -> list[SignalCandidate]:
    before_by_signal: dict[str, list[Any]] = defaultdict(list)
    after_by_signal: dict[str, list[Any]] = defaultdict(list)
    signal_metadata: dict[str, tuple[str, str | None]] = {}

    for target, items in ((before_by_signal, before_frames), (after_by_signal, after_frames)):
        for frame in items:
            message_name = frame.get("opendbc_message")
            for signal_name, decoded in frame.get("opendbc_values", {}).items():
                value = decoded.get("value")
                if value is None or not isinstance(value, (str, int, float, bool)):
                    continue
                target[signal_name].append(value)
                signal_metadata[signal_name] = (message_name, decoded.get("unit"))

    candidates: list[SignalCandidate] = []
    repetition_bonus = min(0.08, max(0, marker_occurrences - 1) * 0.025)
    for signal_name in set(before_by_signal) & set(after_by_signal):
        before = before_by_signal[signal_name]
        after = after_by_signal[signal_name]
        if len(before) < options.min_samples or len(after) < options.min_samples:
            continue

        message_name, unit = signal_metadata[signal_name]
        distinct = set(before) | set(after)
        before_value: Any
        after_value: Any
        stability = 0.0

        # États, compteurs et petits enums : comparaison des distributions.
        if len(distinct) <= 16 or not all(
            isinstance(value, (int, float, bool)) for value in distinct
        ):
            before_value, before_count = Counter(before).most_common(1)[0]
            after_value, after_count = Counter(after).most_common(1)[0]
            if before_value == after_value:
                continue
            effect = _total_variation(before, after)
            stability = (
                before_count / len(before) + after_count / len(after)
            ) / 2
            if effect < 0.38:
                continue
        else:
            numeric_before = [float(value) for value in before]
            numeric_after = [float(value) for value in after]
            before_value = median(numeric_before)
            after_value = median(numeric_after)
            delta = abs(after_value - before_value)
            before_mad = median(abs(value - before_value) for value in numeric_before)
            after_mad = median(abs(value - after_value) for value in numeric_after)
            effect = delta / max(delta + before_mad + after_mad, 1e-9)
            stability = 1 - min(1.0, (before_mad + after_mad) / max(delta, 1e-9))
            if delta <= 0 or effect < 0.55:
                continue

        score = min(0.98, 0.66 * effect + 0.26 * stability + repetition_bonus)
        if score < 0.60:
            continue
        candidates.append(SignalCandidate(
            arbitration_id=arbitration_id,
            extended=extended,
            kind="dbc_signal",
            before_value=_format_signal_value(before_value, unit),
            after_value=_format_signal_value(after_value, unit),
            before_samples=len(before),
            after_samples=len(after),
            effect=round(effect, 3),
            score=round(score, 3),
            confidence=_confidence(score),
            rationale=[
                f"Signal {message_name}.{signal_name} décodé par la base PSA opendbc.",
                "Définition externe à confirmer sur Peugeot 308 T9 2018.",
            ],
            source="opendbc",
            dbc_message=message_name,
            dbc_signal=signal_name,
            unit=unit,
            source_url=source_url,
        ))
    return candidates


def _correlate_marker(
    marker: str,
    marker_events: list[dict],
    frames: list[dict],
    timestamps: list[int],
    options: CorrelationOptions,
    opendbc_source_url: str,
) -> MarkerCorrelation:
    before_by_id: dict[tuple[int, bool], list[dict]] = defaultdict(list)
    after_by_id: dict[tuple[int, bool], list[dict]] = defaultdict(list)
    notes: list[str] = []
    before_us = options.before_ms * 1000
    after_us = options.after_ms * 1000

    for marker_event in marker_events:
        marker_time = int(marker_event["timestamp_us"])
        before_start = bisect_left(timestamps, marker_time - before_us)
        before_end = bisect_left(timestamps, marker_time)
        after_start = bisect_right(timestamps, marker_time)
        after_end = bisect_right(timestamps, marker_time + after_us)
        for frame in frames[before_start:before_end]:
            before_by_id[(frame["id"], frame["extended"])].append(frame)
        for frame in frames[after_start:after_end]:
            after_by_id[(frame["id"], frame["extended"])].append(frame)
        note = str(marker_event.get("note") or "").strip()
        if note and note not in notes:
            notes.append(note)

    candidates: list[SignalCandidate] = []
    repetition_bonus = min(0.08, max(0, len(marker_events) - 1) * 0.025)
    common_ids = set(before_by_id) & set(after_by_id)
    for arbitration_id, extended in common_ids:
        before_frames = before_by_id[(arbitration_id, extended)]
        after_frames = after_by_id[(arbitration_id, extended)]
        if len(before_frames) < options.min_samples or len(after_frames) < options.min_samples:
            continue

        candidates.extend(_opendbc_candidates(
            arbitration_id,
            extended,
            before_frames,
            after_frames,
            len(marker_events),
            options,
            opendbc_source_url,
        ))

        window_before_s = len(marker_events) * options.before_ms / 1000
        window_after_s = len(marker_events) * options.after_ms / 1000
        before_rate = len(before_frames) / window_before_s
        after_rate = len(after_frames) / window_after_s
        rate_effect = abs(after_rate - before_rate) / max(before_rate, after_rate, 0.001)
        if rate_effect >= 0.45 and abs(after_rate - before_rate) >= 1.0:
            score = min(1.0, 0.82 * rate_effect + repetition_bonus)
            candidates.append(SignalCandidate(
                arbitration_id=arbitration_id,
                extended=extended,
                kind="frequency",
                before_value=f"{before_rate:.1f} tr/s",
                after_value=f"{after_rate:.1f} tr/s",
                before_samples=len(before_frames),
                after_samples=len(after_frames),
                effect=round(rate_effect, 3),
                score=round(score, 3),
                confidence=_confidence(score),
                rationale=[
                    "Fréquence d'émission différente avant et après le marqueur.",
                    f"Observation répétée sur {len(marker_events)} occurrence(s).",
                ],
            ))

        max_length = max(
            max((len(frame["data"]) for frame in before_frames), default=0),
            max((len(frame["data"]) for frame in after_frames), default=0),
        )
        for byte_index in range(max_length):
            before_values = [
                frame["data"][byte_index]
                for frame in before_frames
                if len(frame["data"]) > byte_index
            ]
            after_values = [
                frame["data"][byte_index]
                for frame in after_frames
                if len(frame["data"]) > byte_index
            ]
            if len(before_values) < options.min_samples or len(after_values) < options.min_samples:
                continue

            before_mode, before_mode_count = Counter(before_values).most_common(1)[0]
            after_mode, after_mode_count = Counter(after_values).most_common(1)[0]
            variation = _total_variation(before_values, after_values)
            stability = (
                before_mode_count / len(before_values) + after_mode_count / len(after_values)
            ) / 2

            if before_mode != after_mode and variation >= 0.45:
                score = min(1.0, 0.63 * variation + 0.29 * stability + repetition_bonus)
                if score >= 0.58:
                    candidates.append(SignalCandidate(
                        arbitration_id=arbitration_id,
                        extended=extended,
                        kind="byte",
                        byte_index=byte_index,
                        before_value=f"0x{before_mode:02X}",
                        after_value=f"0x{after_mode:02X}",
                        before_samples=len(before_values),
                        after_samples=len(after_values),
                        effect=round(variation, 3),
                        score=round(score, 3),
                        confidence=_confidence(score),
                        rationale=[
                            "Distribution de l'octet nettement différente autour du marqueur.",
                            f"Stabilité moyenne des valeurs dominantes : {stability:.0%}.",
                        ],
                    ))

            for bit_index in range(8):
                before_probability = sum((value >> bit_index) & 1 for value in before_values) / len(before_values)
                after_probability = sum((value >> bit_index) & 1 for value in after_values) / len(after_values)
                effect = abs(after_probability - before_probability)
                if effect < 0.50:
                    continue
                bit_stability = (
                    max(before_probability, 1 - before_probability)
                    + max(after_probability, 1 - after_probability)
                ) / 2
                score = min(1.0, 0.70 * effect + 0.22 * bit_stability + repetition_bonus)
                if score < 0.66:
                    continue
                candidates.append(SignalCandidate(
                    arbitration_id=arbitration_id,
                    extended=extended,
                    kind="bit",
                    byte_index=byte_index,
                    bit_index=bit_index,
                    before_value=f"{before_probability:.0%} à 1",
                    after_value=f"{after_probability:.0%} à 1",
                    before_samples=len(before_values),
                    after_samples=len(after_values),
                    effect=round(effect, 3),
                    score=round(score, 3),
                    confidence=_confidence(score),
                    rationale=[
                        "Probabilité du bit fortement modifiée après l'action.",
                        f"Stabilité moyenne : {bit_stability:.0%}.",
                    ],
                ))

    candidates.sort(
        key=lambda item: (
            item.score + (0.015 if item.source == "opendbc" else 0),
            item.effect,
        ),
        reverse=True,
    )
    return MarkerCorrelation(
        marker=marker,
        notes=notes,
        occurrences=len(marker_events),
        before_ms=options.before_ms,
        after_ms=options.after_ms,
        candidates=candidates[:options.max_candidates_per_marker],
    )


def analyze_behavior(
    session_id: str,
    options: CorrelationOptions | None = None,
) -> BehavioralAnalysisReport:
    options = options or CorrelationOptions()
    events = load_events(session_id)
    frames = _frame_events(events)
    opendbc_decoder = get_opendbc_decoder()
    opendbc_info = _decorate_with_opendbc(frames, opendbc_decoder)
    markers_by_name: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event.get("type") != "marker":
            continue
        marker = str(event.get("name") or "").strip()
        if marker:
            markers_by_name[marker].append(event)

    timestamps = [frame["timestamp_us"] for frame in frames]
    correlations = [
        _correlate_marker(
            marker,
            marker_events,
            frames,
            timestamps,
            options,
            opendbc_decoder.source_url,
        )
        for marker, marker_events in markers_by_name.items()
    ]
    correlations.sort(
        key=lambda item: max((candidate.score for candidate in item.candidates), default=0),
        reverse=True,
    )
    duration_ms = 0.0
    if len(frames) >= 2:
        duration_ms = max(0.0, (frames[-1]["timestamp_us"] - frames[0]["timestamp_us"]) / 1000)

    warnings = [
        "Les correspondances sont des hypothèses statistiques, pas des décodages validés.",
        "Répéter chaque action au moins trois fois avec le même marqueur améliore fortement la confiance.",
        "Valider une hypothèse sur plusieurs sessions avant de l'ajouter à la base véhicule.",
    ]
    if opendbc_info.loaded:
        warnings.append(
            "Les libellés opendbc proviennent d'une base PSA externe non validée pour la 308 T9 2018."
        )
    elif opendbc_info.enabled:
        warnings.append(opendbc_info.error or "La base opendbc n'a pas pu être chargée.")
    if markers_by_name and not any(item.candidates for item in correlations):
        warnings.append(
            "Aucune corrélation assez stable : augmenter la durée des fenêtres ou répéter les actions."
        )
    if not markers_by_name:
        warnings.append("Aucun marqueur présent : seule la cartographie des identifiants est disponible.")

    return BehavioralAnalysisReport(
        session_id=session_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_frames=len(frames),
        unique_ids=len({(frame["id"], frame["extended"]) for frame in frames}),
        duration_ms=round(duration_ms, 1),
        marker_count=sum(len(items) for items in markers_by_name.values()),
        inventory=_inventory(frames),
        correlations=correlations,
        opendbc=opendbc_info,
        warnings=warnings,
    )


def analyze_session(session_id: str) -> AnalysisReport:
    events = load_events(session_id)
    frames = [e for e in events if e.get("type") == "can_frame"]
    markers = [e.get("name", "") for e in events if e.get("type") == "marker"]

    parsed = []
    for index, event in enumerate(frames):
        try:
            data = bytes.fromhex(event.get("data_hex", ""))
        except ValueError:
            continue
        iso = parse_isotp_frame(data)
        if iso is None or iso.kind not in {"single", "first"}:
            continue
        service = uds_service(iso.payload)
        if service is None:
            continue
        parsed.append({
            "index": index,
            "timestamp_us": int(event["timestamp_us"]),
            "id": int(event["arbitration_id"]),
            "payload": iso.payload,
            "service": service,
            "kind": iso.kind,
        })

    candidates_by_key: dict[tuple, dict] = {}
    for req in parsed:
        service = req["service"]
        if service >= 0x40 or service == 0x7F:
            continue

        response = None
        # Recherche temporelle conservatrice : 500 ms et 64 événements suivants.
        for rsp in parsed:
            if rsp["index"] <= req["index"]:
                continue
            if rsp["index"] - req["index"] > 64:
                break
            delta = rsp["timestamp_us"] - req["timestamp_us"]
            if delta < 0 or delta > 500_000:
                continue
            if is_positive_response(service, rsp["payload"]) or is_negative_response(service, rsp["payload"]):
                response = rsp
                break

        response_id = response["id"] if response else req["id"] + 8
        response_hex = response["payload"].hex().upper() if response else None
        key = (req["id"], response_id, req["payload"].hex().upper(), response_hex)

        rationale = ["Trame compatible ISO-TP.", f"Service UDS 0x{service:02X} détecté."]
        confidence = 0.48

        if response:
            confidence += 0.30
            rationale.append("Réponse UDS corrélée temporellement.")
            if response_id == req["id"] + 8:
                confidence += 0.08
                rationale.append("Écart d'identifiant +8 fréquent en diagnostic 11 bits.")

        if service in READ_ONLY_SERVICES:
            confidence += 0.08
            access = "read_only"
            rationale.append("Service classé lecture/diagnostic.")
        elif service in SENSITIVE_SERVICES:
            access = "sensitive"
            rationale.append("Service sensible : ne pas rejouer automatiquement.")
        else:
            access = "unknown"

        if key not in candidates_by_key:
            candidates_by_key[key] = {
                "request_id": req["id"],
                "response_id": response_id,
                "service": service,
                "positive_response_service": ((service + 0x40) & 0xFF) if response else None,
                "request_payload_hex": req["payload"].hex().upper(),
                "response_payload_hex": response_hex,
                "occurrences": 1,
                "confidence": min(confidence, 0.99),
                "rationale": rationale,
                "access": access,
                "status": "experimental",
            }
        else:
            candidates_by_key[key]["occurrences"] += 1
            candidates_by_key[key]["confidence"] = min(
                0.99, candidates_by_key[key]["confidence"] + 0.02
            )

    candidates = [
        UdsCandidate(**value)
        for value in sorted(
            candidates_by_key.values(),
            key=lambda x: (x["confidence"], x["occurrences"]),
            reverse=True,
        )
    ]

    warnings = [
        "Les résultats sont heuristiques et doivent être vérifiés manuellement.",
        "Ne jamais rejouer automatiquement un service sensible.",
    ]

    return AnalysisReport(
        session_id=session_id,
        total_frames=len(frames),
        unique_ids=len({f.get("arbitration_id") for f in frames}),
        markers=markers,
        candidates=candidates,
        warnings=warnings,
    )
