#!/usr/bin/env python3
"""Create a whole-transcript context pack and technical-term candidates."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re


TERM_PATTERNS = [
    re.compile(r"\b[A-Z]{2,}(?:[-./][A-Z0-9]+)*\b"),
    re.compile(r"\b[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]+)+\b"),
    re.compile(r"\b[a-zA-Z]+(?:\.js|\.ts|\.py|\.sh)\b"),
    re.compile(r"(?<!\w)--[a-z0-9][a-z0-9-]*"),
    re.compile(r"\b\w+[/\\]\w+(?:[/\\][\w.-]+)*\b"),
    re.compile(r"\bv?\d+(?:\.\d+){1,3}\b", re.IGNORECASE),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    project = json.loads(args.input.read_text(encoding="utf-8"))
    cues = project.get("cues", [])
    transcript = " ".join(str(cue.get("source", "")).strip() for cue in cues).strip()
    if not transcript:
        parser.error("no source transcript found")
    candidates = Counter()
    for pattern in TERM_PATTERNS:
        candidates.update(pattern.findall(transcript))

    lines = [
        "# Whole-video context pack",
        "",
        f"- Source language: `{project.get('source_language', 'und')}`",
        f"- Cue count: `{len(cues)}`",
        "",
        "## Candidate technical terms",
        "",
        "Verify these against supplied materials or authoritative sources before adding them to the project glossary.",
        "",
    ]
    if candidates:
        lines.extend(f"- `{term}`: {count} occurrence(s)" for term, count in candidates.most_common())
    else:
        lines.append("- No regex-derived candidates; inspect names and domain vocabulary manually.")
    lines.extend(["", "## Full transcript", "", transcript, ""])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
