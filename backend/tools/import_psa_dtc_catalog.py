"""Normalize the public arduino-psa-diag Markdown DTC catalog.

Usage:
    python tools/import_psa_dtc_catalog.py /path/to/arduino-psa-diag/dtc \
        ../database/psa/dtcs/psa_community.json

The generated file deliberately retains the upstream revision and GPL-3.0
provenance. It is data imported from an external project, not an OpenDiag claim
that every definition applies to every PSA vehicle.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


REVISION = "c1409e60798f66bb63149505826170b5eb3c163f"
SOURCE = f"https://github.com/ludwig-v/arduino-psa-diag/tree/{REVISION}/dtc"
ROW = re.compile(r"^\|\s*([PCBU][0-9A-Fa-f]{4})\s*\|\s*(.*?)\s*\|\s*$")


def parse_catalog(path: Path) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = ROW.match(raw_line)
        if not match:
            continue
        code = match.group(1).upper()
        title = " ".join(match.group(2).replace("\\|", "|").split())
        if title and title != "-":
            definitions.setdefault(code, title)
    return definitions


def build(source_dir: Path) -> dict:
    catalogs: dict[str, dict[str, str]] = {}
    for path in sorted(source_dir.glob("*.md"), key=lambda item: item.name.casefold()):
        definitions = parse_catalog(path)
        if definitions:
            catalogs[path.stem] = dict(sorted(definitions.items()))
    return {
        "_meta": {
            "source": SOURCE,
            "revision": REVISION,
            "license": "GPL-3.0",
            "format": 1,
            "catalog_count": len(catalogs),
            "definition_count": sum(len(items) for items in catalogs.values()),
            "warning": (
                "Community data. Match the ECU variant before treating a description "
                "as vehicle-confirmed."
            ),
        },
        "catalogs": catalogs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not args.source_dir.is_dir():
        parser.error(f"Dossier DTC introuvable : {args.source_dir}")
    payload = build(args.source_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"{payload['_meta']['catalog_count']} catalogues, "
        f"{payload['_meta']['definition_count']} définitions -> {args.output}"
    )


if __name__ == "__main__":
    main()
