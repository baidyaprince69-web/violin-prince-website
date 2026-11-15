import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  unlinkSync,
  writeFileSync
} from "node:fs";
import { basename, extname, resolve, dirname } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const audioIndex = args.indexOf("--audio");
const audioArgument = audioIndex >= 0 ? args[audioIndex + 1] : "";

if (!audioArgument || audioArgument.startsWith("--")) {
  throw new Error("Usage: node scripts/prepare-composition.mjs --audio path/to/music-file");
}

const sourceAudio = resolve(process.cwd(), audioArgument);
if (!existsSync(sourceAudio)) throw new Error("Audio file does not exist: " + sourceAudio);

const extension = extname(sourceAudio).toLowerCase();
const supportedExtensions = new Set([".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"]);
if (!supportedExtensions.has(extension)) {
  throw new Error(
    "Unsupported audio format " + (extension || "(no extension)") +
    ". Use MP3, WAV, M4A, AAC, FLAC or OGG."
  );
}

const probeOutput = execFileSync("ffprobe", [
  "-v", "error",
  "-select_streams", "a:0",
  "-show_entries", "stream=codec_name,sample_rate,channels:format=duration,format_name",
  "-of", "json",
  sourceAudio
], { encoding: "utf8", maxBuffer: 2 * 1024 * 1024 });

const probe = JSON.parse(probeOutput);
const audioStream = probe.streams?.[0];
const duration = Number(probe.format?.duration);
if (!audioStream || !Number.isFinite(duration)) {
  throw new Error("ffprobe could not find a valid audio stream and duration.");
}
if (duration < 1 || duration > 1200) {
  throw new Error("Track duration must be between 1 second and 20 minutes.");
}

const assetsDir = resolve(projectRoot, "assets");
const outputDir = resolve(projectRoot, "output");
mkdirSync(assetsDir, { recursive: true });
mkdirSync(outputDir, { recursive: true });

const assetName = "music-bed" + extension;
const assetPath = resolve(assetsDir, assetName);
if (sourceAudio !== assetPath) copyFileSync(sourceAudio, assetPath);

for (const name of readdirSync(assetsDir)) {
  if (/^music-bed\.(mp3|wav|m4a|aac|flac|ogg)$/i.test(name) && name !== assetName) {
    unlinkSync(resolve(assetsDir, name));
  }
}

const templatePath = resolve(projectRoot, "index.template.html.in");
const template = readFileSync(templatePath, "utf8");
if (!template.includes("__DURATION_SECONDS__") || !template.includes("__AUDIO_SOURCE__")) {
  throw new Error("The dynamic composition template is missing required placeholders.");
}

const durationText = duration.toFixed(3).replace(/\.?0+$/, "");
const audioSource = "./assets/" + assetName;
const html = template
  .replaceAll("__DURATION_SECONDS__", durationText)
  .replace("__AUDIO_SOURCE__", audioSource);

if (html.includes("__DURATION_SECONDS__") || html.includes("__AUDIO_SOURCE__")) {
  throw new Error("The composition still contains an unresolved media placeholder.");
}
writeFileSync(resolve(projectRoot, "index.html"), html, "utf8");

const manifest = {
  audio_file: basename(sourceAudio),
  copied_asset: assetName,
  source_duration_seconds: duration,
  audio_codec: audioStream.codec_name || null,
  sample_rate: Number(audioStream.sample_rate || 0) || null,
  channels: Number(audioStream.channels || 0) || null,
  container: probe.format?.format_name || null,
  composition_id: "vp-motion-dynamic",
  composition_duration_seconds: duration,
  visual_cycle_seconds: Math.min(10, duration),
  audio_included: true
};
writeFileSync(
  resolve(outputDir, "audio-manifest.json"),
  JSON.stringify(manifest, null, 2) + "\n",
  "utf8"
);

console.log(JSON.stringify({
  status: "prepared",
  audio_file: manifest.audio_file,
  duration_seconds: duration,
  composition_duration_seconds: duration,
  visual_cycle_seconds: manifest.visual_cycle_seconds,
  audio_asset: audioSource
}, null, 2));
