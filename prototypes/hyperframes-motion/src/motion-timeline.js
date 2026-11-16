import { animate } from "motion";

const MOTION_REFERENCE_DURATION_SECONDS = 10;

/**
 * Keep Motion's animation runtime outside the HyperFrames composition document.
 * HyperFrames owns frame capture and deterministically seeks this registered
 * adapter; Motion owns the visual animation interpolation.
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

  if (progressTime) progressTime.textContent = formatTimestamp(durationSeconds);

  let lastTime = 0;

  function seek(seconds) {
    const safeTime = Math.max(0, Math.min(durationSeconds, Number(seconds) || 0));
    motionTimeline.time = safeTime;

    if (progressFill) {
      progressFill.style.transform = "scaleX(" + (safeTime / durationSeconds).toFixed(8) + ")";
    }
    if (typeof onSeek === "function") onSeek(safeTime);
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
      return durationSeconds;
    },
    progress(value) {
      if (typeof value === "number") seek(value * durationSeconds);
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
