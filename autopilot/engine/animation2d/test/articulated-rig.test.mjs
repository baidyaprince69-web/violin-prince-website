import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { compileMotionTracks } from "../src/motion-build.mjs";

const character = {
  id: "violin-prince",
  canvas: { width: 100, height: 100 },
  layers: [
    { id: "torso", role: "torso", x: 20, y: 20, width: 60, height: 70, pivot_x: 0.5, pivot_y: 0.5 },
    { id: "head", role: "head", x: 40, y: 5, width: 20, height: 45 },
    { id: "face", role: "face", x: 42, y: 20, width: 16, height: 18 },
    { id: "left_upper_arm", role: "left_upper_arm", x: 20, y: 45, width: 20, height: 30 },
    { id: "left_forearm", role: "left_forearm", x: 5, y: 65, width: 25, height: 20 },
    { id: "left_hand", role: "left_hand", x: 0, y: 80, width: 16, height: 16 },
    { id: "right_upper_arm", role: "right_upper_arm", x: 60, y: 45, width: 20, height: 30 },
    { id: "right_forearm", role: "right_forearm", x: 70, y: 65, width: 25, height: 20 },
    { id: "right_hand", role: "right_hand", x: 84, y: 80, width: 16, height: 16 }
  ],
  joints: {
    neck: { x: 0.5, y: 0.45 },
    left_shoulder: { x: 0.35, y: 0.55 },
    left_elbow: { x: 0.25, y: 0.75 },
    left_wrist: { x: 0.12, y: 0.85 },
    right_shoulder: { x: 0.65, y: 0.55 },
    right_elbow: { x: 0.75, y: 0.75 },
    right_wrist: { x: 0.88, y: 0.85 }
  },
  expressions: {
    neutral: { src: "neutral.png", x: 42, y: 20, width: 16, height: 18 }
  },
  scene_actions: {
    "head-test": {
      keyframes: {
        head: { rotate: [0, -10, 10, 0] },
        torso: { rotate: [0, -2, 2, 0] }
      }
    },
    "wave-test": { gesture: "wave" },
    "two-arm-test": { gesture: "explain" }
  }
};

test("selected expression plate replaces the static base face cut-out", () => {
  const renderer = readFileSync(new URL("../build.mjs", import.meta.url), "utf8");
  assert.ok(
    renderer.includes('.rig-part[data-role="face"]{opacity:0}'),
    "base face cut-out must be hidden beneath the selected expression layer"
  );
});

function tracksFor(sceneId) {
  return compileMotionTracks({
    fps: 25,
    width: 100,
    height: 100,
    scenes: [{ id: sceneId, start: 0, duration: 1.5 }],
    characters: [character]
  }).filter(track => track.property === "transform" && (track.target.includes("-part-") || track.target.includes("-expression-")));
}

function parseMatrix(value) {
  const match = /^matrix\(([^)]+)\)$/.exec(String(value));
  assert.ok(match, "articulated layer must use a CSS matrix transform");
  return match[1].split(",").map(Number);
}

function transformPoint(matrix, point) {
  const [a, b, c, d, e, f] = matrix;
  return {
    x: a * point.x + c * point.y + e,
    y: b * point.x + d * point.y + f
  };
}

function globalMatrix(track, layer, index) {
  const [a, b, c, d, e, f] = parseMatrix(track.values[index]);
  const x = Number(layer.x);
  const y = Number(layer.y);
  return [
    a, b, c, d,
    x + e - a * x - c * y,
    y + f - b * x - d * y
  ];
}

test("head rotation and torso counterbalance target independent rig layers", () => {
  const tracks = tracksFor("head-test");
  assert.ok(tracks.some(track => track.target === "head-test-violin-prince-part-head"));
  assert.ok(tracks.some(track => track.target === "head-test-violin-prince-part-torso"));
  assert.ok(tracks.every(track => track.values.every(value => String(value).startsWith("matrix("))));
});

test("wave gesture rotates the upper arm and forearm on separate pivots", () => {
  const targets = new Set(tracksFor("wave-test").map(track => track.target));
  assert.ok(targets.has("wave-test-violin-prince-part-right_upper_arm"));
  assert.ok(targets.has("wave-test-violin-prince-part-right_forearm"));
  assert.ok(targets.has("wave-test-violin-prince-part-right_hand"),
    "wave must articulate the wrist/hand independently");
});

test("forearms and hands follow their parent arm pivots without separating", () => {
  const tracks = tracksFor("wave-test");
  const byTarget = new Map(tracks.map(track => [track.target, track]));
  const roleTrack = role => byTarget.get("wave-test-violin-prince-part-" + role);
  const upper = roleTrack("right_upper_arm");
  const forearm = roleTrack("right_forearm");
  const hand = roleTrack("right_hand");
  assert.ok(upper && forearm && hand);

  const frameIndex = Math.floor(upper.values.length * 0.55);
  const upperLayer = character.layers.find(layer => layer.role === "right_upper_arm");
  const forearmLayer = character.layers.find(layer => layer.role === "right_forearm");
  const handLayer = character.layers.find(layer => layer.role === "right_hand");
  const elbow = { x: character.joints.right_elbow.x * 100, y: character.joints.right_elbow.y * 100 };
  const wrist = { x: character.joints.right_wrist.x * 100, y: character.joints.right_wrist.y * 100 };

  const elbowFromUpper = transformPoint(globalMatrix(upper, upperLayer, frameIndex), elbow);
  const elbowFromForearm = transformPoint(globalMatrix(forearm, forearmLayer, frameIndex), elbow);
  const wristFromForearm = transformPoint(globalMatrix(forearm, forearmLayer, frameIndex), wrist);
  const wristFromHand = transformPoint(globalMatrix(hand, handLayer, frameIndex), wrist);

  assert.ok(Math.hypot(elbowFromUpper.x - elbowFromForearm.x, elbowFromUpper.y - elbowFromForearm.y) < 0.02,
    "elbow pivot must remain connected after the upper arm rotates");
  assert.ok(Math.hypot(wristFromForearm.x - wristFromHand.x, wristFromForearm.y - wristFromHand.y) < 0.02,
    "wrist pivot must follow the forearm without a detached hand");
});

test("two-arm explanation animates both independently separated upper arms", () => {
  const targets = new Set(tracksFor("two-arm-test").map(track => track.target));
  assert.ok(targets.has("two-arm-test-violin-prince-part-left_upper_arm"));
  assert.ok(targets.has("two-arm-test-violin-prince-part-left_forearm"));
  assert.ok(targets.has("two-arm-test-violin-prince-part-left_hand"));
  assert.ok(targets.has("two-arm-test-violin-prince-part-right_upper_arm"));
  assert.ok(targets.has("two-arm-test-violin-prince-part-right_forearm"));
  assert.ok(targets.has("two-arm-test-violin-prince-part-right_hand"));
});


test("generated rig project wires real scene actions into frame-seekable motion tracks", {
  skip: !process.env.VP_RIG_PROJECT
}, () => {
  const project = JSON.parse(readFileSync(process.env.VP_RIG_PROJECT, "utf8"));
  const tracks = compileMotionTracks(project, { fps: project.fps || 25 });
  for (let index = 1; index < project.scenes.length; index += 1) {
    const previous = project.scenes[index - 1];
    const current = project.scenes[index];
    assert.ok(
      Number(previous.start) + Number(previous.duration) <= Number(current.start) + 1e-6,
      "demonstration scenes must not overlap their title/caption windows"
    );
  }
  assert.ok(
    Number(project.duration_seconds) >= Math.max(...project.scenes.map(scene =>
      Number(scene.start) + Number(scene.duration)
    )),
    "project duration must contain every rig scene"
  );
  const articulated = tracks.filter(track => track.property === "transform");
  const target = (scene, role) => scene + "-violin-prince-part-" + role;
  const hasChangingTrack = id => articulated.some(track =>
    track.target === id && track.values.some(value => value !== track.values[0])
  );

  assert.ok(hasChangingTrack(target("scene-head-turn", "head")),
    "head-turn scene must animate the separated head layer");
  assert.ok(hasChangingTrack(target("scene-head-turn", "face")),
    "face cut-out must follow the head around the neck pivot");
  assert.ok(hasChangingTrack("scene-head-turn-violin-prince-expression-neutral"),
    "expression overlay must follow the head around the neck pivot");
  assert.ok(hasChangingTrack(target("scene-head-turn", "torso")),
    "head-turn scene must counterbalance the torso");
  assert.ok(hasChangingTrack(target("scene-wave", "right_upper_arm")),
    "wave scene must animate the right upper arm");
  assert.ok(hasChangingTrack(target("scene-wave", "right_forearm")),
    "wave scene must animate the right forearm independently");
  assert.ok(hasChangingTrack(target("scene-explain", "left_upper_arm")));
  assert.ok(hasChangingTrack(target("scene-explain", "right_upper_arm")));
  assert.ok(hasChangingTrack(target("scene-body", "torso")));
});
