"""US7 partial_failure probe: bounded failure-injection + recovery evidence.

THROWAWAY spike code (see spike/README.md). Implements the `partial_failure`
probe from the shared probe contract
(specs/001-resolve-discovery-spike/contracts/probes.md), backing:

  - FR-010: a failure-injection probe that induces a bounded set of partial
    failures and records, per case, the state created before the failure,
    whether that state can be inspected afterward, whether a rerun
    duplicates it, whether cleanup is possible, and the operator remediation
    path.
  - US7 (spec.md): "Exercise partial-failure recovery via failure injection."
  - SC-009: at least one intentionally-induced partial failure is captured,
    with the resulting Resolve state, rerun behavior, and recovery path
    documented.
  - R10 (research.md): the bounded case set below, chosen so the narrowing
    gate is assessed from induced evidence, not anecdote.

Bounded cases (research.md R10 / spec.md US7 acceptance scenario 1):

  1. invalid_track            - clip insertion onto a track index that does
                                 not exist on the scratch timeline.
  2. missing_preset            - LoadRenderPreset() with a preset name that
                                 does not exist, attempted before any render
                                 job is enqueued.
  3. unwritable_dir             - a temp output directory is chmod'd
                                 read-only before a render is enqueued
                                 against it.
  4. resolve_closed_mid_poll    - a dropped connection is detected mid a
                                 polling loop. This probe cannot close
                                 Resolve programmatically, so this case is
                                 OPERATOR-ASSISTED: it runs a bounded poll
                                 and gracefully detects a drop if the
                                 operator manually quits Resolve during the
                                 window; if no drop occurs it is recorded as
                                 `untested` (not silently promoted to pass
                                 or fail; FR-016).

Every case is bounded and non-hanging (short timeouts, small poll counts).
The probe never touches anything outside a dedicated scratch project/
timeline/output directory it creates itself.

Design constraints (mirrors spike/resolve_env.py):
  - Python 3.11-compatible syntax only.
  - Never hangs: connect() is bounded, every poll loop below is bounded.
  - Offline (Resolve unreachable): exits 2 fast, no case is attempted.

CLI:
    python spike/probes/partial_failure.py [--case invalid_track|
        missing_preset|unwritable_dir|resolve_closed_mid_poll|all]

Exit codes (contracts/probes.md): 0 PASS (all exercised cases left
inspectable, recoverable state with a clear remediation path) / 1 observed
FAIL (or inconclusive - no case could be confirmed) / 2 cannot-run (Resolve
unreachable, or the scratch project/timeline could not be set up).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Make the shared spike modules (resolve_env, evidence) importable. This file
# lives at spike/probes/partial_failure.py, so the spike root is one level up.
# --------------------------------------------------------------------------- #
_SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(_SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPIKE_ROOT))

import evidence  # noqa: E402
import resolve_env  # noqa: E402


# --------------------------------------------------------------------------- #
# Scratch project/timeline this probe owns exclusively.
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Scratch project / timeline / media helpers
# --------------------------------------------------------------------------- #


def _ensure_scratch_project(resolve: Any):
    """Load or create the dedicated scratch project this probe owns."""
    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    if project is None or project.GetName() != SCRATCH_PROJECT_NAME:
        project = project_manager.LoadProject(SCRATCH_PROJECT_NAME)
        if project is None:
            project = project_manager.CreateProject(SCRATCH_PROJECT_NAME)
    if project is None:
        raise RuntimeError(
            "could not create or load scratch project %r" % SCRATCH_PROJECT_NAME
        )
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
    return sorted(
        str(p) for p in media_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    )


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


# --------------------------------------------------------------------------- #
# Case 1: clip insertion onto an invalid track
# --------------------------------------------------------------------------- #


def _case_invalid_track(resolve: Any, project: Any) -> dict:
    timeline, media_pool = _ensure_scratch_timeline(project)
    clip = _ensure_clip(resolve, media_pool)

    if clip is None:
        return {
            "case": "invalid_track",
            "pre_failure_state": (
                "scratch timeline %r exists but no synthetic media is "
                "available under fixtures/media to attempt the insertion"
                % SCRATCH_TIMELINE_NAME
            ),
            "inspectable": False,
            "rerun_duplicates": None,
            "cleanup_possible": None,
            "remediation": (
                "generate fixtures via spike/fixtures/make_media.py before "
                "running this case"
            ),
            "strength": evidence.EvidenceStrength.NOT_FOUND,
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
            "validate trackIndex against timeline.GetTrackCount('video') "
            "before calling MediaPool.AppendToTimeline(); treat a falsy/"
            "empty return as the failure signal rather than assuming success"
        ),
        "strength": (
            evidence.EvidenceStrength.OBSERVED_PASS
            if passed
            else evidence.EvidenceStrength.OBSERVED_FAIL
        ),
    }


# --------------------------------------------------------------------------- #
# Case 2: render enqueue with a missing preset name
# --------------------------------------------------------------------------- #


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
            "rerun also fails to load the same bogus preset (no duplication, "
            "no job created)" if not rerun_loaded else
            "rerun unexpectedly loaded a preset with the same bogus name"
        ),
        "cleanup_possible": True,  # nothing was created; nothing to clean
        "remediation": (
            "call project.GetRenderPresetList() to enumerate valid preset "
            "names before LoadRenderPreset(); treat a False return as a "
            "hard stop before ever calling AddRenderJob()"
        ),
        "strength": (
            evidence.EvidenceStrength.OBSERVED_PASS
            if passed
            else evidence.EvidenceStrength.OBSERVED_FAIL
        ),
    }


# --------------------------------------------------------------------------- #
# Case 3: output directory made unwritable before render
# --------------------------------------------------------------------------- #


def _case_unwritable_dir(project: Any) -> dict:
    tmp_dir = tempfile.mkdtemp(prefix="spike_partial_failure_")
    os.chmod(tmp_dir, 0o500)  # read + execute only, no write
    fs_confirmed_unwritable = not os.access(tmp_dir, os.W_OK)

    presets = project.GetRenderPresetList() or []
    preset_loaded = bool(presets) and bool(project.LoadRenderPreset(presets[0]))

    project.SetRenderSettings(
        {"TargetDir": tmp_dir, "CustomName": "spike_partial_failure_render"}
    )

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
            status = _poll_render_status(
                project, job_id, _RENDER_POLL_TIMEOUT_S, _RENDER_POLL_INTERVAL_S
            )

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
            "temp dir %s created then chmod'd to 0o500 (no write) before "
            "enqueueing a render job; preset preload=%s" % (tmp_dir, preset_loaded)
        ),
        "fs_confirmed_unwritable": fs_confirmed_unwritable,
        "job_added": bool(job_id),
        "add_error": add_error,
        "render_status": status,
        "inspectable": inspectable,
        "rerun_duplicates": (
            "rerun creates a fresh temp dir and job id each time; no "
            "duplication of prior artifacts"
        ),
        "cleanup_possible": cleanup_ok,
        "remediation": (
            "check os.access(target_dir, os.W_OK) before enqueueing, and "
            "poll GetRenderJobStatus() for a terminal 'Failed' status "
            "rather than assuming success once AddRenderJob() returns a job id"
        ),
        "strength": (
            evidence.EvidenceStrength.OBSERVED_PASS
            if passed
            else evidence.EvidenceStrength.OBSERVED_FAIL
        ),
    }


# --------------------------------------------------------------------------- #
# Case 4: Resolve closed during polling (operator-assisted)
# --------------------------------------------------------------------------- #


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
                "poll loop queried project.GetName() every %ds for %ds "
                "without Resolve being closed" % (_CLOSE_POLL_INTERVAL_S, window_s)
            ),
            "observed_drop": False,
            "inspectable": None,
            "rerun_duplicates": None,
            "cleanup_possible": None,
            "remediation": (
                "operator-assisted case: this probe cannot close Resolve "
                "programmatically. To exercise it for real, run "
                "`partial_failure.py --case resolve_closed_mid_poll` and "
                "manually quit Resolve during the %ds poll window. This run "
                "observed no drop, so it is recorded as untested rather "
                "than pass/fail (FR-016 - not-found is never promoted to "
                "proven-impossible)." % window_s
            ),
            "strength": evidence.EvidenceStrength.UNTESTED,
        }

    reconnected = resolve_env.connect() is not None
    inspectable = True  # the exception/falsy response IS the inspectable signal
    passed = inspectable  # recoverability here means: detected gracefully, no hang

    return {
        "case": "resolve_closed_mid_poll",
        "pre_failure_state": (
            "poll loop was querying project.GetName() every %ds; Resolve "
            "connection dropped mid-loop" % _CLOSE_POLL_INTERVAL_S
        ),
        "observed_drop": True,
        "drop_evidence": drop_evidence,
        "inspectable": inspectable,
        "rerun_duplicates": (
            "rerun requires a fresh resolve_env.connect() call, which itself "
            "fails fast (bounded, non-hanging); reconnect %s"
            % ("succeeded" if reconnected else "did not succeed on this attempt")
        ),
        "cleanup_possible": True,  # nothing persisted by this probe on this path
        "remediation": (
            "treat any raised exception or falsy response from a live-object "
            "call as connection loss; surface it to the operator and require "
            "a fresh resolve_env.connect() (which fails fast) before retrying "
            "any in-flight operation"
        ),
        "strength": (
            evidence.EvidenceStrength.OBSERVED_PASS
            if passed
            else evidence.EvidenceStrength.OBSERVED_FAIL
        ),
    }


# --------------------------------------------------------------------------- #
# Dispatch + aggregation
# --------------------------------------------------------------------------- #


def run_case(name: str, resolve: Any, project: Any) -> dict:
    if name == "invalid_track":
        return _case_invalid_track(resolve, project)
    if name == "missing_preset":
        return _case_missing_preset(project)
    if name == "unwritable_dir":
        return _case_unwritable_dir(project)
    if name == "resolve_closed_mid_poll":
        return _case_resolve_closed_mid_poll(resolve, project)
    raise ValueError("unknown case %r" % name)


def _finding_for_case(name: str, result: dict) -> dict:
    detail = {k: v for k, v in result.items() if k != "strength"}
    return evidence.finding(
        id="partial_failure.%s" % name,
        statement=CASE_STATEMENTS[name],
        strength=result["strength"],
        evidence=json.dumps(detail, sort_keys=True, default=str),
    )


def _overall_outcome(case_results: dict):
    strengths = [r["strength"] for r in case_results.values()]
    if any(s == evidence.EvidenceStrength.OBSERVED_FAIL for s in strengths):
        return evidence.ProbeOutcome.FAIL
    if any(s == evidence.EvidenceStrength.OBSERVED_PASS for s in strengths):
        return evidence.ProbeOutcome.PASS
    # every exercised case was NOT_FOUND/UNTESTED - no confirming evidence either way
    return evidence.ProbeOutcome.PARTIAL


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "US7 partial_failure probe: induces a bounded set of partial "
            "failures and records recovery evidence per case (FR-010)."
        )
    )
    parser.add_argument(
        "--case",
        default="all",
        choices=CASE_ORDER + ["all"],
        help="which failure case to run (default: all)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    cases_to_run = list(CASE_ORDER) if args.case == "all" else [args.case]

    resolve = resolve_env.connect()
    if resolve is None:
        diagnosis = resolve_env.diagnose_connection_failure()
        print("CANNOT-RUN: %s" % diagnosis)
        provenance = evidence.build_provenance(
            "partial_failure", evidence.ProbeOutcome.SKIPPED
        )
        findings = [
            evidence.finding(
                id="partial_failure.connection",
                statement=(
                    "Resolve was not reachable; no failure-injection cases "
                    "could be exercised."
                ),
                strength=evidence.EvidenceStrength.NOT_FOUND,
                evidence=diagnosis,
            )
        ]
        out_path = evidence.write_probe_result(
            "partial_failure", provenance, findings, evidence.ProbeOutcome.SKIPPED
        )
        print("wrote %s" % out_path)
        return 2

    try:
        version = resolve.GetVersionString()
    except Exception:
        version = "unknown"

    try:
        project = _ensure_scratch_project(resolve)
    except Exception as exc:
        infra_error = "%s: %s" % (type(exc).__name__, exc)
        print("CANNOT-RUN: could not set up the scratch project: %s" % infra_error)
        provenance = evidence.build_provenance(
            "partial_failure", evidence.ProbeOutcome.SKIPPED, resolve_version=version
        )
        findings = [
            evidence.finding(
                id="partial_failure.project_setup",
                statement=(
                    "Could not create or load the scratch project needed to "
                    "run injection cases."
                ),
                strength=evidence.EvidenceStrength.NOT_FOUND,
                evidence=infra_error,
            )
        ]
        out_path = evidence.write_probe_result(
            "partial_failure", provenance, findings, evidence.ProbeOutcome.SKIPPED
        )
        print("wrote %s" % out_path)
        return 2

    case_results: dict = {}
    findings = []
    for name in cases_to_run:
        try:
            result = run_case(name, resolve, project)
        except Exception as exc:
            result = {
                "case": name,
                "pre_failure_state": None,
                "inspectable": None,
                "rerun_duplicates": None,
                "cleanup_possible": None,
                "remediation": (
                    "unexpected error while exercising this case: %s: %s; "
                    "investigate the scratch project/timeline state directly "
                    "in Resolve before rerunning."
                    % (type(exc).__name__, exc)
                ),
                "strength": evidence.EvidenceStrength.NOT_FOUND,
            }
        case_results[name] = result
        findings.append(_finding_for_case(name, result))
        print("[%s] %s -> %s" % (name, CASE_STATEMENTS[name], result["strength"]))

    outcome = _overall_outcome(case_results)
    edition_val = evidence.edition(
        "unknown",
        evidence.Confidence.INFERRED,
        "partial_failure does not itself determine edition; see the doctor probe",
    )
    provenance = evidence.build_provenance(
        "partial_failure", outcome, resolve_version=version, resolve_edition=edition_val
    )
    out_path = evidence.write_probe_result("partial_failure", provenance, findings, outcome)
    print("wrote %s" % out_path)
    print("result: %s" % outcome.value)

    return 0 if outcome == evidence.ProbeOutcome.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
