import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputDir = resolve(projectRoot, "output/seeking-check");
const html = readFileSync(resolve(projectRoot, "index.html"), "utf8");
const durationMatch = html.match(/<main\b[^>]*data-duration="([0-9.]+)"/i);
const duration = Number(durationMatch?.[1]);

if (!Number.isFinite(duration) || duration < 3) {
  throw new Error("The seeking test requires a prepared composition of at least 3 seconds.");
}

rmSync(outputDir, { recursive: true, force: true });
mkdirSync(outputDir, { recursive: true });

const lateTime = Math.min(
  duration - 0.5,
  Math.max(5.25, Math.floor(duration * 0.72 * 4) / 4)
);
const earlyTime = Math.min(1.25, duration / 4);
const ordered = [lateTime, earlyTime, lateTime, earlyTime];
const formatTime = (value) => String(Number(value.toFixed(2)));
const orderedTimes = ordered.map(formatTime).join(",");

execFileSync("npx", [
  "hyperframes",
  "snapshot",
  "--at", orderedTimes,
  "--no-end",
  "--output", outputDir
], { cwd: projectRoot, stdio: "inherit" });

const frames = ordered.map((time, index) =>
  "frame-" + String(index).padStart(2, "0") + "-at-" + formatTime(time) + "s.png"
);

function pixelHash(file) {
  const source = resolve(outputDir, file);
  if (!existsSync(source)) throw new Error("Missing random-access snapshot: " + file);
  const rgba = execFileSync("ffmpeg", [
    "-hide_banner", "-loglevel", "error",
    "-i", source,
    "-f", "rawvideo",
    "-pix_fmt", "rgba",
    "-"
  ], { maxBuffer: 32 * 1024 * 1024 });
  return createHash("sha256").update(rgba).digest("hex");
}

const hashes = frames.map(pixelHash);
const checks = [
  { time: lateTime, first: hashes[0], repeated: hashes[2] },
  { time: earlyTime, first: hashes[1], repeated: hashes[3] }
];

for (const check of checks) {
  if (check.first !== check.repeated) {
    throw new Error(
      "Frame seeking is not deterministic at " + check.time +
      " seconds: the repeated request produced different pixels."
    );
  }
}
if (hashes[0] === hashes[1]) {
  throw new Error(
    "The full-track visual timeline did not change between the early and late checkpoints."
  );
}

const report = {
  status: "passed",
  composition_duration_seconds: duration,
  visual_sequence_duration_seconds: duration,
  visual_sequence_repeats: false,
  seek_order_seconds: ordered,
  compared_pixels: "RGBA decoded pixels (not PNG metadata)",
  repeated_time_matches: checks.map(item => ({
    time_seconds: item.time,
    sha256: item.first
  }))
};
writeFileSync(resolve(outputDir, "seeking-report.json"), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report, null, 2));
