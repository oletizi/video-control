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

The pure helper functions (object resolution, accessor probing, persistence
comparison, harness-managed-identity assessment, save/reload mechanics) live in
the sibling spike/probes/identity_support.py module, kept separate so this file
holds only the CLI entry point and the top-level orchestration flow.
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
from pathlib import Path  # noqa: E402
from typing import Optional  # noqa: E402

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

# Stdlib `inspect` is already imported (and cached in sys.modules) by the
# `import argparse` above, so it's now safe to restore this script's own
# directory to sys.path for the sibling identity_support import below without
# re-triggering the `inspect.py` shadow described above.
if _PROBES_DIR not in sys.path:
    sys.path.insert(0, _PROBES_DIR)

from identity_support import (  # noqa: E402
    _any_native_id_observed,
    assess_harness_managed_identity,
    check_harness_tag_persistence,
    collect_objects,
    compare_persistence,
    probe_identifiers,
    save_and_reload,
)

PROBE_NAME = "identity"


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
