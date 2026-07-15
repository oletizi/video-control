"""Render probe (US4) for the Resolve discovery spike — T015/T016.

THROWAWAY spike code (see spike/README.md). Answers: can a render be enqueued
and reliably observed to completion through the Resolve scripting API, and
does the probe behave under explicit timeout/stall semantics instead of
hanging (FR-006, FR-014, US4; research.md R6)?

Flow (contracts/probes.md "render" section):
  connect -> GetRenderPresetList()/LoadRenderPreset() -> SetRenderSettings()
  (TargetDir + CustomName) -> AddRenderJob() -> StartRendering(jobId) ->
  poll GetRenderJobStatus(jobId) (JobStatus, CompletionPercentage) on the
  poll interval, subject to an overall timeout AND a stall threshold
  (CompletionPercentage unchanged for --stall seconds).

On timeout or stall: record the last-known JobStatus/CompletionPercentage,
attempt StopRendering(), write evidence, exit non-zero. NEVER hang. On
success: confirm the output file exists in --out with non-zero size.

CLI contract (contracts/probes.md, shared):
  exit 0  PASS            completed within timeout, output present non-zero.
  exit 1  FAIL / STALL    observed failure or stall, recorded with last status.
  exit 2  CANNOT-RUN      Resolve unreachable — fail fast, no hang.

Design constraints:
  - Python 3.11-compatible syntax ONLY.
  - Every Resolve API call is guarded (native calls can raise, return None,
    or return falsy sentinels) — nothing here may crash out or hang the
    operator, even against a live app in an unexpected state.

The guarded-call helper, the preset-load/render-settings/enqueue steps, the
FR-006 timeout/stall poll loop, and output-file confirmation all live in
``render_support.py`` (pure functions over resolve/project/job arguments);
this file is the CLI entrypoint and top-level orchestration.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

# --------------------------------------------------------------------------- #
# Make sibling spike modules (resolve_env, evidence, render_support)
# importable regardless of the caller's CWD, per the probe contract ("Add
# spike/ to sys.path").
# --------------------------------------------------------------------------- #
_SCRIPT_DIR = Path(__file__).resolve().parent  # spike/probes/
_SPIKE_ROOT = _SCRIPT_DIR.parent  # spike/
if str(_SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPIKE_ROOT))

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

# render_support.py is this probe's own sibling module in spike/probes/ (the
# script's own directory, which CPython auto-inserts at sys.path[0] before
# this file starts running) — import it now, before the strip below removes
# that directory from sys.path.
import render_support as rs  # noqa: E402
import argparse  # noqa: E402

# CPython auto-inserts the running script's own directory (spike/probes/) at
# sys.path[0]. Everything this probe needs FROM that directory (render_support,
# just imported above) is now safely in sys.modules, so drop the directory
# from sys.path rather than leave it in place for the rest of this process's
# lifetime: a sibling probe module can collide with a stdlib module name (e.g.
# a `spike/probes/inspect.py` probe shadowing the stdlib `inspect` module that
# argparse's help formatting imports lazily on newer Pythons), and that lazy
# import happens later, inside _parse_args() below — so this drop still needs
# to happen before then, and it does (module load time, before main() runs).
_script_dir_str = str(_SCRIPT_DIR)
sys.path[:] = [p for p in sys.path if p != _script_dir_str]

PROBE_NAME = "render"

DEFAULT_TIMEOUT_S = 300.0
DEFAULT_POLL_S = 2.0
DEFAULT_STALL_S = 60.0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="render.py",
        description=(
            "Render probe (US4): enqueue a render from a preset and observe it "
            "to completion under an explicit timeout/stall contract (FR-006)."
        ),
    )
    parser.add_argument(
        "--preset",
        default=None,
        help=(
            "Render preset name to load via LoadRenderPreset(). Defaults to "
            "the first entry returned by GetRenderPresetList()."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="Overall wall-clock budget in seconds for the render to finish (default: %(default)s).",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=DEFAULT_POLL_S,
        help="Seconds between GetRenderJobStatus() polls (default: %(default)s).",
    )
    parser.add_argument(
        "--stall",
        type=float,
        default=DEFAULT_STALL_S,
        help=(
            "Seconds CompletionPercentage may stay unchanged before the run is "
            "classified as stalled (default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Render output (TargetDir). Defaults to a fresh temp directory.",
    )
    return parser.parse_args(argv)


# --------------------------------------------------------------------------- #
# Result plumbing
# --------------------------------------------------------------------------- #


def _emit(
    outcome: ProbeOutcome,
    findings: list[dict[str, Any]],
    *,
    resolve_version: str = "unknown",
    resolve_edition: Optional[dict[str, Any]] = None,
    summary: str,
) -> int:
    """Stamp provenance, write the raw ProbeResult, print a summary, and map
    the outcome to the CLI contract's exit code (0 PASS / 1 FAIL / 2 SKIPPED-as-cannot-run).
    """
    provenance = build_provenance(
        PROBE_NAME,
        outcome,
        resolve_version=resolve_version,
        resolve_edition=resolve_edition,
    )
    out_path = write_probe_result(PROBE_NAME, provenance, findings, outcome)
    print(summary)
    print(f"Evidence written to {out_path}")
    if outcome == ProbeOutcome.PASS:
        return 0
    if outcome == ProbeOutcome.SKIPPED:
        return 2
    return 1


def _cannot_run(reason: str, findings: list[dict[str, Any]]) -> int:
    """Resolve unreachable (or a hard gate before any mutation was attempted) —
    fail fast per FR-014. Exit 2.
    """
    findings.append(
        finding(
            id="render.cannot_run",
            statement="The render probe could not run against a live Resolve.",
            strength=EvidenceStrength.NOT_FOUND,
            evidence=reason,
        )
    )
    return _emit(
        ProbeOutcome.SKIPPED,
        findings,
        summary=f"CANNOT-RUN: {reason}",
    )


def _fail(
    findings: list[dict[str, Any]],
    step_findings: list[dict[str, Any]],
    fail_summary: str,
    *,
    resolve_version: str,
    resolve_edition: Optional[dict[str, Any]],
) -> int:
    """Append a failed step's findings and emit the standard FAIL result."""
    findings.extend(step_findings)
    return _emit(
        ProbeOutcome.FAIL,
        findings,
        resolve_version=resolve_version,
        resolve_edition=resolve_edition,
        summary=f"FAIL: {fail_summary}",
    )


# --------------------------------------------------------------------------- #
# Main probe logic
# --------------------------------------------------------------------------- #


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    findings: list[dict[str, Any]] = []

    # --- Connect (FR-014: fail fast, never hang) --------------------------- #
    resolve = resolve_env.connect()
    if resolve is None:
        return _cannot_run(resolve_env.diagnose_connection_failure(), findings)

    resolve_version, _ = rs.guarded_call(resolve.GetVersionString)
    resolve_version = resolve_version or "unknown"
    resolve_edition = edition(
        "Studio", Confidence.INFERRED, "external scripting connection succeeded"
    )

    project_manager, err = rs.guarded_call(resolve.GetProjectManager)
    if err or project_manager is None:
        return _cannot_run(
            err or "GetProjectManager() returned None", findings
        )

    project, err = rs.guarded_call(project_manager.GetCurrentProject)
    if err or project is None:
        return _cannot_run(
            err or "GetCurrentProject() returned None (no project open in Resolve)",
            findings,
        )

    # --- T015: load preset, set render settings, enqueue, start ----------- #
    preset_step = rs.load_preset(project, args.preset)
    if preset_step.fail_summary is not None:
        return _fail(
            findings, preset_step.findings, preset_step.fail_summary,
            resolve_version=resolve_version, resolve_edition=resolve_edition,
        )
    findings.extend(preset_step.findings)

    out_dir = args.out or tempfile.mkdtemp(prefix="resolve-render-probe-")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    custom_name = "render_probe_%d" % int(time.time())

    settings_step = rs.apply_render_settings(project, out_dir, custom_name)
    if settings_step.fail_summary is not None:
        return _fail(
            findings, settings_step.findings, settings_step.fail_summary,
            resolve_version=resolve_version, resolve_edition=resolve_edition,
        )
    findings.extend(settings_step.findings)

    enqueue_step = rs.enqueue_render_job(project)
    if enqueue_step.fail_summary is not None:
        return _fail(
            findings, enqueue_step.findings, enqueue_step.fail_summary,
            resolve_version=resolve_version, resolve_edition=resolve_edition,
        )
    findings.extend(enqueue_step.findings)
    job_id = enqueue_step.value

    start_step = rs.start_rendering(project, job_id)
    if start_step.fail_summary is not None:
        return _fail(
            findings, start_step.findings, start_step.fail_summary,
            resolve_version=resolve_version, resolve_edition=resolve_edition,
        )
    findings.extend(start_step.findings)

    # --- T016: explicit timeout/stall poll loop (FR-006) ------------------- #
    timeout_s = max(0.0, args.timeout)
    stall_s = max(0.0, args.stall)
    poll_s = max(rs.MIN_POLL_SLEEP_S, args.poll)

    poll_result = rs.poll_render_job(project, job_id, timeout_s, stall_s, poll_s)

    # --- Breach handling: timeout / stall / poll-error / non-complete ------ #
    if poll_result.outcome_kind in ("timeout", "stall", "poll-error", "terminal-non-complete"):
        breach_findings, summary = rs.handle_breach(project, job_id, poll_result)
        findings.extend(breach_findings)
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary=summary,
        )

    # --- Completed: confirm output file exists with non-zero size --------- #
    confirmation = rs.confirm_output(job_id, out_dir, custom_name, poll_result.elapsed_final, timeout_s)
    findings.extend(confirmation.findings)
    return _emit(
        ProbeOutcome.PASS if confirmation.kind == "ok" else ProbeOutcome.FAIL,
        findings,
        resolve_version=resolve_version,
        resolve_edition=resolve_edition,
        summary=confirmation.summary,
    )


if __name__ == "__main__":
    sys.exit(main())
