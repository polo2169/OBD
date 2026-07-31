import argparse
import json

from app.learn.analyzer import analyze_session
from app.learn.exporter import export_proposals


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse une capture OpenDiag Learn.")
    parser.add_argument("session_id")
    parser.add_argument("--export-yaml", action="store_true")
    args = parser.parse_args()

    report = analyze_session(args.session_id)
    print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))

    if args.export_yaml:
        path = export_proposals(args.session_id)
        print(f"\nProposition YAML : {path}")


if __name__ == "__main__":
    main()
