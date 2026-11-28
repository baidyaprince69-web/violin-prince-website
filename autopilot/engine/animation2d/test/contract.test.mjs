import test from "node:test";
import assert from "node:assert/strict";
import { clampTime, gestureKeyframes } from "../src/contract.mjs";
import { sampleMotionSpring, compileMotionTracks, buildMusicSynchronizedPerformanceTracks } from "../src/motion-build.mjs";

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
  assert.ok(amplitude("torso") >= 3, "torso sway should be visible in a full-body performance");
  assert.ok(amplitude("head") >= 2, "head follow-through should read at full-body scale");
  assert.ok(amplitude("left_forearm") >= 18, "left elbow flex should be visible but controlled");
  assert.ok(amplitude("right_forearm") >= 14, "right elbow flex should be visible but controlled");
  assert.ok(amplitude("left_hand") >= 2, "left wrist should have a distinct cue");
  assert.ok(amplitude("right_hand") >= 3, "right wrist should have a distinct cue");
  assert.ok(amplitude("left_calf") >= 4, "left knee should articulate");
  assert.ok(amplitude("right_calf") >= 4, "right knee should articulate");
  assert.ok(amplitude("left_foot") >= 2, "left ankle should articulate");
  assert.ok(amplitude("right_foot") >= 2, "right ankle should articulate");
});

test("audio-synchronised violin performance has readable bow, torso and weight-shift amplitude", () => {
  const tracks = buildMusicSynchronizedPerformanceTracks({
    targetPrefix: "performance-violin-prince",
    duration: 8,
    bpm: 80,
    beatTimes: [0, .75, 1.5, 2.25, 3, 3.75, 4.5, 5.25, 6, 6.75, 7.5],
    downbeats: [0, 3, 6],
    onsets: [0, 1.5, 2.25, 3, 4.5, 5.25, 6, 7.5],
    noteEvents: [
      {time:0,note:66,velocity:60,duration_seconds:1.5},
      {time:1.5,note:69,velocity:58,duration_seconds:.75},
      {time:2.25,note:71,velocity:64,duration_seconds:.75},
      {time:3,note:73,velocity:72,duration_seconds:1.5},
      {time:4.5,note:76,velocity:78,duration_seconds:.75},
      {time:5.25,note:74,velocity:66,duration_seconds:.75},
      {time:6,note:73,velocity:64,duration_seconds:1.5},
      {time:7.5,note:71,velocity:58,duration_seconds:.75}
    ],
    confidence: 1,
    timingSource: "sampled_violin_cc0",
    fps: 25
  });
  const peak = role => {
    const track = tracks.find(item => item.target === "performance-violin-prince-part-" + role);
    assert.ok(track, "missing synchronised track for " + role);
    return Math.max(...track.values.map(value => Math.abs(Number(value))));
  };
  assert.equal(tracks.length, 23);
  assert.equal(tracks.filter(track => track.music_sync_event === "performer_bow_stroke").length, 3,
    "bow-stroke cues should animate the connected shoulder, elbow and wrist chain");
  assert.equal(tracks.filter(track =>
    track.target === "performance-violin-prince-prop-bow"
  ).length, 0, "the bow prop must not receive a separate motion track outside its hand attachment");
  assert.ok(peak("left_upper_arm") >= 6.0 && peak("left_upper_arm") <= 7.0, "bow shoulder should visibly reciprocate without pulling the sleeve away from the source silhouette");
  assert.ok(peak("left_forearm") >= 6.8 && peak("left_forearm") <= 8.2, "bow elbow should reciprocate within the connected-source-art range");
  assert.ok(peak("torso") >= 2.5 && peak("torso") <= 3.3, "torso should follow the phrase with restrained source-safe sway");
  assert.ok(peak("head") >= 1.4, "head should follow the torso with a slight delay");
  assert.ok(peak("left_thigh") >= 4.0 && peak("left_thigh") <= 5.0, "left thigh should show restrained weight transfer");
  assert.ok(peak("left_calf") >= 2.7 && peak("left_calf") <= 3.5, "left calf should counterbalance without opening the source silhouette");
  assert.ok(peak("left_foot") >= 1.3 && peak("left_foot") <= 1.7, "left foot should participate in restrained weight transfer");
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
