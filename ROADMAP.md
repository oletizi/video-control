---
doc-grammar: roadmap
---

# Roadmap

The governed dependency graph of this project's features. Each item is a
heading-keyed unit identified by its `<phase>:<kind>/<slug>` id.

Mutate the graph with `stackctl roadmap` verbs (run `stackctl roadmap --help`
for the full surface): `add` a new item, `advance` its status, `decompose`,
`reclassify`, `defer`, and `cluster` / `group` to gather existing items under a
created-or-reused parent. Example — cluster items under a new epic with a
dependency chain:

    stackctl roadmap cluster multi:feature/epic --children design:feature/a,impl:feature/b --chain --apply

For an edit that has no verb yet (e.g. moving a `part-of` / `depends-on` edge):
edit this file directly, then run `stackctl roadmap order` to revalidate the
graph (it fails loud on a cycle / dangling ref / duplicate id).

## multi:feature/resolve-automation-harness
- status: planned
- ref: docs/product-brief-resolve-harness.md
A build system for repeatable video production in DaVinci Resolve: agent-driven, repository-based automation harness (CLI + declarative YAML workflows + structured inspection/validation + reusable templates). Opinionated over exhaustive; local, no persistent service. First cycle: macOS-first, already-running Resolve instance, human review before final render.

## design:feature/technical-discovery
- status: in-flight
- design-approved: yes
- design: docs/superpowers/specs/2026-07-14-technical-discovery-design.md
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Phase 0 go/no-go feasibility: map Resolve scripting API coverage (projects/media/timelines/clips/markers/subtitles/Fusion/render), free vs Studio, stable-identifier & snapshot/rollback strategy, GUI-fallback surface. Deliverables: capability matrix, architecture proposal, API risk register, prototype doctor/inspect/render-queue. Exit: reliable connection, structured inspection, test timeline created, test render enqueued+completed, documented limits.

## impl:feature/resolve-connectivity
- status: planned
- depends-on: design:feature/technical-discovery
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Milestone 1: CLI foundation. init + doctor diagnostics, Resolve version/edition detection, running-instance detection, project discovery, structured (JSON) project & timeline inspection, actionable connection remediation, stable exit codes.

## impl:feature/deterministic-timeline-build
- status: planned
- depends-on: impl:feature/resolve-connectivity
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Milestone 2: deterministic timeline construction. Media import, bin management, timeline creation, clip append/trim, markers, and a project-local state manifest enabling idempotent re-runs (tag generated entities; compare desired vs current).

## impl:feature/workflow-execution-engine
- status: planned
- depends-on: impl:feature/deterministic-timeline-build
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Milestone 3: workflow engine. YAML workflow schema + plan/apply/dry-run, dependency-ordered execution, execution journals, postcondition checks, snapshots, safe re-run without uncontrolled duplication (replace/merge/rebuild modes).

## impl:feature/review-render-pipeline
- status: planned
- depends-on: impl:feature/workflow-execution-engine
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Milestone 4: render pipeline. Render preset selection, render-queue control, status inspection, review + final outputs, output/path validation, preflight gating that blocks final render on failed checks unless explicitly overridden.

## impl:feature/screen-walkthrough-mvp
- status: planned
- depends-on: impl:feature/review-render-pipeline
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Milestone 5 / MVP: first packaged workflow, screen-recording product walkthrough with voiceover. Sync screen+narration, configurable pause reduction, captions when transcript present, chapter markers, intro/outro, review + final render, execution report. Human review required before final render. Tests the full thesis end to end.

## impl:feature/developer-preview
- status: planned
- depends-on: impl:feature/screen-walkthrough-mvp
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Milestone 6: Developer Preview packaging. Installer, example projects, compatibility/capability matrix docs, feedback instrumentation, issue templates, extension documentation.

## multi:feature/workflow-productization
- status: planned
- depends-on: impl:feature/developer-preview
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Phase 2: from toolkit to repeatable end-user workflows. Schema validation, reusable workflow packages, template/preset registry, parameterized titles, caption workflow, audio/missing-media checks, preflight, revision-safe regeneration. Exit: 3+ workflows configurable without code changes.

## multi:feature/intelligent-editing-assist
- status: planned
- depends-on: multi:feature/workflow-productization
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Phase 3: AI-assisted editorial as recommendations, not silent edits. Transcript-to-timeline mapping, silence/filler removal, retake detection, chapter/highlight suggestion, speaker segmentation. Suggestions must be evidence-traceable, acceptable/rejectable, deterministic on apply, and explainable.

## multi:feature/team-pipeline-capabilities
- status: planned
- depends-on: multi:feature/workflow-productization
- part-of: multi:feature/resolve-automation-harness
- ref: docs/product-brief-resolve-harness.md
Phase 4: shared production standards & content operations. Shared workflow registry, org presets, template versioning, CI validation, batch execution, render nodes, approval metadata, publishing/asset integrations, project locking/concurrency.