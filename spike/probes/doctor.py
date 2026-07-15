"""doctor probe (US1) — connection, version, edition, interpreter.

THROWAWAY spike code (see spike/README.md). Implements T008-T010 of
specs/001-resolve-discovery-spike/tasks.md against the contract in
specs/001-resolve-discovery-spike/contracts/probes.md:

  T008: connect via resolve_env; report Resolve version (direct) and edition
        (inferred, with evidence — a successful external scripting connection
        is strong Studio evidence, research R3); emit the ordered
        interpreter_attempts() list identifying the working interpreter
        (FR-001 / FR-002 / FR-003).
  T009: multi-run reliability sequence (FR-013): repeat-without-restart (N
        repeat connect + GetVersionString() calls without restarting Resolve,
        checked for consistency and no hangs), plus documented findings for
        the phases that need operator action to exercise for real (Resolve
        closed -> fast-fail, Resolve restarted -> recovery, project switch).
        The probe DOES attempt the closed-fast-fail check itself by verifying
        connect() returns None quickly when Resolve is unreachable.
  T010: shared probe CLI contract (contracts/probes.md): argparse --runs/--json,
        exit 0 PASS / 1 observed-FAIL / 2 cannot-run, provenance + findings
        written to spike/findings/raw/doctor.json via evidence.write_probe_result.

This talks to a LIVE Resolve that may not be running. That is an expected,
first-class case: the probe must diagnose and exit 2, never hang or crash.

The pure helpers this flow relies on (edition inference, the FR-013
multi-run reliability sequence, finding assembly, interpreter-attempt
formatting) live in the sibling doctor_support.py module, split out purely
to keep both files under the project's line-count guideline.

Python 3.11-compatible syntax only.
"""

import argparse
import json
import sys
from pathlib import Path

# Make the sibling spike/ package importable when this file is run directly
# (python spike/probes/doctor.py), regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import doctor_support  # noqa: E402
import evidence  # noqa: E402
import resolve_env  # noqa: E402

PROBE_NAME = "doctor"

# Exit codes per contracts/probes.md.
EXIT_PASS = 0
EXIT_OBSERVED_FAIL = 1
EXIT_CANNOT_RUN = 2

DEFAULT_RUNS = 10


def _get_last_error() -> str | None:
    """Accessor for resolve_env's module-level last_error, injected into the
    doctor_support helpers so they never import resolve_env directly.
    """
    return resolve_env.last_error


def run(runs: int) -> tuple[int, dict]:
    """Run the doctor probe. Returns (exit_code, provenance_dict-ish report)."""
    attempts = resolve_env.interpreter_attempts()
    worker = resolve_env.working_interpreter(attempts)

    resolve = resolve_env.connect()
    connected = resolve is not None

    version = "unknown"
    edition_value = doctor_support.infer_edition(False)
    reliability = None
    diagnosis = None

    if not connected:
        # CANNOT-RUN: no working interpreter OR Resolve unreachable. Fail fast
        # per FR-014 — never hang. diagnose_connection_failure() names the
        # specific gate (interpreter vs connection/edition/permission).
        diagnosis = resolve_env.diagnose_connection_failure(attempts)
        closed_probe = {
            "attempted": True,
            "connected": False,
            "elapsed_s": 0.0,
            "fast": True,
            "error": resolve_env.last_error,
        }
        findings = doctor_support.build_findings(
            attempts, worker, connected, None, edition_value, reliability, closed_probe
        )
        # cannot-run is UNTESTED evidence, NOT an observed failure: a probe that
        # could not connect gathered no gate evidence. Writing SKIPPED (not FAIL)
        # keeps this consistent with the other 7 probes and prevents decision.py
        # from fabricating a NO-GO from a "Resolve not running" condition (FR-016).
        provenance = evidence.build_provenance(
            probe=PROBE_NAME,
            result=evidence.ProbeOutcome.SKIPPED,
            resolve_version=version,
            resolve_edition=edition_value,
        )
        findings.append(
            evidence.finding(
                id="doctor.diagnosis",
                statement="Fail-fast diagnosis for the unreachable/cannot-run case.",
                strength=evidence.EvidenceStrength.NOT_FOUND,
                evidence=diagnosis,
            )
        )
        out_path = evidence.write_probe_result(
            PROBE_NAME, provenance, findings, evidence.ProbeOutcome.SKIPPED
        )
        report = {
            "provenance": provenance,
            "findings": findings,
            "interpreter_attempts": attempts,
            "working_interpreter": worker,
            "diagnosis": diagnosis,
            "raw_ref": str(out_path),
        }
        return EXIT_CANNOT_RUN, report

    # Connected: version (direct) + edition (inferred, R3).
    version = doctor_support.get_version_string(resolve)
    edition_value = doctor_support.infer_edition(True)

    # T009: multi-run reliability sequence + closed-fast-fail characterization.
    reliability = doctor_support.run_repeat_without_restart(
        runs, resolve_env.connect, _get_last_error
    )
    closed_probe = doctor_support.run_closed_fast_fail_probe(
        resolve_env.connect, _get_last_error
    )

    findings = doctor_support.build_findings(
        attempts, worker, connected, version, edition_value, reliability, closed_probe
    )

    outcome = evidence.ProbeOutcome.PASS if reliability["reliable"] else evidence.ProbeOutcome.FAIL
    provenance = evidence.build_provenance(
        probe=PROBE_NAME,
        result=outcome,
        resolve_version=version,
        resolve_edition=edition_value,
    )
    out_path = evidence.write_probe_result(PROBE_NAME, provenance, findings, outcome)

    report = {
        "provenance": provenance,
        "findings": findings,
        "interpreter_attempts": attempts,
        "working_interpreter": worker,
        "reliability": reliability,
        "closed_fast_fail_probe": closed_probe,
        "raw_ref": str(out_path),
    }
    exit_code = EXIT_PASS if reliability["reliable"] else EXIT_OBSERVED_FAIL
    return exit_code, report


def _print_human_summary(exit_code: int, report: dict) -> None:
    provenance = report["provenance"]
    print("doctor probe — result: %s" % provenance["result"])
    print("  resolve_version : %s" % provenance["resolve_version"])
    edition_value = provenance["resolve_edition"]
    print(
        "  edition         : %s (confidence=%s)"
        % (edition_value["value"], edition_value["confidence"])
    )

    worker = report.get("working_interpreter")
    if worker is not None:
        print("  working interp  : %s (%s)" % (worker["path"], worker.get("origin")))
    else:
        print("  working interp  : NONE — no interpreter loaded the native library")

    attempts = report.get("interpreter_attempts")
    if attempts:
        print("  interpreter attempts (in discovery order):")
        for line in doctor_support.format_interpreter_attempts(attempts):
            print(line)

    reliability = report.get("reliability")
    if reliability is not None:
        print(
            "  reliability     : reliable=%s (all_connected=%s, consistent_version=%s, "
            "no_hangs=%s, %d/%d runs)"
            % (
                reliability["reliable"],
                reliability["all_connected"],
                reliability["consistent_version"],
                reliability["no_hangs"],
                reliability["runs_completed"],
                reliability["runs_requested"],
            )
        )

    diagnosis = report.get("diagnosis")
    if diagnosis:
        print("  diagnosis       : %s" % diagnosis)

    print("  raw evidence    : %s" % report.get("raw_ref"))
    print("  exit code       : %d" % exit_code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doctor.py",
        description=(
            "US1 doctor probe: connection, version, edition, interpreter, and "
            "the FR-013 multi-run reliability sequence."
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help="number of repeat-without-restart connect+GetVersionString calls (default: %d)"
        % DEFAULT_RUNS,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full JSON report to stdout instead of the human summary",
    )
    args = parser.parse_args(argv)

    if args.runs < 1:
        parser.error("--runs must be >= 1")

    exit_code, report = run(args.runs)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human_summary(exit_code, report)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
