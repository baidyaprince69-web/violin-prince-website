import test from "node:test";
import assert from "node:assert/strict";
import { compileMotionTracks } from "../src/motion-build.mjs";

const roles = [
  "torso", "head", "face",
  "left_upper_arm", "left_forearm", "left_hand",
  "right_upper_arm", "right_forearm", "right_hand",
  "left_thigh", "left_calf", "left_foot",
  "right_thigh", "right_calf", "right_foot",
  "finger_index", "finger_middle", "finger_ring", "finger_little"
];

const jointNames = [
  "neck", "left_shoulder", "left_elbow", "left_wrist",
  "right_shoulder", "right_elbow", "right_wrist",
  "left_hip", "left_knee", "left_ankle",
  "right_hip", "right_knee", "right_ankle",
  "right_index_base", "right_middle_base", "right_ring_base", "right_little_base"
];

const character = {
  id: "violin-prince",
  canvas: { width: 441, height: 755 },
  layers: roles.map((role, index) => ({
    id: role, role, src: role + ".png",
    x: 80 + (index % 5) * 12, y: 80 + (index % 7) * 16,
    width: 36, height: 48, pivot_x: .5, pivot_y: .5
  })),
  joints: Object.fromEntries(jointNames.map((name, index) => [
    name, { x: .2 + (index % 6) * .12, y: .2 + (index % 7) * .1 }
  ])),
  expressions: { neutral: { src: "neutral.png" } },
  props: {
    violin: {
      id: "violin", src: "violin.webp",
      x: 170, y: 116, width: 263, height: 110,
      pivot_x: .22, pivot_y: .5, z_index: 25, attach_to: "torso"
    },
    bow: {
      id: "bow", src: "bow.webp",
      x: 173, y: 39, width: 172, height: 254,
      pivot_x: .035, pivot_y: .976, z_index: 35, attach_to: "right_hand"
    }
  }
};

const project = {
  width: 720, height: 1280, fps: 25, duration_seconds: 4,
  scenes: [{
    id: "playing", start: 0, duration: 4,
    character_actions: {
      "violin-prince": {
        gesture: "violin_performance",
        instrument_performance: true,
        loop: true,
        cycle_duration_seconds: 2,
        prop_keyframes: {
          bow: {
            rotate: [0, -3.5, 3.5, -3.5, 3.5, 0],
            translate: [
              "-18px -4px", "18px 4px", "-18px -4px",
              "18px 4px", "-18px -4px", "0px 0px"
            ]
          },
          violin: { rotate: [0, -0.45, 0.35, 0.45, 0] }
        }
      }
    }
  }],
  characters: [character]
};

test("full-body gesture animates thigh, knee, ankle and all four fingering controls", () => {
  const tracks = compileMotionTracks(project, { fps: 25 });
  const changed = new Set(tracks
    .filter(track => track.property === "transform" &&
      track.values.some(value => value !== track.values[0]))
    .map(track => track.target));
  for (const role of [
    "left_thigh", "left_calf", "left_foot",
    "right_thigh", "right_calf", "right_foot",
    "finger_index", "finger_middle", "finger_ring", "finger_little"
  ]) {
    assert.ok(changed.has("playing-violin-prince-part-" + role), role + " should have its own changing transform track");
  }
});

test("violin and bow are separately transformed and bow receives a stroke cycle", () => {
  const tracks = compileMotionTracks(project, { fps: 25 });
  for (const id of ["violin", "bow"]) {
    const track = tracks.find(item =>
      item.target === "playing-violin-prince-prop-" + id &&
      item.property === "transform"
    );
    assert.ok(track, id + " must receive an attachment-aware transform");
    assert.ok(track.values.some(value => value !== track.values[0]),
      id + " must move independently with its attachment and performance cue");
  }
  const bow = tracks.find(item => item.target === "playing-violin-prince-prop-bow" && item.property === "transform");
  assert.ok(bow.values.length > 20, "bow stroke is frame-sampled for smooth HyperFrames seeking");
  const bowTranslation = tracks.find(item =>
    item.target === "playing-violin-prince-prop-bow" &&
    item.property === "translate"
  );
  assert.ok(bowTranslation, "bow receives an explicit reciprocal translation along the strings");
  assert.ok(bowTranslation.values.some(value => value !== bowTranslation.values[0]),
    "bow translation must change during each stroke");
});
