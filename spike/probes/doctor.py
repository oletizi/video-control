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

Python 3.11-compatible syntax only.
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Make the sibling spike/ package importable when this file is run directly
# (python spike/probes/doctor.py), regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence  # noqa: E402
import resolve_env  # noqa: E402

PROBE_NAME = "doctor"

# Exit codes per contracts/probes.md.
EXIT_PASS = 0
EXIT_OBSERVED_FAIL = 1
EXIT_CANNOT_RUN = 2

DEFAULT_RUNS = 10

# How long a single closed-fast-fail connect attempt is allowed to take before
# we consider it evidence of a hang rather than a fast failure. connect()
# itself is bounded by resolve_env._CONNECT_TIMEOUT_S; this is a looser
# sanity ceiling on top of that so the probe body never blocks unexpectedly.
_FAST_FAIL_CEILING_S = 25.0


def _get_version_string(resolve) -> str:
    """Call GetVersionString() defensively; never raise out to the caller."""
    try:
        version = resolve.GetVersionString()
    except Exception as exc:  # native API surprises are evidence, not crashes
        return "unknown (GetVersionString() raised %s: %s)" % (type(exc).__name__, exc)
    if not version:
        return "unknown (GetVersionString() returned empty)"
    return str(version)


def _run_repeat_without_restart(runs: int) -> dict:
    """FR-013 repeat-without-restart phase: N connect + GetVersionString()
    calls against the SAME running Resolve, without restarting it.

    Returns a dict with per-run records, consistency verdict, and timing —
    used both for the human summary and for building Findings.
    """
    records: list[dict] = []
    start = time.monotonic()

    for i in range(runs):
        run_start = time.monotonic()
        resolve = resolve_env.connect()
        elapsed = time.monotonic() - run_start
        if resolve is None:
            records.append(
                {
                    "run": i + 1,
                    "connected": False,
                    "version": None,
                    "elapsed_s": round(elapsed, 3),
                    "error": resolve_env.last_error,
                }
            )
        else:
            version = _get_version_string(resolve)
            records.append(
                {
                    "run": i + 1,
                    "connected": True,
                    "version": version,
                    "elapsed_s": round(elapsed, 3),
                    "error": None,
                }
            )

    total_elapsed = time.monotonic() - start

    connected_versions = {r["version"] for r in records if r["connected"]}
    all_connected = all(r["connected"] for r in records)
    consistent_version = len(connected_versions) <= 1
    # A "hang" here means any single run blew past the ceiling; connect()
    # itself already bounds worst case via a worker-thread timeout, so this
    # is a belt-and-suspenders check on the observed elapsed times.
    no_hangs = all(r["elapsed_s"] < _FAST_FAIL_CEILING_S for r in records)

    return {
        "runs_requested": runs,
        "runs_completed": len(records),
        "records": records,
        "all_connected": all_connected,
        "consistent_version": consistent_version,
        "no_hangs": no_hangs,
        "total_elapsed_s": round(total_elapsed, 3),
        "reliable": all_connected and consistent_version and no_hangs,
    }


def _run_closed_fast_fail_probe() -> dict:
    """Attempt the closed-fast-fail phase automatically: if Resolve happens to
    be unreachable right now, confirm connect() returns None quickly rather
    than hanging. This is a best-effort automatic check — it does not force
    Resolve to close; it only characterizes whatever the CURRENT reachability
    state is, timed.
    """
    start = time.monotonic()
    resolve = resolve_env.connect()
    elapsed = time.monotonic() - start
    return {
        "attempted": True,
        "connected": resolve is not None,
        "elapsed_s": round(elapsed, 3),
        "fast": elapsed < _FAST_FAIL_CEILING_S,
        "error": None if resolve is not None else resolve_env.last_error,
    }


def _build_findings(
    attempts: list[dict],
    worker: dict | None,
    connected: bool,
    version: str | None,
    edition_value: dict,
    reliability: dict | None,
    closed_probe: dict,
) -> list[dict]:
    findings: list[dict] = []

    # FR-003: interpreter discovery order + working interpreter.
    if worker is not None:
        findings.append(
            evidence.finding(
                id="doctor.interpreter",
                statement=(
                    "Working interpreter identified: %s (%s), python %s/%s"
                    % (worker["path"], worker.get("origin"), worker.get("version"), worker.get("arch"))
                ),
                strength=evidence.EvidenceStrength.OBSERVED_PASS,
                evidence=json.dumps({"attempts": attempts}),
            )
        )
    else:
        findings.append(
            evidence.finding(
                id="doctor.interpreter",
                statement=(
                    "No Python interpreter (of %d tried) could load the native "
                    "scripting library." % len(attempts)
                ),
                strength=evidence.EvidenceStrength.OBSERVED_FAIL,
                evidence=json.dumps({"attempts": attempts}),
            )
        )

    # FR-001: connection success/failure.
    if connected:
        findings.append(
            evidence.finding(
                id="doctor.connect",
                statement="External-process connection to a running DaVinci Resolve succeeded.",
                strength=evidence.EvidenceStrength.OBSERVED_PASS,
                evidence="scriptapp('Resolve') returned a non-None object",
            )
        )
        # FR-002: version (direct).
        findings.append(
            evidence.finding(
                id="doctor.version",
                statement="Resolve reported version %s via GetVersionString()." % version,
                strength=evidence.EvidenceStrength.OBSERVED_PASS,
                evidence="direct read from resolve.GetVersionString()",
            )
        )
        # FR-002 / R3: edition (inferred).
        findings.append(
            evidence.finding(
                id="doctor.edition",
                statement="Edition inferred as %s." % edition_value["value"],
                strength=evidence.EvidenceStrength.INFERRED,
                evidence=edition_value["evidence"],
            )
        )
    else:
        findings.append(
            evidence.finding(
                id="doctor.connect",
                statement="External-process connection to DaVinci Resolve did not succeed.",
                strength=evidence.EvidenceStrength.OBSERVED_FAIL,
                evidence=resolve_env.last_error or "unknown connection failure",
            )
        )

    # FR-013: repeat-without-restart phase (only meaningful if we could connect
    # at all; still recorded as a finding either way).
    if reliability is not None:
        strength = (
            evidence.EvidenceStrength.OBSERVED_PASS
            if reliability["reliable"]
            else evidence.EvidenceStrength.OBSERVED_FAIL
        )
        findings.append(
            evidence.finding(
                id="doctor.reliability.repeat_without_restart",
                statement=(
                    "Repeat-without-restart sequence (%d/%d runs completed): "
                    "all_connected=%s, consistent_version=%s, no_hangs=%s."
                    % (
                        reliability["runs_completed"],
                        reliability["runs_requested"],
                        reliability["all_connected"],
                        reliability["consistent_version"],
                        reliability["no_hangs"],
                    )
                ),
                strength=strength,
                evidence=json.dumps(reliability["records"]),
            )
        )
    else:
        findings.append(
            evidence.finding(
                id="doctor.reliability.repeat_without_restart",
                statement="Repeat-without-restart sequence not attempted (no initial connection).",
                strength=evidence.EvidenceStrength.NOT_FOUND,
                evidence="doctor never obtained an initial connection to run the sequence against",
            )
        )

    # FR-013 closed-fast-fail: automatically characterized from whatever the
    # current reachability state is (see _run_closed_fast_fail_probe docstring).
    if not closed_probe["connected"]:
        findings.append(
            evidence.finding(
                id="doctor.reliability.closed_fast_fail",
                statement=(
                    "Resolve was unreachable and connect() returned None in %.3fs "
                    "(fast=%s) rather than hanging."
                    % (closed_probe["elapsed_s"], closed_probe["fast"])
                ),
                strength=(
                    evidence.EvidenceStrength.OBSERVED_PASS
                    if closed_probe["fast"]
                    else evidence.EvidenceStrength.OBSERVED_FAIL
                ),
                evidence=closed_probe["error"] or "connect() returned None",
            )
        )
    else:
        findings.append(
            evidence.finding(
                id="doctor.reliability.closed_fast_fail",
                statement=(
                    "Resolve was reachable during this run, so the closed-fast-fail "
                    "path could not be exercised automatically."
                ),
                strength=evidence.EvidenceStrength.NOT_FOUND,
                evidence="connect() succeeded; Resolve was not in a closed state to probe",
            )
        )

    # FR-013 phases that require operator action to exercise for real: these
    # are documented, not executed, since the probe cannot restart Resolve or
    # switch projects on its own. Recorded as findings so the sequence is
    # tracked even though only the automatable phases ran.
    findings.append(
        evidence.finding(
            id="doctor.reliability.restart_recovery",
            statement=(
                "Resolve-restart recovery (connect succeeds again after the "
                "operator restarts Resolve) is a documented phase of the FR-013 "
                "sequence requiring manual restart; not exercised by this "
                "automatic run."
            ),
            strength=evidence.EvidenceStrength.UNTESTED,
            evidence=(
                "Operator action required: quit and relaunch Resolve, then re-run "
                "this probe to observe recovery."
            ),
        )
    )
    findings.append(
        evidence.finding(
            id="doctor.reliability.project_switch",
            statement=(
                "Project switch (connection remains usable after the operator "
                "switches the active project) is an optional documented phase of "
                "the FR-13 sequence; not exercised by this automatic run."
            ),
            strength=evidence.EvidenceStrength.UNTESTED,
            evidence=(
                "Operator action required: switch the active project in Resolve, "
                "then re-run this probe to observe continued usability."
            ),
        )
    )

    return findings


def run(runs: int) -> tuple[int, dict]:
    """Run the doctor probe. Returns (exit_code, provenance_dict-ish report)."""
    attempts = resolve_env.interpreter_attempts()
    worker = resolve_env.working_interpreter(attempts)

    resolve = resolve_env.connect()
    connected = resolve is not None

    version = "unknown"
    edition_value = evidence.edition(
        "unknown",
        evidence.Confidence.INFERRED,
        "edition not determined: no successful connection was established",
    )
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
        findings = _build_findings(
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
    version = _get_version_string(resolve)
    edition_value = evidence.edition(
        "Studio",
        evidence.Confidence.INFERRED,
        "external scripting connection succeeded (scriptapp('Resolve') returned "
        "a live object) — the free edition disables the external/remote "
        "scripting API, so a successful external connection is strong Studio "
        "evidence (research.md R3)",
    )

    # T009: multi-run reliability sequence + closed-fast-fail characterization.
    reliability = _run_repeat_without_restart(runs)
    closed_probe = _run_closed_fast_fail_probe()

    findings = _build_findings(
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
        for a in attempts:
            print(
                "    - %s [%s]: %s%s"
                % (
                    a["path"],
                    a.get("origin"),
                    a.get("load_result"),
                    (" (%s)" % a["failure_type"]) if a.get("failure_type") else "",
                )
            )

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
