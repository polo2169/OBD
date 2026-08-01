from pathlib import Path
from functools import cached_property
from collections import Counter
import json
import yaml

from app.config import settings
from app.models import EcuDefinition


class KnowledgeBase:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.database_dir

    def vehicle(self, profile: str | None = None) -> dict:
        name = profile or settings.vehicle_profile
        path = self._vehicle_paths().get(name)
        if path is None:
            raise FileNotFoundError(f"Profil véhicule introuvable : {name}")
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _vehicle_paths(self) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        for path in sorted(self.root.glob("*/vehicles/*.yaml")):
            paths[path.stem] = path
        return paths

    def vehicle_profiles(self) -> list[dict]:
        profiles: list[dict] = []
        for key, path in self._vehicle_paths().items():
            vehicle = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            diagnostic = vehicle.get("diagnostic", {})
            strategies = diagnostic.get("vin_strategies", [])
            profiles.append({
                "key": key,
                "manufacturer": vehicle.get("manufacturer", "Inconnu"),
                "model": vehicle.get("model", "Inconnu"),
                "platform": vehicle.get("platform"),
                "year": vehicle.get("year"),
                "architecture": vehicle.get("architecture"),
                "confidence": vehicle.get("confidence", "experimental"),
                "identity_scope": diagnostic.get("identity_scope", "full_profile"),
                "vin_methods": [
                    strategy.get("label", strategy.get("key", "Méthode inconnue"))
                    for strategy in strategies
                ],
                "notes": vehicle.get("notes", []),
            })
        return profiles

    def ecus(self, profile: str | None = None) -> list[EcuDefinition]:
        vehicle = self.vehicle(profile)
        definitions: list[EcuDefinition] = []
        for item in vehicle.get("ecus", []):
            definitions.append(EcuDefinition(**item))
        return definitions

    def dids(self) -> dict[int, dict]:
        path = self.root / "psa" / "dids" / "standard.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return {int(str(key), 0): value for key, value in data.items()}

    @cached_property
    def _community_dtc_data(self) -> dict:
        path = self.root / "psa" / "dtcs" / "psa_community.json"
        if not path.exists():
            return {"_meta": {}, "catalogs": {}}
        return json.loads(path.read_text(encoding="utf-8"))

    @cached_property
    def _dtc_index(self) -> dict[str, list[tuple[str, str]]]:
        index: dict[str, list[tuple[str, str]]] = {}
        for catalog, definitions in self._community_dtc_data.get("catalogs", {}).items():
            for code, title in definitions.items():
                index.setdefault(code.upper(), []).append((catalog, title))
        return index

    def dtc_metadata(self) -> dict:
        return self._community_dtc_data.get("_meta", {})

    def lookup_dtc(self, code: str, preferred_catalogs: list[str] | None = None) -> dict:
        normalized = code.upper()
        validated_path = self.root / "psa" / "dtcs" / "vehicle_validated.yaml"
        validated = yaml.safe_load(validated_path.read_text(encoding="utf-8")) if validated_path.exists() else {}
        if normalized in (validated or {}):
            definition = validated[normalized]
            return {
                "title": definition.get("title"),
                "catalogs": [definition.get("system", "vehicle_validated")],
                "source": definition.get("source"),
                "confidence": definition.get("confidence", "vehicle_catalog_confirmed"),
            }
        matches = self._dtc_index.get(normalized, [])
        preferred = preferred_catalogs or []
        preferred_matches = [item for name in preferred for item in matches if item[0] == name]
        candidates = preferred_matches or matches
        if candidates:
            title_counts = Counter(title for _, title in candidates)
            title = title_counts.most_common(1)[0][0]
            catalogs = sorted({catalog for catalog, candidate_title in candidates if candidate_title == title})
            metadata = self.dtc_metadata()
            return {
                "title": title,
                "catalogs": catalogs,
                "source": metadata.get("source"),
                "confidence": (
                    "community_preferred_catalog"
                    if preferred_matches
                    else "community_global_match"
                ),
            }

        generic_path = self.root / "psa" / "dtcs" / "generic_examples.yaml"
        generic = yaml.safe_load(generic_path.read_text(encoding="utf-8")) or {}
        if normalized in generic:
            definition = generic[normalized]
            return {
                "title": definition.get("title"),
                "catalogs": ["generic_examples"],
                "source": definition.get("source"),
                "confidence": definition.get("confidence", "generic"),
            }
        return {}

    def identification_dids(self, profile: str | None = None) -> list[int]:
        vehicle = self.vehicle(profile)
        configured = vehicle.get("diagnostic", {}).get("identification_dids", [0xF190])
        return [int(str(value), 0) for value in configured]

    def probe_did(self, profile: str | None = None) -> int:
        vehicle = self.vehicle(profile)
        configured = vehicle.get("diagnostic", {}).get("probe_did", 0xF190)
        return int(str(configured), 0)
