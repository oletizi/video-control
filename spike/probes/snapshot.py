"""snapshot probe (US6) — reversibility via project export vs timeline duplication.

THROWAWAY spike code (see spike/README.md). Implements the `snapshot` section of
specs/001-resolve-discovery-spike/contracts/probes.md and research.md R8 (FR-009):

  (a) export:    ProjectManager.ExportProject(name, path) captures a pre-mutation
                 snapshot; the live timeline is then mutated; the exported snapshot
                 is re-opened (ImportProject + LoadProject) as a SEPARATE temp
                 project (never destroying the operator's live project) and
                 inspected to see whether it reflects the pre-mutation state.
  (b) duplicate: timeline.DuplicateTimeline(name) is taken; the ORIGINAL timeline is
                 mutated; the duplicate is re-inspected to confirm it still reflects
                 the pre-mutation state (mutation did not leak into the duplicate).

Rollback support is a narrowing gate (not a hard gate): if neither approach
reliably reverts a mutation, this probe evaluates "generated-timeline
replacement" (always creating a fresh output timeline instead of restoring one)
as a fallback and records that evaluation as a Finding.

Every Resolve API call is guarded (version variance across Resolve releases is
expected) — a missing/failing method is recorded as a gap finding, never a crash.

Python 3.11-compatible syntax ONLY. Talks to a LIVE app that may not be running;
degrades gracefully (never hangs, never raises out to the caller) per FR-014.

CLI:
    python spike/probes/snapshot.py --mode export|duplicate|both

Exit codes (contracts/probes.md):
    0 = PASS       (reliable rollback OR viable generated-timeline replacement)
    1 = FAIL       (observed: no reliable rollback and no viable fallback)
    2 = CANNOT-RUN (Resolve unreachable / no working project context)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import uuid
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Make spike/ importable (this file lives at spike/probes/snapshot.py).
# --------------------------------------------------------------------------- #
_SPIKE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SPIKE_ROOT not in sys.path:
    sys.path.insert(0, _SPIKE_ROOT)

import resolve_env  # noqa: E402
from evidence import (  # noqa: E402
    EvidenceStrength,
    ProbeOutcome,
    build_provenance,
    finding,
    write_probe_result,
)

PROBE_NAME = "snapshot"


# --------------------------------------------------------------------------- #
# Guarded call helper — every Resolve API call goes through this so a missing
# method / version-variance failure is recorded as a gap, never a crash.
# --------------------------------------------------------------------------- #

def _safe(label: str, fn: Any, *args: Any, **kwargs: Any) -> tuple[bool, Any]:
    """Call ``fn(*args, **kwargs)``; return (True, result) or (False, err_str).

    Catches every Exception (AttributeError included, for methods absent in a
    given Resolve version) so a single guarded call can never crash the probe.
    """
    try:
        return True, fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — deliberate: any failure is a gap
        return False, "%s: %s" % (type(exc).__name__, exc)


def _marker_present(markers: Any, token: str) -> bool:
    """True if any marker in a GetMarkers()-shaped dict carries ``token``."""
    if not markers:
        return False
    try:
        entries = markers.values()
    except AttributeError:
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        note = str(entry.get("note", ""))
        custom = str(entry.get("customData", ""))
        if token in note or token in custom:
            return True
    return False


def _add_probe_marker(timeline: Any, frame_id: int, token: str) -> bool:
    """Add a distinctively-tagged marker to ``timeline``; True on success.

    Tries the full AddMarker signature (with customData) first, then falls
    back to the shorter signature some Resolve versions expose — guarding
    against API version variance rather than crashing.
    """
    note = "snapshot probe reversibility mutation %s" % token
    ok, result = _safe(
        "AddMarker(customData)",
        timeline.AddMarker,
        frame_id,
        "Blue",
        "snapshot_probe",
        note,
        1,
        token,
    )
    if ok and result:
        return True
    ok2, result2 = _safe(
        "AddMarker(no customData)",
        timeline.AddMarker,
        frame_id,
        "Blue",
        "snapshot_probe",
        note,
        1,
    )
    return bool(ok2 and result2)


def _pick_frame_id(timeline: Any) -> int:
    ok, start = _safe("GetStartFrame", timeline.GetStartFrame)
    if ok and isinstance(start, int):
        return start
    return 0


def _cleanup_marker(timeline: Any, frame_id: int) -> None:
    """Best-effort removal of a probe-added marker so reruns stay idempotent."""
    _safe("DeleteMarkerAtFrame", timeline.DeleteMarkerAtFrame, frame_id)


# --------------------------------------------------------------------------- #
# (a) export/import reversibility
# --------------------------------------------------------------------------- #

def run_export_mode(
    project_manager: Any,
    project: Any,
    timeline: Any,
    findings: list[dict[str, Any]],
) -> Optional[bool]:
    """Test project-export reversibility. Returns True/False/None (gap).

    Never destroys or mutates the operator's live project database entry: the
    export is re-opened as a SEPARATELY NAMED temp project, inspected, then
    deleted. Only the live TIMELINE gets a throwaway marker (cleaned up after).
    """
    token = "snapshot_probe_export_" + uuid.uuid4().hex[:8]
    project_name_ok, project_name = _safe("GetName(project)", project.GetName)
    if not project_name_ok or not project_name:
        findings.append(
            finding(
                "snapshot.export.project_name",
                "Could not read the current project's name; export mode cannot proceed.",
                EvidenceStrength.UNTESTED,
                str(project_name),
            )
        )
        return None

    tmp_dir = tempfile.mkdtemp(prefix="snapshot_probe_")
    export_path = os.path.join(tmp_dir, "%s.drp" % project_name)
    import_name = "%s_snapshot_probe_restore" % project_name
    frame_id = _pick_frame_id(timeline)
    reliable: Optional[bool] = None

    try:
        exported_ok, exported_result = _safe(
            "ExportProject", project_manager.ExportProject, project_name, export_path
        )
        if not exported_ok or exported_result is False:
            findings.append(
                finding(
                    "snapshot.export.export_call",
                    "ExportProject is unavailable or failed in this Resolve version.",
                    EvidenceStrength.UNTESTED,
                    str(exported_result),
                )
            )
            return None

        findings.append(
            finding(
                "snapshot.export.export_call",
                "ExportProject('%s', <tmp path>) succeeded." % project_name,
                EvidenceStrength.OBSERVED_PASS,
                export_path,
            )
        )

        mutated = _add_probe_marker(timeline, frame_id, token)
        if not mutated:
            findings.append(
                finding(
                    "snapshot.export.mutate",
                    "Could not add a probe marker to the live timeline; "
                    "export-restore reversibility cannot be tested.",
                    EvidenceStrength.UNTESTED,
                    "AddMarker failed at frame %d" % frame_id,
                )
            )
            return None
        findings.append(
            finding(
                "snapshot.export.mutate",
                "Mutated the live timeline (added marker token %s) after the export." % token,
                EvidenceStrength.OBSERVED_PASS,
                "frame=%d" % frame_id,
            )
        )

        # Best-effort idempotency: drop any stale temp project from a prior run.
        _safe("DeleteProject(stale)", project_manager.DeleteProject, import_name)

        imported_ok, imported_result = _safe(
            "ImportProject", project_manager.ImportProject, export_path, import_name
        )
        if not imported_ok or imported_result is False:
            findings.append(
                finding(
                    "snapshot.export.restore_call",
                    "Export succeeded but ImportProject (the restore path) failed.",
                    EvidenceStrength.OBSERVED_FAIL,
                    str(imported_result),
                )
            )
            return False

        loaded_ok, loaded_project = _safe(
            "LoadProject(import)", project_manager.LoadProject, import_name
        )
        if not loaded_ok or loaded_project is None:
            findings.append(
                finding(
                    "snapshot.export.restore_load",
                    "ImportProject reported success but the imported project "
                    "could not be loaded/inspected.",
                    EvidenceStrength.OBSERVED_FAIL,
                    str(loaded_project),
                )
            )
            return False

        tl_ok, restored_timeline = _safe(
            "GetCurrentTimeline(restored)", loaded_project.GetCurrentTimeline
        )
        if not tl_ok or restored_timeline is None:
            findings.append(
                finding(
                    "snapshot.export.restore_timeline",
                    "Imported project loaded but its timeline could not be read.",
                    EvidenceStrength.UNTESTED,
                    str(restored_timeline),
                )
            )
            reliable = None
        else:
            markers_ok, markers_after = _safe(
                "GetMarkers(restored)", restored_timeline.GetMarkers
            )
            if not markers_ok:
                findings.append(
                    finding(
                        "snapshot.export.restore_check",
                        "Could not read markers on the restored/imported timeline.",
                        EvidenceStrength.UNTESTED,
                        str(markers_after),
                    )
                )
                reliable = None
            else:
                reverted = not _marker_present(markers_after, token)
                reliable = reverted
                findings.append(
                    finding(
                        "snapshot.export.reversibility",
                        "Export-then-restore %s the post-export mutation."
                        % ("reverted" if reverted else "did NOT revert"),
                        EvidenceStrength.OBSERVED_PASS
                        if reverted
                        else EvidenceStrength.OBSERVED_FAIL,
                        "restored project=%s; mutation token=%s" % (import_name, token),
                    )
                )

        # Switch the operator's Resolve session back to the live project.
        reload_ok, _ = _safe(
            "LoadProject(restore live)", project_manager.LoadProject, project_name
        )
        if not reload_ok:
            findings.append(
                finding(
                    "snapshot.export.context_restore",
                    "Could not switch the current project back to the live "
                    "project after the export/import test; operator context may "
                    "be left on the temp import.",
                    EvidenceStrength.OBSERVED_FAIL,
                    "attempted LoadProject('%s')" % project_name,
                )
            )

        _safe("DeleteProject(temp import)", project_manager.DeleteProject, import_name)
        _cleanup_marker(timeline, frame_id)
        return reliable
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# (b) duplicate-timeline reversibility
# --------------------------------------------------------------------------- #

def run_duplicate_mode(
    project: Any,
    timeline: Any,
    findings: list[dict[str, Any]],
) -> Optional[bool]:
    """Test timeline-duplication isolation. Returns True/False/None (gap)."""
    token = "snapshot_probe_dup_" + uuid.uuid4().hex[:8]
    name_ok, base_name = _safe("GetName(timeline)", timeline.GetName)
    dup_name = "%s_probe_dup" % (base_name if name_ok and base_name else "timeline")

    dup_ok, dup = _safe("DuplicateTimeline", timeline.DuplicateTimeline, dup_name)
    if not dup_ok or dup is None:
        findings.append(
            finding(
                "snapshot.duplicate.duplicate_call",
                "DuplicateTimeline is unavailable or failed in this Resolve version.",
                EvidenceStrength.UNTESTED,
                str(dup),
            )
        )
        return None
    findings.append(
        finding(
            "snapshot.duplicate.duplicate_call",
            "DuplicateTimeline('%s') succeeded." % dup_name,
            EvidenceStrength.OBSERVED_PASS,
            dup_name,
        )
    )

    baseline_ok, baseline_markers = _safe("GetMarkers(dup baseline)", dup.GetMarkers)
    if not baseline_ok:
        findings.append(
            finding(
                "snapshot.duplicate.baseline",
                "Could not read the duplicate's markers before mutating the original.",
                EvidenceStrength.UNTESTED,
                str(baseline_markers),
            )
        )
        _cleanup_duplicate(project, dup)
        return None

    frame_id = _pick_frame_id(timeline)
    mutated = _add_probe_marker(timeline, frame_id, token)
    if not mutated:
        findings.append(
            finding(
                "snapshot.duplicate.mutate",
                "Could not mutate the original timeline; duplicate isolation "
                "cannot be tested.",
                EvidenceStrength.UNTESTED,
                "AddMarker failed at frame %d" % frame_id,
            )
        )
        _cleanup_duplicate(project, dup)
        return None
    findings.append(
        finding(
            "snapshot.duplicate.mutate",
            "Mutated the original timeline (added marker token %s)." % token,
            EvidenceStrength.OBSERVED_PASS,
            "frame=%d" % frame_id,
        )
    )

    after_ok, after_markers = _safe("GetMarkers(dup after)", dup.GetMarkers)
    reliable: Optional[bool] = None
    if not after_ok:
        findings.append(
            finding(
                "snapshot.duplicate.post_check",
                "Could not read the duplicate's markers after mutating the original.",
                EvidenceStrength.UNTESTED,
                str(after_markers),
            )
        )
    else:
        leaked = _marker_present(after_markers, token)
        reliable = not leaked
        findings.append(
            finding(
                "snapshot.duplicate.reversibility",
                "The duplicate %s the post-duplication mutation of the original."
                % ("did NOT preserve (leaked)" if leaked else "preserved pre-mutation state against"),
                EvidenceStrength.OBSERVED_FAIL if leaked else EvidenceStrength.OBSERVED_PASS,
                "duplicate=%s; mutation token=%s" % (dup_name, token),
            )
        )

    _cleanup_marker(timeline, frame_id)
    _cleanup_duplicate(project, dup)
    return reliable


def _cleanup_duplicate(project: Any, dup: Any) -> None:
    media_pool_ok, media_pool = _safe("GetMediaPool", project.GetMediaPool)
    if media_pool_ok and media_pool is not None:
        _safe("DeleteTimelines", media_pool.DeleteTimelines, [dup])


# --------------------------------------------------------------------------- #
# Fallback evaluation: generated-timeline replacement
# --------------------------------------------------------------------------- #

def run_fallback_eval(project: Any, findings: list[dict[str, Any]]) -> Optional[bool]:
    """Evaluate whether always generating a fresh output timeline is viable
    in place of relying on rollback. Returns True/False/None (gap).

    This is only invoked once neither export nor duplicate showed reliable
    reversibility (a narrowing gate per research.md R8 / FR-009): a product
    that always creates a new output timeline may not need restore at all.
    """
    media_pool_ok, media_pool = _safe("GetMediaPool", project.GetMediaPool)
    if not media_pool_ok or media_pool is None:
        findings.append(
            finding(
                "snapshot.fallback.media_pool",
                "Could not reach the media pool to evaluate generated-timeline "
                "replacement as a fallback.",
                EvidenceStrength.UNTESTED,
                str(media_pool),
            )
        )
        return None

    probe_name = "snapshot_probe_fallback_" + uuid.uuid4().hex[:8]
    created_ok, created = _safe(
        "CreateEmptyTimeline", media_pool.CreateEmptyTimeline, probe_name
    )
    if not created_ok or created is None:
        findings.append(
            finding(
                "snapshot.fallback.generated_timeline",
                "Neither export nor duplicate reversibility was reliable, and "
                "creating a fresh replacement timeline also failed/is "
                "unavailable — no viable fallback observed.",
                EvidenceStrength.OBSERVED_FAIL,
                str(created),
            )
        )
        return False

    findings.append(
        finding(
            "snapshot.fallback.generated_timeline",
            "Neither export nor duplicate reversibility was reliable, but "
            "creating a fresh output timeline (CreateEmptyTimeline) succeeded — "
            "a product that always generates a new output timeline instead of "
            "restoring one is a viable fallback strategy.",
            EvidenceStrength.OBSERVED_PASS,
            probe_name,
        )
    )
    _safe("DeleteTimelines(fallback probe)", media_pool.DeleteTimelines, [created])
    return True


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="US6 snapshot probe: project-export vs timeline-duplication reversibility."
    )
    parser.add_argument(
        "--mode",
        choices=["export", "duplicate", "both"],
        default="both",
        help="which reversibility approach(es) to test (default: both)",
    )
    return parser.parse_args(argv)


def _cannot_run(
    findings: list[dict[str, Any]],
    finding_id: str,
    statement: str,
    evidence: str,
    resolve_version: str = "unknown",
) -> int:
    """Record a CANNOT-RUN finding, write the ProbeResult, and return exit 2."""
    print("CANNOT-RUN: %s" % evidence)
    findings.append(finding(finding_id, statement, EvidenceStrength.NOT_FOUND, evidence))
    provenance = build_provenance(
        PROBE_NAME, ProbeOutcome.SKIPPED, resolve_version=resolve_version
    )
    out_path = write_probe_result(PROBE_NAME, provenance, findings, ProbeOutcome.SKIPPED)
    print("Wrote %s" % out_path)
    return 2


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    findings: list[dict[str, Any]] = []

    resolve = resolve_env.connect()
    if resolve is None:
        diagnosis = resolve_env.diagnose_connection_failure()
        return _cannot_run(
            findings,
            "snapshot.connect",
            "Could not connect to a running DaVinci Resolve instance.",
            diagnosis,
        )

    version_ok, resolve_version = _safe("GetVersionString", resolve.GetVersionString)
    resolve_version_str = resolve_version if version_ok and resolve_version else "unknown"

    pm_ok, project_manager = _safe("GetProjectManager", resolve.GetProjectManager)
    project = None
    if pm_ok and project_manager is not None:
        proj_ok, project = _safe("GetCurrentProject", project_manager.GetCurrentProject)
        if not proj_ok:
            project = None

    if not pm_ok or project_manager is None or project is None:
        return _cannot_run(
            findings,
            "snapshot.project_context",
            "Resolve is reachable but no current project is open.",
            "Connected to Resolve, but no current project is open. Open a "
            "scratch/fixture project in Resolve and re-run (spike/README.md "
            "safety note).",
            resolve_version_str,
        )

    tl_ok, timeline = _safe("GetCurrentTimeline", project.GetCurrentTimeline)
    if not tl_ok or timeline is None:
        return _cannot_run(
            findings,
            "snapshot.timeline_context",
            "The current project has no current timeline.",
            "A project is open but it has no current timeline. Open/create a "
            "timeline in the scratch project and re-run.",
            resolve_version_str,
        )

    export_reliable: Optional[bool] = None
    duplicate_reliable: Optional[bool] = None

    if args.mode in ("export", "both"):
        export_reliable = run_export_mode(project_manager, project, timeline, findings)
        # Context may have shifted projects during the export test; re-fetch.
        proj_ok, project = _safe("GetCurrentProject(refresh)", project_manager.GetCurrentProject)
        if proj_ok and project is not None:
            tl_ok, refreshed_timeline = _safe(
                "GetCurrentTimeline(refresh)", project.GetCurrentTimeline
            )
            if tl_ok and refreshed_timeline is not None:
                timeline = refreshed_timeline
    else:
        findings.append(
            finding(
                "snapshot.export.skipped",
                "Export mode not selected (--mode %s)." % args.mode,
                EvidenceStrength.UNTESTED,
                "operator-selected scope",
            )
        )

    if args.mode in ("duplicate", "both"):
        duplicate_reliable = run_duplicate_mode(project, timeline, findings)
    else:
        findings.append(
            finding(
                "snapshot.duplicate.skipped",
                "Duplicate mode not selected (--mode %s)." % args.mode,
                EvidenceStrength.UNTESTED,
                "operator-selected scope",
            )
        )

    reliable = export_reliable is True or duplicate_reliable is True
    fallback_viable: Optional[bool] = None
    if not reliable:
        fallback_viable = run_fallback_eval(project, findings)

    pass_gate = reliable or bool(fallback_viable)
    outcome = ProbeOutcome.PASS if pass_gate else ProbeOutcome.FAIL

    findings.append(
        finding(
            "snapshot.gate",
            "Narrowing gate (US6/FR-009): %s"
            % (
                "reliable rollback observed (export=%s, duplicate=%s)."
                % (export_reliable, duplicate_reliable)
                if reliable
                else (
                    "no reliable rollback (export=%s, duplicate=%s); "
                    "generated-timeline replacement fallback is %s."
                    % (
                        export_reliable,
                        duplicate_reliable,
                        "viable" if fallback_viable else "not viable/not evaluated",
                    )
                )
            ),
            EvidenceStrength.OBSERVED_PASS if pass_gate else EvidenceStrength.OBSERVED_FAIL,
            "export_reliable=%s duplicate_reliable=%s fallback_viable=%s"
            % (export_reliable, duplicate_reliable, fallback_viable),
        )
    )

    print(
        "snapshot probe result: %s (export_reliable=%s, duplicate_reliable=%s, "
        "fallback_viable=%s)"
        % (outcome.value, export_reliable, duplicate_reliable, fallback_viable)
    )

    provenance = build_provenance(PROBE_NAME, outcome, resolve_version=resolve_version_str)
    out_path = write_probe_result(PROBE_NAME, provenance, findings, outcome)
    print("Wrote %s" % out_path)

    return 0 if pass_gate else 1


if __name__ == "__main__":
    sys.exit(main())
