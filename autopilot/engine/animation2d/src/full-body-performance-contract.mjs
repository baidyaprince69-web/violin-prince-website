const FINGER_DIGITS = Object.freeze(["index", "middle", "ring", "little"]);

/**
 * Full-body performance rigs require independent phalange sprites by default.
 * A source-faithful review candidate may explicitly disable fingering when its
 * supplied hand is intentionally retained as one intact sprite.
 */
export function fingeringRolesForPerformanceCharacter(character = {}) {
  const enabled = character?.performance?.fingering_articulation_enabled !== false;
  const controlRoles = enabled
    ? FINGER_DIGITS.map(digit => "finger_" + digit)
    : [];
  const segmentRoles = enabled
    ? FINGER_DIGITS.flatMap(digit => [
        "finger_" + digit,
        "finger_" + digit + "_middle",
        "finger_" + digit + "_tip"
      ])
    : [];
  return { enabled, controlRoles, segmentRoles };
}
