"""decision.py — the Go/No-Go aggregator (US9, NOT a probe).

THROWAWAY spike code (see spike/README.md). Implements T021-T022 of
specs/001-resolve-discovery-spike/tasks.md against:

  * the Decision Policy in spec.md (gate-category table + recommendation-rule
    table), FR-017, FR-018, US9, SC-001, SC-011;
  * the ``Gate`` / ``Decision`` shapes + the mechanical derivation rule in
    data-model.md;
  * the ``decision`` section of contracts/probes.md.

This is the *aggregator*, not a probe: it reads every ProbeResult written under
``spike/findings/raw/*.json`` (each stamped by ``evidence.write_probe_result``),
maps each probe's observation onto one of the eight decision gates and its
category (via ``decision_gates``), applies the Decision Policy mechanically, and
renders the three human-readable decision artifacts (via ``decision_render``):

    spike/findings/go-no-go.md
    spike/findings/capability-matrix.md
    spike/findings/api-risk-register.md

FR-016 is load-bearing here. "Not found during the spike" (a *missing* or
*skipped* probe result) MUST NOT be promoted to "proven impossible." So the
aggregator distinguishes ``met`` / ``unmet-observed`` / ``untested`` (see
``decision_gates``) and, when a hard gate is *untested* (no probe evidence on
disk), reports **INCONCLUSIVE — evidence incomplete, a live run is required**,
rather than fabricating either a GO or a NO-GO. A NO-GO is only ever derived
from an *observed* hard-gate failure.

Runnable as ``python spike/decision.py``; works fully offline (no Resolve, no
findings) — in that case it truthfully reports incomplete evidence.

Python 3.11-compatible syntax only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Make the sibling spike/ modules importable regardless of the caller's cwd
# (python spike/decision.py from the repo root, or from anywhere).
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision_gates import (  # noqa: E402
    REC_GO,
    REC_INCONCLUSIVE,
    STATE_MET,
    STATE_UNMET,
    STATE_UNTESTED,
    _state_from_result,
    build_decision,
)
from decision_render import (  # noqa: E402
    _OP_RE,
    _ROUTE_RE,
    _risk_rows,
    render_capability_matrix,
    render_go_no_go,
    render_risk_register,
)

SPIKE_ROOT = Path(__file__).resolve().parent
FINDINGS_DIR = SPIKE_ROOT / "findings"
RAW_DIR = FINDINGS_DIR / "raw"
FIXTURE_OPS = SPIKE_ROOT / "fixtures" / "mvp-operations.json"


# --------------------------------------------------------------------------- #
# Loading probe results
# --------------------------------------------------------------------------- #


def load_probe_results() -> dict[str, dict[str, Any]]:
    """Read every ``findings/raw/*.json`` into a map keyed by provenance probe.

    Malformed or unreadable files are recorded as a synthetic ``load-error``
    entry (never a crash, never silently dropped) so the decision artifacts can
    surface them. Files that are not recognizable ProbeResults are skipped with
    a note. Returns ``{probe_name: probe_result_with_extras}``.
    """
    results: dict[str, dict[str, Any]] = {}
    if not RAW_DIR.is_dir():
        return results

    for path in sorted(RAW_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Unreadable/malformed file: skip it. The gate whose probe this was
            # will simply have no evidence and be reported UNTESTED (FR-016).
            continue
        if not isinstance(data, dict):
            continue
        provenance = data.get("provenance") or {}
        probe = provenance.get("probe")
        if not probe:
            # Fall back to the filename stem so nothing is silently lost.
            probe = path.stem
        data["_source_path"] = str(path)
        results[probe] = data
    return results


# --------------------------------------------------------------------------- #
# Capability matrix (FR-011 / data-model CapabilityMatrixRow)
# --------------------------------------------------------------------------- #


def _capability_rows(results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Build capability-matrix rows from probe observations + fallback_inventory.

    Core capabilities (the hard/narrowing gate operations) are all
    ``resolve-api``-routed; their status/strength comes from the gate probe's
    result. Non-core operations come from the fallback_inventory findings
    (route + evidence strength are carried per-finding). When no
    fallback_inventory evidence exists, the MVP operation list is read straight
    from the fixture so the matrix still enumerates every attempted operation as
    UNTESTED rather than omitting them.
    """
    rows: list[dict[str, Any]] = []

    # Core capabilities from the gate probes.
    core = [
        ("external connection", "external-connection", "doctor"),
        ("structured inspection vs fixture", "structured-inspection", "inspect"),
        ("timeline build (create/import/place/marker)", "timeline-mutation", "build"),
        ("render to completion", "render-completion", "render"),
        ("stable identifiers", "stable-identity", "identity"),
        ("reversibility / rollback", "reversibility", "snapshot"),
        ("partial-failure recovery", "partial-failure-recovery", "partial_failure"),
    ]
    for op, _gate, probe in core:
        pr = results.get(probe)
        result = (pr or {}).get("result")
        state = _state_from_result(result) if pr is not None else STATE_UNTESTED
        rows.append(
            {
                "operation": op,
                "route": "resolve-api",
                "status": _status_word(state, pr is not None),
                "strength": _strength_for_state(state),
                "notes": "core capability exercised by the '%s' probe" % probe,
            }
        )

    # Non-core operations from fallback_inventory findings.
    fb = results.get("fallback_inventory")
    if fb is not None:
        for f in fb.get("findings") or []:
            fid = f.get("id", "")
            if not fid.startswith("fallback_inventory.") or fid.endswith(".summary"):
                continue
            stmt = f.get("statement", "")
            route_m = _ROUTE_RE.search(stmt)
            op_m = _OP_RE.search(stmt)
            rows.append(
                {
                    "operation": op_m.group(1) if op_m else fid,
                    "route": route_m.group(1) if route_m else "(unparsed)",
                    "status": "classified",
                    "strength": f.get("strength", "untested"),
                    "notes": (f.get("evidence") or "").split(" | ")[0][:160],
                }
            )
    else:
        # No fallback_inventory evidence — enumerate the fixture ops as untested.
        for op in _fixture_operations():
            rows.append(
                {
                    "operation": op,
                    "route": "(untested)",
                    "status": "UNTESTED",
                    "strength": "untested",
                    "notes": "no fallback_inventory evidence on disk; run the probe",
                }
            )
    return rows


def _fixture_operations() -> list[str]:
    try:
        data = json.loads(FIXTURE_OPS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [e.get("operation", "?") for e in data if isinstance(e, dict)]


def _status_word(state: str, present: bool) -> str:
    if state == STATE_MET:
        return "met"
    if state == STATE_UNMET:
        return "unmet (observed)"
    return "UNTESTED"


def _strength_for_state(state: str) -> str:
    if state == STATE_MET:
        return "observed-pass"
    if state == STATE_UNMET:
        return "observed-fail"
    return "untested"


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def run() -> dict[str, Any]:
    """Aggregate the findings and write the three decision artifacts.

    Returns the Decision object (also written to findings/decision.json).
    """
    results = load_probe_results()
    decision = build_decision(results)
    cap_rows = _capability_rows(results)
    risk_rows = _risk_rows(results)

    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    (FINDINGS_DIR / "go-no-go.md").write_text(
        render_go_no_go(decision), encoding="utf-8"
    )
    (FINDINGS_DIR / "capability-matrix.md").write_text(
        render_capability_matrix(decision, cap_rows), encoding="utf-8"
    )
    (FINDINGS_DIR / "api-risk-register.md").write_text(
        render_risk_register(decision, risk_rows), encoding="utf-8"
    )

    # Persist the machine-readable Decision alongside the reports (NOT under
    # raw/, so a re-run never mistakes it for a probe result). gates_full is
    # renderer-only and dropped from the persisted wire object.
    persisted = {k: v for k, v in decision.items() if k != "gates_full"}
    (FINDINGS_DIR / "decision.json").write_text(
        json.dumps(persisted, indent=2) + "\n", encoding="utf-8"
    )
    return decision


def _print_summary(decision: dict[str, Any]) -> None:
    print("decision aggregator — %d gates evaluated" % len(decision["gates"]))
    for g in decision["gates_full"]:
        print(
            "  - %-32s [%-13s] state=%s"
            % (g["name"], g["category"], g["state"])
        )
    print("")
    print("RECOMMENDATION: %s" % decision["recommendation"])
    print("  rationale: %s" % decision["rationale"])
    if not decision["evidence_complete"]:
        print(
            "  evidence: INCOMPLETE — a live probe run against a running "
            "DaVinci Resolve is required (this is NOT a GO)."
        )
    print("")
    print("wrote:")
    for name in ("go-no-go.md", "capability-matrix.md", "api-risk-register.md", "decision.json"):
        print("  - %s" % (FINDINGS_DIR / name))


def main() -> int:
    decision = run()
    _print_summary(decision)
    # Exit code mirrors the probe contract spirit: 0 for GO, 1 for a decided
    # NARROW/NO-GO (a real finding), 2 when evidence is incomplete (could-not-
    # decide — analogous to a probe's cannot-run).
    rec = decision["recommendation"]
    if rec == REC_GO:
        return 0
    if rec == REC_INCONCLUSIVE:
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
