import { animate } from "motion";
import { clampTime, springKeyframes, gestureKeyframes } from "./contract.mjs";

const project = window.VP_PROJECT || {};
const frameRate = Math.max(1, Number(project.fps) || 25);
const totalDuration = Math.max(0, Number(project.duration_seconds) || 0);
const springAnimations = [];
const keyframes = [];
const activeAnimations = [];

function pauseControl(control) {
  if (control && typeof control.pause === "function") control.pause();
  return control;
}

function addSpring(element, property, from, to, start, duration, options = {}) {
  if (!element) return;
  const samples = springKeyframes(from, to, frameRate, Math.max(250, duration * 1000));
  const sampledDuration = samples.length / frameRate;
  const control = pauseControl(animate(element, {
    [property]: samples
  }, {
    type: "tween",
    ease: "linear",
    duration: sampledDuration,
    delay: Math.max(0, Number(start) || 0),
    fill: "both"
  }));
  springAnimations.push({ control, start, duration: sampledDuration, property });
  return control;
}

function addKeyframes(element, properties, start, duration = 0.8) {
  if (!element || !properties || typeof properties !== "object") return;
  for (const [property, values] of Object.entries(properties)) {
    if (!Array.isArray(values) || values.length < 2) continue;
    const control = pauseControl(animate(element, { [property]: values }, {
      type: "tween",
      ease: "easeInOut",
      duration: Math.max(0.08, Number(duration) || 0.8),
      delay: Math.max(0, Number(start) || 0),
      fill: "both"
    }));
    keyframes.push({ control, property, start, duration });
  }
}

function partTransform(element, from, to, start, duration) {
  addSpring(element, "rotate", from, to, start, duration);
}

for (const scene of project.scenes || []) {
  const sceneStart = Number(scene.start) || 0;
  const sceneDuration = Number(scene.duration) || 1;
  const background = document.getElementById(scene.id + "-background");
  const title = document.getElementById(scene.id + "-title");
  const caption = document.getElementById(scene.id + "-caption");
  addSpring(background, "opacity", 0, 1, sceneStart, 650);
  addSpring(background, "scale", 1.045, 1, sceneStart, 800);
  addSpring(title, "opacity", 0, 1, sceneStart + 0.12, 600);
  addSpring(title, "y", 30, 0, sceneStart + 0.12, 700);
  addSpring(caption, "opacity", 0, 1, sceneStart + 0.45, 540);
  addSpring(caption, "y", 20, 0, sceneStart + 0.45, 580);

  for (const character of project.characters || []) {
    const action = (character.scene_actions || {})[scene.id] ||
      ((scene.character_actions || {})[character.id] || {});
    if (Array.isArray(character.scene_ids) && !character.scene_ids.includes(scene.id)) continue;
    if (action.visible === false) continue;
    const wrapper = document.getElementById(scene.id + "-" + character.id);
    if (!wrapper) continue;
    const start = sceneStart + Math.max(0, Number(action.start_offset) || 0);
    addSpring(wrapper, "opacity", 0, 1, start, 650);
    addSpring(wrapper, "y", 28, 0, start, 720);
    const parts = new Map();
    for (const element of wrapper.querySelectorAll(".rig-part")) {
      parts.set(element.dataset.role, element);
    }
    const pose = (character.poses || {})[action.pose || ""] || {};
    for (const [role, props] of Object.entries(pose)) {
      addKeyframes(parts.get(role), props, start + 0.05, Number(action.duration) || 1);
    }
    const gestures = {
      ...gestureKeyframes(action.gesture),
      ...((character.gestures || {})[action.gesture] || {})
    };
    for (const [role, props] of Object.entries(gestures)) {
      addKeyframes(parts.get(role), props, start + 0.10, Number(action.duration) || 1.35);
    }
    for (const [role, props] of Object.entries(action.keyframes || {})) {
      addKeyframes(parts.get(role), props, start, Number(action.duration) || 1);
    }
    const expression = String(action.expression || "neutral").toLowerCase();
    for (const image of wrapper.querySelectorAll(".rig-expression")) {
      addSpring(
        image,
        "opacity",
        image.dataset.expression === expression ? 0 : 0,
        image.dataset.expression === expression ? 1 : 0,
        start,
        140
      );
    }
    // A head nod is a facial/body gesture; blink timing uses a deterministic short sequence.
    const head = parts.get("head");
    if (action.gesture === "nod" && head) partTransform(head, 0, 8, start, 500);
    const eyes = parts.get("eyes");
    if (eyes) addKeyframes(eyes, { scaleY: [1, 0.12, 1] }, start + Math.min(1, sceneDuration * 0.4), 180);
  }
}

// HyperFrames discovers Motion's native Web Animations through its WAAPI adapter.
// These animations are created paused, with fixed finite timing and deterministic keyframes.
window.__vpMotionDiagnostics = {
  keyframeAnimations: keyframes.length,
  springAnimations: springAnimations.length,
  fps: frameRate,
  duration: totalDuration
};
