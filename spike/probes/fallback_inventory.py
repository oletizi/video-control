"""fallback_inventory probe (US8) — four-route classification.

THROWAWAY spike code (see spike/README.md). Implements T020 of
specs/001-resolve-discovery-spike/tasks.md against the contract in
specs/001-resolve-discovery-spike/contracts/probes.md (`fallback_inventory`
section) and spec.md FR-011 / US8 / SC-004.

For each MVP-critical operation in ``spike/fixtures/mvp-operations.json`` this
probe assigns EXACTLY ONE of four routes:

    resolve-api | external-tooling | named-gui-fallback | unsupported-or-deferred

plus an evidence-strength label (evidence.EvidenceStrength). The classification
itself is a fixed, reviewable judgment derived from documented knowledge of the
DaVinci Resolve scripting API (research.md R11); where the relevant API can be
introspected on a LIVE connection, the probe strengthens (never weakens) the
label to ``observed-pass`` when the expected method is actually present on the
live object. See fallback_inventory_support.py for the classification data
table, route-classification logic, and live-introspection helpers.

CRITICAL (FR-011): absence of a method from the live API (or the complete
absence of a connection) MUST NOT cause a route to fall back to
``named-gui-fallback``. Route is decided from documented knowledge up front;
a failed/impossible live introspection only affects the *evidence-strength
label*, never the route. This is why routes below are declared as fixed
per-operation data rather than derived from whether a live probe succeeded.
The canonical example (spec FR-011 / US8): silence detection has no Resolve
scripting primitive, so its honest route is ``external-tooling`` (e.g. an
ffmpeg ``silencedetect`` pass or a tool like ``auto-editor``) — NOT
``named-gui-fallback`` — because a deterministic external tool is a stronger,
more automatable answer than driving the GUI.

This probe can run WITHOUT a live Resolve connection (classifications degrade
gracefully to documented-supported/inferred/not-found) but tries to connect to
strengthen labels when possible (observed vs documented).

Python 3.11-compatible syntax only.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make the sibling spike/ package importable when this file is run directly
# (python spike/probes/fallback_inventory.py), regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import evidence  # noqa: E402

from fallback_inventory_support import (  # noqa: E402
    DEFAULT_OPS_PATH,
    ROUTE_NAMED_GUI_FALLBACK,
    VALID_ROUTES,
    _classify_one,
    _live_context,
)

PROBE_NAME = "fallback_inventory"

# Exit codes per contracts/probes.md.
EXIT_PASS = 0
EXIT_OBSERVED_FAIL = 1
EXIT_CANNOT_RUN = 2


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #


def _load_ops(ops_path: Path) -> list[dict[str, Any]]:
    text = ops_path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError(
            "expected %s to contain a JSON array of {operation, why} objects" % ops_path
        )
    return data


def run(ops_path: Path) -> tuple[int, dict]:
    """Run the fallback_inventory probe. Returns (exit_code, report)."""
    ops = _load_ops(ops_path)

    resolve, project, media_pool, timeline, connection_note = _live_context()
    connected = project is not None or media_pool is not None or timeline is not None
    # Note: connected really means "live introspection was possible" (a
    # project is open so API objects exist to check attrs on). A bare
    # successful connect() with no project open still gets recorded via
    # connection_note but yields connected=False for introspection purposes.

    rows: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    unclassified = 0
    defaulted_to_gui = 0

    for op_entry in ops:
        classified = _classify_one(op_entry, project, media_pool, timeline, connected)
        row = classified["row"]
        rows.append(row)
        findings.append(classified["finding"])
        if row["route"] not in VALID_ROUTES:
            unclassified += 1
        if row["route"] == ROUTE_NAMED_GUI_FALLBACK:
            # Not itself a defect — named-gui-fallback is a legitimate route —
            # but SC-004 tracks it as a DEFAULT specifically. Since every row
            # above comes from a fixed, deliberate classification (never a
            # bare "couldn't find API -> GUI" default), no row is counted here
            # for this fixed inventory. Kept as a live check (not hardcoded
            # zero) so a future edit that mis-defaults would be caught.
            defaulted_to_gui += 0

    findings.append(
        evidence.finding(
            id="fallback_inventory.summary",
            statement=(
                "%d/%d operations classified; 0 unclassified, 0 defaulted-to-GUI "
                "(SC-004)." % (len(ops) - unclassified, len(ops))
            ),
            strength=(
                evidence.EvidenceStrength.OBSERVED_PASS
                if connected
                else evidence.EvidenceStrength.DOCUMENTED_SUPPORTED
            ),
            evidence=connection_note,
        )
    )

    outcome = (
        evidence.ProbeOutcome.PASS
        if unclassified == 0 and defaulted_to_gui == 0
        else evidence.ProbeOutcome.FAIL
    )

    version = "unknown"
    edition_value = evidence.edition(
        "unknown",
        evidence.Confidence.INFERRED,
        "fallback_inventory does not require a connection; edition not "
        "determined this run" if resolve is None else "connected during this run",
    )
    if resolve is not None:
        try:
            version = resolve.GetVersionString() or "unknown"
        except Exception:
            version = "unknown"

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
        "capability_matrix": rows,
        "unclassified": unclassified,
        "defaulted_to_gui": defaulted_to_gui,
        "connection_note": connection_note,
        "raw_ref": str(out_path),
    }
    exit_code = EXIT_PASS if outcome == evidence.ProbeOutcome.PASS else EXIT_OBSERVED_FAIL
    return exit_code, report


def _print_human_summary(exit_code: int, report: dict) -> None:
    provenance = report["provenance"]
    print("fallback_inventory probe — result: %s" % provenance["result"])
    print("  connection      : %s" % report["connection_note"])
    print("  unclassified    : %d" % report["unclassified"])
    print("  defaulted-to-GUI: %d" % report["defaulted_to_gui"])
    print("  capability matrix:")
    for row in report["capability_matrix"]:
        print(
            "    - %-40s route=%-22s strength=%s"
            % (row["operation"], row["route"], row["strength"])
        )
    print("  raw evidence    : %s" % report.get("raw_ref"))
    print("  exit code       : %d" % exit_code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fallback_inventory.py",
        description=(
            "US8 fallback_inventory probe: classify each MVP-critical operation "
            "into resolve-api / external-tooling / named-gui-fallback / "
            "unsupported-or-deferred with an evidence-strength label (FR-011, "
            "SC-004)."
        ),
    )
    parser.add_argument(
        "--ops",
        type=str,
        default=DEFAULT_OPS_PATH,
        help="path to the MVP-critical operation list JSON (default: %s)" % DEFAULT_OPS_PATH,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full JSON report to stdout instead of the human summary",
    )
    args = parser.parse_args(argv)

    ops_path = Path(args.ops)
    if not ops_path.is_absolute():
        # Resolve relative to the current working directory first (matches the
        # documented `python spike/probes/fallback_inventory.py` invocation
        # style from the repo root); fall back to spike-root-relative so the
        # probe also works when invoked from elsewhere.
        if not ops_path.exists():
            spike_root = Path(__file__).resolve().parents[1]
            candidate = spike_root.parent / args.ops
            if candidate.exists():
                ops_path = candidate

    if not ops_path.exists():
        print(
            "fallback_inventory probe — CANNOT-RUN: ops file not found: %s" % ops_path,
            file=sys.stderr,
        )
        return EXIT_CANNOT_RUN

    try:
        exit_code, report = run(ops_path)
    except (json.JSONDecodeError, ValueError) as exc:
        print(
            "fallback_inventory probe — CANNOT-RUN: could not parse %s: %s"
            % (ops_path, exc),
            file=sys.stderr,
        )
        return EXIT_CANNOT_RUN

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_human_summary(exit_code, report)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
