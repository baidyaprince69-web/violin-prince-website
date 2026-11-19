import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { build as bundle } from "esbuild";
import { compileMotionTracks } from "./src/motion-build.mjs";
import { fitCharacterToCanvas } from "./src/character-layout.mjs";

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
  const layout = fitCharacterToCanvas(character, canvasWidth, canvasHeight);
  if (Array.isArray(character.scene_ids) && !character.scene_ids.includes(scene.id)) return "";
  if (action.visible === false) return "";
  const characterScale = Number(action.scale ?? character.scale ?? 1);
  const wrapperStyle = [
    "left:" + Number(action.x ?? character.x ?? 0) + "px",
    "top:" + Number(action.y ?? character.y ?? 0) + "px",
    "transform:translateY(28px) scale(" + characterScale + ")",
    "transform-origin:top left"
  ].join(";");
  const jointForRole = {
    head: "neck",
    face: "neck",
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
      ? ((Number(joint.x) * layout.sourceWidth - Number(layer.x)) / Number(layer.width)) * 100
      : Number(layer.pivot_x ?? 0.5) * 100;
    const pivotY = joint
      ? ((Number(joint.y) * layout.sourceHeight - Number(layer.y)) / Number(layer.height)) * 100
      : Number(layer.pivot_y ?? 0.5) * 100;
    const style = [
      "left:" + (layout.offsetX + Number(layer.x) * layout.scale) + "px",
      "top:" + (layout.offsetY + Number(layer.y) * layout.scale) + "px",
      "width:" + (Number(layer.width) * layout.scale) + "px",
      "height:" + (Number(layer.height) * layout.scale) + "px",
      "transform-origin:0 0",
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
    const neck = (character.joints || {}).neck;
    const expressionX = Number(expression.x ?? face.x ?? 0);
    const expressionY = Number(expression.y ?? face.y ?? 0);
    const expressionWidth = Number(expression.width ?? face.width ?? 1);
    const expressionHeight = Number(expression.height ?? face.height ?? 1);
    const pivotX = neck
      ? ((Number(neck.x) * layout.sourceWidth - expressionX) / expressionWidth) * 100
      : 50;
    const pivotY = neck
      ? ((Number(neck.y) * layout.sourceHeight - expressionY) / expressionHeight) * 100
      : 50;
    const style = [
      "left:" + (layout.offsetX + expressionX * layout.scale) + "px",
      "top:" + (layout.offsetY + expressionY * layout.scale) + "px",
      "width:" + (expressionWidth * layout.scale) + "px",
      "height:" + (expressionHeight * layout.scale) + "px",
      "transform-origin:0 0",
      "z-index:999"
    ].join(";");
    // Full-body pose plates already contain their own face. Never layer
    // the master-face expression crop over a complete pose illustration.
    const initial = poseIsActive
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


function renderMotionGraphic(scene) {
  const data = scene.graphic_data;
  if (!data || typeof data !== "object") return "";
  const type = String(data.type || "").toLowerCase();
  const prefix = scene.id + "-graphic";
  const start = Number(scene.start) || 0;
  const duration = Number(scene.duration) || 1;
  const withPresenter = scene.visual_composition?.layout === "graphic_left_presenter_right";
  const panelClass = withPresenter ? "motion-graphic motion-graphic--with-presenter" : "motion-graphic motion-graphic--full";
  const heading = escapeHtml(data.title || scene.graphic_label || "KEY DETAIL");
  const detail = escapeHtml(data.detail || scene.graphic_detail || "");
  const itemLabel = (item) => typeof item === "string"
    ? item : (item?.label || item?.display || item?.title || "");
  const items = Array.isArray(data.items) ? data.items : [];

  if (["process_flow", "signal_path", "comparison"].includes(type)) {
    if (items.length < 2 || items.length > 4) {
      throw new Error("Motion graphic " + scene.id + " requires two to four process items.");
    }
    const rowGap = 88;
    const firstY = 34;
    const connectorPaths = items.slice(0, -1).map((_item, index) => {
      const from = firstY + index * rowGap + 23;
      const to = firstY + (index + 1) * rowGap - 23;
      return '<path class="graphic-connector" id="' + prefix + '-connector-' + index +
        '" pathLength="1" d="M 27 ' + from + ' L 27 ' + to + '"></path>';
    }).join("");
    const rows = items.map((item, index) => {
      const top = 10 + index * rowGap;
      const label = escapeHtml(itemLabel(item));
      const number = String(index + 1).padStart(2, "0");
      return '<div class="graphic-step" id="' + prefix + '-node-' + index +
        '" style="top:' + top + 'px">' +
        '<span class="graphic-node-index">' + number + '</span>' +
        '<span class="graphic-step-label">' + label + '</span></div>';
    }).join("");
    return '<div class="clip ' + panelClass + ' graphic-flow-panel" id="' + prefix +
      '" data-start="' + start + '" data-duration="' + duration +
      '" data-track-index="30">' +
      '<p class="graphic-eyebrow">VISUAL EXPLANATION</p>' +
      '<h3 class="graphic-heading" id="' + prefix + '-heading">' + heading + '</h3>' +
      (detail ? '<p class="graphic-detail">' + detail + '</p>' : '') +
      '<div class="graphic-flow">' +
      '<svg class="graphic-flow-lines" viewBox="0 0 300 ' + (firstY + (items.length - 1) * rowGap + 30) +
      '" preserveAspectRatio="none" aria-hidden="true">' + connectorPaths + '</svg>' +
      rows + '</div></div>';
  }

  if (type === "arch_heights") {
    if (items.length < 2 || items.length > 4) {
      throw new Error("Animated arch-height chart " + scene.id + " requires two to four values.");
    }
    const numeric = items.map((item) => {
      const value = Number(item?.value);
      if (!Number.isFinite(value) || value <= 0) {
        throw new Error("Animated arch-height chart " + scene.id + " contains an invalid value.");
      }
      return value;
    });
    const maximum = Math.max(...numeric);
    const bars = items.map((item, index) => {
      const height = Math.max(8, Math.round(numeric[index] / maximum * 100));
      return '<div class="graphic-bar-column" id="' + prefix + '-node-' + index + '">' +
        '<div class="graphic-bar-value">' + escapeHtml(item.display || String(numeric[index])) + '</div>' +
        '<div class="graphic-bar-track"><div class="graphic-bar-fill" id="' + prefix +
        '-bar-' + index + '" style="height:' + height + '%"></div></div>' +
        '<div class="graphic-bar-label">' + escapeHtml(item.label || ("ITEM " + (index + 1))) + '</div>' +
        '</div>';
    }).join("");
    return '<div class="clip ' + panelClass + ' graphic-bars-panel" id="' + prefix +
      '" data-start="' + start + '" data-duration="' + duration +
      '" data-track-index="30"><p class="graphic-eyebrow">VISUAL COMPARISON</p>' +
      '<h3 class="graphic-heading" id="' + prefix + '-heading">' + heading + '</h3>' +
      '<div class="graphic-bars">' + bars + '</div></div>';
  }

  if (type === "waveform") {
    const points = [];
    for (let index = 0; index <= 48; index += 1) {
      const x = 8 + index * 5.8;
      const envelope = 0.25 + 0.75 * Math.abs(Math.sin(index / 48 * Math.PI));
      const y = 76 + Math.sin(index / 48 * Math.PI * 8) * 27 * envelope;
      points.push((index === 0 ? "M " : "L ") + x.toFixed(1) + " " + y.toFixed(1));
    }
    return '<div class="clip ' + panelClass + ' graphic-wave-panel" id="' + prefix +
      '" data-start="' + start + '" data-duration="' + duration +
      '" data-track-index="30"><p class="graphic-eyebrow">SIGNAL IN MOTION</p>' +
      '<h3 class="graphic-heading" id="' + prefix + '-heading">' + heading + '</h3>' +
      '<svg class="graphic-wave" viewBox="0 0 300 150" role="img" aria-label="Animated illustrative waveform">' +
      '<path id="' + prefix + '-wave" class="graphic-wave-path" pathLength="1" d="' +
      points.join(" ") + '"></path><circle id="' + prefix + '-wave-marker" class="graphic-wave-marker" ' +
      'cx="8" cy="76" r="6"></circle></svg>' +
      (detail ? '<p class="graphic-detail">' + detail + '</p>' : '') + '</div>';
  }

  throw new Error("Unsupported motion graphic type in scene " + scene.id + ": " + type);
}

function renderAmbientMotif(scene) {
  const mode = String(scene.visual_mode || "").toLowerCase();
  if (mode === "macro_illustration") {
    const prefix = scene.id + "-motif";
    return '<svg class="visual-motif visual-motif--rings" viewBox="0 0 480 480" aria-hidden="true">' +
      '<circle id="' + prefix + '-ring-outer" cx="240" cy="240" r="186"></circle>' +
      '<circle id="' + prefix + '-ring-inner" cx="240" cy="240" r="128"></circle>' +
      '<circle id="' + prefix + '-ring-core" cx="240" cy="240" r="68"></circle>' +
      '<path id="' + prefix + '-ring-sweep" d="M 240 54 A 186 186 0 0 1 425 240"></path>' +
      '</svg>';
  }
  if (mode === "cover_performance") {
    const prefix = scene.id + "-motif";
    const bars = Array.from({ length: 18 }, (_value, index) => {
      const height = 28 + Math.round((0.5 + 0.5 * Math.sin(index * 0.83)) * 48);
      return '<span class="visualizer-bar" id="' + prefix + '-bar-' + index +
        '" style="height:' + height + 'px"></span>';
    }).join("");
    return '<div class="visual-motif visual-motif--spectrum" aria-hidden="true">' + bars + '</div>';
  }
  return "";
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

const motionSceneReports = (project.scenes || []).map((scene) => {
  const prefix = scene.id + "-graphic";
  const data = scene.graphic_data || null;
  const type = String(data?.type || "").toLowerCase();
  const expectedGraphicItems = type === "waveform" ? 1 :
    (Array.isArray(data?.items) ? data.items.length : 0);
  const graphicMotionCount = new Set(project.motion_tracks
    .filter((track) =>
      String(track.target || "").startsWith(prefix + "-node-") ||
      track.target === prefix + "-wave"
    )
    .map((track) => track.target)).size;
  if (data && graphicMotionCount < expectedGraphicItems) {
    throw new Error("Scene " + scene.id + " planned a " + type +
      " graphic but produced only " + graphicMotionCount +
      " animated graphic elements; refusing a static infographic.");
  }
  const visibleCharacters = (project.characters || []).filter((character) => {
    const action = (character.scene_actions || {})[scene.id] ||
      ((scene.character_actions || {})[character.id] || {});
    return action.visible !== false;
  });
  const animatedPresenterCount = visibleCharacters.filter((character) => {
    const action = (character.scene_actions || {})[scene.id] ||
      ((scene.character_actions || {})[character.id] || {});
    if (!action.gesture && !action.pose && !action.keyframes) return false;
    const characterPrefix = scene.id + "-" + character.id + "-part-";
    return project.motion_tracks.some((track) =>
      String(track.target || "").startsWith(characterPrefix)
    );
  }).length;
  if (visibleCharacters.some((character) => {
    const action = (character.scene_actions || {})[scene.id] ||
      ((scene.character_actions || {})[character.id] || {});
    return Boolean(action.gesture || action.pose || action.keyframes);
  }) && animatedPresenterCount < 1) {
    throw new Error("Scene " + scene.id +
      " shows a presenter with a requested gesture but generated no articulated motion.");
  }
  return {
    scene_id: scene.id,
    graphic_type: type,
    expected_graphic_items: expectedGraphicItems,
    animated_graphic_items: graphicMotionCount,
    visible_character_count: visibleCharacters.length,
    animated_presenter_count: animatedPresenterCount
  };
});
const motionReport = {
  status: "passed",
  renderer: "Motion + HyperFrames",
  total_motion_tracks: project.motion_tracks.length,
  animated_graphic_scene_count: motionSceneReports.filter((scene) => scene.expected_graphic_items > 0).length,
  animated_graphic_item_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_graphic_items, 0),
  animated_presenter_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_presenter_count, 0),
  scenes: motionSceneReports
};

mkdirSync(resolve(outputDir, "dist"), { recursive: true });
writeFileSync(resolve(outputDir, "motion-report.json"),
  JSON.stringify(motionReport, null, 2) + "\n", "utf8");
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
  const presenterLayout = scene.visual_composition?.layout === "graphic_left_presenter_right";
  const titleClass = presenterLayout ? "clip scene-title scene-title--with-presenter" : "clip scene-title";
  const captionClass = presenterLayout ? "clip scene-caption scene-caption--with-presenter" : "clip scene-caption";
  const title = '<div class="' + titleClass + '" id="' + escapeHtml(scene.id) +
    '-title" data-start="' + (start + 0.12) + '" data-duration="' +
    Math.max(0.25, sceneDuration - 0.12) + '" data-track-index="' + (10 + index * 3) + '">' +
    escapeHtml(scene.title || (index === 0 ? project.title : "")) + '</div>';
  const caption = '<div class="' + captionClass + '" id="' + escapeHtml(scene.id) +
    '-caption" data-start="' + (start + 0.45) + '" data-duration="' +
    Math.max(0.25, sceneDuration - 0.45) + '" data-track-index="' + (11 + index * 3) + '">' +
    escapeHtml(scene.caption || "") + '</div>';
  const graphic = renderMotionGraphic(scene);
  const atmosphere = renderAmbientMotif(scene);
  const characters = (project.characters || []).map((character, characterIndex) =>
    renderCharacter(character, scene, index, characterIndex, width, height)
  ).join("");
  return background + title + caption + graphic + atmosphere + characters;
}).join("");

const html = '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<title>' + escapeHtml(project.title || "Violin Prince") + '</title>' +
  '<style>' +
  'html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#080f1a}' +
  '#root{position:relative;width:' + width + 'px;height:' + height + 'px;overflow:hidden;background:#080f1a}' +
  '.scene-background{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transform:scale(1.045)}' +
  '.scene-title,.scene-caption{position:absolute;left:7%;right:7%;color:#fff;opacity:0;text-shadow:0 4px 24px #0008}' +
  '.scene-title{top:9%;font:700 38px/1.12 system-ui,sans-serif;letter-spacing:-.03em;z-index:20}' +
  '.scene-caption{bottom:8%;font:500 22px/1.35 system-ui,sans-serif;max-width:86%;color:#e6edf4;z-index:21}' +
  '.scene-title--with-presenter{left:5%;right:auto;width:52%;font-size:31px}' +
  '.scene-caption--with-presenter{left:5%;right:auto;width:52%;max-width:52%;font-size:19px;bottom:6%}' +
  '.character-rig{position:absolute;width:100%;height:100%;opacity:0;transform-origin:top left}' +
  '.rig-part,.rig-expression,.rig-pose{position:absolute;object-fit:contain;max-width:none;pointer-events:none}' +
  '.motion-graphic{position:absolute;left:auto;top:auto;right:auto;bottom:auto;width:86%;height:auto;z-index:34;overflow:visible;color:#f7f1e6;opacity:0;padding:22px 18px;border:1px solid rgba(74,190,185,.26);background:linear-gradient(145deg,rgba(8,18,31,.95),rgba(12,28,40,.91));box-shadow:0 18px 48px rgba(0,0,0,.28),inset 0 0 36px rgba(74,190,185,.06);border-radius:18px}' +
  '.motion-graphic--full{left:7%;top:23%;width:86%;min-height:380px}' +
  '.motion-graphic--with-presenter{left:5%;top:22%;width:51%;min-height:400px;padding:18px 12px}' +
  '.graphic-eyebrow{margin:0 0 9px;color:#4abeb9;font:700 12px/1.2 system-ui,sans-serif;letter-spacing:.18em;text-transform:uppercase}' +
  '.graphic-heading{margin:0;color:#f7f1e6;font:600 23px/1.12 system-ui,sans-serif;letter-spacing:-.02em}' +
  '.graphic-detail{margin:10px 0 0;color:#b8c5d0;font:500 14px/1.35 system-ui,sans-serif}' +
  '.graphic-flow{position:relative;height:330px;margin-top:15px}' +
  '.graphic-flow-lines{position:absolute;inset:0;width:100%;height:100%;overflow:visible}' +
  '.graphic-connector{fill:none;stroke:#4abeb9;stroke-width:2.5;stroke-linecap:round;stroke-dasharray:1;stroke-dashoffset:1;filter:drop-shadow(0 0 5px rgba(74,190,185,.35))}' +
  '.graphic-step{position:absolute;left:0;right:0;display:flex;align-items:center;gap:12px;min-height:54px;opacity:0;transform:translateY(18px) scale(.96)}' +
  '.graphic-node-index{display:grid;place-items:center;flex:0 0 46px;width:46px;height:46px;border:1.5px solid #ebca8b;border-radius:50%;color:#ebca8b;font:700 14px/1 system-ui,sans-serif;box-shadow:0 0 18px rgba(235,202,139,.12),inset 0 0 13px rgba(235,202,139,.08)}' +
  '.graphic-step-label{color:#f7f1e6;font:650 17px/1.18 system-ui,sans-serif;letter-spacing:.01em;overflow-wrap:anywhere}' +
  '.graphic-bars{display:flex;align-items:flex-end;justify-content:space-around;gap:12px;height:280px;margin-top:24px;padding:12px 4px 0;border-bottom:1px solid rgba(183,199,214,.35)}' +
  '.graphic-bar-column{display:flex;flex:1;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:9px;opacity:0}' +
  '.graphic-bar-value,.graphic-bar-label{font:600 12px/1.15 system-ui,sans-serif;color:#dce6ed;text-align:center}' +
  '.graphic-bar-track{display:flex;align-items:flex-end;justify-content:center;width:min(48px,70%);height:68%;background:rgba(74,190,185,.09);border:1px solid rgba(74,190,185,.2);border-radius:9px;overflow:hidden}' +
  '.graphic-bar-fill{width:100%;transform:scaleY(0);transform-origin:bottom;background:linear-gradient(180deg,#ebca8b,#4abeb9);border-radius:8px 8px 0 0;box-shadow:0 0 22px rgba(74,190,185,.24)}' +
  '.graphic-wave{width:100%;height:210px;margin-top:32px;overflow:visible}' +
  '.graphic-wave-path{fill:none;stroke:#ebca8b;stroke-width:3.5;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:1;filter:drop-shadow(0 0 8px rgba(74,190,185,.42))}' +
  '.graphic-wave-marker{fill:#f7f1e6;stroke:#4abeb9;stroke-width:3}' +
  '.visual-motif{position:absolute;z-index:25;pointer-events:none}' +
  '.visual-motif--rings{right:-7%;top:24%;width:66%;height:50%;opacity:.48;overflow:visible}' +
  '.visual-motif--rings circle{fill:none;stroke:#4abeb9;stroke-width:1.4;stroke-opacity:.6;transform-box:fill-box;transform-origin:center}' +
  '.visual-motif--rings circle:nth-child(2){stroke:#ebca8b;stroke-opacity:.48;stroke-dasharray:5 12}' +
  '.visual-motif--rings circle:nth-child(3){stroke:#f7f1e6;stroke-opacity:.35;stroke-dasharray:2 9}' +
  '.visual-motif--rings path{fill:none;stroke:#ebca8b;stroke-width:3;stroke-linecap:round;stroke-dasharray:2 8;filter:drop-shadow(0 0 8px rgba(235,202,139,.6))}' +
  '.visual-motif--spectrum{left:8%;right:8%;bottom:22%;height:92px;display:flex;align-items:center;justify-content:center;gap:7px;opacity:.76}' +
  '.visualizer-bar{display:block;flex:1;max-width:17px;border-radius:9px 9px 3px 3px;transform:scaleY(.22);transform-origin:center bottom;background:linear-gradient(180deg,#f7f1e6 0%,#ebca8b 42%,#4abeb9 100%);box-shadow:0 0 14px rgba(74,190,185,.24)}' +
  // Expression plates replace the base face crop; showing both creates a ghosted double face.
  '.rig-part[data-role="face"]{opacity:0}' +
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
