import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { build } from "esbuild";

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--project" || argv[index] === "--out-dir") {
      result[argv[index]] = argv[index + 1];
      index += 1;
    }
  }
  return result;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function renderCharacter(character, scene) {
  const action = (character.scene_actions || {})[scene.id] ||
    ((scene.character_actions || {})[character.id] || {});
  if (Array.isArray(character.scene_ids) && !character.scene_ids.includes(scene.id)) return "";
  if (action.visible === false) return "";
  const wrapperStyle = [
    "left:" + Number(action.x ?? character.x ?? 0) + "px",
    "top:" + Number(action.y ?? character.y ?? 0) + "px",
    "transform:scale(" + Number(action.scale ?? character.scale ?? 1) + ")"
  ].join(";");
  const layers = (character.layers || []).map((layer) => {
    const style = [
      "left:" + Number(layer.x) + "px",
      "top:" + Number(layer.y) + "px",
      "width:" + Number(layer.width) + "px",
      "height:" + Number(layer.height) + "px",
      "transform-origin:" + (Number(layer.pivot_x ?? 0.5) * 100) + "% " +
        (Number(layer.pivot_y ?? 0.5) * 100) + "%",
      "z-index:" + Number(layer.z_index ?? 1)
    ].join(";");
    return '<img class="rig-part" data-role="' + escapeHtml(layer.role) +
      '" alt="" draggable="false" src="' + escapeHtml(layer.src) +
      '" style="' + style + '">';
  }).join("");

  const face = (character.layers || []).find((layer) => layer.role === "face") || {};
  const expressions = Object.entries(character.expressions || {}).map(([name, expression]) => {
    const style = [
      "left:" + Number(expression.x ?? face.x ?? 0) + "px",
      "top:" + Number(expression.y ?? face.y ?? 0) + "px",
      "width:" + Number(expression.width ?? face.width ?? 1) + "px",
      "height:" + Number(expression.height ?? face.height ?? 1) + "px",
      "z-index:999"
    ].join(";");
    const initial = name === "neutral" ? "opacity:1;" : "opacity:0;";
    return '<img class="rig-expression" data-expression="' + escapeHtml(name) +
      '" alt="" draggable="false" src="' + escapeHtml(expression.src) +
      '" style="' + style + ";" + initial + '">';
  }).join("");

  return '<div class="clip character-rig" id="' + escapeHtml(scene.id + "-" + character.id) +
    '" data-start="' + Number(scene.start) + '" data-duration="' + Number(scene.duration) +
    '" data-track-index="30" style="' + wrapperStyle + '">' + layers + expressions + '</div>';
}

const args = parseArgs(process.argv.slice(2));
const projectPath = resolve(args["--project"] || "project.example.json");
const outputDir = resolve(args["--out-dir"] || ".validation");
const project = JSON.parse(readFileSync(projectPath, "utf8"));
if (!Array.isArray(project.scenes) || project.scenes.length < 1) {
  throw new Error("A HyperFrames project requires at least one scene.");
}
const width = Math.max(1, Math.floor(Number(project.width) || 720));
const height = Math.max(1, Math.floor(Number(project.height) || 1280));
const fps = Math.max(1, Math.floor(Number(project.fps) || 25));
const duration = Number(project.duration_seconds);
if (!Number.isFinite(duration) || duration <= 0) {
  throw new Error("duration_seconds must be positive.");
}

mkdirSync(resolve(outputDir, "dist"), { recursive: true });
const markup = project.scenes.map((scene, index) => {
  const start = Number(scene.start) || 0;
  const sceneDuration = Number(scene.duration);
  if (!scene.id || !Number.isFinite(sceneDuration) || sceneDuration <= 0) {
    throw new Error("Every scene needs an id and positive duration.");
  }
  const background = scene.image
    ? '<img class="clip scene-background" id="' + escapeHtml(scene.id) +
      '-background" data-start="' + start + '" data-duration="' + sceneDuration +
      '" data-track-index="' + index + '" src="' + escapeHtml(scene.image) +
      '" alt="" draggable="false">'
    : '<div class="clip scene-background" id="' + escapeHtml(scene.id) +
      '-background" data-start="' + start + '" data-duration="' + sceneDuration +
      '" data-track-index="' + index + '" style="background:' +
      escapeHtml(scene.background_color || "#101b2b") + '"></div>';
  const title = '<div class="clip scene-title" id="' + escapeHtml(scene.id) +
    '-title" data-start="' + (start + 0.12) + '" data-duration="' +
    Math.max(0.25, sceneDuration - 0.12) + '" data-track-index="10">' +
    escapeHtml(scene.title || (index === 0 ? project.title : "")) + '</div>';
  const caption = '<div class="clip scene-caption" id="' + escapeHtml(scene.id) +
    '-caption" data-start="' + (start + 0.45) + '" data-duration="' +
    Math.max(0.25, sceneDuration - 0.45) + '" data-track-index="11">' +
    escapeHtml(scene.caption || "") + '</div>';
  const characters = (project.characters || []).map((character) => renderCharacter(character, scene)).join("");
  return background + title + caption + characters;
}).join("");

const html = '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<title>' + escapeHtml(project.title || "Violin Prince") + '</title>' +
  '<style>' +
  'html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#080f1a}' +
  '#root{position:relative;width:' + width + 'px;height:' + height + 'px;overflow:hidden;background:#080f1a}' +
  '.scene-background{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transform:scale(1.045)}' +
  '.scene-title,.scene-caption{position:absolute;left:7%;right:7%;color:#fff;opacity:0;text-shadow:0 4px 24px #0008}' +
  '.scene-title{top:13%;font:700 42px/1.12 system-ui,sans-serif;letter-spacing:-.03em;z-index:20}' +
  '.scene-caption{bottom:18%;font:500 27px/1.35 system-ui,sans-serif;max-width:86%;color:#e6edf4;z-index:21}' +
  '.character-rig{position:absolute;width:100%;height:100%;opacity:0;transform-origin:center center}' +
  '.rig-part,.rig-expression{position:absolute;object-fit:contain;max-width:none;pointer-events:none}' +
  '</style></head><body><div id="root" data-composition-id="root" data-start="0"' +
  ' data-width="' + width + '" data-height="' + height + '">' + markup +
  '</div><script>window.VP_PROJECT=' + JSON.stringify(project).replace(/</g, "\\u003c") +
  ';</script><script src="./dist/player.js"></script></body></html>';

writeFileSync(resolve(outputDir, "index.html"), html, "utf8");
await build({
  entryPoints: [new URL("./src/player.mjs", import.meta.url).pathname],
  bundle: true,
  format: "iife",
  platform: "browser",
  target: ["chrome120"],
  outfile: resolve(outputDir, "dist/player.js"),
  legalComments: "none"
});
