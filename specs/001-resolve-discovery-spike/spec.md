# Feature Specification: Resolve Discovery Spike (Phase 0 Feasibility)

**Feature Branch**: `design/technical-discovery`

**Created**: 2026-07-14

**Status**: Draft (revised after third-party review, 2026-07-14)

**Roadmap item**: `design:feature/technical-discovery` (part-of `multi:feature/resolve-automation-harness`)

**Design record**: `docs/superpowers/specs/2026-07-14-technical-discovery-design.md`

**Input**: Phase 0 technical-discovery feasibility spike for the DaVinci Resolve automation harness — a throwaway, Python-only spike whose sole deliverable is a trustworthy, reproducible GO / NARROW / NO-GO decision on whether DaVinci Resolve can be driven reliably from an external process, before any production harness code (roadmap milestones M1–M6) is built.

## User Scenarios & Testing *(mandatory)*

The "user" of this spike is the **operator / decision-maker** deciding whether to
fund the roadmap. Value is measured in *decision confidence*, not shipped
product. The nine stories are organized into three **decision groups** that carry
different strategic weight (see [Decision Policy](#decision-policy)):

- **Group A — Core feasibility (hard gates).** A failure here is a candidate NO-GO.
  US1 doctor · US2 inspect · US3 build · US4 render.
- **Group B — Product architecture viability (narrowing gates).** A failure here
  narrows scope or forces an architectural choice, but need not sink the product.
  US5 identity · US6 reversibility · US7 partial-failure recovery.
- **Group C — Roadmap-shaping evidence (informational).** Findings shape later
  milestones and produce the decision. US8 fallback inventory · US9 decision package.

Each story is independently runnable and evidence-producing. Every result an
artifact records carries an **evidence-strength label** (see FR-016) so that
"not discovered during the spike" is never silently promoted to "proven impossible."

---

### Group A — Core feasibility (hard gates)

### User Story 1 - Establish and diagnose the external connection (Priority: P1)

As the operator, I run a `doctor` probe and learn — with evidence — whether an
external Python process can connect to the running DaVinci Resolve **repeatably**,
what version and **edition** it is, whether external scripting is available, and
which Python interpreter loads the native scripting library.

**Why this priority**: This is the MVP and the single most decisive slice. If an
external process cannot connect under any supportable local configuration, the
harness thesis fails here.

**Independent Test**: With Resolve running, execute the doctor probe; it emits a
structured report and a connection verdict, reproducible by re-running the one
command.

**Acceptance Scenarios**:

1. **Given** Resolve 20.3.2 is running with external scripting available, **When** the operator runs the doctor probe, **Then** it reports connection success, the version, the edition (with a confidence label per FR-002), and the interpreter that loaded the API.
2. **Given** the doctor probe runs a documented multi-run sequence (repeat query without restart; Resolve closed → fast fail; Resolve restarted → recovery; project switched), **When** it completes, **Then** it records the outcome of each phase and reports reliable vs unreliable connectivity (FR-013).
3. **Given** external scripting is unavailable (free edition or disabled in Preferences), **When** the doctor probe runs, **Then** it fails with an actionable diagnosis naming the specific gate (edition vs permission vs interpreter) — a valued finding, not a spike crash.
4. **Given** the operator's default interpreter cannot load the native library, **When** the doctor probe runs, **Then** it proceeds through the documented fallback interpreters and records which one works (or that none do) per FR-003.

---

### User Story 2 - Inspect live project and timeline state against a fixture (Priority: P1)

As the operator, I run an `inspect` probe against a **known reference fixture**
project and receive structured (JSON) output that is compared automatically to the
fixture's expected manifest.

**Why this priority**: "Inspect before mutate" is a core product principle; proving
the API exposes enough state as *structured, verifiable* data is a prerequisite for
every safe workflow.

**Independent Test**: Open the version-controlled fixture project; run the inspect
probe; a machine comparison against the expected manifest reports matches and
differences automatically. The Resolve UI is a secondary manual check only.

**Acceptance Scenarios**:

1. **Given** the reference fixture (see FR-007) is active, **When** the operator runs the inspect probe, **Then** its JSON enumerates project, timeline, tracks, clips, and markers, and a comparison against the expected manifest reports 0 unexplained differences.
2. **Given** the fixture references intentionally-offline media, **When** the inspect probe runs, **Then** the missing media is represented explicitly and matches the manifest's `offline_media` entry.

---

### User Story 3 - Build a test timeline deterministically (Priority: P2)

As the operator, I run a `build` probe that creates a test timeline, imports
deterministic synthetic media (FR-012) into a bin, places a clip, and adds a marker.

**Why this priority**: Timeline mutation is the heart of the harness. If clips,
timelines, and markers cannot be created reliably from script, the workflow engine
(M3) has nothing to compile to.

**Independent Test**: Run the build probe against a scratch project; verify via the
inspect probe (and manually in the UI) that the timeline, imported clip, and marker
exist as specified.

**Acceptance Scenarios**:

1. **Given** a scratch project and the synthetic fixtures, **When** the operator runs the build probe, **Then** a named test timeline exists containing the imported clip and the marker.
2. **Given** the build probe is run a second time, **When** it executes, **Then** its re-run behavior (duplicate vs no-op vs error) is observed and recorded as an idempotency finding — never assumed.

---

### User Story 4 - Drive a render to completion with defined timeout semantics (Priority: P2)

As the operator, I run a `render` probe that enqueues a render from a preset and
waits for completion under **explicit timeout and stall semantics**, then confirms
the output file exists.

**Why this priority**: Rendering is the terminal deliverable of every workflow and
a Phase 0 exit criterion; enqueue-and-complete reliability is a known risk area.

**Independent Test**: Run the render probe against the test timeline; confirm the
job completes and the expected output file is produced with non-zero size.

**Acceptance Scenarios**:

1. **Given** a test timeline and a valid preset, **When** the operator runs the render probe, **Then** a job is enqueued, runs to completion within the overall timeout, and the output file is present with non-zero size.
2. **Given** progress remains unchanged for the configured stall interval, **When** the render probe is polling, **Then** it classifies the run as stalled, records the last-known status, attempts cancellation where supported, writes evidence, and exits non-zero (FR-006) — never hanging silently.

---

### Group B — Product architecture viability (narrowing gates)

### User Story 5 - Probe stable identifiers for idempotency (Priority: P2)

As the operator, I run an `identity` probe that enumerates the identifiers the API
exposes for clips/timelines/bins and reports whether they persist across a
save/reload.

**Why this priority**: Idempotent re-runs are load-bearing for "repeatable," but a
lack of *native* stable identifiers does not by itself sink the product if a
harness-managed identity strategy is credible (a NARROW, not NO-GO — see Decision Policy).

**Independent Test**: Run the identity probe before and after a save/reload; it
reports whether exposed identifiers are stable across the cycle.

**Acceptance Scenarios**:

1. **Given** a built timeline, **When** the identity probe runs before and after a save/reload, **Then** it reports identifier stability and, if native identifiers are unstable/absent, assesses whether harness-managed identity (metadata tags/markers) is viable.

---

### User Story 6 - Probe reversibility / rollback (Priority: P3)

As the operator, I run a `snapshot` probe that tests rollback approaches (project
export vs timeline duplication) and reports whether reliable reversibility is
achievable.

**Why this priority**: Safe rollback supports "safe by default," but its absence
narrows rather than blocks — a product that always generates a new output timeline
may not need automatic project restore (see Decision Policy).

**Independent Test**: Take a snapshot, mutate, then restore; confirm the mutation is
reverted, or record that reliable rollback is not achievable and whether
generated-timeline replacement is a viable substitute.

**Acceptance Scenarios**:

1. **Given** a snapshot is taken and the timeline is then mutated, **When** the operator restores, **Then** the mutation is reverted, OR the probe records that reliable rollback is unavailable and evaluates generated-timeline replacement as the fallback.

---

### User Story 7 - Exercise partial-failure recovery via failure injection (Priority: P2)

As the operator, I run a `partial-failure` probe that **intentionally induces**
failures mid-operation and records what state results, whether it can be inspected,
whether a rerun duplicates, and whether the operator gets a clear remediation path.

**Why this priority**: "Acceptable partial-failure recovery" is a decision gate; it
must be assessed from *induced evidence*, not anecdote. This story exists so the
gate is backed by a deliberate probe.

**Independent Test**: Run the probe's injection cases; each records the pre-failure
state, post-failure inspectability, rerun behavior, cleanup possibility, and
remediation clarity.

**Acceptance Scenarios**:

1. **Given** a bounded set of injected failures (e.g. clip insertion onto an invalid track; render with a missing preset; output directory made unwritable before render; Resolve closed during polling), **When** each is run, **Then** the probe records: what was created before failure, whether state can be inspected afterward, whether rerun duplicates, whether cleanup is possible, and the remediation path surfaced to the operator.

---

### Group C — Roadmap-shaping evidence (informational)

### User Story 8 - Classify MVP-critical operations by implementation route (Priority: P3)

As the operator, I receive an inventory of MVP-critical operations (subtitle import,
Fusion title-template insertion, silence detection, etc.) each classified into one
of four routes — **not** a false API-vs-GUI binary.

**Why this priority**: Informs how much of the roadmap depends on fragile GUI
automation vs external tooling vs harness-owned logic — strategic input, not a hard gate.

**Independent Test**: Review the inventory; each operation carries one of four
classifications backed by an evidence-strength label.

**Acceptance Scenarios**:

1. **Given** the list of MVP-critical operations, **When** the inventory is produced, **Then** each operation is classified as **Resolve API** / **External deterministic tooling** / **Named GUI fallback** / **Unsupported-or-deferred**, with a supporting evidence-strength label (FR-016). Absence from the Resolve API MUST NOT be recorded as "GUI-only" by default.

---

### User Story 9 - Produce the deterministic Go/No-Go decision package (Priority: P1)

As the operator, I read a single decision package — capability matrix, API risk
register, and a recommendation that follows the **documented Decision Policy** — and
can make the fund / narrow / stop call without re-running anything.

**Why this priority**: This is why the spike exists; it aggregates US1–US8 into a
reproducible recommendation.

**Independent Test**: A reviewer who did not run the probes reads
`spike/findings/go-no-go.md`, and by applying the Decision Policy to the recorded
gate results reaches the same GO / NARROW / NO-GO recommendation.

**Acceptance Scenarios**:

1. **Given** the probes have run, **When** the operator opens the decision package, **Then** each gate is marked met/unmet with a link to evidence and its category (hard / narrowing / informational).
2. **Given** the gate results, **When** the recommendation is written, **Then** it is derived by applying the Decision Policy table (FR-017) — GO / NARROW / NO-GO — rather than unstructured judgment, and names the specific finding(s) driving any NARROW or NO-GO.

### Edge Cases

- **Resolve not running** when a probe is invoked → fail fast with a "start Resolve" diagnosis, not a hang (FR-014).
- **No interpreter loads the native library** → recorded as a hard constraint; doctor reports it explicitly.
- **Free edition refuses external scripting** → US1 fails with the edition gate named; the in-app Console fallback is noted; a material NO-GO/NARROW input.
- **Render stalls indefinitely** → the render probe times out with last-known status and attempts cancellation (FR-006).
- **Second run of the build probe** → behavior observed and recorded (idempotency), never assumed.
- **Induced partial failure mid-mutation** → state captured and assessed (US7), not left ambiguous.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The spike MUST establish an external-process connection to a running DaVinci Resolve and report connection success/failure with an actionable diagnosis.
- **FR-002**: The spike MUST report the Resolve version and determine the **edition** and **external-scripting availability** using the strongest available evidence. Each such value MUST be recorded with a **confidence classification** (`direct` | `inferred`) and the supporting evidence (e.g. `{"edition":{"value":"Studio","confidence":"inferred","evidence":"external scripting connection succeeded"}}`). The spike MUST NOT present a filesystem/process-name heuristic as an authoritative API value.
- **FR-003**: The doctor probe MUST test the operator's default Python interpreter first, then documented fallback interpreters (a pinned Python 3.11 environment and any Resolve-provided supported runtime), recording for each: interpreter path, version, architecture, import/load result, failure type, the environment variables used, the native library path, and a reproduction command. The working interpreter MUST be recorded as a hard constraint for M1.
- **FR-004**: The spike MUST inspect the active project and timeline and emit structured JSON covering tracks, clips, markers, media pool, timeline settings, and missing media.
- **FR-005**: The spike MUST create a test timeline, import synthetic media into a bin, place a clip, and add a marker, and MUST observe and record the behavior of a repeated run (idempotency).
- **FR-006**: The render probe MUST enqueue a render from a preset and wait under explicit semantics: a configurable **overall timeout**, a **poll interval**, and a **stall threshold** (unchanged observable progress). On timeout or stall it MUST record the last-known job status, attempt cancellation where supported, write evidence before exiting, and exit non-zero. On success it MUST confirm the output file exists with non-zero size.
- **FR-007**: The spike MUST provide a **version-controlled reference fixture** (a known project manifest: named timeline, defined video/audio track counts, named clips on named tracks, a named marker at a known frame, and intentionally-offline media) and MUST compare inspect output against the expected manifest **automatically**, reporting differences.
- **FR-008**: The spike MUST enumerate the stable identifiers the API exposes and report whether they persist across a save/reload; if native identifiers are unstable/absent, it MUST assess the viability of a harness-managed identity strategy.
- **FR-009**: The spike MUST test at least one snapshot/rollback approach (project export and/or timeline duplication) and report whether reliable reversibility is achievable; if not, it MUST assess generated-timeline replacement as the fallback.
- **FR-010**: The spike MUST include a **failure-injection** probe that induces a bounded set of partial failures and records, per case: state created before failure, post-failure inspectability, rerun/duplication behavior, cleanup possibility, and the operator remediation path.
- **FR-011**: The spike MUST classify each MVP-critical operation into exactly one of four routes — **Resolve API**, **External deterministic tooling**, **Named GUI fallback**, **Unsupported-or-deferred** — each with an evidence-strength label. Absence from the Resolve API MUST NOT default to "GUI-only."
- **FR-012**: The spike MUST generate or bundle **deterministic synthetic** video and audio fixtures suitable for import, timeline placement, synchronization, inspection, and rendering (e.g. a ~10s video with burned-in frame count/timecode; a generated tone or spoken fixture; known resolution, frame rate, codec, duration, sample rate). It MUST NOT depend on capturing an actual screen recording (which introduces macOS Screen-Recording permission noise unrelated to Resolve feasibility).
- **FR-013**: The doctor probe MUST validate connection **reliability across repeated invocations**, not a single handshake: a documented sequence including repeat-without-restart, Resolve-closed fast-failure, Resolve-restart recovery, and (optionally) project switching. The connection gate is met only if the repeated sequence succeeds consistently with no hangs and consistent reported state.
- **FR-014**: Every probe MUST be independently runnable as a single command and MUST fail fast with a clear diagnosis when Resolve is not running or not reachable (demonstrated at least for the doctor and render probes).
- **FR-015**: Every raw evidence artifact MUST record **provenance**: timestamp, host OS, host architecture, Resolve version, Resolve edition (with confidence), Python path and version, probe git commit, probe name, and result.
- **FR-016**: Every recorded finding MUST carry an **evidence-strength label** drawn from: `observed-pass`, `observed-fail`, `documented-supported`, `documented-unsupported`, `not-found`, `inferred`, `untested`. "Not found during the spike" MUST NOT be represented as "proven impossible."
- **FR-017**: The go/no-go recommendation MUST be **derived by applying the Decision Policy** (below) to the recorded gate results — reproducible, not judgment-dependent — and MUST name the finding(s) driving any NARROW or NO-GO.
- **FR-018**: The spike MUST write its evidence to disk under `spike/findings/` as `capability-matrix.md`, `api-risk-register.md`, and `go-no-go.md`, plus raw JSON inspection/provenance dumps.
- **FR-019**: The spike MUST be isolated as throwaway code under a `spike/` directory and MUST NOT introduce production CLI, workflow-engine, bridge, or packaged-workflow code (those are later milestones); no production (non-`spike/`) source file may be added or modified.

### Key Entities *(include if feature involves data)*

- **Probe**: A single-purpose, independently runnable script exercising one capability and emitting labeled evidence (doctor, inspect, build, render, identity, snapshot, partial-failure, fallback-inventory).
- **Reference fixture**: A version-controlled project manifest + synthetic media the inspect probe is checked against automatically.
- **Evidence artifact**: A file under `spike/findings/` (report or raw JSON) carrying provenance (FR-015) and an evidence-strength label (FR-016).
- **Capability matrix**: A table mapping each attempted operation to a route/status with evidence labels.
- **API risk register**: Discovered risks (Python-load, edition gate, identifier stability, render reliability, reversibility, GUI-only ops) with severity and mitigation.
- **Gate**: A decision criterion categorized hard / narrowing / informational.
- **Decision package**: capability matrix + risk register + a Decision-Policy-derived GO / NARROW / NO-GO recommendation.

## Decision Policy

The recommendation is **derived**, not judged. Each gate is categorized, and the
recorded gate results map to a recommendation via the table below (FR-017).

### Gate categories

| Gate | Category |
|------|----------|
| External connection (repeatable) | **Hard gate** |
| Structured inspection (fixture-verified) | **Hard gate** |
| Timeline mutation (create/import/place/marker) | **Hard gate** |
| Render completion (enqueue → observe → finish) | **Hard gate** |
| Stable identity for idempotency | **Narrowing gate** |
| Reliable rollback / reversibility | **Narrowing gate** |
| Partial-failure recovery | **Narrowing gate** |
| Non-core operation availability (fallback inventory) | **Informational constraint** |

### Recommendation rule

| Finding | Recommendation |
|---------|----------------|
| External connection cannot be established under a supportable local configuration | **NO-GO** |
| Structured inspection is materially incomplete or inaccurate vs the fixture | **NO-GO** |
| Timeline creation or clip placement is unreliable | **NO-GO** |
| Rendering cannot be started and observed reliably | **NO-GO** |
| Stable native identifiers are unavailable, but harness-managed identity appears workable | **NARROW** |
| Reliable rollback is unavailable, but generated-timeline replacement is workable | **NARROW** |
| One or more non-core operations are GUI-only / unsupported | **NARROW or defer capability** |
| All hard gates pass and remaining risks have credible mitigations | **GO** |

Any hard-gate failure forces NO-GO. Narrowing-gate failures with a credible
mitigation force NARROW (not NO-GO). Informational constraints shape milestone
scope but do not by themselves block.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The decision package marks **every gate** met/unmet with its category and a link to a named evidence artifact.
- **SC-002**: A reviewer who did not run the probes can reproduce every probe result by running a single documented command per probe.
- **SC-003**: The two largest unknowns — installed **edition** and the **working Python interpreter** — are resolved to concrete recorded values (with confidence labels), not left open.
- **SC-004**: Each MVP-critical operation in the fallback inventory carries one of the four route classifications with an evidence-strength label (0 unclassified, 0 defaulted-to-GUI).
- **SC-005**: Every probe fails fast (no indefinite hang) when Resolve is not running, demonstrated for at least the doctor and render probes.
- **SC-006**: No production (non-`spike/`) source file is added or modified by the spike.
- **SC-007** *(repeated connectivity)*: External connection succeeds across the documented repeated-invocation sequence including a Resolve restart, OR the recommendation records the reproducible failure pattern.
- **SC-008** *(machine-checkable inspection)*: The inspect probe is evaluated against the version-controlled expected fixture, with differences reported automatically.
- **SC-009** *(failure-injection evidence)*: At least one intentionally-induced partial failure is captured, with the resulting Resolve state, rerun behavior, and recovery path documented.
- **SC-010** *(evidence provenance)*: Every raw evidence artifact records probe version, Resolve environment, Python runtime, timestamp, and result classification.
- **SC-011** *(deterministic recommendation)*: The GO / NARROW / NO-GO recommendation follows the documented Decision Policy rather than unstructured judgment.

## Assumptions

- DaVinci Resolve 20.3.2 is installed and can be launched and left running during the spike; external scripting can be enabled in Preferences by the operator.
- **Edition is determined by evidence, not assumed.** A free-edition (or scripting-disabled) finding is an expected, valued outcome that materially informs the decision.
- Synthetic media is generated/bundled by the spike (deterministic video with burned-in timecode + a generated audio fixture); no real screen recording is required, avoiding macOS Screen-Recording permission noise. Real media may be substituted later.
- The spike is throwaway: it lives under `spike/`, is not intended to become product code, and may take shortcuts a shipped harness would not — the added rigor here is in the *evidence and decision model*, not in production-grade probe code.
- **Interpreter (test fixture, not requirement):** the operator's current default is Homebrew Python 3.14.6; the *requirement* (FR-003) is default-first-then-documented-fallbacks. The concrete 3.14.6/3.11 values are fixtures for this machine, not the conceptual requirement. The working interpreter becomes a hard M1 constraint.
- All spike work stays on the single `design/technical-discovery` branch; `.specify/feature.json` resolves the active feature dir for downstream commands (spec dir name is independent of the branch).
- The eventual harness implementation language (TypeScript-with-bridge vs Python-native) is deliberately NOT decided by this spike; it is informed by the findings and settled in a later milestone.
