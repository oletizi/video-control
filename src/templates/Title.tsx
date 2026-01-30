import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { getTransitionState, getTypewriterState } from "@/transitions";
import type { ParsedTitleOverlay, ParsedTransition } from "@/parser/parse";
import type { Theme } from "@/parser/schema";
import { defaultFontStyles } from "@/templates/shared";

export interface TitleProps {
  overlay: ParsedTitleOverlay;
  theme: Theme;
  defaultTransition?: ParsedTransition;
}

export const Title: React.FC<TitleProps> = ({ overlay, theme, defaultTransition }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const transitionIn = overlay.transition?.in ?? defaultTransition?.in ?? "fade";
  const transitionOut = overlay.transition?.out ?? defaultTransition?.out ?? "fade";
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

  const containerStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    opacity: state.opacity,
    transform: state.transform !== "none" ? state.transform : undefined,
  };

  const titleStyle: React.CSSProperties = {
    ...defaultFontStyles,
    fontSize: overlay.fontSize ?? 120,
    fontWeight: 700,
    color: overlay.color ?? theme.text,
    textAlign: "center",
    lineHeight: 1.1,
    textShadow: "0 4px 20px rgba(0, 0, 0, 0.3)",
  };

  const subtitleStyle: React.CSSProperties = {
    ...defaultFontStyles,
    fontSize: (overlay.fontSize ?? 120) * 0.4,
    fontWeight: 400,
    color: overlay.color ?? theme.text,
    opacity: 0.8,
    marginTop: 20,
    textAlign: "center",
  };

  return (
    <AbsoluteFill style={containerStyle}>
      <div style={titleStyle}>{displayText}</div>
      {displaySubtitle && <div style={subtitleStyle}>{displaySubtitle}</div>}
    </AbsoluteFill>
  );
};
