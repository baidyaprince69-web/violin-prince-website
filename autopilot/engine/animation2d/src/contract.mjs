export function clampTime(value, duration) {
  const total = Number.isFinite(Number(duration)) ? Math.max(0, Number(duration)) : 0;
  const time = Number.isFinite(Number(value)) ? Number(value) : 0;
  return Math.min(total, Math.max(0, time));
}

export function gestureKeyframes(name) {
  const gestures = {
    wave: {
      right_upper_arm: { rotate: [0, -28, 14, -24, 0] },
      right_forearm: { rotate: [0, -18, 24, -16, 0] },
      right_hand: { rotate: [0, -9, 13, -7, 0] }
    },
    point: {
      right_upper_arm: { rotate: [0, -42] },
      right_forearm: { rotate: [0, 24] },
      right_hand: { rotate: [0, -8] }
    },
    point_left: {
      // Several emphasis beats keep the pointing arm alive for the whole narration beat.
      left_upper_arm: { rotate: [0, 26, 17, 32, 19, 29, 15, 24] },
      left_forearm: { rotate: [0, -18, -9, -23, -11, -20, -8, -16] },
      left_hand: { rotate: [0, 8, 1, 10, 2, 8, 1, 6] },
      right_upper_arm: { rotate: [0, 8, 2, 11, 3, 9, 1, 6] },
      right_forearm: { rotate: [0, -6, 2, -8, 2, -6, 1, -4] },
      right_hand: { rotate: [0, 4, -2, 5, -1, 4, 0, 3] },
      head: { rotate: [0, -4, 2, -5, 1, -3, 0, -2] }
    },
    point_right: {
      // Mirror the left-pointing sequence for layouts with the graphic on the right.
      left_upper_arm: { rotate: [0, -8, -2, -11, -3, -9, -1, -6] },
      left_forearm: { rotate: [0, 6, -2, 8, -2, 6, -1, 4] },
      left_hand: { rotate: [0, -4, 2, -5, 1, -4, 0, -3] },
      right_upper_arm: { rotate: [0, -26, -17, -32, -19, -29, -15, -24] },
      right_forearm: { rotate: [0, 18, 9, 23, 11, 20, 8, 16] },
      right_hand: { rotate: [0, -8, -1, -10, -2, -8, -1, -6] },
      head: { rotate: [0, 4, -2, 5, -1, 3, 0, 2] }
    },
    open_palms: {
      left_upper_arm: { rotate: [0, -20, -14] },
      left_forearm: { rotate: [0, 18, 8] },
      right_upper_arm: { rotate: [0, 20, 14] },
      right_forearm: { rotate: [0, -18, -8] }
    },
    explain: {
      left_upper_arm: { rotate: [0, -12, -4, -12, 0] },
      left_forearm: { rotate: [0, 7, -4, 6, 0] },
      left_hand: { rotate: [0, -6, 5, -4, 0] },
      right_upper_arm: { rotate: [0, 12, 4, 12, 0] },
      right_forearm: { rotate: [0, -7, 4, -6, 0] },
      right_hand: { rotate: [0, 6, -5, 4, 0] }
    },
    nod: {
      head: { rotate: [0, 7, -4, 0] }
    },
    thinking: {
      head: { rotate: [0, -6] },
      left_upper_arm: { rotate: [0, -36] },
      left_forearm: { rotate: [0, 32] }
    },
    idle_breath: {
      torso: { rotate: [0, -1.1, 0, 1.1, 0] },
      head: { rotate: [0, -0.6, 0, 0.6, 0] }
    },
    talking: {
      head: { rotate: [0, -2.5, 1.5, -2, 0] },
      left_upper_arm: { rotate: [0, -7, -2, -9, 0] },
      left_forearm: { rotate: [0, 8, 2, 9, 0] },
      right_upper_arm: { rotate: [0, 7, 2, 9, 0] },
      right_forearm: { rotate: [0, -8, -2, -9, 0] }
    },
    violin_bow: {
      torso: { rotate: [0, -1.4, 0, 1.4, 0] },
      head: { rotate: [0, -1.2, .5, 1.2, 0] },
      left_upper_arm: { rotate: [0, -12, -11, -13, 0] },
      left_forearm: { rotate: [0, 7, 4, 8, 0] },
      left_hand: { rotate: [0, -3, 1, -3, 0] },
      right_upper_arm: { rotate: [0, 4, 6, 4, 0] },
      right_forearm: { rotate: [0, -18, 11, -18, 0] },
      right_hand: { rotate: [0, 5, -5, 5, 0] }
    },
    walk_cycle: {
      torso: { rotate: [0, -2, 0, 2, 0] },
      head: { rotate: [0, 1, 0, -1, 0] },
      left_upper_arm: { rotate: [0, 17, 0, -17, 0] },
      left_forearm: { rotate: [0, -10, 0, 10, 0] },
      right_upper_arm: { rotate: [0, -17, 0, 17, 0] },
      right_forearm: { rotate: [0, 10, 0, -10, 0] },
      left_thigh: { rotate: [0, 20, 0, -20, 0] },
      left_shin: { rotate: [0, -26, 0, 26, 0] },
      left_foot: { rotate: [0, 8, 0, -8, 0] },
      right_thigh: { rotate: [0, -20, 0, 20, 0] },
      right_shin: { rotate: [0, 26, 0, -26, 0] },
      right_foot: { rotate: [0, -8, 0, 8, 0] }
    },
    violin_performance: {
      torso: { rotate: [0, -0.7, 0, 0.7, 0] },
      head: { rotate: [0, -1.0, 0.4, 1.0, 0] },
      left_upper_arm: { rotate: [0, -1.2, -0.4, -1.5, 0] },
      left_forearm: { rotate: [0, 1.8, -0.8, 1.5, 0] },
      left_hand: { rotate: [0, -2.2, 1.8, -1.6, 0] },
      right_upper_arm: { rotate: [0, 1.5, -1.2, 1.5, 0] },
      right_forearm: { rotate: [0, -3.5, 4.5, -3.5, 0] },
      right_hand: { rotate: [0, 1.8, -2.4, 1.8, 0] },
      left_thigh: { rotate: [0, 0.6, -0.6, 0.6, 0] },
      right_thigh: { rotate: [0, -0.6, 0.6, -0.6, 0] },
      left_shin: { rotate: [0, 0.8, 0, -0.8, 0] },
      right_shin: { rotate: [0, -0.8, 0, 0.8, 0] },
      violin: { rotate: [0, -0.45, 0.45, -0.45, 0] },
      bow: { rotate: [0, -5.5, 5.5, -5.5, 0] }
    },
    dance_groove: {
      torso: { rotate: [0, -5, 0, 5, 0] },
      head: { rotate: [0, 4, -2, -4, 0] },
      left_upper_arm: { rotate: [0, -18, 5, -12, 0] },
      left_forearm: { rotate: [0, 14, -5, 10, 0] },
      right_upper_arm: { rotate: [0, 18, -5, 12, 0] },
      right_forearm: { rotate: [0, -14, 5, -10, 0] }
    }
  };
  return gestures[String(name || "").toLowerCase()] || {};
}
