# Quickstart: Running the Resolve Discovery Spike

End-to-end validation guide. This proves the spike produces a reproducible GO/NARROW/
NO-GO. Implementation details live in `tasks.md`; this is the run/validation surface.

## Prerequisites

1. **DaVinci Resolve 20.3.2 running.** Launch the app and leave it open (scripts cannot
   connect otherwise).
2. **External scripting enabled.** Resolve → Preferences → System → General →
   "External scripting using" set to **Local** (not None). (If this is unavailable, the
   doctor probe will report it — a valued finding.)
3. **A working Python interpreter.** The doctor probe resolves this for you (attempts the
   default Homebrew Python 3.14.6, then a pinned 3.11, then Resolve's runtime). If none
   loads the native library, that is recorded as a hard constraint.
4. **`ffmpeg`** on PATH (for synthetic media generation).
5. **Environment variables** (macOS) — set by `spike/resolve_env.py`, shown here for reference:
   - `RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"`
   - `RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"`
   - `PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"`

## One-time fixture setup

```bash
python spike/fixtures/make_media.py       # generate deterministic synthetic video + audio
```

Expected: `spike/fixtures/media/` gains a ~10s timecode-burned video and a known-spec audio
file; specs recorded in a sidecar.

## Run the probes (each is independent, one command)

```bash
python spike/probes/doctor.py --runs 10          # US1 — MUST pass first (gates the rest)
python spike/probes/inspect.py                   # US2 — diffs live state vs fixture manifest
python spike/probes/build.py --runs 2            # US3 — build + idempotency observation
python spike/probes/render.py --timeout 300 --poll 2 --stall 60   # US4
python spike/probes/identity.py --reload         # US5
python spike/probes/snapshot.py --mode both      # US6
python spike/probes/partial_failure.py --case all # US7 — failure injection
python spike/probes/fallback_inventory.py        # US8 — four-route classification
```

Each writes a provenance-stamped `spike/findings/raw/<probe>.json` and prints a summary.
Exit codes: `0` PASS · `1` observed FAIL (still a valid finding) · `2` could-not-run.

## Produce the decision package

```bash
python spike/decision.py
```

Expected outputs under `spike/findings/`:
- `capability-matrix.md` — every attempted op → route + evidence strength
- `api-risk-register.md` — discovered risks with severity + mitigation
- `go-no-go.md` — **GO / NARROW / NO-GO**, derived by the Decision Policy, with each gate
  marked met/unmet (category + evidence link) and the drivers of any NARROW/NO-GO

## Validation (acceptance)

- [ ] **SC-002/SC-005**: `doctor` and `render` fail fast (exit 2, no hang) when Resolve is closed.
- [ ] **SC-003**: `go-no-go.md` records a concrete edition (with confidence) and the working interpreter.
- [ ] **SC-007**: the doctor multi-run sequence result is recorded (success across restart, or a reproducible failure pattern).
- [ ] **SC-008**: `inspect` reports the fixture diff automatically (0 unexplained differences on the fixture).
- [ ] **SC-009**: at least one injected partial failure is captured with state + rerun + remediation.
- [ ] **SC-010**: every `findings/raw/*.json` carries full provenance.
- [ ] **SC-011**: the recommendation in `go-no-go.md` follows the Decision Policy table (reproducible by re-derivation).
- [ ] **SC-006**: `git status` shows no changes outside `spike/` and `specs/`.

## Safety notes

- The spike operates on a **scratch/fixture project** — do not point it at real work.
- All artifacts are throwaway; `spike/` is not product code.
- Nothing outside `spike/` (notably `src/`, the Remotion product) is created or modified.
