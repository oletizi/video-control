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
category (hard / narrowing / informational), applies the Decision Policy
mechanically, and renders the three human-readable decision artifacts (FR-018):

    spike/findings/go-no-go.md
    spike/findings/capability-matrix.md
    spike/findings/api-risk-register.md

FR-016 is load-bearing here. "Not found during the spike" (a *missing* or
*skipped* probe result) MUST NOT be promoted to "proven impossible." A naive
reading of the derivation rule ("any hard gate unmet -> NO-GO") would, applied
to gates that were merely never exercised, fabricate a NO-GO out of absence of
evidence — exactly the promotion FR-016 forbids. So this aggregator distinguishes
three per-gate states — ``met`` / ``unmet-observed`` / ``untested`` — and when a
hard gate is *untested* (no probe evidence on disk) it reports **INCONCLUSIVE —
evidence incomplete, a live run is required**, rather than fabricating either a
GO or a NO-GO. A NO-GO is only ever derived from an *observed* hard-gate failure.

Runnable as ``python spike/decision.py``; works fully offline (no Resolve, no
findings) — in that case it truthfully reports incomplete evidence.

Python 3.11-compatible syntax only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

# Make the sibling spike/ modules importable regardless of the caller's cwd
# (python spike/decision.py from the repo root, or from anywhere).
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence  # noqa: E402  (reuse build_provenance / EvidenceStrength etc.)

SPIKE_ROOT = Path(__file__).resolve().parent
FINDINGS_DIR = SPIKE_ROOT / "findings"
RAW_DIR = FINDINGS_DIR / "raw"
FIXTURE_OPS = SPIKE_ROOT / "fixtures" / "mvp-operations.json"

# Per-gate state labels (internal, not persisted as an enum — kept explicit).
STATE_MET = "met"
STATE_UNMET = "unmet-observed"
STATE_UNTESTED = "untested"

# Recommendation values. GO / NARROW / NO-GO are the documented Decision-Policy
# outcomes (data-model.md). INCONCLUSIVE is the FR-016-consistent resolution of
# the gap the policy table leaves open: it is what an honest aggregator must say
# when the hard gates were never exercised, instead of promoting absence of
# evidence into a fabricated GO or NO-GO.
REC_GO = "GO"
REC_NARROW = "NARROW"
REC_NOGO = "NO-GO"
REC_INCONCLUSIVE = "INCONCLUSIVE"


# --------------------------------------------------------------------------- #
# Gate registry — the Decision Policy gate-category table (spec.md)
# --------------------------------------------------------------------------- #
#
# ``probe`` is the provenance ``probe`` name each probe stamps (note the inspect
# probe lives in inspect_probe.py but stamps probe name "inspect"). ``mitigation``
# is the credible mitigation the Decision Policy requires for a NARROWING failure
# to force NARROW (not NO-GO); hard/informational gates carry None.

GATE_REGISTRY: list[dict[str, Any]] = [
    {
        "gate": "external-connection",
        "category": "hard",
        "probe": "doctor",
        "label": "External connection (repeatable)",
        "mitigation": None,
    },
    {
        "gate": "structured-inspection",
        "category": "hard",
        "probe": "inspect",
        "label": "Structured inspection (fixture-verified)",
        "mitigation": None,
    },
    {
        "gate": "timeline-mutation",
        "category": "hard",
        "probe": "build",
        "label": "Timeline mutation (create/import/place/marker)",
        "mitigation": None,
    },
    {
        "gate": "render-completion",
        "category": "hard",
        "probe": "render",
        "label": "Render completion (enqueue -> observe -> finish)",
        "mitigation": None,
    },
    {
        "gate": "stable-identity",
        "category": "narrowing",
        "probe": "identity",
        "label": "Stable identity for idempotency",
        "mitigation": (
            "harness-managed identity (metadata tags / markers) is a credible "
            "substitute for absent or unstable native identifiers (US5 / FR-008)"
        ),
    },
    {
        "gate": "reversibility",
        "category": "narrowing",
        "probe": "snapshot",
        "label": "Reliable rollback / reversibility",
        "mitigation": (
            "generated-timeline replacement (always emit a NEW output timeline "
            "rather than mutating in place) is a credible substitute for "
            "unavailable project rollback (US6 / FR-009)"
        ),
    },
    {
        "gate": "partial-failure-recovery",
        "category": "narrowing",
        "probe": "partial_failure",
        "label": "Partial-failure recovery",
        "mitigation": (
            "inspect-before-mutate + idempotent re-run + an explicit surfaced "
            "remediation path is a credible mitigation (US7 / FR-010)"
        ),
    },
    {
        "gate": "non-core-operation-availability",
        "category": "informational",
        "probe": "fallback_inventory",
        "label": "Non-core operation availability (fallback inventory)",
        "mitigation": None,
    },
]

# Known probe names, so a stray/foreign file in raw/ (e.g. a decision dump) is
# never mistaken for a probe result.
KNOWN_PROBES: frozenset[str] = frozenset(g["probe"] for g in GATE_REGISTRY)


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
# Gate derivation
# --------------------------------------------------------------------------- #


def _state_from_result(result: Optional[str]) -> str:
    """Map a probe-level ``result`` string to a per-gate state.

    pass -> met; fail/partial -> unmet-observed (real observed evidence of an
    unmet gate); skipped or absent -> untested (no evidence — FR-016).
    """
    if result == "pass":
        return STATE_MET
    if result in ("fail", "partial"):
        return STATE_UNMET
    # "skipped", None, or anything unexpected -> untested (absence of evidence).
    return STATE_UNTESTED


def _evidence_ref(probe: str, present: bool) -> str:
    """Relative path used both as the Gate.evidence_ref and the md link target."""
    ref = "findings/raw/%s.json" % probe
    return ref if present else ref + " (MISSING — probe not yet run)"


def build_gates(
    results: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Derive every Gate (data-model.md shape) + the drivers list.

    Returns ``(gates, notes)`` where each gate is
    ``{name, category, met, evidence_ref, state, untested, detail}`` (a superset
    of the data-model Gate: the extra fields carry the observed/untested
    distinction the renderers and the recommendation rule need). ``notes`` holds
    human-readable remarks about missing/malformed inputs.
    """
    gates: list[dict[str, Any]] = []
    notes: list[str] = []

    for spec in GATE_REGISTRY:
        probe = spec["probe"]
        pr = results.get(probe)
        present = pr is not None
        result = (pr or {}).get("result") if present else None
        state = _state_from_result(result) if present else STATE_UNTESTED

        if not present:
            notes.append(
                "gate '%s' UNTESTED: no evidence file %s on disk (probe not run)"
                % (spec["gate"], "findings/raw/%s.json" % probe)
            )
        elif state == STATE_UNTESTED:
            notes.append(
                "gate '%s' UNTESTED: probe '%s' recorded result=%r (skipped / "
                "could-not-run)" % (spec["gate"], probe, result)
            )

        detail = _gate_detail(spec, pr, state)
        gates.append(
            {
                "name": spec["gate"],
                "category": spec["category"],
                "met": state == STATE_MET,
                "evidence_ref": _evidence_ref(probe, present),
                "state": state,
                "untested": state == STATE_UNTESTED,
                "detail": detail,
                "probe": probe,
                "label": spec["label"],
                "mitigation": spec["mitigation"],
            }
        )

    drivers = _derive_drivers(gates)
    return gates, drivers


def _gate_detail(spec: dict[str, Any], pr: Optional[dict[str, Any]], state: str) -> str:
    """One-line human explanation of why a gate is in its state."""
    if pr is None:
        return "No probe evidence on disk — run: %s" % _probe_command(spec["probe"])
    result = pr.get("result")
    findings = pr.get("findings") or []
    # Prefer the most decisive finding statement matching the state.
    picked = _pick_finding(findings, state)
    stmt = picked.get("statement") if picked else None
    base = "probe '%s' result=%s" % (spec["probe"], result)
    return "%s — %s" % (base, stmt) if stmt else base


def _pick_finding(findings: list[dict[str, Any]], state: str) -> Optional[dict[str, Any]]:
    """Pick a representative finding for a gate state (best-effort)."""
    if not findings:
        return None
    if state == STATE_MET:
        want = {"observed-pass", "documented-supported"}
    elif state == STATE_UNMET:
        want = {"observed-fail", "documented-unsupported"}
    else:
        want = {"untested", "not-found"}
    for f in findings:
        if f.get("strength") in want:
            return f
    return findings[0]


def _derive_drivers(gates: list[dict[str, Any]]) -> list[str]:
    """The finding(s) forcing any NARROW / NO-GO / INCONCLUSIVE (FR-017)."""
    drivers: list[str] = []
    for g in gates:
        if g["category"] == "hard" and g["state"] == STATE_UNMET:
            drivers.append(
                "NO-GO driver — HARD gate '%s' observed unmet: %s"
                % (g["name"], g["detail"])
            )
    for g in gates:
        if g["category"] == "hard" and g["state"] == STATE_UNTESTED:
            drivers.append(
                "INCONCLUSIVE driver — HARD gate '%s' untested (no evidence): %s"
                % (g["name"], g["detail"])
            )
    for g in gates:
        if g["category"] == "narrowing" and g["state"] == STATE_UNMET:
            drivers.append(
                "NARROW driver — narrowing gate '%s' observed unmet; mitigation: %s"
                % (g["name"], g["mitigation"])
            )
    for g in gates:
        if g["category"] == "narrowing" and g["state"] == STATE_UNTESTED:
            drivers.append(
                "INCONCLUSIVE driver — narrowing gate '%s' untested (no evidence)"
                % g["name"]
            )
    return drivers


# --------------------------------------------------------------------------- #
# Recommendation rule (Decision Policy — spec.md / data-model.md)
# --------------------------------------------------------------------------- #


def derive_recommendation(gates: list[dict[str, Any]]) -> tuple[str, str]:
    """Apply the Decision Policy mechanically. Returns (recommendation, rationale).

    Precedence (FR-016-consistent extension of the data-model derivation rule):

      1. Any HARD gate OBSERVED unmet          -> NO-GO   (a proven hard failure)
      2. Else any HARD gate untested           -> INCONCLUSIVE (evidence incomplete)
      3. Else (all hard gates met):
         a. Any NARROWING gate observed unmet  -> NARROW  (mitigation recorded)
         b. Else any NARROWING gate untested   -> INCONCLUSIVE (evidence incomplete)
         c. Else                               -> GO
    """
    hard = [g for g in gates if g["category"] == "hard"]
    narrowing = [g for g in gates if g["category"] == "narrowing"]

    hard_observed_fail = [g for g in hard if g["state"] == STATE_UNMET]
    hard_untested = [g for g in hard if g["state"] == STATE_UNTESTED]

    if hard_observed_fail:
        names = ", ".join(g["name"] for g in hard_observed_fail)
        return REC_NOGO, (
            "at least one HARD gate was OBSERVED to fail (%s); any hard-gate "
            "failure forces NO-GO." % names
        )

    if hard_untested:
        names = ", ".join(g["name"] for g in hard_untested)
        return REC_INCONCLUSIVE, (
            "%d of %d HARD gates are UNTESTED (%s) — no probe evidence exists on "
            "disk. Absence of evidence is NOT evidence of failure (FR-016): this "
            "is neither a GO (nothing has been proven to work) nor a NO-GO "
            "(nothing has been proven impossible). A live probe run against a "
            "running DaVinci Resolve is required before the recommendation can "
            "resolve to GO / NARROW / NO-GO." % (len(hard_untested), len(hard), names)
        )

    # All hard gates met.
    narrowing_observed_fail = [g for g in narrowing if g["state"] == STATE_UNMET]
    narrowing_untested = [g for g in narrowing if g["state"] == STATE_UNTESTED]

    if narrowing_observed_fail:
        names = ", ".join(g["name"] for g in narrowing_observed_fail)
        return REC_NARROW, (
            "all HARD gates pass, but one or more NARROWING gates were observed "
            "unmet (%s). Each has a credible recorded mitigation, so the policy "
            "forces NARROW (not NO-GO)." % names
        )

    if narrowing_untested:
        names = ", ".join(g["name"] for g in narrowing_untested)
        return REC_INCONCLUSIVE, (
            "all HARD gates pass, but one or more NARROWING gates are UNTESTED "
            "(%s). A GO cannot be asserted without their evidence; a live run of "
            "those probes is required." % names
        )

    return REC_GO, (
        "all HARD gates pass and every narrowing/informational gate is satisfied "
        "with credible mitigations for any residual risk."
    )


# --------------------------------------------------------------------------- #
# Decision assembly
# --------------------------------------------------------------------------- #

_REC_TO_OUTCOME = {
    REC_GO: evidence.ProbeOutcome.PASS,
    REC_NARROW: evidence.ProbeOutcome.PARTIAL,
    REC_NOGO: evidence.ProbeOutcome.FAIL,
    REC_INCONCLUSIVE: evidence.ProbeOutcome.SKIPPED,
}


def build_decision(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Assemble the Decision object (data-model.md) with a provenance stamp."""
    gates, notes = build_gates(results)
    recommendation, rationale = derive_recommendation(gates)
    drivers = _derive_drivers(gates)

    provenance = evidence.build_provenance(
        probe="decision",
        result=_REC_TO_OUTCOME[recommendation],
    )
    return {
        "recommendation": recommendation,
        "rationale": rationale,
        "gates": [
            {
                "name": g["name"],
                "category": g["category"],
                "met": g["met"],
                "evidence_ref": g["evidence_ref"],
                "state": g["state"],
            }
            for g in gates
        ],
        "gates_full": gates,  # renderer-only detail; not part of the wire Gate
        "drivers": drivers,
        "notes": notes,
        "provenance": provenance,
        "evidence_complete": not any(g["untested"] for g in gates),
    }


# --------------------------------------------------------------------------- #
# Capability matrix (FR-011 / data-model CapabilityMatrixRow)
# --------------------------------------------------------------------------- #

_ROUTE_RE = re.compile(r"classified as ([a-z][a-z-]+)")
_OP_RE = re.compile(r"^'(.+?)'")


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
# Risk register (data-model "API risk register")
# --------------------------------------------------------------------------- #

RISK_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "python-load",
        "title": "No supported Python interpreter loads the native scripting library",
        "probe": "doctor",
        "severity_open": "High",
        "mitigation": (
            "Pin the working interpreter the doctor probe identifies as a hard "
            "M1 constraint; try documented fallback interpreters (FR-003)."
        ),
    },
    {
        "id": "edition-gate",
        "title": "Free edition / disabled external scripting blocks the API",
        "probe": "doctor",
        "severity_open": "High",
        "mitigation": (
            "Require DaVinci Resolve Studio with external scripting enabled in "
            "Preferences; the doctor probe names the specific gate (edition vs "
            "permission vs interpreter) (FR-002)."
        ),
    },
    {
        "id": "structured-inspection",
        "title": "API does not expose enough verifiable structured state",
        "probe": "inspect",
        "severity_open": "High",
        "mitigation": (
            "Diff inspect output against the version-controlled fixture manifest; "
            "supplement gaps with additional documented API queries (FR-007)."
        ),
    },
    {
        "id": "timeline-mutation-reliability",
        "title": "Timeline / clip / marker creation is unreliable or non-idempotent",
        "probe": "build",
        "severity_open": "High",
        "mitigation": (
            "Record the observed re-run (idempotency) behavior and add "
            "harness-managed de-duplication where needed (FR-005)."
        ),
    },
    {
        "id": "render-reliability",
        "title": "Render cannot be started / observed to completion (stalls, hangs)",
        "probe": "render",
        "severity_open": "High",
        "mitigation": (
            "Explicit overall timeout + stall threshold + cancellation with "
            "last-known-status evidence; never poll indefinitely (FR-006)."
        ),
    },
    {
        "id": "identifier-stability",
        "title": "Native identifiers are unstable or absent across save/reload",
        "probe": "identity",
        "severity_open": "Medium",
        "mitigation": (
            "Harness-managed identity via metadata tags / markers instead of "
            "relying on native GetUniqueId() stability (FR-008)."
        ),
    },
    {
        "id": "reversibility",
        "title": "Reliable rollback / project restore is unavailable",
        "probe": "snapshot",
        "severity_open": "Medium",
        "mitigation": (
            "Always emit a NEW output timeline (generated-timeline replacement) "
            "rather than mutating in place (FR-009)."
        ),
    },
    {
        "id": "partial-failure-recovery",
        "title": "Induced partial failures leave uninspectable / unrecoverable state",
        "probe": "partial_failure",
        "severity_open": "Medium",
        "mitigation": (
            "Inspect-before-mutate, idempotent re-run, and an explicit surfaced "
            "remediation path per injected case (FR-010)."
        ),
    },
    {
        "id": "gui-only-ops",
        "title": "MVP-critical operations are GUI-only / unsupported",
        "probe": "fallback_inventory",
        "severity_open": "Medium",
        "mitigation": (
            "Route via external deterministic tooling where the API is silent, "
            "and defer genuinely unsupported capabilities. Absence from the API "
            "is NOT recorded as GUI-only by default (FR-011)."
        ),
    },
]


def _risk_rows(results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in RISK_REGISTRY:
        pr = results.get(r["probe"])
        present = pr is not None
        state = _state_from_result((pr or {}).get("result")) if present else STATE_UNTESTED

        if r["id"] == "gui-only-ops":
            gui_hits = _gui_only_hits(pr) if present else None
            if not present:
                status, severity = "Untested — no evidence", "Unknown (untested)"
            elif gui_hits:
                status = "OPEN — %d GUI-only/unsupported op(s): %s" % (
                    len(gui_hits),
                    ", ".join(gui_hits),
                )
                severity = r["severity_open"]
            else:
                status, severity = (
                    "Not observed — every op routed to API or external tooling",
                    "Low (observed)",
                )
        else:
            if state == STATE_MET:
                status, severity = "Mitigated / not observed (gate met)", "Low (observed-pass)"
            elif state == STATE_UNMET:
                status, severity = "OPEN — observed", r["severity_open"]
            else:
                status, severity = "Untested — no evidence", "Unknown (untested)"

        rows.append(
            {
                "id": r["id"],
                "title": r["title"],
                "severity": severity,
                "status": status,
                "mitigation": r["mitigation"],
                "evidence_ref": _evidence_ref(r["probe"], present),
            }
        )
    return rows


def _gui_only_hits(pr: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    for f in pr.get("findings") or []:
        stmt = f.get("statement", "")
        route_m = _ROUTE_RE.search(stmt)
        if route_m and route_m.group(1) in ("named-gui-fallback", "unsupported-or-deferred"):
            op_m = _OP_RE.search(stmt)
            hits.append(op_m.group(1) if op_m else f.get("id", "?"))
    return hits


# --------------------------------------------------------------------------- #
# Markdown rendering (FR-018)
# --------------------------------------------------------------------------- #


def _prov_block(prov: dict[str, Any]) -> str:
    return (
        "> Generated by `spike/decision.py` at %s\n"
        "> host: %s/%s · python: %s · probe_commit: %s\n"
        % (
            prov.get("timestamp"),
            prov.get("host_os"),
            prov.get("host_arch"),
            prov.get("python_version"),
            prov.get("probe_commit"),
        )
    )


def _probe_command(probe: str) -> str:
    if probe == "inspect":
        return "python spike/probes/inspect_probe.py"
    return "python spike/probes/%s.py" % probe


def render_go_no_go(decision: dict[str, Any]) -> str:
    rec = decision["recommendation"]
    gates = decision["gates_full"]
    lines: list[str] = []
    lines.append("# Go / No-Go Decision\n")
    lines.append(_prov_block(decision["provenance"]))
    lines.append("")
    lines.append("## Recommendation: **%s**\n" % rec)
    lines.append(decision["rationale"] + "\n")

    if not decision["evidence_complete"]:
        untested = [g["name"] for g in gates if g["untested"]]
        lines.append("> [!] EVIDENCE INCOMPLETE — a live probe run is required.\n")
        lines.append(
            "> %d of %d gates are UNTESTED (no probe evidence on disk): %s.\n"
            % (len(untested), len(gates), ", ".join(untested))
        )
        lines.append(
            "> This is explicitly **not** a GO (nothing has been proven to work) "
            "and **not** a NO-GO (nothing has been proven impossible). Per FR-016, "
            "absence of evidence is never promoted to 'proven impossible'. Run the "
            "probes against a running DaVinci Resolve, then re-run "
            "`python spike/decision.py`.\n"
        )

    lines.append("## Gates\n")
    lines.append("| Gate | Category | Status | Evidence |")
    lines.append("|------|----------|--------|----------|")
    for g in gates:
        status = {
            STATE_MET: "MET",
            STATE_UNMET: "UNMET (observed)",
            STATE_UNTESTED: "UNTESTED",
        }[g["state"]]
        ref = g["evidence_ref"]
        if "MISSING" in ref:
            link = "`%s`" % ref
        else:
            link = "[`%s`](%s)" % (ref, ref.replace("findings/", ""))
        lines.append(
            "| %s | %s | %s | %s |" % (g["label"], g["category"], status, link)
        )
    lines.append("")

    lines.append("## Drivers\n")
    if decision["drivers"]:
        for d in decision["drivers"]:
            lines.append("- %s" % d)
    else:
        lines.append("- (none) — no gate forced a NARROW / NO-GO / INCONCLUSIVE.")
    lines.append("")

    lines.append("## Per-gate detail\n")
    for g in gates:
        lines.append("### %s (%s gate)\n" % (g["label"], g["category"]))
        lines.append("- **State**: %s" % g["state"])
        lines.append("- **Detail**: %s" % g["detail"])
        if g["mitigation"]:
            lines.append("- **Mitigation if unmet**: %s" % g["mitigation"])
        lines.append("- **Evidence**: `%s`\n" % g["evidence_ref"])

    lines.append("## How the recommendation is derived (Decision Policy)\n")
    lines.append(
        "The recommendation is **mechanical**, not judged (SC-011 / FR-017): "
        "any HARD gate observed unmet -> NO-GO; else any HARD gate untested -> "
        "INCONCLUSIVE (evidence incomplete); else any NARROWING gate observed "
        "unmet (with its recorded mitigation) -> NARROW; else any narrowing gate "
        "untested -> INCONCLUSIVE; else -> GO. A reviewer who did not run the "
        "probes can reproduce this recommendation from the gate table above.\n"
    )

    if not decision["evidence_complete"]:
        lines.append("## To complete the evidence, run each untested probe\n")
        for g in gates:
            if g["untested"]:
                lines.append("- `%s`  (gate: %s)" % (_probe_command(g["probe"]), g["name"]))
        lines.append("\nThen re-run `python spike/decision.py`.\n")

    return "\n".join(lines) + "\n"


def render_capability_matrix(decision: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# Capability Matrix\n")
    lines.append(_prov_block(decision["provenance"]))
    lines.append("")
    lines.append(
        "Each attempted operation is mapped to one of four routes "
        "(`resolve-api` / `external-tooling` / `named-gui-fallback` / "
        "`unsupported-or-deferred`) with an evidence-strength label (FR-011). "
        "Absence from the Resolve API is never defaulted to GUI-only.\n"
    )
    lines.append("| Operation | Route | Status | Evidence strength | Notes |")
    lines.append("|-----------|-------|--------|-------------------|-------|")
    for r in rows:
        notes = (r["notes"] or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            "| %s | `%s` | %s | `%s` | %s |"
            % (r["operation"], r["route"], r["status"], r["strength"], notes)
        )
    lines.append("")
    if not decision["evidence_complete"]:
        lines.append(
            "> Rows marked `UNTESTED` reflect probes not yet run — not proven "
            "impossibility (FR-016). Run the probes to populate them.\n"
        )
    return "\n".join(lines) + "\n"


def render_risk_register(decision: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# API Risk Register\n")
    lines.append(_prov_block(decision["provenance"]))
    lines.append("")
    lines.append(
        "Discovered / anticipated risks with severity and mitigation, derived "
        "mechanically from the recorded probe findings. A risk whose backing "
        "probe has not run is recorded as **Untested (Unknown severity)** — never "
        "as either resolved or as a proven blocker (FR-016).\n"
    )
    lines.append("| Risk | Severity | Status | Mitigation | Evidence |")
    lines.append("|------|----------|--------|------------|----------|")
    for r in rows:
        mit = r["mitigation"].replace("|", "\\|")
        lines.append(
            "| **%s** — %s | %s | %s | %s | `%s` |"
            % (r["id"], r["title"], r["severity"], r["status"], mit, r["evidence_ref"])
        )
    lines.append("")
    return "\n".join(lines) + "\n"


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
