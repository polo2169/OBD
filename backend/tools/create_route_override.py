"""Create one local, driver-confirmed road geometry for an existing replay."""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import settings


def parse_coordinate(value: str) -> tuple[float, float]:
    try:
        longitude, latitude = (float(part.strip()) for part in value.split(",", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Coordonnée attendue sous la forme longitude,latitude : {value}") from exc
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"Coordonnée hors limites : {value}")
    return longitude, latitude


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("session_id")
    parser.add_argument("--coordinate", action="append", required=True)
    parser.add_argument("--expect", action="append", default=[])
    parser.add_argument("--confirmation", required=True)
    args = parser.parse_args()

    if Path(args.session_id).name != args.session_id or not args.session_id.startswith("learn-"):
        raise SystemExit("Identifiant de session invalide.")
    session_path = settings.session_dir / f"{args.session_id}.jsonl"
    if not session_path.exists():
        raise SystemExit(f"Capture introuvable : {session_path}")
    coordinates = [parse_coordinate(value) for value in args.coordinate]
    if len(coordinates) < 2:
        raise SystemExit("Deux coordonnées au minimum sont nécessaires.")

    coordinate_path = ";".join(f"{longitude:.7f},{latitude:.7f}" for longitude, latitude in coordinates)
    query = urlencode({"overview": "full", "geometries": "geojson", "steps": "true"})
    url = f"https://router.project-osrm.org/route/v1/driving/{coordinate_path}?{query}"
    request = Request(url, headers={"User-Agent": "OpenDiag-PSA/0.5 local-driver-confirmed-route"})
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get("code") != "Ok" or not result.get("routes"):
        raise SystemExit(f"OSRM n'a retourné aucun itinéraire : {result.get('code', 'réponse invalide')}")

    route = result["routes"][0]
    road_refs: list[str] = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            label = str(step.get("ref") or step.get("name") or "").strip()
            if label and label not in road_refs:
                road_refs.append(label)
    normalized_roads = " | ".join(road_refs).casefold()
    missing = [expected for expected in args.expect if expected.casefold() not in normalized_roads]
    if missing:
        raise SystemExit(f"Itinéraire refusé, axes attendus absents : {', '.join(missing)}")

    payload = {
        "version": 1,
        "session_id": args.session_id,
        "source": "osrm_public_driver_confirmed",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "driver_confirmation": args.confirmation,
        "requested_coordinates": [[longitude, latitude] for longitude, latitude in coordinates],
        "snapped_waypoints": result.get("waypoints", []),
        "distance_m": route.get("distance"),
        "duration_s": route.get("duration"),
        "road_refs": road_refs,
        "geometry": route["geometry"],
    }
    output_path = session_path.with_suffix(".route.json")
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    print(json.dumps({
        "path": str(output_path),
        "distance_m": payload["distance_m"],
        "duration_s": payload["duration_s"],
        "road_refs": road_refs,
        "coordinate_count": len(payload["geometry"]["coordinates"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
