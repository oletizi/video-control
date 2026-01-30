import React from "react";
import { AbsoluteFill } from "remotion";
import { Title, LowerThird, Callout, Code, Parameter } from "@/templates";
import type {
  ParsedProject,
  ParsedOverlay,
  ParsedTitleOverlay,
  ParsedLowerThirdOverlay,
  ParsedCalloutOverlay,
  ParsedCodeOverlay,
  ParsedParameterOverlay,
  ParsedTransition,
} from "@/parser/parse";
import type { Theme } from "@/parser/schema";

export interface OverlayCompositionProps {
  project: ParsedProject;
}

export const OverlayComposition: React.FC<OverlayCompositionProps> = ({ project }) => {
  const { theme, defaults, overlays } = project;

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      {overlays.map((overlay, index) => (
        <OverlayRenderer
          key={overlay.id ?? `overlay-${index}`}
          overlay={overlay}
          theme={theme}
          defaultTransition={defaults.transition}
        />
      ))}
    </AbsoluteFill>
  );
};

interface OverlayRendererProps {
  overlay: ParsedOverlay;
  theme: Theme;
  defaultTransition?: ParsedTransition;
}

const OverlayRenderer: React.FC<OverlayRendererProps> = ({
  overlay,
  theme,
  defaultTransition,
}) => {
  switch (overlay.type) {
    case "title":
      return (
        <Title
          overlay={overlay as ParsedTitleOverlay}
          theme={theme}
          defaultTransition={defaultTransition}
        />
      );

    case "lower-third":
      return (
        <LowerThird
          overlay={overlay as ParsedLowerThirdOverlay}
          theme={theme}
          defaultTransition={defaultTransition}
        />
      );

    case "callout":
      return (
        <Callout
          overlay={overlay as ParsedCalloutOverlay}
          theme={theme}
          defaultTransition={defaultTransition}
        />
      );

    case "code":
      return (
        <Code
          overlay={overlay as ParsedCodeOverlay}
          theme={theme}
          defaultTransition={defaultTransition}
        />
      );

    case "parameter":
      return (
        <Parameter
          overlay={overlay as ParsedParameterOverlay}
          theme={theme}
          defaultTransition={defaultTransition}
        />
      );

    default: {
      // TypeScript exhaustive check
      const _exhaustive: never = overlay;
      console.warn(`Unknown overlay type: ${(_exhaustive as ParsedOverlay).type}`);
      return null;
    }
  }
};
