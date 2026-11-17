import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { build as bundle } from "esbuild";
import { compileMotionTracks } from "./src/motion-build.mjs";

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

function renderCharacter(character, scene, sceneIndex, characterIndex, canvasWidth, canvasHeight) {
  const action = (character.scene_actions || {})[scene.id] ||
    ((scene.character_actions || {})[character.id] || {});
  if (Array.isArray(character.scene_ids) && !character.scene_ids.includes(scene.id)) return "";
  if (action.visible === false) return "";
  const wrapperStyle = [
    "left:" + Number(action.x ?? character.x ?? 0) + "px",
    "top:" + Number(action.y ?? character.y ?? 0) + "px",
    "transform:scale(" + Number(action.scale ?? character.scale ?? 1) + ")"
  ].join(";");
  const jointForRole = {
    head: "neck",
    left_upper_arm: "left_shoulder",
    left_forearm: "left_elbow",
    left_hand: "left_wrist",
    right_upper_arm: "right_shoulder",
    right_forearm: "right_elbow",
    right_hand: "right_wrist"
  };
  const layers = (character.layers || []).map((layer) => {
    const jointName = jointForRole[layer.role];
    const joint = jointName ? (character.joints || {})[jointName] : null;
    const pivotX = joint
      ? ((Number(joint.x) * canvasWidth - Number(layer.x)) / Number(layer.width)) * 100
      : Number(layer.pivot_x ?? 0.5) * 100;
    const pivotY = joint
      ? ((Number(joint.y) * canvasHeight - Number(layer.y)) / Number(layer.height)) * 100
      : Number(layer.pivot_y ?? 0.5) * 100;
    const style = [
      "left:" + Number(layer.x) + "px",
      "top:" + Number(layer.y) + "px",
      "width:" + Number(layer.width) + "px",
      "height:" + Number(layer.height) + "px",
      "transform-origin:" + pivotX + "% " + pivotY + "%",
      "z-index:" + Number(layer.z_index ?? 1)
    ].join(";");
    const partId = scene.id + "-" + character.id + "-part-" + layer.id;
    return '<img class="rig-part" id="' + escapeHtml(partId) +
      '" data-role="' + escapeHtml(layer.role) +
      '" data-joint="' + escapeHtml(jointName || "") +
      '" alt="" draggable="false" src="' + escapeHtml(layer.src) +
      '" style="' + style + '">';
  }).join("");

  const selectedPose = String(action.pose_asset || "").toLowerCase();
  const poseIsActive = Boolean(selectedPose && character.pose_assets &&
    Object.prototype.hasOwnProperty.call(character.pose_assets, selectedPose));
  const face = (character.layers || []).find((layer) => layer.role === "face") || {};
  const expressions = Object.entries(character.expressions || {}).map(([name, expression]) => {
    const style = [
      "left:" + Number(expression.x ?? face.x ?? 0) + "px",
      "top:" + Number(expression.y ?? face.y ?? 0) + "px",
      "width:" + Number(expression.width ?? face.width ?? 1) + "px",
      "height:" + Number(expression.height ?? face.height ?? 1) + "px",
      "z-index:999"
    ].join(";");
    const initial = poseIsActive && selectedPose !== "resting_hands"
      ? "opacity:0;"
      : (name === "neutral" ? "opacity:1;" : "opacity:0;");
    const expressionId = scene.id + "-" + character.id + "-expression-" + name;
    return '<img class="rig-expression" id="' + escapeHtml(expressionId) +
      '" data-expression="' + escapeHtml(name) +
      '" alt="" draggable="false" src="' + escapeHtml(expression.src) +
      '" style="' + style + ";" + initial + '">';
  }).join("");

  const poseAssets = Object.entries(character.pose_assets || {}).map(([name, pose]) => {
    const style = [
      "left:0px", "top:0px",
      "width:" + canvasWidth + "px",
      "height:" + canvasHeight + "px",
      "object-fit:contain",
      "z-index:90",
      "opacity:" + (name === selectedPose ? "1" : "0")
    ].join(";");
    const poseId = scene.id + "-" + character.id + "-pose-" + name;
    return '<img class="rig-pose" id="' + escapeHtml(poseId) +
      '" data-pose="' + escapeHtml(name) +
      '" alt="" draggable="false" src="' + escapeHtml(pose.src) +
      '" style="' + style + '">';
  }).join("");
  return '<div class="clip character-rig" id="' + escapeHtml(scene.id + "-" + character.id) +
    '" data-pose-active="' + (poseIsActive ? "true" : "false") +
    '" data-pose-name="' + escapeHtml(poseIsActive ? selectedPose : "") +
    '" data-start="' + Number(scene.start) + '" data-duration="' + Number(scene.duration) +
    '" data-track-index="' + (40 + sceneIndex * 100 + characterIndex) +
    '" style="' + wrapperStyle + '">' + layers + expressions + poseAssets + '</div>';
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
project.motion_tracks = compileMotionTracks(project, { fps });

mkdirSync(resolve(outputDir, "dist"), { recursive: true });
const sceneIds = new Set();
const markup = project.scenes.map((scene, index) => {
  if (sceneIds.has(scene.id)) throw new Error("Scene ids must be unique: " + scene.id);
  sceneIds.add(scene.id);
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
    Math.max(0.25, sceneDuration - 0.12) + '" data-track-index="' + (10 + index * 3) + '">' +
    escapeHtml(scene.title || (index === 0 ? project.title : "")) + '</div>';
  const caption = '<div class="clip scene-caption" id="' + escapeHtml(scene.id) +
    '-caption" data-start="' + (start + 0.45) + '" data-duration="' +
    Math.max(0.25, sceneDuration - 0.45) + '" data-track-index="' + (11 + index * 3) + '">' +
    escapeHtml(scene.caption || "") + '</div>';
  const characters = (project.characters || []).map((character, characterIndex) =>
    renderCharacter(character, scene, index, characterIndex, width, height)
  ).join("");
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
  '.rig-part,.rig-expression,.rig-pose{position:absolute;object-fit:contain;max-width:none;pointer-events:none}' +
  '.character-rig[data-pose-active="true"] .rig-part{opacity:0}' +
  '.character-rig[data-pose-active="true"]:not([data-pose-name="resting_hands"]) .rig-expression{opacity:0}' +
  '</style></head><body><div id="root" data-composition-id="root" data-start="0"' +
  ' data-duration="' + duration + '" data-fps="' + fps + '"' +
  ' data-width="' + width + '" data-height="' + height + '">' + markup +
  '</div><script>window.VP_PROJECT=' + JSON.stringify(project).replace(/</g, "\\u003c") +
  ';</script><script src="./dist/player.js"></script></body></html>';

writeFileSync(resolve(outputDir, "index.html"), html, "utf8");
await bundle({
  entryPoints: [new URL("./src/player.mjs", import.meta.url).pathname],
  bundle: true,
  format: "iife",
  platform: "browser",
  target: ["chrome120"],
  outfile: resolve(outputDir, "dist/player.js"),
  legalComments: "none"
});
