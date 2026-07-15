"""snapshot probe (US6) support helpers — pure Resolve-object functions.

THROWAWAY spike code (see spike/README.md). Split out of snapshot.py to keep
each file under the repo's line/byte governance envelope; see snapshot.py's
module docstring for the full probe description (export vs duplicate
reversibility, generated-timeline-replacement fallback, exit codes).

Everything here takes resolve/project/timeline objects (or the ProjectManager)
as explicit arguments — no module-level Resolve state — and appends Finding
dicts to a caller-supplied ``findings`` list. Every Resolve API call is
guarded via ``_safe`` (version variance across Resolve releases is expected):
a missing/failing method is recorded as a gap finding, never a crash.

Python 3.11-compatible syntax ONLY.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Make spike/ importable (this file lives at spike/probes/snapshot_support.py).
# --------------------------------------------------------------------------- #
_SPIKE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SPIKE_ROOT not in sys.path:
    sys.path.insert(0, _SPIKE_ROOT)

from evidence import EvidenceStrength, finding  # noqa: E402


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
