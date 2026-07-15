"""inspect probe (US2 / T011-T012) - structured project/timeline inspection + fixture diff.

THROWAWAY spike code (see spike/README.md). Implements:
  - T011 (FR-004): connect to a running DaVinci Resolve, walk the active
    project/timeline, and serialize project name, timeline name, per-track-type
    track counts, clips per track, markers, media pool clip list, timeline
    settings, and offline/missing media into structured JSON. Every Resolve API
    call is guarded — a method missing on this Resolve version (or a call that
    raises) is recorded as a "gap", never a crash (R4, research.md).
  - T012 (FR-007, SC-008): load the version-controlled reference fixture
    (spike/fixtures/expected_manifest.json, data-model.md ReferenceFixtureManifest)
    and automatically diff the live inspection against it — project, timeline,
    track counts, clip names per track, marker frame+name, offline media. Every
    comparison becomes a Finding (match = observed-pass, mismatch = observed-fail).
    0 unexplained differences is PASS (SC-008).

CLI contract (contracts/probes.md "inspect"):
  --fixture <path>  (default spike/fixtures/expected_manifest.json)
  --json            print the full ProbeResult JSON to stdout as well

Exit codes (shared probe contract):
  0 = PASS (0 unexplained differences)
  1 = observed FAIL (material mismatch)
  2 = CANNOT-RUN (Resolve unreachable, or the fixture could not be loaded) — fails
      fast, never hangs (FR-014).

Design constraints: Python 3.11-compatible syntax only. Never raises out to the
caller on an unreachable Resolve or a version-uneven API surface.
"""

from __future__ import annotations

import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# This file's module name ("inspect") collides with the Python STDLIB
# `inspect` module. When run as a script, Python inserts this file's own
# directory (spike/probes/) at the front of sys.path, which shadows the
# stdlib module for anything imported later in the process — including
# lazily, from inside argparse/dataclasses. Strip this file's directory from
# sys.path FIRST, before importing anything else (including argparse), so the
# real stdlib `inspect` is always the one found.
# --------------------------------------------------------------------------- #
_THIS_DIR = str(Path(__file__).resolve().parent)


def _real_path(entry: str) -> str:
    try:
        return str(Path(entry or ".").resolve())
    except OSError:
        return entry


sys.path[:] = [p for p in sys.path if _real_path(p) != _THIS_DIR]

import argparse  # noqa: E402
import json  # noqa: E402
from typing import Any, Callable, Optional  # noqa: E402

# --------------------------------------------------------------------------- #
# Make spike/ importable regardless of CWD, so `import resolve_env` and
# `import evidence` (spike/resolve_env.py, spike/evidence.py) resolve whether
# this script is invoked as `python spike/probes/inspect.py` from the repo root
# or from anywhere else. NOTE: only spike/ is added — spike/probes/ (this
# file's own directory) must stay off sys.path, per the shadowing note above.
# --------------------------------------------------------------------------- #
_SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(_SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPIKE_ROOT))

import evidence  # noqa: E402
import resolve_env  # noqa: E402
from evidence import EvidenceStrength, ProbeOutcome  # noqa: E402

PROBE_NAME = "inspect"
DEFAULT_FIXTURE = _SPIKE_ROOT / "fixtures" / "expected_manifest.json"

TRACK_TYPES = ("video", "audio", "subtitle")

# Timeline settings probed via GetSetting(key) — a version-uneven surface
# (R4), so each key is fetched independently and guarded.
TIMELINE_SETTING_KEYS = (
    "timelineFrameRate",
    "timelineResolutionWidth",
    "timelineResolutionHeight",
    "videoMonitorFormat",
)


# --------------------------------------------------------------------------- #
# Guarded API access — a missing method or a raising call is a recorded gap,
# never a crash. Resolve's scripting API is uneven across versions/editions;
# this is the mechanism that keeps the probe alive across that unevenness.
# --------------------------------------------------------------------------- #

def _safe_call(
    obj: Any,
    method_name: str,
    *args: Any,
    gaps: Optional[list[dict[str, str]]] = None,
    label: Optional[str] = None,
) -> tuple[Any, bool]:
    """Call obj.method_name(*args), guarding against absence/failure.

    Returns (value, ok). On failure, appends a gap record (dict) to `gaps` (if
    given) describing what was attempted and why it didn't work, and returns
    (None, False). Never raises.
    """
    tag = label or method_name
    if obj is None:
        if gaps is not None:
            gaps.append({"call": tag, "reason": "target object is None"})
        return None, False
    method = getattr(obj, method_name, None)
    if method is None or not callable(method):
        if gaps is not None:
            gaps.append({"call": tag, "reason": "method not present on this API version"})
        return None, False
    try:
        return method(*args), True
    except Exception as exc:  # noqa: BLE001 - version-uneven native API, must not crash the probe
        if gaps is not None:
            gaps.append({"call": tag, "reason": "%s: %s" % (type(exc).__name__, exc)})
        return None, False


def _guarded(label: str, gaps: list[dict[str, str]], fn: Callable[[], Any]) -> Any:
    """Run a zero-arg callable, guarding against any exception (e.g. unexpected
    shapes returned by an API call that itself "succeeded"). Same gap-recording
    contract as _safe_call.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        gaps.append({"call": label, "reason": "%s: %s" % (type(exc).__name__, exc)})
        return None


def _track_label(track_type: str, index: int) -> str:
    """Resolve's 1-based track index rendered V1/A1/S1-style (matches the
    fixture's `track` field, e.g. "V1", "A1")."""
    prefix = {"video": "V", "audio": "A", "subtitle": "S"}.get(track_type, track_type[:1].upper())
    return "%s%d" % (prefix, index)


# --------------------------------------------------------------------------- #
# T011 — live inspection (FR-004)
# --------------------------------------------------------------------------- #

def inspect_live(resolve: Any) -> dict[str, Any]:
    """Walk the live Resolve state and serialize project/timeline/tracks/clips/
    markers/media-pool/settings/offline-media (FR-004). Every API call is
    guarded; a missing method or unexpected shape is recorded in `gaps`, and
    the walk continues as far as it can rather than aborting.
    """
    gaps: list[dict[str, str]] = []
    result: dict[str, Any] = {
        "project": None,
        "timeline": None,
        "tracks": {},
        "clips": [],
        "markers": [],
        "media_pool_clips": [],
        "timeline_settings": {},
        "offline_media": [],
        "gaps": gaps,
    }

    project_manager, pm_ok = _safe_call(resolve, "GetProjectManager", gaps=gaps)
    project = None
    if pm_ok:
        project, _ = _safe_call(project_manager, "GetCurrentProject", gaps=gaps)

    if project is not None:
        name, _ = _safe_call(project, "GetName", gaps=gaps, label="project.GetName")
        result["project"] = name

    timeline = None
    if project is not None:
        timeline, _ = _safe_call(project, "GetCurrentTimeline", gaps=gaps)

    if timeline is not None:
        name, _ = _safe_call(timeline, "GetName", gaps=gaps, label="timeline.GetName")
        result["timeline"] = name
        _inspect_tracks(timeline, result, gaps)
        _inspect_markers(timeline, result, gaps)
        _inspect_timeline_settings(timeline, result, gaps)

    _inspect_media_pool(project, result, gaps)

    return result


def _inspect_tracks(timeline: Any, result: dict[str, Any], gaps: list[dict[str, str]]) -> None:
    for track_type in TRACK_TYPES:
        count, count_ok = _safe_call(
            timeline, "GetTrackCount", track_type, gaps=gaps,
            label="GetTrackCount(%r)" % track_type,
        )
        if not count_ok or count is None:
            continue
        result["tracks"][track_type] = count

        def _collect_track_clips(track_type: str = track_type, count: int = count) -> None:
            for i in range(1, int(count) + 1):
                items, items_ok = _safe_call(
                    timeline, "GetItemListInTrack", track_type, i, gaps=gaps,
                    label="GetItemListInTrack(%r, %d)" % (track_type, i),
                )
                if not items_ok or not items:
                    continue
                track_label = _track_label(track_type, i)
                for item in items:
                    clip_name, _ = _safe_call(
                        item, "GetName", gaps=gaps, label="timelineItem.GetName"
                    )
                    result["clips"].append({"name": clip_name, "track": track_label})

        _guarded("collect clips for track type %r" % track_type, gaps, _collect_track_clips)


def _inspect_markers(timeline: Any, result: dict[str, Any], gaps: list[dict[str, str]]) -> None:
    markers, markers_ok = _safe_call(timeline, "GetMarkers", gaps=gaps)
    if not markers_ok or not markers:
        return

    def _collect_markers() -> None:
        # GetMarkers() -> {frame_int: {"name": ..., "color": ..., ...}, ...}
        for frame, marker_info in markers.items():
            marker_name = marker_info.get("name") if isinstance(marker_info, dict) else None
            result["markers"].append({"frame": int(frame), "name": marker_name})
        result["markers"].sort(key=lambda m: m["frame"])

    _guarded("collect markers", gaps, _collect_markers)


def _inspect_timeline_settings(
    timeline: Any, result: dict[str, Any], gaps: list[dict[str, str]]
) -> None:
    for key in TIMELINE_SETTING_KEYS:
        value, ok = _safe_call(
            timeline, "GetSetting", key, gaps=gaps, label="GetSetting(%r)" % key
        )
        if ok and value not in (None, ""):
            result["timeline_settings"][key] = value


def _inspect_media_pool(project: Any, result: dict[str, Any], gaps: list[dict[str, str]]) -> None:
    if project is None:
        return
    media_pool, _ = _safe_call(project, "GetMediaPool", gaps=gaps)
    root_folder, _ = _safe_call(media_pool, "GetRootFolder", gaps=gaps)
    clip_list, clip_list_ok = _safe_call(root_folder, "GetClipList", gaps=gaps)
    if not clip_list_ok or not clip_list:
        return

    def _collect_media_pool_clips() -> None:
        for clip in clip_list:
            clip_name, _ = _safe_call(
                clip, "GetName", gaps=gaps, label="mediaPoolItem.GetName"
            )
            online_status, status_ok = _safe_call(
                clip, "GetClipProperty", "Online Status", gaps=gaps,
                label='mediaPoolItem.GetClipProperty("Online Status")',
            )
            result["media_pool_clips"].append(
                {"name": clip_name, "online_status": online_status if status_ok else None}
            )
            is_offline = (
                status_ok
                and isinstance(online_status, str)
                and online_status.strip().lower() not in ("", "online")
            )
            if is_offline and clip_name:
                result["offline_media"].append(clip_name)

    _guarded("collect media pool clips", gaps, _collect_media_pool_clips)


# --------------------------------------------------------------------------- #
# T012 — fixture diff (FR-007, SC-008)
# --------------------------------------------------------------------------- #

def _load_fixture(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def diff_against_fixture(live: dict[str, Any], fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare the live inspection against the ReferenceFixtureManifest
    (data-model.md). Returns a flat list of per-field comparisons, each with a
    `match` boolean. Every comparison — match or mismatch — becomes a Finding;
    a mismatch here is by definition "unexplained" (the fixture is the sole
    authority for this controlled scenario), so 0 mismatches is SC-008 PASS.
    """
    diffs: list[dict[str, Any]] = []

    def _check(field: str, expected: Any, actual: Any) -> None:
        diffs.append({"field": field, "expected": expected, "actual": actual, "match": expected == actual})

    _check("project", fixture.get("project"), live.get("project"))
    _check("timeline", fixture.get("timeline"), live.get("timeline"))

    expected_tracks = fixture.get("tracks", {})
    live_tracks = live.get("tracks", {})
    for track_type in sorted(set(expected_tracks) | set(live_tracks)):
        _check(
            "tracks.%s" % track_type,
            expected_tracks.get(track_type),
            live_tracks.get(track_type),
        )

    expected_clips = {(c["name"], c["track"]) for c in fixture.get("clips", [])}
    live_clips = {(c["name"], c["track"]) for c in live.get("clips", [])}
    for name, track in sorted(expected_clips - live_clips):
        _check("clips[%s@%s]" % (name, track), "present", "missing")
    for name, track in sorted(live_clips - expected_clips):
        _check("clips[%s@%s]" % (name, track), "not-expected", "present")

    expected_markers = {(m["frame"], m["name"]) for m in fixture.get("markers", [])}
    live_markers = {(m["frame"], m["name"]) for m in live.get("markers", [])}
    for frame, name in sorted(expected_markers - live_markers):
        _check("markers[%s@%s]" % (name, frame), "present", "missing")
    for frame, name in sorted(live_markers - expected_markers):
        _check("markers[%s@%s]" % (name, frame), "not-expected", "present")

    expected_offline = set(fixture.get("offline_media", []))
    live_offline = set(live.get("offline_media", []))
    for name in sorted(expected_offline - live_offline):
        _check("offline_media[%s]" % name, "offline", "not-offline-or-missing")
    for name in sorted(live_offline - expected_offline):
        _check("offline_media[%s]" % name, "not-expected-offline", "offline")

    return diffs


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inspect",
        description=(
            "US2: serialize the active Resolve project/timeline (FR-004) and "
            "diff it against a version-controlled reference fixture (FR-007, SC-008)."
        ),
    )
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE),
        help="path to the expected-manifest fixture JSON (default: %(default)s)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="also print the full ProbeResult JSON to stdout",
    )
    return parser


def _cannot_run(reason: str, resolve_version: str = "unknown") -> int:
    """Write a SKIPPED ProbeResult and print a CANNOT-RUN diagnosis. Exit 2."""
    provenance = evidence.build_provenance(
        probe=PROBE_NAME,
        result=ProbeOutcome.SKIPPED,
        resolve_version=resolve_version,
    )
    findings = [
        evidence.finding(
            id="inspect.cannot_run",
            statement="inspect probe could not run",
            strength=EvidenceStrength.OBSERVED_FAIL,
            evidence=reason,
        )
    ]
    out_path = evidence.write_probe_result(PROBE_NAME, provenance, findings, ProbeOutcome.SKIPPED)
    print("CANNOT-RUN: %s" % reason)
    print("wrote %s" % out_path)
    return 2


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    fixture_path = Path(args.fixture)

    # Fail fast, never hang (FR-014): resolve_env.connect() itself is bounded
    # by an internal timeout and never raises.
    resolve = resolve_env.connect()
    if resolve is None:
        return _cannot_run(resolve_env.diagnose_connection_failure())

    version, _ = _safe_call(resolve, "GetVersionString")
    resolve_version = version or "unknown"

    try:
        fixture = _load_fixture(fixture_path)
    except (OSError, json.JSONDecodeError) as exc:
        return _cannot_run(
            "could not load fixture %s: %s: %s" % (fixture_path, type(exc).__name__, exc),
            resolve_version=resolve_version,
        )

    live = inspect_live(resolve)
    diffs = diff_against_fixture(live, fixture)
    unexplained = [d for d in diffs if not d["match"]]

    findings: list[dict[str, Any]] = []
    for gap in live["gaps"]:
        findings.append(
            evidence.finding(
                id="inspect.gap.%s" % gap["call"],
                statement="API call unavailable/failed during inspection: %s" % gap["call"],
                strength=EvidenceStrength.NOT_FOUND,
                evidence=gap["reason"],
            )
        )
    for d in diffs:
        strength = EvidenceStrength.OBSERVED_PASS if d["match"] else EvidenceStrength.OBSERVED_FAIL
        findings.append(
            evidence.finding(
                id="inspect.diff.%s" % d["field"],
                statement="fixture field %r: expected=%r actual=%r" % (d["field"], d["expected"], d["actual"]),
                strength=strength,
                evidence="live inspection vs fixture %s" % fixture_path,
            )
        )

    outcome = ProbeOutcome.PASS if not unexplained else ProbeOutcome.FAIL
    provenance = evidence.build_provenance(
        probe=PROBE_NAME,
        result=outcome,
        resolve_version=resolve_version,
    )
    out_path = evidence.write_probe_result(PROBE_NAME, provenance, findings, outcome)
    probe_result = evidence.build_probe_result(provenance, findings, outcome)

    print("project: %s" % live["project"])
    print("timeline: %s" % live["timeline"])
    print("tracks: %s" % live["tracks"])
    print("clips: %d found" % len(live["clips"]))
    print("markers: %d found" % len(live["markers"]))
    print("media pool clips: %d found" % len(live["media_pool_clips"]))
    print("offline media: %s" % live["offline_media"])
    print("gaps recorded: %d" % len(live["gaps"]))
    print("diff: %d checks, %d unexplained differences" % (len(diffs), len(unexplained)))
    for d in unexplained:
        print("  MISMATCH %s: expected=%r actual=%r" % (d["field"], d["expected"], d["actual"]))
    if unexplained:
        print("RESULT: FAIL (SC-008 not met — %d unexplained differences)" % len(unexplained))
    else:
        print("RESULT: PASS (0 unexplained differences, SC-008 met)")
    print("wrote %s" % out_path)

    if args.json:
        print(json.dumps(probe_result, indent=2))

    return 0 if outcome == ProbeOutcome.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
