# Text Overlay Generator

Generate professional text overlay videos from YAML definitions. Export as ProRes 4444 with alpha channel for compositing in DaVinci Resolve, Final Cut Pro, and other NLEs.

## Features

- **5 overlay templates**: Title, Lower-Third, Callout, Code, Parameter
- **7 transition types**: cut, fade, slide-up/down/left/right, typewriter
- **YAML-based workflow**: Define overlays in human-readable format
- **ProRes 4444 output**: Full alpha channel support for compositing
- **CLI tools**: render, validate, templates, init commands

## Quick Start

```bash
# Install dependencies
npm install

# Start Remotion Studio for preview
npm run dev

# Generate sample project file
npm run cli -- init -o my-project.yaml

# Validate a project file
npm run cli -- validate my-project.yaml

# Render to ProRes 4444
npm run cli -- render my-project.yaml -o output.mov
```

## Project File Format

```yaml
project:
  name: "My Video Overlays"
  resolution: [1920, 1080]
  framerate: 30
  duration: "1:00"

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
  - type: title
    text: "Welcome"
    in: "0:01.000"
    out: "0:05.000"

  - type: lower-third
    text: "Speaker Name"
    subtitle: "Title"
    in: "0:06.000"
    out: "0:12.000"
    position: bottom-left
```

## CLI Commands

### `textoverlay render <project>`
Render a YAML project to video.

```bash
npm run cli -- render project.yaml -o output.mov
npm run cli -- render project.yaml -o frames/ --format png-sequence
npm run cli -- render project.yaml --range 0:45-1:00
```

Options:
- `-o, --output <path>`: Output file path (default: output.mov)
- `--format <format>`: prores, png-sequence, or webm (default: prores)
- `--range <range>`: Time range to render (e.g., 0:45-1:00)
- `--concurrency <n>`: Parallel render threads (default: 4)

### `textoverlay validate <project>`
Validate a YAML project without rendering.

```bash
npm run cli -- validate project.yaml
```

### `textoverlay templates`
List available overlay templates and their properties.

```bash
npm run cli -- templates
```

### `textoverlay init`
Generate a sample project file.

```bash
npm run cli -- init > my-project.yaml
npm run cli -- init -o my-project.yaml
```

## Overlay Templates

### Title
Centered title text with optional subtitle.

```yaml
- type: title
  text: "Main Title"
  subtitle: "Optional subtitle"
  fontSize: 120
  transition:
    in: fade
    out: fade
    duration: 0.5
```

### Lower-Third
Name/title bar at bottom of screen.

```yaml
- type: lower-third
  text: "Speaker Name"
  subtitle: "Role or Title"
  position: bottom-left  # or bottom-right
```

### Callout
Positioned label with optional arrow pointing to a target.

```yaml
- type: callout
  text: "Look here!"
  position: [800, 300]
  arrow: true
  arrow_target: [600, 400]
```

### Code
Syntax-highlighted code block using Shiki.

```yaml
- type: code
  text: |
    function example() {
      return "hello";
    }
  syntax: typescript
  theme: github-dark
  position: center
```

### Parameter
Key-value display for measurements or settings.

```yaml
- type: parameter
  label: "Threshold"
  value: "-18"
  unit: "dB"
  position: [100, 100]
```

## Transitions

All overlays support entry and exit transitions:

| Transition | Description |
|------------|-------------|
| `cut` | Instant on/off (default) |
| `fade` | Opacity fade |
| `slide-up` | Slide in from below |
| `slide-down` | Slide in from above |
| `slide-left` | Slide in from right |
| `slide-right` | Slide in from left |
| `typewriter` | Characters appear sequentially |

```yaml
transition:
  in: slide-up
  out: fade
  duration: 0.3
```

## Timecode Formats

Overlays use timecodes to specify timing:

- `"MM:SS.mmm"` - Minutes, seconds, milliseconds (e.g., "1:30.500")
- `"SS.mmm"` - Seconds and milliseconds (e.g., "45.250")
- `123` - Frame number

## Development

```bash
# Start Remotion Studio
npm run dev

# Type check
npm run lint

# Run CLI tests
npm run test:cli
```

## Project Structure

```
src/
├── cli/           # CLI entry point and commands
├── parser/        # YAML parsing and Zod schemas
├── templates/     # Remotion overlay components
├── transitions/   # Animation utilities
├── composition/   # Main Remotion composition
└── utils/         # Timing utilities
```

## License

MIT
