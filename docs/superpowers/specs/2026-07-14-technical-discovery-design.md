# Design: Phase 0 Technical-Discovery Spike

**Roadmap item:** `design:feature/technical-discovery`
**Date:** 2026-07-14
**Status:** design approved (operator: oletizi)

/ A feasibility spike for the DaVinci Resolve automation harness. Its only job is
to produce a trustworthy **go/no-go** on whether Resolve can be driven reliably
from an external process, before any of M1–M6 is built. /

## Problem domain

The roadmap (`multi:feature/resolve-automation-harness`) proposes a build-system-
style harness that lets coding agents assemble, inspect, and render DaVinci
Resolve projects from declarative YAML. Everything downstream (M1 connectivity →
M6 developer preview, then the phase epics) is blocked on one unproven premise:
**that Resolve can be driven reliably enough from an external process to support a
repeatable, inspectable, recoverable workflow.** If that premise fails, the
roadmap is built on sand.

Empirical grounding from probing this machine (2026-07-14):

- **Resolve 20.3.2 is installed** at `/Applications/DaVinci Resolve/DaVinci Resolve.app`.
- The scripting API package (updated 2025-10-07) is present at
  `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/`,
  including `Modules/DaVinciResolveScript.py` and the compiled
  `Contents/Libraries/Fusion/fusionscript.so`.
- The API is **Python-native**: an external process connects by importing
  `DaVinciResolveScript` (a shim that loads `fusionscript.so`) with
  `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH` exported. Supported:
  **Python ≥ 3.6 64-bit**.
- Resolve **must be running** for a script to connect, and external scripting must
  be **enabled in Preferences** (default is Console-only; external processes need
  the "local network" permission).
- The vendor README is explicitly titled *"Scripting API for DaVinci Resolve
  **Studio**"* — external scripting has historically been a Studio-only feature.

Concrete unknowns the spike must resolve:

- Does `fusionscript.so` **load under the installed Homebrew Python 3.14.6**? The
  API only promises ≥3.6; the compiled lib is version-sensitive and 3.14 is very
  new.
- Is this install **licensed as Studio**? The free edition may refuse an external
  connection entirely.
- Are there **stable identifiers** for clips/timelines/bins to make re-runs
  idempotent?
- What **snapshot/rollback** primitives are scriptable?
- Is **render automation** (enqueue → complete) reliable and observable?
- Which MVP-critical ops (subtitle import, Fusion title templates, silence
  detection) are **API-reachable vs GUI-only**?

## Solution space

The chosen shape and the rejected alternatives (this section satisfies the
≥2-alternatives gate).

### Chosen — Python-only throwaway spike

A `spike/` directory (deliberately **not** `src/`) of thin, single-purpose Python
scripts, each proving one capability, producing structured evidence: a capability
matrix, an API risk register, and a go/no-go recommendation. This is the fastest
path to trustworthy truth and has zero coupling to eventual product code. It
isolates the one question that matters now — *can we reliably drive Resolve?* —
from the separate, later question of *what language the product is*.

The spike prototypes in Python **regardless of the eventual harness language**,
because Python is Resolve's native control surface and therefore the lowest-risk
way to reach the connection quickly.

### Rejected — Skip the spike, build M1 connectivity directly

Build the production CLI (`impl:feature/resolve-connectivity`) straight away and
learn as we go. Rejected: couples learning to production code and defeats the
entire purpose of a cheap Phase 0 gate. The brief's own recommendation is a short
discovery phase first.

### Rejected — Python core + TypeScript bridge in the spike

Also prototype the TS→Python bridge (a TS CLI shelling out to a Python worker that
holds the Resolve connection over stdio JSON-RPC). Rejected this session: it adds
the IPC seam as a *second* unproven variable and slows time-to-truth. The bridge
can be de-risked in M1 once Resolve-control itself is proven. (Operator decision,
2026-07-14: "Python-only spike.")

### Rejected — TypeScript-only via direct FFI to fusionscript.so

Load `fusionscript.so` directly from Node via an FFI. Rejected: it is a Python
C-extension, not a plain C ABI; loading it from Node is high-risk to infeasible
and directly contradicts the vendor README's documented usage.

### Rejected (as primary) — In-app Console / Scripts-menu only

Drive Resolve only via scripts placed in the Fusion Scripts folders and invoked
from the in-app Console/menu, with no external process. Rejected as the primary
path: it does not test the **agent-driven external automation** the product
depends on. **Retained as a documented fallback** if external scripting proves
unavailable on this machine (e.g. a free-edition license) — in which case that
finding itself is a material go/no-go input.

## Decisions

- **Language/runtime:** Python only, throwaway, under `spike/`. Test against the
  installed Resolve 20.3.2.
- **Python-version risk, resolved empirically:** attempt Homebrew 3.14.6 first; if
  `fusionscript.so` will not load, fall back to a pinned 3.11 (pyenv/uv) or
  Resolve's bundled Python, and **document the working version** as a hard M1
  constraint.
- **Spike probes** (mapped 1:1 to the brief's Phase 0 exit criteria):
  1. `doctor` — env vars, connection handshake, Resolve version + **edition**
     detection, external-scripting-permission check.
  2. `inspect` — active project & timeline → structured JSON.
  3. `build` — create a test timeline, import sample media, place a clip, add a
     marker.
  4. `render` — enqueue a render preset and **wait for completion**.
  5. `identity` — probe stable identifiers (e.g. `GetUniqueId`) for idempotent
     re-runs.
  6. `snapshot` — probe project-export vs timeline-duplicate for rollback.
  7. `fallback-inventory` — enumerate ops that are GUI-only.
- **Evidence artifacts** written to disk under `spike/findings/`:
  `capability-matrix.md`, `api-risk-register.md`, `go-no-go.md`, plus raw JSON
  inspection dumps.
- **Sample media:** default to the **spike generating/synthesizing a short
  throwaway screen-recording + voiceover pair** (operator did not supply one at
  design time); operator may substitute real media later.
- **Go/No-Go gate**, encoded directly from the brief: reliable connection ·
  structured inspection · test timeline created · test render completed · a
  workable stable-identifier strategy · acceptable partial-failure recovery. A GO
  advances `impl:feature/resolve-connectivity`; a NO-GO triggers the brief's
  "reconsider or narrow" clause.

## Open questions

The spike resolves these; none block starting it.

1. Is the installed edition Studio? (resolved in `doctor`)
2. Which Python version actually loads `fusionscript.so`?
3. What stable identifiers does the API expose, and are they durable across
   save/reload?
4. Snapshot granularity — project export vs timeline duplication — what is
   genuinely scriptable and reversible?
5. Which MVP ops (subtitle import, Fusion title templates, silence detection) are
   API-reachable vs GUI-only?
6. Sample media — default is spike-synthesized throwaway footage; confirm whether
   real footage should replace it before M1.

## Provenance

- **Roadmap item:** `design:feature/technical-discovery`, part-of
  `multi:feature/resolve-automation-harness`.
- **Source brief:** `docs/product-brief-resolve-harness.md` (Phase 0: Technical
  Discovery and Feasibility; Go/No-Go Criteria).
- **Environment probe (2026-07-14):** Resolve 20.3.2 installed; scripting API at
  the standard macOS path; `fusionscript.so` present; Homebrew Python 3.14.6;
  Resolve not currently running; README declares Studio + Python ≥ 3.6.
- **Design method:** `superpowers:brainstorming` driven in-session via
  `/stack-control:design`, with the capture-over-YAGNI house rule injected.
- **Operator decisions (2026-07-14):** (a) "you should check" → environment probed
  directly rather than asked; (b) "Python-only spike" chosen over Python+TS-bridge
  and let-the-spike-decide; (c) design approved.
- **Handoff target:** `/stack-control:define` (Spec Kit spec authoring).
