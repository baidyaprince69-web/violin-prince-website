#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readFileSync, existsSync, mkdirSync, copyFileSync, writeFileSync, statSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, extname, resolve, basename } from "node:path";
import { fileURLToPath } from "node:url";
import {
  AUDIO_ANALYSIS_SAMPLE_RATE,
  buildAudioEnvelope,
} from "./src/audioAnalysis.mjs";
import {
  buildCompositionProps,
  COMPOSITION_ID,
  validateSourceProbe,
} from "./src/contract.mjs";

const PACKAGE_DIR = dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = resolve(PACKAGE_DIR, "public");
const ENGINE_DIR = resolve(PACKAGE_DIR, "..");
const ENTRY_POINT = "src/index.jsx";

function parseArgs(argv) {
  const values = {};
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (!item.startsWith("--")) {
      throw new Error(`Unexpected argument: ${item}`);
    }
    const key = item.slice(2);
    const value = argv[i + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Missing value for --${key}`);
    }
    values[key] = value;
    i += 1;
  }
  if (!values.input || !values.output) {
    throw new Error("Usage: npm run render -- --input <source.mp4> --output <candidate.mp4> [--title <text>] [--subtitle <text>]");
  }
  return values;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: PACKAGE_DIR,
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    ...options,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || "").slice(-5000);
    throw new Error(`${command} failed (exit ${result.status}):\n${detail}`);
  }
  return result.stdout ?? "";
}

function probeMedia(filePath) {
  const stdout = run("ffprobe", [
    "-v", "error",
    "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate",
    "-of", "json",
    filePath,
  ]);
  return JSON.parse(stdout);
}

function extractAudioPcm(filePath) {
  const result = spawnSync("ffmpeg", [
    "-v", "error",
    "-i", filePath,
    "-vn",
    "-ac", "1",
    "-ar", String(AUDIO_ANALYSIS_SAMPLE_RATE),
    "-f", "f32le",
    "pipe:1",
  ], {
    cwd: PACKAGE_DIR,
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = String(result.stderr || "").slice(-5000);
    throw new Error(`FFmpeg audio analysis failed (exit ${result.status}):\n${detail}`);
  }
  if (!Buffer.isBuffer(result.stdout) || result.stdout.length === 0) {
    throw new Error("FFmpeg returned no decoded audio samples for analysis.");
  }
  return result.stdout;
}

function sha256(filePath) {
  return createHash("sha256").update(readFileSync(filePath)).digest("hex");
}

function ensureFonts() {
  const fontSource = resolve(ENGINE_DIR, "assets", "fonts");
  const fontDestination = resolve(PUBLIC_DIR, "fonts");
  mkdirSync(fontDestination, { recursive: true });
  for (const filename of ["DMSans.woff2", "DMSerifDisplay-Regular.woff2"]) {
    const source = resolve(fontSource, filename);
    if (!existsSync(source)) {
      throw new Error(`The approved Violin Prince font asset is missing: ${source}`);
    }
    copyFileSync(source, resolve(fontDestination, filename));
  }
}

function verifyRenderedOutput(filePath, sourceMedia) {
  if (!existsSync(filePath) || statSync(filePath).size < 1000) {
    throw new Error("Remotion did not produce a usable MP4 file.");
  }
  const rendered = validateSourceProbe(probeMedia(filePath));
  const durationDelta = Math.abs(rendered.durationSeconds - sourceMedia.durationSeconds);
  if (durationDelta > 0.08) {
    throw new Error(
      `Remotion output duration changed by ${durationDelta.toFixed(3)} seconds; audio/video alignment check failed.`,
    );
  }
  return rendered;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputPath = resolve(args.input);
  const outputPath = resolve(args.output);
  if (!existsSync(inputPath) || !statSync(inputPath).isFile()) {
    throw new Error(`Input video does not exist: ${inputPath}`);
  }
  if (extname(outputPath).toLowerCase() !== ".mp4") {
    throw new Error("Output path must end in .mp4.");
  }
  if (inputPath === outputPath) {
    throw new Error("The Remotion candidate must be a separate file; the source video is never overwritten.");
  }

  const sourceMedia = validateSourceProbe(probeMedia(inputPath));
  const audioEnvelope = buildAudioEnvelope(extractAudioPcm(inputPath), {
    durationSeconds: sourceMedia.durationSeconds,
    sampleRate: AUDIO_ANALYSIS_SAMPLE_RATE,
  });
  const compositionProps = buildCompositionProps(sourceMedia, {
    title: args.title,
    subtitle: args.subtitle,
    audioEnvelope,
  });

  mkdirSync(PUBLIC_DIR, { recursive: true });
  const stagedSource = resolve(PUBLIC_DIR, "source-video.mp4");
  copyFileSync(inputPath, stagedSource);
  ensureFonts();
  mkdirSync(dirname(outputPath), { recursive: true });
  if (existsSync(outputPath)) rmSync(outputPath);
  const propsPath = resolve(PACKAGE_DIR, `render-props-${process.pid}.json`);
  writeFileSync(propsPath, JSON.stringify(compositionProps, null, 2) + "\n", "utf8");

  try {
    const cliPath = resolve(PACKAGE_DIR, "node_modules", "@remotion", "cli", "remotion-cli.js");
    if (!existsSync(cliPath)) {
      throw new Error("Remotion dependencies are not installed. Run npm install in autopilot/engine/remotion.");
    }
    const renderResult = spawnSync(process.execPath, [
      cliPath,
      "render",
      ENTRY_POINT,
      COMPOSITION_ID,
      outputPath,
      "--props",
      propsPath,
      "--codec",
      "h264",
      "--pixel-format",
      "yuv420p",
      "--concurrency",
      "2",
    ], {
      cwd: PACKAGE_DIR,
      stdio: "inherit",
      env: { ...process.env, REMOTION_NO_UPDATE_CHECK: "1" },
    });
    if (renderResult.error) throw renderResult.error;
    if (renderResult.status !== 0) {
      throw new Error(`Remotion CLI exited with status ${renderResult.status}.`);
    }
  } finally {
    if (existsSync(propsPath)) rmSync(propsPath);
  }

  const renderedMedia = verifyRenderedOutput(outputPath, sourceMedia);
  const reportPath = outputPath.replace(/\.mp4$/i, ".report.json");
  const report = {
    schema_version: 1,
    status: "rendered_candidate_not_approved",
    renderer: "Remotion 4.0.547",
    composition_id: COMPOSITION_ID,
    source: {
      filename: basename(inputPath),
      sha256: sha256(inputPath),
      ...sourceMedia,
    },
    output: {
      filename: basename(outputPath),
      sha256: sha256(outputPath),
      ...renderedMedia,
    },
    creative_inputs: {
      title: compositionProps.title,
      subtitle: compositionProps.subtitle,
      brand_name: compositionProps.brandName,
      audio_reactive_visualizer: true,
    },
    audio_analysis: {
      method: "FFmpeg-decoded mono PCM, per-frame RMS envelope",
      sample_rate_hz: AUDIO_ANALYSIS_SAMPLE_RATE,
      frequency_bands_analyzed: false,
    },
    publishing: {
      enabled: false,
      uploader_invoked: false,
      source_video_overwritten: false,
      approval_required_before_any_production_use: true,
    },
  };
  writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  console.log(`Remotion candidate rendered and verified: ${outputPath}`);
  console.log(`Review report: ${reportPath}`);
}

main().catch((error) => {
  console.error(error?.stack || error);
  process.exitCode = 1;
});
