#!/usr/bin/env python3
"""Run an available Whisper CLI with reliable defaults and a deterministic output path."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def find_whisper() -> str | None:
    found = shutil.which("whisper")
    if found:
        return found
    base = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    candidates = [
        base / "tools" / "translate-video-subtitles" / "venv" / "bin" / "whisper",
        base / "tools" / "translate-video-subtitles" / "venv" / "Scripts" / "whisper.exe",
    ]
    return next((str(path) for path in candidates if path.exists()), None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model", default="turbo")
    parser.add_argument("--language")
    parser.add_argument("--initial-prompt")
    parser.add_argument("--threads", type=int)
    args = parser.parse_args()

    if not args.input.is_file():
        parser.error(f"input does not exist: {args.input}")
    whisper = find_whisper()
    if not whisper:
        print("Whisper is missing. Run scripts/bootstrap.sh or bootstrap.ps1 first.", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        whisper,
        str(args.input.resolve()),
        "--model", args.model,
        "--output_dir", str(args.output_dir.resolve()),
        "--output_format", "json",
        "--task", "transcribe",
        "--word_timestamps", "True",
        "--fp16", "False",
        "--verbose", "False",
    ]
    if args.language:
        cmd += ["--language", args.language]
    if args.initial_prompt:
        cmd += ["--initial_prompt", args.initial_prompt, "--carry_initial_prompt", "True"]
    if args.threads:
        cmd += ["--threads", str(args.threads)]

    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    expected = args.output_dir / f"{args.input.stem}.json"
    if not expected.exists():
        matches = sorted(args.output_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches:
            print("Whisper completed but no JSON output was found.", file=sys.stderr)
            return 3
        expected = matches[0]
    print(expected.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
