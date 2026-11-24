import test from "node:test";
import assert from "node:assert/strict";
import { clampTime, gestureKeyframes } from "../src/contract.mjs";
import { sampleMotionSpring, compileMotionTracks } from "../src/motion-build.mjs";

test("frame seek time is finite and clamped to the composition", () => {
  assert.equal(clampTime(-2, 4), 0);
  assert.equal(clampTime(2.5, 4), 2.5);
  assert.equal(clampTime(9, 4), 4);
  assert.equal(clampTime(Number.NaN, 4), 0);
});

test("Motion build-time spring samples are finite and repeatable", () => {
  const first = sampleMotionSpring(0, 100, 25, 900);
  const second = sampleMotionSpring(0, 100, 25, 900);
  assert.deepEqual(first, second);
  assert.ok(first.values.length >= 2);
  assert.equal(first.values[0], 0);
  assert.ok(first.values.every(Number.isFinite));
  assert.ok(Math.abs(first.values.at(-1) - 100) < 1);
  assert.ok(first.duration > 0);
});

test("scene and character animations compile to native WAAPI tracks", () => {
  const project = {
    scenes: [{
      id: "scene-one", start: 0, duration: 4,
      character_actions: {
        guide: { gesture: "wave", expression: "curious", duration: 1.2 }
      }
    }],
    characters: [{
      id: "guide",
      layers: [
        { id: "right-arm", role: "right_upper_arm" },
        { id: "right-forearm", role: "right_forearm" },
        { id: "face", role: "face" }
      ],
      expressions: { neutral: {}, curious: {} },
      poses: {},
      gestures: {}
    }]
  };
  const tracks = compileMotionTracks(project, { fps: 25 });
  assert.ok(tracks.some(track => track.target === "scene-one-background" && track.property === "opacity"));
  assert.ok(tracks.some(track => track.target === "scene-one-guide-part-right-arm" && track.property === "transform"));
  assert.ok(tracks.some(track => track.target === "scene-one-guide-expression-curious"));
  assert.ok(tracks.every(track => track.values.length >= 2 && track.duration > 0));
});

test("violin performance has controlled articulation at elbow, wrist, knee and ankle joints", () => {
  const performance = gestureKeyframes("violin_performance");
  const amplitude = role => Math.max(...performance[role].rotate.map(value => Math.abs(value)));
  assert.ok(amplitude("left_forearm") >= 12, "left elbow flex should be visible but restrained");
  assert.ok(amplitude("right_forearm") >= 10, "right elbow flex should be visible but restrained");
  assert.ok(amplitude("left_hand") >= 2, "left wrist should have a distinct cue");
  assert.ok(amplitude("right_hand") >= 3, "right wrist should have a distinct cue");
  assert.ok(amplitude("left_calf") >= 2.5, "left knee should articulate");
  assert.ok(amplitude("right_calf") >= 2.5, "right knee should articulate");
  assert.ok(amplitude("left_foot") >= 1.2, "left ankle should articulate");
  assert.ok(amplitude("right_foot") >= 1.2, "right ankle should articulate");
});

test("gesture presets include arms and head movement", () => {
  const wave = gestureKeyframes("wave");
  assert.ok(wave.right_upper_arm);
  assert.ok(wave.right_forearm);
  assert.ok(gestureKeyframes("nod").head);
  assert.deepEqual(gestureKeyframes("unknown"), {});
  for (const name of ["idle_breath", "talking", "violin_bow", "walk_cycle", "dance_groove"]) {
    assert.ok(Object.keys(gestureKeyframes(name)).length >= 2, name + " should animate multiple rig parts");
  }
});
