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
  const bow = find("playing-violin-prince-prop-bow");
  const bowTranslation = tracks.find(track =>
    track.target === "playing-violin-prince-prop-bow" && track.property === "translate"
  );
  const bowShoulder = find("playing-violin-prince-part-left_upper_arm");
  const elbow = find("playing-violin-prince-part-left_forearm");
  const wrist = find("playing-violin-prince-part-left_hand");
  const fingerboardForearm = find("playing-violin-prince-part-right_forearm");
  const fingerboardHand = find("playing-violin-prince-part-right_hand");
  const indexFinger = find("playing-violin-prince-part-finger_index");
  const ringFinger = find("playing-violin-prince-part-finger_ring");
  const littleFinger = find("playing-violin-prince-part-finger_little");

  assert.ok(bow && bowTranslation && bowShoulder && elbow && wrist);
  assert.ok(fingerboardForearm && fingerboardHand && indexFinger && ringFinger && littleFinger);
  assert.equal(bow.start, 0.12);
  assert.ok(bowTranslation.values.length > 80,
    "bow travel is sampled at composition frame rate");
  assert.ok(new Set(bowTranslation.values).size > 3,
    "bow travel moves continuously between beat reversals");
  assert.deepEqual(bow.key_times.slice(0, 4), [0, 0.06, 0.56, 1.06]);
  assert.equal(bow.key_times.at(-1), 3.88);
  assert.ok(bow.values.some((value, index) => index > 1 && value !== bow.values[index - 1]));
  assert.ok(indexFinger.key_times.includes(0.268));
  assert.ok(ringFinger.key_times.includes(1.268));
  assert.ok(littleFinger.key_times.includes(1.768));
  assert.ok(fingerboardForearm.key_times.includes(0.268));
  assert.ok(fingerboardHand.key_times.includes(0.268));
  assert.ok(bowShoulder.values.some(value => Math.abs(value) >= 3.8));
  assert.ok(elbow.values.some(value => Math.abs(value) >= 12.8));
  assert.ok(wrist.values.some(value => Math.abs(value) >= 4.3));

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
    "playing-violin-prince-part-right_forearm",
    "playing-violin-prince-part-right_hand",
    "playing-violin-prince-part-finger_index",
    "playing-violin-prince-part-finger_ring"
  ]) {
    const regular = getTrack(regularTracks, target);
    const synchronized = getTrack(musicTracks, target);
    assert.ok(regular && synchronized, target + " must compile in both modes");
    assert.notDeepEqual(synchronized.values, regular.values,
      target + " must use the audio event map instead of the generic loop");
  }

  const bowTravel = getTrack(musicTracks, "playing-violin-prince-prop-bow", "translate");
  assert.ok(bowTravel && bowTravel.values.length > 80);
  assert.ok(new Set(bowTravel.values).size > 3);
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
    "right_upper_arm", "right_forearm", "right_hand",
    "torso", "head", "left_thigh", "right_thigh",
    "left_calf", "right_calf", "left_foot", "right_foot",
    "finger_index", "finger_middle", "finger_ring", "finger_little"
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
  assert.ok(bow, "bow remains independently animated over the intact body");
  assert.ok(bow.values.some(value => value !== bow.values[0]));
  assert.equal(findTrack("playing-violin-prince-prop-violin"), undefined,
    "the original violin stays in the preserved source illustration");

  const bowHand = findTrack("playing-violin-prince-part-left_hand");
  assert.ok(bowHand, "the original bow-grip hand remains aligned above the bow");
  assert.ok(bowHand.values.some(value => value !== bowHand.values[0]));

  for (const role of ["finger_index", "finger_middle", "finger_ring", "finger_little"]) {
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
  for (const role of ["finger_index", "finger_middle", "finger_ring", "finger_little"]) {
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
    assert.ok(variantOpacity, "head expression " + name + " has an independent visibility track");
    assert.equal(variantOpacity.keyframeEasing, "steps(1, end)",
      "full-head expression plates must switch without overlapping ghost faces");
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
    assert.equal(opacity.keyframeEasing, "steps(1, end)",
      "full-head angle plates must switch without overlapping ghost faces");
  }
});


test("head expression sequence switches plates independently of head-angle sequence", () => {
  const expressionProject = structuredClone(project);
  const action = expressionProject.scenes[0].character_actions["violin-prince"];
  action.head_expression_sequence = ["focused", "neutral", "surprised", "happy"];
  action.head_expression_cycle_duration_seconds = 4;
  action.head_expression_loop = true;
  action.head_angle_sequence = ["front", "three_quarter", "front", "profile_left", "front"];
  action.head_angle_cycle_duration_seconds = 4;

  const tracks = compileMotionTracks(expressionProject, { fps: 25 });
  const find = (target, property) => tracks.find(track =>
    track.target === target && track.property === property
  );

  for (const name of ["focused", "neutral", "surprised", "happy"]) {
    const opacity = find("playing-violin-prince-head-variant-" + name, "opacity");
    assert.ok(opacity, name + " expression gets an independent live visibility track");
    assert.ok(opacity.values.includes(1) && opacity.values.includes(0));
    assert.equal(opacity.keyframeEasing, "steps(1, end)");
    assert.equal(opacity.duration, 4);
  }
  for (const name of ["three_quarter", "profile_left"]) {
    const opacity = find("playing-violin-prince-head-angle-" + name, "opacity");
    assert.ok(opacity, name + " head angle retains its own visibility track");
    assert.ok(opacity.values.includes(1) && opacity.values.includes(0));
    assert.equal(opacity.keyframeEasing, "steps(1, end)");
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
