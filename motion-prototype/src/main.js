import { animate } from "motion";
import { gsap } from "gsap";

const DURATION = 10;
const motionTracks = [];

function addTrack(target, keyframes, options, start = 0) {
  const controls = animate(target, keyframes, { ...options, autoplay: false });
  motionTracks.push({ controls, start });
  return controls;
}

addTrack("#depth-grid", { x: [0, -18, 7], y: [0, 18, -4] }, { duration: 9.8, ease: "easeInOut" });
addTrack("#orbital-ring", { rotate: [-8, 14], scale: [1, 1.08] }, { duration: 9.8, ease: "easeInOut" });
addTrack("#opening", { opacity: [0, 1] }, { duration: 0.25 }, 0);
addTrack(".hero-kicker", { opacity: [0, 1], y: [24, 0] }, { duration: 0.62, ease: "easeOut" }, 0.22);
addTrack("#hero-line-one", { opacity: [0, 1], y: [54, 0], filter: ["blur(12px)", "blur(0px)"] }, { duration: 0.85, ease: "easeOut" }, 0.52);
addTrack("#hero-line-two", { opacity: [0, 1], y: [48, 0], filter: ["blur(12px)", "blur(0px)"] }, { duration: 0.88, ease: "easeOut" }, 0.88);
addTrack("#hero-rule", { scaleX: [0, 1] }, { duration: 0.75, ease: "easeOut" }, 1.38);
addTrack("#hero-note", { opacity: [0, 1], y: [18, 0] }, { duration: 0.72, ease: "easeOut" }, 1.62);
addTrack("#particles-opening .particle", { opacity: [0, 0.78, 0], y: [28, -82], x: [-10, 8] }, { duration: 2.1 }, 0.5);
addTrack("#opening", { opacity: [1, 0], y: [0, -22] }, { duration: 0.52, ease: "easeIn" }, 2.72);

addTrack("#wave-section", { opacity: [0, 1], y: [34, 0] }, { duration: 0.68, ease: "easeOut" }, 2.82);
addTrack("#wave-kicker", { opacity: [0, 1], y: [19, 0] }, { duration: 0.55 }, 3.02);
addTrack("#wave-title", { opacity: [0, 1], y: [42, 0], filter: ["blur(10px)", "blur(0px)"] }, { duration: 0.72, ease: "easeOut" }, 3.18);
addTrack("#wave-subtitle", { opacity: [0, 1], y: [15, 0] }, { duration: 0.6 }, 3.55);
addTrack("#waveform-panel", { opacity: [0, 1], scale: [0.94, 1] }, { duration: 0.68, ease: "easeOut" }, 3.25);
addTrack(".waveform-bar", { scaleY: [0.22, 0.96, 0.34, 0.82] }, { duration: 1.05, repeat: 1, repeatType: "mirror" }, 3.55);
addTrack("#wave-scan", { opacity: [0, 0.9, 0], x: [-210, 510] }, { duration: 2.65, ease: "easeInOut" }, 3.62);
addTrack("#wave-frequency", { opacity: [0, 1], y: [12, 0] }, { duration: 0.62 }, 4.05);
addTrack("#wave-bottom-note", { opacity: [0, 1], y: [22, 0] }, { duration: 0.7 }, 5.62);
addTrack("#particles-wave .particle", { opacity: [0, 0.65, 0], y: [24, -65], x: [7, -12] }, { duration: 2.0 }, 3.55);
addTrack("#wave-section", { opacity: [1, 0], y: [0, -20] }, { duration: 0.46, ease: "easeIn" }, 6.72);

addTrack("#outro", { opacity: [0, 1], scale: [0.965, 1] }, { duration: 0.7, ease: "easeOut" }, 6.96);
addTrack("#outro-halo", { scale: [0.9, 1.09], rotate: [0, -12] }, { duration: 2.8, ease: "easeInOut" }, 7.0);
addTrack("#outro-kicker", { opacity: [0, 1], y: [18, 0] }, { duration: 0.55 }, 7.28);
addTrack("#outro-brand", { opacity: [0, 1], y: [38, 0], filter: ["blur(11px)", "blur(0px)"] }, { duration: 0.82, ease: "easeOut" }, 7.52);
addTrack("#outro-rule", { scaleX: [0, 1] }, { duration: 0.72 }, 8.2);
addTrack("#outro-note", { opacity: [0, 1], y: [12, 0] }, { duration: 0.6 }, 8.48);
addTrack("#particles-outro .particle", { opacity: [0, 0.7, 0], y: [25, -70], x: [-9, 11] }, { duration: 1.7 }, 7.45);

function seekMotion(time) {
  for (const { controls, start } of motionTracks) {
    const localTime = time - start;
    controls.time = Math.max(0, Math.min(controls.duration, localTime));
  }
}

let lastFrameTime = 0;
const clock = {
  get frameTime() {
    return lastFrameTime;
  },
  set frameTime(value) {
    lastFrameTime = value;
    seekMotion(Math.max(0, Math.min(DURATION, value)));
  }
};

const rootTimeline = gsap.timeline({ paused: true });
rootTimeline.to(clock, { frameTime: DURATION, duration: DURATION, ease: "none" }, 0);

window.__timelines = window.__timelines || {};
window.__timelines.main = rootTimeline;
clock.frameTime = 0;
