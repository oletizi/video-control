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
The guarded-call helper and the export/duplicate/fallback implementations live
in ``snapshot_support.py`` (pure functions over resolve/project/timeline
arguments); this file is the CLI entrypoint and top-level orchestration.

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
import sys
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
from snapshot_support import (  # noqa: E402
    _safe,
    run_duplicate_mode,
    run_export_mode,
    run_fallback_eval,
)

PROBE_NAME = "snapshot"


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
