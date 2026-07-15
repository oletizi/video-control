#!/usr/bin/env python3
"""Deterministic synthetic-media fixture generator (spike, throwaway code).

FR-012 (specs/001-resolve-discovery-spike/spec.md) requires deterministic
synthetic video and audio fixtures for import/timeline/inspection/render
probes, and explicitly forbids depending on real screen capture (macOS
Screen-Recording/TCC permission noise unrelated to Resolve feasibility).

research.md R9 selects the approach implemented here: ffmpeg lavfi sources
only (testsrc2 for video, sine for audio) with burned-in frame number and
timecode, at fixed/known resolution, fps, codec, duration, and sample rate.
No microphone, no screen, no camera, no network, no wall-clock-derived
content -- everything about the generated bitstreams is a pure function of
the constants below, so re-running this script regenerates byte-identical
media (modulo encoder/library version drift, which is outside this spike's
control) and always overwrites in place (idempotent).

Run:
    python spike/fixtures/make_media.py

Writes:
    spike/fixtures/media/fixture-video.mov
    spike/fixtures/media/fixture-tone.wav
    spike/fixtures/media/fixtures.json   (sidecar: exact specs of the above)
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# --- Known, fixed specs (the whole point is that downstream probes/manifest
#     can rely on these values rather than re-deriving them via ffprobe). ---

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30
DURATION_S = 10
VIDEO_CODEC = "prores_ks"
VIDEO_PROFILE = 2  # "standard" ProRes 422 -- widely supported by Resolve on macOS
VIDEO_PIX_FMT = "yuv422p10le"
VIDEO_FRAME_COUNT = VIDEO_FPS * DURATION_S  # 300, exact: lavfi duration * rate

AUDIO_SAMPLE_RATE = 48000
AUDIO_CHANNELS = 2
AUDIO_CODEC = "pcm_s16le"
AUDIO_BIT_DEPTH = 16
TONE_HZ = 440

# Fixed, non-wall-clock creation_time so the mov/wav container metadata does
# not vary run-to-run (ffmpeg's mov muxer otherwise stamps real UTC "now").
FIXED_CREATION_TIME = "2000-01-01T00:00:00.000000Z"

FIXTURES_DIR = Path(__file__).resolve().parent
MEDIA_DIR = FIXTURES_DIR / "media"
VIDEO_FILENAME = "fixture-video.mov"
AUDIO_FILENAME = "fixture-tone.wav"
SIDECAR_FILENAME = "fixtures.json"

# Candidate system font files for drawtext (first one found on disk wins).
# drawtext requires an explicit fontfile on ffmpeg builds without fontconfig
# default-font resolution, so we fail fast with a clear message if none of
# these exist rather than let ffmpeg fail with an opaque filter error.
FONT_CANDIDATES = [
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("/System/Library/Fonts/HelveticaNeue.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
]


def _die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def check_ffmpeg_on_path() -> str:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        _die(
            "ffmpeg not found on PATH. install ffmpeg "
            "(e.g. `brew install ffmpeg`) and re-run "
            "spike/fixtures/make_media.py."
        )
    assert ffmpeg_path is not None  # for type checkers; _die exits the process
    return ffmpeg_path


def find_drawtext_font() -> str:
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    candidates_str = "\n".join(f"  - {c}" for c in FONT_CANDIDATES)
    _die(
        "no usable font file found for ffmpeg drawtext. checked:\n"
        f"{candidates_str}\n"
        "install one of the above (this spike targets macOS) or edit "
        "FONT_CANDIDATES in spike/fixtures/make_media.py."
    )
    raise AssertionError("unreachable")  # _die exits the process


def run_ffmpeg(cmd: list[str]) -> None:
    print(f"$ {shlex.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    print(f"[exit code: {result.returncode}]")
    if result.returncode != 0:
        _die(f"ffmpeg command failed (exit {result.returncode}): {shlex.join(cmd)}")


def build_video_filter(font_file: str) -> str:
    # Two chained drawtext filters: burned-in frame number, and burned-in
    # timecode. Colons inside the timecode value must be escaped for
    # ffmpeg's own filtergraph parser (this is not shell quoting -- these
    # args are passed to subprocess as a list, with no shell involved).
    frame_num_filter = (
        f"drawtext=fontfile={font_file}"
        ":text='Frame %{frame_num}'"
        ":x=10:y=10:fontsize=36:fontcolor=white"
        ":box=1:boxcolor=black@0.6:boxborderw=6"
    )
    timecode_filter = (
        f"drawtext=fontfile={font_file}"
        r":timecode='00\:00\:00\:00'"
        f":rate={VIDEO_FPS}"
        r":text='TC\: '"
        ":x=10:y=60:fontsize=36:fontcolor=yellow"
        ":box=1:boxcolor=black@0.6:boxborderw=6"
    )
    return f"{frame_num_filter},{timecode_filter}"


def make_video(video_path: Path, font_file: str) -> None:
    video_filter = build_video_filter(font_file)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={VIDEO_WIDTH}x{VIDEO_HEIGHT}:rate={VIDEO_FPS}:duration={DURATION_S}",
        "-vf",
        video_filter,
        "-t",
        str(DURATION_S),
        "-r",
        str(VIDEO_FPS),
        "-c:v",
        VIDEO_CODEC,
        "-profile:v",
        str(VIDEO_PROFILE),
        "-pix_fmt",
        VIDEO_PIX_FMT,
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-map_metadata",
        "-1",
        "-metadata",
        f"creation_time={FIXED_CREATION_TIME}",
        "-an",
        str(video_path),
    ]
    run_ffmpeg(cmd)


def make_audio(audio_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={TONE_HZ}:sample_rate={AUDIO_SAMPLE_RATE}:duration={DURATION_S}",
        "-t",
        str(DURATION_S),
        "-ar",
        str(AUDIO_SAMPLE_RATE),
        "-ac",
        str(AUDIO_CHANNELS),
        "-c:a",
        AUDIO_CODEC,
        "-fflags",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-map_metadata",
        "-1",
        str(audio_path),
    ]
    run_ffmpeg(cmd)


def assert_nonempty(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        _die(f"expected ffmpeg to produce a non-empty file at {path}, but it did not.")


def write_sidecar(sidecar_path: Path, video_path: Path, audio_path: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generator": "spike/fixtures/make_media.py",
        "notes": (
            "All media below is synthetic, generated deterministically by "
            "ffmpeg lavfi sources (testsrc2, sine). No real screen capture, "
            "microphone, or camera input was used (FR-012)."
        ),
        "video": {
            "path": str(video_path.relative_to(FIXTURES_DIR.parent.parent)),
            "filename": video_path.name,
            "container": "mov",
            "codec": VIDEO_CODEC,
            "profile": VIDEO_PROFILE,
            "pix_fmt": VIDEO_PIX_FMT,
            "width": VIDEO_WIDTH,
            "height": VIDEO_HEIGHT,
            "fps": VIDEO_FPS,
            "duration_s": DURATION_S,
            "frame_count": VIDEO_FRAME_COUNT,
            "source_filter": "testsrc2",
            "burned_in": ["frame_num", "timecode"],
            "audio_streams": 0,
        },
        "audio": {
            "path": str(audio_path.relative_to(FIXTURES_DIR.parent.parent)),
            "filename": audio_path.name,
            "container": "wav",
            "codec": AUDIO_CODEC,
            "bit_depth": AUDIO_BIT_DEPTH,
            "sample_rate": AUDIO_SAMPLE_RATE,
            "channels": AUDIO_CHANNELS,
            "duration_s": DURATION_S,
            "tone_hz": TONE_HZ,
            "source_filter": "sine",
        },
    }
    sidecar_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    check_ffmpeg_on_path()
    font_file = find_drawtext_font()

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    video_path = MEDIA_DIR / VIDEO_FILENAME
    audio_path = MEDIA_DIR / AUDIO_FILENAME
    sidecar_path = MEDIA_DIR / SIDECAR_FILENAME

    print(f"Generating video fixture -> {video_path}")
    make_video(video_path, font_file)
    assert_nonempty(video_path)

    print(f"Generating audio fixture -> {audio_path}")
    make_audio(audio_path)
    assert_nonempty(audio_path)

    print(f"Writing sidecar spec -> {sidecar_path}")
    write_sidecar(sidecar_path, video_path, audio_path)

    print("Done.")
    print(f"  video: {video_path} ({video_path.stat().st_size} bytes)")
    print(f"  audio: {audio_path} ({audio_path.stat().st_size} bytes)")
    print(f"  sidecar: {sidecar_path}")


if __name__ == "__main__":
    main()
