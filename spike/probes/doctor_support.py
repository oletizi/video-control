"""Pure helpers for the doctor probe (US1) — companion to doctor.py.

THROWAWAY spike code (see spike/README.md). Split out of doctor.py purely to
keep both files under the project's 300-500-line file-size guideline; the
CLI entrypoint + main flow stay in doctor.py, and this module holds:

  - edition inference (FR-002 / R3)
  - the FR-013 multi-run reliability sequence (repeat-without-restart +
    closed-fast-fail characterization)
  - the build_findings() helper that assembles every Finding doctor emits
  - interpreter-attempt formatting for the human-readable summary

Everything here is a function of its arguments only. In particular, the
reliability-sequence functions do not import resolve_env themselves — the
caller injects a ``connect`` callable (see resolve_env.connect) and a
``get_last_error`` accessor (see resolve_env.last_error) so this module's
only project import is ``evidence``.

Python 3.11-compatible syntax only.
"""

import json
import time
from typing import Callable, Optional

import evidence

# How long a single closed-fast-fail connect attempt is allowed to take before
# we consider it evidence of a hang rather than a fast failure. connect()
# itself is bounded by resolve_env._CONNECT_TIMEOUT_S; this is a looser
# sanity ceiling on top of that so the probe body never blocks unexpectedly.
FAST_FAIL_CEILING_S = 25.0


def get_version_string(resolve) -> str:
    """Call GetVersionString() defensively; never raise out to the caller."""
    try:
        version = resolve.GetVersionString()
    except Exception as exc:  # native API surprises are evidence, not crashes
        return "unknown (GetVersionString() raised %s: %s)" % (type(exc).__name__, exc)
    if not version:
        return "unknown (GetVersionString() returned empty)"
    return str(version)


def infer_edition(connected: bool) -> dict:
    """FR-002 / R3: infer the Resolve edition from connection success.

    A successful external scripting connection is strong Studio evidence (the
    free edition disables the external/remote scripting API); no connection
    means edition is simply undetermined.
    """
    if not connected:
        return evidence.edition(
            "unknown",
            evidence.Confidence.INFERRED,
            "edition not determined: no successful connection was established",
        )
    return evidence.edition(
        "Studio",
        evidence.Confidence.INFERRED,
        "external scripting connection succeeded (scriptapp('Resolve') returned "
        "a live object) — the free edition disables the external/remote "
        "scripting API, so a successful external connection is strong Studio "
        "evidence (research.md R3)",
    )


def format_interpreter_attempts(attempts: list[dict]) -> list[str]:
    """Render each InterpreterAttempt as one human-summary line, in order."""
    return [
        "    - %s [%s]: %s%s"
        % (
            a["path"],
            a.get("origin"),
            a.get("load_result"),
            (" (%s)" % a["failure_type"]) if a.get("failure_type") else "",
        )
        for a in attempts
    ]


def run_repeat_without_restart(
    runs: int,
    connect: Callable[[], object],
    get_last_error: Callable[[], Optional[str]],
) -> dict:
    """FR-013 repeat-without-restart phase: N connect + GetVersionString()
    calls against the SAME running Resolve, without restarting it.

    ``connect`` and ``get_last_error`` are injected (see resolve_env.connect /
    resolve_env.last_error) so this module stays free of a resolve_env import.

    Returns a dict with per-run records, consistency verdict, and timing —
    used both for the human summary and for building Findings.
    """
    records: list[dict] = []
    start = time.monotonic()

    for i in range(runs):
        run_start = time.monotonic()
        resolve = connect()
        elapsed = time.monotonic() - run_start
        if resolve is None:
            records.append(
                {
                    "run": i + 1,
                    "connected": False,
                    "version": None,
                    "elapsed_s": round(elapsed, 3),
                    "error": get_last_error(),
                }
            )
        else:
            version = get_version_string(resolve)
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
    no_hangs = all(r["elapsed_s"] < FAST_FAIL_CEILING_S for r in records)

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


def run_closed_fast_fail_probe(
    connect: Callable[[], object],
    get_last_error: Callable[[], Optional[str]],
) -> dict:
    """Attempt the closed-fast-fail phase automatically: if Resolve happens to
    be unreachable right now, confirm connect() returns None quickly rather
    than hanging. This is a best-effort automatic check — it does not force
    Resolve to close; it only characterizes whatever the CURRENT reachability
    state is, timed.
    """
    start = time.monotonic()
    resolve = connect()
    elapsed = time.monotonic() - start
    return {
        "attempted": True,
        "connected": resolve is not None,
        "elapsed_s": round(elapsed, 3),
        "fast": elapsed < FAST_FAIL_CEILING_S,
        "error": None if resolve is not None else get_last_error(),
    }


def build_findings(
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
                evidence=closed_probe.get("error") or "unknown connection failure",
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
    # current reachability state is (see run_closed_fast_fail_probe docstring).
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
