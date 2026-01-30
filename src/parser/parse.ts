import * as yaml from "js-yaml";
import { ZodError } from "zod";
import {
  ProjectSchema,
  type Project,
  type TitleOverlay,
  type LowerThirdOverlay,
  type CalloutOverlay,
  type CodeOverlay,
  type ParameterOverlay,
  type TransitionType,
} from "@/parser/schema";
import { parseTimecode, parseDuration } from "@/utils/timing";

/**
 * Base parsed overlay fields
 */
interface ParsedOverlayBase {
  inFrame: number;
  outFrame: number;
  durationInFrames: number;
  transitionInFrames: number;
}

/**
 * Parsed title overlay
 */
export type ParsedTitleOverlay = Omit<TitleOverlay, "in" | "out"> & ParsedOverlayBase;

/**
 * Parsed lower-third overlay
 */
export type ParsedLowerThirdOverlay = Omit<LowerThirdOverlay, "in" | "out"> & ParsedOverlayBase;

/**
 * Parsed callout overlay
 */
export type ParsedCalloutOverlay = Omit<CalloutOverlay, "in" | "out"> & ParsedOverlayBase;

/**
 * Parsed code overlay
 */
export type ParsedCodeOverlay = Omit<CodeOverlay, "in" | "out"> & ParsedOverlayBase;

/**
 * Parsed parameter overlay
 */
export type ParsedParameterOverlay = Omit<ParameterOverlay, "in" | "out"> & ParsedOverlayBase;

/**
 * Union of all parsed overlay types
 */
export type ParsedOverlay =
  | ParsedTitleOverlay
  | ParsedLowerThirdOverlay
  | ParsedCalloutOverlay
  | ParsedCodeOverlay
  | ParsedParameterOverlay;

/**
 * Parsed transition with proper types
 */
export interface ParsedTransition {
  in: TransitionType;
  out: TransitionType;
  duration: number;
}

/**
 * Result of parsing a project file
 */
export interface ParsedProject {
  project: {
    name: string;
    width: number;
    height: number;
    fps: number;
    durationInFrames: number;
  };
  defaults: {
    font: string;
    transition?: ParsedTransition;
    style?: Record<string, string | number>;
  };
  theme: {
    primary: string;
    secondary: string;
    text: string;
    accent: string;
  };
  overlays: ParsedOverlay[];
}

/**
 * Parse error with location information
 */
export class ParseError extends Error {
  constructor(
    message: string,
    public readonly line?: number,
    public readonly column?: number,
    public readonly path?: string[]
  ) {
    super(message);
    this.name = "ParseError";
  }
}

/**
 * Format Zod errors into human-readable messages
 */
function formatZodError(error: ZodError): string {
  const messages = error.errors.map((err) => {
    const path = err.path.join(".");
    return `  - ${path}: ${err.message}`;
  });
  return `Validation errors:\n${messages.join("\n")}`;
}

/**
 * Parse YAML content into a validated Project
 */
export function parseYaml(content: string): Project {
  let parsed: unknown;

  try {
    parsed = yaml.load(content);
  } catch (err) {
    if (err instanceof yaml.YAMLException) {
      throw new ParseError(
        `YAML syntax error: ${err.message}`,
        err.mark?.line,
        err.mark?.column
      );
    }
    throw err;
  }

  const result = ProjectSchema.safeParse(parsed);

  if (!result.success) {
    throw new ParseError(formatZodError(result.error));
  }

  return result.data;
}

/**
 * Parse and process a project file into render-ready format
 */
export function parseProject(content: string): ParsedProject {
  const project = parseYaml(content);

  const fps = project.project.framerate;
  const [width, height] = project.project.resolution;
  const durationInFrames = parseDuration(project.project.duration, fps);

  // Apply defaults
  const defaultTransition = project.defaults?.transition
    ? {
        in: project.defaults.transition.in as TransitionType,
        out: project.defaults.transition.out as TransitionType,
        duration: project.defaults.transition.duration,
      }
    : undefined;

  const defaults = {
    font: project.defaults?.font ?? "Inter",
    transition: defaultTransition,
    style: project.defaults?.style,
  };

  const theme = {
    primary: project.theme?.primary ?? "#3B82F6",
    secondary: project.theme?.secondary ?? "#1E293B",
    text: project.theme?.text ?? "#F8FAFC",
    accent: project.theme?.accent ?? "#F59E0B",
  };

  // Process overlays with frame-based timing
  const overlays: ParsedOverlay[] = project.overlays.map((overlay, index) => {
    const inFrame = parseTimecode(overlay.in, fps);
    const outFrame = parseTimecode(overlay.out, fps);
    const overlayDuration = outFrame - inFrame;

    // Get transition duration in frames
    const transitionDuration =
      overlay.transition?.duration ?? defaults.transition?.duration ?? 0.25;
    const transitionInFrames = Math.round(transitionDuration * fps);

    // Validate timing
    if (inFrame < 0) {
      throw new ParseError(
        `Overlay ${overlay.id ?? index}: "in" time cannot be negative`
      );
    }
    if (outFrame <= inFrame) {
      throw new ParseError(
        `Overlay ${overlay.id ?? index}: "out" time must be after "in" time`
      );
    }
    if (outFrame > durationInFrames) {
      throw new ParseError(
        `Overlay ${overlay.id ?? index}: "out" time exceeds project duration`
      );
    }

    // Destructure to remove in/out and add frame-based timing
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { in: _in, out: _out, ...rest } = overlay;

    return {
      ...rest,
      inFrame,
      outFrame,
      durationInFrames: overlayDuration,
      transitionInFrames,
    } as ParsedOverlay;
  });

  return {
    project: {
      name: project.project.name,
      width,
      height,
      fps,
      durationInFrames,
    },
    defaults,
    theme,
    overlays,
  };
}

/**
 * Validate a YAML file without full parsing
 * Returns list of validation errors, or empty array if valid
 */
export function validateYaml(content: string): string[] {
  const errors: string[] = [];

  try {
    parseProject(content);
  } catch (err) {
    if (err instanceof ParseError) {
      errors.push(err.message);
    } else if (err instanceof Error) {
      errors.push(`Unexpected error: ${err.message}`);
    } else {
      errors.push(`Unknown error: ${String(err)}`);
    }
  }

  return errors;
}
