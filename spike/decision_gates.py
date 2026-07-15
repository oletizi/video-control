"""decision_gates.py — gate mapping + Decision Policy derivation (US9).

THROWAWAY spike code (see spike/README.md). Split out of decision.py: maps each
ProbeResult onto one of the eight categorized decision gates (hard / narrowing /
informational) and applies the Decision Policy mechanically to derive
GO / NARROW / NO-GO / INCONCLUSIVE.

FR-016 is load-bearing here. "Not found during the spike" (a *missing* or
*skipped* probe result) MUST NOT be promoted to "proven impossible." So this
distinguishes three per-gate states — ``met`` / ``unmet-observed`` / ``untested``
— and a NO-GO is only ever derived from an *observed* hard-gate failure; an
untested hard gate yields INCONCLUSIVE, not a fabricated GO or NO-GO.

Python 3.11-compatible syntax only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# Make the sibling spike/ modules importable regardless of the caller's cwd.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence  # noqa: E402  (reuse build_provenance / ProbeOutcome etc.)

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


# A gate's remediation command; lives here because _gate_detail references it.
def _probe_command(probe: str) -> str:
    if probe == "inspect":
        return "python spike/probes/inspect_probe.py"
    return "python spike/probes/%s.py" % probe


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
