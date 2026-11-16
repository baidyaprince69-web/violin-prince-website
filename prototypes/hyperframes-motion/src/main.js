import { registerMotionTimeline } from "./motion-timeline.js";
import { renderSceneIllustration, syncSceneIllustration } from "./illustrations.js";

const root = document.getElementById("root");
if (!root) throw new Error("The HyperFrames composition root was not found.");

const DURATION = Number(root.dataset.duration);
if (!Number.isFinite(DURATION) || DURATION < 1) {
  throw new Error("The portrait composition needs a valid audio-derived duration.");
}

const contentNode = document.getElementById("vp-content-config");
let contentConfig = {};
if (contentNode) {
  try {
    contentConfig = JSON.parse(contentNode.textContent || "{}");
  } catch {
    throw new Error("The Autopilot content context is not valid JSON.");
  }
}

const scenes = Array.isArray(contentConfig.scenes) ? contentConfig.scenes.slice(0, 5) : [];
const narrationWords = Array.isArray(contentConfig.narration_words)
  ? contentConfig.narration_words.filter((cue) =>
      cue && typeof cue.text === "string" &&
      Number.isFinite(Number(cue.start)) && Number.isFinite(Number(cue.end)) &&
      Number(cue.start) >= 0 && Number(cue.end) > Number(cue.start)
    )
  : [];
const narrationEndSeconds = narrationWords.reduce(
  (latest, cue) => Math.max(latest, Number(cue.end) || 0), 0
);
const narrationContextPresent = Boolean(contentConfig.narration_engine || contentConfig.narration_voice);
const isNarratedExplainer =
  contentConfig.narration_engine === "Kokoro-82M" &&
  contentConfig.narration_voice === "af_heart" &&
  narrationWords.length > 0;

if (narrationContextPresent && !isNarratedExplainer) {
  throw new Error("The explainer composition requires valid Kokoro af_heart word timings.");
}
if (!scenes.length) {
  throw new Error("The portrait explainer needs at least one approved storyboard scene.");
}

function cleanText(value, fallback, limit = 90) {
  return typeof value === "string" && value.trim()
    ? value.trim().replace(/\s+/g, " ").slice(0, limit)
    : fallback;
}

const maxSentenceIndex = narrationWords.reduce(
  (max, cue) => Math.max(max, Number(cue.sentence_index) || 0), 0
);
const sceneSentenceIndices = scenes.map((scene, index) => {
  const declared = Number(scene.sentence_index);
  if (Number.isInteger(declared) && declared >= 0) return declared;
  return scenes.length === 1
    ? 0
    : Math.round(index * maxSentenceIndex / (scenes.length - 1));
});

const sceneArt = document.getElementById("diagram-items");
const sceneKicker = document.getElementById("scene-kicker");
const sceneTitle = document.getElementById("scene-title");
const sceneDescription = document.getElementById("scene-description");
const sceneCounter = document.getElementById("scene-counter");
const captionLine = document.getElementById("caption-line");
const progressTime = document.getElementById("progress-time");
const progressFill = document.getElementById("progress-fill");

if (!sceneArt || !sceneKicker || !sceneTitle || !sceneDescription || !captionLine || !progressFill) {
  throw new Error("The portrait composition is missing a required scene or caption layer.");
}

const sceneSentenceFractions = scenes.map((scene) => {
  const fraction = Number(scene.sentence_fraction);
  return Number.isFinite(fraction) ? Math.max(0, Math.min(0.95, fraction)) : 0;
});

function sceneStartTime(sceneIndex) {
  const sentenceIndex = sceneSentenceIndices[sceneIndex] ?? 0;
  const cues = narrationWords.filter((cue) =>
    (Number(cue.sentence_index) || 0) === sentenceIndex
  );
  if (cues.length) {
    const sentenceStart = Number(cues[0].start);
    const sentenceEnd = Number(cues[cues.length - 1].end);
    return sentenceStart + (sentenceEnd - sentenceStart) * sceneSentenceFractions[sceneIndex];
  }
  return DURATION * sceneIndex / scenes.length;
}

function sceneIndexForCue(cue, seconds) {
  if (!narrationWords.length) {
    let timedIndex = 0;
    for (let index = 0; index < scenes.length; index += 1) {
      if (seconds >= DURATION * index / scenes.length) timedIndex = index;
    }
    return timedIndex;
  }
  const sentenceIndex = Number(cue?.sentence_index || 0);
  const cueStart = Number(cue?.start || 0);
  let active = 0;
  for (let index = 0; index < scenes.length; index += 1) {
    const sceneSentence = sceneSentenceIndices[index];
    if (
      sentenceIndex > sceneSentence ||
      (sentenceIndex === sceneSentence && cueStart >= sceneStartTime(index))
    ) active = index;
  }
  return active;
}

function sceneTimingRange(sceneIndex) {
  return {
    start: sceneStartTime(sceneIndex),
    end: sceneIndex + 1 < scenes.length ? sceneStartTime(sceneIndex + 1) : DURATION
  };
}

function measureSceneSubject(svg, scene, index) {
  const subject = svg.querySelector(".scene-subject");
  if (!subject || typeof subject.getBBox !== "function") {
    throw new Error("Scene " + (index + 1) + " has no measurable subject group.");
  }
  const bounds = subject.getBBox();
  const widthRatio = bounds.width / 1080;
  const heightRatio = bounds.height / 1920;
  const metrics = {
    scene: index + 1,
    type: String(scene?.graphic_data?.type || "illustration"),
    subject_width_px: Math.round(bounds.width),
    subject_height_px: Math.round(bounds.height),
    subject_width_ratio: Number(widthRatio.toFixed(3)),
    subject_height_ratio: Number(heightRatio.toFixed(3))
  };
  if (bounds.width < 420 || bounds.height < 760) {
    throw new Error(
      "Scene " + (index + 1) + " subject is too small for phone viewing: " +
      JSON.stringify(metrics)
    );
  }
  svg.dataset.subjectWidth = String(Math.round(bounds.width));
  svg.dataset.subjectHeight = String(Math.round(bounds.height));
  window.__vpVisualQa = window.__vpVisualQa || { scenes: {} };
  window.__vpVisualQa.scenes[String(index + 1)] = metrics;
  root.dataset.visualQaSceneCount = String(Object.keys(window.__vpVisualQa.scenes).length);
}

function renderScene(scene, index) {
  const svg = renderSceneIllustration(scene, contentConfig.topic || "");
  sceneArt.replaceChildren(svg);
  measureSceneSubject(svg, scene, index);
  return svg;
}

function syncNarrationCaption(seconds) {
  if (narrationWords.length &&
      seconds > narrationEndSeconds + 0.18) {
    captionLine.replaceChildren();
    return;
  }
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

let activeSceneIndex = -1;
let activeIllustration = null;

function syncScene(seconds) {
  let cue = narrationWords[0];
  for (const word of narrationWords) {
    if (Number(word.start) <= seconds) cue = word;
    else break;
  }
  const narrationFinished = narrationWords.length > 0 &&
    seconds >= narrationEndSeconds - 0.02;
  const nextIndex = narrationFinished
    ? scenes.length - 1
    : Math.min(scenes.length - 1, sceneIndexForCue(cue, seconds));
  const scene = scenes[nextIndex];
  const range = sceneTimingRange(nextIndex);
  const span = Math.max(0.8, range.end - range.start);
  const progress = Math.max(0, Math.min(1, (seconds - range.start) / span));
  const reveal = nextIndex === 0 ? 1 : Math.max(0, Math.min(1, (seconds - range.start) / 0.55));

  if (nextIndex !== activeSceneIndex) {
    activeIllustration = renderScene(scene, nextIndex);
    activeSceneIndex = nextIndex;
  }

  sceneKicker.textContent = cleanText(scene.graphic_label, "THE EXPLANATION", 42);
  sceneTitle.textContent = cleanText(scene.caption, contentConfig.title || contentConfig.topic || "A MUSIC IDEA, EXPLAINED", 72);
  sceneDescription.textContent = cleanText(scene.graphic_detail, contentConfig.hook || "", 105);
  if (sceneCounter) {
    sceneCounter.textContent = String(nextIndex + 1).padStart(2, "0") + " / " +
      String(scenes.length).padStart(2, "0");
  }

  const titleOpacity = nextIndex === 0 ? 1 : reveal;
  sceneKicker.style.opacity = titleOpacity.toFixed(4);
  sceneTitle.style.opacity = titleOpacity.toFixed(4);
  sceneDescription.style.opacity = titleOpacity.toFixed(4);
  sceneTitle.style.transform = "translateY(" + ((1 - titleOpacity) * 18).toFixed(2) + "px)";

  if (activeIllustration) {
    activeIllustration.style.opacity = reveal.toFixed(4);
    const illustrationProgress = nextIndex === 0 ? Math.max(progress, 0.18) : progress;
    syncSceneIllustration(activeIllustration, seconds, illustrationProgress, nextIndex);
  }
  syncNarrationCaption(seconds);
}

function formatTimestamp(seconds) {
  const safe = Math.max(0, Math.ceil(seconds));
  const minutes = Math.floor(safe / 60);
  return String(minutes).padStart(2, "0") + ":" + String(safe % 60).padStart(2, "0");
}

progressTime.textContent = formatTimestamp(DURATION);
syncScene(0);

const sequence = [
  ["#top-mark", { y: [-16, 0], opacity: [0, 1] }, { duration: 0.75, ease: "easeOut", at: 0 }],
  ["#top-rule", { scaleX: [0, 1] }, { duration: 0.8, ease: "easeOut", at: 0.25 }],
  ["#haze-a", { x: [-26, 18, -8], y: [18, -10, 8], scale: [0.94, 1.08, 1] }, { duration: 10, ease: "linear", times: [0, 0.55, 1], at: 0 }],
  ["#haze-b", { x: [18, -20, 8], y: [-8, 15, -4], scale: [1.04, 0.94, 1.02] }, { duration: 10, ease: "linear", times: [0, 0.5, 1], at: 0 }],
  ["#top-rule", { opacity: [0.45, 0.85, 0.45] }, { duration: 10, ease: "linear", times: [0, 0.5, 1], at: 0 }]
];

registerMotionTimeline({
  root,
  sequence,
  duration: DURATION,
  onSeek(seconds) {
    progressFill.style.transform = "scaleX(" + (seconds / DURATION).toFixed(8) + ")";
    syncScene(seconds);
  }
});
