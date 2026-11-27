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

export const CinematicTitleCard = ({
  title,
  subtitle,
  brandName,
  directionId,
  introDurationFrames,
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
  const translateY = interpolate(entrance, [0, 1], [20, 0]);
  const scale = interpolate(entrance, [0, 1], [0.975, 1]);
  const ruleScale = interpolate(frame, [8, 27], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const sweepX = interpolate(frame, [10, 50], [-260, 280], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });

  const bars = Array.from({ length: BAR_COUNT }, (_, index) => {
    const centreWeight = 1 - Math.abs(index - (BAR_COUNT - 1) / 2) / (BAR_COUNT / 2);
    const pulse = Math.abs(Math.sin(frame * 0.19 + index * 0.66));
    return Math.round(4 + pulse * (8 + centreWeight * 11));
  });

  return (
    <div
      style={{
        position: "absolute",
        top: 650,
        right: 27,
        width: 236,
        boxSizing: "border-box",
        padding: "18px 18px 15px 19px",
        overflow: "hidden",
        opacity,
        transform: `translateY(${translateY}px) scale(${scale})`,
        transformOrigin: "right center",
        color: theme.textPrimary,
        background: `linear-gradient(145deg, ${theme.panelStart}, ${theme.panelEnd})`,
        border: `1px solid ${theme.border}`,
        borderLeft: `3px solid ${theme.accentGold}`,
        borderRadius: 10,
        boxShadow: theme.shadow,
        backdropFilter: "blur(13px)",
        WebkitBackdropFilter: "blur(13px)",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: 1,
          background: `linear-gradient(90deg, transparent, ${theme.accentGoldSoft}, transparent)`,
          transform: `scaleX(${ruleScale})`,
          transformOrigin: "left center",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: -8,
          bottom: -8,
          left: 0,
          width: 54,
          background: `linear-gradient(90deg, transparent, ${theme.accentGoldSoft}, transparent)`,
          transform: `translateX(${sweepX}px)`,
          opacity: 0.9,
        }}
      />

      <div
        style={{
          position: "relative",
          color: theme.accentGold,
          fontFamily: "VP-Sans, Arial, sans-serif",
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 2.05,
          lineHeight: 1.35,
          textTransform: "uppercase",
        }}
      >
        {brandName}
      </div>

      <div
        style={{
          width: 56 * ruleScale,
          height: 2,
          marginTop: 10,
          marginBottom: 13,
          background: `linear-gradient(90deg, ${theme.accentGold}, ${theme.accentCool})`,
          boxShadow: `0 0 12px ${theme.accentGoldSoft}`,
        }}
      />

      <div
        style={{
          position: "relative",
          maxWidth: 194,
          color: theme.textPrimary,
          fontFamily: "VP-Serif, Georgia, serif",
          fontSize: 29,
          fontWeight: 400,
          lineHeight: 1.05,
          letterSpacing: -0.55,
          overflowWrap: "normal",
          textShadow: "0 2px 16px rgba(0,0,0,.2)",
        }}
      >
        {title}
      </div>

      {subtitle ? (
        <div
          style={{
            position: "relative",
            marginTop: 11,
            color: theme.textMuted,
            fontFamily: "VP-Sans, Arial, sans-serif",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 1.7,
            lineHeight: 1.4,
            textTransform: "uppercase",
          }}
        >
          {subtitle}
        </div>
      ) : null}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          marginTop: 15,
          paddingTop: 11,
          borderTop: "1px solid rgba(217, 189, 139, 0.18)",
        }}
      >
        <div
          style={{
            color: theme.accentGold,
            fontFamily: "VP-Sans, Arial, sans-serif",
            fontSize: 8,
            fontWeight: 700,
            letterSpacing: 1.8,
            lineHeight: 1.2,
            whiteSpace: "nowrap",
          }}
        >
          RESONANCE
        </div>
        <div
          aria-hidden="true"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 3,
            height: 22,
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
                opacity: 0.55 + (height / 24) * 0.45,
                boxShadow: index % 3 === 0 ? "0 0 7px rgba(142,215,228,.3)" : "none",
              }}
            />
          ))}
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          right: 0,
          bottom: 0,
          left: 0,
          height: 2,
          background: `linear-gradient(90deg, ${theme.accentGold}, ${theme.accentCool}, transparent 88%)`,
          transform: `scaleX(${ruleScale})`,
          transformOrigin: "left center",
          opacity: 0.8,
        }}
      />
    </div>
  );
};
