"""US5 identity probe — stable identifiers for idempotency (Group B, narrowing gate).

THROWAWAY spike code (see spike/README.md). Implements the `identity` probe from
the CLI contract (specs/001-resolve-discovery-spike/contracts/probes.md, "identity
(US5)" section), research R7, and FR-008 / spec.md US5.

What it does:
  - Connects to a running Resolve (spike/resolve_env.py) and, for each object type
    where the live API exposes one (Timeline, TimelineItem, MediaPoolItem, Folder),
    probes `GetUniqueId()` plus any similarly-named identifier accessor the object
    genuinely exposes. Presence/absence is recorded per object type with an
    evidence-strength label — absence is `not-found`, never "proven impossible"
    (FR-016).
  - With `--reload`, saves the current project and reloads it (ProjectManager
    Save/Close/Load), then re-probes the same objects and reports whether the
    recorded identifier values PERSIST across the cycle.
  - Regardless of native-identifier outcome, ASSESSES harness-managed identity
    viability: it writes a durable marker tag (a generated UUID) onto the current
    timeline and checks whether it round-trips immediately (and, with `--reload`,
    whether it survives the save/reload cycle). This is itself an empirical probe,
    not a guess, and is recorded as a Finding — a narrowing gate, per spec.md's
    Decision Policy: absence of native identity is a NARROW input, not a NO-GO.

Exit codes (probe CLI contract):
  0 = PASS  — durable native identity OR a credible harness-managed strategy.
  1 = FAIL  — observed, recorded FAIL (neither durable native ids nor a credible
              harness-managed strategy); still a successful run of the probe.
  2 = CANNOT-RUN — Resolve unreachable; fails fast (FR-014), never hangs (bounded
              by resolve_env.connect()'s worker-thread timeout).

Design constraints: Python 3.11-compatible syntax only; degrades gracefully when
a project/timeline/media pool is absent rather than crashing (every live API call
is wrapped so an unexpected shape is a recorded Finding, not a traceback).
"""

import os
import sys

# Defensive, self-contained fix-up BEFORE importing argparse: Python auto-
# prepends a directly-run script's own directory (spike/probes/) to sys.path.
# A sibling probe module is named `inspect.py` (the `inspect` probe, US2),
# which then shadows the stdlib `inspect` module for every script started
# directly from this directory. Python 3.13+'s argparse internally imports the
# real stdlib `inspect` while building its help formatter, so — with no
# involvement from Resolve at all — the shadow turns a bare `import argparse`
# (or any `--help`) into a crash. This script does not need its own directory
# on sys.path (it only needs spike/, its parent, added explicitly below), so
# strip the auto-inserted entry rather than depend on a sibling file's name.
_PROBES_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path = [p for p in sys.path if os.path.abspath(p or ".") != _PROBES_DIR]

import argparse  # noqa: E402
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Optional  # noqa: E402

# Make the sibling spike/ modules (resolve_env, evidence) importable regardless
# of the caller's cwd. spike/probes/identity.py -> parent.parent == spike/.
_SPIKE_DIR = Path(__file__).resolve().parent.parent
if str(_SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(_SPIKE_DIR))

import resolve_env  # noqa: E402
from evidence import (  # noqa: E402
    Confidence,
    EvidenceStrength,
    ProbeOutcome,
    build_provenance,
    edition,
    finding,
    write_probe_result,
)

PROBE_NAME = "identity"

# Object types the API documents GetUniqueId() on (research R7).
OBJECT_TYPES = ["Timeline", "TimelineItem", "MediaPoolItem", "Folder"]

# The documented primary accessor, always probed (present or absent) on every
# resolved object.
PRIMARY_ACCESSOR = "GetUniqueId"

# Plausible alternate/similar identifier accessors. These are speculative and
# version-dependent, so absence is not recorded (it carries no signal — it was
# never asserted these exist); presence IS recorded as a genuine discovery.
ALT_ACCESSOR_CANDIDATES = ["GetMediaId", "GetClipId", "GetItemId", "GetTimelineId"]

_MEDIA_POOL_RECURSION_LIMIT = 6


# --------------------------------------------------------------------------- #
# Object resolution (degrades to None, never raises)
# --------------------------------------------------------------------------- #


def _first_timeline_item(timeline: Any) -> Any:
    """Return the first clip found in any video track of ``timeline``, or None."""
    try:
        track_count = timeline.GetTrackCount("video") or 0
    except Exception:
        track_count = 0
    for track_index in range(1, track_count + 1):
        try:
            items = timeline.GetItemListInTrack("video", track_index)
        except Exception:
            items = None
        if items:
            return items[0]
    return None


def _first_media_pool_item(folder: Any, depth: int = 0) -> Any:
    """Depth-first search for the first clip in ``folder`` or its subfolders."""
    if folder is None or depth > _MEDIA_POOL_RECURSION_LIMIT:
        return None
    try:
        clips = folder.GetClipList()
    except Exception:
        clips = None
    if clips:
        return clips[0]
    try:
        subfolders = folder.GetSubFolderList()
    except Exception:
        subfolders = None
    for sub in subfolders or []:
        found = _first_media_pool_item(sub, depth + 1)
        if found is not None:
            return found
    return None


def collect_objects(project: Any) -> dict:
    """Resolve one representative live object per OBJECT_TYPES from the active
    project state. Degrades to None (never raises) when something is absent —
    e.g. no current timeline, empty media pool — since that is itself a Finding
    (recorded by the caller), not a probe crash.
    """
    objects: dict = {t: None for t in OBJECT_TYPES}
    if project is None:
        return objects

    try:
        timeline = project.GetCurrentTimeline()
    except Exception:
        timeline = None
    objects["Timeline"] = timeline

    if timeline is not None:
        try:
            objects["TimelineItem"] = _first_timeline_item(timeline)
        except Exception:
            objects["TimelineItem"] = None

    try:
        media_pool = project.GetMediaPool()
        root_folder = media_pool.GetRootFolder() if media_pool else None
    except Exception:
        root_folder = None
    objects["Folder"] = root_folder

    if root_folder is not None:
        try:
            objects["MediaPoolItem"] = _first_media_pool_item(root_folder)
        except Exception:
            objects["MediaPoolItem"] = None

    return objects


# --------------------------------------------------------------------------- #
# Identifier probing (GetUniqueId + similar accessors)
# --------------------------------------------------------------------------- #


def _safe_call(obj: Any, method_name: str) -> tuple:
    """Call ``obj.<method_name>()`` if present. Returns (value, error_or_None).

    ``error`` is the literal string "accessor-not-present" when the object has
    no such method at all (distinct from the method existing but raising or
    returning nothing).
    """
    if obj is None or not hasattr(obj, method_name):
        return None, "accessor-not-present"
    try:
        method = getattr(obj, method_name)
        value = method()
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    return value, None


def _probe_object_identifiers(obj_type: str, obj: Any) -> tuple:
    """Probe identifier accessors for one live object.

    Always checks PRIMARY_ACCESSOR (present or absent). Additionally checks the
    ALT_ACCESSOR_CANDIDATES that the object genuinely exposes (via hasattr) —
    candidates it does NOT expose are silently skipped, since their absence was
    never asserted as meaningful.

    Returns (per_type_report, list_of_findings).
    """
    accessors_checked = [PRIMARY_ACCESSOR] + [
        name for name in ALT_ACCESSOR_CANDIDATES if hasattr(obj, name)
    ]
    accessor_results: dict = {}
    findings: list = []
    for accessor in accessors_checked:
        value, error = _safe_call(obj, accessor)
        accessor_results[accessor] = {"value": value, "error": error}
        if error == "accessor-not-present":
            strength = EvidenceStrength.NOT_FOUND
            statement = "%s.%s() is not exposed on this object." % (obj_type, accessor)
        elif error is not None:
            strength = EvidenceStrength.OBSERVED_FAIL
            statement = "%s.%s() raised an error: %s" % (obj_type, accessor, error)
        elif value in (None, ""):
            strength = EvidenceStrength.OBSERVED_FAIL
            statement = "%s.%s() returned an empty/None id." % (obj_type, accessor)
        else:
            strength = EvidenceStrength.OBSERVED_PASS
            statement = "%s.%s() returned id %r." % (obj_type, accessor, value)
        findings.append(
            finding(
                id="identity.%s.%s" % (obj_type.lower(), accessor.lower()),
                statement=statement,
                strength=strength,
                evidence="accessor=%s value=%r error=%s" % (accessor, value, error),
            )
        )
    return {"object_present": True, "accessors": accessor_results}, findings


def probe_identifiers(objects: dict) -> tuple:
    """Probe identifiers across every OBJECT_TYPES entry in ``objects``.

    Returns (report, findings) where report maps object type ->
    {"object_present": bool, "accessors": {name: {"value", "error"}}}.
    """
    report: dict = {}
    findings: list = []
    for obj_type in OBJECT_TYPES:
        obj = objects.get(obj_type)
        if obj is None:
            findings.append(
                finding(
                    id="identity.%s.availability" % obj_type.lower(),
                    statement=(
                        "No live %s object was available to probe (current "
                        "project/timeline/media-pool state did not expose one). "
                        "This is NOT evidence that the API lacks identifiers for "
                        "this type." % obj_type
                    ),
                    strength=EvidenceStrength.NOT_FOUND,
                    evidence="object resolution returned None before any accessor was attempted.",
                )
            )
            report[obj_type] = {"object_present": False, "accessors": {}}
            continue
        obj_report, obj_findings = _probe_object_identifiers(obj_type, obj)
        report[obj_type] = obj_report
        findings.extend(obj_findings)
    return report, findings


def _any_native_id_observed(report: dict) -> bool:
    """True if at least one object type/accessor returned a real, non-empty id."""
    return any(
        accessor_result.get("error") is None and accessor_result.get("value") not in (None, "")
        for type_report in report.values()
        for accessor_result in type_report.get("accessors", {}).values()
    )


def compare_persistence(before_report: dict, after_report: dict) -> tuple:
    """Compare identifier values recorded before vs after a save/reload cycle.

    Only compares accessors that returned a real value before reload (nothing to
    compare for an accessor that was absent/failed to begin with). Returns
    (findings, all_stable, any_compared).
    """
    findings: list = []
    all_stable = True
    any_compared = False
    for obj_type in OBJECT_TYPES:
        before = before_report.get(obj_type, {})
        after = after_report.get(obj_type, {})
        if not before.get("object_present") or not after.get("object_present"):
            continue
        for accessor, before_result in before.get("accessors", {}).items():
            before_value = before_result.get("value")
            if before_result.get("error") is not None or before_value in (None, ""):
                continue  # nothing durable to compare
            after_result = after.get("accessors", {}).get(accessor, {})
            after_value = after_result.get("value")
            any_compared = True
            persisted = before_value == after_value and after_result.get("error") is None
            if not persisted:
                all_stable = False
            findings.append(
                finding(
                    id="identity.%s.%s.persistence" % (obj_type.lower(), accessor.lower()),
                    statement=(
                        "%s.%s() %s across save/reload (before=%r, after=%r)."
                        % (
                            obj_type,
                            accessor,
                            "persisted" if persisted else "CHANGED / became unavailable",
                            before_value,
                            after_value,
                        )
                    ),
                    strength=EvidenceStrength.OBSERVED_PASS
                    if persisted
                    else EvidenceStrength.OBSERVED_FAIL,
                    evidence="before=%r after=%r" % (before_value, after_value),
                )
            )
    return findings, all_stable, any_compared


# --------------------------------------------------------------------------- #
# Harness-managed identity assessment (marker-tag durable key)
# --------------------------------------------------------------------------- #


def assess_harness_managed_identity(timeline: Any, reload_requested: bool) -> tuple:
    """Assess viability of a harness-managed identity strategy (a durable marker
    tag) as a fallback when native identifiers are absent/unstable (FR-008,
    research R7). This writes a marker carrying a generated UUID onto the
    timeline and checks whether it round-trips immediately.

    Returns (finding_dict, tag_or_None). ``tag`` is non-None only when the tag
    was actually written, so the caller can re-check it for persistence after a
    reload.
    """
    if timeline is None:
        return (
            finding(
                id="identity.harness_managed.assessment",
                statement=(
                    "No timeline was available to assess harness-managed identity "
                    "(marker/metadata tagging) against."
                ),
                strength=EvidenceStrength.NOT_FOUND,
                evidence="no live Timeline object in the current project state.",
            ),
            None,
        )

    tag = "identity-probe-%s" % uuid.uuid4()
    try:
        added = timeline.AddMarker(0, "Blue", tag, "identity spike probe marker", 1, "")
    except Exception as exc:
        return (
            finding(
                id="identity.harness_managed.assessment",
                statement="Attempting a harness-managed marker tag raised: %s" % exc,
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence="timeline.AddMarker(...) raised %s: %s" % (type(exc).__name__, exc),
            ),
            None,
        )
    if not added:
        return (
            finding(
                id="identity.harness_managed.assessment",
                statement="timeline.AddMarker() returned falsy for the harness-managed tag marker.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence="AddMarker returned a falsy result; tag=%s" % tag,
            ),
            None,
        )

    try:
        markers = timeline.GetMarkers() or {}
    except Exception as exc:
        return (
            finding(
                id="identity.harness_managed.assessment",
                statement="Marker was added but GetMarkers() raised: %s" % exc,
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence="%s: %s; tag=%s" % (type(exc).__name__, exc, tag),
            ),
            None,
        )
    found_immediately = any(m.get("name") == tag for m in markers.values())
    if not found_immediately:
        return (
            finding(
                id="identity.harness_managed.assessment",
                statement="Harness-managed marker tag was added but not found on immediate re-read.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence="tag=%s markers_after_add=%s" % (tag, list(markers.keys())),
            ),
            None,
        )

    if reload_requested:
        statement = (
            "Harness-managed marker tag round-tripped immediately (added + read "
            "back); persistence across save/reload is recorded separately "
            "(identity.harness_managed.persistence)."
        )
    else:
        statement = (
            "Harness-managed marker tag round-tripped immediately (added + read "
            "back); persistence across save/reload was not tested (--reload not "
            "passed), so this is a credible but UNCONFIRMED harness-managed "
            "identity strategy."
        )
    return (
        finding(
            id="identity.harness_managed.assessment",
            statement=statement,
            strength=EvidenceStrength.OBSERVED_PASS,
            evidence="tag=%s; AddMarker + GetMarkers immediate round-trip matched" % tag,
        ),
        tag,
    )


def check_harness_tag_persistence(timeline: Any, tag: Optional[str]) -> dict:
    """Re-check whether the harness-managed marker ``tag`` survived a reload."""
    if timeline is None or tag is None:
        return finding(
            id="identity.harness_managed.persistence",
            statement=(
                "Could not check harness-managed tag persistence: no reloaded "
                "timeline (or no tag was written) available."
            ),
            strength=EvidenceStrength.NOT_FOUND,
            evidence="reloaded timeline missing or tag was never written",
        )
    try:
        markers = timeline.GetMarkers() or {}
    except Exception as exc:
        return finding(
            id="identity.harness_managed.persistence",
            statement="GetMarkers() raised after reload: %s" % exc,
            strength=EvidenceStrength.OBSERVED_FAIL,
            evidence="%s: %s" % (type(exc).__name__, exc),
        )
    persisted = any(m.get("name") == tag for m in markers.values())
    return finding(
        id="identity.harness_managed.persistence",
        statement=(
            "Harness-managed marker tag %s across save/reload."
            % ("PERSISTED" if persisted else "did NOT persist")
        ),
        strength=EvidenceStrength.OBSERVED_PASS if persisted else EvidenceStrength.OBSERVED_FAIL,
        evidence="tag=%s markers_after_reload=%s" % (tag, list(markers.keys())),
    )


# --------------------------------------------------------------------------- #
# Save + reload cycle (FR-008)
# --------------------------------------------------------------------------- #


def save_and_reload(project_manager: Any, project: Any) -> tuple:
    """Save ``project`` and reload it via ProjectManager Close/Load.

    Returns (reloaded_project_or_None, error_or_None).
    """
    try:
        name = project.GetName()
    except Exception as exc:
        return None, "could not read project name: %s" % exc
    try:
        saved = project.Save()
    except Exception as exc:
        return None, "project.Save() raised: %s" % exc
    if not saved:
        return None, "project.Save() returned falsy"
    try:
        project_manager.CloseProject(project)
    except Exception as exc:
        return None, "ProjectManager.CloseProject() raised: %s" % exc
    try:
        reloaded = project_manager.LoadProject(name)
    except Exception as exc:
        return None, "ProjectManager.LoadProject(%r) raised: %s" % (name, exc)
    if reloaded is None:
        return None, "ProjectManager.LoadProject(%r) returned None" % name
    return reloaded, None


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="identity.py",
        description=(
            "US5 identity probe: enumerate GetUniqueId()-style identifiers across "
            "Timeline/TimelineItem/MediaPoolItem/Folder, assess harness-managed "
            "identity viability (marker tag), and optionally test persistence "
            "across a save/reload cycle (FR-008, research R7)."
        ),
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help=(
            "Save the current project and reload it (ProjectManager Save/Close/"
            "Load), then re-check native identifier and harness-managed-tag "
            "persistence across the cycle."
        ),
    )
    return parser


def main(argv=None) -> int:
    args = _build_argparser().parse_args(argv)

    resolve = resolve_env.connect()
    if resolve is None:
        diagnosis = resolve_env.diagnose_connection_failure()
        provenance = build_provenance(PROBE_NAME, ProbeOutcome.SKIPPED)
        findings = [
            finding(
                id="identity.connect",
                statement="Could not connect to a running DaVinci Resolve instance.",
                strength=EvidenceStrength.UNTESTED,
                evidence=diagnosis,
            )
        ]
        out_path = write_probe_result(PROBE_NAME, provenance, findings, ProbeOutcome.SKIPPED)
        print("CANNOT-RUN: %s" % diagnosis)
        print("Wrote %s" % out_path)
        return 2

    try:
        version = resolve.GetVersionString()
    except Exception:
        version = "unknown"
    resolve_edition = edition(
        "Studio",
        Confidence.INFERRED,
        "external scripting connection succeeded (the free edition disables external scripting)",
    )

    findings: list = []

    try:
        project_manager = resolve.GetProjectManager()
    except Exception as exc:
        project_manager = None
        findings.append(
            finding(
                id="identity.project_manager",
                statement="GetProjectManager() raised: %s" % exc,
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence="%s: %s" % (type(exc).__name__, exc),
            )
        )

    project = None
    if project_manager is not None:
        try:
            project = project_manager.GetCurrentProject()
        except Exception as exc:
            findings.append(
                finding(
                    id="identity.project",
                    statement="GetCurrentProject() raised: %s" % exc,
                    strength=EvidenceStrength.OBSERVED_FAIL,
                    evidence="%s: %s" % (type(exc).__name__, exc),
                )
            )
    if project is None:
        findings.append(
            finding(
                id="identity.project.availability",
                statement=(
                    "No current project is open in Resolve; identity probing is "
                    "limited to whatever the API exposes with none open."
                ),
                strength=EvidenceStrength.NOT_FOUND,
                evidence="GetCurrentProject() returned None (or ProjectManager was unavailable).",
            )
        )

    before_objects = collect_objects(project)
    before_report, id_findings = probe_identifiers(before_objects)
    findings.extend(id_findings)
    native_observed = _any_native_id_observed(before_report)

    if not args.reload:
        findings.append(
            finding(
                id="identity.persistence.untested",
                statement=(
                    "Save/reload persistence was not tested (--reload not passed); "
                    "native identifier durability is therefore UNTESTED, not confirmed."
                ),
                strength=EvidenceStrength.UNTESTED,
                evidence="re-run with --reload to test persistence across a save/reload cycle.",
            )
        )

    timeline = before_objects.get("Timeline")
    harness_finding, harness_tag = assess_harness_managed_identity(timeline, args.reload)
    findings.append(harness_finding)
    harness_immediate_pass = harness_finding["strength"] == EvidenceStrength.OBSERVED_PASS.value

    native_durable = False
    harness_persisted: Optional[bool] = None

    if args.reload:
        if project is None or project_manager is None:
            findings.append(
                finding(
                    id="identity.reload",
                    statement="Cannot save/reload: no current project is open.",
                    strength=EvidenceStrength.NOT_FOUND,
                    evidence="project or project_manager unavailable before reload was attempted.",
                )
            )
        else:
            reloaded_project, reload_error = save_and_reload(project_manager, project)
            if reloaded_project is None:
                findings.append(
                    finding(
                        id="identity.reload",
                        statement="Save/reload cycle failed: %s" % reload_error,
                        strength=EvidenceStrength.OBSERVED_FAIL,
                        evidence=reload_error or "unknown reload failure",
                    )
                )
            else:
                findings.append(
                    finding(
                        id="identity.reload",
                        statement="Project saved and reloaded successfully.",
                        strength=EvidenceStrength.OBSERVED_PASS,
                        evidence="ProjectManager.CloseProject + LoadProject round-trip succeeded.",
                    )
                )
                after_objects = collect_objects(reloaded_project)
                after_report, _after_id_findings = probe_identifiers(after_objects)
                persist_findings, all_stable, any_compared = compare_persistence(
                    before_report, after_report
                )
                findings.extend(persist_findings)
                if any_compared:
                    native_durable = native_observed and all_stable

                reloaded_timeline = after_objects.get("Timeline")
                harness_persist_finding = check_harness_tag_persistence(reloaded_timeline, harness_tag)
                findings.append(harness_persist_finding)
                harness_persisted = (
                    harness_persist_finding["strength"] == EvidenceStrength.OBSERVED_PASS.value
                )

    # PASS(narrowing) bar per contracts/probes.md: durable native identity OR a
    # credible harness-managed strategy.
    if args.reload:
        harness_credible = bool(harness_persisted)
    else:
        harness_credible = harness_immediate_pass

    overall_pass = native_durable or harness_credible
    outcome = ProbeOutcome.PASS if overall_pass else ProbeOutcome.FAIL

    findings.append(
        finding(
            id="identity.gate",
            statement=(
                "Identity narrowing gate: native_durable=%s, harness_managed_credible=%s -> %s. "
                "(Narrowing gate per Decision Policy — a FAIL here narrows scope, it does not "
                "by itself force NO-GO.)"
                % (native_durable, harness_credible, "PASS" if overall_pass else "FAIL")
            ),
            strength=EvidenceStrength.OBSERVED_PASS if overall_pass else EvidenceStrength.OBSERVED_FAIL,
            evidence="see identity.*.persistence and identity.harness_managed.* findings above.",
        )
    )

    provenance = build_provenance(
        PROBE_NAME,
        outcome,
        resolve_version=version or "unknown",
        resolve_edition=resolve_edition,
    )
    out_path = write_probe_result(PROBE_NAME, provenance, findings, outcome)

    print("identity probe result: %s" % outcome.value)
    for f in findings:
        print(" - [%s] %s: %s" % (f["strength"], f["id"], f["statement"]))
    print("Wrote %s" % out_path)

    return 0 if outcome == ProbeOutcome.PASS else 1


if __name__ == "__main__":
    sys.exit(main())
