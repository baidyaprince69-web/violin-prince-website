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
    element.textContent = value.trim().replace(/\s+/g, " ").slice(0, maxChars);
  }
}
const scenes = Array.isArray(contentConfig.scenes) ? contentConfig.scenes.slice(0, 3) : [];
const sceneCaptions = Array.isArray(contentConfig.captions) ? contentConfig.captions : [];
const narrationWords = Array.isArray(contentConfig.narration_words)
  ? contentConfig.narration_words.filter((cue) =>
      cue && typeof cue.text === "string" &&
      Number.isFinite(Number(cue.start)) && Number.isFinite(Number(cue.end)) &&
      Number(cue.start) >= 0 && Number(cue.end) > Number(cue.start)
    )
  : [];
setContentText("#top-mark .top-index", "RESEARCH / EXPLAINED / ANIMATED", 36);
setContentText("#headline-one .eyebrow", scenes[0]?.graphic_label || "THE QUESTION", 32);
setContentText("#explainer-title", contentConfig.title || contentConfig.topic, 48);
setContentText("#headline-one .headline-note", contentConfig.hook, 110);
setContentText(
  "#wave-section .wave-caption > span:first-child",
  scenes[0]?.graphic_label || scenes[0]?.caption || contentConfig.topic,
  38,
);
setContentText("#diagram-detail-left", scenes[0]?.graphic_detail || "THE MECHANISM", 32);
setContentText("#diagram-detail-right", scenes[1]?.graphic_label || "STEP BY STEP", 32);
setContentText("#headline-two .eyebrow", scenes[1]?.graphic_label || "THE EXPLANATION", 32);
setContentText("#scene-two-title", scenes[1]?.caption || sceneCaptions[1], 60);
setContentText("#headline-two .headline-note", scenes[1]?.graphic_detail || "", 110);
setContentText("#headline-three .eyebrow", scenes[2]?.graphic_label || "THE TAKEAWAY", 32);
setContentText("#scene-three-title", scenes[2]?.caption || sceneCaptions[2], 60);
setContentText("#headline-three .headline-note", scenes[2]?.graphic_detail || "", 110);
setContentText("#bottom-progress .progress-label", contentConfig.topic, 48);

const waveform = document.getElementById("waveform");
const diagramItems = document.getElementById("diagram-items");
const particleLayer = document.getElementById("particle-layer");
const captionLine = document.getElementById("caption-line");
const captionKicker = document.getElementById("caption-kicker");
if (!waveform || !diagramItems || !particleLayer || !captionLine) {
  throw new Error("The prototype explainer layers are incomplete.");
}
if (contentConfig.narration_engine !== "Kokoro-82M" || contentConfig.narration_voice !== "af_heart" || narrationWords.length === 0) {
  throw new Error("The explainer composition requires Kokoro af_heart word timings.");
}
if (captionKicker) captionKicker.textContent = "KOKORO · WORD-SYNCHRONISED EXPLANATION";

// The explainer diagram is data-driven. It only displays facts supplied by the
// approved planner; it never manufactures measurements or process steps.
function makeDiagramNode(label, value = "") {
  const node = document.createElement("div");
  node.className = "diagram-node";
  const title = document.createElement("span");
  title.className = "diagram-node-label";
  title.textContent = label || "Key detail";
  node.appendChild(title);
  if (value) {
    const detail = document.createElement("span");
    detail.className = "diagram-node-value";
    detail.textContent = value;
    node.appendChild(detail);
  }
  return node;
}

function renderDiagram(scene) {
  diagramItems.replaceChildren();
  const graphic = scene && scene.graphic_data && typeof scene.graphic_data === "object"
    ? scene.graphic_data
    : {};
  const items = Array.isArray(graphic.items) ? graphic.items.slice(0, 4) : [];
  const kind = String(graphic.type || "").toLowerCase();

  if (kind === "process_flow" && items.length >= 2) {
    items.forEach((item, index) => {
      diagramItems.appendChild(makeDiagramNode(item.label, ""));
      if (index < items.length - 1) {
        const arrow = document.createElement("span");
        arrow.className = "diagram-arrow";
        arrow.textContent = "→";
        diagramItems.appendChild(arrow);
      }
    });
    return;
  }

  if (kind === "arch_heights" && items.length >= 2) {
    const values = items.map((item) => Math.max(0, Number(item.value) || 0));
    const maximum = Math.max(...values, 1);
    items.forEach((item, index) => {
      const node = makeDiagramNode(item.label, item.display || "");
      const track = document.createElement("div");
      track.className = "diagram-bar-track";
      const bar = document.createElement("div");
      bar.className = "diagram-bar";
      bar.style.height = Math.max(8, Math.round(values[index] / maximum * 100)) + "%";
      track.appendChild(bar);
      node.insertBefore(track, node.lastChild);
      diagramItems.appendChild(node);
    });
    return;
  }

  const fallback = document.createElement("div");
  fallback.className = "diagram-fallback";
  fallback.textContent = (scene?.caption || contentConfig.topic || "") +
    (scene?.graphic_detail ? " — " + scene.graphic_detail : "");
  diagramItems.appendChild(fallback);
}

function sceneIndexForSentence(sentenceIndex) {
  if (sentenceIndex <= 0) return 0;
  if (sentenceIndex >= 3) return 2;
  return 1;
}

let lastSceneIndex = -1;
const sceneHeadlines = [
  document.getElementById("headline-one"),
  document.getElementById("headline-two"),
  document.getElementById("headline-three"),
];
function syncScene(seconds) {
  let cue = narrationWords[0];
  for (const word of narrationWords) {
    if (Number(word.start) <= seconds) cue = word;
    else break;
  }
  const nextIndex = sceneIndexForSentence(Number(cue?.sentence_index || 0));
  sceneHeadlines.forEach((headline, index) => {
    if (!headline) return;
    headline.style.opacity = index === nextIndex ? "1" : "0";
    headline.querySelectorAll(".eyebrow, h1, h2, .headline-note").forEach((element) => {
      element.style.opacity = "1";
      element.style.transform = "none";
    });
  });
  const diagramPanel = document.getElementById("wave-section");
  if (diagramPanel) {
    diagramPanel.style.opacity = "1";
    diagramPanel.style.transform = "none";
    diagramPanel.querySelectorAll(".wave-caption, .wave-foot").forEach((element) => {
      element.style.opacity = "1";
      element.style.transform = "none";
    });
  }
  if (nextIndex !== lastSceneIndex) {
    renderDiagram(scenes[nextIndex] || scenes[Math.min(nextIndex, scenes.length - 1)] || {});
    lastSceneIndex = nextIndex;
  }
}

function syncNarrationCaption(seconds) {
  let activeIndex = -1;
  for (let index = 0; index < narrationWords.length; index += 1) {
    const cue = narrationWords[index];
    if (seconds >= Number(cue.start) && seconds <= Number(cue.end)) {
      activeIndex = index;
      break;
    }
    if (Number(cue.start) <= seconds) activeIndex = index;
  }
  captionLine.replaceChildren();
  if (activeIndex < 0) return;
  const first = Math.max(0, activeIndex - 1);
  const last = Math.min(narrationWords.length, activeIndex + 2);
  for (let index = first; index < last; index += 1) {
    const word = document.createElement("span");
    word.className = index === activeIndex
      ? "caption-word caption-word-active"
      : "caption-word";
    word.textContent = narrationWords[index].text;
    captionLine.appendChild(word);
  }
}

syncScene(0);
syncNarrationCaption(0);

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
  syncScene(safeTime);
  syncNarrationCaption(safeTime);
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
