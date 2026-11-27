import React from "react";
import {
  AbsoluteFill,
  Easing,
  OffthreadVideo,
  interpolate,
  staticFile,
  useCurrentFrame,
} from "remotion";

export const ShortComposition = ({
  title,
  subtitle,
  brandName,
  showIntro,
  introDurationFrames,
}) => {
  const frame = useCurrentFrame();
  const introEnd = Math.max(24, Number(introDurationFrames) || 60);
  const introOpacity = interpolate(
    frame,
    [0, 8, Math.max(9, introEnd - 10), introEnd],
    [0, 1, 1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    },
  );
  const introOffset = interpolate(frame, [0, 18], [22, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const ruleWidth = interpolate(frame, [8, 28], [0, 82], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#050b13" }}>
      <OffthreadVideo
        src={staticFile("source-video.mp4")}
        volume={1}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
        }}
      />

      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(4,8,16,.62) 0%, rgba(4,8,16,.12) 22%, transparent 43%, transparent 72%, rgba(4,8,16,.22) 100%)",
        }}
      />

      {showIntro ? (
        <AbsoluteFill
          style={{
            pointerEvents: "none",
            opacity: introOpacity,
            transform: `translateY(${introOffset}px)`,
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 94,
              left: 58,
              right: 58,
              color: "#f2e8d7",
              textShadow: "0 3px 20px rgba(0,0,0,.5)",
            }}
          >
            <div
              style={{
                color: "#d9bd8b",
                fontFamily: "VP-Sans, Arial, sans-serif",
                fontSize: 15,
                fontWeight: 700,
                letterSpacing: 4,
                textTransform: "uppercase",
              }}
            >
              {brandName}
            </div>
            <div
              style={{
                width: ruleWidth,
                height: 2,
                marginTop: 17,
                marginBottom: 18,
                background: "linear-gradient(90deg, #d9bd8b, rgba(217,189,139,0))",
              }}
            />
            <div
              style={{
                maxWidth: 590,
                color: "#fbf1e2",
                fontFamily: "VP-Serif, Georgia, serif",
                fontSize: 54,
                fontWeight: 400,
                lineHeight: 1.02,
                letterSpacing: -1.3,
              }}
            >
              {title}
            </div>
            {subtitle ? (
              <div
                style={{
                  marginTop: 16,
                  color: "#e0d6c5",
                  fontFamily: "VP-Sans, Arial, sans-serif",
                  fontSize: 17,
                  fontWeight: 500,
                  letterSpacing: 1.2,
                }}
              >
                {subtitle}
              </div>
            ) : null}
          </div>
        </AbsoluteFill>
      ) : null}
    </AbsoluteFill>
  );
};
