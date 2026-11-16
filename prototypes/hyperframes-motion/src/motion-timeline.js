import { animate } from "motion";

const MOTION_REFERENCE_DURATION_SECONDS = 10;

/**
 * Keep Motion's animation runtime outside the HyperFrames composition document.
 * HyperFrames seeks this registered adapter for deterministic frame capture;
 * Motion owns visual interpolation and interactive playback.
 */
export function registerMotionTimeline({ root, sequence, duration, onSeek }) {
  const compositionId = root?.dataset?.compositionId;
  const durationSeconds = Number(duration);

  if (!compositionId) {
    throw new Error("The Motion timeline needs a HyperFrames composition ID.");
  }
  if (!Number.isFinite(durationSeconds) || durationSeconds < 1) {
    throw new Error("The Motion timeline needs a valid audio-derived duration.");
  }
  if (!Array.isArray(sequence) || sequence.length === 0) {
    throw new Error("The Motion timeline needs at least one animation sequence.");
  }

  // Ten seconds is only the authored reference length of these ambient
  // animation cues. Scale them to the real composition duration; it is not
  // a ten-second export limit.
  const scale = durationSeconds / MOTION_REFERENCE_DURATION_SECONDS;
  const scaledSequence = sequence.map(([selector, properties, options]) => [
    selector,
    properties,
    {
      ...options,
      duration: options.duration * scale,
      at: (options.at ?? 0) * scale
    }
  ]);

  const progressFill = document.getElementById("progress-fill");
  const progressTime = document.querySelector("#bottom-progress .progress-time");

  function formatTimestamp(seconds) {
    const totalSeconds = Math.max(0, Math.ceil(seconds));
    const minutes = Math.floor(totalSeconds / 60);
    const remainder = totalSeconds % 60;
    return String(minutes).padStart(2, "0") + ":" + String(remainder).padStart(2, "0");
  }

  if (progressTime) progressTime.textContent = formatTimestamp(durationSeconds);

  let lastTime = 0;
  let suppressSeekUpdate = false;

  function clampTime(seconds) {
    return Math.max(0, Math.min(durationSeconds, Number(seconds) || 0));
  }

  function updateVisualState(seconds, notify = true) {
    const safeTime = clampTime(seconds);
    lastTime = safeTime;
    if (progressFill) {
      progressFill.style.transform = "scaleX(" + (safeTime / durationSeconds).toFixed(8) + ")";
    }
    if (notify && !suppressSeekUpdate && typeof onSeek === "function") {
      onSeek(safeTime);
    }
  }

  const motionTimeline = animate(scaledSequence, {
    autoplay: false,
    onUpdate(time) {
      // Motion's own playhead keeps the scene and word captions in sync during
      // preview playback; HyperFrames can still seek the same timeline directly.
      updateVisualState(time);
    }
  });
  motionTimeline.pause();
  updateVisualState(0);

  function seek(seconds, suppressEvents = false) {
    const safeTime = clampTime(seconds);
    suppressSeekUpdate = Boolean(suppressEvents);
    try {
      motionTimeline.time = safeTime;
    } finally {
      suppressSeekUpdate = false;
    }
    updateVisualState(safeTime, !suppressEvents);
    return timelineAdapter;
  }

  const timelineAdapter = {
    // HyperFrames direct-timeline contract.
    duration() {
      return durationSeconds;
    },
    time(seconds) {
      if (typeof seconds === "number") return seek(seconds, false);
      return lastTime;
    },
    seek,
    play() {
      motionTimeline.play();
      return timelineAdapter;
    },
    pause() {
      motionTimeline.pause();
      return timelineAdapter;
    },
    timeScale(scaleValue) {
      if (typeof scaleValue === "number" && Number.isFinite(scaleValue)) {
        motionTimeline.speed = scaleValue;
        return timelineAdapter;
      }
      return motionTimeline.speed;
    },

    // Compatibility methods retained for the pinned HyperFrames renderer.
    totalTime(seconds) {
      if (typeof seconds === "number") return seek(seconds, false);
      return lastTime;
    },
    progress(value) {
      if (typeof value === "number") return seek(value * durationSeconds, false);
      return lastTime / durationSeconds;
    },
    kill() {
      motionTimeline.stop();
    }
  };

  window.__timelines = window.__timelines || {};
  window.__timelines[compositionId] = timelineAdapter;
  window.__vpMotionAdapterReady = true;
  return timelineAdapter;
}
