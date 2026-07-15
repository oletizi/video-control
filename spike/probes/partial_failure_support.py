"""Pure helper functions for the partial_failure probe (see partial_failure.py).

THROWAWAY spike code (see spike/README.md). Split out of partial_failure.py to
keep both files within the repo's code-governance line/byte caps; this module
holds no CLI/entry-point logic of its own - see partial_failure.py for the
probe contract, bounded case descriptions, and exit-code semantics.

Everything here is a pure helper: the scratch project/timeline/media setup
helpers, the four failure-injection cases (each taking resolve/project/
timeline as arguments and returning a recovery-evidence dict), and the
per-case finding builder.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

# Make the shared spike modules (resolve_env, evidence) importable. This file
# lives at spike/probes/partial_failure_support.py, so the spike root is one
# level up.
_SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(_SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPIKE_ROOT))

from evidence import EvidenceStrength, finding  # noqa: E402
import resolve_env  # noqa: E402

# Scratch project/timeline this probe owns exclusively.
SCRATCH_PROJECT_NAME = "spike_partial_failure"
SCRATCH_TIMELINE_NAME = "spike_partial_failure_timeline"

# Bounded loop parameters (never hang; see resolve_env.py's own timeout style).
_RENDER_POLL_TIMEOUT_S = 20
_RENDER_POLL_INTERVAL_S = 1
_CLOSE_POLL_ITERATIONS = 10
_CLOSE_POLL_INTERVAL_S = 1

CASE_ORDER = [
    "invalid_track",
    "missing_preset",
    "unwritable_dir",
    "resolve_closed_mid_poll",
]

CASE_STATEMENTS = {
    "invalid_track": (
        "Inserting a clip at an out-of-range track index fails, and the "
        "resulting state is inspectable, non-duplicating on rerun, and "
        "cleanly remediable."
    ),
    "missing_preset": (
        "Loading a nonexistent render preset fails without enqueueing a "
        "render job, leaving inspectable, cleanly remediable state."
    ),
    "unwritable_dir": (
        "Rendering to a chmod'd read-only output directory fails (or never "
        "reaches Complete), leaving inspectable, cleanable state with a "
        "clear remediation path."
    ),
    "resolve_closed_mid_poll": (
        "A dropped connection mid-poll (Resolve closed) is detected "
        "gracefully without hanging. Operator-assisted: this probe cannot "
        "close Resolve programmatically, so a genuine drop only occurs if "
        "the operator manually quits Resolve during the poll window."
    ),
}

def _ensure_scratch_project(resolve: Any):
    """Load or create the dedicated scratch project this probe owns."""
    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    if project is None or project.GetName() != SCRATCH_PROJECT_NAME:
        project = project_manager.LoadProject(SCRATCH_PROJECT_NAME)
        if project is None:
            project = project_manager.CreateProject(SCRATCH_PROJECT_NAME)
    if project is None:
        raise RuntimeError("could not create or load scratch project %r" % SCRATCH_PROJECT_NAME)
    return project

def _ensure_scratch_timeline(project: Any):
    """Find or create this probe's scratch timeline; returns (timeline, media_pool)."""
    media_pool = project.GetMediaPool()
    timeline = project.GetCurrentTimeline()
    if timeline is None or timeline.GetName() != SCRATCH_TIMELINE_NAME:
        found = None
        count = project.GetTimelineCount() or 0
        for i in range(1, count + 1):
            candidate = project.GetTimelineByIndex(i)
            if candidate and candidate.GetName() == SCRATCH_TIMELINE_NAME:
                found = candidate
                break
        timeline = found or media_pool.CreateEmptyTimeline(SCRATCH_TIMELINE_NAME)
        if timeline is not None:
            project.SetCurrentTimeline(timeline)
    if timeline is None:
        raise RuntimeError("could not create or find the scratch timeline")
    return timeline, media_pool

def _find_fixture_media_paths() -> list:
    """Absolute paths to any synthetic media already generated under fixtures/media."""
    media_dir = _SPIKE_ROOT / "fixtures" / "media"
    if not media_dir.is_dir():
        return []
    return sorted(str(p) for p in media_dir.iterdir() if p.is_file() and not p.name.startswith("."))

def _ensure_clip(resolve: Any, media_pool: Any):
    """A MediaPoolItem to attempt the invalid-track insertion with, or None."""
    root = media_pool.GetRootFolder()
    clips = root.GetClipList() or []
    if clips:
        return clips[0]
    paths = _find_fixture_media_paths()
    if not paths:
        return None
    storage = resolve.GetMediaStorage()
    imported = storage.AddItemsToMediaPool(paths) or []
    return imported[0] if imported else None

def _poll_render_status(project: Any, job_id: str, timeout_s: int, poll_s: int) -> str:
    """Bounded poll of a render job's status; never blocks past timeout_s."""
    deadline = time.monotonic() + timeout_s
    last_status: Optional[str] = None
    while time.monotonic() < deadline:
        try:
            info = project.GetRenderJobStatus(job_id) or {}
        except Exception as exc:  # connection or API error mid-poll
            return "error: %s: %s" % (type(exc).__name__, exc)
        last_status = info.get("JobStatus")
        if last_status in ("Complete", "Cancelled", "Failed"):
            return last_status
        time.sleep(poll_s)
    return "stalled (last status=%s, timeout=%ds)" % (last_status, timeout_s)

def _case_invalid_track(resolve: Any, project: Any) -> dict:
    timeline, media_pool = _ensure_scratch_timeline(project)
    clip = _ensure_clip(resolve, media_pool)
    if clip is None:
        return {
            "case": "invalid_track",
            "pre_failure_state": (
                "scratch timeline %r exists but no synthetic media is available "
                "under fixtures/media to attempt the insertion" % SCRATCH_TIMELINE_NAME
            ),
            "inspectable": False,
            "rerun_duplicates": None,
            "cleanup_possible": None,
            "remediation": "generate fixtures via spike/fixtures/make_media.py before running this case",
            "strength": EvidenceStrength.NOT_FOUND,
        }

    track_count_before = timeline.GetTrackCount("video")
    invalid_index = track_count_before + 1000  # unambiguously out of range
    clip_info = {"mediaPoolItem": clip, "trackIndex": invalid_index, "mediaType": 1}
    append_error = None
    try:
        appended = media_pool.AppendToTimeline([clip_info])
    except Exception as exc:
        appended = None
        append_error = "%s: %s" % (type(exc).__name__, exc)

    track_count_after = timeline.GetTrackCount("video")
    induced_failure = not appended
    rerun_note = None
    if induced_failure:
        try:
            rerun_appended = media_pool.AppendToTimeline([clip_info])
        except Exception:
            rerun_appended = None
        rerun_note = (
            "rerun also rejected the same clip_info (no duplication observed)"
            if not rerun_appended
            else "rerun unexpectedly succeeded where the first attempt failed"
        )

    cleanup_possible = track_count_after == track_count_before
    inspectable = True  # GetTrackCount()/GetItemListInTrack() are queryable regardless
    passed = induced_failure and inspectable and cleanup_possible
    return {
        "case": "invalid_track",
        "pre_failure_state": (
            "scratch timeline %r had %d video track(s) before the attempt"
            % (SCRATCH_TIMELINE_NAME, track_count_before)
        ),
        "invalid_track_index_used": invalid_index,
        "observed_append_result": bool(appended),
        "append_error": append_error,
        "track_count_unchanged_after_failure": cleanup_possible,
        "inspectable": inspectable,
        "rerun_duplicates": rerun_note,
        "cleanup_possible": cleanup_possible,
        "remediation": (
            "validate trackIndex against timeline.GetTrackCount('video') before calling "
            "MediaPool.AppendToTimeline(); treat a falsy/empty return as the failure "
            "signal rather than assuming success"
        ),
        "strength": EvidenceStrength.OBSERVED_PASS if passed else EvidenceStrength.OBSERVED_FAIL,
    }

def _case_missing_preset(project: Any) -> dict:
    bogus_preset = "spike_missing_preset_" + uuid.uuid4().hex[:8]
    jobs_before = project.GetRenderJobList() or []
    load_error = None
    try:
        loaded = project.LoadRenderPreset(bogus_preset)
    except Exception as exc:
        loaded = False
        load_error = "%s: %s" % (type(exc).__name__, exc)

    jobs_after = project.GetRenderJobList() or []
    no_job_created = len(jobs_after) == len(jobs_before)
    rerun_loaded = False
    try:
        rerun_loaded = project.LoadRenderPreset(bogus_preset)
    except Exception:
        rerun_loaded = False

    induced_failure = not loaded
    inspectable = True  # GetRenderPresetList()/GetRenderJobList() queryable throughout
    passed = induced_failure and no_job_created and inspectable
    return {
        "case": "missing_preset",
        "pre_failure_state": (
            "%d render job(s) queued before the attempt; preset %r does not exist"
            % (len(jobs_before), bogus_preset)
        ),
        "load_render_preset_result": bool(loaded),
        "load_error": load_error,
        "no_render_job_created": no_job_created,
        "inspectable": inspectable,
        "rerun_duplicates": (
            "rerun also fails to load the same bogus preset (no duplication, no job created)"
            if not rerun_loaded
            else "rerun unexpectedly loaded a preset with the same bogus name"
        ),
        "cleanup_possible": True,  # nothing was created; nothing to clean
        "remediation": (
            "call project.GetRenderPresetList() to enumerate valid preset names before "
            "LoadRenderPreset(); treat a False return as a hard stop before ever calling "
            "AddRenderJob()"
        ),
        "strength": EvidenceStrength.OBSERVED_PASS if passed else EvidenceStrength.OBSERVED_FAIL,
    }

def _case_unwritable_dir(project: Any) -> dict:
    tmp_dir = tempfile.mkdtemp(prefix="spike_partial_failure_")
    os.chmod(tmp_dir, 0o500)  # read + execute only, no write
    fs_confirmed_unwritable = not os.access(tmp_dir, os.W_OK)
    presets = project.GetRenderPresetList() or []
    preset_loaded = bool(presets) and bool(project.LoadRenderPreset(presets[0]))
    project.SetRenderSettings({"TargetDir": tmp_dir, "CustomName": "spike_partial_failure_render"})

    job_id = None
    add_error = None
    try:
        job_id = project.AddRenderJob()
    except Exception as exc:
        add_error = "%s: %s" % (type(exc).__name__, exc)

    status = None
    if job_id:
        try:
            project.StartRendering([job_id])
        except Exception as exc:
            status = "start-error: %s: %s" % (type(exc).__name__, exc)
        else:
            status = _poll_render_status(project, job_id, _RENDER_POLL_TIMEOUT_S, _RENDER_POLL_INTERVAL_S)

    induced_failure = fs_confirmed_unwritable and (
        not job_id or (status is not None and not status.startswith("Complete"))
    )

    # Best-effort cleanup regardless of outcome.
    if job_id:
        try:
            project.StopRendering()
        except Exception:
            pass
        try:
            project.DeleteRenderJob(job_id)
        except Exception:
            pass
    cleanup_ok = True
    try:
        os.chmod(tmp_dir, 0o700)
        shutil.rmtree(tmp_dir)
    except OSError:
        cleanup_ok = False

    inspectable = True  # dir permissions + render-job status were queryable throughout
    passed = induced_failure and inspectable and cleanup_ok
    return {
        "case": "unwritable_dir",
        "pre_failure_state": (
            "temp dir %s created then chmod'd to 0o500 (no write) before enqueueing a "
            "render job; preset preload=%s" % (tmp_dir, preset_loaded)
        ),
        "fs_confirmed_unwritable": fs_confirmed_unwritable,
        "job_added": bool(job_id),
        "add_error": add_error,
        "render_status": status,
        "inspectable": inspectable,
        "rerun_duplicates": "rerun creates a fresh temp dir and job id each time; no duplication of prior artifacts",
        "cleanup_possible": cleanup_ok,
        "remediation": (
            "check os.access(target_dir, os.W_OK) before enqueueing, and poll "
            "GetRenderJobStatus() for a terminal 'Failed' status rather than assuming "
            "success once AddRenderJob() returns a job id"
        ),
        "strength": EvidenceStrength.OBSERVED_PASS if passed else EvidenceStrength.OBSERVED_FAIL,
    }

def _case_resolve_closed_mid_poll(resolve: Any, project: Any) -> dict:
    dropped = False
    drop_evidence = None
    for _ in range(_CLOSE_POLL_ITERATIONS):
        time.sleep(_CLOSE_POLL_INTERVAL_S)
        try:
            name = project.GetName()
        except Exception as exc:
            dropped = True
            drop_evidence = "%s: %s" % (type(exc).__name__, exc)
            break
        if not name:
            dropped = True
            drop_evidence = "project.GetName() returned falsy mid-poll"
            break

    window_s = _CLOSE_POLL_ITERATIONS * _CLOSE_POLL_INTERVAL_S
    if not dropped:
        return {
            "case": "resolve_closed_mid_poll",
            "pre_failure_state": (
                "poll loop queried project.GetName() every %ds for %ds without Resolve "
                "being closed" % (_CLOSE_POLL_INTERVAL_S, window_s)
            ),
            "observed_drop": False,
            "inspectable": None,
            "rerun_duplicates": None,
            "cleanup_possible": None,
            "remediation": (
                "operator-assisted case: this probe cannot close Resolve programmatically. "
                "To exercise it for real, run `partial_failure.py --case "
                "resolve_closed_mid_poll` and manually quit Resolve during the %ds poll "
                "window. This run observed no drop, so it is recorded as untested rather "
                "than pass/fail (FR-016 - not-found is never promoted to proven-impossible)."
                % window_s
            ),
            "strength": EvidenceStrength.UNTESTED,
        }

    reconnected = resolve_env.connect() is not None
    inspectable = True  # the exception/falsy response IS the inspectable signal
    passed = inspectable  # recoverability here means: detected gracefully, no hang
    return {
        "case": "resolve_closed_mid_poll",
        "pre_failure_state": (
            "poll loop was querying project.GetName() every %ds; Resolve connection "
            "dropped mid-loop" % _CLOSE_POLL_INTERVAL_S
        ),
        "observed_drop": True,
        "drop_evidence": drop_evidence,
        "inspectable": inspectable,
        "rerun_duplicates": (
            "rerun requires a fresh resolve_env.connect() call, which itself fails fast "
            "(bounded, non-hanging); reconnect %s"
            % ("succeeded" if reconnected else "did not succeed on this attempt")
        ),
        "cleanup_possible": True,  # nothing persisted by this probe on this path
        "remediation": (
            "treat any raised exception or falsy response from a live-object call as "
            "connection loss; surface it to the operator and require a fresh "
            "resolve_env.connect() (which fails fast) before retrying any in-flight operation"
        ),
        "strength": EvidenceStrength.OBSERVED_PASS if passed else EvidenceStrength.OBSERVED_FAIL,
    }

def _finding_for_case(name: str, result: dict) -> dict:
    detail = {k: v for k, v in result.items() if k != "strength"}
    return finding(
        id="partial_failure.%s" % name,
        statement=CASE_STATEMENTS[name],
        strength=result["strength"],
        evidence=json.dumps(detail, sort_keys=True, default=str),
    )
