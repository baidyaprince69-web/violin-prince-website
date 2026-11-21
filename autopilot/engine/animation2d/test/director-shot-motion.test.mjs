import test from "node:test";
import assert from "node:assert/strict";
import {
  directorCameraKeyframes,
  directorTransitionSpec,
  compileMotionTracks
} from "../src/motion-build.mjs";

test("Master Director camera vocabulary produces distinct directed frame moves", () => {
  const movements = [
    "dolly_in", "dolly_out", "truck_left", "truck_right", "pan", "tilt",
    "orbit", "crane_up", "crane_down", "whip_pan", "controlled_handheld",
    "arc", "parallax_track", "tracking", "zoom_in", "zoom_out", "locked_off"
  ];
  const frames = movements.map((movement) => directorCameraKeyframes({
    movement,
    shot_size: "close_up"
  }));
  assert.equal(frames.length, movements.length);
  assert.ok(frames.every((value) => Array.isArray(value) && value.length >= 2));
  assert.ok(new Set(frames.map((value) => JSON.stringify(value))).size >= 12);
  assert.ok(directorCameraKeyframes({movement:"zoom_in",shot_size:"macro"})[0]
    .includes("scale(1.140)"));
  assert.throws(
    () => directorCameraKeyframes({movement:"teleport",shot_size:"wide"}),
    /Unsupported Master Director camera movement/
  );
});

test("Master Director transition names map to explicit Motion properties", () => {
  assert.equal(directorTransitionSpec("dissolve", 0.36).property, "opacity");
  assert.equal(directorTransitionSpec("whip_pan", 0.36).property, "filter");
  assert.equal(directorTransitionSpec("luma_wipe", 0.36).property, "clipPath");
  assert.equal(directorTransitionSpec("shape_match", 0.36).property, "clipPath");
  assert.equal(directorTransitionSpec("foreground_wipe", 0.36).property, "clipPath");
  assert.deepEqual(directorTransitionSpec("cut", 0), {
    property:"opacity", values:[1,1], easing:"linear"
  });
  assert.throws(
    () => directorTransitionSpec("morph_cut", 0.36),
    /Unsupported Master Director transition/
  );
});

test("shot projects compile the director transition and camera timing into frame tracks", () => {
  const project = {
    duration_seconds: 8,
    scenes: [{
      id: "shot-02",
      start: 3.64,
      duration: 4.36,
      visual_mode: "director_shot",
      transition_in: "shape_match",
      transition_in_duration: 0.36,
      camera_motion_start_offset: 0.36,
      camera_motion_duration: 4,
      camera_easing: "ease-in-out",
      director_camera: {movement:"dolly_in",shot_size:"macro"}
    }],
    characters: []
  };
  const tracks = compileMotionTracks(project, {fps:25});
  const background = tracks.filter((track) => track.target === "shot-02-background");
  assert.ok(background.some((track) => track.property === "clipPath"));
  assert.ok(background.some((track) => track.property === "opacity" &&
    track.values[0] === 1 && track.values.at(-1) === 1));
  const camera = background.find((track) => track.property === "transform");
  assert.ok(camera);
  assert.equal(camera.start, 4);
  assert.equal(camera.duration, 4);
  assert.ok(camera.values.at(-1).includes("scale(1.225)"));
});
