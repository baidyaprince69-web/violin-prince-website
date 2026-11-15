import { existsSync } from "node:fs";
import { execFileSync } from "node:child_process";

const file = "output/violin-prince-motion-10s.mp4";
if (!existsSync(file)) throw new Error("Expected MP4 output was not created: " + file);

const raw = execFileSync("ffprobe", [
  "-v", "error",
  "-select_streams", "v:0",
  "-show_entries", "stream=codec_name,width,height,r_frame_rate:format=duration",
  "-of", "json",
  file
], { encoding: "utf8" });

const probe = JSON.parse(raw);
const video = probe.streams && probe.streams[0];
const duration = Number(probe.format && probe.format.duration);
const [numerator, denominator] = String(video && video.r_frame_rate || "0/1").split("/");
const fps = Number(numerator) / Number(denominator || 1);

if (!video) throw new Error("ffprobe did not find a video stream.");
if (video.width !== 1080 || video.height !== 1920) {
  throw new Error("Expected 1080x1920 vertical output, received " + video.width + "x" + video.height + ".");
}
if (!Number.isFinite(duration) || duration < 9.8 || duration > 10.2) {
  throw new Error("Expected approximately 10 seconds, received " + duration + " seconds.");
}
if (Math.abs(fps - 30) > 0.01) throw new Error("Expected 30 fps, received " + fps + " fps.");
if (video.codec_name !== "h264") throw new Error("Expected H.264 MP4 video, received " + video.codec_name + ".");

console.log(JSON.stringify({
  file,
  codec: video.codec_name,
  width: video.width,
  height: video.height,
  fps,
  duration_seconds: duration
}, null, 2));
