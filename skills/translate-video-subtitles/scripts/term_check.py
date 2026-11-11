#!/usr/bin/env python3
"""Check corrected/translated cues against a project terminology glossary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def contains(text: str, needle: str) -> bool:
    if re.fullmatch(r"[A-Za-z0-9 .+/#_-]+", needle):
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None
    return needle.casefold() in text.casefold()


def check(project: dict, glossary: dict) -> dict:
    errors, reviews = [], []
    entries = glossary.get("entries", [])
    for cue in project.get("cues", []):
        cue_id = cue.get("id")
        source = str(cue.get("source", ""))
        target = str(cue.get("target", ""))
        for entry in entries:
            canonical = str(entry.get("canonical", "")).strip()
            if not canonical:
                continue
            expected = str(entry.get("target") or canonical)
            for alias in entry.get("aliases", []):
                if alias.casefold() == canonical.casefold():
                    continue
                if contains(source, alias) or contains(target, alias):
                    issue = {"cue": cue_id, "alias": alias, "canonical": canonical, "evidence": entry.get("evidence")}
                    (errors if entry.get("strict_aliases") else reviews).append(issue)
            if contains(source, canonical):
                if entry.get("preserve", False) and not contains(target, canonical):
                    errors.append({"cue": cue_id, "missing_preserved_term": canonical})
                elif not entry.get("preserve", False) and expected and not contains(target, expected):
                    errors.append({"cue": cue_id, "expected_target_term": expected, "source_term": canonical})
    return {"errors": errors, "reviews": reviews, "passed": not errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--glossary", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    project = json.loads(args.input.read_text(encoding="utf-8"))
    glossary = json.loads(args.glossary.read_text(encoding="utf-8"))
    result = check(project, glossary)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
