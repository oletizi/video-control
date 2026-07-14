# Feature Specification: Resolve Discovery Spike (Phase 0 Feasibility)

**Feature Branch**: `design/technical-discovery`

**Created**: 2026-07-14

**Status**: Draft

**Roadmap item**: `design:feature/technical-discovery` (part-of `multi:feature/resolve-automation-harness`)

**Design record**: `docs/superpowers/specs/2026-07-14-technical-discovery-design.md`

**Input**: Phase 0 technical-discovery feasibility spike for the DaVinci Resolve automation harness — a throwaway, Python-only spike whose sole deliverable is a trustworthy GO/NO-GO decision on whether DaVinci Resolve can be driven reliably from an external process, before any production harness code (roadmap milestones M1–M6) is built.

## User Scenarios & Testing *(mandatory)*

The "user" of this spike is the **harness team / operator** deciding whether to
fund the roadmap. Value is measured in *decision confidence*, not shipped
product. Each story is an independently runnable probe that yields evidence; the
final story synthesizes them into the decision.

### User Story 1 - Establish and diagnose the external connection (Priority: P1)

As the operator, I run a single `doctor` probe and learn — with evidence —
whether an external Python process can connect to the running DaVinci Resolve,
what version and **edition** it is, whether external scripting is permitted, and
which Python interpreter actually loads the native scripting library.

**Why this priority**: This is the MVP and the single most decisive slice. If an
external process cannot connect at all (e.g. the install is the free edition, or
`fusionscript.so` will not load under any available Python), the entire harness
thesis fails here and no further probe matters. It resolves the two largest
unknowns (edition gate, Python-load) in one step.

**Independent Test**: With Resolve running, execute the doctor probe; it emits a
structured report naming version, edition, scripting-permission state, the
working Python interpreter, and a connection PASS/FAIL — reproducible by re-running
the one command.

**Acceptance Scenarios**:

1. **Given** Resolve 20.3.2 is running with external scripting enabled, **When** the operator runs the doctor probe, **Then** it reports a successful connection, the version, the detected edition, and the Python interpreter that loaded the API.
2. **Given** the installed edition forbids external scripting (or scripting is disabled in Preferences), **When** the operator runs the doctor probe, **Then** it fails with a clear, actionable diagnosis naming the specific gate (edition vs permission vs interpreter) rather than an opaque error.
3. **Given** the default Homebrew Python 3.14.6 cannot load `fusionscript.so`, **When** the doctor probe runs, **Then** it reports the load failure and identifies a working interpreter (or records that none was found) as a documented constraint.

---

### User Story 2 - Inspect live project and timeline state (Priority: P2)

As the operator, I run an `inspect` probe against the active project and timeline
and receive a structured (JSON) description of its tracks, clips, markers, media
pool, and timeline settings.

**Why this priority**: "Inspect before mutate" is a core product principle;
proving the API exposes enough state as structured data is a prerequisite for
every safe workflow. Decisive, but only meaningful once US1 connects.

**Independent Test**: With a known test project open, run the inspect probe;
compare its JSON output against what is visible in the Resolve UI for the same
project/timeline.

**Acceptance Scenarios**:

1. **Given** a project with a timeline is active, **When** the operator runs the inspect probe, **Then** it emits JSON enumerating the project, timeline, tracks, clips, and markers that match the UI.
2. **Given** a timeline references offline/missing media, **When** the inspect probe runs, **Then** the missing media is represented explicitly in the output.

---

### User Story 3 - Build a test timeline deterministically (Priority: P2)

As the operator, I run a `build` probe that creates a test timeline, imports
sample media into a bin, places a clip, and adds a marker.

**Why this priority**: Timeline mutation is the heart of the harness. If clips,
timelines, and markers cannot be created reliably from script, the workflow
engine (M3) has nothing to compile to.

**Independent Test**: Run the build probe against an empty/scratch project; verify
in the UI (and via the inspect probe) that the timeline, imported media, placed
clip, and marker exist as specified.

**Acceptance Scenarios**:

1. **Given** a scratch project and available sample media, **When** the operator runs the build probe, **Then** a named test timeline exists containing the imported clip and the marker.
2. **Given** the build probe is run a second time, **When** it executes, **Then** its re-run behavior (duplicate vs no-op vs error) is observed and recorded as an idempotency finding.

---

### User Story 4 - Drive a render to completion (Priority: P2)

As the operator, I run a `render` probe that enqueues a render job from a preset
and waits for it to complete, then confirms the output file exists.

**Why this priority**: Rendering is the terminal deliverable of every workflow
and a Phase 0 exit criterion. Enqueue-and-complete reliability is a known risk
area in Resolve automation.

**Independent Test**: Run the render probe against the test timeline; confirm the
job completes and the expected output file is produced on disk.

**Acceptance Scenarios**:

1. **Given** a test timeline and a valid render preset, **When** the operator runs the render probe, **Then** a render job is enqueued, runs to completion, and the output file is present with non-zero size.
2. **Given** a render job fails or stalls, **When** the render probe is waiting, **Then** it reports the failure/stall with the job status rather than hanging silently.

---

### User Story 5 - Probe idempotency and reversibility (Priority: P3)

As the operator, I run probes that (a) enumerate the stable identifiers the API
exposes for clips/timelines/bins and (b) test snapshot/rollback options
(project export vs timeline duplication).

**Why this priority**: Idempotent re-runs and safe rollback are load-bearing for
the product's "safe by default" and "repeatable" principles, but they refine
rather than gate the core feasibility call.

**Independent Test**: Run the identity probe and confirm identifiers persist
across a save/reload; run the snapshot probe, mutate, then restore, and confirm
the restore succeeds.

**Acceptance Scenarios**:

1. **Given** a built timeline, **When** the identity probe runs before and after a save/reload, **Then** it reports whether the exposed identifiers are stable across the cycle.
2. **Given** a snapshot is taken and the timeline is then mutated, **When** the operator restores the snapshot, **Then** the mutation is reverted (or the probe records that reliable rollback is not achievable).

---

### User Story 6 - Inventory GUI-only fallback operations (Priority: P3)

As the operator, I receive an inventory of operations the MVP will need (e.g.
subtitle import, Fusion title-template insertion, silence detection) classified
as API-reachable vs GUI-only.

**Why this priority**: Informs how much of the roadmap depends on fragile GUI
automation — a strategic risk input, but not a hard gate on the core connection
feasibility.

**Independent Test**: Review the inventory; each listed operation has a
classification backed by an attempted API call or a cited API-surface gap.

**Acceptance Scenarios**:

1. **Given** the list of MVP-critical operations, **When** the inventory is produced, **Then** each operation is marked API-reachable or GUI-only with supporting evidence.

---

### User Story 7 - Produce the Go/No-Go decision package (Priority: P1)

As the operator, I read a single decision package — capability matrix, API risk
register, and a go/no-go recommendation — and can make the fund/narrow/stop call
without re-running anything.

**Why this priority**: This is the reason the spike exists. It is P1 as the
culminating deliverable; it aggregates the evidence from US1–US6.

**Independent Test**: A reviewer who did not run the probes can read
`spike/findings/go-no-go.md` and the capability matrix and reach the same
recommendation, tracing each gate criterion to its supporting evidence.

**Acceptance Scenarios**:

1. **Given** the probes have run, **When** the operator opens the decision package, **Then** each of the six go/no-go gate criteria is marked met/unmet with a link to its evidence.
2. **Given** any gate criterion is unmet, **When** the recommendation is written, **Then** it states NO-GO (or a narrowed scope) and names the specific blocking finding.

### Edge Cases

- What happens when **Resolve is not running** when a probe is invoked? (Expected: fail fast with a "start Resolve" diagnosis, not a hang.)
- What happens when **no Python interpreter** on the machine can load `fusionscript.so`? (Expected: recorded as a hard constraint; doctor reports it explicitly.)
- What happens when the install is the **free edition** and refuses external scripting? (Expected: US1 fails with the edition gate named; the in-app Console fallback is noted; this becomes a material NO-GO/narrow input.)
- What happens when a **render stalls indefinitely**? (Expected: the render probe times out with the last-known job status rather than blocking forever.)
- What happens on a **second run** of the build probe? (Expected: behavior observed and recorded — the idempotency finding — never assumed.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The spike MUST establish an external-process connection to a running DaVinci Resolve and report connection success/failure with an actionable diagnosis.
- **FR-002**: The spike MUST detect and report the Resolve version and **edition** (Studio vs free) and the external-scripting permission state.
- **FR-003**: The spike MUST determine which available Python interpreter loads the native scripting library, attempting the default Homebrew Python 3.14.6 first and falling back to a pinned Python 3.11 (or Resolve's bundled Python) if needed, and MUST record the working interpreter as a constraint for M1.
- **FR-004**: The spike MUST inspect the active project and timeline and emit the result as structured JSON covering tracks, clips, markers, media pool, timeline settings, and missing media.
- **FR-005**: The spike MUST create a test timeline, import sample media into a bin, place a clip, and add a marker, and MUST observe and record the behavior of a repeated run (idempotency).
- **FR-006**: The spike MUST enqueue a render from a preset, wait for completion, and confirm the output file exists — reporting failure/stall status rather than hanging.
- **FR-007**: The spike MUST enumerate the stable identifiers the API exposes and report whether they persist across a save/reload.
- **FR-008**: The spike MUST test at least one snapshot/rollback approach (project export and/or timeline duplication) and report whether reliable reversibility is achievable.
- **FR-009**: The spike MUST classify each MVP-critical operation (subtitle import, Fusion title-template insertion, silence detection) as API-reachable or GUI-only, with supporting evidence.
- **FR-010**: The spike MUST write its evidence to disk under `spike/findings/` as `capability-matrix.md`, `api-risk-register.md`, and `go-no-go.md`, plus raw JSON inspection dumps.
- **FR-011**: The go/no-go recommendation MUST evaluate all six gate criteria (reliable connection, structured inspection, test timeline created, test render completed, workable stable-identifier strategy, acceptable partial-failure recovery) and mark each met/unmet with traceable evidence.
- **FR-012**: When the sample media is not operator-supplied, the spike MUST synthesize a short throwaway screen-recording + voiceover pair to test against.
- **FR-013**: Every probe MUST be independently runnable as a single command and MUST fail fast with a clear diagnosis when Resolve is not running or not reachable.
- **FR-014**: The spike MUST be isolated as throwaway code under a `spike/` directory and MUST NOT introduce production CLI, workflow-engine, bridge, or packaged-workflow code (those are later milestones).

### Key Entities *(include if feature involves data)*

- **Probe**: A single-purpose, independently runnable script that exercises one capability and emits evidence (doctor, inspect, build, render, identity, snapshot, fallback-inventory).
- **Capability matrix**: A table mapping each attempted Resolve operation to a status (works / partial / GUI-only / unavailable) with notes.
- **API risk register**: A list of discovered risks (Python-load, edition gate, identifier stability, render reliability, reversibility, GUI-only ops) with severity and mitigation.
- **Go/No-Go decision**: The recommendation object mapping each of the six gate criteria to met/unmet + evidence, resolving to GO / NARROW / NO-GO.
- **Evidence artifact**: A file under `spike/findings/` (markdown report or raw JSON dump) that backs a matrix cell or gate criterion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The spike produces a go/no-go recommendation in which **all six** gate criteria are individually marked met/unmet, each traceable to a named evidence artifact.
- **SC-002**: A reviewer who did not run the probes can reproduce every probe result by running a single documented command per probe.
- **SC-003**: The two largest unknowns — installed **edition** and the **working Python interpreter** — are resolved to concrete recorded values (not left open).
- **SC-004**: Each MVP-critical operation in the fallback inventory carries an API-reachable / GUI-only classification with supporting evidence (0 unclassified).
- **SC-005**: Every probe fails fast (no indefinite hang) when Resolve is not running, demonstrated for at least the doctor and render probes.
- **SC-006**: No production (non-`spike/`) source file is added or modified by the spike.

## Assumptions

- DaVinci Resolve 20.3.2 is installed and can be launched and left running during the spike; external scripting can be enabled in Preferences by the operator.
- The installed edition is assumed to be Studio until the doctor probe proves otherwise; a free-edition finding is an expected, valued outcome (it materially informs the decision).
- Sample media is synthesized by the spike (a short screen recording + voiceover) because the operator supplied none at design time; real media may be substituted later.
- The spike is throwaway: it lives under `spike/`, is not intended to become product code, and may take shortcuts a shipped harness would not.
- Falling back from Homebrew Python 3.14.6 to a pinned Python 3.11 (via pyenv/uv) or Resolve's bundled Python is acceptable for the spike; the working choice becomes a hard constraint recorded for M1.
- All spike work stays on the single `design/technical-discovery` branch (the spec directory name is independent of the branch; `.specify/feature.json` resolves the active feature dir for downstream commands).
- The eventual harness implementation language (TypeScript-with-bridge vs Python-native) is deliberately NOT decided by this spike; it is informed by the findings and settled in a later milestone.
