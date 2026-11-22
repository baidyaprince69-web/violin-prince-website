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
