# Probe CLI Contracts

Every probe is a single-command Python script under `spike/probes/`. Shared contract:

- **Invocation**: `python spike/probes/<name>.py [flags]` (run via the interpreter the
  doctor probe identified as working).
- **Output**: human-readable summary to stdout; a provenance-stamped `ProbeResult` JSON
  written to `spike/findings/raw/<name>.json`.
- **Exit codes**: `0` = probe ran and its gate/observation is PASS; `1` = observed FAIL
  (a real finding, still a successful run of the probe); `2` = could not run
  (Resolve not reachable / no working interpreter) — fail fast, never hang (FR-014).
- **Every probe** stamps provenance (FR-015) and labels findings with an
  EvidenceStrength (FR-016).

---

## doctor (US1) — connection, version, edition, interpreter

- **Flags**: `--runs N` (default per FR-013 sequence), `--json`.
- **Does**: resolves a working interpreter (FR-003, ordered attempts); connects; runs the
  multi-run reliability sequence (repeat-without-restart; Resolve-closed fast-fail;
  Resolve-restart recovery; optional project switch); reports version (`direct`) and
  edition (`inferred`, with evidence).
- **PASS (exit 0)**: repeated connection sequence succeeds consistently, no hangs; a
  load-capable interpreter found. **FAIL (1)**: connection refused / edition or permission
  gate. **CANNOT-RUN (2)**: no interpreter loads the native lib.

## inspect (US2) — structured state vs fixture

- **Flags**: `--fixture spike/fixtures/expected_manifest.json`, `--json`.
- **Does**: serializes the active project/timeline/tracks/clips/markers/media-pool/settings
  to JSON; diffs against the fixture manifest; reports matches + unexplained differences.
- **PASS**: 0 unexplained differences (SC-008). **FAIL**: material mismatch/incompleteness.

## build (US3) — deterministic timeline construction

- **Flags**: `--project <name>`, `--runs 2` (idempotency).
- **Does**: imports the synthetic media, creates the timeline, places a clip, adds a marker;
  re-runs to observe duplicate vs no-op vs error.
- **PASS**: timeline+clip+marker created as specified. **FAIL**: unreliable creation.
  Re-run behavior recorded as a Finding regardless.

## render (US4) — enqueue + observe with timeout/stall

- **Flags**: `--preset <name>`, `--timeout <s>`, `--poll <s>`, `--stall <s>`, `--out <dir>`.
- **Does**: loads preset, sets target dir/name, enqueues, starts, polls status; enforces
  overall timeout + stall threshold; on breach records last-known status, attempts stop,
  writes evidence, exits non-zero; on success confirms output file non-zero size (FR-006).
- **PASS**: completed within timeout, output present. **FAIL/STALL**: recorded with last status.

## identity (US5) — stable identifiers

- **Flags**: `--reload` (save + reload to test persistence).
- **Does**: probes `GetUniqueId()` across object types; reports availability + persistence
  across save/reload; if absent/unstable, assesses harness-managed identity viability.
- **PASS(narrowing)**: durable native identity OR credible harness-managed strategy.

## snapshot (US6) — reversibility

- **Flags**: `--mode export|duplicate|both`.
- **Does**: takes a snapshot, mutates, attempts restore; records whether each approach reliably
  reverts; if not, evaluates generated-timeline replacement fallback.
- **PASS(narrowing)**: reliable rollback OR viable generated-timeline replacement.

## partial_failure (US7) — failure injection

- **Flags**: `--case <name|all>`.
- **Does**: induces each bounded failure (invalid-track insert; missing preset; unwritable
  out-dir; Resolve closed mid-poll); per case records pre-failure state, post-failure
  inspectability, rerun/duplication, cleanup possibility, remediation path (FR-010).
- **PASS(narrowing)**: failures leave inspectable, recoverable state with a clear remediation path.

## fallback_inventory (US8) — four-route classification

- **Flags**: `--ops spike/fixtures/mvp-operations.json` (the MVP-critical op list).
- **Does**: for each MVP-critical operation, attempts/classifies into `resolve-api` /
  `external-tooling` / `named-gui-fallback` / `unsupported-or-deferred` with an
  evidence-strength label; never defaults absence-from-API to GUI-only (FR-011).
- **PASS(informational)**: 0 unclassified, 0 defaulted-to-GUI (SC-004).

---

## decision (US9) — NOT a probe; the aggregator

- **Invocation**: `python spike/decision.py`.
- **Does**: reads every `findings/raw/*.json`, maps observations to gates (with categories),
  applies the Decision Policy table (FR-017), and writes `findings/go-no-go.md` +
  `findings/capability-matrix.md` + `findings/api-risk-register.md`.
- **Output**: a `Decision` object → GO / NARROW / NO-GO with drivers and provenance (SC-011).
