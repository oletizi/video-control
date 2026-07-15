# Resolve Discovery Spike (Phase 0 Feasibility)

This is a THROWAWAY, Python-only feasibility spike that drives a running DaVinci Resolve 20.3.2 through the native DaVinciResolveScript API to answer, with reproducible evidence, whether Resolve can be driven reliably from an external process — BEFORE any production harness code (roadmap milestones M1-M6) is built. It is not product code.

## How to run

See `specs/001-resolve-discovery-spike/quickstart.md` for the authoritative run guide.

**Prerequisites:**
- DaVinci Resolve 20.3.2 running
- External scripting enabled in Preferences > System > General
- ffmpeg on PATH

**Run sequence:**
1. Execute the probes under `spike/probes/`
2. Run `spike/decision.py`

## Safety

- Operate only on a scratch/fixture project, never real work
- All artifacts are throwaway
- Nothing outside `spike/` is created or modified (the existing `src/` Remotion product is off-limits)

## Layout

- `resolve_env.py` — Environment and interpreter resolution
- `evidence.py` — Provenance and evidence-strength labels
- `decision.py` — Decision Policy → GO/NARROW/NO-GO
- `probes/` — The 8 probes
- `fixtures/` — Synthetic media and reference manifest
- `findings/` — Evidence outputs

## Notes

Working interpreter and enable-external-scripting steps will be filled in after the first live run (task T025).
