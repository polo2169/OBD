from pathlib import Path
from functools import cached_property
from collections import Counter
import json
import yaml

from app.config import settings
from app.models import EcuDefinition


_PYPSADIAG_FAMILY_ALIASES = {"BMF_UDS_PSA": "BMF"}

_PYPSADIAG_NON_CODING_TABS = {"ident", "vin", "cal"}


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

    @cached_property
    def _pypsadiag_variants(self) -> dict[str, dict[str, dict]]:
        """Return the source JSONs without merging ECU variants.

        A family can contain several incompatible ECUs (for example NAC, RCC
        and IVI in ``TELEMAT``).  Merging their zones is useful for discovery,
        but is not safe enough for a write workflow.  Telecoding therefore
        always resolves one exact source file through this index.
        """
        root = self._pypsadiag_root / "ecu_definitions"
        result: dict[str, dict[str, dict]] = {}
        if not root.exists():
            return result
        for family_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            variants: dict[str, dict] = {}
            for path in sorted(family_dir.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if isinstance(payload, dict):
                    variants[path.stem] = payload
            if variants:
                result[family_dir.name] = variants
        return result

    @staticmethod
    def _option_definition(option: dict, index: int, byte_length: int) -> dict | None:
        raw_binary = option.get("mask")
        raw_hex = option.get("value")
        try:
            if isinstance(raw_binary, str):
                encoded = int(raw_binary, 2)
            elif isinstance(raw_hex, str):
                encoded = int(raw_hex, 16)
            else:
                return None
        except ValueError:
            return None
        width = max(byte_length * 2, 2)
        return {
            "key": f"option-{index}",
            "name": str(option.get("name") or f"Valeur 0x{encoded:X}"),
            "encoded_hex": f"{encoded:0{width}X}",
        }

    @classmethod
    def _field_definition(
        cls,
        field: dict,
        *,
        key: str,
        zone_read_only: bool,
    ) -> dict:
        form_type = str(field.get("form_type") or "string")
        mask_binary = field.get("mask")
        byte_range = field.get("byte_range")
        if isinstance(byte_range, int) and byte_range > 0:
            byte_length = byte_range
        elif isinstance(mask_binary, str) and mask_binary:
            byte_length = max(1, (len(mask_binary) + 7) // 8)
        else:
            byte_length = 1
        mask_hex = None
        if isinstance(mask_binary, str):
            try:
                mask_hex = f"{int(mask_binary, 2):0{byte_length * 2}X}"
            except ValueError:
                mask_hex = None

        options = [
            normalized
            for index, option in enumerate(field.get("params") or [])
            if isinstance(option, dict)
            for normalized in [cls._option_definition(option, index, byte_length)]
            if normalized is not None
        ]
        available_logic = str(field.get("available_logic") or "active_low")
        if form_type == "checkbox" and mask_hex is not None:
            mask_value = int(mask_hex, 16)
            active_value = mask_value if available_logic == "active_high" else 0
            inactive_value = 0 if available_logic == "active_high" else mask_value
            options = [
                {
                    "key": "false",
                    "name": "Absent / désactivé",
                    "encoded_hex": f"{inactive_value:0{byte_length * 2}X}",
                },
                {
                    "key": "true",
                    "name": "Présent / activé",
                    "encoded_hex": f"{active_value:0{byte_length * 2}X}",
                },
            ]

        zone_lengths = field.get("zoneLength")
        if isinstance(zone_lengths, int):
            accepted_lengths = [zone_lengths]
        elif isinstance(zone_lengths, list):
            accepted_lengths = [item for item in zone_lengths if isinstance(item, int)]
        else:
            accepted_lengths = []
        read_only = zone_read_only or bool(field.get("read_only", False))
        writable = bool(
            not read_only
            and mask_hex is not None
            and form_type in {"checkbox", "combobox"}
            and options
        )
        return {
            "key": key,
            "name": str(field.get("name") or key),
            "form_type": form_type,
            "value_type": str(field.get("type") or "raw"),
            "byte": int(field.get("byte") or 0),
            "byte_length": byte_length,
            "mask_hex": mask_hex,
            "available_logic": available_logic,
            "accepted_zone_lengths": accepted_lengths,
            "read_only": read_only,
            "writable": writable,
            "options": options,
        }

    @classmethod
    def _zone_definition(cls, zone_id: str, zone: dict, tabs: dict) -> dict:
        zone_read_only = bool(zone.get("read_only", False))
        fields: list[dict] = []
        if zone.get("form_type") == "multi":
            raw_params = zone.get("params")
            if isinstance(raw_params, list):
                for index, field in enumerate(raw_params):
                    if not isinstance(field, dict) or not field.get("form_type"):
                        continue
                    key = str(
                        field.get("id")
                        or field.get("extra_name")
                        or field.get("name_original")
                        or f"field-{index}"
                    )
                    fields.append(cls._field_definition(field, key=key, zone_read_only=zone_read_only))
            for key, field in zone.items():
                if not isinstance(field, dict) or not field.get("form_type"):
                    continue
                fields.append(cls._field_definition(field, key=key, zone_read_only=zone_read_only))
        elif zone.get("form_type") in {"checkbox", "combobox", "string"}:
            key = str(zone.get("id") or f"zone-{zone_id}")
            fields.append(cls._field_definition(zone, key=key, zone_read_only=zone_read_only))

        tab = str(zone.get("tab") or "other")
        structured = bool(fields)
        coding_candidate = bool(
            structured
            and tab not in _PYPSADIAG_NON_CODING_TABS
            and not zone_read_only
            and int(zone_id, 16) < 0xF000
        )
        return {
            "did": int(zone_id, 16),
            "did_hex": zone_id.upper().zfill(4),
            "name": str(zone.get("name") or zone.get("id") or f"Zone 0x{zone_id}"),
            "tab": tab,
            "tab_name": str(tabs.get(tab) or tab),
            "value_type": str(zone.get("type") or "raw"),
            "form_type": str(zone.get("form_type") or "string"),
            "read_only": zone_read_only,
            "coding_candidate": coding_candidate,
            "writable": coding_candidate and any(field["writable"] for field in fields),
            "fields": fields,
        }

    def telecoding_variants_for_family(self, family: str | None) -> list[dict]:
        if not family:
            return []
        folder = _PYPSADIAG_FAMILY_ALIASES.get(family, family)
        variants = self._pypsadiag_variants.get(folder, {})
        normalized: list[dict] = []
        for variant_id, payload in variants.items():
            tabs = payload.get("tabs") if isinstance(payload.get("tabs"), dict) else {}
            zones = []
            for zone_id, zone in (payload.get("zones") or {}).items():
                if not isinstance(zone, dict):
                    continue
                try:
                    zones.append(self._zone_definition(str(zone_id), zone, tabs))
                except ValueError:
                    continue
            raw_keys = payload.get("keys")
            if isinstance(raw_keys, dict):
                keys = [
                    {"variant": str(name), "key_hex": str(value).upper()}
                    for name, value in raw_keys.items()
                    if isinstance(value, str) and len(value) == 4
                ]
            elif isinstance(raw_keys, str) and len(raw_keys) == 4:
                keys = [{"variant": str(payload.get("name") or variant_id), "key_hex": raw_keys.upper()}]
            else:
                keys = []
            protocol = str(payload.get("protocol") or "unknown")
            normalized.append({
                "id": variant_id,
                "name": str(payload.get("name") or variant_id),
                "family": folder,
                "protocol": protocol,
                "request_id": int(str(payload.get("tx_id")), 16) if payload.get("tx_id") else None,
                "response_id": int(str(payload.get("rx_id")), 16) if payload.get("rx_id") else None,
                "security_keys": keys,
                "tabs": {str(key): str(value) for key, value in tabs.items()},
                "zones": zones,
                "zone_count": len(zones),
                "coding_zone_count": sum(zone["coding_candidate"] for zone in zones),
                "writable_zone_count": sum(zone["writable"] for zone in zones),
                "write_supported": protocol == "uds" and bool(keys),
                "source": self.pypsadiag_source(),
            })
        return normalized

    def telecoding_variant(self, family: str | None, variant_id: str) -> dict:
        variant = next(
            (item for item in self.telecoding_variants_for_family(family) if item["id"] == variant_id),
            None,
        )
        if variant is None:
            raise KeyError(f"Variante de télécodage inconnue : {variant_id}.")
        return variant

    @staticmethod
    def decode_telecoding_fields(zone: dict, raw: bytes) -> list[dict]:
        decoded: list[dict] = []
        for field in zone.get("fields", []):
            start = field["byte"]
            length = field["byte_length"]
            accepted_lengths = field.get("accepted_zone_lengths") or []
            available = (not accepted_lengths or len(raw) in accepted_lengths) and start + length <= len(raw)
            item = {**field, "available": available, "raw_hex": None, "value_key": None, "value": None}
            if not available:
                decoded.append(item)
                continue
            segment = raw[start:start + length]
            item["raw_hex"] = segment.hex().upper()
            if field.get("mask_hex") is None:
                decoded.append(item)
                continue
            mask = int(field["mask_hex"], 16)
            value = int.from_bytes(segment, "big") & mask
            selected = next(
                (
                    option
                    for option in field.get("options", [])
                    if int(option["encoded_hex"], 16) & mask == value
                ),
                None,
            )
            if selected:
                item["value_key"] = selected["key"]
                item["value"] = selected["name"]
            else:
                item["value"] = f"Valeur non répertoriée (0x{value:0{length * 2}X})"
            decoded.append(item)
        return decoded

    @staticmethod
    def _legacy_telecoding_zones(raw_zones: dict) -> dict[str, dict]:
        """Normalize one PyPSADiag variant to the lightweight read decoder."""
        zones: dict[str, dict] = {}
        for zone_id, zone in raw_zones.items():
            if not isinstance(zone, dict):
                continue
            zones[str(zone_id).upper().zfill(4)] = {
                "name": zone.get("name", zone_id),
                "byte": zone.get("byte", 0),
                "parameters": {
                    key: value
                    for key, value in zone.items()
                    if isinstance(value, dict) and "mask" in value
                },
            }
        return zones

    def telecoding_zones_for_family(
        self,
        family: str | None,
        variant_id: str | None = None,
    ) -> dict[str, dict]:
        """Zone id -> {name, byte, parameters} for a vehicle.yaml ``family`` string.

        The pypsadiag ``ecu_definitions/`` folder names don't always match the
        family string used in our vehicle YAMLs (e.g. BSI is folder ``BMF`` but
        YAML family ``BMF_UDS_PSA``); resolve through that alias here so callers
        never need to know about the mismatch.
        """
        if not family:
            return {}
        folder = _PYPSADIAG_FAMILY_ALIASES.get(family, family)
        if variant_id:
            variant = self._pypsadiag_variants.get(folder, {}).get(variant_id)
            if variant is None:
                return {}
            return self._legacy_telecoding_zones(variant.get("zones") or {})
        return self._pypsadiag_ecu_definitions.get(folder, {})

    def describe_telecoding_zone(
        self,
        family: str | None,
        did: int,
        variant_id: str | None = None,
    ) -> dict | None:
        zones = self.telecoding_zones_for_family(family, variant_id)
        return zones.get(f"{did:04X}")

    def pypsadiag_source(self) -> str | None:
        return self._pypsadiag_metadata.get("source")

    def pypsadiag_metadata(self) -> dict:
        return dict(self._pypsadiag_metadata)

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
