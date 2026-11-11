#!/usr/bin/env python3
"""Objective acceptance report for a translated hard-subtitled video."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import statistics
import subprocess
import tempfile

import subtitle_tool as st
import term_check


SSIM_RE = re.compile(r"All:([0-9.]+)")


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def sample_cues(cues: list[dict], count: int) -> list[dict]:
    usable = [cue for cue in cues if cue["end"] - cue["start"] >= 0.7]
    if len(usable) <= count:
        return usable
    return [usable[round(i * (len(usable) - 1) / (count - 1))] for i in range(count)]


def region_ssim(source: Path, output: Path, timestamp: float, region: str) -> float | None:
    if region == "top":
        crop = "crop=iw:trunc(ih*0.30/2)*2:0:0"
    else:
        crop = "crop=iw:trunc(ih*0.34/2)*2:0:ih-oh"
    graph = f"[0:v]{crop}[a];[1:v]{crop}[b];[a][b]ssim"
    proc = subprocess.run([
        st.require_tool("ffmpeg"), "-hide_banner", "-ss", f"{timestamp:.3f}", "-i", str(source),
        "-ss", f"{timestamp:.3f}", "-i", str(output), "-filter_complex", graph,
        "-frames:v", "1", "-f", "null", "-",
    ], text=True, capture_output=True)
    match = SSIM_RE.search(proc.stderr)
    return float(match.group(1)) if match else None


def make_contact_sheet(video: Path, cues: list[dict], output: Path, count: int) -> None:
    chosen = sample_cues(cues, count)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="subtitle-qa-") as temp:
        temp_path = Path(temp)
        for index, cue in enumerate(chosen):
            timestamp = (cue["start"] + cue["end"]) / 2
            frame = temp_path / f"frame-{index:03d}.jpg"
            subprocess.run([
                st.require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{timestamp:.3f}", "-i", str(video), "-frames:v", "1",
                "-vf", "scale=480:-2:force_original_aspect_ratio=decrease", "-q:v", "2", str(frame),
            ], check=True)
        subprocess.run([
            st.require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", "1", "-i", str(temp_path / "frame-%03d.jpg"),
            "-vf", f"tile={len(chosen)}x1", "-frames:v", "1", str(output),
        ], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=st.path_file)
    parser.add_argument("--output", required=True, type=st.path_file)
    parser.add_argument("--cues", required=True, type=st.path_file)
    parser.add_argument("--ass", required=True, type=st.path_file)
    parser.add_argument("--glossary", required=True, type=st.path_file)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--contact-sheet", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=5, choices=range(2, 10))
    args = parser.parse_args()

    source = st.media_summary(args.source)
    output = st.media_summary(args.output)
    project = st.load_project(args.cues)
    glossary = json.loads(args.glossary.read_text(encoding="utf-8"))
    cues = project["cues"]
    failures, warnings = [], []

    duration_delta = abs(source["duration"] - output["duration"])
    if duration_delta > 0.25:
        failures.append(f"duration delta {duration_delta:.3f}s exceeds 0.25s")
    if (source["width"], source["height"]) != (output["width"], output["height"]):
        failures.append("output resolution differs from source")
    if not output["audio_streams"]:
        failures.append("output has no audio stream")
    if not output["video_codec"]:
        failures.append("output has no video stream")

    lint_errors, lint_warnings = st.lint_project(project, True)
    failures.extend(lint_errors)
    warnings.extend(lint_warnings)
    durations = [cue["end"] - cue["start"] for cue in cues]
    source_rates = [len(cue["source"]) / max(cue["end"] - cue["start"], .001) for cue in cues]
    target_rates = [st.display_units(cue["target"]) / max(cue["end"] - cue["start"], .001) for cue in cues]
    outside_duration = sum(d < .7 or d > 8 for d in durations)
    if cues and outside_duration / len(cues) > .05:
        failures.append("more than 5% of cues fall outside 0.7-8.0 seconds")
    source_p95, target_p95 = percentile(source_rates, .95), percentile(target_rates, .95)
    if source_p95 > 24:
        failures.append(f"source reading-rate p95 {source_p95:.1f} exceeds 24 chars/s")
    if target_p95 > 18:
        failures.append(f"target reading-rate p95 {target_p95:.1f} exceeds 18 units/s")

    width, height = source["width"], source["height"]
    short = min(width, height)
    target_size = max(24, round(short * .038))
    source_size = max(18, round(short * .028))
    target_limit = max(18, round(width / (target_size * 1.08)))
    source_limit = max(30, round(width / (source_size * .60)))
    line_failures = []
    for cue in cues:
        target_lines = st.wrap_cjk(cue["target"], target_limit).count(r"\N") + 1
        source_lines = st.wrap_latin(cue["source"], source_limit).count(r"\N") + 1
        if target_lines > 2 or source_lines > 2:
            line_failures.append({"cue": cue["id"], "target_lines": target_lines, "source_lines": source_lines})
    if line_failures:
        failures.append(f"{len(line_failures)} cue(s) exceed two lines in one language")

    terms = term_check.check(project, glossary)
    if terms["errors"]:
        failures.append(f"{len(terms['errors'])} terminology consistency error(s)")
    if terms["reviews"]:
        failures.append(f"{len(terms['reviews'])} suspected ASR alias(es) remain unresolved")

    chosen = sample_cues(cues, args.samples)
    burn_samples = []
    for cue in chosen:
        timestamp = (cue["start"] + cue["end"]) / 2
        top = region_ssim(args.source, args.output, timestamp, "top")
        bottom = region_ssim(args.source, args.output, timestamp, "bottom")
        detected = top is not None and bottom is not None and bottom < top - .002
        burn_samples.append({"cue": cue["id"], "time": timestamp, "top_ssim": top, "subtitle_region_ssim": bottom, "caption_delta_detected": detected})
    burn_ratio = statistics.mean(item["caption_delta_detected"] for item in burn_samples) if burn_samples else 0
    if burn_ratio < .6:
        failures.append(f"hard-subtitle pixel delta detected in only {burn_ratio:.0%} of sampled cue frames")

    make_contact_sheet(args.output, cues, args.contact_sheet, args.samples)
    if not args.ass.is_file() or args.ass.stat().st_size < 200:
        failures.append("ASS deliverable is missing or unexpectedly small")

    report = {
        "passed": not failures,
        "thresholds": {
            "duration_delta_seconds_max": .25,
            "cue_duration_seconds": [.7, 8.0],
            "cue_duration_outlier_share_max": .05,
            "source_reading_rate_p95_max": 24,
            "target_reading_rate_p95_max": 18,
            "lines_per_language_max": 2,
            "burn_in_sample_pass_share_min": .6,
        },
        "metrics": {
            "cue_count": len(cues),
            "duration_delta_seconds": duration_delta,
            "source_reading_rate_p95": source_p95,
            "target_reading_rate_p95": target_p95,
            "duration_outlier_count": outside_duration,
            "line_failure_count": len(line_failures),
            "burn_in_sample_pass_share": burn_ratio,
        },
        "terminology": terms,
        "burn_in_samples": burn_samples,
        "line_failures": line_failures,
        "failures": failures,
        "warnings": warnings,
        "contact_sheet": str(args.contact_sheet.resolve()),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
