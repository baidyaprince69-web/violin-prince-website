import test from "node:test";
import assert from "node:assert/strict";
import {
  FPS,
  WIDTH,
  HEIGHT,
  buildCompositionProps,
  parseFrameRate,
  validateSourceProbe,
} from "../src/contract.mjs";

const validProbe = {
  format: { duration: "8.000000" },
  streams: [
    {
      codec_type: "video",
      codec_name: "h264",
      width: WIDTH,
      height: HEIGHT,
      avg_frame_rate: "25/1",
    },
    { codec_type: "audio", codec_name: "aac" },
  ],
};

test("parses rational frame rates", () => {
  assert.equal(parseFrameRate("25/1"), 25);
  assert.ok(Math.abs(parseFrameRate("30000/1001") - 29.97) < 0.001);
  assert.equal(parseFrameRate("unknown"), 0);
});

test("accepts a source matching the Violin Prince short-video contract", () => {
  const result = validateSourceProbe(validProbe);
  assert.equal(result.width, WIDTH);
  assert.equal(result.height, HEIGHT);
  assert.equal(result.frameRate, FPS);
  assert.equal(result.hasAudio, true);
});

test("rejects sources without audio", () => {
  assert.throws(
    () => validateSourceProbe({ ...validProbe, streams: [validProbe.streams[0]] }),
    /no audio stream/,
  );
});

test("rejects mismatched dimensions and frame rates", () => {
  const landscape = structuredClone(validProbe);
  landscape.streams[0].width = 1280;
  landscape.streams[0].height = 720;
  assert.throws(() => validateSourceProbe(landscape), /Expected the existing Violin Prince portrait format/);

  const wrongFps = structuredClone(validProbe);
  wrongFps.streams[0].avg_frame_rate = "30/1";
  assert.throws(() => validateSourceProbe(wrongFps), /Expected approximately 25 fps/);
});

test("rejects overly long inputs before rendering", () => {
  const longVideo = structuredClone(validProbe);
  longVideo.format.duration = "181";
  assert.throws(() => validateSourceProbe(longVideo), /duration must be between/);
});

test("generates bounded, JSON-safe Remotion composition props", () => {
  const media = validateSourceProbe(validProbe);
  const props = buildCompositionProps(media, {
    title: "  Bowing and resonance  ",
    subtitle: "A short music explainer",
  });
  assert.equal(props.durationInFrames, 200);
  assert.equal(props.title, "Bowing and resonance");
  assert.equal(props.subtitle, "A short music explainer");
  assert.equal(props.brandName, "VIOLIN PRINCE");
  assert.equal(props.showIntro, true);
  assert.ok(props.introDurationFrames > 0 && props.introDurationFrames < props.durationInFrames);
});
