import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { getTransitionState, getTypewriterState } from "@/transitions";
import type { ParsedLowerThirdOverlay, ParsedTransition } from "@/parser/parse";
import type { Theme } from "@/parser/schema";
import { defaultFontStyles, getPositionStyles } from "@/templates/shared";

export interface LowerThirdProps {
  overlay: ParsedLowerThirdOverlay;
  theme: Theme;
  defaultTransition?: ParsedTransition;
}

export const LowerThird: React.FC<LowerThirdProps> = ({
  overlay,
  theme,
  defaultTransition,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const transitionIn = overlay.transition?.in ?? defaultTransition?.in ?? "slide-up";
  const transitionOut = overlay.transition?.out ?? defaultTransition?.out ?? "slide-down";
  const transitionFrames = overlay.transitionInFrames;

  const state = getTransitionState({
    frame,
    startFrame: overlay.inFrame,
    endFrame: overlay.outFrame,
    transitionFrames,
    transitionIn,
    transitionOut,
    text: overlay.text,
    fps,
  });

  if (!state.visible) {
    return null;
  }

  // Check for typewriter effect
  const typewriter = getTypewriterState({
    frame,
    startFrame: overlay.inFrame,
    endFrame: overlay.outFrame,
    transitionFrames,
    transitionIn,
    transitionOut,
    text: overlay.text,
    fps,
  });

  const displayText = typewriter ? typewriter.text : overlay.text;
  const displaySubtitle = overlay.subtitle;

  const positionStyles = getPositionStyles(overlay.position, "bottom-left");

  // Handle the transform from position preset (center) vs transition
  const baseTransform = positionStyles.transform || "";
  const transitionTransform = state.transform !== "none" ? state.transform : "";
  const combinedTransform = [baseTransform, transitionTransform].filter(Boolean).join(" ");

  const containerStyle: React.CSSProperties = {
    ...positionStyles,
    opacity: state.opacity,
    transform: combinedTransform || undefined,
  };

  const wrapperStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "row",
    alignItems: "stretch",
    borderRadius: 8,
    overflow: "hidden",
    boxShadow: "0 4px 20px rgba(0, 0, 0, 0.3)",
  };

  const accentBarStyle: React.CSSProperties = {
    width: 6,
    backgroundColor: theme.accent,
  };

  const contentStyle: React.CSSProperties = {
    backgroundColor: overlay.backgroundColor ?? theme.secondary,
    padding: "16px 24px",
  };

  const nameStyle: React.CSSProperties = {
    ...defaultFontStyles,
    fontSize: overlay.fontSize ?? 32,
    fontWeight: 600,
    color: overlay.color ?? theme.text,
    lineHeight: 1.2,
  };

  const subtitleStyle: React.CSSProperties = {
    ...defaultFontStyles,
    fontSize: (overlay.fontSize ?? 32) * 0.6,
    fontWeight: 400,
    color: overlay.color ?? theme.text,
    opacity: 0.7,
    marginTop: 4,
  };

  return (
    <AbsoluteFill>
      <div style={containerStyle}>
        <div style={wrapperStyle}>
          <div style={accentBarStyle} />
          <div style={contentStyle}>
            <div style={nameStyle}>{displayText}</div>
            {displaySubtitle && <div style={subtitleStyle}>{displaySubtitle}</div>}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
