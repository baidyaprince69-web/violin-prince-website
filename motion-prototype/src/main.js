import { animate, stagger } from "motion";
import { gsap } from "gsap";

const DURATION = 10;

/*
 * Motion owns every visible animation. The paused timeline can be assigned an
 * exact time, making each rendered frame reproducible.
 */
const motionTimeline = animate(
  [
    ["#depth-grid", { x: [0, -18, 7], y: [0, 18, -4] }, { duration: 9.8, ease: "easeInOut", at: 0 }],
    ["#orbital-ring", { rotate: [-8, 14], scale: [1, 1.08] }, { duration: 9.8, ease: "easeInOut", at: 0 }],
    ["#opening", { opacity: [0, 1] }, { duration: 0.25, at: 0 }],
    [".hero-kicker", { opacity: [0, 1], y: [24, 0] }, { duration: 0.62, ease: "easeOut", at: 0.22 }],
    ["#hero-line-one", { opacity: [0, 1], y: [54, 0], filter: ["blur(12px)", "blur(0px)"] }, { duration: 0.85, ease: "easeOut", at: 0.52 }],
    ["#hero-line-two", { opacity: [0, 1], y: [48, 0], filter: ["blur(12px)", "blur(0px)"] }, { duration: 0.88, ease: "easeOut", at: 0.88 }],
    ["#hero-rule", { scaleX: [0, 1] }, { duration: 0.75, ease: "easeOut", at: 1.38 }],
    ["#hero-note", { opacity: [0, 1], y: [18, 0] }, { duration: 0.72, ease: "easeOut", at: 1.62 }],
    ["#particles-opening .particle", { opacity: [0, 0.78, 0], y: [28, -82], x: [-10, 8] }, { duration: 2.1, at: 0.5, delay: stagger(0.075) }],
    ["#opening", { opacity: [1, 0], y: [0, -22] }, { duration: 0.52, ease: "easeIn", at: 2.72 }],

    ["#wave-section", { opacity: [0, 1], y: [34, 0] }, { duration: 0.68, ease: "easeOut", at: 2.82 }],
    ["#wave-kicker", { opacity: [0, 1], y: [19, 0] }, { duration: 0.55, at: 3.02 }],
    ["#wave-title", { opacity: [0, 1], y: [42, 0], filter: ["blur(10px)", "blur(0px)"] }, { duration: 0.72, ease: "easeOut", at: 3.18 }],
    ["#wave-subtitle", { opacity: [0, 1], y: [15, 0] }, { duration: 0.6, at: 3.55 }],
    ["#waveform-panel", { opacity: [0, 1], scale: [0.94, 1] }, { duration: 0.68, ease: "easeOut", at: 3.25 }],
    [".waveform-bar", { scaleY: [0.22, 0.96, 0.34, 0.82] }, { duration: 1.05, repeat: 1, repeatType: "mirror", ease: "easeInOut", delay: stagger(0.03), at: 3.55 }],
    ["#wave-scan", { opacity: [0, 0.9, 0], x: [-210, 510] }, { duration: 2.65, ease: "easeInOut", at: 3.62 }],
    ["#wave-frequency", { opacity: [0, 1], y: [12, 0] }, { duration: 0.62, at: 4.05 }],
    ["#wave-bottom-note", { opacity: [0, 1], y: [22, 0] }, { duration: 0.7, at: 5.62 }],
    ["#particles-wave .particle", { opacity: [0, 0.65, 0], y: [24, -65], x: [7, -12] }, { duration: 2.0, at: 3.55, delay: stagger(0.09) }],
    ["#wave-section", { opacity: [1, 0], y: [0, -20] }, { duration: 0.46, ease: "easeIn", at: 6.72 }],

    ["#outro", { opacity: [0, 1], scale: [0.965, 1] }, { duration: 0.7, ease: "easeOut", at: 6.96 }],
    ["#outro-halo", { scale: [0.9, 1.09], rotate: [0, -12] }, { duration: 2.8, ease: "easeInOut", at: 7.0 }],
    ["#outro-kicker", { opacity: [0, 1], y: [18, 0] }, { duration: 0.55, at: 7.28 }],
    ["#outro-brand", { opacity: [0, 1], y: [38, 0], filter: ["blur(11px)", "blur(0px)"] }, { duration: 0.82, ease: "easeOut", at: 7.52 }],
    ["#outro-rule", { scaleX: [0, 1] }, { duration: 0.72, at: 8.2 }],
    ["#outro-note", { opacity: [0, 1], y: [12, 0] }, { duration: 0.6, at: 8.48 }],
    ["#particles-outro .particle", { opacity: [0, 0.7, 0], y: [25, -70], x: [-9, 11] }, { duration: 1.7, at: 7.45, delay: stagger(0.055) }]
  ],
  { autoplay: false }
);

motionTimeline.time = 0;

/*
 * HyperFrames currently registers a paused GSAP root timeline per composition.
 * This adapter is only a clock: GSAP does not animate visible properties.
 * Each HyperFrames seek writes its exact time into the Motion timeline.
 */
const clock = { progress: 0 };
function syncMotionTime() {
  const frameTime = Math.max(0, Math.min(DURATION, rootTimeline.time()));
  motionTimeline.time = Math.min(frameTime, motionTimeline.duration);
}

const rootTimeline = gsap.timeline({ paused: true, onUpdate: syncMotionTime });
rootTimeline.to(clock, { progress: 1, duration: DURATION, ease: "none" }, 0);

window.__timelines = window.__timelines || {};
window.__timelines.main = rootTimeline;
syncMotionTime();
