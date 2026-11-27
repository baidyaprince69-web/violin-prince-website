import { DEFAULT_VISUAL_DIRECTION, resolveVisualDirection } from "./visualDirection.mjs";

export const COMPOSITION_ID = "violin-prince-remotion-compositor";
export const FPS = 25;
export const WIDTH = 720;
export const HEIGHT = 1280;
export const MAX_DURATION_SECONDS = 180;

export function parseFrameRate(value) {
  const [numeratorText, denominatorText] = String(value ?? "").split("/");
  const numerator = Number(numeratorText);
  const denominator = denominatorText === undefined ? 1 : Number(denominatorText);
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) {
    return 0;
  }
  return numerator / denominator;
}

export function validateSourceProbe(probe) {
  if (!probe || typeof probe !== "object" || !Array.isArray(probe.streams)) {
    throw new Error("ffprobe did not return readable video metadata.");
  }

  const video = probe.streams.find((stream) => stream.codec_type === "video");
  const audio = probe.streams.find((stream) => stream.codec_type === "audio");
  if (!video) {
    throw new Error("The source file has no video stream.");
  }
  if (!audio) {
    throw new Error("The source file has no audio stream; this compositor requires the original soundtrack.");
  }

  const width = Number(video.width);
  const height = Number(video.height);
  if (width !== WIDTH || height !== HEIGHT) {
    throw new Error(
      `Expected the existing Violin Prince portrait format ${WIDTH}x${HEIGHT}; received ${width}x${height}.`,
    );
  }

  const frameRate = parseFrameRate(video.avg_frame_rate || video.r_frame_rate);
  if (!frameRate || Math.abs(frameRate - FPS) > 0.6) {
    throw new Error(`Expected approximately ${FPS} fps; received ${frameRate || "unknown"} fps.`);
  }

  const durationSeconds = Number(probe.format?.duration);
  if (!Number.isFinite(durationSeconds) || durationSeconds < 2 || durationSeconds > MAX_DURATION_SECONDS) {
    throw new Error(
      `Source duration must be between 2 and ${MAX_DURATION_SECONDS} seconds; received ${durationSeconds}.`,
    );
  }

  return {
    width,
    height,
    frameRate,
    durationSeconds,
    hasAudio: true,
    videoCodec: String(video.codec_name || "unknown"),
    audioCodec: String(audio.codec_name || "unknown"),
  };
}

export function buildCompositionProps(media, options = {}) {
  const title = String(options.title ?? "A Violin Performance").trim().slice(0, 100);
  const subtitle = String(options.subtitle ?? "VIOLIN PRINCE").trim().slice(0, 140);
  const durationInFrames = Math.ceil(media.durationSeconds * FPS);
  const visualDirection = String(options.visualDirection ?? DEFAULT_VISUAL_DIRECTION);
  resolveVisualDirection(visualDirection);
  const suppliedEnvelope = Array.isArray(options.audioEnvelope) ? options.audioEnvelope : [];
  const audioEnvelope = Array.from({ length: durationInFrames }, (_, index) => {
    const value = Number(suppliedEnvelope[index] ?? 0.18);
    const finiteValue = Number.isFinite(value) ? value : 0.18;
    return Math.round(Math.min(1, Math.max(0, finiteValue)) * 1000) / 1000;
  });

  return {
    durationInFrames,
    title,
    subtitle,
    brandName: "VIOLIN PRINCE",
    visualDirection,
    audioEnvelope,
    showIntro: Boolean(title || subtitle),
    introDurationFrames: Math.min(75, Math.max(24, Math.floor(durationInFrames * 0.3))),
  };
}
