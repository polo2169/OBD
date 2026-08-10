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


def test_draft_profiles_are_outside_the_published_vehicle_directories():
    published = {path.resolve() for path in settings.database_dir.glob("*/vehicles/*.yaml")}
    drafts = {path.resolve() for path in settings.database_dir.glob("*/drafts/*.yaml")}
    assert published.isdisjoint(drafts)
    assert Path(settings.database_dir / "fiat" / "drafts" / "fiat_500_generic_legacy.yaml").exists()
