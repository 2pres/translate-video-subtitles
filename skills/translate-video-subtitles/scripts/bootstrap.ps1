$ErrorActionPreference = "Stop"
$SkillName = "translate-video-subtitles"

function Has-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

if (-not (Has-Command "winget")) {
    throw "winget is required for automatic Windows setup. Install App Installer, then rerun this script."
}
if (-not (Has-Command "ffmpeg") -or -not (Has-Command "ffprobe")) {
    winget install --id Gyan.FFmpeg --exact --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
if (-not (Has-Command "python")) {
    winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

$RuntimeRoot = Join-Path $env:USERPROFILE ".codex\tools\$SkillName"
$RuntimeVenv = Join-Path $RuntimeRoot "venv"
if (-not (Has-Command "whisper")) {
    New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
    python -m venv $RuntimeVenv
    & "$RuntimeVenv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
    & "$RuntimeVenv\Scripts\python.exe" -m pip install --upgrade openai-whisper
}

if (Has-Command "ffmpeg") {
    $Filters = ffmpeg -hide_banner -filters 2>&1 | Out-String
    if ($Filters -notmatch "\sass\s") {
        throw "The active FFmpeg build lacks the libass subtitle filter. Reinstall the full Gyan.FFmpeg package, open a new terminal, and rerun."
    }
}

Write-Host "[$SkillName] Environment ready. Open a new terminal if winget changed PATH."
