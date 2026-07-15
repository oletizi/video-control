"""Pure helpers for the build probe (US3) — split out of build.py.

THROWAWAY spike code (see spike/README.md). Everything here takes its
Resolve objects (project_manager / project / media_pool / timeline) as
arguments rather than reaching for global state, so it can be exercised or
read independently of the CLI entrypoint in build.py.

Contents:
  - guarded_call: never-raise wrapper around a native Resolve API call.
  - get_or_create_project / find_timeline_by_name: small finding-producing
    helpers used while assembling the timeline.
  - run_build_once: the full T013 sequence (import media -> create timeline
    -> append clip -> add marker).
  - classify_idempotency: the T014 cross-run idempotency classification.

Python 3.11-compatible syntax only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

# spike/ must be importable so the shared evidence module can be reused, same
# as build.py. This mirrors build.py's own sys.path setup defensively, in
# case this module is ever imported before build.py has done so.
SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(SPIKE_ROOT))

import evidence  # noqa: E402
from evidence import EvidenceStrength  # noqa: E402

FIXTURE_MEDIA_DIR = SPIKE_ROOT / "fixtures" / "media"
VIDEO_FIXTURE = FIXTURE_MEDIA_DIR / "fixture-video.mov"
AUDIO_FIXTURE = FIXTURE_MEDIA_DIR / "fixture-tone.wav"

TIMELINE_NAME = "Spike Timeline"
MARKER_FRAME = 48
MARKER_COLOR = "Blue"
MARKER_NAME = "Spike Marker"
MARKER_NOTE = "Added by spike/probes/build.py"
MARKER_DURATION = 1
MARKER_CUSTOM_DATA = ""


# --------------------------------------------------------------------------- #
# Guarded API call helper — never let a native call crash the probe.
# --------------------------------------------------------------------------- #


def guarded_call(fn: Any, *args: Any, **kwargs: Any) -> tuple[bool, Any, Optional[str]]:
    """Call ``fn(*args, **kwargs)``, never raising.

    Returns ``(ok, value, error)``. ``ok`` is False for any exception
    (AttributeError included — e.g. a method absent on this Resolve version)
    as well as for a callable that isn't actually callable (``fn`` is None).
    """
    if fn is None:
        return False, None, "method not available on this object (None)"
    try:
        return True, fn(*args, **kwargs), None
    except Exception as exc:  # noqa: BLE001 — deliberately broad, this is a probe
        return False, None, f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- #
# Project setup
# --------------------------------------------------------------------------- #


def get_or_create_project(project_manager: Any, name: str) -> tuple[Any, str]:
    """Load ``name`` if it already exists, else create it. Returns (project, note)."""
    ok, project, err = guarded_call(getattr(project_manager, "LoadProject", None), name)
    if ok and project is not None:
        return project, f"loaded existing project '{name}'"

    ok2, project2, err2 = guarded_call(getattr(project_manager, "CreateProject", None), name)
    if ok2 and project2 is not None:
        return project2, f"created new project '{name}'"

    return None, f"LoadProject failed ({err}); CreateProject failed ({err2})"


def find_timeline_by_name(project: Any, name: str) -> Optional[Any]:
    """Best-effort scan of the project's timelines for an exact name match."""
    ok, count, _ = guarded_call(getattr(project, "GetTimelineCount", None))
    if not ok or not count:
        return None
    for index in range(1, int(count) + 1):
        ok_t, timeline, _ = guarded_call(getattr(project, "GetTimelineByIndex", None), index)
        if not ok_t or timeline is None:
            continue
        ok_n, timeline_name, _ = guarded_call(getattr(timeline, "GetName", None))
        if ok_n and timeline_name == name:
            return timeline
    return None


# --------------------------------------------------------------------------- #
# One build run (T013 sequence): import -> create timeline -> append -> marker
# --------------------------------------------------------------------------- #


def run_build_once(project_manager: Any, project_name: str, run_index: int) -> dict[str, Any]:
    """Perform the full build sequence once. Never raises.

    Returns a dict with ``ok`` (bool: timeline+clip+marker all created this
    run), ``findings`` (list of Finding dicts for this run), and ``observed``
    (a dict of raw counts/flags used by the cross-run idempotency comparison).
    """
    findings: list[dict[str, Any]] = []
    observed: dict[str, Any] = {
        "timeline_count_before": None,
        "timeline_count_after": None,
        "clip_count_before": None,
        "clip_count_after": None,
        "create_timeline_returned_none": None,
        "marker_added": False,
        "clip_appended": False,
        "errors": [],
    }

    def fail(step_id: str, statement: str, err: Optional[str]) -> None:
        observed["errors"].append({"step": step_id, "error": err})
        findings.append(
            evidence.finding(
                id=f"build.run{run_index}.{step_id}",
                statement=statement,
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=err or "no further detail",
            )
        )

    def ok_finding(step_id: str, statement: str, detail: str) -> None:
        findings.append(
            evidence.finding(
                id=f"build.run{run_index}.{step_id}",
                statement=statement,
                strength=EvidenceStrength.OBSERVED_PASS,
                evidence=detail,
            )
        )

    # --- Project -------------------------------------------------------- #
    project, project_note = get_or_create_project(project_manager, project_name)
    if project is None:
        fail("project", f"Could not load or create project '{project_name}'.", project_note)
        return {"ok": False, "findings": findings, "observed": observed}
    ok_finding("project", f"Project '{project_name}' is available.", project_note)

    # --- MediaPool -------------------------------------------------------- #
    ok, media_pool, err = guarded_call(getattr(project, "GetMediaPool", None))
    if not ok or media_pool is None:
        fail("media_pool", "project.GetMediaPool() did not return a MediaPool.", err)
        return {"ok": False, "findings": findings, "observed": observed}
    ok_finding("media_pool", "MediaPool obtained.", "project.GetMediaPool() succeeded")

    # --- Pre-import bin/timeline counts (for idempotency comparison) ----- #
    ok, root_folder, _ = guarded_call(getattr(media_pool, "GetRootFolder", None))
    if ok and root_folder is not None:
        ok_c, clip_list, _ = guarded_call(getattr(root_folder, "GetClipList", None))
        if ok_c and clip_list is not None:
            observed["clip_count_before"] = len(clip_list)
    ok, tcount, _ = guarded_call(getattr(project, "GetTimelineCount", None))
    if ok and tcount is not None:
        observed["timeline_count_before"] = int(tcount)

    # --- Import synthetic media (T013) ------------------------------------ #
    ok, imported_items, err = guarded_call(
        getattr(media_pool, "ImportMedia", None), [str(VIDEO_FIXTURE), str(AUDIO_FIXTURE)]
    )
    if not ok or not imported_items:
        fail(
            "import_media",
            "MediaPool.ImportMedia([fixture-video.mov, fixture-tone.wav]) did not "
            "return imported items.",
            err or "ImportMedia returned an empty/falsy result",
        )
        imported_items = []
    else:
        ok_finding(
            "import_media",
            f"Imported {len(imported_items)} media item(s) via MediaPool.ImportMedia.",
            f"paths=[{VIDEO_FIXTURE.name}, {AUDIO_FIXTURE.name}]",
        )

    ok, root_folder, _ = guarded_call(getattr(media_pool, "GetRootFolder", None))
    if ok and root_folder is not None:
        ok_c, clip_list, _ = guarded_call(getattr(root_folder, "GetClipList", None))
        if ok_c and clip_list is not None:
            observed["clip_count_after"] = len(clip_list)

    # --- Create timeline (T013) ------------------------------------------- #
    ok, timeline, err = guarded_call(
        getattr(media_pool, "CreateEmptyTimeline", None), TIMELINE_NAME
    )
    if not ok:
        fail(
            "create_timeline",
            f"MediaPool.CreateEmptyTimeline('{TIMELINE_NAME}') raised.",
            err,
        )
        timeline = None
    elif timeline is None:
        # A guarded, non-crashing None is itself idempotency-relevant evidence
        # (e.g. some versions refuse a duplicate-named timeline) — record it
        # as a gap, then fall back to locating any existing timeline so the
        # rest of the sequence can still be attempted.
        observed["create_timeline_returned_none"] = True
        findings.append(
            evidence.finding(
                id=f"build.run{run_index}.create_timeline",
                statement=(
                    f"MediaPool.CreateEmptyTimeline('{TIMELINE_NAME}') returned None "
                    "instead of raising or returning a Timeline."
                ),
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence="possible duplicate-name gate or version variance; see research.md R5",
            )
        )
        timeline = find_timeline_by_name(project, TIMELINE_NAME)
    else:
        observed["create_timeline_returned_none"] = False
        ok_finding(
            "create_timeline",
            f"Timeline '{TIMELINE_NAME}' created.",
            "MediaPool.CreateEmptyTimeline() returned a Timeline object",
        )

    ok, tcount_after, _ = guarded_call(getattr(project, "GetTimelineCount", None))
    if ok and tcount_after is not None:
        observed["timeline_count_after"] = int(tcount_after)

    if timeline is None:
        fail(
            "timeline_missing",
            f"No usable timeline named '{TIMELINE_NAME}' after create attempt.",
            "CreateEmptyTimeline failed/None and no existing timeline of that name was found",
        )
        return {"ok": False, "findings": findings, "observed": observed}

    # Make the freshly-created (or recovered) timeline current before
    # appending — guarded, non-fatal: some Resolve versions already set the
    # newly created timeline as current automatically.
    guarded_call(getattr(project, "SetCurrentTimeline", None), timeline)

    # --- Place a clip (T013) ----------------------------------------------- #
    video_item = None
    for item in imported_items:
        ok_name, item_name, _ = guarded_call(getattr(item, "GetName", None))
        if ok_name and item_name == VIDEO_FIXTURE.name:
            video_item = item
            break
    if video_item is None and imported_items:
        video_item = imported_items[0]  # best-effort fallback

    if video_item is None:
        fail(
            "append_clip",
            "No MediaPoolItem available to append (import step produced nothing usable).",
            "imported_items was empty",
        )
    else:
        ok, appended, err = guarded_call(
            getattr(media_pool, "AppendToTimeline", None), [video_item]
        )
        if ok and appended:
            observed["clip_appended"] = True
            ok_finding(
                "append_clip",
                f"Clip '{VIDEO_FIXTURE.name}' appended to timeline '{TIMELINE_NAME}'.",
                "MediaPool.AppendToTimeline([video_item]) returned a non-empty result",
            )
        else:
            fail(
                "append_clip",
                f"MediaPool.AppendToTimeline([{VIDEO_FIXTURE.name}]) did not place a clip.",
                err or "AppendToTimeline returned an empty/falsy result",
            )

    # --- Add a marker (T013) ------------------------------------------------ #
    ok, marker_result, err = guarded_call(
        getattr(timeline, "AddMarker", None),
        MARKER_FRAME,
        MARKER_COLOR,
        MARKER_NAME,
        MARKER_NOTE,
        MARKER_DURATION,
        MARKER_CUSTOM_DATA,
    )
    if ok and marker_result:
        observed["marker_added"] = True
        ok_finding(
            "add_marker",
            f"Marker '{MARKER_NAME}' added at frame {MARKER_FRAME}.",
            "Timeline.AddMarker(...) returned truthy",
        )
    else:
        fail(
            "add_marker",
            f"Timeline.AddMarker(frame={MARKER_FRAME}, name='{MARKER_NAME}') failed.",
            err or "AddMarker returned an empty/falsy result",
        )

    run_ok = bool(timeline is not None and observed["clip_appended"] and observed["marker_added"])
    return {"ok": run_ok, "findings": findings, "observed": observed}


# --------------------------------------------------------------------------- #
# T014 — cross-run idempotency classification
# --------------------------------------------------------------------------- #


def classify_idempotency(run_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare run 1 vs run 2 (etc.) and record what actually happened.

    Never assumes idempotent/non-idempotent behavior — classifies into
    duplicate / no-op / error / indeterminate strictly from observed counts,
    and returns a Finding either way (T014, FR-005).
    """
    first, second = run_results[0]["observed"], run_results[1]["observed"]
    label = "indeterminate"
    detail_parts = [
        f"run1 timeline_count(before={first['timeline_count_before']}, "
        f"after={first['timeline_count_after']})",
        f"run2 timeline_count(before={second['timeline_count_before']}, "
        f"after={second['timeline_count_after']})",
        f"run2 create_timeline_returned_none={second['create_timeline_returned_none']}",
        f"run2 errors={second['errors']}",
    ]

    if second["errors"] and not run_results[1]["ok"]:
        label = "error"
    elif (
        first["timeline_count_after"] is not None
        and second["timeline_count_before"] is not None
        and second["timeline_count_after"] is not None
    ):
        if second["timeline_count_after"] > second["timeline_count_before"]:
            # A second timeline object got created under the same requested
            # name -> Resolve does not dedupe by name; re-running duplicates.
            label = "duplicate"
        elif second["timeline_count_after"] == second["timeline_count_before"]:
            # No new timeline appeared; either creation was refused (None,
            # handled by falling back to the existing timeline) or Resolve
            # itself reused the existing named timeline.
            label = "no-op"

    strength = EvidenceStrength.OBSERVED_PASS if label != "indeterminate" else EvidenceStrength.NOT_FOUND
    statement = (
        f"Re-running the build sequence against timeline '{TIMELINE_NAME}' was observed to: {label}."
    )
    return evidence.finding(
        id="build.idempotency",
        statement=statement,
        strength=strength,
        evidence="; ".join(detail_parts),
    )
