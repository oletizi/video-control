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
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# Make sibling spike modules (resolve_env, evidence) importable regardless of
# the caller's CWD, per the probe contract ("Add spike/ to sys.path").
# --------------------------------------------------------------------------- #
_SCRIPT_DIR = Path(__file__).resolve().parent  # spike/probes/
_SPIKE_ROOT = _SCRIPT_DIR.parent  # spike/
if str(_SPIKE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPIKE_ROOT))

# CPython auto-inserts the running script's own directory (spike/probes/) at
# sys.path[0]. This probe needs nothing from spike/probes/ itself (only
# spike/ for resolve_env + evidence above), and a sibling probe module can
# collide with a stdlib module name (e.g. a `spike/probes/inspect.py` probe
# shadowing the stdlib `inspect` module that argparse's help formatting
# imports lazily on newer Pythons) — so drop it rather than risk an import
# collision that would crash this probe before it ever reaches Resolve.
_script_dir_str = str(_SCRIPT_DIR)
sys.path[:] = [p for p in sys.path if p != _script_dir_str]

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

PROBE_NAME = "render"

DEFAULT_TIMEOUT_S = 300.0
DEFAULT_POLL_S = 2.0
DEFAULT_STALL_S = 60.0

# Minimum sleep floor so a caller-supplied --poll of 0 (or negative) cannot
# turn the poll loop into a tight busy-spin.
_MIN_POLL_SLEEP_S = 0.05

# JobStatus strings the Resolve render API is documented to report once a job
# leaves the active "Rendering" state.
_TERMINAL_STATUSES = frozenset({"Complete", "Cancelled", "Failed"})


# --------------------------------------------------------------------------- #
# Guarded API-call helper
# --------------------------------------------------------------------------- #


def _guarded_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, Optional[str]]:
    """Call a Resolve API method, catching ANY exception it raises.

    The scripting API is an opaque native binding — a call can raise, block
    briefly, or simply return None/False on failure. Every touchpoint in this
    probe goes through this helper so a single unexpected native error can
    never crash the probe or leave it in an unguarded state.

    Returns ``(value, error)`` where ``error`` is ``None`` on success.
    """
    try:
        return func(*args, **kwargs), None
    except Exception as exc:  # noqa: BLE001 - deliberately broad: guarding an opaque native API
        return None, "%s: %s" % (type(exc).__name__, exc)


def _preset_name(entry: Any) -> Optional[str]:
    """Best-effort extraction of a preset name from a GetRenderPresetList() entry.

    The documented shape varies by Resolve version (plain strings vs. dicts
    with a name-like key); this stays tolerant rather than assuming one shape.
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for key in ("PresetName", "Name", "name"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                return value
    return None


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

    resolve_version, _ = _guarded_call(resolve.GetVersionString)
    resolve_version = resolve_version or "unknown"
    resolve_edition = edition(
        "Studio", Confidence.INFERRED, "external scripting connection succeeded"
    )

    project_manager, err = _guarded_call(resolve.GetProjectManager)
    if err or project_manager is None:
        return _cannot_run(
            err or "GetProjectManager() returned None", findings
        )

    project, err = _guarded_call(project_manager.GetCurrentProject)
    if err or project is None:
        return _cannot_run(
            err or "GetCurrentProject() returned None (no project open in Resolve)",
            findings,
        )

    # --- T015: load preset, set render settings, enqueue, start ----------- #
    preset_list, err = _guarded_call(project.GetRenderPresetList)
    if err:
        findings.append(
            finding(
                id="render.preset_list",
                statement="GetRenderPresetList() raised an exception.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=err,
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary=f"FAIL: {err}",
        )

    preset_name = args.preset
    if preset_name is None:
        candidates = preset_list if isinstance(preset_list, list) else []
        for entry in candidates:
            preset_name = _preset_name(entry)
            if preset_name:
                break

    if not preset_name:
        findings.append(
            finding(
                id="render.preset_list",
                statement="No render preset available to load.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=f"--preset not supplied and GetRenderPresetList() returned {preset_list!r}",
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary="FAIL: no render preset available (supply --preset or define one in Resolve).",
        )

    loaded, err = _guarded_call(project.LoadRenderPreset, preset_name)
    if err or not loaded:
        findings.append(
            finding(
                id="render.preset_load",
                statement=f"LoadRenderPreset({preset_name!r}) did not succeed.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=err or f"LoadRenderPreset returned {loaded!r}",
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary=f"FAIL: could not load render preset {preset_name!r}.",
        )
    findings.append(
        finding(
            id="render.preset_load",
            statement=f"LoadRenderPreset({preset_name!r}) succeeded.",
            strength=EvidenceStrength.OBSERVED_PASS,
            evidence="LoadRenderPreset returned a truthy result.",
        )
    )

    out_dir = args.out or tempfile.mkdtemp(prefix="resolve-render-probe-")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    custom_name = "render_probe_%d" % int(time.time())

    render_settings = {"TargetDir": out_dir, "CustomName": custom_name}
    _settings_result, err = _guarded_call(project.SetRenderSettings, render_settings)
    if err:
        findings.append(
            finding(
                id="render.settings",
                statement="SetRenderSettings() raised an exception.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=err,
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary=f"FAIL: {err}",
        )
    findings.append(
        finding(
            id="render.settings",
            statement=f"SetRenderSettings(TargetDir={out_dir!r}, CustomName={custom_name!r}) applied without error.",
            strength=EvidenceStrength.OBSERVED_PASS,
            evidence="SetRenderSettings raised no exception.",
        )
    )

    job_id, err = _guarded_call(project.AddRenderJob)
    if err or not job_id:
        findings.append(
            finding(
                id="render.enqueue",
                statement="AddRenderJob() did not return a usable job id.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=err or f"AddRenderJob returned {job_id!r}",
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary="FAIL: AddRenderJob() did not enqueue a job.",
        )
    findings.append(
        finding(
            id="render.enqueue",
            statement=f"AddRenderJob() enqueued job {job_id!r}.",
            strength=EvidenceStrength.OBSERVED_PASS,
            evidence="AddRenderJob returned a job id.",
        )
    )

    started, err = _guarded_call(project.StartRendering, job_id)
    if err or started is False:
        findings.append(
            finding(
                id="render.start",
                statement=f"StartRendering({job_id!r}) did not start the job.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=err or f"StartRendering returned {started!r}",
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary=f"FAIL: could not start render job {job_id!r}.",
        )
    findings.append(
        finding(
            id="render.start",
            statement=f"StartRendering({job_id!r}) started without error.",
            strength=EvidenceStrength.OBSERVED_PASS,
            evidence="StartRendering raised no exception and did not return False.",
        )
    )

    # --- T016: explicit timeout/stall poll loop (FR-006) ------------------- #
    timeout_s = max(0.0, args.timeout)
    stall_s = max(0.0, args.stall)
    poll_s = max(_MIN_POLL_SLEEP_S, args.poll)

    start_time = time.monotonic()
    last_progress_time = start_time
    last_status: Optional[str] = None
    last_percentage: Optional[float] = None
    outcome_kind: Optional[str] = None  # "completed" | "timeout" | "stall" | "poll-error" | "terminal-non-complete"
    poll_error: Optional[str] = None

    while True:
        now = time.monotonic()
        elapsed = now - start_time

        if elapsed > timeout_s:
            outcome_kind = "timeout"
            break

        status, err = _guarded_call(project.GetRenderJobStatus, job_id)
        if err:
            outcome_kind = "poll-error"
            poll_error = err
            break
        status = status if isinstance(status, dict) else {}

        job_status = status.get("JobStatus")
        if job_status is not None:
            last_status = job_status
        percentage = status.get("CompletionPercentage")
        if percentage is not None:
            if last_percentage is None or percentage != last_percentage:
                last_percentage = percentage
                last_progress_time = now

        if (now - last_progress_time) > stall_s:
            outcome_kind = "stall"
            break

        if job_status in _TERMINAL_STATUSES:
            outcome_kind = "completed" if job_status == "Complete" else "terminal-non-complete"
            break

        time.sleep(poll_s)

    elapsed_final = time.monotonic() - start_time

    # --- Breach handling: timeout / stall / poll-error / non-complete ------ #
    if outcome_kind in ("timeout", "stall", "poll-error", "terminal-non-complete"):
        _stop_result, stop_err = _guarded_call(project.StopRendering)
        stop_note = (
            f"StopRendering() raised: {stop_err}" if stop_err else "StopRendering() attempted, no exception raised."
        )
        detail = poll_error if outcome_kind == "poll-error" else stop_note
        findings.append(
            finding(
                id=f"render.{outcome_kind.replace('-', '_')}",
                statement=(
                    f"Render job {job_id!r} did not complete cleanly ({outcome_kind}) "
                    f"after {elapsed_final:.1f}s; last JobStatus={last_status!r}, "
                    f"last CompletionPercentage={last_percentage!r}."
                ),
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=detail,
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary=(
                f"FAIL ({outcome_kind}): last JobStatus={last_status}, "
                f"last CompletionPercentage={last_percentage}, elapsed={elapsed_final:.1f}s."
            ),
        )

    # --- Completed: confirm output file exists with non-zero size --------- #
    out_path_obj = Path(out_dir)
    all_files = [p for p in out_path_obj.iterdir() if p.is_file()]
    matched = [p for p in all_files if p.name.startswith(custom_name)]
    candidates = matched if matched else all_files

    if not candidates:
        findings.append(
            finding(
                id="render.output_missing",
                statement=f"Render job {job_id!r} reported Complete, but no output file was found in {out_dir!r}.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=f"CustomName prefix={custom_name!r}; directory listing={[p.name for p in all_files]!r}",
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary=f"FAIL: job reported Complete but no output file found in {out_dir}.",
        )

    nonzero = [p for p in candidates if p.stat().st_size > 0]
    if not nonzero:
        findings.append(
            finding(
                id="render.output_empty",
                statement=f"Output file(s) found for job {job_id!r}, but all are zero bytes.",
                strength=EvidenceStrength.OBSERVED_FAIL,
                evidence=f"files={[str(p) for p in candidates]!r}",
            )
        )
        return _emit(
            ProbeOutcome.FAIL,
            findings,
            resolve_version=resolve_version,
            resolve_edition=resolve_edition,
            summary="FAIL: output file(s) present but zero bytes.",
        )

    findings.append(
        finding(
            id="render.completed",
            statement=(
                f"Render job {job_id!r} completed within timeout ({elapsed_final:.1f}s / {timeout_s}s budget); "
                f"output file(s) confirmed present with non-zero size."
            ),
            strength=EvidenceStrength.OBSERVED_PASS,
            evidence=f"files={[str(p) for p in nonzero]!r}",
        )
    )
    return _emit(
        ProbeOutcome.PASS,
        findings,
        resolve_version=resolve_version,
        resolve_edition=resolve_edition,
        summary=(
            f"PASS: render job {job_id} completed in {elapsed_final:.1f}s; "
            f"output confirmed at {[str(p) for p in nonzero]}."
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
