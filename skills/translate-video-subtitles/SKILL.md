---
name: translate-video-subtitles
description: Professionally translate videos and deliver verified hard-subtitled MP4 files with bilingual or single-language subtitles. Use when a user provides a video or audio/video file and asks to translate it, add Chinese/English subtitles, make bilingual captions, burn subtitles into the video, correct an existing transcript, or export SRT/ASS subtitle files. Also use when the required FFmpeg, Python, or Whisper environment is missing; install the environment and continue the job.
---

# Translate Video Subtitles

Turn a supplied video into a polished translated deliverable across media inspection, timeline construction, context-aware terminology correction, translation, subtitle typesetting, rendering, and objective QA. Complete the work end to end after the user approves the subtitle appearance. The style-preview checkpoint below is a required intermediate handoff, not final delivery.

## Defaults

- Preserve the original video and create a new output.
- For English speech, produce concise Chinese above and corrected English below.
- For Chinese speech, produce concise English above and corrected Chinese below.
- For other languages, keep the corrected original below and translate into the user's conversation language above.
- Burn subtitles into an MP4. Also keep editable bilingual SRT and ASS files.
- Use clearly readable subtitles with no tall opaque box. Follow the user-approved font, size, width, weight, and placement rather than automatically choosing small text. Keep proper nouns, product names, API/SDK terms, CLI names, keyboard shortcuts, and code in their original form.
- If `/Volumes/xiabin` is mounted, place the final MP4 in `/Volumes/xiabin/Codex Final Videos`; otherwise use a `translated-video/` folder beside the source.

Ask the user to choose or approve the subtitle image preview before full-video rendering. Other questions are needed only when language, subtitle mode, or HDR handling cannot be inferred safely. An already approved style may be reused when explicitly requested, but still show a preview on the new source and await confirmation unless the user explicitly waives this checkpoint.

## Workflow

### 1. Resolve input and create a work folder

Use the actual attached/local video path. Never overwrite it. Create a temporary work folder outside the Skill directory, and record the source path, output path, and requested language.

Use a clear final name such as:

```text
<source-stem>-bilingual-zh-en.mp4
```

### 2. Bootstrap the environment

Run:

```bash
bash <skill-dir>/scripts/bootstrap.sh
```

The script checks and installs FFmpeg, ffprobe, Python, and Whisper when missing. It uses Homebrew on macOS and the detected package manager on Linux, and keeps Python ASR packages in an isolated runtime when installation is needed. On Windows, run `scripts/bootstrap.ps1` from PowerShell.

Do not merely tell the user to install dependencies. Install them, re-run the check, and continue. Tell the user before a large first-use speech-model download begins.

### 3. Inspect the source

```bash
python3 <skill-dir>/scripts/subtitle_tool.py inspect \
  --video /absolute/path/input.mp4 \
  --output /absolute/path/work/inspection.json
```

Check duration, dimensions, rotation, audio, embedded subtitle streams, and HDR status. If the source is HDR, pause for a choice between preserving HDR with a compatible workflow or producing an SDR compatibility copy; never silently flatten HDR.

Truth-source order:

```text
user-approved transcript or sidecar subtitles
> usable embedded text subtitle track
> speech recognition from the actual audio
> script or article draft used only as a terminology reference
```

Do not treat bitmap subtitle tracks as editable text.

### 3a. Preview subtitle appearance with image generation — required checkpoint

Before committing to full-video transcription/translation and full-length encoding:

1. Extract and inspect real frames with visible speech; choose a short representative sentence from the actual audio or reliable existing captions and translate it. Include a long line or a busy/light background when these affect readability. Inspect existing hard subtitles, faces, speaker labels, and platform UI to choose clear space.
2. Use the available image generation/editing tool (apply the imagegen skill when available) with the inspected source frame as a reference to create subtitle appearance previews. This is an explicit user requirement: a text-only description or an unseen ASS file is insufficient. Preserve the reference scene and aspect ratio, and request the exact bilingual text, Chinese above English, with clearly specified font appearance, size, weight, width, spacing, outline, and position. When no style is fixed, offer 2–3 clearly labeled options; for a requested adjustment, show the revised option. Reuse original English hard subtitles rather than duplicating them.
3. Show the images inline and ask which option the user wants, or whether font/size/position needs changing. **Wait for the response before encoding the full video.** While waiting, local inspection or transcript preparation may continue. Never treat silence or elapsed time as approval. If the user explicitly waives preview/approval, record that instruction and proceed.
4. Generated previews illustrate appearance; they do not reliably prove exact font metrics, character accuracy, or subtitle timing. Label them as style mockups. Map the selected look to explicit ASS/font parameters and render a real composited still with the actual subtitle engine before the full encode. Inspect glyphs, line breaks, long-line width, safe margins, and Chinese/English overlap. Show it with the mockup when possible; if the real render materially differs, show the correction and obtain approval again.
5. Save mockups, the actual rendered still, chosen parameters, and the user's approval in the project preview/records folders. Reuse those exact parameters during final rendering. If image generation is unavailable or fails, explain the limitation and ask whether an actual rendered-frame preview is acceptable; do not silently claim to have generated a mockup.

Use sizes proportional to the source dimensions. For this user's previously approved look, start with white Chinese text, Microsoft YaHei bold, horizontal scale 108%, and a restrained dark outline; adapt sizes and placement to the source instead of copying pixel values blindly. English must remain readable too. Check timing against this video's speech/existing captions; do not copy a previous video's global offset.

### 4. Acquire the source transcript

If a good SRT/VTT/Whisper JSON exists, import it:

```bash
python3 <skill-dir>/scripts/subtitle_tool.py import-captions \
  --input /absolute/path/captions.srt \
  --output /absolute/path/work/cues.json \
  --source-language en
```

For an embedded text track, extract it with FFmpeg first. If no reliable text exists, transcribe the video:

```bash
python3 <skill-dir>/scripts/transcribe.py \
  --input /absolute/path/input.mp4 \
  --output-dir /absolute/path/work/asr \
  --model turbo \
  --language en
```

Omit `--language` when genuinely unknown. Use `large-v3` or a second pass on difficult/high-value material. Pass known names through `--initial-prompt` when useful. Import the produced JSON with `import-captions`.

### 5. Correct, translate, and resegment

Read `references/quality-bar.md` before editing cues.

Build a whole-video context pack before translating individual cues:

```bash
python3 <skill-dir>/scripts/context_pack.py \
  --input /absolute/path/work/cues.json \
  --output /absolute/path/work/context-pack.md
```

Copy only the relevant entries from `references/developer-glossary.json` when the subject is AI/software, then add domain terms discovered from the full transcript, title/description, supplied scripts, slides, repository files, and authoritative product documentation. Save the result as `work/glossary.json`. Do not rely on cue-local context to guess a name. Every glossary entry must state its canonical form, known ASR confusions, whether it must remain untranslated, and the evidence source. After resolving an alias against the audio and whole-video context, set `strict_aliases: true` or remove that alias when it is a legitimate ordinary word in this video. Use `references/glossary-template.json` for the schema.

Edit `cues.json` directly. Each cue must contain `id`, numeric `start` and `end` seconds, corrected `source`, and polished `target`. Translate meaning, tone, and intent rather than word order. Listen to ambiguous regions. Use surrounding context to fix homophones and technical names.

Resegment adjacent ASR fragments into complete thoughts. Keep timing aligned to speech and avoid leaving half a sentence on one card. Split dense cues instead of shrinking the whole subtitle style. Do not invent speech during silence.

Run the lint gate:

```bash
python3 <skill-dir>/scripts/subtitle_tool.py lint \
  --input /absolute/path/work/cues.json \
  --require-target

python3 <skill-dir>/scripts/term_check.py \
  --input /absolute/path/work/cues.json \
  --glossary /absolute/path/work/glossary.json
```

Resolve every error. Review each suspected ASR alias against audio/context instead of blind replacement, then record the correction in the project glossary. Review warnings that indicate dense or awkward cards.

### 6. Build editable subtitles and render (after style approval)

```bash
python3 <skill-dir>/scripts/subtitle_tool.py build \
  --input /absolute/path/work/cues.json \
  --video /absolute/path/input.mp4 \
  --ass-output /absolute/path/output/final-name.ass \
  --srt-output /absolute/path/output/final-name.srt

python3 <skill-dir>/scripts/subtitle_tool.py render \
  --video /absolute/path/input.mp4 \
  --ass /absolute/path/output/final-name.ass \
  --output /absolute/path/final.mp4
```

Before the full render, verify the recorded style approval from step 3a and use the approved ASS/font parameters; the build script defaults are not a substitute for the approved look.

Keep the source audio unless container compatibility forces an AAC fallback. Preserve source resolution and frame cadence. Do not crop or resize merely to make captions fit.

### 7. Verify the deliverable

```bash
python3 <skill-dir>/scripts/acceptance.py \
  --source /absolute/path/input.mp4 \
  --output /absolute/path/final.mp4 \
  --cues /absolute/path/work/cues.json \
  --ass /absolute/path/output/final-name.ass \
  --glossary /absolute/path/work/glossary.json \
  --report /absolute/path/work/acceptance-report.json \
  --contact-sheet /absolute/path/work/contact-sheet.jpg
```

The command must exit `0` and the report must say `passed: true`. It measures media integrity, timing overlap, cue-duration distribution, 95th-percentile reading speed, predicted line count, terminology consistency, and whether pixels actually changed in the subtitle region at cue midpoints. It also extracts cue-aligned frames rather than arbitrary evenly spaced frames.

Inspect the contact sheet visually because glyph substitution and occlusion still require seeing the frames. Also spot-check the opening, a dense middle section, proper-name sections, scene changes, and the ending with audio. Confirm:

- final duration matches the source within 0.25 seconds;
- video and audio streams exist;
- resolution is unchanged unless requested;
- Chinese is above and original speech is below for the default English-to-Chinese flow;
- subtitles remain inside safe margins, do not cover persistent speaker labels, and have no clipping or broken glyphs;
- translation and timing remain coherent across cue boundaries.

If a check fails, fix and re-render. Export success alone is not completion.

### 8. Deliver and clean up

Give the user the final MP4 path and, when useful, the editable SRT path. Keep the original. Delete disposable extracted audio, ASR cache files, temporary frames, and partial renders only after the final MP4 is verified. Do not delete the final MP4, final SRT/ASS, or the source.

Report any uncertain name or inaudible passage honestly; never disguise ASR uncertainty as a confirmed translation.
