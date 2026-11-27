import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";
import { CinematicTitleCard } from "./CinematicTitleCard.jsx";

export const ShortComposition = ({
  title,
  subtitle,
  brandName,
  showIntro,
  introDurationFrames,
  visualDirection,
}) => {
  const sansFont = staticFile("fonts/DMSans.woff2");
  const serifFont = staticFile("fonts/DMSerifDisplay-Regular.woff2");

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
        <CinematicTitleCard
          title={title}
          subtitle={subtitle}
          brandName={brandName}
          directionId={visualDirection}
          introDurationFrames={introDurationFrames}
        />
      ) : null}
    </AbsoluteFill>
  );
};
