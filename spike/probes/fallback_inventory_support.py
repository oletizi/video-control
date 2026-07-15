"""Support module for fallback_inventory.py (US8 four-route classification).

THROWAWAY spike code (see spike/README.md). See the module docstring of
``fallback_inventory.py`` for the full contract (FR-011 / US8 / SC-004 /
research.md R11). This module holds everything that doesn't need to live in
the CLI entrypoint: ``OPERATION_CLASSIFICATIONS`` (the fixed, reviewable
per-operation route table: route + baseline evidence-strength + rationale +
optional live probe), the per-operation live-introspection probe functions
plus ``_live_context`` (best-effort connect/introspect helpers that can only
ever STRENGTHEN a label — documented -> observed-pass — never redirect a
route), and ``_classify_one`` (the route-classification + finding-builder
routine that turns one fixture entry into a CapabilityMatrixRow + Finding).

CRITICAL (FR-011): absence of a method from the live API (or the complete
absence of a connection) MUST NOT cause a route to fall back to
``named-gui-fallback``. Route is decided from documented knowledge up front;
a failed/impossible live introspection only affects the *evidence-strength
label*, never the route. This is why routes are declared as fixed
per-operation data below rather than derived from whether a live probe
succeeded.

Python 3.11-compatible syntax only.
"""

import sys
from pathlib import Path
from typing import Any, Callable, Optional

# Make the sibling spike/ package importable when this module is imported
# directly (e.g. by a test), regardless of the caller's cwd. Harmless if
# fallback_inventory.py already performed the same insertion.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence  # noqa: E402
import resolve_env  # noqa: E402

DEFAULT_OPS_PATH = "spike/fixtures/mvp-operations.json"

# The four permitted routes (FR-011 / data-model.md CapabilityMatrixRow.route).
ROUTE_RESOLVE_API = "resolve-api"
ROUTE_EXTERNAL_TOOLING = "external-tooling"
ROUTE_NAMED_GUI_FALLBACK = "named-gui-fallback"
ROUTE_UNSUPPORTED_OR_DEFERRED = "unsupported-or-deferred"

VALID_ROUTES = frozenset(
    {
        ROUTE_RESOLVE_API,
        ROUTE_EXTERNAL_TOOLING,
        ROUTE_NAMED_GUI_FALLBACK,
        ROUTE_UNSUPPORTED_OR_DEFERRED,
    }
)

# --------------------------------------------------------------------------- #
# Live-introspection probe functions. Each receives (project, media_pool,
# timeline) — any of which may be None (no project open, no timeline created)
# — and must never raise.
# --------------------------------------------------------------------------- #


def _has_attr(obj: Any, name: str) -> bool:
    return obj is not None and hasattr(obj, name)


def _probe_media_pool_import_media(project: Any, media_pool: Any, timeline: Any) -> bool:
    return _has_attr(media_pool, "ImportMedia")

def _probe_media_pool_create_timeline(project: Any, media_pool: Any, timeline: Any) -> bool:
    return _has_attr(media_pool, "CreateEmptyTimeline")

def _probe_media_pool_append_to_timeline(project: Any, media_pool: Any, timeline: Any) -> bool:
    return _has_attr(media_pool, "AppendToTimeline")

def _probe_timeline_add_marker(project: Any, media_pool: Any, timeline: Any) -> bool:
    return _has_attr(timeline, "AddMarker")

def _probe_timeline_import_into_timeline(project: Any, media_pool: Any, timeline: Any) -> bool:
    return _has_attr(timeline, "ImportIntoTimeline")

def _probe_timeline_insert_fusion_title(project: Any, media_pool: Any, timeline: Any) -> bool:
    return _has_attr(timeline, "InsertFusionTitleIntoTimeline")

def _probe_project_render_api(project: Any, media_pool: Any, timeline: Any) -> bool:
    return (
        _has_attr(project, "GetRenderPresetList")
        and _has_attr(project, "AddRenderJob")
        and _has_attr(project, "LoadRenderPreset")
    )


def _probe_no_silence_primitive(project: Any, media_pool: Any, timeline: Any) -> bool:
    """Negative-evidence probe for silence detection: dir()-scan the live
    objects we have for anything naming silence/audio-detection. Returns True
    if such a method is (surprisingly) present — which would be evidence
    AGAINST the external-tooling route; returns False (no such method found)
    when none exists, which CONFIRMS (rather than causes) the external-tooling
    classification per FR-011 — absence here does not flip the route.
    """
    needles = ("silence", "detectsilence", "loudness")
    for obj in (project, media_pool, timeline):
        if obj is None:
            continue
        try:
            names = dir(obj)
        except Exception:
            continue
        for n in names:
            if any(needle in n.lower() for needle in needles):
                return True
    return False

# --------------------------------------------------------------------------- #
# Classification data (research.md R11-adjacent domain knowledge). Each entry
# maps one MVP-critical operation (matched against the "operation" field of
# mvp-operations.json) to a fixed route + baseline (offline) evidence strength
# + rationale, and — where the live Resolve API can be introspected — a probe
# function that, given a live (project, media_pool, timeline) tuple, returns
# True if the expected primitive is present. A True result upgrades the label
# to observed-pass. A False/absent result NEVER changes the route (FR-011);
# it only means the live check could not confirm it, so the documented label
# is kept and a note is attached.
# --------------------------------------------------------------------------- #

OPERATION_CLASSIFICATIONS: list[dict[str, Any]] = [
    {
        "operation": "media import",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.DOCUMENTED_SUPPORTED,
        "rationale": "The Resolve scripting API documents MediaPool.ImportMedia(items) for importing external media files into the media pool — a core, long-standing part of the scripting surface.",
        "live_probe": _probe_media_pool_import_media,
        "live_target_desc": "media_pool.ImportMedia",
    },
    {
        "operation": "timeline creation",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.DOCUMENTED_SUPPORTED,
        "rationale": "The Resolve scripting API documents MediaPool.CreateEmptyTimeline(name) for deterministic timeline creation.",
        "live_probe": _probe_media_pool_create_timeline,
        "live_target_desc": "media_pool.CreateEmptyTimeline",
    },
    {
        "operation": "clip placement / trim",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.INFERRED,
        "rationale": "Placement is documented via MediaPool.AppendToTimeline() / MediaPool.InsertTimeline(); trim (adjusting a placed clip's in/out) is not a single crisply-named documented method but is composed from documented TimelineItem property setters, so the combined placement+trim operation is labeled inferred rather than documented-supported to avoid overclaiming trim fidelity.",
        "live_probe": _probe_media_pool_append_to_timeline,
        "live_target_desc": "media_pool.AppendToTimeline",
    },
    {
        "operation": "marker creation",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.DOCUMENTED_SUPPORTED,
        "rationale": "The Resolve scripting API documents Timeline.AddMarker(frameId, color, name, note, duration, customData) as a first-class primitive.",
        "live_probe": _probe_timeline_add_marker,
        "live_target_desc": "timeline.AddMarker",
    },
    {
        "operation": "subtitle import",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.DOCUMENTED_SUPPORTED,
        "rationale": "The Resolve scripting API documents Timeline.ImportIntoTimeline(fileName, importOptions), whose importOptions cover subtitle files (e.g. .srt) with offset/frame-rate parameters — a named, documented route, not a GUI-only fallback.",
        "live_probe": _probe_timeline_import_into_timeline,
        "live_target_desc": "timeline.ImportIntoTimeline",
    },
    {
        "operation": "silence detection / pause reduction",
        "route": ROUTE_EXTERNAL_TOOLING,
        "offline_strength": evidence.EvidenceStrength.DOCUMENTED_SUPPORTED,
        "rationale": "FR-011 CRITICAL CASE: the Resolve scripting API exposes no silence- or loudness-detection primitive. Per FR-011, that absence MUST NOT default to named-gui-fallback. The honest, stronger route is external deterministic tooling — e.g. ffmpeg's `silencedetect` audio filter (or a tool such as auto-editor) run against the exported/source audio — which is scriptable, reproducible, and independent of Resolve's GUI. Its output (cut points) is then fed back as programmatic clip placement (resolve-api) rather than requiring manual GUI scrubbing.",
        "live_probe": _probe_no_silence_primitive,
        "live_target_desc": "dir()-scan of project/media_pool/timeline for a silence/loudness method",
        "live_probe_is_negative_evidence": True,
    },
    {
        "operation": "intro/outro insertion",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.INFERRED,
        "rationale": "Not a distinct named feature in the scripting API; inferred from the same documented MediaPool.AppendToTimeline()/InsertTimeline() primitive used for any clip placement, applied to bumper/outro media at the head/tail of the timeline.",
        "live_probe": _probe_media_pool_append_to_timeline,
        "live_target_desc": "media_pool.AppendToTimeline",
    },
    {
        "operation": "Fusion title-template insertion",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.DOCUMENTED_SUPPORTED,
        "rationale": "The Resolve scripting API documents Timeline.InsertFusionTitleIntoTimeline(templateName) as a named method for inserting a Fusion title template by name onto the current timeline.",
        "live_probe": _probe_timeline_insert_fusion_title,
        "live_target_desc": "timeline.InsertFusionTitleIntoTimeline",
    },
    {
        "operation": "chapter markers from configuration",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.INFERRED,
        "rationale": "Resolve has no native 'chapter marker' object distinct from a regular timeline marker; chapters are conventionally represented as markers with a reserved color/name pattern consumed downstream (e.g. by an export step). Classified resolve-api by way of the documented Timeline.AddMarker() primitive, but labeled inferred because 'chapter' semantics are a harness-side convention, not an API-native concept.",
        "live_probe": _probe_timeline_add_marker,
        "live_target_desc": "timeline.AddMarker",
    },
    {
        "operation": "multi-format render",
        "route": ROUTE_RESOLVE_API,
        "offline_strength": evidence.EvidenceStrength.DOCUMENTED_SUPPORTED,
        "rationale": "The Resolve scripting API documents Project.GetRenderPresetList(), Project.LoadRenderPreset(presetName), and Project.AddRenderJob() for enqueueing one job per format/preset — the same documented surface the `render` probe (US4) exercises directly.",
        "live_probe": _probe_project_render_api,
        "live_target_desc": "project.GetRenderPresetList/LoadRenderPreset/AddRenderJob",
    },
]

_CLASSIFICATION_BY_OP: dict[str, dict[str, Any]] = {
    c["operation"]: c for c in OPERATION_CLASSIFICATIONS
}

# --------------------------------------------------------------------------- #
# Live introspection context
# --------------------------------------------------------------------------- #


def _live_context() -> tuple[Optional[Any], Optional[Any], Optional[Any], Optional[Any], str]:
    """Best-effort connect + fetch (resolve, project, media_pool, timeline).

    Returns (resolve, project, media_pool, timeline, connection_note). Any
    element may be None (Resolve unreachable, no project open, no timeline
    created). Never raises — every failure degrades to None with an
    explanatory note, per the module docstring's offline-first contract.
    """
    resolve = resolve_env.connect()
    if resolve is None:
        return None, None, None, None, (
            "no live connection (%s) — classifications use documented knowledge only"
            % (resolve_env.last_error or "unknown reason")
        )

    try:
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject() if project_manager else None
    except Exception as exc:  # defensive: never let introspection crash the probe
        return resolve, None, None, None, (
            "connected, but GetProjectManager()/GetCurrentProject() raised %s: %s"
            % (type(exc).__name__, exc)
        )

    if project is None:
        return resolve, None, None, None, (
            "connected, but no current project is open — API objects unavailable "
            "for live introspection"
        )

    media_pool = None
    timeline = None
    try:
        media_pool = project.GetMediaPool()
    except Exception:
        media_pool = None
    try:
        timeline = project.GetCurrentTimeline()
    except Exception:
        timeline = None

    note = "connected; project=%s media_pool=%s timeline=%s" % (
        "present",
        "present" if media_pool is not None else "absent",
        "present" if timeline is not None else "absent",
    )
    return resolve, project, media_pool, timeline, note

# --------------------------------------------------------------------------- #
# Classification + finding builder
# --------------------------------------------------------------------------- #


def _classify_one(
    op_entry: dict[str, Any],
    project: Optional[Any],
    media_pool: Optional[Any],
    timeline: Optional[Any],
    connected: bool,
) -> dict[str, Any]:
    """Classify a single operation. Returns a CapabilityMatrixRow-shaped dict
    plus a Finding under ``finding``.

    Every operation resolves to a route (never left unclassified): known
    operations use the fixed OPERATION_CLASSIFICATIONS table; any operation in
    the fixture that this probe does not recognize is honestly classified as
    ``unsupported-or-deferred`` / ``not-found`` (never silently defaulted to
    named-gui-fallback) with a note that it needs manual research — this keeps
    SC-004's "0 unclassified" true without inventing false confidence.
    """
    name = op_entry.get("operation", "<missing operation field>")
    why = op_entry.get("why", "")
    spec = _CLASSIFICATION_BY_OP.get(name)

    if spec is None:
        row = {
            "operation": name,
            "route": ROUTE_UNSUPPORTED_OR_DEFERRED,
            "strength": evidence.EvidenceStrength.NOT_FOUND.value,
            "notes": (
                "No classification entry exists in fallback_inventory.py's "
                "OPERATION_CLASSIFICATIONS table for this operation from %s. "
                "Per FR-011 this is recorded as unsupported-or-deferred/"
                "not-found (needs research), NEVER defaulted to "
                "named-gui-fallback." % DEFAULT_OPS_PATH
            ),
        }
        f = evidence.finding(
            id="fallback_inventory.%s" % _slug(name),
            statement=(
                "Operation '%s' (why: %s) has no classification entry; recorded "
                "as unsupported-or-deferred pending research, not defaulted to "
                "GUI." % (name, why)
            ),
            strength=evidence.EvidenceStrength.NOT_FOUND,
            evidence="no matching entry in OPERATION_CLASSIFICATIONS",
        )
        return {"row": row, "finding": f}

    route = spec["route"]
    strength = spec["offline_strength"]
    notes = spec["rationale"]
    live_probe: Optional[Callable[[Any, Any, Any], bool]] = spec.get("live_probe")
    is_negative = bool(spec.get("live_probe_is_negative_evidence"))

    live_note = "not attempted (no live connection)"
    if connected and live_probe is not None:
        try:
            found = bool(live_probe(project, media_pool, timeline))
        except Exception as exc:  # introspection must never crash the probe
            found = False
            live_note = "live introspection raised %s: %s" % (type(exc).__name__, exc)
        else:
            if is_negative:
                # For silence detection: "found" here means a silence-ish method
                # DOES exist (surprising); "not found" CONFIRMS (not causes) the
                # external-tooling route already fixed above (FR-011).
                if found:
                    live_note = (
                        "live introspection unexpectedly found a silence/loudness-"
                        "named method (%s) — route intentionally left as "
                        "external-tooling pending manual review; this is "
                        "surprising evidence, not an automatic reclassification."
                        % spec["live_target_desc"]
                    )
                    strength = evidence.EvidenceStrength.OBSERVED_PASS
                else:
                    live_note = (
                        "live introspection confirmed no silence/loudness "
                        "primitive is exposed (%s) — reinforces, does not "
                        "cause, the external-tooling classification (FR-011)"
                        % spec["live_target_desc"]
                    )
                    strength = evidence.EvidenceStrength.OBSERVED_FAIL
            else:
                if found:
                    strength = evidence.EvidenceStrength.OBSERVED_PASS
                    live_note = "live introspection confirmed %s is present" % spec[
                        "live_target_desc"
                    ]
                else:
                    # Absence on THIS live object never downgrades/redirects the
                    # route (FR-011) — it only means live evidence didn't firm
                    # up further than the documented baseline this run (e.g. no
                    # timeline/media pool open yet).
                    live_note = (
                        "live introspection did NOT find %s on the live object "
                        "available this run (route unchanged per FR-011; kept "
                        "as documented baseline: %s)" % (spec["live_target_desc"], strength.value)
                    )
    elif connected and live_probe is None:
        live_note = "no live introspection defined for this operation"

    row = {
        "operation": name,
        "route": route,
        "strength": strength.value if isinstance(strength, evidence.EvidenceStrength) else strength,
        "notes": notes + " | live: " + live_note,
    }
    f = evidence.finding(
        id="fallback_inventory.%s" % _slug(name),
        statement="'%s' classified as %s." % (name, route),
        strength=strength,
        evidence=notes + " | live: " + live_note,
    )
    return {"row": row, "finding": f}


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
