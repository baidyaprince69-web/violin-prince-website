import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  buildMusicSynchronizedPerformanceTracks,
  compileMotionTracks,
  mapViolinFirstPositionPitch
} from "../src/motion-build.mjs";
import { fitCharacterToCanvas } from "../src/character-layout.mjs";

const rendererSource = readFileSync(new URL("../build.mjs", import.meta.url), "utf8");

test("violin MIDI pitches resolve to standard-tuning strings and first-position fingers", () => {
  assert.equal(mapViolinFirstPositionPitch(55).status, "open_string");
  assert.equal(mapViolinFirstPositionPitch(55).string, "G");
  assert.equal(mapViolinFirstPositionPitch(62).string, "D");
  assert.equal(mapViolinFirstPositionPitch(64).finger, "finger_index");
  assert.equal(mapViolinFirstPositionPitch(67).finger, "finger_ring");
  assert.equal(mapViolinFirstPositionPitch(72).finger, "finger_middle");
  assert.equal(mapViolinFirstPositionPitch(83).finger, "finger_little");
  assert.equal(mapViolinFirstPositionPitch(54).status, "outside_first_position");
  assert.equal(mapViolinFirstPositionPitch(84).status, "outside_first_position");
});

test("notes outside first position are flagged without inventing a finger", () => {
  const tracks = buildMusicSynchronizedPerformanceTracks({
    targetPrefix: "fingering-boundary",
    duration: 2,
    bpm: 120,
    beatTimes: [0, 0.5, 1, 1.5],
    noteEvents: [
      { time: 0.25, note: 84, velocity: 70, duration_seconds: 0.5 },
      { time: 1.25, note: 54, velocity: 70, duration_seconds: 0.5 }
    ],
    confidence: 1
  });
  const index = tracks.find(track => track.target === "fingering-boundary-part-finger_index");
  assert.ok(index);
  assert.equal(index.music_sync_fingering_summary.status, "manual_review_required");
  assert.equal(index.music_sync_fingering_summary.unsupported_note_count, 2);
  assert.deepEqual(index.music_sync_fingering_map.map(item => item.finger), [null, null]);
  assert.ok(index.values.every(value => value === 0),
    "unsupported positions must not be assigned to a guessed first-position finger");
});

test("precomputed articulated matrices retain the sprite-origin CSS transform origin", () => {
  assert.match(
    rendererSource,
    /"transform-origin:0 0"/,
    "joint compensation is already encoded in layer-local matrices; CSS must not apply a second pivot"
  );
});


const roles = [
  "torso", "head", "face",
  "left_upper_arm", "left_forearm", "left_hand",
  "right_upper_arm", "right_forearm", "right_hand",
  "left_thigh", "left_calf", "left_foot",
  "right_thigh", "right_calf", "right_foot",
  "finger_index", "finger_index_middle", "finger_index_tip",
  "finger_middle", "finger_middle_middle", "finger_middle_tip",
  "finger_ring", "finger_ring_middle", "finger_ring_tip",
  "finger_little", "finger_little_middle", "finger_little_tip"
];

const jointNames = [
  "neck", "left_shoulder", "left_elbow", "left_wrist",
  "right_shoulder", "right_elbow", "right_wrist",
  "left_hip", "left_knee", "left_ankle",
  "right_hip", "right_knee", "right_ankle",
  "right_index_base", "right_index_pip", "right_index_dip",
  "right_middle_base", "right_middle_pip", "right_middle_dip",
  "right_ring_base", "right_ring_pip", "right_ring_dip",
  "right_little_base", "right_little_pip", "right_little_dip"
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
  head_variants: Object.fromEntries(["happy", "focused", "surprised", "neutral"].map(name => [
    name, { src: "head-variant-" + name + ".png", x: 120, y: 20, width: 80, height: 100, pivot_x: .5, pivot_y: .92 }
  ])),
  head_angles: Object.fromEntries(["front", "three_quarter", "profile_right", "profile_left"].map(name => [
    name, { src: "head-angle-" + name + ".png", x: 120, y: 20, width: 80, height: 100, pivot_x: .5, pivot_y: .92 }
  ])),
  props: {
    violin: {
      id: "violin", src: "violin.webp",
      x: 170, y: 116, width: 263, height: 110,
      pivot_x: .22, pivot_y: .5, z_index: 25, attach_to: "torso"
    },
    bow: {
      id: "bow", src: "bow.webp",
      x: 173, y: 39, width: 172, height: 254,
      pivot_x: .035, pivot_y: .976, z_index: 35, attach_to: "left_hand",
      stroke_axis: { x: 0.58, y: -0.81 }
    }
  }
};

const bowHandFixture = character.layers.find(layer => layer.role === "left_hand");
Object.assign(bowHandFixture, { x: 107, y: 222, width: 90, height: 59, pivot_x: 0.5, pivot_y: 0.5 });
Object.assign(character.joints, {
  left_shoulder: { x: 127 / 441, y: 176 / 755 },
  left_elbow: { x: 27 / 441, y: 252 / 755 },
  left_wrist: { x: 116 / 441, y: 231 / 755 }
});
Object.assign(character.props.bow, {
  x: 147, y: 44, width: 191, height: 254,
  pivot_x: 0.1623036649, pivot_y: 0.78,
  stroke_axis: { x: 0.627793, y: -0.77838 }
});

const project = {
  width: 720, height: 1280, fps: 25, duration_seconds: 4,
  scenes: [{
    id: "playing", start: 0, duration: 4,
    character_actions: {
      "violin-prince": {
        gesture: "violin_performance",
        instrument_performance: true,
        expression: "focused",
        head_angle: "front",
        head_angle_sequence: ["front", "three_quarter", "profile_right", "profile_left", "front"],
        head_angle_cycle_duration_seconds: 3,
        loop: true,
        cycle_duration_seconds: 2,
      }
    }
  }],
  characters: [character]
};

test("body and joint surfaces use source image sprites with hierarchical blended transforms", () => {
  const spriteProject = structuredClone(project);
  const spriteCharacter = spriteProject.characters[0];
  spriteCharacter.layers.push({
    id: "joint_surface_left_knee",
    role: "joint_surface_left_knee",
    src: "joint_surface_left_knee.png",
    x: 92, y: 540, width: 48, height: 48,
    pivot_x: 0.5, pivot_y: 0.5, z_index: 12,
    joint_surface: {
      joint: "left_knee",
      parent_role: "left_thigh",
      child_role: "left_calf",
      blend_weight: 0.5,
      blend_axis_start: [0.263, 0.689],
      blend_axis_end: [0.263, 0.808]
    }
  });
  for (const layer of spriteCharacter.layers) delete layer.mesh_deformation;

  const tracks = compileMotionTracks(spriteProject, { fps: 25 });
  const find = target => tracks.find(track =>
    track.target === target && track.property === "transform"
  );
  for (const role of [
    "torso", "left_upper_arm", "left_forearm", "left_hand",
    "right_upper_arm", "right_forearm", "right_hand",
    "left_thigh", "left_calf", "left_foot",
    "right_thigh", "right_calf", "right_foot"
  ]) {
    const track = find("playing-violin-prince-part-" + role);
    assert.ok(track?.values.some(value => value !== track.values[0]),
      role + " must receive a changing hierarchical image-sprite transform");
  }
  for (const role of [
    "finger_index", "finger_index_middle", "finger_index_tip",
    "finger_middle", "finger_middle_middle", "finger_middle_tip",
    "finger_ring", "finger_ring_middle", "finger_ring_tip",
    "finger_little", "finger_little_middle", "finger_little_tip"
  ]) {
    const track = find("playing-violin-prince-part-" + role);
    assert.ok(track?.values.some(value => value !== track.values[0]),
      role + " must remain independently articulated as a source image sprite");
  }
  const jointTransform = find("playing-violin-prince-part-joint_surface_left_knee");
  assert.ok(jointTransform?.values.some(value => value !== jointTransform.values[0]),
    "the knee patch must follow the parent/child blended rigid transform");
  assert.equal(tracks.some(track => track.target.includes("-mesh-triangle-")), false,
    "the character's source artwork must not be rasterized through SVG mesh triangles");
  assert.equal(spriteCharacter.layers.some(layer => layer.mesh_deformation), false,
    "all character layers must remain normal source image sprites");
});

test("waist and neck-support reference layers inherit their parent body transforms", () => {
  const candidateProject = structuredClone(project);
  candidateProject.characters[0].layers.push(
    {
      id: "waist", role: "waist", src: "waist.png",
      x: 100, y: 370, width: 120, height: 48,
      pivot_x: .5, pivot_y: .5, z_index: 30
    },
    {
      id: "neck_bridge", role: "neck_bridge", src: "neck-bridge.png",
      x: 116, y: 132, width: 127, height: 66,
      pivot_x: .5, pivot_y: .03, z_index: 45
    }
  );
  const tracks = compileMotionTracks(candidateProject, { fps: 25 });
  const find = role => tracks.find(track =>
    track.target === "playing-violin-prince-part-" + role &&
    track.property === "transform"
  );
  for (const role of ["waist", "neck_bridge"]) {
    const track = find(role);
    assert.ok(track, role + " must receive a hierarchical transform track");
    assert.ok(track.values.some(value => value !== track.values[0]),
      role + " must follow its torso/head parent motion");
  }
});

test("full-body performance can be fully visible on the first composition frame", () => {
  const immediateProject = structuredClone(project);
  const action = immediateProject.scenes[0].character_actions["violin-prince"];
  action.visible = true;
  action.start_offset = 0;
  action.appear_immediately = true;
  // The production preview intentionally starts from a fixed front/focused plate.
  // Sequence transitions are tested separately; this asserts the static entry path.
  delete action.head_angle_sequence;
  delete action.head_expression_sequence;

  const tracks = compileMotionTracks(immediateProject, { fps: 25 });
  const opacityTrack = tracks.find(track =>
    track.target === "playing-violin-prince" && track.property === "opacity"
  );

  assert.ok(opacityTrack, "the presenter must receive an explicit opacity track");
  assert.deepEqual(opacityTrack.values, [1, 1],
    "the first keyframe must be fully opaque rather than starting at zero");
  assert.equal(opacityTrack.start, 0,
    "the fully visible presenter track must start at time zero");
  assert.equal(opacityTrack.duration, 0.08,
    "immediate visibility should use a minimal constant-opacity track");

  const focusedHeadPlate = tracks.find(track =>
    track.target === "playing-violin-prince-head-variant-focused" &&
    track.property === "opacity"
  );
  const inactiveHeadPlate = tracks.find(track =>
    track.target === "playing-violin-prince-head-variant-neutral" &&
    track.property === "opacity"
  );
  assert.deepEqual(focusedHeadPlate?.values, [1, 1],
    "the selected head plate must be fully opaque on frame zero");
  assert.deepEqual(inactiveHeadPlate?.values, [0, 0],
    "unselected head plates must be hidden on frame zero");

  const legacyTracks = compileMotionTracks(project, { fps: 25 });
  const legacyOpacity = legacyTracks.find(track =>
    track.target === "playing-violin-prince" && track.property === "opacity"
  );
  assert.ok(legacyOpacity);
  assert.equal(legacyOpacity.values[0], 0,
    "presenters without the immediate-visibility flag retain their normal entrance fade");
  assert.equal(legacyOpacity.values.at(-1), 1);
});

test("music-synchronized performance keyframes follow beat and onset timestamps", () => {
  const tracks = buildMusicSynchronizedPerformanceTracks({
    targetPrefix: "playing-violin-prince",
    start: 0.12,
    duration: 3.88,
    bpm: 120,
    beatTimes: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5],
    downbeats: [0, 2],
    onsets: [0.25, 0.75, 1.25, 1.75, 2.25],
    noteEvents: [
      { time: 0.25, note: 62, velocity: 60, duration_seconds: 0.75 },
      { time: 0.75, note: 67, velocity: 64, duration_seconds: 0.75 },
      { time: 1.25, note: 72, velocity: 78, duration_seconds: 1.5 },
      { time: 1.75, note: 77, velocity: 88, duration_seconds: 0.75 },
      { time: 2.25, note: 83, velocity: 92, duration_seconds: 0.65 }
    ],
    bowTravelAxis: { x: 0.58, y: -0.81 },
    confidence: 1
  });
  const find = target => tracks.find(track => track.target === target);
  const bowPropMotionTracks = tracks.filter(track =>
    track.target === "playing-violin-prince-prop-bow"
  );
  const bowShoulder = find("playing-violin-prince-part-left_upper_arm");
  const elbow = find("playing-violin-prince-part-left_forearm");
  const wrist = find("playing-violin-prince-part-left_hand");
  const torso = find("playing-violin-prince-part-torso");
  const head = find("playing-violin-prince-part-head");
  const leftThigh = find("playing-violin-prince-part-left_thigh");
  const leftCalf = find("playing-violin-prince-part-left_calf");
  const fingerboardArmTracks = tracks.filter(track =>
    /playing-violin-prince-part-right_(upper_arm|forearm|hand)$/.test(track.target)
  );
  const indexFinger = find("playing-violin-prince-part-finger_index");
  const middleFinger = find("playing-violin-prince-part-finger_middle");
  const ringFinger = find("playing-violin-prince-part-finger_ring");
  const littleFinger = find("playing-violin-prince-part-finger_little");

  assert.ok(bowShoulder && elbow && wrist);
  assert.equal(bowPropMotionTracks.length, 0,
    "the bow must not receive an independent rotation or translation that can break its grip");
  assert.equal(tracks.filter(track => track.music_sync_event === "performer_bow_stroke").length, 3,
    "the three bow-stroke cues belong to the shoulder, elbow and wrist chain");
  assert.equal(fingerboardArmTracks.length, 0,
    "the violin-neck arm must not drift away from its contact point");
  assert.ok(indexFinger && middleFinger && ringFinger && littleFinger);
  const noteAssignments = indexFinger.music_sync_fingering_map;
  assert.deepEqual(noteAssignments.map(item => item.status),
    ["open_string", "first_position", "first_position", "first_position", "first_position"]);
  assert.deepEqual(noteAssignments.map(item => item.string), ["D", "D", "A", "E", "E"]);
  assert.deepEqual(noteAssignments.map(item => item.finger),
    [null, "finger_ring", "finger_middle", "finger_index", "finger_little"]);
  assert.equal(indexFinger.music_sync_fingering_summary.status, "first_position_mapped");
  assert.equal(indexFinger.music_sync_fingering_summary.open_string_note_count, 1);
  assert.equal(bowShoulder.music_sync_event, "performer_bow_stroke");
  assert.equal(elbow.music_sync_event, "performer_bow_stroke");
  assert.equal(indexFinger.music_sync_event, "performer_finger_note");
  assert.equal(indexFinger.music_sync_timing_source, "validated_audio_event_map");
  assert.equal(tracks.filter(track => track.music_sync_event === "performer_bow_stroke").length, 4);
  assert.equal(tracks.filter(track => track.music_sync_event === "performer_finger_note").length, 12);
  assert.equal(tracks.filter(track => track.music_sync_event === "performer_weight_shift").length, 6);
  assert.ok(ringFinger.key_times.includes(0.768));
  assert.ok(middleFinger.key_times.includes(1.268));
  assert.ok(indexFinger.key_times.includes(1.768));
  assert.ok(littleFinger.key_times.includes(2.268));
  assert.ok(Math.max(...bowShoulder.values.map(Math.abs)) <= 7.0);
  assert.ok(Math.max(...elbow.values.map(Math.abs)) <= 8.2);
  assert.ok(Math.max(...torso.values.map(Math.abs)) <= 3.4 &&
    Math.max(...torso.values.map(Math.abs)) >= 2.5,
    "torso follow-through must remain subtle enough to preserve the single-pose source artwork");
  assert.ok(Math.max(...head.values.map(Math.abs)) <= 2.3 &&
    Math.max(...head.values.map(Math.abs)) >= 1.7,
    "head follow-through must stay restrained and visibly respond to the phrase");
  assert.ok(Math.max(...leftThigh.values.map(Math.abs)) <= 5.0 &&
    Math.max(...leftThigh.values.map(Math.abs)) >= 4.0,
    "weight transfer must remain small enough to keep the source silhouette connected");
  assert.ok(Math.max(...leftCalf.values.map(Math.abs)) <= 3.5 &&
    Math.max(...leftCalf.values.map(Math.abs)) >= 2.7,
    "lower-leg balance must remain subtle relative to the source pose");
  assert.ok(Math.max(...wrist.values.map(Math.abs)) <= 2.5);
  assert.ok(bowShoulder.values.some(value => Math.abs(value) >= 6.0));
  assert.ok(elbow.values.some(value => Math.abs(value) >= 6.8),
    "the forearm must continue contributing to each controlled bow stroke");
  assert.ok(wrist.values.some(value => Math.abs(value) >= 0.8));
  assert.equal(bowShoulder.values.length, elbow.values.length);
  assert.equal(elbow.values.length, wrist.values.length);
  assert.ok(bowShoulder.values.length > 12,
    "bow path should be smoothly sampled between beats instead of snapping at beats");
  for (let i = 0; i < bowShoulder.values.length; i += 1) {
    assert.ok(Math.abs(
      bowShoulder.values[i] + elbow.values[i] + wrist.values[i]
    ) < 1e-6, "the three joints should counter-rotate without changing bow angle");
  }

  assert.deepEqual(buildMusicSynchronizedPerformanceTracks({
    targetPrefix: "playing-violin-prince",
    bpm: 120,
    beatTimes: [0, 0.5, 1],
    confidence: 0.1
  }), [], "low-confidence audio analysis must not drive the rig");
});

test("compileMotionTracks consumes audio beat maps for bow, arm and finger motion", () => {
  const musicProject = structuredClone(project);
  musicProject.scenes[0].character_actions["violin-prince"].music_sync = {
    source: "decoded_audio_spectral_flux_autocorrelation",
    bpm: 120,
    confidence: 0.84,
    beat_times: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5],
    downbeats: [0, 2],
    onsets: [0.25, 0.75, 1.25, 1.75, 2.25, 2.75, 3.25],
    note_events: [
      { time: 0.25, note: 62, velocity: 60, duration_seconds: 0.75 },
      { time: 0.75, note: 65, velocity: 58, duration_seconds: 0.75 },
      { time: 1.25, note: 67, velocity: 64, duration_seconds: 0.75 },
      { time: 1.75, note: 69, velocity: 72, duration_seconds: 0.75 },
      { time: 2.25, note: 72, velocity: 78, duration_seconds: 0.75 },
      { time: 2.75, note: 70, velocity: 66, duration_seconds: 0.75 },
      { time: 3.25, note: 69, velocity: 70, duration_seconds: 0.75 }
    ]
  };

  const regularTracks = compileMotionTracks(project, { fps: 25 });
  const musicTracks = compileMotionTracks(musicProject, { fps: 25 });
  const getTrack = (tracks, target, property = "transform") =>
    tracks.find(track => track.target === target && track.property === property);

  for (const target of [
    "playing-violin-prince-prop-bow",
    "playing-violin-prince-part-left_upper_arm",
    "playing-violin-prince-part-left_forearm",
    "playing-violin-prince-part-left_hand",
    "playing-violin-prince-part-finger_index",
    "playing-violin-prince-part-finger_index_middle",
    "playing-violin-prince-part-finger_index_tip",
    "playing-violin-prince-part-finger_ring",
    "playing-violin-prince-part-finger_ring_middle",
    "playing-violin-prince-part-finger_ring_tip"
  ]) {
    const regular = getTrack(regularTracks, target);
    const synchronized = getTrack(musicTracks, target);
    assert.ok(regular && synchronized, target + " must compile in both modes");
    assert.notDeepEqual(synchronized.values, regular.values,
      target + " must use the audio event map instead of the generic loop");
  }

  const presenterSyncTracks = musicTracks.filter(track =>
    String(track.music_sync_event || "").startsWith("performer_")
  );
  assert.equal(presenterSyncTracks.length, 24,
    "all 23 measured presenter transforms must retain sync provenance after hierarchy compilation");
  assert.equal(presenterSyncTracks.filter(track =>
    track.music_sync_event === "performer_bow_stroke").length, 4);
  assert.equal(presenterSyncTracks.filter(track =>
    track.music_sync_event === "performer_finger_note").length, 12);
  assert.equal(presenterSyncTracks.filter(track =>
    track.music_sync_event === "performer_body_balance").length, 2);
  assert.equal(presenterSyncTracks.filter(track =>
    track.music_sync_event === "performer_weight_shift").length, 6);
  assert.ok(presenterSyncTracks.every(track =>
    track.property === "transform" &&
    track.music_sync_timing_source === "decoded_audio_spectral_flux_autocorrelation"
  ), "sync provenance must survive on all final frame-seekable presenter transforms");
  assert.equal(presenterSyncTracks.filter(track =>
    track.target === "playing-violin-prince-prop-bow" && track.property === "translate"
  ).length, 0, "the bow must not translate independently of the bowing hand");

  const bowTransform = getTrack(musicTracks, "playing-violin-prince-prop-bow", "transform");
  const bowHandTransform = getTrack(musicTracks, "playing-violin-prince-part-left_hand", "transform");
  assert.ok(bowTransform && bowTransform.values.some(value => value !== bowTransform.values[0]),
    "bow follows the articulated bowing-hand parent");
  assert.equal(bowTransform.music_sync_event, "performer_bow_stroke");
  assert.ok(bowHandTransform, "the hand transform is available for the grip-attachment check");

  const matrixPoint = (value, point, scale, layer) => {
    const match = String(value).match(/^matrix\(([^)]+)\)$/);
    assert.ok(match, "hierarchical transforms must be affine CSS matrices");
    const [a,b,c,d,e,f] = match[1].split(",").map(Number);
    return {
      x: Number(layer.x) * scale + a * point.x * scale + c * point.y * scale + e,
      y: Number(layer.y) * scale + b * point.x * scale + d * point.y * scale + f
    };
  };
  const character = project.characters[0];
  const bow = character.props.bow;
  const hand = character.layers.find(layer => layer.role === "left_hand");
  const scale = fitCharacterToCanvas(character, project.width, project.height).scale;
  const grip = { x: bow.pivot_x * bow.width, y: bow.pivot_y * bow.height };
  const handGrip = {
    x: bow.x + grip.x - hand.x,
    y: bow.y + grip.y - hand.y
  };
  const gripErrors = bowTransform.values.map((value, index) => {
    const bowPoint = matrixPoint(value, grip, scale, bow);
    const handPoint = matrixPoint(bowHandTransform.values[index], handGrip, scale, hand);
    return Math.hypot(bowPoint.x - handPoint.x, bowPoint.y - handPoint.y);
  });
  assert.ok(Math.max(...gripErrors) < 0.05,
    "the bow grip must stay locked to the same point on the bowing hand in every frame");

  const rawAxis = bow.stroke_axis;
  const axisLength = Math.hypot(rawAxis.x, rawAxis.y);
  const axis = { x: rawAxis.x / axisLength, y: rawAxis.y / axisLength };
  const limits = [];
  if (axis.x > 1e-6) limits.push((bow.width - grip.x) / axis.x);
  if (axis.x < -1e-6) limits.push((0 - grip.x) / axis.x);
  if (axis.y > 1e-6) limits.push((bow.height - grip.y) / axis.y);
  if (axis.y < -1e-6) limits.push((0 - grip.y) / axis.y);
  const tipDistance = Math.min(...limits.filter(value => Number.isFinite(value) && value > 0));
  const tip = { x: grip.x + axis.x * tipDistance, y: grip.y + axis.y * tipDistance };
  const tipPositions = bowTransform.values.map(value => matrixPoint(value, tip, scale, bow));
  const tipXRange = Math.max(...tipPositions.map(point => point.x)) - Math.min(...tipPositions.map(point => point.x));
  const tipYRange = Math.max(...tipPositions.map(point => point.y)) - Math.min(...tipPositions.map(point => point.y));
  assert.ok(Math.hypot(tipXRange, tipYRange) >= 26,
    "the attached bow tip must travel visibly through the arm chain across the strings");
});

test("sampled note pitches select finger layers and music cues counterbalance the full body", () => {
  const tracks = buildMusicSynchronizedPerformanceTracks({
    targetPrefix: "playing-violin-prince",
    duration: 3.8,
    bpm: 120,
    beatTimes: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5],
    downbeats: [0, 2],
    onsets: [0, 1, 2, 3],
    noteEvents: [
      { time: 0, note: 60, velocity: 65, duration_seconds: 0.5 },
      { time: 1, note: 64, velocity: 70, duration_seconds: 0.5 },
      { time: 2, note: 68, velocity: 75, duration_seconds: 0.5 },
      { time: 3, note: 72, velocity: 80, duration_seconds: 0.5 }
    ],
    confidence: 1
  });
  const targets = new Set(tracks.map(track => track.target));
  for (const role of [
    "left_upper_arm", "left_forearm", "left_hand",
    "torso", "head", "left_thigh", "right_thigh",
    "left_calf", "right_calf", "left_foot", "right_foot",
    "finger_index", "finger_index_middle", "finger_index_tip",
    "finger_middle", "finger_middle_middle", "finger_middle_tip",
    "finger_ring", "finger_ring_middle", "finger_ring_tip",
    "finger_little", "finger_little_middle", "finger_little_tip"
  ]) {
    assert.ok(targets.has("playing-violin-prince-part-" + role), role + " must receive its own synchronized cue");
  }
});

test("full-body gesture animates thigh, knee, ankle and all four fingering controls", () => {
  const tracks = compileMotionTracks(project, { fps: 25 });
  const changed = new Set(tracks
    .filter(track => track.property === "transform" &&
      track.values.some(value => value !== track.values[0]))
    .map(track => track.target));
  for (const role of [
    "left_thigh", "left_calf", "left_foot",
    "right_thigh", "right_calf", "right_foot",
    "finger_index", "finger_index_middle", "finger_index_tip",
    "finger_middle", "finger_middle_middle", "finger_middle_tip",
    "finger_ring", "finger_ring_middle", "finger_ring_tip",
    "finger_little", "finger_little_middle", "finger_little_tip"
  ]) {
    assert.ok(changed.has("playing-violin-prince-part-" + role), role + " should have its own changing transform track");
  }
});

test("violin stays torso-mounted and bow follows the bowing-hand chain", () => {
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
  const bowRotation = tracks.find(item =>
    item.target === "playing-violin-prince-prop-bow" &&
    item.property === "rotate"
  );
  assert.equal(bowTranslation, undefined,
    "bow position is inherited from the hand grip and arm pivots");
  assert.equal(bowRotation, undefined,
    "bow angle is inherited from the wrist instead of a second prop pivot");
});


test("intact full-body composite keeps limbs together while bow and fingers animate", () => {
  const compositeCharacter = {
    ...character,
    base_art: {
      src: "performance-composite-base.png",
      x: 0, y: 0, width: 441, height: 755,
      mode: "intact_full_body_with_bow_and_finger_cutouts"
    }
  };
  const compositeProject = {
    ...project,
    characters: [compositeCharacter]
  };
  const tracks = compileMotionTracks(compositeProject, { fps: 25 });
  const findTrack = (target, property = "transform") =>
    tracks.find(track => track.target === target && track.property === property);
  const base = findTrack("playing-violin-prince-base-art");
  assert.ok(base, "full-body composite base receives a coordinated transform track");
  assert.ok(base.values.some(value => value !== base.values[0]));

  const bow = findTrack("playing-violin-prince-prop-bow");
  assert.ok(bow, "bow remains aligned to its grip while following the intact body");
  assert.ok(bow.values.some(value => value !== bow.values[0]));
  assert.equal(findTrack("playing-violin-prince-prop-violin"), undefined,
    "the original violin stays in the preserved source illustration");

  const bowHand = findTrack("playing-violin-prince-part-left_hand");
  assert.ok(bowHand, "the original bow-grip hand remains aligned above the bow");
  assert.ok(bowHand.values.some(value => value !== bowHand.values[0]));

  for (const role of [
    "finger_index", "finger_index_middle", "finger_index_tip",
    "finger_middle", "finger_middle_middle", "finger_middle_tip",
    "finger_ring", "finger_ring_middle", "finger_ring_tip",
    "finger_little", "finger_little_middle", "finger_little_tip"
  ]) {
    const track = findTrack("playing-violin-prince-part-" + role);
    assert.ok(track, role + " retains its own transform track");
    assert.ok(track.values.some(value => value !== track.values[0]));
  }

  for (const role of [
    "left_upper_arm", "left_forearm", "right_upper_arm", "right_forearm",
    "right_hand", "left_thigh", "left_calf", "left_foot",
    "right_thigh", "right_calf", "right_foot"
  ]) {
    assert.equal(findTrack("playing-violin-prince-part-" + role), undefined,
      role + " must remain part of the intact source body until segmentation is repaired");
  }
});

test("segmented source base keeps twelve independent limb/hand layers and the bow chain", () => {
  const segmentedCharacter = {
    ...character,
    performance_base_mode: "segmented_source_body",
    base_art: {
      src: "performance-segmented-base.png",
      x: 0, y: 0, width: 441, height: 755,
      mode: "segmented_source_body",
      source_alpha_preserved: true,
      source_pixels_outside_cut_mask_preserved: true
    }
  };
  const segmentedProject = {
    ...project,
    characters: [segmentedCharacter]
  };
  const tracks = compileMotionTracks(segmentedProject, { fps: 25 });
  const findTrack = target => tracks.find(track =>
    track.target === target && track.property === "transform"
  );
  const base = findTrack("playing-violin-prince-base-art");
  assert.ok(base, "the source underpaint base follows the torso");
  assert.ok(base.values.some(value => value !== base.values[0]));

  const limbs = [
    "left_upper_arm", "left_forearm", "left_hand",
    "right_upper_arm", "right_forearm", "right_hand",
    "left_thigh", "left_calf", "left_foot",
    "right_thigh", "right_calf", "right_foot"
  ];
  for (const role of limbs) {
    const track = findTrack("playing-violin-prince-part-" + role);
    assert.ok(track, role + " receives its own hierarchical transform");
    assert.ok(track.values.some(value => value !== track.values[0]),
      role + " must have changing frame-seekable movement");
  }
  for (const role of [
    "finger_index", "finger_index_middle", "finger_index_tip",
    "finger_middle", "finger_middle_middle", "finger_middle_tip",
    "finger_ring", "finger_ring_middle", "finger_ring_tip",
    "finger_little", "finger_little_middle", "finger_little_tip"
  ]) {
    const track = findTrack("playing-violin-prince-part-" + role);
    assert.ok(track, role + " remains an independent fingering layer");
    assert.ok(track.values.some(value => value !== track.values[0]));
  }

  const bow = findTrack("playing-violin-prince-prop-bow");
  assert.ok(bow, "the bow attaches to the source-aligned bow hand");
  assert.ok(bow.values.some(value => value !== bow.values[0]));
  const violin = findTrack("playing-violin-prince-prop-violin");
  assert.ok(violin, "the violin remains independently layered between upper arms and forearms");
  assert.ok(violin.values.some(value => value !== violin.values[0]));
});

test("segmented source violin underlay is not duplicated by a second animated prop", () => {
  const segmentedCharacter = {
    ...character,
    performance_base_mode: "segmented_source_body",
    base_art: {
      src: "performance-segmented-base.png",
      x: 0, y: 0, width: 441, height: 755,
      z_index: 1,
      mode: "segmented_source_body",
      source_alpha_preserved: true,
      source_pixels_outside_cut_mask_preserved: true,
      violin_source_underlay_preserved: true
    }
  };
  const segmentedProject = {
    ...project,
    characters: [segmentedCharacter]
  };
  const tracks = compileMotionTracks(segmentedProject, { fps: 25 });
  const findTrack = target => tracks.find(track =>
    track.target === target && track.property === "transform"
  );

  assert.ok(findTrack("playing-violin-prince-prop-bow"),
    "the moving bow remains a separate animated prop");
  assert.equal(findTrack("playing-violin-prince-prop-violin"), undefined,
    "the source violin already belongs to the torso underlay and must render only once");
});

test("modular head expressions and angle plates are separately rendered and frame-seekable", () => {
  const tracks = compileMotionTracks(project, { fps: 25 });
  assert.equal(tracks.some(track =>
    track.target === "playing-violin-prince-expression-neutral" &&
    track.property === "opacity"
  ), false, "legacy face expression overlays must stay disabled when full head plates are active");
  for (const name of ["happy", "focused", "surprised", "neutral"]) {
    assert.ok(tracks.some(track =>
      track.target === "playing-violin-prince-head-variant-" + name &&
      track.property === "transform"
    ), "head expression " + name + " follows the neck pivot");
    const variantOpacity = tracks.find(track =>
      track.target === "playing-violin-prince-head-variant-" + name &&
      track.property === "opacity"
    );
    if (name === "focused") {
      assert.ok(variantOpacity, "the selected front expression has a visibility track");
      assert.ok(variantOpacity.values.includes(1) && variantOpacity.values.includes(0));
      assert.ok(variantOpacity.values.some(value => value > 0 && value < 1),
        "front expression changes use sampled opacity crossfades");
      assert.ok(Array.isArray(variantOpacity.offsets));
      assert.equal(variantOpacity.offsets.length, variantOpacity.values.length);
      assert.equal(variantOpacity.offsets[0], 0);
      assert.equal(variantOpacity.offsets.at(-1), 1);
      assert.equal(variantOpacity.keyframeEasing, undefined);
    } else {
      assert.equal(variantOpacity, undefined,
        "unused expression plates do not receive empty opacity animations");
    }
  }
  for (const name of ["three_quarter", "profile_right", "profile_left"]) {
    assert.ok(tracks.some(track =>
      track.target === "playing-violin-prince-head-angle-" + name &&
      track.property === "transform"
    ), "head angle " + name + " follows the neck pivot");
    const opacity = tracks.find(track =>
      track.target === "playing-violin-prince-head-angle-" + name &&
      track.property === "opacity"
    );
    assert.ok(opacity, "head angle " + name + " has a frame-seekable swap track");
    assert.ok(opacity.values.includes(1) && opacity.values.includes(0));
    assert.ok(opacity.values.some(value => value > 0 && value < 1),
      "head angle changes use sampled opacity crossfades");
    assert.ok(Array.isArray(opacity.offsets));
    assert.equal(opacity.offsets.length, opacity.values.length);
    assert.equal(opacity.offsets[0], 0);
    assert.equal(opacity.offsets.at(-1), 1);
    assert.equal(opacity.keyframeEasing, undefined);
  }
});


test("head expression sequence switches plates independently of head-angle sequence", () => {
  const expressionProject = structuredClone(project);
  const action = expressionProject.scenes[0].character_actions["violin-prince"];
  action.head_expression_sequence = ["focused", "neutral", "surprised", "happy"];
  action.head_expression_cycle_duration_seconds = 4;
  action.head_expression_loop = true;
  action.head_angle_sequence = ["front", "three_quarter", "front", "profile_right", "front", "three_quarter", "front", "profile_left", "front"];
  action.head_angle_cycle_duration_seconds = 4;

  const tracks = compileMotionTracks(expressionProject, { fps: 25 });
  const find = (target, property) => tracks.find(track =>
    track.target === target && track.property === property
  );

  for (const name of ["focused", "neutral", "surprised", "happy"]) {
    const opacity = find("playing-violin-prince-head-variant-" + name, "opacity");
    assert.ok(opacity, name + " expression gets an independent live visibility track");
    assert.ok(opacity.values.includes(1) && opacity.values.includes(0));
    assert.ok(opacity.values.some(value => value > 0 && value < 1),
      name + " expression should blend through intermediate opacity values");
    assert.ok(Array.isArray(opacity.offsets));
    assert.equal(opacity.offsets.length, opacity.values.length);
    assert.equal(opacity.offsets[0], 0);
    assert.equal(opacity.offsets.at(-1), 1);
    assert.equal(opacity.keyframeEasing, undefined);
    assert.equal(opacity.duration, 4);
  }
  for (const name of ["three_quarter", "profile_left"]) {
    const opacity = find("playing-violin-prince-head-angle-" + name, "opacity");
    assert.ok(opacity, name + " head angle retains its own visibility track");
    assert.ok(opacity.values.includes(1) && opacity.values.includes(0));
    assert.ok(opacity.values.some(value => value > 0 && value < 1));
    assert.ok(Array.isArray(opacity.offsets));
    assert.equal(opacity.offsets.length, opacity.values.length);
    assert.equal(opacity.keyframeEasing, undefined);
  }
});

test("segmented composite body keeps modular head plates attached to neck motion", () => {
  const segmentedProject = structuredClone(project);
  const segmentedCharacter = segmentedProject.characters[0];
  segmentedCharacter.performance_base_mode = "segmented_source_body";
  segmentedCharacter.base_art = {
    src: "performance-segmented-base.png",
    x: 0, y: 0, width: 441, height: 755, z_index: 1
  };
  const tracks = compileMotionTracks(segmentedProject, { fps: 25 });
  const find = (target, property = "transform") => tracks.find(track =>
    track.target === target && track.property === property
  );

  assert.ok(find("playing-violin-prince-base-art"),
    "the segmented parent plate continues to follow the torso");
  for (const name of ["happy", "focused", "surprised", "neutral"]) {
    const track = find("playing-violin-prince-head-variant-" + name);
    assert.ok(track, name + " full-head expression plate follows the neck and torso");
    assert.ok(track.values.some(value => value !== track.values[0]));
  }
  for (const name of ["front", "three_quarter", "profile_right", "profile_left"]) {
    if (name === "front") continue;
    const track = find("playing-violin-prince-head-angle-" + name);
    assert.ok(track, name + " head-angle plate follows the neck pivot");
    assert.ok(track.values.some(value => value !== track.values[0]));
  }
});


test("fingerboard notes select the mapped string and one finger, then sustain that press", () => {
  const tracks = buildMusicSynchronizedPerformanceTracks({
    targetPrefix: "finger-test",
    duration: 2,
    bpm: 120,
    beatTimes: [0, 0.5, 1, 1.5],
    downbeats: [0, 1],
    onsets: [0.1, 0.6],
    noteEvents: [
      { time: 0.1, note: 60, velocity: 64, duration_seconds: 0.25 },
      { time: 0.6, note: 72, velocity: 88, duration_seconds: 0.8 }
    ],
    confidence: 1
  });
  const getFinger = name => tracks.find(track =>
    track.target === "finger-test-part-" + name
  );
  const digits = ["index", "middle", "ring", "little"];
  const fingerSegments = digits.flatMap(name => [
    getFinger("finger_" + name),
    getFinger("finger_" + name + "_middle"),
    getFinger("finger_" + name + "_tip")
  ]);
  assert.ok(fingerSegments.every(Boolean), "all four fingers need base, middle and tip tracks");

  const map = getFinger("finger_index").music_sync_fingering_map;
  assert.deepEqual(map.map(item => ({ string: item.string, finger: item.finger })),
    [{ string: "G", finger: "finger_ring" }, { string: "A", finger: "finger_middle" }]);

  for (const digit of ["ring", "middle"]) {
    const base = getFinger("finger_" + digit);
    const middle = getFinger("finger_" + digit + "_middle");
    const tip = getFinger("finger_" + digit + "_tip");
    assert.ok(base.key_times.some(time => time >= (digit === "ring" ? 0.10 : 0.60) &&
      time <= (digit === "ring" ? 0.16 : 0.66)));
    const maxCombinedCurl = Math.max(...base.values.map((value, i) =>
      Math.abs(Number(value)) + Math.abs(Number(middle.values[i] || 0)) +
      Math.abs(Number(tip.values[i] || 0))
    ));
    assert.ok(maxCombinedCurl > 4, digit + " phalanges should combine to a visible press");
  }
  for (const digit of ["index", "little"]) {
    assert.ok(getFinger("finger_" + digit).values.every(value => Number(value) === 0),
      digit + " must not be curled for notes assigned to other fingers");
  }

  const middle = getFinger("finger_middle");
  assert.ok(middle.key_times.some(time => time > 1.1),
    "the long A-string second-finger note holds before its release and settle");
});
