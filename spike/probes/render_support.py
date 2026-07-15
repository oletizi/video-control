"""Pure/orchestration helpers for the render probe (US4) — spike/probes/render.py.

THROWAWAY spike code (see spike/README.md). Extracted out of render.py so both
files stay under the project's line/size caps; NO behavior change from the
prior single-file implementation. Every function here takes the live
resolve/project/job objects (or plain data derived from them) as explicit
arguments rather than reading module globals, so each step of the render
probe's flow — preset load, render-settings, enqueue/start, the FR-006
timeout/stall poll loop, and output-file confirmation — stays independently
readable and testable.

This module imports only from ``evidence`` (never from ``resolve_env`` or
``render.py`` itself) to keep it a leaf: render.py owns the connection to
Resolve and the CLI/exit-code contract; this module owns the guarded API
call plumbing and the deterministic decisions built on top of it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional

from evidence import EvidenceStrength, finding

# JobStatus strings the Resolve render API is documented to report once a job
# leaves the active "Rendering" state.
TERMINAL_STATUSES = frozenset({"Complete", "Cancelled", "Failed"})

# Minimum sleep floor so a caller-supplied --poll of 0 (or negative) cannot
# turn the poll loop into a tight busy-spin.
MIN_POLL_SLEEP_S = 0.05


# --------------------------------------------------------------------------- #
# Guarded API-call helper
# --------------------------------------------------------------------------- #


def guarded_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, Optional[str]]:
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


def preset_name_from_entry(entry: Any) -> Optional[str]:
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
# Finding builders
# --------------------------------------------------------------------------- #


def pass_finding(id_: str, statement: str, evidence_text: str) -> dict[str, Any]:
    return finding(id=id_, statement=statement, strength=EvidenceStrength.OBSERVED_PASS, evidence=evidence_text)


def fail_finding(id_: str, statement: str, evidence_text: str) -> dict[str, Any]:
    return finding(id=id_, statement=statement, strength=EvidenceStrength.OBSERVED_FAIL, evidence=evidence_text)


class StepResult(NamedTuple):
    """Outcome of one guarded setup step: ``value`` is the useful result on
    success; ``fail_summary`` is ``None`` on success and a one-line summary
    (for the CLI's FAIL message) on failure. ``findings`` is always populated
    (a PASS or FAIL finding for the step).
    """

    value: Any
    findings: list[dict[str, Any]]
    fail_summary: Optional[str]


# --------------------------------------------------------------------------- #
# T015: preset load / render settings / enqueue / start
# --------------------------------------------------------------------------- #


def load_preset(project: Any, requested_preset: Optional[str]) -> StepResult:
    """GetRenderPresetList() -> pick a name (requested, else first candidate)
    -> LoadRenderPreset(name). Mirrors the exact finding ids/statements the
    render probe has always emitted for this step.
    """
    preset_list, err = guarded_call(project.GetRenderPresetList)
    if err:
        return StepResult(
            None,
            [fail_finding("render.preset_list", "GetRenderPresetList() raised an exception.", err)],
            err,
        )

    preset_name = requested_preset
    if preset_name is None:
        candidates = preset_list if isinstance(preset_list, list) else []
        for entry in candidates:
            preset_name = preset_name_from_entry(entry)
            if preset_name:
                break

    if not preset_name:
        return StepResult(
            None,
            [
                fail_finding(
                    "render.preset_list",
                    "No render preset available to load.",
                    f"--preset not supplied and GetRenderPresetList() returned {preset_list!r}",
                )
            ],
            "no render preset available (supply --preset or define one in Resolve).",
        )

    loaded, err = guarded_call(project.LoadRenderPreset, preset_name)
    if err or not loaded:
        return StepResult(
            None,
            [
                fail_finding(
                    "render.preset_load",
                    f"LoadRenderPreset({preset_name!r}) did not succeed.",
                    err or f"LoadRenderPreset returned {loaded!r}",
                )
            ],
            f"could not load render preset {preset_name!r}.",
        )

    return StepResult(
        preset_name,
        [
            pass_finding(
                "render.preset_load",
                f"LoadRenderPreset({preset_name!r}) succeeded.",
                "LoadRenderPreset returned a truthy result.",
            )
        ],
        None,
    )


def apply_render_settings(project: Any, out_dir: str, custom_name: str) -> StepResult:
    """SetRenderSettings({TargetDir, CustomName})."""
    render_settings = {"TargetDir": out_dir, "CustomName": custom_name}
    _settings_result, err = guarded_call(project.SetRenderSettings, render_settings)
    if err:
        return StepResult(
            None,
            [fail_finding("render.settings", "SetRenderSettings() raised an exception.", err)],
            err,
        )

    return StepResult(
        render_settings,
        [
            pass_finding(
                "render.settings",
                f"SetRenderSettings(TargetDir={out_dir!r}, CustomName={custom_name!r}) applied without error.",
                "SetRenderSettings raised no exception.",
            )
        ],
        None,
    )


def enqueue_render_job(project: Any) -> StepResult:
    """AddRenderJob()."""
    job_id, err = guarded_call(project.AddRenderJob)
    if err or not job_id:
        return StepResult(
            None,
            [
                fail_finding(
                    "render.enqueue",
                    "AddRenderJob() did not return a usable job id.",
                    err or f"AddRenderJob returned {job_id!r}",
                )
            ],
            "AddRenderJob() did not enqueue a job.",
        )

    return StepResult(
        job_id,
        [
            pass_finding(
                "render.enqueue",
                f"AddRenderJob() enqueued job {job_id!r}.",
                "AddRenderJob returned a job id.",
            )
        ],
        None,
    )


def start_rendering(project: Any, job_id: Any) -> StepResult:
    """StartRendering(job_id)."""
    started, err = guarded_call(project.StartRendering, job_id)
    if err or started is False:
        return StepResult(
            None,
            [
                fail_finding(
                    "render.start",
                    f"StartRendering({job_id!r}) did not start the job.",
                    err or f"StartRendering returned {started!r}",
                )
            ],
            f"could not start render job {job_id!r}.",
        )

    return StepResult(
        started,
        [
            pass_finding(
                "render.start",
                f"StartRendering({job_id!r}) started without error.",
                "StartRendering raised no exception and did not return False.",
            )
        ],
        None,
    )


# --------------------------------------------------------------------------- #
# T016: explicit timeout/stall poll loop (FR-006)
# --------------------------------------------------------------------------- #


class PollResult(NamedTuple):
    outcome_kind: str  # "completed" | "timeout" | "stall" | "poll-error" | "terminal-non-complete"
    last_status: Optional[str]
    last_percentage: Optional[float]
    poll_error: Optional[str]
    elapsed_final: float


def poll_render_job(project: Any, job_id: Any, timeout_s: float, stall_s: float, poll_s: float) -> PollResult:
    """Poll GetRenderJobStatus(job_id) until a terminal status, timeout, or
    stall — subject to the FR-006 explicit timeout/stall contract. NEVER hangs:
    the overall wall-clock budget (timeout_s) and the stalled-progress budget
    (stall_s, driven off CompletionPercentage) both bound the loop.
    """
    start_time = time.monotonic()
    last_progress_time = start_time
    last_status: Optional[str] = None
    last_percentage: Optional[float] = None
    outcome_kind: Optional[str] = None
    poll_error: Optional[str] = None

    while True:
        now = time.monotonic()
        elapsed = now - start_time

        if elapsed > timeout_s:
            outcome_kind = "timeout"
            break

        status, err = guarded_call(project.GetRenderJobStatus, job_id)
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

        if job_status in TERMINAL_STATUSES:
            outcome_kind = "completed" if job_status == "Complete" else "terminal-non-complete"
            break

        time.sleep(poll_s)

    elapsed_final = time.monotonic() - start_time
    return PollResult(outcome_kind, last_status, last_percentage, poll_error, elapsed_final)


def handle_breach(project: Any, job_id: Any, poll_result: PollResult) -> tuple[list[dict[str, Any]], str]:
    """Attempt StopRendering() and build the FAIL finding + CLI summary for a
    timeout/stall/poll-error/terminal-non-complete poll outcome.
    """
    outcome_kind = poll_result.outcome_kind
    _stop_result, stop_err = guarded_call(project.StopRendering)
    stop_note = (
        f"StopRendering() raised: {stop_err}" if stop_err else "StopRendering() attempted, no exception raised."
    )
    detail = poll_result.poll_error if outcome_kind == "poll-error" else stop_note
    findings = [
        fail_finding(
            f"render.{outcome_kind.replace('-', '_')}",
            (
                f"Render job {job_id!r} did not complete cleanly ({outcome_kind}) "
                f"after {poll_result.elapsed_final:.1f}s; last JobStatus={poll_result.last_status!r}, "
                f"last CompletionPercentage={poll_result.last_percentage!r}."
            ),
            detail,
        )
    ]
    summary = (
        f"FAIL ({outcome_kind}): last JobStatus={poll_result.last_status}, "
        f"last CompletionPercentage={poll_result.last_percentage}, elapsed={poll_result.elapsed_final:.1f}s."
    )
    return findings, summary


# --------------------------------------------------------------------------- #
# Output-file confirmation
# --------------------------------------------------------------------------- #


class OutputConfirmation(NamedTuple):
    kind: str  # "missing" | "empty" | "ok"
    findings: list[dict[str, Any]]
    summary: str
    nonzero_files: list[Path]


def confirm_output(
    job_id: Any,
    out_dir: str,
    custom_name: str,
    elapsed_final: float,
    timeout_s: float,
) -> OutputConfirmation:
    """Confirm the render's output file exists in out_dir with non-zero size."""
    out_path_obj = Path(out_dir)
    all_files = [p for p in out_path_obj.iterdir() if p.is_file()]
    matched = [p for p in all_files if p.name.startswith(custom_name)]
    candidates = matched if matched else all_files

    if not candidates:
        findings = [
            fail_finding(
                "render.output_missing",
                f"Render job {job_id!r} reported Complete, but no output file was found in {out_dir!r}.",
                f"CustomName prefix={custom_name!r}; directory listing={[p.name for p in all_files]!r}",
            )
        ]
        return OutputConfirmation(
            "missing",
            findings,
            f"FAIL: job reported Complete but no output file found in {out_dir}.",
            [],
        )

    nonzero = [p for p in candidates if p.stat().st_size > 0]
    if not nonzero:
        findings = [
            fail_finding(
                "render.output_empty",
                f"Output file(s) found for job {job_id!r}, but all are zero bytes.",
                f"files={[str(p) for p in candidates]!r}",
            )
        ]
        return OutputConfirmation("empty", findings, "FAIL: output file(s) present but zero bytes.", [])

    findings = [
        pass_finding(
            "render.completed",
            (
                f"Render job {job_id!r} completed within timeout ({elapsed_final:.1f}s / {timeout_s}s budget); "
                f"output file(s) confirmed present with non-zero size."
            ),
            f"files={[str(p) for p in nonzero]!r}",
        )
    ]
    summary = (
        f"PASS: render job {job_id} completed in {elapsed_final:.1f}s; "
        f"output confirmed at {[str(p) for p in nonzero]}."
    )
    return OutputConfirmation("ok", findings, summary, nonzero)
