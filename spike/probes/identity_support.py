"""Pure helper functions for the US5 identity probe (spike/probes/identity.py).

Split out of identity.py to keep both files under the code-governance size
envelope. Everything here is a pure function of its arguments (a resolved
``project``/``timeline``/object dict, or an already-collected report dict) —
no CLI parsing, no top-level connection logic, no ``sys.exit``. The caller
(identity.py's ``main()``) owns the live Resolve connection and orchestrates
these helpers in sequence.

Covers: GetUniqueId()/similar-accessor probing (research R7), save/reload
persistence comparison, harness-managed-identity (marker tag) assessment, and
the Finding objects each of those produces. See identity.py's module
docstring for the full behavioral contract this module implements pieces of.
"""

import uuid
from typing import Any, Optional

from evidence import EvidenceStrength, finding

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

# --- Object resolution (degrades to None, never raises) --------------------- #

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

# --- Identifier probing (GetUniqueId + similar accessors) ------------------- #

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

# --- Harness-managed identity assessment (marker-tag durable key) ----------- #

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

# --- Save + reload cycle (FR-008) -------------------------------------------- #

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
