import { animate } from "motion";

const ROOT_ID = "vp-motion-dynamic";
const root = document.getElementById("root");

if (!root) throw new Error("The HyperFrames composition root was not found.");

const DURATION = Number(root.dataset.duration);
if (!Number.isFinite(DURATION) || DURATION < 1) {
  throw new Error("The full-track composition needs a valid audio-derived duration.");
}
// The authored ten-second sequence is stretched across the source track once.
// HyperFrames seeks on the complete timeline; no modulo/repeat loop is used.
const BASE_SEQUENCE_DURATION = 10;
const TIMELINE_SCALE = DURATION / BASE_SEQUENCE_DURATION;

const contentNode = document.getElementById("vp-content-config");
let contentConfig = {};
if (contentNode) {
  try {
    contentConfig = JSON.parse(contentNode.textContent || "{}");
  } catch {
    throw new Error("The Autopilot content context is not valid JSON.");
  }
}
function setContentText(selector, value, maxChars = 42) {
  const element = document.querySelector(selector);
  if (element && typeof value === "string" && value.trim()) {
    element.textContent = value.trim().replace(/\\s+/g, " ").slice(0, maxChars);
  }
}
const sceneCaptions = Array.isArray(contentConfig.captions) ? contentConfig.captions : [];
const shortHook = typeof contentConfig.hook === "string"
  ? contentConfig.hook.trim().split(/\\s+/).slice(0, 4).join(" ")
  : "";
setContentText("#headline-one .headline-note", shortHook, 32);
setContentText("#wave-section .wave-caption > span:first-child", contentConfig.topic, 25);
setContentText("#headline-two h2", sceneCaptions[0], 24);
setContentText("#headline-two .headline-note", sceneCaptions[1], 38);
setContentText(
  "#bottom-progress .progress-label",
  sceneCaptions[2] || contentConfig.title || contentConfig.topic,
  26,
);

const waveform = document.getElementById("waveform");
const particleLayer = document.getElementById("particle-layer");
if (!waveform || !particleLayer) throw new Error("The prototype visual layers are incomplete.");

// Fixed arithmetic keeps every generated visual identical across renders.
const barCount = 56;
for (let index = 0; index < barCount; index += 1) {
  const bar = document.createElement("span");
  bar.className = "wave-bar";
  bar.id = "wave-bar-" + index;
  waveform.appendChild(bar);
}

const particleCount = 18;
for (let index = 0; index < particleCount; index += 1) {
  const particle = document.createElement("span");
  particle.className = "particle";
  particle.id = "particle-" + index;
  particle.style.left = ((index * 47 + 13) % 94 + 3) + "%";
  particle.style.top = ((index * 31 + 17) % 88 + 6) + "%";
  particleLayer.appendChild(particle);
}

const sequence = [
  ["#top-mark", { opacity: [0, 1], y: [-18, 0] }, { duration: 0.72, ease: "easeOut", at: 0.12 }],
  ["#top-rule", { scaleX: [0, 1] }, { duration: 0.9, ease: "easeOut", at: 0.32 }],
  ["#haze-a", { x: [-34, 24, -8], y: [24, -12, 10], scale: [0.92, 1.08, 1] }, { duration: 10, ease: "linear", times: [0, 0.55, 1], at: 0 }],
  ["#haze-b", { x: [26, -24, 12], y: [-12, 18, -4], scale: [1.05, 0.94, 1.02] }, { duration: 10, ease: "linear", times: [0, 0.5, 1], at: 0 }],
  ["#headline-one .eyebrow", { opacity: [0, 1], x: [-20, 0] }, { duration: 0.7, ease: "easeOut", at: 0.62 }],
  ["#headline-one h1", { opacity: [1, 1], y: [18, 0], scale: [0.97, 1] }, { duration: 1.1, ease: "easeOut", at: 0 }],
  ["#headline-one .headline-note", { opacity: [0, 1], y: [16, 0] }, { duration: 0.7, ease: "easeOut", at: 1.62 }],
  ["#wave-section", { opacity: [0, 1], y: [34, 0] }, { duration: 0.9, ease: "easeOut", at: 1.72 }],
  ["#wave-section .wave-caption", { opacity: [0, 1], x: [-18, 0] }, { duration: 0.6, ease: "easeOut", at: 2.02 }],
  ["#wave-section .wave-foot", { opacity: [0, 1] }, { duration: 0.7, ease: "easeOut", at: 2.15 }],
  ["#wave-section", { opacity: [1, 0], y: [0, -24] }, { duration: 0.55, ease: "easeIn", at: 3.18 }],
  ["#orbit", { opacity: [0, 0.68, 0.42], scale: [0.82, 1.03, 1.1], rotate: [0, 18, 42] }, { duration: 8.2, ease: "linear", times: [0, 0.42, 1], at: 1.15 }],
  ["#orbit .orbit-arc", { opacity: [0, 1, 0.45], pathLength: [0, 1, 1] }, { duration: 4.2, ease: "easeOut", times: [0, 0.6, 1], at: 1.8 }],
  ["#headline-one", { opacity: [1, 0] }, { duration: 0.55, ease: "easeIn", at: 3.22 }],
  ["#headline-two .eyebrow", { opacity: [0, 1], x: [-20, 0] }, { duration: 0.6, ease: "easeOut", at: 3.55 }],
  ["#headline-two h2", { opacity: [0, 1], y: [42, 0] }, { duration: 0.9, ease: "easeOut", at: 3.78 }],
  ["#headline-two .headline-note", { opacity: [0, 1], y: [14, 0] }, { duration: 0.65, ease: "easeOut", at: 4.45 }],
  ["#headline-two", { opacity: [1, 0] }, { duration: 0.55, ease: "easeIn", at: 6.28 }],
  ["#headline-three .eyebrow", { opacity: [0, 1], x: [-18, 0] }, { duration: 0.6, ease: "easeOut", at: 6.58 }],
  ["#headline-three h2", { opacity: [0, 1], y: [36, 0] }, { duration: 0.9, ease: "easeOut", at: 6.78 }],
  ["#headline-three .headline-note", { opacity: [0, 1] }, { duration: 0.65, ease: "easeOut", at: 7.2 }],
  ["#headline-three", { opacity: [1, 0] }, { duration: 0.48, ease: "easeIn", at: 7.72 }],
  ["#end-card", { opacity: [0, 1], y: [22, 0] }, { duration: 0.65, ease: "easeOut", at: 7.95 }],
  ["#end-card .end-rule", { scaleX: [0, 1] }, { duration: 0.55, ease: "easeOut", at: 8.0 }],
  ["#end-card .end-name", { opacity: [0, 1], y: [18, 0] }, { duration: 0.5, ease: "easeOut", at: 8.15 }]
];

for (let index = 0; index < barCount; index += 1) {
  const phase = (index * 13) % 17;
  const peak = 0.42 + (phase / 17) * 0.72;
  const dip = 0.14 + ((index * 7) % 11) / 42;
  const peakTwo = 0.38 + ((index * 5) % 19) / 25;
  sequence.push([
    "#wave-bar-" + index,
    {
      scaleY: [0.16, peak, dip, peakTwo, 0.2],
      opacity: [0.28, 0.95, 0.52, 0.9, 0.35]
    },
    {
      duration: 6.8,
      ease: "linear",
      times: [0, 0.22, 0.48, 0.77, 1],
      at: 1.72
    }
  ]);
}

for (let index = 0; index < particleCount; index += 1) {
  const offset = (index % 6) * 13 - 32;
  const rise = 48 + ((index * 23) % 94);
  sequence.push([
    "#particle-" + index,
    {
      opacity: [0, 0.72, 0.16],
      x: [0, offset, offset * -0.35],
      y: [0, -rise, -rise * 1.25],
      scale: [0.5, 1, 0.72]
    },
    {
      duration: 8.6,
      ease: "linear",
      times: [0, 0.56, 1],
      at: 0.7 + (index % 5) * 0.12
    }
  ]);
}

// Motion supplies the seekable animation controls; HyperFrames owns the frame clock.
// This compact adapter exposes the methods used by HyperFrames' timeline registry.
const scaledSequence = sequence.map(([selector, properties, options]) => [
  selector,
  properties,
  {
    ...options,
    duration: options.duration * TIMELINE_SCALE,
    at: (options.at ?? 0) * TIMELINE_SCALE
  }
]);
const motionTimeline = animate(scaledSequence, { autoplay: false });
motionTimeline.pause();

const progressFill = document.getElementById("progress-fill");
const progressTime = document.querySelector("#bottom-progress .progress-time");

function formatTimestamp(seconds) {
  const totalSeconds = Math.max(0, Math.ceil(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainder = totalSeconds % 60;
  return String(minutes).padStart(2, "0") + ":" + String(remainder).padStart(2, "0");
}

if (progressTime) progressTime.textContent = formatTimestamp(DURATION);

let lastTime = 0;

function seek(seconds) {
  const safeTime = Math.max(0, Math.min(DURATION, Number(seconds) || 0));
  // Seek directly on the complete, stretched composition timeline.
  motionTimeline.time = safeTime;

  if (progressFill) {
    progressFill.style.transform = "scaleX(" + (safeTime / DURATION).toFixed(8) + ")";
  }
  lastTime = safeTime;
}

const timelineAdapter = {
  pause() {
    motionTimeline.pause();
    return timelineAdapter;
  },
  totalTime(seconds) {
    if (typeof seconds === "number") seek(seconds);
    return lastTime;
  },
  time(seconds) {
    if (typeof seconds === "number") {
      seek(seconds);
      return timelineAdapter;
    }
    return lastTime;
  },
  duration() {
    return DURATION;
  },
  progress(value) {
    if (typeof value === "number") seek(value * DURATION);
    return lastTime / DURATION;
  },
  kill() {
    motionTimeline.stop();
  }
};

window.__timelines = window.__timelines || {};
window.__timelines[ROOT_ID] = timelineAdapter;
window.__vpMotionAdapterReady = true;
