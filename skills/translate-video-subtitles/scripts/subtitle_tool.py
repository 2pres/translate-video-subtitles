#!/usr/bin/env python3
"""Deterministic subtitle import, lint, ASS/SRT build, render, and media QA."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unicodedata
import os


TIME_RE = re.compile(r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})")


def require_tool(name: str) -> str:
    base = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    candidates = [
        base / "tools" / "translate-video-subtitles" / "bin" / name,
        Path("/opt/homebrew/opt/ffmpeg-full/bin") / name,
        Path("/usr/local/opt/ffmpeg-full/bin") / name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    path = shutil.which(name)
    if path:
        return path
    raise RuntimeError(f"{name} is missing; run scripts/bootstrap.sh first")


def run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=capture)


def ffprobe(path: Path) -> dict:
    proc = run([
        require_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ], capture=True)
    return json.loads(proc.stdout)


def media_summary(path: Path) -> dict:
    raw = ffprobe(path)
    streams = raw.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    subtitles = [s for s in streams if s.get("codec_type") == "subtitle"]
    duration = float(raw.get("format", {}).get("duration") or (video or {}).get("duration") or 0)
    transfer = (video or {}).get("color_transfer", "")
    hdr = transfer in {"smpte2084", "arib-std-b67"}
    rotation = 0
    for side in (video or {}).get("side_data_list", []):
        if "rotation" in side:
            rotation = int(side["rotation"])
    return {
        "path": str(path.resolve()),
        "duration": duration,
        "width": (video or {}).get("width"),
        "height": (video or {}).get("height"),
        "rotation": rotation,
        "frame_rate": (video or {}).get("avg_frame_rate"),
        "video_codec": (video or {}).get("codec_name"),
        "pixel_format": (video or {}).get("pix_fmt"),
        "color_transfer": transfer or None,
        "hdr": hdr,
        "audio_streams": [
            {"index": s.get("index"), "codec": s.get("codec_name"), "language": s.get("tags", {}).get("language")}
            for s in audio
        ],
        "subtitle_streams": [
            {
                "index": s.get("index"),
                "codec": s.get("codec_name"),
                "language": s.get("tags", {}).get("language"),
                "title": s.get("tags", {}).get("title"),
                "text_usable": s.get("codec_name") not in {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"},
            }
            for s in subtitles
        ],
    }


def parse_time(value: str | float | int) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    match = TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid timestamp: {value}")
    parts = {k: int(v) for k, v in match.groupdict().items()}
    return parts["h"] * 3600 + parts["m"] * 60 + parts["s"] + parts["ms"] / 1000


def srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_time(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def parse_srt_or_vtt(text: str) -> list[dict]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    cues = []
    blocks = re.split(r"\n{2,}", text)
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or lines[0].upper() == "WEBVTT":
            continue
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = lines[timing_index].split("-->")
        start_token = timing[0].strip().replace(".", ",")
        end_token = timing[1].strip().split()[0].replace(".", ",")
        body = normalize_text(" ".join(lines[timing_index + 1:]))
        if body:
            cues.append({"id": len(cues) + 1, "start": parse_time(start_token), "end": parse_time(end_token), "source": body, "target": ""})
    return cues


def import_captions(path: Path, source_language: str | None) -> dict:
    suffix = path.suffix.lower()
    if suffix in {".srt", ".vtt"}:
        cues = parse_srt_or_vtt(path.read_text(encoding="utf-8-sig"))
        detected = None
    elif suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        detected = raw.get("language") if isinstance(raw, dict) else None
        source_cues = raw.get("cues") or raw.get("segments") if isinstance(raw, dict) else raw
        cues = []
        for item in source_cues:
            text = normalize_text(str(item.get("source") or item.get("text") or ""))
            if not text:
                continue
            cues.append({
                "id": len(cues) + 1,
                "start": parse_time(item["start"]),
                "end": parse_time(item["end"]),
                "source": text,
                "target": normalize_text(str(item.get("target") or "")),
            })
    else:
        raise ValueError("supported caption inputs are .srt, .vtt, and .json")
    if not cues:
        raise ValueError("no caption cues found")
    return {"schema_version": 1, "source_language": source_language or detected or "und", "target_language": "zh-Hans", "cues": cues}


def load_project(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw.get("cues"), list):
        raise ValueError("JSON must contain a cues array")
    for index, cue in enumerate(raw["cues"], 1):
        cue.setdefault("id", index)
        cue["start"] = parse_time(cue["start"])
        cue["end"] = parse_time(cue["end"])
        cue["source"] = normalize_text(str(cue.get("source", "")))
        cue["target"] = normalize_text(str(cue.get("target", "")))
    return raw


def display_units(text: str) -> float:
    units = 0.0
    for char in text:
        if char.isspace():
            units += 0.3
        elif unicodedata.east_asian_width(char) in {"W", "F", "A"}:
            units += 1.0
        else:
            units += 0.55
    return units


def lint_project(project: dict, require_target: bool) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    prior_end = 0.0
    for index, cue in enumerate(project["cues"], 1):
        label = f"cue {cue.get('id', index)}"
        start, end = cue["start"], cue["end"]
        duration = end - start
        if not cue["source"]:
            errors.append(f"{label}: source text is empty")
        if require_target and not cue["target"]:
            errors.append(f"{label}: target text is empty")
        if start < 0 or end <= start:
            errors.append(f"{label}: invalid timing {start:.3f}-{end:.3f}")
        if start < prior_end - 0.05:
            warnings.append(f"{label}: overlaps previous cue by {prior_end - start:.2f}s")
        if duration < 0.7:
            warnings.append(f"{label}: very short duration {duration:.2f}s")
        if duration > 8.0:
            warnings.append(f"{label}: long duration {duration:.2f}s")
        if duration > 0:
            source_rate = len(cue["source"]) / duration
            target_rate = display_units(cue["target"]) / duration
            if source_rate > 24:
                warnings.append(f"{label}: source reading rate {source_rate:.1f} chars/s")
            if cue["target"] and target_rate > 18:
                warnings.append(f"{label}: target reading rate {target_rate:.1f} units/s")
        if display_units(cue["target"]) > 52:
            warnings.append(f"{label}: target text is visually dense")
        if len(cue["source"]) > 96:
            warnings.append(f"{label}: source text is visually dense")
        prior_end = max(prior_end, end)
    return errors, warnings


def wrap_cjk(text: str, limit: int) -> str:
    if display_units(text) <= limit:
        return text
    lines, current = [], ""
    for char in text:
        if current and display_units(current + char) > limit:
            lines.append(current.strip())
            current = char
        else:
            current += char
    if current.strip():
        lines.append(current.strip())
    return r"\N".join(lines)


def wrap_latin(text: str, limit: int) -> str:
    return r"\N".join(textwrap.wrap(text, width=limit, break_long_words=False, break_on_hyphens=False))


def ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", "（").replace("}", "）")


def build_ass(project: dict, width: int, height: int, margin_bottom: int | None = None) -> str:
    short = min(width, height)
    target_size = max(24, round(short * 0.038))
    source_size = max(18, round(short * 0.028))
    outline = max(2, round(short * 0.0026))
    margin_v = margin_bottom if margin_bottom is not None else round(height * 0.07)
    target_limit = max(18, round(width / (target_size * 1.08)))
    source_limit = max(30, round(width / (source_size * 0.60)))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Bilingual,PingFang SC,{target_size},&H00F4F1EA,&H000000FF,&H90000000,&H70000000,-1,0,0,0,100,100,0,0,1,{outline},1,2,{round(width * .07)},{round(width * .07)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in project["cues"]:
        target = ass_escape(wrap_cjk(cue["target"], target_limit))
        source = ass_escape(wrap_latin(cue["source"], source_limit))
        text = (
            rf"{{\fnPingFang SC\fs{target_size}\b1\c&H00F4F1EA&}}{target}"
            rf"\N{{\fnHelvetica Neue\fs{source_size}\b0\c&H00D7D7D2&}}{source}"
        )
        lines.append(f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},Bilingual,,0,0,0,,{text}\n")
    return "".join(lines)


def build_srt(project: dict) -> str:
    blocks = []
    for index, cue in enumerate(project["cues"], 1):
        blocks.append(f"{index}\n{srt_time(cue['start'])} --> {srt_time(cue['end'])}\n{cue['target']}\n{cue['source']}\n")
    return "\n".join(blocks)


def cmd_inspect(args: argparse.Namespace) -> int:
    summary = media_summary(args.video)
    payload = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    project = import_captions(args.input, args.source_language)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(project['cues'])} cues -> {args.output}")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    project = load_project(args.input)
    errors, warnings = lint_project(project, args.require_target)
    for message in errors:
        print(f"ERROR: {message}")
    for message in warnings:
        print(f"WARN: {message}")
    print(f"{len(project['cues'])} cues, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def cmd_build(args: argparse.Namespace) -> int:
    project = load_project(args.input)
    errors, _ = lint_project(project, True)
    if errors:
        raise ValueError("cannot build: " + "; ".join(errors[:5]))
    summary = media_summary(args.video)
    if not summary["width"] or not summary["height"]:
        raise ValueError("video dimensions unavailable")
    args.ass_output.parent.mkdir(parents=True, exist_ok=True)
    args.ass_output.write_text(build_ass(project, summary["width"], summary["height"], args.margin_bottom), encoding="utf-8")
    args.srt_output.parent.mkdir(parents=True, exist_ok=True)
    args.srt_output.write_text(build_srt(project), encoding="utf-8")
    print(f"ASS: {args.ass_output}\nSRT: {args.srt_output}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    source = media_summary(args.video)
    if source["hdr"] and not args.allow_hdr:
        raise ValueError("HDR source detected. Choose a preserve-HDR workflow or pass --allow-hdr only after deciding the output treatment.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"output exists: {args.output}; choose a new path or pass --overwrite")
    ffmpeg = require_tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="subtitle-render-") as temp_dir:
        safe_ass = Path(temp_dir) / "captions.ass"
        shutil.copy2(args.ass, safe_ass)
        base = [ffmpeg, "-hide_banner", "-y", "-i", str(args.video), "-vf", f"ass=filename={safe_ass}", "-map", "0:v:0", "-map", "0:a?", "-map_metadata", "0", "-map_chapters", "0", "-sn", "-c:v", args.video_codec, "-preset", args.preset, "-crf", str(args.crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        copy_audio = base + ["-c:a", "copy", str(args.output)]
        try:
            run(copy_audio)
        except subprocess.CalledProcessError:
            if args.output.exists():
                args.output.unlink()
            print("Render with copied audio failed; retrying with AAC 192 kb/s.", file=sys.stderr)
            run(base + ["-c:a", "aac", "-b:a", "192k", str(args.output)])
    print(args.output.resolve())
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    source, output = media_summary(args.source), media_summary(args.output)
    failures = []
    if abs(source["duration"] - output["duration"]) > 0.25:
        failures.append(f"duration differs by {abs(source['duration'] - output['duration']):.3f}s")
    if (source["width"], source["height"]) != (output["width"], output["height"]):
        failures.append("resolution changed")
    if not output["audio_streams"]:
        failures.append("output has no audio")
    if not output["video_codec"]:
        failures.append("output has no video")
    report = {"source": source, "output": output, "failures": failures, "ok": not failures}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def cmd_contact_sheet(args: argparse.Namespace) -> int:
    summary = media_summary(args.video)
    duration = max(summary["duration"], 1.0)
    interval = duration / args.frames
    args.output.parent.mkdir(parents=True, exist_ok=True)
    vf = f"fps=1/{interval:.6f},scale=480:-2:force_original_aspect_ratio=decrease,tile={args.frames}x1"
    run([require_tool("ffmpeg"), "-hide_banner", "-y", "-i", str(args.video), "-vf", vf, "-frames:v", "1", "-q:v", "2", str(args.output)])
    print(args.output.resolve())
    return 0


def path_file(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file not found: {path}")
    return path.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_p = sub.add_parser("inspect")
    inspect_p.add_argument("--video", required=True, type=path_file)
    inspect_p.add_argument("--output", type=Path)
    inspect_p.set_defaults(func=cmd_inspect)

    import_p = sub.add_parser("import-captions")
    import_p.add_argument("--input", required=True, type=path_file)
    import_p.add_argument("--output", required=True, type=Path)
    import_p.add_argument("--source-language")
    import_p.set_defaults(func=cmd_import)

    lint_p = sub.add_parser("lint")
    lint_p.add_argument("--input", required=True, type=path_file)
    lint_p.add_argument("--require-target", action="store_true")
    lint_p.set_defaults(func=cmd_lint)

    build_p = sub.add_parser("build")
    build_p.add_argument("--input", required=True, type=path_file)
    build_p.add_argument("--video", required=True, type=path_file)
    build_p.add_argument("--ass-output", required=True, type=Path)
    build_p.add_argument("--srt-output", required=True, type=Path)
    build_p.add_argument("--margin-bottom", type=int)
    build_p.set_defaults(func=cmd_build)

    render_p = sub.add_parser("render")
    render_p.add_argument("--video", required=True, type=path_file)
    render_p.add_argument("--ass", required=True, type=path_file)
    render_p.add_argument("--output", required=True, type=Path)
    render_p.add_argument("--video-codec", default="libx264")
    render_p.add_argument("--preset", default="medium")
    render_p.add_argument("--crf", type=int, default=18)
    render_p.add_argument("--allow-hdr", action="store_true")
    render_p.add_argument("--overwrite", action="store_true")
    render_p.set_defaults(func=cmd_render)

    validate_p = sub.add_parser("validate")
    validate_p.add_argument("--source", required=True, type=path_file)
    validate_p.add_argument("--output", required=True, type=path_file)
    validate_p.set_defaults(func=cmd_validate)

    sheet_p = sub.add_parser("contact-sheet")
    sheet_p.add_argument("--video", required=True, type=path_file)
    sheet_p.add_argument("--output", required=True, type=Path)
    sheet_p.add_argument("--frames", type=int, default=5)
    sheet_p.set_defaults(func=cmd_contact_sheet)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (ValueError, RuntimeError, FileExistsError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
