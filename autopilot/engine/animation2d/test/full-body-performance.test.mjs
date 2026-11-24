import test from "node:test";
import assert from "node:assert/strict";
import {
  buildMusicSynchronizedPerformanceTracks,
  compileMotionTracks
} from "../src/motion-build.mjs";

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
      pivot_x: .035, pivot_y: .976, z_index: 35, attach_to: "left_hand"
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

test("source texture meshes deform continuously and a lower-body knee surface follows thigh and calf chains", () => {
  const meshProject = structuredClone(project);
  const meshCharacter = meshProject.characters[0];
  const byRole = new Map(meshCharacter.layers.map(layer => [layer.role, layer]));
  byRole.get("torso").mesh_deformation = {
    profile: "torso", driver_role: "torso",
    axis_start: [0.3, 0.08], axis_end: [0.55, 0.94],
    influence: "center", columns: 2, rows: 2,
    max_angle_deg: 1.2, max_displacement_px: 2.4
  };
  byRole.get("left_upper_arm").mesh_deformation = {
    profile: "limb_joint", driver_role: "left_upper_arm",
    axis_start: [0.8, 0.2], axis_end: [0.2, 0.8],
    influence: "distal", columns: 2, rows: 4,
    max_angle_deg: 5, max_displacement_px: 2.8
  };
  meshCharacter.layers.push({
    id: "joint_surface_left_knee",
    role: "joint_surface_left_knee",
    src: "joint_surface_left_knee.png",
    x: 92, y: 540, width: 48, height: 48,
    pivot_x: 0.5, pivot_y: 0.5, z_index: 12,
    mesh_deformation: {
      profile: "joint_surface",
      columns: 3,
      rows: 3
    },
    joint_surface: {
      joint: "left_knee",
      parent_role: "left_thigh",
      child_role: "left_calf",
      blend_weight: 0.5,
      blend_axis_start: [0.14, 0.40],
      blend_axis_end: [0.19, 0.48]
    }
  });

  const tracks = compileMotionTracks(meshProject, { fps: 25 });
  const find = target => tracks.find(track =>
    track.target === target && track.property === "transform"
  );
  const torsoMesh = tracks.filter(track =>
    track.target.startsWith("playing-violin-prince-part-torso-mesh-triangle-")
  );
  const upperArmMesh = tracks.filter(track =>
    track.target.startsWith("playing-violin-prince-part-left_upper_arm-mesh-triangle-")
  );
  assert.equal(torsoMesh.length, 8);
  assert.equal(upperArmMesh.length, 16);
  assert.ok(torsoMesh.some(track => track.values.some(value => value !== track.values[0])),
    "torso triangle vertices must receive changing frame-sampled affine transforms");
  assert.ok(upperArmMesh.some(track => track.values.some(value => value !== track.values[0])),
    "limb surface must deform in addition to its parent rotation");
  const thighTransform = find("playing-violin-prince-part-left_thigh");
  const calfTransform = find("playing-violin-prince-part-left_calf");
  assert.ok(thighTransform?.values.some(value => value !== thighTransform.values[0]),
    "the proximal thigh must move during the violin-performance cycle");
  assert.ok(calfTransform?.values.some(value => value !== calfTransform.values[0]),
    "the distal calf must move during the violin-performance cycle");
  const jointTransform = find("playing-violin-prince-part-joint_surface_left_knee");
  assert.equal(jointTransform, undefined,
    "a mesh-deformed joint surface must not also receive a rigid patch transform");
  const jointMesh = tracks.filter(track =>
    track.target.startsWith("playing-violin-prince-part-joint_surface_left_knee-mesh-triangle-")
  );
  assert.equal(jointMesh.length, 18,
    "a 3-by-3 joint surface grid must produce eighteen triangle tracks");
  assert.ok(jointMesh.some(track =>
    track.values.some(value => value !== track.values[0])
  ), "joint-surface triangles must follow changing thigh and calf poses");
  const sampleIndex = Math.floor(jointMesh[0].values.length * 0.65);
  assert.notEqual(jointMesh[0].values[sampleIndex], jointMesh.at(-1).values[sampleIndex],
    "proximal and distal joint-surface rows must receive different parent/child blends");
  assert.ok(!meshCharacter.layers.find(layer => layer.role === "left_hand").mesh_deformation);
  assert.ok(!meshCharacter.layers.find(layer => layer.role === "finger_index").mesh_deformation);
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
      { time: 1.75, note: 77, velocity: 88, duration_seconds: 0.75 }
    ],
    confidence: 1
  });
  const find = target => tracks.find(track => track.target === target);
  const bowPropTracks = tracks.filter(track => track.target === "playing-violin-prince-prop-bow");
  const bowShoulder = find("playing-violin-prince-part-left_upper_arm");
  const elbow = find("playing-violin-prince-part-left_forearm");
  const wrist = find("playing-violin-prince-part-left_hand");
  const fingerboardArmTracks = tracks.filter(track =>
    /playing-violin-prince-part-right_(upper_arm|forearm|hand)$/.test(track.target)
  );
  const indexFinger = find("playing-violin-prince-part-finger_index");
  const ringFinger = find("playing-violin-prince-part-finger_ring");
  const littleFinger = find("playing-violin-prince-part-finger_little");

  assert.ok(bowShoulder && elbow && wrist);
  assert.equal(bowPropTracks.length, 0,
    "bow motion must come from the grip's shoulder-elbow-wrist chain");
  assert.equal(fingerboardArmTracks.length, 0,
    "the violin-neck arm must not drift away from its contact point");
  assert.ok(indexFinger && ringFinger && littleFinger);
  assert.ok(indexFinger.key_times.includes(0.268));
  assert.ok(ringFinger.key_times.includes(1.286));
  assert.ok(littleFinger.key_times.includes(1.795));
  assert.ok(Math.max(...bowShoulder.values.map(Math.abs)) <= 7.0);
  assert.ok(Math.max(...elbow.values.map(Math.abs)) <= 0.6);
  assert.ok(Math.max(...wrist.values.map(Math.abs)) <= 6.4);
  assert.ok(bowShoulder.values.some(value => Math.abs(value) >= 5.0));
  assert.ok(elbow.values.some(value => Math.abs(value) >= 0.4));
  assert.ok(wrist.values.some(value => Math.abs(value) >= 4.5));
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

  const bowTransform = getTrack(musicTracks, "playing-violin-prince-prop-bow", "transform");
  assert.ok(bowTransform && bowTransform.values.some(value => value !== bowTransform.values[0]),
    "bow follows the articulated bowing-hand parent");
  assert.equal(getTrack(musicTracks, "playing-violin-prince-prop-bow", "translate"), undefined,
    "bow must not receive a second independent slide");
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


test("fingerboard notes retain lower-finger contact and sustain presses for note duration", () => {
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

  // The high register note prepares/presses the index, middle, ring and
  // little fingers together rather than flicking a single arbitrary finger.
  for (const track of fingerSegments) {
    assert.ok(track.key_times.some(time => time >= 0.60 && time <= 0.66));
    assert.ok(track.values.some(value => Math.abs(Number(value)) > 0.5));
  }
  for (const digit of digits) {
    const base = getFinger("finger_" + digit);
    const middle = getFinger("finger_" + digit + "_middle");
    const tip = getFinger("finger_" + digit + "_tip");
    const maxCombinedCurl = Math.max(...base.values.map((value, i) =>
      Math.abs(Number(value)) + Math.abs(Number(middle.values[i] || 0)) +
      Math.abs(Number(tip.values[i] || 0))
    ));
    assert.ok(maxCombinedCurl > 4, digit + " phalanges should combine to a visible press");
  }
  const index = getFinger("finger_index");
  // The second note is sustained; its press/release cycle must outlast the short note.
  const indexLateKeys = index.key_times.filter(time => time > 0.7);
  assert.ok(indexLateKeys.some(time => time > 1.1),
    "long note holds the finger position before the release and settle");
});
