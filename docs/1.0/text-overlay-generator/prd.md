# Product Requirements Document: TextOverlay Video Generator

**Project:** ol_dsp Demo Video Text Overlay System  
**Version:** 1.0 MVP  
**Date:** January 29, 2026  
**Author:** Orion (Product Owner)

---

## Executive Summary

This document defines the MVP requirements for a text overlay video generation system. The tool will allow content creators to define timed text overlays in a simple markup format and render them to video files with alpha transparency for compositing in professional non-linear editors (DaVinci Resolve, Final Cut Pro).

The primary goal is to dramatically reduce the time spent adding text overlays to demo videos by separating content definition (text, timing) from visual design (templates) and rendering (video export).

---

## Problem Statement

Creating text overlays for demo videos is currently time-consuming due to:

1. Non-linear editors have rudimentary text editing capabilities
2. Text styling must be applied manually to each element
3. Timing adjustments require direct manipulation in the timeline
4. No separation between content and presentation
5. Iterating on text content requires re-doing timeline work

---

## Goals

| Goal | Success Metric |
|------|----------------|
| Reduce text overlay creation time | 75% reduction in time from content draft to rendered overlay |
| Enable rapid iteration | Text changes require only file edit + re-render (no timeline work) |
| Maintain professional quality | Output indistinguishable from native NLE text tools |
| Support standard NLE workflows | ProRes 4444 export compatible with Resolve and FCP |

---

## Non-Goals (MVP)

The following are explicitly out of scope for the MVP:

- Real-time preview in a custom UI
- Integration with specific NLE plugins
- Audio-reactive text animations
- Automatic transcription or caption generation
- Cloud rendering or collaboration features
- Complex motion graphics beyond basic transitions

---

## User Stories

**US-1:** As a content creator, I want to define text overlays in a simple text file so that I can use my preferred text editor and version control.

**US-2:** As a content creator, I want to specify timing using timecodes so that overlays sync precisely with my video content.

**US-3:** As a content creator, I want to choose from pre-built animation templates so that I don't need motion design skills.

**US-4:** As a content creator, I want to render overlays with transparency so that I can composite them in my existing NLE workflow.

**US-5:** As a content creator, I want to re-render after text changes without reconfiguring styling so that iteration is fast.

---

## Functional Requirements

### FR-1: Markup Format

The system shall accept a YAML configuration file defining text overlays with the following properties:

```yaml
# Example markup format
project:
  name: "ol_dsp Compressor Demo"
  resolution: [1920, 1080]
  framerate: 30
  duration: "2:30"  # or frame count

overlays:
  - type: lower-third
    text: "Threshold Control"
    subtitle: "Sets the level where compression begins"
    in: "0:05.500"      # timecode or frame number
    out: "0:12.000"
    position: bottom-left
    
  - type: title
    text: "Attack & Release"
    in: "0:45.000"
    out: "0:48.500"
    transition:
      in: fade
      out: fade
      duration: 0.3
      
  - type: callout
    text: "−10 dB"
    in: "1:02.000"
    out: "1:08.000"
    position: [850, 320]  # pixel coordinates
    arrow: true
    arrow_target: [720, 280]
```

**Required fields per overlay:** `type`, `text`, `in`, `out`

**Supported timecode formats:** `MM:SS.mmm`, `SS.mmm`, or integer frame numbers

### FR-2: Template System

The system shall include the following built-in templates:

| Template | Description | Customizable Properties |
|----------|-------------|------------------------|
| `title` | Centered title text | font size, color, background |
| `lower-third` | Name/title bar at bottom | text, subtitle, alignment |
| `callout` | Positioned label with optional arrow | position, arrow, arrow_target |
| `code` | Monospace text block | syntax highlighting theme |
| `parameter` | Key-value display | label, value, unit |

Each template shall support:
- Custom font override
- Color scheme override
- Position override (where applicable)
- Transition override (in/out animation)

### FR-3: Animation/Transitions

The system shall support the following transition types:

| Transition | Description |
|------------|-------------|
| `cut` | Instant on/off (default) |
| `fade` | Opacity fade |
| `slide-up` | Slide in from below |
| `slide-down` | Slide in from above |
| `slide-left` | Slide in from right |
| `slide-right` | Slide in from left |
| `typewriter` | Characters appear sequentially |

Transition duration shall be configurable per-overlay or globally.

### FR-4: Rendering

The system shall render to the following formats:

| Format | Codec | Use Case |
|--------|-------|----------|
| ProRes 4444 (.mov) | Apple ProRes 4444 | Primary output for NLE compositing |
| PNG Sequence | PNG with alpha | Fallback for maximum compatibility |
| WebM | VP9 with alpha | Web preview / documentation |

**Output requirements:**
- Alpha channel preserved in all formats
- Frame-accurate timing (no drift over duration)
- Resolution matching source specification
- Framerate matching source specification

### FR-5: CLI Interface

The system shall provide a command-line interface:

```bash
# Basic render
textoverlay render project.yaml -o output.mov

# Specify format
textoverlay render project.yaml -o output/ --format png-sequence

# Preview specific time range
textoverlay render project.yaml -o preview.mov --range 0:45-1:00

# Validate markup without rendering
textoverlay validate project.yaml

# List available templates
textoverlay templates

# Generate sample project file
textoverlay init > my-project.yaml
```

---

## Technical Requirements

### TR-1: Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Runtime | Node.js 18+ | Developer familiarity, React ecosystem |
| Framework | Remotion | Purpose-built for programmatic video, React-based |
| Styling | Tailwind CSS | Rapid styling, consistent design tokens |
| Animation | Framer Motion | Declarative animations, React integration |
| CLI | Commander.js or oclif | Standard Node CLI tooling |
| Parsing | js-yaml | YAML parsing |

### TR-2: Project Structure

```
text-overlay-generator/
├── src/
│   ├── cli/              # CLI entry points and commands
│   ├── parser/           # YAML parsing and validation
│   ├── templates/        # Remotion template components
│   │   ├── Title.tsx
│   │   ├── LowerThird.tsx
│   │   ├── Callout.tsx
│   │   ├── Code.tsx
│   │   └── Parameter.tsx
│   ├── transitions/      # Animation definitions
│   ├── composition/      # Main Remotion composition
│   └── utils/            # Timecode parsing, etc.
├── templates/            # User-customizable template overrides
├── package.json
└── remotion.config.ts
```

### TR-3: Performance Requirements

| Metric | Target |
|--------|--------|
| Render speed | ≥ 2x realtime on M1 Mac (1 min video in ≤ 30 sec) |
| Memory usage | ≤ 2GB for 1080p 5-minute render |
| Startup time | ≤ 2 seconds to begin rendering |

### TR-4: Error Handling

The system shall provide clear error messages for:
- Invalid YAML syntax (with line numbers)
- Unknown template types
- Invalid timecode formats
- Overlapping overlay IDs
- Missing required fields
- Out-of-bounds positions
- Unsupported output formats

---

## Future Considerations (Post-MVP)

The following features are anticipated for future versions and should be considered in architectural decisions:

1. **Lottie/Rive integration** — Import animation templates from motion design tools
2. **Watch mode** — Auto-re-render on file changes
3. **GUI preview** — Browser-based preview without full render
4. **Theme system** — Shareable style configurations
5. **Template marketplace** — Community-contributed templates
6. **Project references** — Import/extend other project files
7. **Batch rendering** — Render multiple projects in sequence

---

## Acceptance Criteria

The MVP is complete when:

1. A user can create a YAML file defining text overlays with timing
2. All five core templates render correctly with default styling
3. All seven transition types animate correctly
4. ProRes 4444 output imports cleanly into DaVinci Resolve with working alpha
5. PNG sequence output imports cleanly into Final Cut Pro with working alpha
6. CLI provides all specified commands with appropriate help text
7. Errors produce actionable messages with file/line references
8. Documentation covers markup format, templates, and CLI usage
9. At least one complete demo video (ol_dsp tool demo) is produced using the system

---

## Open Questions

1. **Font licensing:** Should we bundle open-source fonts or rely on system fonts? Recommendation: Bundle Inter and JetBrains Mono for consistency.

2. **Template customization depth:** How much styling should be exposed in YAML vs. requiring template code changes? Recommendation: Start minimal, expand based on usage.

3. **Render farm support:** Is distributed rendering needed for longer videos? Recommendation: Defer to post-MVP; Remotion supports Lambda rendering if needed.

---

## Appendix A: Example Complete Project File

```yaml
project:
  name: "ol_dsp Compressor Demo"
  resolution: [1920, 1080]
  framerate: 30
  duration: "2:30"

defaults:
  font: "Inter"
  transition:
    type: fade
    duration: 0.25

theme:
  primary: "#3B82F6"
  secondary: "#1E293B"
  text: "#F8FAFC"
  accent: "#F59E0B"

overlays:
  - id: intro-title
    type: title
    text: "Understanding Compression"
    in: "0:01.000"
    out: "0:04.500"

  - id: presenter
    type: lower-third
    text: "Orion"
    subtitle: "ol_dsp Project"
    in: "0:05.000"
    out: "0:10.000"
    position: bottom-left

  - id: threshold-label
    type: callout
    text: "Threshold: −18 dB"
    in: "0:32.000"
    out: "0:38.000"
    position: [1200, 400]
    arrow: true
    arrow_target: [980, 350]

  - id: code-example
    type: code
    text: |
      compressor.set_threshold(-18.0);
      compressor.set_ratio(4.0);
      compressor.set_attack(10.0);
    in: "1:45.000"
    out: "1:55.000"
    position: top-right
    syntax: rust

  - id: param-display
    type: parameter
    label: "Gain Reduction"
    value: "−6.2"
    unit: "dB"
    in: "2:00.000"
    out: "2:15.000"
    position: [100, 100]
```

---

## Appendix B: Template Mockups

*To be added: Visual mockups of each template type showing default styling and key variants.*

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-29 | Orion | Initial MVP specification |
