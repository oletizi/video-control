# Phase 1 Data Model: Resolve Discovery Spike

The spike's "data" is its **evidence**. These are the shapes every probe emits and
the decision step consumes. All are JSON-serializable; markdown reports are rendered
from them.

## EvidenceStrength (enum)

One of: `observed-pass` · `observed-fail` · `documented-supported` ·
`documented-unsupported` · `not-found` · `inferred` · `untested`.

Rule: `not-found` MUST NOT be rendered as "proven impossible" (FR-016).

## Confidence (enum)

One of: `direct` · `inferred`. Used for values the API does not authoritatively expose
(edition, scripting availability) — FR-002.

## Provenance (embedded in every artifact) — FR-015

| Field | Type | Notes |
|-------|------|-------|
| `timestamp` | string (ISO-8601, local offset) | when the probe ran |
| `host_os` | string | e.g. `macOS` |
| `host_arch` | string | e.g. `arm64` |
| `resolve_version` | string | from `GetVersionString()` (`direct`) |
| `resolve_edition` | `{value, confidence, evidence}` | edition inference (FR-002) |
| `python_path` | string | interpreter that loaded the API |
| `python_version` | string | e.g. `3.11.9` |
| `probe` | string | probe name (`doctor`, `inspect`, …) |
| `probe_commit` | string | git SHA of the spike at run time |
| `result` | `pass` \| `fail` \| `partial` \| `skipped` | probe-level outcome |

## Finding

A single recorded observation.

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | stable within a probe (e.g. `doctor.connect`, `render.timeout`) |
| `statement` | string | what was observed |
| `strength` | EvidenceStrength | FR-016 |
| `evidence` | string | supporting detail / command output pointer |
| `raw_ref` | string \| null | path to a raw JSON dump under `findings/raw/` |

## ProbeResult

What each probe writes (one JSON file under `findings/raw/<probe>.json`).

| Field | Type |
|-------|------|
| `provenance` | Provenance |
| `findings` | Finding[] |
| `result` | `pass` \| `fail` \| `partial` \| `skipped` |

## InterpreterAttempt (doctor) — FR-003

`{ path, version, arch, load_result: pass|fail, failure_type, env_vars, native_lib_path, repro_command }`.
The doctor result carries an ordered list; the first `load_result: pass` is the working interpreter.

## ReferenceFixtureManifest (FR-007)

The version-controlled expected state the inspect probe is diffed against.

```json
{
  "project": "Resolve Spike Fixture",
  "timeline": "Spike Timeline",
  "tracks": { "video": 2, "audio": 2 },
  "clips": [
    { "name": "fixture-video.mov", "track": "V1" },
    { "name": "fixture-tone.wav",  "track": "A1" }
  ],
  "markers": [ { "frame": 48, "name": "Spike Marker" } ],
  "offline_media": [ "intentionally-missing.mov" ]
}
```

The inspect probe emits the live equivalent; `inspect` reports matches and unexplained
differences automatically (0 unexplained = pass, SC-008).

## CapabilityMatrixRow

| Field | Type | Notes |
|-------|------|-------|
| `operation` | string | e.g. `create timeline`, `subtitle import` |
| `route` | `resolve-api` \| `external-tooling` \| `named-gui-fallback` \| `unsupported-or-deferred` | four routes (FR-011) |
| `strength` | EvidenceStrength | |
| `notes` | string | |

## Gate

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | e.g. `external-connection` |
| `category` | `hard` \| `narrowing` \| `informational` | from the Decision Policy |
| `met` | boolean | |
| `evidence_ref` | string | link to the backing artifact |

## Decision (output of `decision.py`) — FR-017

| Field | Type | Notes |
|-------|------|-------|
| `gates` | Gate[] | every gate, categorized + met/unmet |
| `recommendation` | `GO` \| `NARROW` \| `NO-GO` | derived by the Decision Policy table |
| `drivers` | string[] | the finding(s) forcing any NARROW/NO-GO |
| `provenance` | Provenance | environment stamp |

Derivation rule (mechanical): any `hard` gate unmet → `NO-GO`; else any `narrowing`
gate unmet (with a credible mitigation recorded) → `NARROW`; else → `GO`.
