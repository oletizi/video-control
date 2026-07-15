# Phase 0 Research: Resolve Discovery Spike

This resolves the technical unknowns the probes depend on. Each entry is a
planning-time decision; the spike EMPIRICALLY confirms or refutes it and records the
result with an evidence-strength label. Where the API behavior is genuinely unknown
until run, the "decision" is *how the probe will investigate*, not an asserted answer.

## R1 — External connection bootstrap

- **Decision**: Connect via the native module: set `RESOLVE_SCRIPT_API`,
  `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH` (macOS values from the vendor README), then
  `import DaVinciResolveScript as dvr; resolve = dvr.scriptapp("Resolve")`. A `None`
  return means "not reachable" → fail fast with a diagnosis.
- **Rationale**: This is the documented, lowest-risk path and matches the installed
  API package. Isolating env setup in `spike/resolve_env.py` lets every probe reuse it.
- **Alternatives considered**: In-app Console/Scripts-menu execution (rejected as
  primary — does not test external automation; retained as documented fallback if the
  external connection is refused).

## R2 — Python interpreter / native-library load (the first empirical risk)

- **Decision**: `resolve_env.py` attempts the operator default (Homebrew Python
  3.14.6) first, then documented fallbacks — a pinned Python 3.11 (`uv`/pyenv) and any
  Resolve-provided runtime — recording per attempt: path, version, architecture,
  import/load result, failure type, env vars, native-lib path, reproduction command.
- **Rationale**: `fusionscript.so` is a version-sensitive C-extension; ≥3.6 is only a
  floor. 3.14 may not load. Targeting 3.11-compatible syntax keeps the fallback usable.
- **Alternatives considered**: Assume 3.14 works (rejected — unverified); hard-require
  3.11 up front (rejected — the requirement is discovery-order, not a machine-specific pin).

## R3 — Version and edition determination

- **Decision**: Version is `direct` via `resolve.GetVersionString()`. Edition is
  `inferred`: a successful **external** scripting connection is itself strong Studio
  evidence (the free edition disables the external/remote scripting API), corroborated
  where possible by a Studio-only API probe. Record `{value, confidence, evidence}`.
- **Rationale**: There is no authoritative "is-Studio" API value; FR-002 forbids
  presenting filesystem/process heuristics as authoritative, so edition must be labeled
  `inferred`.
- **Alternatives considered**: Parse app bundle / license files (rejected — brittle,
  and would be mislabeled as authoritative).

## R4 — Structured inspection surface

- **Decision**: Walk `GetProjectManager()` → `GetCurrentProject()` →
  `GetCurrentTimeline()`; enumerate tracks via `GetTrackCount(type)` +
  `GetItemListInTrack(type, i)`; markers via `GetMarkers()`; media pool via
  `GetMediaPool()` / `GetRootFolder()` / `GetClipList()`; timeline settings via
  `GetSetting()`. Serialize to JSON and diff against `expected_manifest.json`.
- **Rationale**: These are the stable, documented accessors; a fixture diff makes US2
  machine-checkable (FR-007) rather than "eyeball the UI."
- **Alternatives considered**: UI-only verification (rejected — not reproducible).

## R5 — Timeline build

- **Decision**: `MediaPool.ImportMedia([paths])` → `MediaPool.CreateEmptyTimeline(name)`
  (or `CreateTimelineFromClips`) → `AppendToTimeline([clip])` → `timeline.AddMarker(...)`.
  Run twice to observe idempotency (duplicate vs no-op vs error).
- **Rationale**: Documented media-pool/timeline mutation surface; the second run is the
  only honest way to learn idempotency (FR-005).
- **Alternatives considered**: n/a (this is the core mutation path under test).

## R6 — Render enqueue + observation

- **Decision**: `project.GetRenderPresetList()` / `LoadRenderPreset()` →
  `SetRenderSettings({TargetDir, CustomName})` → `AddRenderJob()` → `StartRendering(jobId)`;
  poll `GetRenderJobStatus(jobId)` (`JobStatus`, `CompletionPercentage`) on the configured
  interval; enforce overall timeout + stall threshold; on breach record last-known status,
  attempt `StopRendering()`, write evidence, exit non-zero. Confirm output file non-zero size.
- **Rationale**: Directly implements FR-006's timeout/stall semantics against the
  documented render API.
- **Alternatives considered**: Fire-and-forget enqueue (rejected — "reliable render" needs
  observed completion).

## R7 — Stable identifiers

- **Decision**: Probe `GetUniqueId()` where exposed (Timeline, TimelineItem,
  MediaPoolItem, Folder); record availability and whether values persist across a
  save + reload. If unstable/absent, assess harness-managed identity (marker/metadata tags).
- **Rationale**: Idempotent re-runs need a durable key; native availability is version-
  dependent, so it must be probed, and a fallback strategy assessed (narrowing gate).
- **Alternatives considered**: Assume `GetUniqueId` exists everywhere (rejected — uneven
  across object types/versions).

## R8 — Reversibility / snapshot

- **Decision**: Probe two approaches: project-level export
  (`ProjectManager.ExportProject(name, path)`) and timeline duplication
  (`timeline.DuplicateTimeline(name)`); mutate, then attempt restore; record whether each
  reliably reverts. If neither, evaluate generated-timeline replacement as the fallback.
- **Rationale**: Rollback support is a narrowing gate; the product may not need automatic
  restore if it always generates a new output timeline.
- **Alternatives considered**: Assume project export round-trips (rejected — unverified).

## R9 — Deterministic synthetic media (no real screen capture)

- **Decision**: Generate fixtures with `ffmpeg`: a ~10s video from `testsrc2` with
  `drawtext` burning in frame/timecode at a known resolution/fps/codec, and an audio
  fixture from `sine` (or a TTS-generated clip) at a known sample rate. Emit a sidecar
  describing exact specs; regenerate deterministically.
- **Rationale**: FR-012 — real screen capture trips macOS Screen-Recording (TCC) permission,
  noise unrelated to Resolve feasibility. Synthetic fixtures give stronger, reproducible evidence.
- **Alternatives considered**: `screencapture`/AVFoundation capture (rejected — permission
  noise, non-deterministic).

## R10 — Partial-failure injection

- **Decision**: The `partial_failure` probe deliberately induces a bounded set: clip
  insertion onto an invalid track; render with a missing preset; output dir made unwritable
  pre-render; Resolve closed during polling. Per case, record pre-failure state, post-failure
  inspectability, rerun/duplication behavior, cleanup possibility, remediation path.
- **Rationale**: FR-010 — the recovery gate must be assessed from induced evidence, not anecdote.
- **Alternatives considered**: Observe incidental failures only (rejected — not systematic).

## R11 — Evidence + decision model

- **Decision**: `evidence.py` stamps every artifact with provenance (FR-015) and attaches an
  evidence-strength label (FR-016); `decision.py` reads the recorded gate results and applies
  the spec's Decision Policy table (FR-017) to emit GO/NARROW/NO-GO. No manual judgment in the
  final step.
- **Rationale**: Makes the recommendation reproducible (SC-011) and the findings interpretable
  later (SC-010).
- **Alternatives considered**: Prose-only findings (rejected — not reproducible, invites
  "not-found" → "impossible" drift).

**All NEEDS CLARIFICATION resolved** — the remaining true-unknowns (does 3.14 load; is it
Studio; are identifiers stable; does rollback round-trip) are the spike's *outputs*, resolved
empirically by the probes above, not planning blockers.
