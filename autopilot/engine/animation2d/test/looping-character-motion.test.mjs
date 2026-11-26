import test from "node:test";
import assert from "node:assert/strict";
import { compileMotionTracks } from "../src/motion-build.mjs";

const performer = {
  id: "performer",
  canvas: { width: 100, height: 100 },
  layers: [
    { id: "torso", role: "torso", x: 20, y: 20, width: 60, height: 70, pivot_x: .5, pivot_y: .5 },
    { id: "right-upper", role: "right_upper_arm", x: 60, y: 35, width: 20, height: 30, pivot_x: .5, pivot_y: .2 },
    { id: "right-forearm", role: "right_forearm", x: 68, y: 55, width: 22, height: 25, pivot_x: .2, pivot_y: .2 },
    { id: "right-hand", role: "right_hand", x: 80, y: 72, width: 15, height: 15, pivot_x: .2, pivot_y: .3 }
  ],
  joints: {
    neck: { x: .5, y: .36 },
    right_shoulder: { x: .65, y: .43 },
    right_elbow: { x: .76, y: .61 },
    right_wrist: { x: .87, y: .76 }
  },
  expressions: {}
};

test("looped violin-bow joints repeat on cycle boundaries and root motion loops", () => {
  const project = {
    duration_seconds: 6,
    fps: 25,
    scenes: [{ id: "performance", start: 0, duration: 6, character_actions: {
      performer: {
        visible: true,
        gesture: "violin_bow",
        expression: "neutral",
        loop: true,
        cycle_duration_seconds: 1.5,
        root_motion: { type: "sway", intensity: .35 }
      }
    }}],
    characters: [performer]
  };
  const tracks = compileMotionTracks(project, { fps: 25 });
  const arm = tracks.find(track =>
    track.target === "performance-performer-part-right-upper" && track.property === "transform"
  );
  assert.ok(arm, "the violin-bow gesture must generate an articulated upper-arm transform");
  // Samples 75 frames apart represent exactly 3 seconds, or two 1.5s cycles.
  assert.equal(arm.values[5], arm.values[80], "the articulated pose must repeat after two cycles");

  const root = tracks.find(track =>
    track.target === "performance-performer-motion" && track.property === "transform"
  );
  assert.ok(root, "root travel must target the separate inner character motion group");
  assert.equal(root.loop, true);
  assert.equal(root.duration, 1.5);
});

test("non-looped gestures still settle rather than wrapping", () => {
  const project = {
    duration_seconds: 4,
    fps: 25,
    scenes: [{ id: "single", start: 0, duration: 4, character_actions: {
      performer: { visible: true, gesture: "wave", duration: 1.2 }
    }}],
    characters: [performer]
  };
  const tracks = compileMotionTracks(project, { fps: 25 });
  const arm = tracks.find(track =>
    track.target === "single-performer-part-right-upper" && track.property === "transform"
  );
  assert.ok(arm);
  assert.notEqual(arm.values[10], arm.values[0], "the gesture must visibly move during its active interval");
  assert.equal(arm.values[35], arm.values.at(-1), "the non-looping gesture must settle at its final pose");
  assert.equal(arm.duration, 4);
});


test("intact source composites can use a low-amplitude, non-puppet sway", () => {
  const project = {
    duration_seconds: 4,
    fps: 25,
    scenes: [{ id: "composite", start: 0, duration: 4, character_actions: {
      performer: {
        visible: true,
        root_motion: {
          type: "sway",
          intensity: 0.1,
          distance_px: 2,
          rotation_deg: 0.18
        }
      }
    }}],
    characters: [performer]
  };
  const tracks = compileMotionTracks(project, { fps: 25 });
  const root = tracks.find(track =>
    track.target === "composite-performer-motion" && track.property === "transform"
  );
  assert.ok(root, "the source composite should retain one whole-character motion track");
  assert.ok(
    root.values.some(value => String(value).includes("translateX(-0.7px) rotate(-0.18deg)")),
    "the left sway should stay within the configured low-amplitude range"
  );
  assert.ok(
    root.values.some(value => String(value).includes("translateX(0.7px) rotate(0.18deg)")),
    "the right sway should stay within the configured low-amplitude range"
  );
});
