#!/usr/bin/env bash
set -euo pipefail

skill_name="translate-video-subtitles"
runtime_root="${CODEX_HOME:-${HOME}/.codex}/tools/${skill_name}"
runtime_venv="${runtime_root}/venv"

note() { printf '[%s] %s\n' "$skill_name" "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
has_ass_filter() { "$1" -hide_banner -filters 2>/dev/null | grep -Eq '(^|[[:space:]])ass[[:space:]]'; }

install_macos_packages() {
  if ! have brew; then
    note "Homebrew is missing; installing it from the official Homebrew installer."
    export NONINTERACTIVE=1
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -x /opt/homebrew/bin/brew ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
      eval "$(/usr/local/bin/brew shellenv)"
    fi
  fi
  if ! have ffmpeg || ! have ffprobe; then
    brew install ffmpeg-full
  elif ! has_ass_filter "$(command -v ffmpeg)"; then
    note "The installed FFmpeg lacks the libass subtitle renderer; installing ffmpeg-full."
    brew install ffmpeg-full
  fi
  have python3 || brew install python@3.12

  full_prefix="$(brew --prefix ffmpeg-full 2>/dev/null || true)"
  if [[ -n "$full_prefix" && -x "$full_prefix/bin/ffmpeg" ]]; then
    mkdir -p "$runtime_root/bin"
    ln -sfn "$full_prefix/bin/ffmpeg" "$runtime_root/bin/ffmpeg"
    ln -sfn "$full_prefix/bin/ffprobe" "$runtime_root/bin/ffprobe"
  fi
}

as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  elif have sudo; then
    sudo "$@"
  else
    note "A system package must be installed, but sudo is unavailable."
    exit 2
  fi
}

install_linux_packages() {
  if have apt-get; then
    as_root apt-get update
    as_root apt-get install -y ffmpeg python3 python3-venv
  elif have dnf; then
    as_root dnf install -y ffmpeg python3
  elif have pacman; then
    as_root pacman -Sy --needed --noconfirm ffmpeg python python-virtualenv
  else
    note "No supported package manager found (apt, dnf, or pacman)."
    exit 2
  fi
}

if ! have ffmpeg || ! have ffprobe || ! have python3; then
  case "$(uname -s)" in
    Darwin) install_macos_packages ;;
    Linux) install_linux_packages ;;
    *) note "Unsupported shell platform. On Windows use bootstrap.ps1."; exit 2 ;;
  esac
fi

ffmpeg_path="$(command -v ffmpeg)"
if [[ -x "$runtime_root/bin/ffmpeg" ]]; then
  ffmpeg_path="$runtime_root/bin/ffmpeg"
fi
if ! has_ass_filter "$ffmpeg_path"; then
  case "$(uname -s)" in
    Darwin) install_macos_packages; ffmpeg_path="$runtime_root/bin/ffmpeg" ;;
    Linux) note "FFmpeg is installed without the libass subtitle filter; install a full FFmpeg build and rerun."; exit 2 ;;
  esac
fi

if have whisper; then
  whisper_path="$(command -v whisper)"
  note "Using existing Whisper: ${whisper_path}"
else
  note "Installing Whisper in isolated runtime: ${runtime_venv}"
  mkdir -p "$runtime_root"
  python3 -m venv "$runtime_venv"
  "$runtime_venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$runtime_venv/bin/python" -m pip install --upgrade openai-whisper
  whisper_path="$runtime_venv/bin/whisper"
fi

note "ffmpeg: ${ffmpeg_path}"
note "ffprobe: $([[ -x "$runtime_root/bin/ffprobe" ]] && printf '%s' "$runtime_root/bin/ffprobe" || command -v ffprobe)"
note "python3: $(command -v python3)"
note "whisper: ${whisper_path}"
note "Environment ready. The selected ASR model downloads automatically on first use."
