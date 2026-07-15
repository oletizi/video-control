# Tasks: Resolve Discovery Spike (Phase 0 Feasibility)

**Feature**: `specs/001-resolve-discovery-spike` · **Branch**: `design/technical-discovery`
**Inputs**: plan.md, spec.md, research.md, data-model.md, contracts/probes.md, quickstart.md

> **Tier map configured.** `.stack-control/config.yaml` binds `fast → haiku`,
> `balanced → sonnet`, `powerful → opus`. Each task below carries a `[tier:<label>]`
> resolved by `stackctl resolve-tiers` at `/stack-control:execute` to dispatch it to a
> right-sized model. Assignment rationale: **powerful** for the hard foundational
> modules + the decision aggregator; **fast** for scaffolding + static fixtures;
> **balanced** for the probe implementations.

> **Scope guard (FR-019):** every task writes ONLY under `spike/`. No task may create or
> modify anything under `src/` (the existing Remotion product) or elsewhere. A task that
> would touch non-`spike/` code is out of scope.

**Task format**: `- [ ] TID [P?] [USn?] [tier:LABEL] Description (path)`
`[P]` = parallelizable (different file, no incomplete dep). `[USn]` = user story.

---

## Phase 1: Setup

- [x] T001 [tier:fast] Create the throwaway spike tree — `spike/`, `spike/probes/`, `spike/fixtures/`, `spike/fixtures/media/`, `spike/findings/`, `spike/findings/raw/` — with a `spike/README.md` (what the spike is, how to run it, the "scratch project only / nothing outside spike/" safety notes)
- [x] T002 [P] [tier:fast] Add `spike/fixtures/media/` to `.gitignore` (generated media is not committed) and confirm `git status` shows no non-`spike/`/`specs/` changes

## Phase 2: Foundational (blocking — all probes depend on these)

- [x] T003 [tier:powerful] Implement `spike/resolve_env.py`: set `RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` / `PYTHONPATH` (macOS), and resolve a working interpreter in FR-003 order (Homebrew 3.14.6 → pinned 3.11 → Resolve runtime), returning per-attempt `InterpreterAttempt` records (path, version, arch, load_result, failure_type, env_vars, native_lib_path, repro_command). Expose `connect() -> resolve|None` and a fail-fast diagnosis (research R1/R2)
- [x] T004 [P] [tier:powerful] Implement `spike/evidence.py`: `Provenance` stamping (FR-015 — timestamp, host os/arch, resolve version, edition `{value,confidence,evidence}`, python path/version, probe, probe_commit via `git rev-parse HEAD`, result), the `EvidenceStrength` enum (FR-016), and `Finding` / `ProbeResult` writers that emit provenance-stamped JSON to `spike/findings/raw/<probe>.json` (data-model.md)
- [x] T005 [P] [tier:balanced] Implement `spike/fixtures/make_media.py`: generate deterministic synthetic media with `ffmpeg` — a ~10s `testsrc2` video with `drawtext` burned-in frame/timecode at a known resolution/fps/codec, and a known-spec audio fixture (`sine` or TTS) — plus a sidecar recording exact specs (FR-012, research R9). NO real screen capture
- [x] T006 [P] [tier:fast] Author `spike/fixtures/expected_manifest.json`, the version-controlled reference-fixture state the inspect probe is diffed against (project/timeline/track counts/named clips/marker@frame/offline media) per data-model.md ReferenceFixtureManifest (FR-007)
- [x] T007 [P] [tier:fast] Author `spike/fixtures/mvp-operations.json`, the MVP-critical operation list for the fallback inventory (subtitle import, Fusion title-template insertion, silence detection, chapter markers, intro/outro insert, multi-format render) (FR-011)

## Phase 3: User Story 1 — doctor (Priority: P1) 🚩 MVP

**Goal**: repeatable external connection + version + edition + working interpreter.
**Independent test**: `python spike/probes/doctor.py --runs 10` emits a verdict + report, reproducible.

- [x] T008 [US1] [tier:balanced] Implement `spike/probes/doctor.py`: connect via `resolve_env`, report version (`direct`) and edition (`inferred`, with evidence — external-scripting success as Studio signal, research R3), and emit the ordered `InterpreterAttempt` list identifying the working interpreter (FR-001/FR-002/FR-003)
- [x] T009 [US1] [tier:balanced] Add the multi-run reliability sequence to `spike/probes/doctor.py` (FR-013): repeat-without-restart, Resolve-closed fast-fail, Resolve-restart recovery, optional project switch; PASS only if consistent with no hangs (SC-007)
- [x] T010 [P] [US1] [tier:balanced] Enforce the shared probe CLI contract in `spike/probes/doctor.py` (exit 0 PASS / 1 observed-FAIL / 2 cannot-run, fail-fast when Resolve unreachable) and write `spike/findings/raw/doctor.json` (contracts/probes.md, FR-014)

## Phase 4: User Story 2 — inspect (Priority: P1)

**Goal**: structured project/timeline state, machine-diffed vs the fixture.
**Independent test**: `python spike/probes/inspect_probe.py` reports 0 unexplained diffs on the fixture.

- [x] T011 [US2] [tier:balanced] Implement `spike/probes/inspect_probe.py` (renamed from `inspect.py` to avoid shadowing the stdlib `inspect` module): serialize project/timeline/tracks/clips/markers/media-pool/settings + missing media to JSON (research R4, FR-004)
- [x] T012 [US2] [tier:balanced] Add automatic diff of inspect output vs `expected_manifest.json`, reporting matches + unexplained differences (0 unexplained = PASS, SC-008); apply the probe CLI contract + `raw/inspect.json`

## Phase 5: User Story 3 — build (Priority: P2)

**Goal**: deterministic timeline construction + idempotency observation.
**Independent test**: `python spike/probes/build.py --runs 2` creates timeline+clip+marker, records re-run behavior.

- [x] T013 [US3] [tier:balanced] Implement `spike/probes/build.py`: import synthetic media, create timeline, place clip, add marker (research R5, FR-005); apply the probe CLI contract + `raw/build.json`
- [x] T014 [US3] [tier:balanced] Add the second-run idempotency observation to `spike/probes/build.py` (duplicate vs no-op vs error), recorded as a Finding regardless of outcome

## Phase 6: User Story 4 — render (Priority: P2)

**Goal**: enqueue + observe a render under explicit timeout/stall semantics.
**Independent test**: `python spike/probes/render.py --timeout 300 --poll 2 --stall 60` completes + confirms output.

- [x] T015 [US4] [tier:balanced] Implement `spike/probes/render.py`: load preset, set target dir/name, enqueue, start, poll `GetRenderJobStatus` (research R6, FR-006)
- [x] T016 [US4] [tier:balanced] Add timeout + stall handling to `spike/probes/render.py` (overall timeout, poll interval, stall threshold → record last status, attempt stop, write evidence, exit non-zero; confirm output non-zero size); apply the probe CLI contract + `raw/render.json` (FR-014)

## Phase 7: User Story 5 — identity (Priority: P2)

**Goal**: stable-identifier availability + persistence for idempotency.
**Independent test**: `python spike/probes/identity.py --reload` reports identifier stability across save/reload.

- [x] T017 [US5] [tier:balanced] Implement `spike/probes/identity.py`: probe `GetUniqueId()` across object types, test persistence across save+reload, and if absent/unstable assess harness-managed identity viability (research R7, FR-008); apply the probe CLI contract + `raw/identity.json`

## Phase 8: User Story 6 — snapshot (Priority: P3)

**Goal**: reversibility via project export vs timeline duplication.
**Independent test**: `python spike/probes/snapshot.py --mode both` reports whether restore reverts a mutation.

- [x] T018 [US6] [tier:balanced] Implement `spike/probes/snapshot.py`: take snapshot (export and/or duplicate), mutate, attempt restore, record reversibility; if unreliable, evaluate generated-timeline replacement fallback (research R8, FR-009); apply the probe CLI contract + `raw/snapshot.json`

## Phase 9: User Story 7 — partial_failure (Priority: P2)

**Goal**: induced partial-failure recovery evidence.
**Independent test**: `python spike/probes/partial_failure.py --case all` captures state/rerun/remediation per case.

- [x] T019 [US7] [tier:balanced] Implement `spike/probes/partial_failure.py`: inject the bounded cases (invalid-track insert; missing preset; unwritable out-dir; Resolve closed mid-poll), recording per case pre-failure state, post-failure inspectability, rerun/duplication, cleanup possibility, remediation path (research R10, FR-010, SC-009); apply the probe CLI contract + `raw/partial_failure.json`

## Phase 10: User Story 8 — fallback_inventory (Priority: P3)

**Goal**: four-route classification of MVP-critical operations.
**Independent test**: `python spike/probes/fallback_inventory.py` classifies every op; 0 unclassified/defaulted-to-GUI.

- [x] T020 [US8] [tier:balanced] Implement `spike/probes/fallback_inventory.py`: for each op in `mvp-operations.json`, classify into `resolve-api` / `external-tooling` / `named-gui-fallback` / `unsupported-or-deferred` with an evidence-strength label; never default API-absence to GUI-only (research R11, FR-011, SC-004); apply the probe CLI contract + `raw/fallback_inventory.json`

## Phase 11: User Story 9 — decision package (Priority: P1)

**Goal**: deterministic GO/NARROW/NO-GO derived via the Decision Policy.
**Independent test**: a reviewer re-derives the same recommendation from `go-no-go.md`.

- [x] T021 [US9] [tier:powerful] Implement `spike/decision.py`: read every `findings/raw/*.json`, map observations to categorized `Gate`s (hard/narrowing/informational), apply the Decision Policy table (FR-017), and emit a `Decision` object (recommendation + drivers + provenance)
- [x] T022 [US9] [tier:balanced] Render `spike/findings/go-no-go.md` (each gate met/unmet + category + evidence link + the derived GO/NARROW/NO-GO), `spike/findings/capability-matrix.md`, and `spike/findings/api-risk-register.md` from the decision + probe results (FR-018, SC-001/SC-011)

## Phase 12: Polish & Acceptance

> **Operator-run (`- [~]`):** T023–T025 require a **live Resolve** (running + external
> scripting enabled + Studio edition) that a coding agent cannot set up in-session. They
> are marked `- [~]` so the `tasks-complete` gate excludes them (audit-before-acceptance):
> execute governs the written code now, and the operator runs the quickstart to produce
> the actual go/no-go evidence.

- [~] T023 [tier:balanced] Run the full quickstart end-to-end against a running Resolve and record the actual outputs (all probes + `decision.py`)
- [~] T024 [P] [tier:balanced] Verify the quickstart SC acceptance checklist (SC-001..SC-011) — especially SC-005 (doctor/render fail fast, exit 2, no hang when Resolve closed), SC-006 (`git status` clean outside `spike/`+`specs/`), SC-010 (provenance on every `raw/*.json`)
- [~] T025 [P] [tier:balanced] Fill `spike/README.md` with the confirmed working interpreter + the enable-external-scripting steps discovered during T023 (hand these to M1 as constraints)

---

## Dependencies & execution order

- **Setup (T001–T002)** → **Foundational (T003–T007)** → **user stories**.
- `resolve_env.py` (T003) + `evidence.py` (T004) block **every** probe. Fixtures (T005–T007) block inspect/build/render/fallback.
- **US1 doctor is the MVP** and the runtime gate: at *run* time it must PASS before the other probes yield meaningful evidence. At *implementation* time the probe files are independent (different files) and can be built in parallel once Foundational is done.
- **US9 decision (T021–T022)** depends on all probe JSON existing; run last.
- Polish (T023–T025) depends on all probes + decision.

## Parallel opportunities

- Foundational: T004, T005, T006, T007 are `[P]` (distinct files) once T003 is underway.
- Across stories: once Foundational lands, the eight probe implementations (T008–T020) touch distinct files and can proceed in parallel, save the intra-probe ordering shown (e.g. T008 before T009/T010).

## Implementation strategy

MVP = **US1 doctor** alone: it resolves the two largest unknowns (edition, working interpreter) and the connection hard gate — a partial go/no-go on its own. Then inspect + build + render complete the hard gates; identity/snapshot/partial_failure add the narrowing gates; fallback_inventory + decision produce the package. Favor breadth of evidence over polish; spike-grade code is acceptable, the evidence/decision model is not.

**Total: 25 tasks** — Setup 2 · Foundational 5 · US1 3 · US2 2 · US3 2 · US4 2 · US5 1 · US6 1 · US7 1 · US8 1 · US9 2 · Polish 3.
Tier split: **fast** 4 (T001–T002, T006–T007) · **powerful** 3 (T003–T004, T021) · **balanced** 18 (all probes + T005 + T022–T025).
