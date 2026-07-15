"""Shared evidence & provenance helpers for the Resolve discovery spike.

Every probe (doctor, inspect, build, render, identity, snapshot,
partial_failure, fallback_inventory) imports this module to stamp provenance
(FR-015) and label findings with an evidence strength (FR-016). The spike's
"data" is its evidence; these are the exact shapes described in
``specs/001-resolve-discovery-spike/data-model.md`` and the probe output
contract in ``contracts/probes.md``.

Everything here is deliberately JSON-serializable (plain dicts + primitives)
so a reviewer who never ran the probes can read the raw artifacts and the
decision aggregator (``decision.py``) can consume them mechanically.

Spike-grade code, rigorous evidence model. Python 3.11 compatible.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #

# This module lives at spike/evidence.py, so the spike root is its parent.
SPIKE_ROOT = Path(__file__).resolve().parent
RAW_FINDINGS_DIR = SPIKE_ROOT / "findings" / "raw"


# --------------------------------------------------------------------------- #
# EvidenceStrength (FR-016)
# --------------------------------------------------------------------------- #

class EvidenceStrength(str, Enum):
    """The evidence-strength label attached to every recorded finding.

    Exactly these seven labels are permitted (data-model.md / FR-016). The
    ``str`` mixin makes every member JSON-serializable as its wire value.

    ``NOT_FOUND`` is a first-class, *distinct* label. It means "this was not
    discovered during the spike" and MUST NOT be conflated with, promoted to,
    or rendered as "proven impossible" (FR-016, data-model rule). Impossibility
    would be ``OBSERVED_FAIL`` / ``DOCUMENTED_UNSUPPORTED`` backed by evidence;
    absence of a finding is simply ``NOT_FOUND``. The two are never the same.
    """

    OBSERVED_PASS = "observed-pass"
    OBSERVED_FAIL = "observed-fail"
    DOCUMENTED_SUPPORTED = "documented-supported"
    DOCUMENTED_UNSUPPORTED = "documented-unsupported"
    NOT_FOUND = "not-found"
    INFERRED = "inferred"
    UNTESTED = "untested"


# Frozen set of the exact permitted wire values, for fast validation.
EVIDENCE_STRENGTHS: frozenset[str] = frozenset(e.value for e in EvidenceStrength)


def validate_evidence_strength(value: Any) -> str:
    """Return the canonical wire string for ``value`` or raise ValueError.

    Accepts an ``EvidenceStrength`` member or one of the exact wire strings.
    Anything else is rejected loudly — no silent coercion, no default. This is
    how "not found" is prevented from drifting into any other meaning.
    """
    if isinstance(value, EvidenceStrength):
        return value.value
    if isinstance(value, str) and value in EVIDENCE_STRENGTHS:
        return value
    permitted = ", ".join(sorted(EVIDENCE_STRENGTHS))
    raise ValueError(
        f"invalid EvidenceStrength {value!r}; must be one of: {permitted}"
    )


# --------------------------------------------------------------------------- #
# Confidence (FR-002)
# --------------------------------------------------------------------------- #

class Confidence(str, Enum):
    """Confidence classification for values the API does not authoritatively
    expose (edition, scripting availability) — FR-002.

    ``DIRECT``   -> read straight from an authoritative API call.
    ``INFERRED`` -> deduced from indirect evidence (e.g. "external scripting
                    connection succeeded, therefore Studio edition").
    """

    DIRECT = "direct"
    INFERRED = "inferred"


CONFIDENCES: frozenset[str] = frozenset(c.value for c in Confidence)


def validate_confidence(value: Any) -> str:
    """Return the canonical wire string for a Confidence or raise ValueError."""
    if isinstance(value, Confidence):
        return value.value
    if isinstance(value, str) and value in CONFIDENCES:
        return value
    permitted = ", ".join(sorted(CONFIDENCES))
    raise ValueError(
        f"invalid Confidence {value!r}; must be one of: {permitted}"
    )


# --------------------------------------------------------------------------- #
# Result classification (probe-level outcome)
# --------------------------------------------------------------------------- #

class ProbeOutcome(str, Enum):
    """Probe-level outcome recorded in provenance and ProbeResult."""

    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    SKIPPED = "skipped"


PROBE_OUTCOMES: frozenset[str] = frozenset(o.value for o in ProbeOutcome)


def validate_result(value: Any) -> str:
    """Return the canonical wire string for a probe outcome or raise."""
    if isinstance(value, ProbeOutcome):
        return value.value
    if isinstance(value, str) and value in PROBE_OUTCOMES:
        return value
    permitted = ", ".join(sorted(PROBE_OUTCOMES))
    raise ValueError(
        f"invalid probe result {value!r}; must be one of: {permitted}"
    )


# --------------------------------------------------------------------------- #
# edition value (FR-002)
# --------------------------------------------------------------------------- #

def edition(value: str, confidence: Any, evidence: str) -> dict[str, Any]:
    """Build the ``{value, confidence, evidence}`` edition shape (FR-002).

    The edition is never presented as an authoritative API value from a
    filesystem/process-name heuristic; every edition claim carries a validated
    confidence label and the supporting evidence string. Example::

        edition("Studio", Confidence.INFERRED,
                "external scripting connection succeeded")
    """
    return {
        "value": value,
        "confidence": validate_confidence(confidence),
        "evidence": evidence,
    }


# --------------------------------------------------------------------------- #
# Provenance (FR-015)
# --------------------------------------------------------------------------- #

def _iso_now_local() -> str:
    """Current wall-clock time as ISO-8601 with the local UTC offset."""
    return datetime.now(timezone.utc).astimezone().isoformat()


def _host_os() -> str:
    """Human-friendly OS label, e.g. ``macOS`` rather than ``Darwin``."""
    system = platform.system()
    return "macOS" if system == "Darwin" else system


def probe_commit() -> str:
    """Return the spike's git SHA (``git rev-parse HEAD``).

    Degrades to the literal string ``"unknown"`` if this is not a git
    checkout or git is unavailable — the artifact is still valid, provenance
    just records that the commit could not be resolved.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(SPIKE_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if completed.returncode != 0:
        return "unknown"
    sha = completed.stdout.strip()
    return sha or "unknown"


def build_provenance(
    probe: str,
    result: Any,
    *,
    resolve_version: str = "unknown",
    resolve_edition: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble the provenance stamp embedded in every artifact (FR-015).

    Args:
        probe: probe name, e.g. ``doctor``, ``inspect``.
        result: probe-level outcome (``pass``/``fail``/``partial``/``skipped``).
        resolve_version: from ``GetVersionString()`` (a ``direct`` value).
            Defaults to ``"unknown"`` because it comes from the live
            connection the probe owns, and a probe that cannot connect still
            needs to stamp provenance.
        resolve_edition: an ``edition()`` dict from the live connection. When
            omitted, an ``untested`` placeholder edition is recorded so the
            field always has the documented ``{value, confidence, evidence}``
            shape rather than being null/absent.

    Returns a JSON-serializable dict matching the Provenance table exactly.
    """
    if resolve_edition is None:
        resolve_edition = edition(
            "unknown",
            Confidence.INFERRED,
            "edition not determined (no edition evidence supplied by probe)",
        )
    else:
        # Validate the confidence label of a caller-supplied edition dict.
        if "confidence" not in resolve_edition:
            raise ValueError("resolve_edition must have a 'confidence' key")
        validate_confidence(resolve_edition["confidence"])

    return {
        "timestamp": _iso_now_local(),
        "host_os": _host_os(),
        "host_arch": platform.machine(),
        "resolve_version": resolve_version,
        "resolve_edition": resolve_edition,
        "python_path": sys.executable,
        "python_version": platform.python_version(),
        "probe": probe,
        "probe_commit": probe_commit(),
        "result": validate_result(result),
    }


# --------------------------------------------------------------------------- #
# Finding (FR-016)
# --------------------------------------------------------------------------- #

def finding(
    id: str,
    statement: str,
    strength: Any,
    evidence: str,
    raw_ref: Optional[str] = None,
) -> dict[str, Any]:
    """Build a single recorded observation (a Finding).

    Args:
        id: stable within a probe, e.g. ``doctor.connect``, ``render.timeout``.
        statement: what was observed.
        strength: an EvidenceStrength (member or wire string); validated.
        evidence: supporting detail / pointer to command output.
        raw_ref: path to a raw JSON dump under ``findings/raw/``, or ``None``.

    Returns a JSON-serializable dict matching the Finding table exactly.
    """
    return {
        "id": id,
        "statement": statement,
        "strength": validate_evidence_strength(strength),
        "evidence": evidence,
        "raw_ref": raw_ref,
    }


# --------------------------------------------------------------------------- #
# ProbeResult + writer
# --------------------------------------------------------------------------- #

def build_probe_result(
    provenance: dict[str, Any],
    findings: list[dict[str, Any]],
    result: Any,
) -> dict[str, Any]:
    """Assemble the ProbeResult shape (provenance + findings + result).

    Each finding is re-validated so a malformed strength cannot slip through
    even if a probe hand-built the dict instead of using ``finding()``.
    """
    validated_findings: list[dict[str, Any]] = []
    for f in findings:
        if "strength" not in f:
            raise ValueError(f"finding {f.get('id')!r} is missing 'strength'")
        validate_evidence_strength(f["strength"])
        validated_findings.append(f)

    return {
        "provenance": provenance,
        "findings": validated_findings,
        "result": validate_result(result),
    }


def write_probe_result(
    probe_name: str,
    provenance: dict[str, Any],
    findings: list[dict[str, Any]],
    result: Any,
) -> Path:
    """Serialize a ProbeResult to ``spike/findings/raw/<probe>.json``.

    Creates parent directories as needed. Returns the path written so the
    probe can print it and reference it as a ``raw_ref``.
    """
    probe_result = build_probe_result(provenance, findings, result)
    RAW_FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_FINDINGS_DIR / f"{probe_name}.json"
    out_path.write_text(
        json.dumps(probe_result, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return out_path


# --------------------------------------------------------------------------- #
# __main__ smoke (does NOT require Resolve)
# --------------------------------------------------------------------------- #

def _smoke() -> dict[str, Any]:
    """Construct a sample ProbeResult without touching Resolve."""
    prov = build_provenance(
        probe="smoke",
        result=ProbeOutcome.PASS,
        resolve_version="20.3.2",
        resolve_edition=edition(
            "Studio",
            Confidence.INFERRED,
            "external scripting connection succeeded",
        ),
    )
    findings = [
        finding(
            id="smoke.evidence_model",
            statement="evidence module constructs a valid ProbeResult",
            strength=EvidenceStrength.OBSERVED_PASS,
            evidence="in-process construction of provenance + finding",
        ),
        finding(
            id="smoke.not_found_is_distinct",
            statement="not-found is a distinct label, not 'proven impossible'",
            strength=EvidenceStrength.NOT_FOUND,
            evidence="see EvidenceStrength docstring (FR-016)",
        ),
    ]
    return build_probe_result(prov, findings, ProbeOutcome.PASS)


if __name__ == "__main__":
    print(json.dumps(_smoke(), indent=2))
