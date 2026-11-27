import React from "react";
import { Composition } from "remotion";
import { ShortComposition } from "./ShortComposition.jsx";
import { COMPOSITION_ID, FPS, HEIGHT, WIDTH } from "./contract.mjs";

const defaultProps = {
  durationInFrames: 200,
  title: "A Violin Performance",
  subtitle: "VIOLIN PRINCE",
  brandName: "VIOLIN PRINCE",
  visualDirection: "midnight-resonance",
  showIntro: true,
  introDurationFrames: 60,
};

export const RemotionRoot = () => (
  <Composition
    id={COMPOSITION_ID}
    component={ShortComposition}
    width={WIDTH}
    height={HEIGHT}
    fps={FPS}
    durationInFrames={defaultProps.durationInFrames}
    defaultProps={defaultProps}
    calculateMetadata={({ props }) => ({
      durationInFrames: props.durationInFrames,
    })}
  />
);
