from pathlib import Path
from functools import cached_property
from collections import Counter
import json
import yaml

from app.config import settings
from app.models import EcuDefinition


_PYPSADIAG_FAMILY_ALIASES = {"BMF_UDS_PSA": "BMF"}


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
    def _pypsadiag_root(self) -> Path:
        return self.root / "psa" / "community" / "pypsadiag"

    @cached_property
    def _pypsadiag_metadata(self) -> dict:
        path = self._pypsadiag_root / "metadata.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @cached_property
    def _pypsadiag_dtc_data(self) -> dict[str, dict[str, str]]:
        directory = self._pypsadiag_root / "dtc"
        catalogs: dict[str, dict[str, str]] = {}
        if not directory.exists():
            return catalogs
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = {
                code.upper(): value.get("name", "")
                for code, value in data.items()
                if code != "_comment" and isinstance(value, dict) and value.get("name")
            }
            if entries:
                catalogs[path.stem] = entries
        return catalogs

    @cached_property
    def _pypsadiag_failure_types(self) -> dict[str, str]:
        path = self._pypsadiag_root / "dtc_failure_types.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            code.upper(): value.get("name", "")
            for code, value in data.items()
            if isinstance(value, dict) and value.get("name")
        }

    def failure_type_label(self, failure_type: int) -> str | None:
        return self._pypsadiag_failure_types.get(f"{failure_type:02X}")

    @cached_property
    def _dtc_index(self) -> dict[str, list[tuple[str, str, str | None]]]:
        index: dict[str, list[tuple[str, str, str | None]]] = {}
        community_source = self._community_dtc_data.get("_meta", {}).get("source")
        for catalog, definitions in self._community_dtc_data.get("catalogs", {}).items():
            for code, title in definitions.items():
                index.setdefault(code.upper(), []).append((catalog, title, community_source))
        pypsadiag_source = self._pypsadiag_metadata.get("source")
        for catalog, definitions in self._pypsadiag_dtc_data.items():
            for code, title in definitions.items():
                index.setdefault(code.upper(), []).append((catalog, title, pypsadiag_source))
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
            title_counts = Counter(title for _, title, _ in candidates)
            title = title_counts.most_common(1)[0][0]
            winning = [item for item in candidates if item[1] == title]
            catalogs = sorted({catalog for catalog, candidate_title, _ in winning})
            source = next((entry_source for _, _, entry_source in winning if entry_source), None)
            return {
                "title": title,
                "catalogs": catalogs,
                "source": source,
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

    @cached_property
    def _pypsadiag_ecu_definitions(self) -> dict[str, dict[str, dict]]:
        """family -> zone id (e.g. '2101') -> {name, byte, parameters} merged across
        every ECU variant JSON found under that family (CVM2.json, CVM3.json, ...)."""
        root = self._pypsadiag_root / "ecu_definitions"
        result: dict[str, dict[str, dict]] = {}
        if not root.exists():
            return result
        for family_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            zones: dict[str, dict] = {}
            for path in sorted(family_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                for zone_id, zone in (data.get("zones") or {}).items():
                    if not isinstance(zone, dict):
                        continue
                    merged = zones.setdefault(zone_id, {
                        "name": zone.get("name", zone_id),
                        "byte": zone.get("byte", 0),
                        "parameters": {},
                    })
                    for key, value in zone.items():
                        if key in {"id", "name", "tab", "byte", "type", "form_type"}:
                            continue
                        if isinstance(value, dict) and "mask" in value:
                            merged["parameters"].setdefault(key, value)
            if zones:
                result[family_dir.name] = zones
        return result

    def telecoding_zones_for_family(self, family: str | None) -> dict[str, dict]:
        """Zone id -> {name, byte, parameters} for a vehicle.yaml ``family`` string.

        The pypsadiag ``ecu_definitions/`` folder names don't always match the
        family string used in our vehicle YAMLs (e.g. BSI is folder ``BMF`` but
        YAML family ``BMF_UDS_PSA``); resolve through that alias here so callers
        never need to know about the mismatch.
        """
        if not family:
            return {}
        folder = _PYPSADIAG_FAMILY_ALIASES.get(family, family)
        return self._pypsadiag_ecu_definitions.get(folder, {})

    def describe_telecoding_zone(self, family: str | None, did: int) -> dict | None:
        zones = self.telecoding_zones_for_family(family)
        return zones.get(f"{did:04X}")

    def pypsadiag_source(self) -> str | None:
        return self._pypsadiag_metadata.get("source")

    @staticmethod
    def decode_telecoding_parameters(zone: dict, raw: bytes) -> list[dict]:
        decoded: list[dict] = []
        for key, param in zone.get("parameters", {}).items():
            byte_offset = param.get("byte", 0)
            mask_str = param.get("mask")
            if not isinstance(mask_str, str) or len(mask_str) > 8 or byte_offset >= len(raw):
                continue
            raw_byte = raw[byte_offset]
            mask = int(mask_str, 2)
            masked_value = raw_byte & mask
            matched = None
            for option in param.get("params", []):
                option_mask = option.get("mask")
                if option_mask is None:
                    continue
                if int(option_mask, 2) == masked_value:
                    matched = option.get("name")
                    break
            decoded.append({
                "key": key,
                "name": param.get("name", key),
                "byte": byte_offset,
                "raw_hex": f"{raw_byte:02X}",
                "value": matched,
                "options": [
                    option.get("name")
                    for option in param.get("params", [])
                    if option.get("name") and option.get("mask") is not None
                ],
            })
        return decoded

    def identification_dids(self, profile: str | None = None) -> list[int]:
        vehicle = self.vehicle(profile)
        configured = vehicle.get("diagnostic", {}).get("identification_dids", [0xF190])
        return [int(str(value), 0) for value in configured]

    def probe_did(self, profile: str | None = None) -> int:
        vehicle = self.vehicle(profile)
        configured = vehicle.get("diagnostic", {}).get("probe_did", 0xF190)
        return int(str(configured), 0)
