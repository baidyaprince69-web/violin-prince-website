export const DEFAULT_VISUAL_DIRECTION = "midnight-resonance";

const DIRECTIONS = Object.freeze({
  "midnight-resonance": Object.freeze({
    id: "midnight-resonance",
    panelStart: "#07111e",
    panelEnd: "#0b1c2c",
    accentGold: "#d9bd8b",
    accentGoldSoft: "rgba(217, 189, 139, 0.28)",
    accentCool: "#8ed7e4",
    textPrimary: "#fbf1e2",
    textMuted: "#d5cabb",
    border: "rgba(217, 189, 139, 0.42)",
    shadow: "0 18px 46px rgba(0, 0, 0, 0.42)",
  }),
});

export function resolveVisualDirection(id = DEFAULT_VISUAL_DIRECTION) {
  const key = String(id ?? DEFAULT_VISUAL_DIRECTION).trim();
  const direction = DIRECTIONS[key];
  if (!direction) {
    throw new Error(`Unknown Violin Prince visual direction: ${key}`);
  }
  return direction;
}

export function listVisualDirections() {
  return Object.keys(DIRECTIONS);
}
