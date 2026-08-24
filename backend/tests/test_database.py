from collections import Counter
from pathlib import Path
import json

import yaml

from app.config import settings
from app.database import KnowledgeBase


def test_all_versioned_knowledge_files_are_parseable():
    errors: list[str] = []
    for path in sorted(settings.database_dir.rglob("*.yaml")):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            errors.append(f"{path}: {exc}")
    for path in sorted(settings.database_dir.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
    assert errors == []


def test_published_vehicle_profiles_are_unique_and_complete():
    profiles = KnowledgeBase().vehicle_profiles()
    assert profiles

    identities = [
        (
            profile["manufacturer"],
            profile["model"],
            profile["platform"],
            profile["year"],
        )
        for profile in profiles
    ]
    duplicates = [identity for identity, count in Counter(identities).items() if count > 1]
    assert duplicates == []

    required = {"key", "manufacturer", "model", "architecture", "confidence"}
    assert all(required <= profile.keys() for profile in profiles)
    assert all(profile["manufacturer"] != "Inconnu" for profile in profiles)
    assert all(profile["model"] != "Inconnu" for profile in profiles)


def test_renault_trafic_ecus_parse_without_validation_errors():
    ecus = KnowledgeBase().ecus("renault_trafic_x82")
    assert {ecu.key for ecu in ecus} == {
        "engine",
        "gearbox",
        "abs_esp",
        "power_steering",
        "body_computer",
        "airbag",
        "gateway",
        "instrument_cluster",
    }
    assert all(ecu.protocol == "uds" and ecu.access == "read_only" for ecu in ecus)


def test_renault_trafic_x83_publishes_250k_live_obd_identity_profile():
    knowledge = KnowledgeBase()
    profile = knowledge.vehicle("renault_trafic_x83")
    summary = next(
        item for item in knowledge.vehicle_profiles() if item["key"] == "renault_trafic_x83"
    )

    assert profile["platform"] == "X83"
    assert profile["networks"]["diagnostic_can"]["bitrate"] == 250_000
    assert summary["identity_scope"] == "identity_only"
    assert summary["identity_buses"] == ["live"]
    assert summary["identity_protocols"] == ["obd"]
    assert summary["can_bitrate"] == 250_000
    assert {ecu.key for ecu in knowledge.ecus("renault_trafic_x83")} == {"engine"}


def test_draft_profiles_are_outside_the_published_vehicle_directories():
    published = {path.resolve() for path in settings.database_dir.glob("*/vehicles/*.yaml")}
    drafts = {path.resolve() for path in settings.database_dir.glob("*/drafts/*.yaml")}
    assert published.isdisjoint(drafts)
    assert Path(settings.database_dir / "fiat" / "drafts" / "fiat_500_generic_legacy.yaml").exists()


def test_open_dtc_catalogs_are_loaded_with_attribution_and_rich_details():
    knowledge = KnowledgeBase()
    metadata = knowledge.dtc_metadata()

    assert metadata["generic"]["entry_count"] == 9_533
    assert metadata["generic"]["license"] == "CC0-1.0"
    assert metadata["fiat"]["entry_count"] == 100
    assert metadata["fiat"]["license"] == "MIT"

    generic = knowledge.lookup_dtc("P0100")
    assert generic["catalogs"] == ["obdex_generic"]
    assert generic["description"]
    assert len(generic["common_causes"]) >= 1
    assert generic["repair_difficulty"]


def test_fiat_dtc_lookup_is_preferred_only_in_fiat_context():
    knowledge = KnowledgeBase()

    fiat = knowledge.lookup_dtc("P1300", ["fiat_community", "obdex_generic"])
    assert fiat["catalogs"] == ["fiat_community"]
    assert fiat["confidence"] == "community_manufacturer_match_unverified_for_vehicle"

    # A Fiat lookup must never inherit an unrelated PSA manufacturer label.
    assert knowledge.lookup_dtc("B1238", ["fiat_community", "obdex_generic"]) == {}
