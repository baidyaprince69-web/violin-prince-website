import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputDir = resolve(projectRoot, "output/seeking-check");
rmSync(outputDir, { recursive: true, force: true });
mkdirSync(outputDir, { recursive: true });

const orderedTimes = "5.25,1.25,5.25,1.25";
execFileSync("npx", [
  "hyperframes",
  "snapshot",
  "--at", orderedTimes,
  "--no-end",
  "--output", outputDir
], { cwd: projectRoot, stdio: "inherit" });

const frames = [
  "frame-00-at-5.25s.png",
  "frame-01-at-1.25s.png",
  "frame-02-at-5.25s.png",
  "frame-03-at-1.25s.png"
];

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
  { time: 5.25, first: hashes[0], repeated: hashes[2] },
  { time: 1.25, first: hashes[1], repeated: hashes[3] }
];

for (const check of checks) {
  if (check.first !== check.repeated) {
    throw new Error(
      "Frame seeking is not deterministic at " + check.time +
      " seconds: the repeated request produced different pixels."
    );
  }
}

const report = {
  status: "passed",
  seek_order_seconds: [5.25, 1.25, 5.25, 1.25],
  compared_pixels: "RGBA decoded pixels (not PNG metadata)",
  repeated_time_matches: checks.map(item => ({
    time_seconds: item.time,
    sha256: item.first
  }))
};
writeFileSync(resolve(outputDir, "seeking-report.json"), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify(report, null, 2));
