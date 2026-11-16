import { registerMotionTimeline } from "./motion-timeline.js";
import { renderSceneIllustration, syncSceneIllustration } from "./illustrations.js";

const root = document.getElementById("root");

if (!root) throw new Error("The HyperFrames composition root was not found.");

const DURATION = Number(root.dataset.duration);
if (!Number.isFinite(DURATION) || DURATION < 1) {
  throw new Error("The full-track composition needs a valid audio-derived duration.");
}
// Ambient Motion elements are stretched across the full source track.
// Narrative scene changes use Kokoro sentence/word timestamps directly; no scene is looped.
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
const narrationContextPresent = Boolean(contentConfig.narration_engine || contentConfig.narration_voice);
const isNarratedExplainer =
  contentConfig.narration_engine === "Kokoro-82M" &&
  contentConfig.narration_voice === "af_heart" &&
  narrationWords.length > 0;
if (narrationContextPresent && !isNarratedExplainer) {
  throw new Error("The explainer composition requires valid Kokoro af_heart word timings.");
}
if (captionKicker) {
  captionKicker.textContent = isNarratedExplainer
    ? "KOKORO · WORD-SYNCHRONISED EXPLANATION"
    : "MOTION + HYPERFRAMES VISUAL TEST";
}

// The explainer diagram is data-driven. It only displays facts supplied by the
// approved planner; it never manufactures measurements or process steps.
function makeDiagramNode(label, value = "", index = 0) {
  const node = document.createElement("div");
  node.className = "diagram-node";
  node.dataset.diagramIndex = String(index);
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
  const visualMode = String(scene?.visual_mode || "").toLowerCase();
  diagramItems.dataset.diagramKind = kind || visualMode || "explanation";

  if (["room_acoustics", "signal_chain", "violin_performance_2d"].includes(kind)) {
    const illustration = renderSceneIllustration(scene, contentConfig.topic);
    diagramItems.replaceChildren(illustration);
    return;
  }

  if (!kind && visualMode === "waveform") {
    // Decorative signal bars, not measured audio data.
    const levels = [
      18, 34, 27, 58, 39, 76, 45, 90, 56, 72,
      38, 84, 50, 96, 62, 78, 42, 68, 31, 88,
      48, 74, 36, 60, 28, 82, 46, 70, 32, 54
    ];
    levels.forEach((level, index) => {
      const bar = document.createElement("span");
      bar.className = "wave-bar";
      bar.dataset.diagramIndex = String(index);
      bar.style.height = level + "%";
      diagramItems.appendChild(bar);
    });
    return;
  }

  if (kind === "process_flow" && items.length >= 2) {
    items.forEach((item, index) => {
      diagramItems.appendChild(makeDiagramNode(item.label, "", index));
      if (index < items.length - 1) {
        const arrow = document.createElement("span");
        arrow.className = "diagram-arrow";
        arrow.dataset.diagramIndex = String(index + 0.5);
        arrow.textContent = "→";
        diagramItems.appendChild(arrow);
      }
    });
    return;
  }

  if (kind === "comparison" && items.length >= 2) {
    diagramItems.appendChild(makeDiagramNode(items[0].label, items[0].display || "", 0));
    const divider = document.createElement("span");
    divider.className = "diagram-vs";
    divider.dataset.diagramIndex = "0.5";
    divider.textContent = "VS";
    diagramItems.appendChild(divider);
    diagramItems.appendChild(makeDiagramNode(items[1].label, items[1].display || "", 1));
    return;
  }

  if (kind === "arch_heights" && items.length >= 2) {
    const values = items.map((item) => Math.max(0, Number(item.value) || 0));
    const maximum = Math.max(...values, 1);
    items.forEach((item, index) => {
      const node = makeDiagramNode(item.label, item.display || "", index);
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
  const fallbackText = [scene?.caption, scene?.graphic_detail]
    .filter((part) => typeof part === "string" && part.trim())
    .join(" — ");
  fallback.textContent = fallbackText || contentConfig.topic || "MOTION + HYPERFRAMES VISUAL TEST";
  diagramItems.appendChild(fallback);
}

function sceneTimingRange(sceneIndex) {
  if (narrationWords.length) {
    const sentenceMinimum = sceneIndex === 0 ? 0 : sceneIndex === 1 ? 1 : 3;
    const sentenceMaximum = sceneIndex === 0 ? 0 : sceneIndex === 1 ? 2 : Number.POSITIVE_INFINITY;
    const cues = narrationWords.filter((cue) => {
      const sentence = Number(cue.sentence_index || 0);
      return sentence >= sentenceMinimum && sentence <= sentenceMaximum;
    });
    if (cues.length) {
      return {
        start: Number(cues[0].start),
        end: Number(cues[cues.length - 1].end),
      };
    }
  }
  return {
    start: DURATION * sceneIndex / 3,
    end: DURATION * (sceneIndex + 1) / 3,
  };
}

// Reveal each approved process step as its corresponding sentence is spoken.
// The result is a pure function of the seek time, so random-access rendering is
// deterministic and does not depend on previous frames.
function syncDiagramMotion(seconds, sceneIndex) {
  const children = Array.from(diagramItems.children);
  if (!children.length) return;
  const range = sceneTimingRange(sceneIndex);
  const span = Math.max(0.6, range.end - range.start);
  const progress = Math.max(0, Math.min(1, (seconds - range.start) / span));
  const diagramNodeCount = children.filter((element) => element.classList.contains("diagram-node")).length;
  const revealCount = diagramNodeCount || children.length;
  children.forEach((element) => {
    const rawIndex = Number(element.dataset.diagramIndex || 0);
    const revealAt = Math.max(0, Math.min(0.82, (rawIndex / Math.max(1, revealCount)) * 0.82));
    const reveal = Math.max(0, Math.min(1, (progress - revealAt) / 0.12));
    element.style.opacity = reveal.toFixed(4);
    if (element.classList.contains("diagram-arrow")) {
      element.style.transform = "translateX(" + ((1 - reveal) * 14).toFixed(2) + "px)";
    } else {
      element.style.transform = "translateY(" + ((1 - reveal) * 22).toFixed(2) + "px) scale(" +
        (0.96 + reveal * 0.04).toFixed(4) + ")";
    }
    const bar = element.querySelector(".diagram-bar");
    if (bar) {
      bar.style.transformOrigin = "center bottom";
      bar.style.transform = "scaleY(" + reveal.toFixed(4) + ")";
    }
  });
  const illustration = diagramItems.querySelector(".scene-illustration");
  if (illustration) syncSceneIllustration(illustration, seconds, progress);
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

  // The spoken sentence is the single source of truth for every narrative
  // visual: title, diagram, explanatory labels and word captions all move on
  // the same native Kokoro clock.
  const nextIndex = sceneIndexForSentence(Number(cue?.sentence_index || 0));
  const scene = scenes[nextIndex] || scenes[Math.min(nextIndex, scenes.length - 1)] || {};
  const sceneRange = sceneTimingRange(nextIndex);
  const timedReveal = Math.max(0, Math.min(1, (seconds - sceneRange.start) / 0.48));
  // Keep the opening frame usable as the video's thumbnail.
  const sceneReveal = nextIndex === 0 ? 1 : timedReveal;

  const finalNarrationEnd = narrationWords.length
    ? Number(narrationWords[narrationWords.length - 1].end)
    : DURATION;
  const outroStart = finalNarrationEnd + 0.12;
  const outroReveal = isNarratedExplainer
    ? Math.max(0, Math.min(1, (seconds - outroStart) / 0.38))
    : 0;
  const outroVisible = outroReveal > 0;

  sceneHeadlines.forEach((headline, index) => {
    if (!headline) return;
    const active = !outroVisible && index === nextIndex;
    headline.style.opacity = active ? "1" : "0";
    headline.querySelectorAll(".eyebrow, h1, h2, .headline-note").forEach((element) => {
      element.style.opacity = active ? sceneReveal.toFixed(4) : "0";
      element.style.transform = active
        ? "translateY(" + ((1 - sceneReveal) * 18).toFixed(2) + "px)"
        : "translateY(18px)";
    });
  });

  const diagramPanel = document.getElementById("wave-section");
  if (diagramPanel) {
    diagramPanel.style.opacity = outroVisible ? "0" : sceneReveal.toFixed(4);
    diagramPanel.style.transform = outroVisible
      ? "translateY(-12px)"
      : "translateY(" + ((1 - sceneReveal) * 18).toFixed(2) + "px)";
    diagramPanel.querySelectorAll(".wave-caption, .wave-foot").forEach((element) => {
      element.style.opacity = outroVisible ? "0" : sceneReveal.toFixed(4);
      element.style.transform = "none";
    });
  }

  setContentText("#wave-section .wave-caption-right", String(nextIndex + 1) + " / 03", 12);
  setContentText("#diagram-detail-left", scene.graphic_detail || scene.caption, 42);
  setContentText("#diagram-detail-right", scene.graphic_label || "THE EXPLANATION", 42);

  const endCard = document.getElementById("end-card");
  if (endCard) {
    endCard.style.opacity = outroReveal.toFixed(4);
    endCard.style.transform = "translateY(" + ((1 - outroReveal) * 22).toFixed(2) + "px)";
    endCard.querySelectorAll(".end-name, .end-kicker, .end-subtitle, .end-rule").forEach((element) => {
      element.style.opacity = outroReveal.toFixed(4);
    });
  }

  if (nextIndex !== lastSceneIndex) {
    renderDiagram(scene);
    lastSceneIndex = nextIndex;
  }
  syncDiagramMotion(seconds, nextIndex);
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
  ["#top-mark", { y: [-18, 0] }, { duration: 0.72, ease: "easeOut", at: 0 }],
  ["#top-rule", { scaleX: [0, 1] }, { duration: 0.9, ease: "easeOut", at: 0.32 }],
  ["#haze-a", { x: [-34, 24, -8], y: [24, -12, 10], scale: [0.92, 1.08, 1] }, { duration: 10, ease: "linear", times: [0, 0.55, 1], at: 0 }],
  ["#haze-b", { x: [26, -24, 12], y: [-12, 18, -4], scale: [1.05, 0.94, 1.02] }, { duration: 10, ease: "linear", times: [0, 0.5, 1], at: 0 }],
  ["#orbit", { opacity: [0, 0.68, 0.42], scale: [0.82, 1.03, 1.1], rotate: [0, 18, 42] }, { duration: 8.2, ease: "linear", times: [0, 0.42, 1], at: 1.15 }],
  ["#orbit .orbit-arc", { opacity: [0, 1, 0.45], pathLength: [0, 1, 1] }, { duration: 4.2, ease: "easeOut", times: [0, 0.6, 1], at: 1.8 }],
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

registerMotionTimeline({
  root,
  sequence,
  duration: DURATION,
  onSeek(seconds) {
    syncScene(seconds);
    syncNarrationCaption(seconds);
  }
});
