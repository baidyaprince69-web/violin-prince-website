import React from "react";
import {
  Easing,
  interpolate,
  spring,
  useCurrentFrame,
} from "remotion";
import { resolveVisualDirection } from "./visualDirection.mjs";

const FPS = 25;
const BAR_COUNT = 14;

export const CinematicTextOverlay = ({
  title,
  subtitle,
  brandName,
  directionId,
  introDurationFrames,
  audioEnvelope,
}) => {
  const frame = useCurrentFrame();
  const theme = resolveVisualDirection(directionId);
  const duration = Math.max(24, Number(introDurationFrames) || 60);
  const entrance = spring({
    frame,
    fps: FPS,
    config: { damping: 19, mass: 0.72, stiffness: 128 },
  });
  const opacity = interpolate(
    frame,
    [0, 7, Math.max(8, duration - 9), duration],
    [0, 1, 1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    },
  );
  const translateY = interpolate(entrance, [0, 1], [18, 0]);
  const scale = interpolate(entrance, [0, 1], [0.985, 1]);
  const ruleScale = interpolate(frame, [8, 27], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const titleReveal = interpolate(frame, [4, 17], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const subtitleReveal = interpolate(frame, [10, 23], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  const levelAt = (targetFrame) => {
    const value = Number(audioEnvelope?.[Math.max(0, targetFrame)]);
    return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0.18;
  };
  const audioLevel = levelAt(frame);
  const bars = Array.from({ length: BAR_COUNT }, (_, index) => {
    const centreWeight = 1 - Math.abs(index - (BAR_COUNT - 1) / 2) / (BAR_COUNT / 2);
    const delayedLevel = levelAt(frame - (index % 4));
    return Math.round(3 + delayedLevel * (7 + centreWeight * 11));
  });

  const readableShadow =
    "0 2px 4px rgba(0,0,0,.94), 0 6px 18px rgba(0,0,0,.78), 0 0 34px rgba(0,0,0,.34)";

  return (
    <div
      style={{
        position: "absolute",
        top: 638,
        right: 32,
        width: 300,
        boxSizing: "border-box",
        overflow: "visible",
        opacity,
        transform: `translateY(${translateY}px) scale(${scale})`,
        transformOrigin: "right center",
        pointerEvents: "none",
        color: theme.textPrimary,
      }}
    >
      <div
        style={{
          color: theme.accentGold,
          fontFamily: "VP-Sans, Arial, sans-serif",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 3.1,
          lineHeight: 1.35,
          textTransform: "uppercase",
          textShadow: readableShadow,
          opacity: 0.98,
        }}
      >
        {brandName}
      </div>

      <div
        style={{
          position: "relative",
          width: 86 * ruleScale,
          height: 2,
          marginTop: 12,
          marginBottom: 15,
          background: `linear-gradient(90deg, ${theme.accentGold}, ${theme.accentCool})`,
          boxShadow: `0 0 ${Math.round(8 + audioLevel * 13)}px ${theme.accentGoldSoft}`,
          transformOrigin: "left center",
        }}
      />

      <div
        style={{
          maxWidth: 292,
          color: theme.textPrimary,
          fontFamily: "VP-Serif, Georgia, serif",
          fontSize: 42,
          fontWeight: 400,
          lineHeight: 0.99,
          letterSpacing: -0.72,
          overflowWrap: "normal",
          textShadow: readableShadow,
          opacity: titleReveal,
          transform: `translateY(${(1 - titleReveal) * 8}px)`,
          textWrap: "pretty",
        }}
      >
        {title}
      </div>

      {subtitle ? (
        <div
          style={{
            marginTop: 13,
            color: theme.accentCool,
            fontFamily: "VP-Sans, Arial, sans-serif",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 2.55,
            lineHeight: 1.45,
            textTransform: "uppercase",
            textShadow: readableShadow,
            opacity: subtitleReveal,
            transform: `translateY(${(1 - subtitleReveal) * 5}px)`,
          }}
        >
          {subtitle}
        </div>
      ) : null}

      <div
        aria-hidden="true"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 3,
          height: 24,
          marginTop: 14,
          filter: "drop-shadow(0 1px 5px rgba(0,0,0,.8))",
        }}
      >
        {bars.map((height, index) => (
          <div
            key={index}
            style={{
              width: 3,
              height,
              borderRadius: 3,
              background: index % 3 === 0 ? theme.accentCool : theme.accentGold,
              opacity: 0.62 + (height / 22) * 0.38,
              boxShadow: index % 3 === 0
                ? `0 0 ${Math.round(2 + audioLevel * 6)}px rgba(142,215,228,.38)`
                : "none",
            }}
          />
        ))}
      </div>
    </div>
  );
};
