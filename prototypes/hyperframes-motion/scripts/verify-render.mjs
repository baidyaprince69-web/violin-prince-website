import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const file = "output/violin-prince-motion-full-track.mp4";
const manifestPath = "output/audio-manifest.json";
if (!existsSync(file)) throw new Error("Expected MP4 output was not created: " + file);
if (!existsSync(manifestPath)) throw new Error("Audio manifest is missing; duration cannot be verified.");

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const expectedDuration = Number(manifest.source_duration_seconds);
if (!Number.isFinite(expectedDuration) || expectedDuration < 1) {
  throw new Error("Audio manifest contains an invalid source duration.");
}

const raw = execFileSync("ffprobe", [
  "-v", "error",
  "-show_entries",
  "stream=codec_type,codec_name,width,height,r_frame_rate,duration:format=duration",
  "-of", "json",
  file
], { encoding: "utf8", maxBuffer: 2 * 1024 * 1024 });

const probe = JSON.parse(raw);
const streams = probe.streams || [];
const video = streams.find((stream) => stream.codec_type === "video");
const audio = streams.find((stream) => stream.codec_type === "audio");
const formatDuration = Number(probe.format?.duration);
const videoDuration = Number(video?.duration || formatDuration);
const [numerator, denominator] = String(video?.r_frame_rate || "0/1").split("/");
const fps = Number(numerator) / Number(denominator || 1);

if (!video) throw new Error("ffprobe did not find a video stream.");
if (!audio) throw new Error("The exported MP4 does not contain the source music track.");
if (video.width !== 1080 || video.height !== 1920) {
  throw new Error("Expected 1080x1920 vertical output, received " + video.width + "x" + video.height + ".");
}
if (!Number.isFinite(formatDuration) || Math.abs(formatDuration - expectedDuration) > 0.25) {
  throw new Error(
    "Expected full-track duration " + expectedDuration +
    "s, received MP4 duration " + formatDuration + "s."
  );
}
if (!Number.isFinite(videoDuration) || Math.abs(videoDuration - expectedDuration) > 0.25) {
  throw new Error(
    "Video stream does not cover the full music track: " + videoDuration +
    "s versus " + expectedDuration + "s."
  );
}
if (Math.abs(fps - 30) > 0.01) throw new Error("Expected 30 fps, received " + fps + " fps.");
if (video.codec_name !== "h264") throw new Error("Expected H.264 MP4 video, received " + video.codec_name + ".");

console.log(JSON.stringify({
  file,
  codec: video.codec_name,
  audio_codec: audio.codec_name,
  audio_included: true,
  width: video.width,
  height: video.height,
  fps,
  expected_audio_duration_seconds: expectedDuration,
  actual_mp4_duration_seconds: formatDuration,
  actual_video_stream_duration_seconds: videoDuration
}, null, 2));
