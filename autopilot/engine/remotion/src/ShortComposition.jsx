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
  const sansFont = staticFile("fonts/DMSans.woff2");
  const serifFont = staticFile("fonts/DMSerifDisplay-Regular.woff2");
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
  const panelOffset = interpolate(frame, [0, 20], [22, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const accentWidth = interpolate(frame, [8, 30], [0, 54], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#050b13" }}>
      <style>{`
        @font-face {
          font-family: VP-Sans;
          src: url('${sansFont}') format('woff2');
          font-weight: 400 700;
          font-style: normal;
        }
        @font-face {
          font-family: VP-Serif;
          src: url('${serifFont}') format('woff2');
          font-weight: 400;
          font-style: normal;
        }
      `}</style>
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
            "linear-gradient(180deg, rgba(4,8,16,.36) 0%, rgba(4,8,16,.06) 20%, transparent 43%, transparent 72%, rgba(4,8,16,.22) 100%)",
        }}
      />

      {showIntro ? (
        <AbsoluteFill
          style={{
            pointerEvents: "none",
            opacity: introOpacity,
            transform: `translateX(${panelOffset}px)`,
          }}
        >
          <div
            style={{
              position: "absolute",
              top: 650,
              right: 28,
              width: 222,
              boxSizing: "border-box",
              padding: "19px 18px 18px 20px",
              color: "#f2e8d7",
              background:
                "linear-gradient(145deg, rgba(5,11,19,.91), rgba(8,20,32,.77))",
              border: "1px solid rgba(217,189,139,.38)",
              borderLeft: "3px solid #d9bd8b",
              borderRadius: 9,
              boxShadow: "0 16px 42px rgba(0,0,0,.34)",
              backdropFilter: "blur(12px)",
              WebkitBackdropFilter: "blur(12px)",
            }}
          >
            <div
              style={{
                color: "#d9bd8b",
                fontFamily: "VP-Sans, Arial, sans-serif",
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: 2.1,
                lineHeight: 1.3,
                textTransform: "uppercase",
              }}
            >
              {brandName}
            </div>
            <div
              style={{
                width: accentWidth,
                height: 2,
                marginTop: 11,
                marginBottom: 13,
                background:
                  "linear-gradient(90deg, #d9bd8b, rgba(217,189,139,0))",
              }}
            />
            <div
              style={{
                maxWidth: 184,
                color: "#fbf1e2",
                fontFamily: "VP-Serif, Georgia, serif",
                fontSize: 30,
                fontWeight: 400,
                lineHeight: 1.04,
                letterSpacing: -0.5,
                overflowWrap: "normal",
              }}
            >
              {title}
            </div>
            {subtitle ? (
              <div
                style={{
                  marginTop: 13,
                  color: "#e0d6c5",
                  fontFamily: "VP-Sans, Arial, sans-serif",
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: 1.35,
                  lineHeight: 1.3,
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
