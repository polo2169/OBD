#!/usr/bin/env python3
"""Import compact, attributable OBD/Fiat DTC catalogs from local checkouts.

The importer deliberately consumes local source trees instead of downloading at
runtime.  This keeps the diagnostic application fully offline and makes every
generated catalog reproducible from a pinned upstream revision.
"""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import date
from pathlib import Path
import json
import subprocess

import yaml


OBDEX_SOURCE = "https://github.com/foerbsnavi/obdex"
FIAT_COMMUNITY_SOURCE = "https://github.com/kierandrewett/obd"
FIAT_ORIGINAL_SOURCE = "https://dot.report/dtc/"


def _revision(root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def import_obdex(source: Path, destination: Path) -> int:
    entries: dict[str, dict] = {}
    for path in sorted((source / "data" / "generic").glob("*_enriched.yaml")):
        for item in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            code = str(item["code"]).upper()
            causes = [
                label
                for cause in item.get("common_causes", [])
                if (label := (cause.get("label") or {}).get("en"))
            ]
            entries[code] = {
                "title": (item.get("title") or {}).get("en"),
                "description": (item.get("description") or {}).get("en"),
                "common_causes": causes,
                "repair_difficulty": (item.get("repair") or {}).get("difficulty"),
            }

    _write_json(destination, {
        "_meta": {
            "source": OBDEX_SOURCE,
            "revision": _revision(source),
            "license": "CC0-1.0",
            "imported": date.today().isoformat(),
            "language": "en",
            "catalog": "obdex_generic",
            "scope": "Generic OBD-II DTCs only; no manufacturer-specific interpretation.",
            "entry_count": len(entries),
        },
        "codes": entries,
    })
    return len(entries)


def import_fiat_community(source: Path, destination: Path) -> int:
    path = source / "dtc_codes" / "fiat.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = {
        str(code).upper(): {"title": str(title)}
        for code, title in raw.items()
        if title
    }
    _write_json(destination, {
        "_meta": {
            "source": FIAT_COMMUNITY_SOURCE,
            "original_source": FIAT_ORIGINAL_SOURCE,
            "revision": _revision(source),
            "license": "MIT",
            "imported": date.today().isoformat(),
            "language": "mixed (English/Italian)",
            "catalog": "fiat_community",
            "scope": (
                "Community Fiat manufacturer-code labels. Not filtered for the Fiat 500, "
                "engine family or model year; always cross-check against the emitting ECU."
            ),
            "entry_count": len(entries),
        },
        "codes": entries,
    })
    return len(entries)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--obdex", type=Path, required=True)
    parser.add_argument("--fiat-community", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()

    generic_count = import_obdex(
        args.obdex.resolve(),
        args.database.resolve() / "generic" / "dtcs" / "obdex.json",
    )
    fiat_count = import_fiat_community(
        args.fiat_community.resolve(),
        args.database.resolve() / "fiat" / "dtcs" / "community.json",
    )
    print(f"Imported {generic_count} generic DTCs and {fiat_count} Fiat labels.")


if __name__ == "__main__":
    main()
