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
      left_upper_arm: { rotate: [0, 38] },
      left_forearm: { rotate: [0, -18] },
      left_hand: { rotate: [0, 7] }
    },
    point_right: {
      right_upper_arm: { rotate: [0, -38] },
      right_forearm: { rotate: [0, 18] },
      right_hand: { rotate: [0, -7] }
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
    }
  };
  return gestures[String(name || "").toLowerCase()] || {};
}
