"""Validate the example library and run explicit live hook evaluations."""

import argparse
import json
from pathlib import Path

from editmaxxing.config import Settings
from editmaxxing.hook_policy import load_examples, policy_version
from editmaxxing.models import Word
from editmaxxing.provider import OpenAIProvider, ProviderError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Call the configured model for each case.")
    parser.add_argument("--case", help="Run one case ID.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/hook-evaluation.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "backend/tests/fixtures/hook_eval_cases.json").read_text())
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            parser.error("Choose a case ID from backend/tests/fixtures/hook_eval_cases.json.")
    examples = load_examples()
    provider = OpenAIProvider(Settings()) if args.live else None
    rows = []
    for case in cases:
        row = {**case, "status": "ready_for_live_review"}
        if provider:
            words = [
                Word(
                    id=f"w_{i}",
                    source_id="body",
                    text=text,
                    start_ms=i * 350,
                    end_ms=i * 350 + 300,
                )
                for i, text in enumerate(case["transcript"].split())
            ]
            try:
                result = provider.analyze(words, [])
                row.update(status="requires_editorial_review", result=result.model_dump())
            except ProviderError as error:
                row.update(status="failed", error_code=error.code)
        rows.append(row)
    report = {
        "policy_version": policy_version(),
        "library_validation": "passed",
        "example_count": len(examples),
        "mode": "live" if args.live else "offline",
        "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Library: {len(examples)} valid examples. Cases: {len(rows)}. Mode: {report['mode']}.")
    print(f"Report: {args.output.resolve()}")
    if any(row["status"] == "failed" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
