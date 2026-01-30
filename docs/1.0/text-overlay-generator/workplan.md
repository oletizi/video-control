# Text Overlay Generator - Workplan

**GitHub Milestone:** [Week of Jan 27-31](https://github.com/oletizi/video-control/milestone/1)
**GitHub Issues:**

- [Parent: Text Overlay Generator (#1)](https://github.com/oletizi/video-control/issues/1)
- [Phase 1: Project Setup (#2)](https://github.com/oletizi/video-control/issues/2)
- [Phase 2: Templates (#3)](https://github.com/oletizi/video-control/issues/3)
- [Phase 3: Animation (#4)](https://github.com/oletizi/video-control/issues/4)
- [Phase 4: Rendering (#5)](https://github.com/oletizi/video-control/issues/5)
- [Phase 5: CLI (#6)](https://github.com/oletizi/video-control/issues/6)
- [Phase 6: Documentation (#7)](https://github.com/oletizi/video-control/issues/7)

---

## Phase 1: Project Setup & Core Infrastructure

### Tasks

1. Initialize Remotion project with TypeScript
2. Set up project structure per TR-2
3. Configure Tailwind CSS and Framer Motion
4. Implement CLI skeleton with Commander.js
5. Create YAML parser with validation

### Success Criteria

- [ ] `npm run dev` launches Remotion studio
- [ ] CLI responds to `--help` and `--version`
- [ ] YAML parser validates example project file

---

## Phase 2: Template Implementation

### Tasks

1. Implement `Title` template component
2. Implement `LowerThird` template component
3. Implement `Callout` template component (with arrow support)
4. Implement `Code` template component (with syntax highlighting)
5. Implement `Parameter` template component

### Success Criteria

- [ ] All five templates render with default styling
- [ ] Templates accept customization props (font, color, position)
- [ ] Templates handle missing optional fields gracefully

---

## Phase 3: Animation System

### Tasks

1. Implement `cut` transition (instant)
2. Implement `fade` transition
3. Implement `slide-up`, `slide-down`, `slide-left`, `slide-right` transitions
4. Implement `typewriter` transition
5. Create transition configuration system

### Success Criteria

- [ ] All seven transition types animate correctly
- [ ] Transitions respect duration configuration
- [ ] In/out transitions work independently

---

## Phase 4: Rendering Pipeline

### Tasks

1. Implement main Remotion composition
2. Configure ProRes 4444 output
3. Configure PNG sequence output
4. Configure WebM output
5. Implement time range rendering

### Success Criteria

- [ ] ProRes 4444 output has working alpha channel
- [ ] PNG sequence output imports into FCP with alpha
- [ ] Time range flag renders only specified segment

---

## Phase 5: CLI Completion

### Tasks

1. Implement `render` command with format options
2. Implement `validate` command
3. Implement `templates` command
4. Implement `init` command
5. Add comprehensive error messages

### Success Criteria

- [ ] All CLI commands work per FR-5
- [ ] Error messages include file/line references
- [ ] Help text documents all options

---

## Phase 6: Documentation & Demo

### Tasks

1. Write markup format documentation
2. Write template usage guide
3. Write CLI reference
4. Create ol_dsp demo project
5. Render demo video

### Success Criteria

- [ ] Documentation covers all markup features
- [ ] Demo video renders successfully
- [ ] Demo imports cleanly into DaVinci Resolve

---

## Dependencies

- Remotion 4.x
- Node.js 18+
- ffmpeg (for ProRes encoding)

## Risks

| Risk | Mitigation |
|------|------------|
| ProRes encoding complexity | Test early with ffmpeg; fallback to PNG sequence |
| Remotion learning curve | Start with simple templates; iterate |
| Font consistency across systems | Bundle Inter and JetBrains Mono fonts |
