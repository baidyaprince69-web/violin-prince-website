import { spring } from "motion";
import { gestureKeyframes } from "./contract.mjs";
import { fitCharacterToCanvas } from "./character-layout.mjs";

export function sampleMotionSpring(from, to, fps = 25, maxMs = 1400) {
  const frameRate = Math.max(1, Number(fps) || 25);
  const maximum = Math.max(250, Math.min(4000, Number(maxMs) || 1400));
  const generator = spring({
    keyframes: [Number(from), Number(to)],
    stiffness: 320,
    damping: 26,
    mass: 1
  });
  const stepMs = 1000 / frameRate;
  const values = [];
  let elapsed = 0;
  for (; elapsed <= maximum; elapsed += stepMs) {
    const state = generator.next(elapsed);
    const value = Number(state.value);
    if (!Number.isFinite(value)) {
      throw new TypeError("Motion produced a non-finite spring sample.");
    }
    values.push(value);
    if (state.done) break;
  }
  if (!values.length || Math.abs(values.at(-1) - Number(to)) > 0.001) {
    values.push(Number(to));
  }
  return {
    values,
    duration: Math.max(1 / frameRate, (values.length - 1) / frameRate)
  };
}

function cssKeyframeValues(property, values) {
  if (property === "rotate") {
    return values.map(value => typeof value === "number" ? value + "deg" : String(value));
  }
  if (property === "x" || property === "y") {
    throw new TypeError("Use CSS transform translateX/translateY for native frame-seekable movement.");
  }
  return values;
}

function multiplyMatrix(left, right) {
  return {
    a: left.a * right.a + left.c * right.b,
    b: left.b * right.a + left.d * right.b,
    c: left.a * right.c + left.c * right.d,
    d: left.b * right.c + left.d * right.d,
    e: left.a * right.e + left.c * right.f + left.e,
    f: left.b * right.e + left.d * right.f + left.f
  };
}

function translateMatrix(x, y) {
  return { a: 1, b: 0, c: 0, d: 1, e: x, f: y };
}

function rotateMatrix(degrees) {
  const radians = Number(degrees) * Math.PI / 180;
  const cosine = Math.cos(radians);
  const sine = Math.sin(radians);
  return { a: cosine, b: sine, c: -sine, d: cosine, e: 0, f: 0 };
}

function aroundPivot(point, degrees) {
  return multiplyMatrix(
    multiplyMatrix(translateMatrix(point.x, point.y), rotateMatrix(degrees)),
    translateMatrix(-point.x, -point.y)
  );
}

function cubicBezierProgress(progress, x1 = 0.42, y1 = 0, x2 = 0.58, y2 = 1) {
  const tGoal = Math.min(1, Math.max(0, progress));
  if (tGoal === 0 || tGoal === 1) return tGoal;
  const coordinate = (t, first, second) => {
    const inverse = 1 - t;
    return 3 * inverse * inverse * t * first +
      3 * inverse * t * t * second + t * t * t;
  };
  let low = 0;
  let high = 1;
  let parameter = tGoal;
  for (let iteration = 0; iteration < 18; iteration += 1) {
    parameter = (low + high) / 2;
    const x = coordinate(parameter, x1, x2);
    if (x < tGoal) low = parameter;
    else high = parameter;
  }
  return coordinate(parameter, y1, y2);
}

function numericCssValue(value) {
  const parsed = Number.parseFloat(String(value));
  return Number.isFinite(parsed) ? parsed : 0;
}

function sampleRotationTrack(track, time) {
  const values = track.values || [];
  if (values.length < 2) return numericCssValue(values[0] || 0);
  const duration = Math.max(0.001, Number(track.duration) || 0.001);
  const rawProgress = (Number(time) - Number(track.start || 0)) / duration;
  const progress = Math.min(1, Math.max(0, rawProgress));
  const segmentPosition = progress * (values.length - 1);
  const segment = Math.min(values.length - 2, Math.floor(segmentPosition));
  const localProgress = segmentPosition - segment;
  const eased = track.easing === "linear"
    ? localProgress
    : cubicBezierProgress(localProgress);
  const from = numericCssValue(values[segment]);
  const to = numericCssValue(values[segment + 1]);
  return from + (to - from) * eased;
}

function layerPivot(layer, joint, sourceWidth, sourceHeight, fallback = { x: 0.5, y: 0.5 }) {
  if (joint) {
    return {
      x: Number(joint.x) * sourceWidth,
      y: Number(joint.y) * sourceHeight
    };
  }
  return {
    x: Number(layer?.x || 0) + Number(layer?.width || 0) * Number(layer?.pivot_x ?? fallback.x),
    y: Number(layer?.y || 0) + Number(layer?.height || 0) * Number(layer?.pivot_y ?? fallback.y)
  };
}

function localCssMatrix(world, layer, scale) {
  const x = Number(layer?.x || 0);
  const y = Number(layer?.y || 0);
  const relative = multiplyMatrix(
    multiplyMatrix(translateMatrix(-x, -y), world),
    translateMatrix(x, y)
  );
  return "matrix(" + [
    relative.a, relative.b, relative.c, relative.d,
    relative.e * scale, relative.f * scale
  ].map(value => Number(value.toFixed(6))).join(",") + ")";
}

function addHierarchicalTransformTracks(project, sourceTracks, fps) {
  const transformTracks = [];
  const width = Math.max(1, Number(project.width) || 720);
  const height = Math.max(1, Number(project.height) || 1280);
  const frameRate = Math.max(1, Number(fps) || 25);

  for (const scene of project.scenes || []) {
    const sceneStart = Number(scene.start) || 0;
    const sceneDuration = Number(scene.duration) || 1;
    const sampleOffsets = [];
    for (let elapsed = 0; elapsed < sceneDuration - 1e-8; elapsed += 1 / frameRate) {
      sampleOffsets.push(elapsed / sceneDuration);
    }
    sampleOffsets.push(1);

    for (const character of project.characters || []) {
      const action = (character.scene_actions || {})[scene.id] ||
        ((scene.character_actions || {})[character.id] || {});
      if (Array.isArray(character.scene_ids) && !character.scene_ids.includes(scene.id)) continue;
      if (action.visible === false) continue;

      const prefix = scene.id + "-" + character.id;
      const layers = character.layers || [];
      const layerByRole = new Map(layers.map(layer => [layer.role, layer]));
      const sourceWidth = Number(character.canvas?.width) || width;
      const sourceHeight = Number(character.canvas?.height) || height;
      const { scale } = fitCharacterToCanvas(character, width, height);
      const joints = character.joints || {};
      const rotationTracks = new Map();

      for (const layer of layers) {
        const id = prefix + "-part-" + layer.id;
        rotationTracks.set(
          layer.role,
          sourceTracks.filter(track => track.target === id && track.property === "rotate")
        );
      }

      const hasRotation = role => (rotationTracks.get(role) || []).length > 0;
      const dependencies = {
        torso: ["torso"],
        head: ["torso", "head"],
        face: ["torso", "head"],
        left_upper_arm: ["torso", "left_upper_arm"],
        left_forearm: ["torso", "left_upper_arm", "left_forearm"],
        left_hand: ["torso", "left_upper_arm", "left_forearm", "left_hand"],
        right_upper_arm: ["torso", "right_upper_arm"],
        right_forearm: ["torso", "right_upper_arm", "right_forearm"],
        right_hand: ["torso", "right_upper_arm", "right_forearm", "right_hand"]
      };

      const rolesToAnimate = new Set();
      for (const [role, ancestors] of Object.entries(dependencies)) {
        if (ancestors.some(hasRotation) && (layerByRole.has(role) || role === "face")) {
          rolesToAnimate.add(role);
        }
      }
      const expressionNames = Object.keys(character.expressions || {});
      const needsExpressionTransform = hasRotation("torso") || hasRotation("head");
      if (!rolesToAnimate.size && !(needsExpressionTransform && expressionNames.length)) continue;

      const pivotFor = (jointName, layerRole) =>
        layerPivot(layerByRole.get(layerRole), joints[jointName], sourceWidth, sourceHeight);
      const torsoPivot = layerPivot(layerByRole.get("torso"), null, sourceWidth, sourceHeight);
      const neckPivot = pivotFor("neck", "head");
      const leftShoulder = pivotFor("left_shoulder", "left_upper_arm");
      const leftElbow = pivotFor("left_elbow", "left_forearm");
      const leftWrist = pivotFor("left_wrist", "left_hand");
      const rightShoulder = pivotFor("right_shoulder", "right_upper_arm");
      const rightElbow = pivotFor("right_elbow", "right_forearm");
      const rightWrist = pivotFor("right_wrist", "right_hand");

      const localAngle = (role, time) => {
        const candidates = rotationTracks.get(role) || [];
        if (!candidates.length) return 0;
        const selected = candidates[candidates.length - 1];
        return sampleRotationTrack(selected, time);
      };

      const sampledMatrices = new Map([...rolesToAnimate].map(role => [role, []]));
      const sampledExpressionMatrices = new Map(expressionNames.map(name => [name, []]));

      for (const offset of sampleOffsets) {
        const time = sceneStart + offset * sceneDuration;
        const torsoWorld = aroundPivot(torsoPivot, localAngle("torso", time));
        const headWorld = multiplyMatrix(
          torsoWorld,
          aroundPivot(neckPivot, localAngle("head", time))
        );

        const leftUpperWorld = multiplyMatrix(
          torsoWorld,
          aroundPivot(leftShoulder, localAngle("left_upper_arm", time))
        );
        const leftForearmWorld = multiplyMatrix(
          leftUpperWorld,
          aroundPivot(leftElbow, localAngle("left_forearm", time))
        );
        const leftHandWorld = multiplyMatrix(
          leftForearmWorld,
          aroundPivot(leftWrist, localAngle("left_hand", time))
        );

        const rightUpperWorld = multiplyMatrix(
          torsoWorld,
          aroundPivot(rightShoulder, localAngle("right_upper_arm", time))
        );
        const rightForearmWorld = multiplyMatrix(
          rightUpperWorld,
          aroundPivot(rightElbow, localAngle("right_forearm", time))
        );
        const rightHandWorld = multiplyMatrix(
          rightForearmWorld,
          aroundPivot(rightWrist, localAngle("right_hand", time))
        );

        const worldByRole = {
          torso: torsoWorld,
          head: headWorld,
          face: headWorld,
          left_upper_arm: leftUpperWorld,
          left_forearm: leftForearmWorld,
          left_hand: leftHandWorld,
          right_upper_arm: rightUpperWorld,
          right_forearm: rightForearmWorld,
          right_hand: rightHandWorld
        };
        for (const role of rolesToAnimate) {
          sampledMatrices.get(role).push(
            localCssMatrix(worldByRole[role], layerByRole.get(role), scale)
          );
        }
        for (const name of expressionNames) {
          sampledExpressionMatrices.get(name).push(
            localCssMatrix(headWorld, character.expressions[name], scale)
          );
        }
      }

      for (const role of rolesToAnimate) {
        transformTracks.push({
          target: prefix + "-part-" + (layerByRole.get(role).id),
          property: "transform",
          values: sampledMatrices.get(role),
          offsets: sampleOffsets,
          start: sceneStart,
          duration: sceneDuration,
          easing: "linear"
        });
      }
      if (needsExpressionTransform) {
        for (const name of expressionNames) {
          transformTracks.push({
            target: prefix + "-expression-" + name,
            property: "transform",
            values: sampledExpressionMatrices.get(name),
            offsets: sampleOffsets,
            start: sceneStart,
            duration: sceneDuration,
            easing: "linear"
          });
        }
      }
    }
  }
  return transformTracks;
}

export function compileMotionTracks(project, { fps = 25 } = {}) {
  const tracks = [];
  const addSpring = (target, property, from, to, start, maxMs) => {
    const sampled = sampleMotionSpring(from, to, fps, maxMs);
    tracks.push({
      target,
      property,
      values: sampled.values,
      start: Math.max(0, Number(start) || 0),
      duration: sampled.duration,
      easing: "linear"
    });
  };
  const addKeyframes = (target, properties, start, durationSeconds, easing = "ease-in-out") => {
    if (!properties || typeof properties !== "object") return;
    for (const [property, rawValues] of Object.entries(properties)) {
      if (!Array.isArray(rawValues) || rawValues.length < 2) continue;
      tracks.push({
        target,
        property,
        values: cssKeyframeValues(property, rawValues),
        start: Math.max(0, Number(start) || 0),
        duration: Math.max(0.08, Number(durationSeconds) || 0.8),
        easing
      });
    }
  };

  for (const scene of project.scenes || []) {
    const sceneStart = Number(scene.start) || 0;
    const sceneDuration = Number(scene.duration) || 1;
    const backgroundId = scene.id + "-background";
    const titleId = scene.id + "-title";
    const captionId = scene.id + "-caption";
    addSpring(backgroundId, "opacity", 0, 1, sceneStart, 650);
    addSpring(backgroundId, "transform", 1.045, 1, sceneStart, 800);
    tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(value => "scale(" + value + ")");
    addSpring(titleId, "opacity", 0, 1, sceneStart + 0.12, 600);
    addSpring(titleId, "transform", 30, 0, sceneStart + 0.12, 700);
    tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(value => "translateY(" + value + "px)");
    addSpring(captionId, "opacity", 0, 1, sceneStart + 0.45, 540);
    addSpring(captionId, "transform", 20, 0, sceneStart + 0.45, 580);
    tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(value => "translateY(" + value + "px)");

    for (const character of project.characters || []) {
      const action = (character.scene_actions || {})[scene.id] ||
        ((scene.character_actions || {})[character.id] || {});
      if (Array.isArray(character.scene_ids) && !character.scene_ids.includes(scene.id)) continue;
      if (action.visible === false) continue;
      const prefix = scene.id + "-" + character.id;
      const actionStart = sceneStart + Math.max(0, Number(action.start_offset) || 0);
      addSpring(prefix, "opacity", 0, 1, actionStart, 650);
      addSpring(prefix, "transform", 28, 0, actionStart, 720);
      tracks[tracks.length - 1].values = tracks[tracks.length - 1].values.map(value => "translateY(" + value + "px)");
      const partIdByRole = new Map();
      for (const layer of character.layers || []) {
        const target = prefix + "-part-" + layer.id;
        partIdByRole.set(layer.role, target);
      }

      const addRigKeyframes = (role, properties, start, duration) => {
        addKeyframes(partIdByRole.get(role), properties, start, duration);
        // The face cut-out and expression overlays are separate images, but
        // they must inherit the head's neck-pivot motion to stay registered.
        if (role === "head") {
          addKeyframes(partIdByRole.get("face"), properties, start, duration);
          for (const name of Object.keys(character.expressions || {})) {
            addKeyframes(prefix + "-expression-" + name, properties, start, duration);
          }
        }
      };
      const pose = (character.poses || {})[action.pose || ""] || {};
      for (const [role, properties] of Object.entries(pose)) {
        addRigKeyframes(role, properties, actionStart + 0.05, Number(action.duration) || 1);
      }
      const gestures = {
        ...gestureKeyframes(action.gesture),
        ...((character.gestures || {})[action.gesture] || {})
      };
      for (const [role, properties] of Object.entries(gestures)) {
        addRigKeyframes(role, properties, actionStart + 0.10, Number(action.duration) || 1.35);
      }
      for (const [role, properties] of Object.entries(action.keyframes || {})) {
        addRigKeyframes(role, properties, actionStart, Number(action.duration) || 1);
      }
      const selectedExpression = String(action.expression || "neutral").toLowerCase();
      const activePoseAsset = String(action.pose_asset || "").toLowerCase();
      // Full-body pose plates already contain their own face. Animate
      // expression overlays only while the separated body-part rig is active.
      if (!activePoseAsset) {
        for (const name of Object.keys(character.expressions || {})) {
          addSpring(prefix + "-expression-" + name, "opacity",
            name === selectedExpression ? 0 : 1,
            name === selectedExpression ? 1 : 0,
            actionStart, 140);
        }
      }
      const eyeTarget = partIdByRole.get("eyes");
      if (eyeTarget) {
        addKeyframes(eyeTarget, { scaleY: [1, 0.12, 1] },
          actionStart + Math.min(1, sceneDuration * 0.4), 0.18);
      }
    }
  }
  const articulated = addHierarchicalTransformTracks(project, tracks, fps);
  return [...tracks.filter(track => track.property !== "rotate"), ...articulated];
}
