# Implementation Plan: Resolve Discovery Spike (Phase 0 Feasibility)

**Branch**: `design/technical-discovery` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-resolve-discovery-spike/spec.md`

## Summary

A throwaway, Python-only feasibility spike that drives a running DaVinci Resolve
20.3.2 through the native `DaVinciResolveScript` API to answer one question with
reproducible evidence: **can Resolve be driven reliably from an external process?**
Eight independently-runnable probes (doctor, inspect, build, render, identity,
snapshot, partial-failure, fallback-inventory) each emit provenance-stamped,
evidence-strength-labeled findings under `spike/findings/`. A decision step applies
the spec's **Decision Policy** to the recorded gate results and emits a GO / NARROW /
NO-GO recommendation. All code is isolated under a top-level `spike/` directory and
touches no production (`src/`) code.

## Technical Context

**Language/Version**: Python. The **working interpreter is resolved empirically** by
the doctor probe (FR-003): attempt the operator default (Homebrew Python 3.14.6)
first, then documented fallbacks — a pinned Python 3.11 (via `uv`/pyenv) and any
Resolve-provided runtime. The load-capable interpreter is recorded as a hard M1
constraint. Plan targets Python 3.11-compatible syntax so a fallback runtime works.

**Primary Dependencies**: `DaVinciResolveScript` (native module loading
`fusionscript.so` via the `RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` / `PYTHONPATH`
env vars); `ffmpeg` (deterministic synthetic media generation); Python standard
library only for everything else (`json`, `subprocess`, `dataclasses`, `argparse`,
`pathlib`, `platform`, `time`). No web/service frameworks.

**Storage**: Files only. Evidence artifacts (markdown + JSON) under `spike/findings/`;
the reference-fixture manifest under `spike/fixtures/`. No database.

**Testing**: The probes *are* the experiment. Correctness of the inspect probe is
machine-checked against a version-controlled expected manifest (FR-007). A small
assertion helper compares actual vs expected; a full test framework is not required
(pytest optional for the fixture-diff only).

**Target Platform**: macOS (arm64), DaVinci Resolve 20.3.2, external scripting enabled.

**Project Type**: Single-project throwaway CLI spike, isolated under `spike/`.

**Performance Goals**: N/A (feasibility, not performance). The render probe exposes a
configurable overall timeout, poll interval, and stall threshold (FR-006) — operational
guards, not performance targets.

**Constraints**: MUST NOT modify or add any non-`spike/` source (the existing Remotion
`src/` product is off-limits, FR-019); no persistent background service; Resolve must be
running and reachable; every probe fails fast (no hangs) when it is not (FR-014).

**Scale/Scope**: 8 probes + shared env/evidence helpers + synthetic-media generator +
reference fixture + decision step + 3 findings documents.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The project constitution (`.specify/memory/constitution.md`) is an **unratified
template** (placeholder principles only) — there are no concrete ratified gates to
evaluate against. Rather than fabricate gates, this plan is checked against the
**spec's own guardrails**, which serve as the effective constitution for this spike:

- **Throwaway isolation** — all code under `spike/`, no `src/` mutation (FR-019). ✅ honored by structure below.
- **Evidence rigor** — provenance (FR-015) + evidence-strength labels (FR-016) on every finding. ✅ modeled in Phase 1 data-model.
- **Reproducibility** — one command per probe; deterministic fixtures (FR-012); machine-checked inspection (FR-007). ✅.
- **Deterministic decision** — recommendation derived via the Decision Policy (FR-017), not judgment. ✅.

**Result: PASS** (no violations; no Complexity Tracking entries required).

## Project Structure

### Documentation (this feature)

```text
specs/001-resolve-discovery-spike/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output (evidence + fixture data model)
├── quickstart.md        # Phase 1 output (end-to-end run guide)
├── contracts/           # Phase 1 output (per-probe CLI contracts)
│   └── probes.md
├── checklists/
│   └── requirements.md  # spec quality checklist (already present)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
spike/                              # throwaway; the ONLY tree this feature writes to
├── README.md                       # what the spike is, how to run it, safety notes
├── resolve_env.py                  # env-var setup + interpreter/lib resolution (shared)
├── evidence.py                     # provenance stamp + evidence-strength labeling helpers
├── decision.py                     # applies the Decision Policy → GO/NARROW/NO-GO
├── probes/
│   ├── doctor.py                   # US1  — connection (multi-run), version, edition, interpreter
│   ├── inspect.py                  # US2  — project/timeline → JSON, diffed vs fixture
│   ├── build.py                    # US3  — create timeline, import, place clip, marker
│   ├── render.py                   # US4  — enqueue + wait w/ timeout/stall semantics
│   ├── identity.py                 # US5  — stable-identifier probe
│   ├── snapshot.py                 # US6  — reversibility probe
│   ├── partial_failure.py          # US7  — failure-injection probe
│   └── fallback_inventory.py       # US8  — four-route classification
├── fixtures/
│   ├── make_media.py               # deterministic synthetic AV via ffmpeg (FR-012)
│   ├── expected_manifest.json      # reference fixture expected state (FR-007)
│   └── media/                      # generated media (gitignored)
└── findings/                       # evidence outputs (US9 decision package)
    ├── capability-matrix.md
    ├── api-risk-register.md
    ├── go-no-go.md
    └── raw/                        # per-probe JSON dumps (provenance-stamped)
```

**Structure Decision**: Single throwaway tree at `spike/`. `spike/probes/*` are the
eight independently-runnable probes; `spike/resolve_env.py` and `spike/evidence.py`
are the only shared modules (connection bootstrap + evidence stamping); `spike/decision.py`
is the Decision-Policy evaluator. Nothing outside `spike/` is created or modified. The
existing `src/` (Remotion/TypeScript product) is never touched.

## Complexity Tracking

*No Constitution Check violations — this section is intentionally empty.*
