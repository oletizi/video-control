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

Bounded cases (research.md R10 / spec.md US7 acceptance scenario 1); the
implementation of each case lives in partial_failure_support.py:

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
import sys
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Make the shared spike modules (resolve_env, evidence) and this probe's
# support module importable. This file lives at spike/probes/partial_failure.py,
# so the spike root is one level up.
# --------------------------------------------------------------------------- #
_SPIKE_ROOT = Path(__file__).resolve().parent.parent
if str(_SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPIKE_ROOT))

import evidence  # noqa: E402
import resolve_env  # noqa: E402

import partial_failure_support as pfs  # noqa: E402


# --------------------------------------------------------------------------- #
# Dispatch + aggregation
# --------------------------------------------------------------------------- #


def run_case(name: str, resolve: Any, project: Any) -> dict:
    if name == "invalid_track":
        return pfs._case_invalid_track(resolve, project)
    if name == "missing_preset":
        return pfs._case_missing_preset(project)
    if name == "unwritable_dir":
        return pfs._case_unwritable_dir(project)
    if name == "resolve_closed_mid_poll":
        return pfs._case_resolve_closed_mid_poll(resolve, project)
    raise ValueError("unknown case %r" % name)


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
        choices=pfs.CASE_ORDER + ["all"],
        help="which failure case to run (default: all)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    cases_to_run = list(pfs.CASE_ORDER) if args.case == "all" else [args.case]

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
        project = pfs._ensure_scratch_project(resolve)
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
        findings.append(pfs._finding_for_case(name, result))
        print("[%s] %s -> %s" % (name, pfs.CASE_STATEMENTS[name], result["strength"]))

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
