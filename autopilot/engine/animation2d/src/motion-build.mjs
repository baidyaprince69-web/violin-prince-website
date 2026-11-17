import { spring } from "motion";
import { gestureKeyframes } from "./contract.mjs";

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

      const pose = (character.poses || {})[action.pose || ""] || {};
      for (const [role, properties] of Object.entries(pose)) {
        addKeyframes(partIdByRole.get(role), properties, actionStart + 0.05, Number(action.duration) || 1);
      }
      const gestures = {
        ...gestureKeyframes(action.gesture),
        ...((character.gestures || {})[action.gesture] || {})
      };
      for (const [role, properties] of Object.entries(gestures)) {
        addKeyframes(partIdByRole.get(role), properties, actionStart + 0.10, Number(action.duration) || 1.35);
      }
      for (const [role, properties] of Object.entries(action.keyframes || {})) {
        addKeyframes(partIdByRole.get(role), properties, actionStart, Number(action.duration) || 1);
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
  return tracks;
}
