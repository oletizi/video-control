"""decision_render.py — API-risk derivation + the three markdown renderers.

THROWAWAY spike code (see spike/README.md). Split out of decision.py: holds the
API-risk-register data + row derivation, plus the three human-readable decision
renderers (FR-018) that produce:

    findings/go-no-go.md
    findings/capability-matrix.md
    findings/api-risk-register.md

Absence of a probe result is rendered as UNTESTED, never as proven impossibility
(FR-016). Python 3.11-compatible syntax only.
"""

from __future__ import annotations

import re
from typing import Any

# Make the sibling spike/ modules importable regardless of the caller's cwd.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from decision_gates import (  # noqa: E402
    STATE_MET,
    STATE_UNMET,
    STATE_UNTESTED,
    _evidence_ref,
    _probe_command,
    _state_from_result,
)

# Shared parsers for fallback_inventory finding statements ("classified as X",
# "'op' ..."). Used by the capability rows (decision.py) and the risk rows here.
_ROUTE_RE = re.compile(r"classified as ([a-z][a-z-]+)")
_OP_RE = re.compile(r"^'(.+?)'")


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
