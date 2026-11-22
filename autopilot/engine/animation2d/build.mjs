import { readFileSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { build as bundle } from "esbuild";
import { compileMotionTracks } from "./src/motion-build.mjs";
import { gestureKeyframes } from "./src/contract.mjs";
import { fitCharacterToCanvas } from "./src/character-layout.mjs";
import { renderStagecraftMarkup, stagecraftMotionNodeIds, stagecraftNodeCounts } from "./src/stagecraft.mjs";

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

function gestureKeyframeCount(name) {
  const gesture = gestureKeyframes(name);
  return Object.values(gesture).reduce((maximum, properties) => {
    const longest = Object.values(properties || {}).reduce((count, values) =>
      Math.max(count, Array.isArray(values) ? values.length : 0), 0);
    return Math.max(maximum, longest);
  }, 0);
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
  const compositeBase = Boolean(character.base_art && character.base_art.src);
  const hasHeadPlates = !compositeBase && (
    Object.keys(character.head_variants || {}).length > 0 ||
    Object.keys(character.head_angles || {}).length > 0);
  const baseArt = compositeBase ? (() => {
    const asset = character.base_art;
    const style = [
      "position:absolute",
      "left:" + (layout.offsetX + Number(asset.x || 0) * layout.scale) + "px",
      "top:" + (layout.offsetY + Number(asset.y || 0) * layout.scale) + "px",
      "width:" + (Number(asset.width) * layout.scale) + "px",
      "height:" + (Number(asset.height) * layout.scale) + "px",
      "object-fit:contain",
      "transform-origin:0 0",
      "z-index:" + Number(asset.z_index ?? 10)
    ].join(";");
    return '<img class="rig-base-art" id="' + escapeHtml(scene.id + "-" + character.id + "-base-art") +
      '" alt="" draggable="false" src="' + escapeHtml(asset.src) +
      '" style="' + style + '">';
  })() : "";
  const jointForRole = {
    head: "neck",
    face: "neck",
    left_upper_arm: "left_shoulder",
    left_forearm: "left_elbow",
    left_hand: "left_wrist",
    right_upper_arm: "right_shoulder",
    right_forearm: "right_elbow",
    right_hand: "right_wrist",
    left_thigh: "left_hip",
    left_calf: "left_knee",
    left_foot: "left_ankle",
    right_thigh: "right_hip",
    right_calf: "right_knee",
    right_foot: "right_ankle",
    finger_index: "right_index_base",
    finger_middle: "right_middle_base",
    finger_ring: "right_ring_base",
    finger_little: "right_little_base"
  };
  const layers = (character.layers || [])
    .filter(layer => !compositeBase ||
      layer.role === "left_hand" || String(layer.role || "").startsWith("finger_"))
    .map((layer) => {
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
    ];
    if (hasHeadPlates && (layer.role === "head" || layer.role === "face")) {
      style.push("opacity:0");
    }
    const styleText = style.join(";");
    const partId = scene.id + "-" + character.id + "-part-" + layer.id;
    return '<img class="rig-part" id="' + escapeHtml(partId) +
      '" data-role="' + escapeHtml(layer.role) +
      '" data-joint="' + escapeHtml(jointName || "") +
      '" alt="" draggable="false" src="' + escapeHtml(layer.src) +
      '" style="' + styleText + '">';
  }).join("");

  const props = Object.values(character.props || {})
    .filter(prop => !compositeBase || prop.id === "bow")
    .map((prop) => {
    const style = [
      "left:" + (layout.offsetX + Number(prop.x) * layout.scale) + "px",
      "top:" + (layout.offsetY + Number(prop.y) * layout.scale) + "px",
      "width:" + (Number(prop.width) * layout.scale) + "px",
      "height:" + (Number(prop.height) * layout.scale) + "px",
      "transform-origin:0 0",
      "z-index:" + Number(prop.z_index ?? 25)
    ].join(";");
    const propId = scene.id + "-" + character.id + "-prop-" + prop.id;
    return '<img class="rig-prop" id="' + escapeHtml(propId) +
      '" data-prop="' + escapeHtml(prop.id) +
      '" data-attached-to="' + escapeHtml(prop.attach_to || "torso") +
      '" alt="" draggable="false" src="' + escapeHtml(prop.src) +
      '" style="' + style + '">';
  }).join("");

  const selectedPose = String(action.pose_asset || "").toLowerCase();
  const poseIsActive = Boolean(selectedPose && character.pose_assets &&
    Object.prototype.hasOwnProperty.call(character.pose_assets, selectedPose));
  const face = (character.layers || []).find((layer) => layer.role === "face") || {};
  const expressions = compositeBase ? "" : Object.entries(character.expressions || {}).map(([name, expression]) => {
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
    const initial = (poseIsActive || hasHeadPlates)
      ? "opacity:0;"
      : (name === "neutral" ? "opacity:1;" : "opacity:0;");
    const expressionId = scene.id + "-" + character.id + "-expression-" + name;
    return '<img class="rig-expression" id="' + escapeHtml(expressionId) +
      '" data-expression="' + escapeHtml(name) +
      '" alt="" draggable="false" src="' + escapeHtml(expression.src) +
      '" style="' + style + ";" + initial + '">';
  }).join("");

  const poseAssets = compositeBase ? "" : Object.entries(character.pose_assets || {}).map(([name, pose]) => {
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
  const selectedHeadAngle = String(action.head_angle || "front").toLowerCase();
  const selectedHeadExpression = String(action.head_expression || action.expression || "neutral").toLowerCase();
  const headVariantEntries = Object.entries(character.head_variants || {});
  const headAngleEntries = Object.entries(character.head_angles || {});
  const headVariants = compositeBase ? "" : headVariantEntries.map(([name, variant]) => {
    const style = [
      "position:absolute",
      "left:" + (layout.offsetX + Number(variant.x) * layout.scale) + "px",
      "top:" + (layout.offsetY + Number(variant.y) * layout.scale) + "px",
      "width:" + (Number(variant.width) * layout.scale) + "px",
      "height:" + (Number(variant.height) * layout.scale) + "px",
      "object-fit:contain",
      "transform-origin:0 0",
      "z-index:" + Number(variant.z_index ?? 85),
      "opacity:" + (!poseIsActive && selectedHeadAngle === "front" && name === selectedHeadExpression ? "1" : "0")
    ].join(";");
    const variantId = scene.id + "-" + character.id + "-head-variant-" + name;
    return '<img class="rig-head-variant" id="' + escapeHtml(variantId) +
      '" data-head-variant="' + escapeHtml(name) +
      '" alt="" draggable="false" src="' + escapeHtml(variant.src) +
      '" style="' + style + '">';
  }).join("");
  const headAngles = compositeBase ? "" : headAngleEntries.map(([name, angle]) => {
    const style = [
      "position:absolute",
      "left:" + (layout.offsetX + Number(angle.x) * layout.scale) + "px",
      "top:" + (layout.offsetY + Number(angle.y) * layout.scale) + "px",
      "width:" + (Number(angle.width) * layout.scale) + "px",
      "height:" + (Number(angle.height) * layout.scale) + "px",
      "object-fit:contain",
      "transform-origin:0 0",
      "z-index:" + Number(angle.z_index ?? 85),
      "opacity:" + (!poseIsActive && selectedHeadAngle === name && name !== "front" ? "1" : "0")
    ].join(";");
    const angleId = scene.id + "-" + character.id + "-head-angle-" + name;
    return '<img class="rig-head-angle" id="' + escapeHtml(angleId) +
      '" data-head-angle="' + escapeHtml(name) +
      '" alt="" draggable="false" src="' + escapeHtml(angle.src) +
      '" style="' + style + '">';
  }).join("");

  return '<div class="clip character-rig" id="' + escapeHtml(scene.id + "-" + character.id) +
    '" data-pose-active="' + (poseIsActive ? "true" : "false") +
    '" data-pose-name="' + escapeHtml(poseIsActive ? selectedPose : "") +
    '" data-head-plates="' + (hasHeadPlates ? "true" : "false") +
    '" data-head-angle="' + escapeHtml(selectedHeadAngle) +
    '" data-start="' + Number(scene.start) + '" data-duration="' + Number(scene.duration) +
    '" data-track-index="' + (40 + sceneIndex * 100 + characterIndex) +
    '" style="' + wrapperStyle + '"><div class="character-motion" id="' +
    escapeHtml(scene.id + "-" + character.id + "-motion") + '">' +
    baseArt + layers + expressions + props + poseAssets + headVariants + headAngles + '</div></div>';
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
const directorPalette = project.director_palette || {};
const validHex = (value, fallback) =>
  /^#[0-9a-fA-F]{6}$/.test(String(value || "")) ? String(value) : fallback;
const themeStyle = [
  "--vp-dominant:" + validHex(directorPalette.dominant, "#050b13"),
  "--vp-secondary:" + validHex(directorPalette.secondary, "#f4ead9"),
  "--vp-accent:" + validHex(directorPalette.accent, "#e7d4ad")
].join(";");

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
    const hasArticulatedTracks = project.motion_tracks.some((track) =>
      String(track.target || "").startsWith(characterPrefix)
    );
    const gestureName = String(action.gesture || "").trim().toLowerCase();
    const pointingGestureHasMultipleBeats = !["point_left", "point_right"].includes(gestureName) ||
      gestureKeyframeCount(gestureName) >= 4;
    return hasArticulatedTracks && pointingGestureHasMultipleBeats;
  }).length;
  if (visibleCharacters.some((character) => {
    const action = (character.scene_actions || {})[scene.id] ||
      ((scene.character_actions || {})[character.id] || {});
    return Boolean(action.gesture || action.pose || action.keyframes);
  }) && animatedPresenterCount < 1) {
    throw new Error("Scene " + scene.id +
      " requires articulated presenter motion; pointing gestures must contain multiple emphasis beats.");
  }
  const fullBodyPerformanceCharacters = visibleCharacters.filter((character) => {
    const action = (character.scene_actions || {})[scene.id] ||
      ((scene.character_actions || {})[character.id] || {});
    return action.instrument_performance === true ||
      String(action.gesture || "").trim().toLowerCase() === "violin_performance";
  });
  let animatedFullBodyPartCount = 0;
  let animatedFingeringControlCount = 0;
  let animatedInstrumentPropCount = 0;
  let preservedCompositeBaseCount = 0;
  for (const character of fullBodyPerformanceCharacters) {
    const compositeBaseMode = Boolean(character.base_art && character.base_art.src);
    const requiredLegs = [
      "left_thigh", "left_calf", "left_foot",
      "right_thigh", "right_calf", "right_foot"
    ];
    const requiredFingers = [
      "finger_index", "finger_middle", "finger_ring", "finger_little"
    ];
    const requiredRoles = compositeBaseMode
      ? ["left_hand", ...requiredFingers]
      : [...requiredLegs, ...requiredFingers];
    const roleSet = new Set((character.layers || []).map((layer) => String(layer.role || "")));
    const propSet = new Set(Object.keys(character.props || {}));
    if (compositeBaseMode) {
      preservedCompositeBaseCount += 1;
      if (character.base_art.mode !== "intact_full_body_with_bow_and_finger_cutouts") {
        throw new Error("Scene " + scene.id + " composite base must preserve the intact source illustration.");
      }
    }
    for (const role of requiredRoles) {
      if (!roleSet.has(role)) {
        throw new Error("Scene " + scene.id + " full-body performance rig is missing layer " + role + ".");
      }
      const target = scene.id + "-" + character.id + "-part-" +
        (character.layers || []).find((layer) => layer.role === role).id;
      const track = project.motion_tracks.find((item) =>
        item.target === target && item.property === "transform" &&
        item.values.some((value) => value !== item.values[0])
      );
      if (!track) {
        throw new Error("Scene " + scene.id + " full-body performance part " + role +
          " has no changing frame-seekable transform track.");
      }
      if (requiredLegs.includes(role)) animatedFullBodyPartCount += 1;
      if (requiredFingers.includes(role)) animatedFingeringControlCount += 1;
    }
    const requiredProps = compositeBaseMode ? ["bow"] : ["violin", "bow"];
    for (const propId of requiredProps) {
      if (!propSet.has(propId)) {
        throw new Error("Scene " + scene.id + " full-body performance is missing the " + propId + " prop.");
      }
      const target = scene.id + "-" + character.id + "-prop-" + propId;
      const track = project.motion_tracks.find((item) =>
        item.target === target && item.property === "transform" &&
        item.values.some((value) => value !== item.values[0])
      );
      if (!track) {
        throw new Error("Scene " + scene.id + " instrument prop " + propId +
          " has no changing attachment/performance transform track.");
      }
      animatedInstrumentPropCount += 1;
    }
    if (compositeBaseMode) {
      const baseTarget = scene.id + "-" + character.id + "-base-art";
      if (!project.motion_tracks.some((item) =>
        item.target === baseTarget && item.property === "transform" &&
        item.values.some((value) => value !== item.values[0])
      )) {
        throw new Error("Scene " + scene.id + " complete-body base has no coordinated breathing/sway transform.");
      }
    }
  }

  const presenterPoseAssets = visibleCharacters.flatMap((character) => {
    const action = (character.scene_actions || {})[scene.id] ||
      ((scene.character_actions || {})[character.id] || {});
    const selected = String(action.pose_asset || "").trim().toLowerCase();
    if (!selected) return [];
    const available = Object.keys(character.pose_assets || {})
      .map((name) => name.toLowerCase());
    if (!available.includes(selected)) {
      throw new Error("Scene " + scene.id + " requests unknown presenter pose asset: " + selected);
    }
    return [selected];
  });

  const stagecraftCounts = stagecraftNodeCounts(scene);
  const stagecraftTargets = new Set(project.motion_tracks
    .filter(track => track.property === "transform" && track.loop === true)
    .map(track => track.target));
  const expectedStagecraftIds = stagecraftMotionNodeIds(scene);
  const animatedStagecraftNodeCount = expectedStagecraftIds.filter(id => stagecraftTargets.has(id)).length;
  if (stagecraftCounts.total && animatedStagecraftNodeCount !== stagecraftCounts.total) {
    throw new Error("Scene " + scene.id + " stagecraft is missing looping motion tracks; static stagecraft is blocked.");
  }
  const visualLayers = Array.isArray(scene.visual_layers) ? scene.visual_layers : [];
  let independentLayerMotionCount = 0;
  if (String(scene.visual_mode || "").toLowerCase() === "director_shot") {
    if (visualLayers.length < 3) {
      throw new Error("Director shot " + scene.id + " needs at least three separate visual layers.");
    }
    const roles = new Set(visualLayers.map((layer) => String(layer.role || "").toLowerCase()));
    if (!roles.has("background") || !roles.has("subject")) {
      throw new Error("Director shot " + scene.id + " is missing a separate background or subject layer.");
    }
    if (!["foreground", "atmosphere", "graphic"].some((role) => roles.has(role))) {
      throw new Error("Director shot " + scene.id + " needs a foreground, atmosphere or graphic depth layer.");
    }
    const layerIds = new Set();
    const zIndexes = new Set();
    for (const layer of visualLayers) {
      const layerId = String(layer.id || "");
      const role = String(layer.role || "").toLowerCase();
      if (!layerId || layerIds.has(layerId)) {
        throw new Error("Director shot " + scene.id + " has a missing or duplicate visual layer ID.");
      }
      layerIds.add(layerId);
      const z = Number(layer.z_index);
      if (!Number.isInteger(z) || z < 0 || zIndexes.has(z)) {
        throw new Error("Director shot " + scene.id + " has an invalid or duplicated layer depth order.");
      }
      zIndexes.add(z);
      if (!layer.image || !existsSync(resolve(outputDir, layer.image))) {
        throw new Error("Director shot " + scene.id + " is missing staged layer asset " + layerId + ".");
      }
      if (role !== "background") {
        if (String(layer.asset_mode || "") !== "transparent_png" || !layer.asset_has_alpha) {
          throw new Error("Director shot " + scene.id + " layer " + layerId +
            " is not a verified transparent cutout.");
        }
      }
      const motionType = String(layer.motion?.type || "locked").toLowerCase();
      if (role !== "background" && motionType !== "locked") {
        independentLayerMotionCount += 1;
      }
    }
    const actualLayerMotionCount = new Set(project.motion_tracks
      .filter((track) =>
        String(track.target || "").startsWith(scene.id + "-layer-") &&
        track.property === "transform"
      )
      .map((track) => track.target)).size;
    if (actualLayerMotionCount < independentLayerMotionCount || independentLayerMotionCount < 2) {
      throw new Error("Director shot " + scene.id + " requested " + independentLayerMotionCount +
        " independently animated foreground/subject layers but Motion generated " +
        actualLayerMotionCount + ".");
    }
  }
  return {
    scene_id: scene.id,
    graphic_type: type,
    expected_graphic_items: expectedGraphicItems,
    animated_graphic_items: graphicMotionCount,
    visible_character_count: visibleCharacters.length,
    animated_presenter_count: animatedPresenterCount,
    presenter_gesture_keyframes: visibleCharacters.reduce((maximum, character) => {
      const action = (character.scene_actions || {})[scene.id] ||
        ((scene.character_actions || {})[character.id] || {});
      return Math.max(maximum, gestureKeyframeCount(action.gesture));
    }, 0),
    presenter_pose_asset_count: presenterPoseAssets.length,
    presenter_pose_assets: presenterPoseAssets,
    full_body_performance_character_count: fullBodyPerformanceCharacters.length,
    animated_full_body_parts: animatedFullBodyPartCount,
    animated_fingering_controls: animatedFingeringControlCount,
    animated_instrument_props: animatedInstrumentPropCount,
    preserved_composite_base_count: preservedCompositeBaseCount,
    full_body_visual_mode: preservedCompositeBaseCount > 0 ? "intact_composite_base" : "segmented_limb_rig",
    independent_layer_motion_count: independentLayerMotionCount,
    rendered_layer_count: visualLayers.length,
    stagecraft_environment: scene.stagecraft?.environment || "",
    animated_stagecraft_environment_nodes: stagecraftCounts.environment,
    animated_stagecraft_objects: stagecraftCounts.objects,
    animated_stagecraft_nodes: animatedStagecraftNodeCount
  };
});
const motionReport = {
  status: "passed",
  renderer: "Motion + HyperFrames",
  total_motion_tracks: project.motion_tracks.length,
  animated_graphic_scene_count: motionSceneReports.filter((scene) => scene.expected_graphic_items > 0).length,
  animated_graphic_item_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_graphic_items, 0),
  animated_presenter_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_presenter_count, 0),
  presenter_pose_asset_count: motionSceneReports.reduce((sum, scene) => sum + scene.presenter_pose_asset_count, 0),
  full_body_performance_scene_count: motionSceneReports.filter((scene) => scene.full_body_performance_character_count > 0).length,
  animated_full_body_part_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_full_body_parts, 0),
  animated_fingering_control_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_fingering_controls, 0),
  animated_instrument_prop_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_instrument_props, 0),
  preserved_composite_base_count: motionSceneReports.reduce((sum, scene) => sum + scene.preserved_composite_base_count, 0),
  independent_layer_motion_count: motionSceneReports.reduce((sum, scene) => sum + scene.independent_layer_motion_count, 0),
  rendered_layer_count: motionSceneReports.reduce((sum, scene) => sum + scene.rendered_layer_count, 0),
  animated_stagecraft_environment_node_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_stagecraft_environment_nodes, 0),
  animated_stagecraft_object_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_stagecraft_objects, 0),
  animated_stagecraft_node_count: motionSceneReports.reduce((sum, scene) => sum + scene.animated_stagecraft_nodes, 0),
  animated_stagecraft_scene_count: motionSceneReports.filter(scene => scene.animated_stagecraft_nodes > 0).length,
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
  const presenterLayout = scene.visual_composition?.layout === "graphic_left_presenter_right";
  const backgroundClass = presenterLayout
    ? "clip scene-background scene-background--presenter-layout"
    : "clip scene-background";
  const visualLayers = Array.isArray(scene.visual_layers) ? scene.visual_layers : [];
  const layeredMarkup = visualLayers.map((layer, layerIndex) => {
    const role = String(layer.role || "foreground").toLowerCase();
    const isBackground = role === "background";
    const layerId = isBackground
      ? scene.id + "-background"
      : scene.id + "-layer-" + String(layer.id || layerIndex + 1);
    const className = isBackground
      ? backgroundClass + " scene-layer scene-layer--background"
      : "clip scene-layer scene-layer--" + escapeHtml(role);
    const objectFit = isBackground ? "cover" : "contain";
    const style = [
      "z-index:" + Number(layer.z_index ?? (10 + layerIndex)),
      "object-fit:" + objectFit
    ].join(";");
    return '<img class="' + className + '" id="' + escapeHtml(layerId) +
      '" data-start="' + start + '" data-duration="' + sceneDuration +
      '" data-track-index="' + (index * 100 + Number(layer.z_index ?? layerIndex + 1)) +
      '" src="' + escapeHtml(layer.image) + '" style="' + style +
      '" alt="" draggable="false">';
  }).join("");
  const background = layeredMarkup || (scene.image
    ? '<img class="' + backgroundClass + '" id="' + escapeHtml(scene.id) +
      '-background" data-start="' + start + '" data-duration="' + sceneDuration +
      '" data-track-index="' + index + '" src="' + escapeHtml(scene.image) +
      '" alt="" draggable="false">'
    : '<div class="clip scene-background" id="' + escapeHtml(scene.id) +
      '-background" data-start="' + start + '" data-duration="' + sceneDuration +
      '" data-track-index="' + index + '" style="background:' +
      escapeHtml(scene.background_color || "#101b2b") + '"></div>');
  const titleClass = presenterLayout ? "clip scene-title scene-title--with-presenter" : "clip scene-title";
  const captionClass = presenterLayout
    ? "clip scene-caption scene-caption--with-presenter"
    : (index === 0 ? "clip scene-caption scene-caption--intro" : "clip scene-caption");
  const chapter = escapeHtml(scene.graphic_label || (index === 0 ? "THE HOOK" : index === project.scenes.length - 1 ? "THE PAYOFF" : "THE DETAIL"));
  const editorialIndex = String(scene.editorial_index || index + 1).padStart(2, "0");
  const editorialTotal = String(scene.editorial_total || project.scenes.length).padStart(2, "0");
  const brand = '<div class="clip scene-brand" id="' + escapeHtml(scene.id) +
    '-brand" data-start="' + (start + 0.04) + '" data-duration="' +
    Math.max(0.25, sceneDuration - 0.04) + '" data-track-index="' + (9 + index * 3) + '">' +
    '<span class="scene-brand__name">VIOLIN PRINCE</span>' +
    '<span class="scene-brand__separator"></span>' +
    '<span class="scene-brand__chapter">' + chapter + '</span>' +
    '<span class="scene-brand__index">' + editorialIndex + ' / ' + editorialTotal + '</span>' +
    '</div>';
  const titleText = String(scene.title || (index === 0 ? project.title : "")).trim();
  const title = titleText
    ? '<div class="' + titleClass + '" id="' + escapeHtml(scene.id) +
      '-title" data-start="' + (start + 0.18) + '" data-duration="' +
      Math.max(0.25, sceneDuration - 0.18) + '" data-track-index="' + (10 + index * 3) + '">' +
      escapeHtml(titleText) + '</div>'
    : "";
  const caption = '<div class="' + captionClass + '" id="' + escapeHtml(scene.id) +
    '-caption" data-start="' + (start + 0.52) + '" data-duration="' +
    Math.max(0.25, sceneDuration - 0.52) + '" data-track-index="' + (11 + index * 3) + '">' +
    escapeHtml(scene.caption || "") + '</div>';
  const grade = '<div class="clip scene-grade" id="' + escapeHtml(scene.id) +
    '-grade" data-start="' + start + '" data-duration="' + sceneDuration +
    '" data-track-index="' + (8 + index * 3) + '"></div>';
  const graphic = renderMotionGraphic(scene);
  const atmosphere = renderAmbientMotif(scene);
  const stagecraftMarkup = renderStagecraftMarkup(scene, width, height, index);
  const characters = (project.characters || []).map((character, characterIndex) =>
    renderCharacter(character, scene, index, characterIndex, width, height)
  ).join("");
  const cameraWorld = '<div class="scene-camera-world" id="' + escapeHtml(scene.id + "-camera-world") + '">' +
    background + grade + atmosphere + stagecraftMarkup + characters + '</div>';
  return cameraWorld + brand + title + caption + graphic;
}).join("");

const html = '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<title>' + escapeHtml(project.title || "Violin Prince") + '</title>' +
  '<style>' +
  '@font-face{font-family:DMSerifDisplay;src:url("./assets/fonts/DMSerifDisplay-Regular.ttf") format("truetype");font-display:swap}' +
  '@font-face{font-family:DMSans;src:url("./assets/fonts/DMSans-Regular.ttf") format("truetype");font-weight:400;font-display:swap}' +
  '@font-face{font-family:DMSans;src:url("./assets/fonts/DMSans-Medium.ttf") format("truetype");font-weight:500;font-display:swap}' +
  '@font-face{font-family:DMSans;src:url("./assets/fonts/DMSans-Bold.ttf") format("truetype");font-weight:700;font-display:swap}' +
  'html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#050b13}' +
  '#root{position:relative;width:' + width + 'px;height:' + height + 'px;overflow:hidden;background:var(--vp-dominant,#050b13);color:var(--vp-secondary,#f4ead9)}' +
  '.scene-background{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transform:scale(1.06);will-change:transform,opacity}' +
  '.scene-camera-world{position:absolute;inset:0;width:100%;height:100%;z-index:1;transform-origin:50% 50%;will-change:transform}' +
  '.scene-layer{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;will-change:transform,opacity,filter;transform-origin:50% 50%}' +
  '.scene-layer:not(.scene-layer--background){opacity:0;object-position:center center}' +
  '.scene-background--presenter-layout{filter:brightness(.42) saturate(.90) blur(1.5px)}' +
  '.scene-grade{position:absolute;inset:0;z-index:5;pointer-events:none;background:radial-gradient(ellipse at 52% 42%,rgba(0,0,0,0) 36%,rgba(2,7,13,.34) 100%),linear-gradient(180deg,rgba(3,8,15,.44) 0%,rgba(3,8,15,.06) 26%,rgba(3,8,15,0) 62%,rgba(3,8,15,.34) 100%)}' +
  '.scene-brand{position:absolute;left:0;right:0;top:0;height:174px;z-index:18;display:flex;align-items:flex-start;gap:12px;padding:34px 7% 0;box-sizing:border-box;background:linear-gradient(180deg,rgba(4,10,18,.96) 0%,rgba(4,10,18,.86) 52%,rgba(4,10,18,0) 100%);color:var(--vp-accent,#e7d4ad);font:700 12px/1 DMSans,Arial,sans-serif;letter-spacing:.19em;text-transform:uppercase;opacity:0}' +
  '.scene-brand__name{color:var(--vp-secondary,#f6ead6)}' +
  '.scene-brand__separator{width:1px;height:13px;background:var(--vp-accent,rgba(190,151,91,.7));margin-top:-1px}' +
  '.scene-brand__chapter{color:var(--vp-accent,#c7aa79);font-weight:500;letter-spacing:.15em}' +
  '.scene-brand__index{margin-left:auto;color:rgba(240,226,203,.72);font-size:11px;letter-spacing:.18em}' +
  '.scene-title,.scene-caption{position:absolute;left:7%;right:7%;opacity:0;text-shadow:0 6px 28px rgba(0,0,0,.72);z-index:22}' +
  '.scene-title{top:18%;max-width:86%;color:var(--vp-secondary,#fbf0df);font:400 50px/.99 DMSerifDisplay,Georgia,serif;letter-spacing:-.025em}' +
  '.scene-caption{top:18.5%;color:var(--vp-accent,#e8c98d);font:700 15px/1.25 DMSans,Arial,sans-serif;letter-spacing:.17em;text-transform:uppercase;max-width:82%}' +
  '.scene-caption--intro{top:31%;max-width:86%;font-size:14px;letter-spacing:.19em}' +
  '.scene-title--with-presenter{left:5%;right:auto;top:14%;width:43%;font-size:28px;line-height:1.02}' +
  '.scene-caption--with-presenter{left:5%;right:auto;top:18.5%;width:41%;max-width:41%;font-size:13px;letter-spacing:.12em}' +
  '.character-rig{position:absolute;width:100%;height:100%;opacity:0;transform-origin:top left;z-index:38}' +
  '.character-motion{position:absolute;inset:0;width:100%;height:100%;transform-origin:50% 70%;will-change:transform}' +
  '.scene-stagecraft{position:absolute;inset:0;width:100%;height:100%;z-index:2;overflow:hidden;pointer-events:none;mix-blend-mode:screen}' +
  '.scene-stagecraft svg{display:block;width:100%;height:100%;overflow:visible}' +
  '.stagecraft-node{transform-box:fill-box;transform-origin:center;will-change:transform,opacity}' +
  '.rig-base-art{position:absolute;object-fit:contain;max-width:none;pointer-events:none;will-change:transform}' +
  '.rig-part,.rig-expression,.rig-pose,.rig-prop{position:absolute;object-fit:contain;max-width:none;pointer-events:none}' +
  '.motion-graphic{position:absolute;left:auto;top:auto;right:auto;bottom:auto;width:86%;height:auto;z-index:34;overflow:visible;color:#f4ead9;opacity:0;padding:24px 20px;border:1px solid rgba(190,151,91,.48);border-left:3px solid #bf985e;background:linear-gradient(145deg,rgba(5,13,22,.97),rgba(9,27,35,.95));box-shadow:0 22px 64px rgba(0,0,0,.42),inset 0 1px 0 rgba(255,244,220,.07);border-radius:9px}' +
  '.motion-graphic--full{left:7%;top:23%;width:86%;min-height:380px}' +
  '.motion-graphic--with-presenter{left:5%;top:25%;width:41%;min-height:400px;padding:20px 16px}' +
  '.graphic-eyebrow{margin:0 0 11px;color:var(--vp-secondary,#70b9b2);font:700 11px/1.2 DMSans,Arial,sans-serif;letter-spacing:.21em;text-transform:uppercase}' +
  '.graphic-heading{margin:0;color:var(--vp-secondary,#fbf0df);font:400 25px/1.08 DMSerifDisplay,Georgia,serif;letter-spacing:-.01em}' +
  '.graphic-detail{margin:12px 0 0;color:#b9c7c9;font:400 14px/1.38 DMSans,Arial,sans-serif;letter-spacing:.01em}' +
  '.graphic-flow{position:relative;height:330px;margin-top:16px}' +
  '.graphic-flow-lines{position:absolute;inset:0;width:100%;height:100%;overflow:visible}' +
  '.graphic-connector{fill:none;stroke:#6ab7b0;stroke-width:2;stroke-linecap:round;stroke-dasharray:1;stroke-dashoffset:1;filter:drop-shadow(0 0 5px rgba(106,183,176,.28))}' +
  '.graphic-step{position:absolute;left:0;right:0;display:flex;align-items:center;gap:13px;min-height:54px;opacity:0;transform:translateY(18px) scale(.96)}' +
  '.graphic-node-index{display:grid;place-items:center;flex:0 0 44px;width:44px;height:44px;border:1px solid rgba(194,155,93,.85);border-radius:7px;background:rgba(194,155,93,.08);color:#d6b47c;font:700 13px/1 DMSans,Arial,sans-serif;letter-spacing:.04em;box-shadow:inset 0 0 18px rgba(194,155,93,.06)}' +
  '.graphic-step-label{color:#f5ecde;font:500 17px/1.2 DMSans,Arial,sans-serif;letter-spacing:.025em;overflow-wrap:anywhere}' +
  '.graphic-bars{display:flex;align-items:flex-end;justify-content:space-around;gap:12px;height:280px;margin-top:24px;padding:12px 4px 0;border-bottom:1px solid rgba(183,199,214,.35)}' +
  '.graphic-bar-column{display:flex;flex:1;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:9px;opacity:0}' +
  '.graphic-bar-value,.graphic-bar-label{font:600 12px/1.15 system-ui,sans-serif;color:#dce6ed;text-align:center}' +
  '.graphic-bar-track{display:flex;align-items:flex-end;justify-content:center;width:min(48px,70%);height:68%;background:rgba(74,190,185,.09);border:1px solid rgba(74,190,185,.2);border-radius:9px;overflow:hidden}' +
  '.graphic-bar-fill{width:100%;transform:scaleY(0);transform-origin:bottom;background:linear-gradient(180deg,#ebca8b,#4abeb9);border-radius:8px 8px 0 0;box-shadow:0 0 22px rgba(74,190,185,.24)}' +
  '.graphic-wave{width:100%;height:210px;margin-top:32px;overflow:visible}' +
  '.graphic-wave-path{fill:none;stroke:var(--vp-accent,#ebca8b);stroke-width:3.5;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:1;filter:drop-shadow(0 0 8px rgba(74,190,185,.42))}' +
  '.graphic-wave-marker{fill:#f7f1e6;stroke:#4abeb9;stroke-width:3}' +
  '.visual-motif{position:absolute;z-index:25;pointer-events:none;mix-blend-mode:screen}' +
  '.visual-motif--rings{right:-7%;top:24%;width:66%;height:50%;opacity:.48;overflow:visible}' +
  '.visual-motif--rings circle{fill:none;stroke:#4abeb9;stroke-width:1.4;stroke-opacity:.6;transform-box:fill-box;transform-origin:center}' +
  '.visual-motif--rings circle:nth-child(2){stroke:#ebca8b;stroke-opacity:.48;stroke-dasharray:5 12}' +
  '.visual-motif--rings circle:nth-child(3){stroke:#f7f1e6;stroke-opacity:.35;stroke-dasharray:2 9}' +
  '.visual-motif--rings path{fill:none;stroke:#ebca8b;stroke-width:3;stroke-linecap:round;stroke-dasharray:2 8;filter:drop-shadow(0 0 8px rgba(235,202,139,.6))}' +
  '.visual-motif--spectrum{left:8%;right:8%;bottom:22%;height:92px;display:flex;align-items:center;justify-content:center;gap:7px;opacity:.58}' +
  '.visualizer-bar{display:block;flex:1;max-width:17px;border-radius:9px 9px 3px 3px;transform:scaleY(.22);transform-origin:center bottom;background:linear-gradient(180deg,#f7f1e6 0%,#ebca8b 42%,#4abeb9 100%);box-shadow:0 0 14px rgba(74,190,185,.24)}' +
  // Expression plates replace the base face crop; showing both creates a ghosted double face.
  '.rig-part[data-role="face"]{opacity:0}' +
  '.character-rig[data-head-plates="true"]:not([data-pose-active="true"]) .rig-part[data-role="head"],.character-rig[data-head-plates="true"]:not([data-pose-active="true"]) .rig-part[data-role="face"]{opacity:0}' +
  '.character-rig[data-head-plates="true"] .rig-expression{opacity:0}' +
  '.character-rig[data-pose-active="true"] .rig-head-variant,.character-rig[data-pose-active="true"] .rig-head-angle{opacity:0!important}' +
  '.rig-head-variant,.rig-head-angle{pointer-events:none}' +
  '.character-rig[data-pose-active="true"] .rig-part{opacity:0}' +
  '.character-rig[data-pose-active="true"]:not([data-pose-name="resting_hands"]) .rig-expression{opacity:0}' +
  '</style></head><body><div id="root" data-composition-id="root" data-start="0"' +
  ' data-duration="' + duration + '" data-fps="' + fps + '"' +
  ' data-width="' + width + '" data-height="' + height + '" style="' + themeStyle + '">' + markup +
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
