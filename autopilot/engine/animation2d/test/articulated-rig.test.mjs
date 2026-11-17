import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { compileMotionTracks } from "../src/motion-build.mjs";

const character = {
  id: "violin-prince",
  layers: [
    { id: "torso", role: "torso" },
    { id: "head", role: "head" },
    { id: "left_upper_arm", role: "left_upper_arm" },
    { id: "left_forearm", role: "left_forearm" },
    { id: "left_hand", role: "left_hand" },
    { id: "right_upper_arm", role: "right_upper_arm" },
    { id: "right_forearm", role: "right_forearm" },
    { id: "right_hand", role: "right_hand" }
  ],
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
    scenes: [{ id: sceneId, start: 0, duration: 1.5 }],
    characters: [character]
  }).filter(track => track.property === "rotate");
}

test("head rotation and torso counterbalance target independent rig layers", () => {
  const tracks = tracksFor("head-test");
  assert.ok(tracks.some(track => track.target === "head-test-violin-prince-part-head"));
  assert.ok(tracks.some(track => track.target === "head-test-violin-prince-part-torso"));
  assert.ok(tracks.every(track => track.values.every(value => String(value).endsWith("deg"))));
});

test("wave gesture rotates the upper arm and forearm on separate pivots", () => {
  const targets = new Set(tracksFor("wave-test").map(track => track.target));
  assert.ok(targets.has("wave-test-violin-prince-part-right_upper_arm"));
  assert.ok(targets.has("wave-test-violin-prince-part-right_forearm"));
  assert.ok(targets.has("wave-test-violin-prince-part-right_hand"),
    "wave must articulate the wrist/hand independently");
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
  const rotating = tracks.filter(track => track.property === "rotate");
  const target = (scene, role) => scene + "-violin-prince-part-" + role;
  const hasChangingTrack = id => rotating.some(track =>
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
