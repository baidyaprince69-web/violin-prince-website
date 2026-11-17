const project = window.VP_PROJECT || {};
const tracks = Array.isArray(project.motion_tracks) ? project.motion_tracks : [];
const animations = [];

for (const track of tracks) {
  if (!track || typeof track.target !== "string" || typeof track.property !== "string") continue;
  const element = document.getElementById(track.target);
  if (!element || !Array.isArray(track.values) || track.values.length < 2) continue;
  const keyframes = track.values.map(value => ({ [track.property]: value }));
  const animation = element.animate(keyframes, {
    duration: Math.max(1, Number(track.duration) * 1000),
    delay: Math.max(0, Number(track.start) * 1000),
    easing: track.easing || "linear",
    fill: "both"
  });
  animation.pause();
  animation.currentTime = 0;
  animations.push(animation);
}

// HyperFrames' WAAPI adapter seeks these paused native animations at every
// requested composition time. The small root contract registers the composition
// duration for HyperFrames but does not create a browser-clock animation ticker.
const duration = Math.max(0, Number(project.duration_seconds) || 0);
const rootTimeline = {
  play() {},
  pause() {},
  seek() {},
  time() { return 0; },
  duration() { return duration; },
  totalDuration() { return duration; },
  add() {},
  paused() { return true; },
  set() {},
  getChildren() { return []; }
};
window.__timelines = window.__timelines || {};
window.__timelines.root = rootTimeline;
window.__vpMotionDiagnostics = {
  renderer: "native-paused-waapi",
  springGenerator: "Motion build-time sampling",
  animationCount: animations.length,
  fps: Number(project.fps) || 25,
  duration
};
