const ENVIRONMENTS = new Set(["city_night", "forest_dusk", "space", "concert_stage", "laboratory", "abstract"]);
const KINDS = new Set(["orb", "spark", "leaf", "light_streak", "music_note", "gear", "ring", "comet", "particle"]);
const MOTIONS = new Set(["float", "drift", "orbit", "rotate", "pulse", "flicker", "sway", "travel_left", "travel_right", "bob"]);

const escape = value => String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
function safeId(value) {
  const id = String(value || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  if (!id || id.length > 48) throw new TypeError("Stagecraft IDs must contain 1–48 safe characters.");
  return id;
}
function bounded(value, fallback, low, high) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.min(high, Math.max(low, parsed)) : fallback;
}
function color(value, fallback) {
  if (value == null || value === "") return fallback;
  if (!/^#[0-9a-fA-F]{6}$/.test(String(value))) throw new TypeError("Stagecraft colours must be six-digit hexadecimal values.");
  return String(value);
}
function createNode(sceneId, id, x, y, content, motion, amplitude, period) {
  return { id: sceneId + "-stagecraft-" + safeId(id), x, y, content, motion, amplitude, period };
}
function nodeMarkup(item) {
  return '<g transform="translate(' + item.x.toFixed(1) + ' ' + item.y.toFixed(1) + ')"><g class="stagecraft-node" id="' +
    escape(item.id) + '">' + item.content + '</g></g>';
}
function environmentFor(scene, width, height) {
  const theme = String(scene.stagecraft.environment || "").toLowerCase();
  if (!ENVIRONMENTS.has(theme)) throw new TypeError("Unsupported stagecraft environment: " + theme);
  const sceneId = safeId(scene.id);
  const nodes = [];
  const add = (id, x, y, content, motion, amplitude = 22, period = 3.5) =>
    nodes.push(createNode(sceneId, id, x * width, y * height, content, motion, amplitude, period));
  let top, bottom, accent, base = "";

  if (theme === "city_night") {
    top = "#071328"; bottom = "#173b52"; accent = "#5ed6db";
    base += '<circle cx="' + width * .78 + '" cy="' + height * .18 + '" r="' + width * .07 + '" fill="#dce8ee"/>';
    for (let i = 0; i < 15; i += 1) {
      const bw = width * (.035 + (i % 4) * .009), bh = height * (.14 + (i * 13 % 21) / 100);
      const x = i * width / 15, y = height - bh;
      base += '<rect x="' + x + '" y="' + y + '" width="' + bw + '" height="' + bh + '" fill="' +
        (i % 2 ? "#10283d" : "#0b2031") + '"/>';
      for (let row = 0; row < 4; row += 1) {
        base += '<rect x="' + (x + bw * .22) + '" y="' + (y + 16 + row * 24) +
          '" width="' + Math.max(2, bw * .16) + '" height="7" rx="2" fill="#e8c991" opacity="' +
          ((i + row) % 3 ? ".5" : ".12") + '"/>';
      }
    }
    base += '<path d="M0 ' + height * .89 + ' Q' + width * .5 + ' ' + height * .82 + ' ' + width +
      ' ' + height * .9 + ' V' + height + ' H0Z" fill="#07111c"/>';
    add("city-haze", .28, .69, '<ellipse rx="' + width * .22 + '" ry="' + height * .035 +
      '" fill="#54c7cc" opacity=".35" filter="url(#' + sceneId + '-blur)"/>', "drift", width * .07, 9);
    add("traffic-a", .05, .84, '<path d="M-90 0 H90" stroke="#d4fbf1" stroke-width="4" stroke-linecap="round"/>' +
      '<path d="M-90 0 H90" stroke="#55d8dc" stroke-width="11" opacity=".45" filter="url(#' + sceneId + '-blur)"/>',
      "travel_right", width * .55, 3.2);
    add("traffic-b", .95, .92, '<path d="M-75 0 H75" stroke="#fff0c8" stroke-width="4" stroke-linecap="round"/>' +
      '<path d="M-75 0 H75" stroke="#e8a36d" stroke-width="10" opacity=".4"/>', "travel_left", width * .6, 2.8);
    add("signal-glow", .52, .42, '<circle r="' + width * .09 + '" fill="#5ed6db" opacity=".18"/>' +
      '<circle r="' + width * .03 + '" fill="#b5ffff"/>', "pulse", 16, 4.1);
  } else if (theme === "forest_dusk") {
    top = "#1a3038"; bottom = "#596f5b"; accent = "#f0d28b";
    base += '<path d="M0 ' + height * .74 + ' Q' + width * .28 + ' ' + height * .61 + ' ' +
      width * .53 + ' ' + height * .76 + ' T' + width + ' ' + height * .7 + ' V' + height + ' H0Z" fill="#17352b"/>';
    for (let i = 0; i < 9; i += 1) {
      const x = i * width / 8, topY = height * (.1 + (i % 3) * .06);
      base += '<path d="M' + x + ' ' + height + ' Q' + (x + 22) + ' ' + height * .55 + ' ' +
        x + ' ' + topY + '" stroke="#091d1a" stroke-width="' + width * .026 + '" fill="none"/>' +
        '<ellipse cx="' + x + '" cy="' + topY + '" rx="' + width * .12 + '" ry="' + height * .14 +
        '" fill="' + (i % 2 ? "#214a3b" : "#2c5541") + '"/>';
    }
    for (let i = 0; i < 5; i += 1) {
      add("leaf-" + i, .12 + i * .18, .32 + (i % 2) * .15,
        '<path d="M0 0 Q22 -23 46 -2 Q20 18 0 0Z" fill="' + (i % 2 ? "#b6cd86" : "#79a56c") + '"/>',
        "sway", 15 + i * 2, 2.7 + i * .3);
    }
    for (let i = 0; i < 4; i += 1) {
      add("firefly-" + i, .15 + i * .21, .56 + (i % 2) * .12,
        '<circle r="5" fill="#fff1aa"/><circle r="20" fill="#f3d982" opacity=".25"/>',
        "flicker", 6, 1.3 + i * .35);
    }
  } else if (theme === "space") {
    top = "#050a20"; bottom = "#141e43"; accent = "#8b9dff";
    for (let i = 0; i < 55; i += 1) {
      const x = (i * 137.5) % width, y = (i * 91.7) % height;
      base += '<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' +
        (1.2 + i % 4 * .6) + '" fill="#eaf0ff" opacity="' + (.25 + i % 4 * .14) + '"/>';
    }
    base += '<circle cx="' + width * .73 + '" cy="' + height * .3 + '" r="' + width * .11 +
      '" fill="#b58bbd" opacity=".68"/><ellipse cx="' + width * .73 + '" cy="' + height * .3 +
      '" rx="' + width * .17 + '" ry="' + width * .05 + '" fill="none" stroke="#e6c8ed" stroke-width="6" opacity=".55"/>';
    add("orbit-moon", .27, .34, '<circle r="' + width * .025 + '" fill="#7cc9e0"/>' +
      '<circle r="' + width * .06 + '" fill="none" stroke="#9abfff" stroke-width="3" opacity=".65"/>', "orbit", width * .09, 9);
    add("comet-a", .08, .23, '<path d="M-105 0 Q-35 -12 0 0" fill="none" stroke="#a8c3ff" stroke-width="8" opacity=".5"/>' +
      '<circle r="6" fill="#fff"/>', "travel_right", width * .58, 5.2);
    add("comet-b", .92, .61, '<path d="M-80 0 Q-30 -10 0 0" fill="none" stroke="#d5a8ff" stroke-width="7" opacity=".5"/>' +
      '<circle r="5" fill="#fff"/>', "travel_left", width * .58, 7);
    add("stardust", .49, .75, '<path d="M0 -18 L5 -5 L18 0 L5 5 L0 18 L-5 5 L-18 0 L-5 -5Z" fill="#e0e4ff"/>', "pulse", 13, 2.2);
  } else if (theme === "concert_stage") {
    top = "#080c18"; bottom = "#281b2b"; accent = "#e5c38b";
    base += '<path d="M0 0 H' + width * .18 + ' Q' + width * .29 + ' ' + height * .3 + ' ' +
      width * .17 + ' ' + height + ' H0Z M' + width + ' 0 H' + width * .82 + ' Q' +
      width * .71 + ' ' + height * .3 + ' ' + width * .83 + ' ' + height + ' H' + width + 'Z" fill="#351f33"/>' +
      '<path d="M0 ' + height * .9 + ' Q' + width * .5 + ' ' + height * .75 + ' ' + width +
      ' ' + height * .9 + ' V' + height + ' H0Z" fill="#0c111d"/>';
    add("spotlight-left", .28, .02, '<path d="M-20 0 L-235 ' + height * .83 + ' H235Z" fill="#8ed6dc" opacity=".17"/>' +
      '<circle r="22" fill="#eaffff" opacity=".8"/>', "sway", 24, 5.1);
    add("spotlight-right", .72, .02, '<path d="M-18 0 L-210 ' + height * .83 + ' H210Z" fill="#f1ca8a" opacity=".17"/>' +
      '<circle r="20" fill="#fff0ce" opacity=".8"/>', "sway", 20, 4.4);
    for (let i = 0; i < 6; i += 1) {
      add("stage-dust-" + i, .1 + i * .15, .46 + (i % 3) * .12,
        '<circle r="' + (3 + i % 3) + '" fill="#f4dfb5"/><circle r="17" fill="#edc98f" opacity=".2"/>',
        "float", 24 + i * 2, 2.4 + i * .25);
    }
    add("stage-beat-ring", .5, .75, '<ellipse rx="' + width * .2 + '" ry="' + height * .04 +
      '" fill="none" stroke="#d7b77d" stroke-width="4" opacity=".65"/>', "pulse", 24, 2.2);
  } else if (theme === "laboratory") {
    top = "#071a29"; bottom = "#17404a"; accent = "#62d7d1";
    for (let x = 0; x <= width; x += 48) base += '<path d="M' + x + ' 0 V' + height + '" stroke="#9ad7d5" stroke-opacity=".12"/>';
    for (let y = 0; y <= height; y += 48) base += '<path d="M0 ' + y + ' H' + width + '" stroke="#9ad7d5" stroke-opacity=".12"/>';
    base += '<rect x="' + width * .08 + '" y="' + height * .2 + '" width="' + width * .84 +
      '" height="' + height * .5 + '" rx="26" fill="#092a3a" fill-opacity=".55" stroke="#80d7d2" stroke-opacity=".38"/>';
    add("molecule-core", .5, .44, '<circle r="24" fill="#f0d08d"/><circle r="52" fill="none" stroke="#65d4d0" stroke-width="4"/>', "pulse", 13, 2.8);
    add("molecule-orbit-a", .5, .44, '<ellipse rx="132" ry="54" fill="none" stroke="#74d2cc" stroke-width="3"/><circle cx="132" cy="0" r="13" fill="#baf3e6"/>', "rotate", 360, 5.2);
    add("molecule-orbit-b", .5, .44, '<ellipse rx="184" ry="78" fill="none" stroke="#dfc58c" stroke-width="3"/><circle cx="-184" cy="0" r="11" fill="#efd398"/>', "rotate", -360, 6.5);
    add("signal-pulse", .5, .77, '<path d="M-238 0 H-112 L-72 -38 L-32 34 L12 -18 L54 0 H238" fill="none" stroke="#62d7d1" stroke-width="5" stroke-linejoin="round"/>', "drift", width * .08, 3.8);
    add("data-beacon", .86, .18, '<circle r="11" fill="#b6f3df"/><circle r="34" fill="none" stroke="#b6f3df" stroke-width="3"/>', "flicker", 10, 1.7);
  } else {
    top = "#080c1e"; bottom = "#172943"; accent = "#68d0cf";
    base += '<circle cx="' + width * .5 + '" cy="' + height * .47 + '" r="' + width * .26 +
      '" fill="none" stroke="#65cbc7" stroke-opacity=".2" stroke-width="2"/>' +
      '<circle cx="' + width * .5 + '" cy="' + height * .47 + '" r="' + width * .36 +
      '" fill="none" stroke="#e5c58d" stroke-opacity=".18" stroke-width="2"/>';
    add("abstract-ring-a", .5, .47, '<ellipse rx="' + width * .24 + '" ry="' + height * .12 +
      '" fill="none" stroke="#62d7d1" stroke-width="3" opacity=".55"/>', "rotate", 360, 17);
    add("abstract-ring-b", .5, .47, '<ellipse rx="' + width * .3 + '" ry="' + height * .19 +
      '" fill="none" stroke="#e4bd7d" stroke-width="2" stroke-dasharray="9 18" opacity=".5"/>', "rotate", -360, 23);
    for (let i = 0; i < 6; i += 1) {
      add("abstract-orb-" + i, .12 + i * .15, .27 + (i % 2) * .42,
        '<circle r="' + (10 + i * 2) + '" fill="#68d2cd"/><circle r="' + (25 + i * 3) +
        '" fill="#68d2cd" opacity=".17"/>', "orbit", 24 + i * 7, 3.1 + i * .45);
    }
    add("abstract-wave", .5, .79, '<path d="M-300 0 Q-220 -45 -140 0 T20 0 T180 0 T340 0" fill="none" stroke="#f0cd8d" stroke-width="4"/>', "float", 24, 3.6);
  }

  const defs = '<defs><linearGradient id="' + sceneId + '-sky" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0%" stop-color="' + top + '"/><stop offset="100%" stop-color="' + bottom + '"/></linearGradient>' +
    '<filter id="' + sceneId + '-blur" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="9"/></filter></defs>';
  return { theme, nodes, base: '<rect width="100%" height="100%" fill="url(#' + sceneId + '-sky)"/>' + base, defs };
}
function objectShape(kind, size, colour) {
  if (kind === "music_note") return '<text x="0" y="0" text-anchor="middle" fill="' + colour + '" font-size="' + size * 2 + '" font-family="serif">♪</text>';
  if (kind === "light_streak") return '<path d="M-' + size * 2 + ' 0 H' + size * 2 + '" stroke="' + colour + '" stroke-width="' + Math.max(3, size * .16) + '" stroke-linecap="round"/>';
  if (kind === "leaf") return '<path d="M-' + size + ' 0 Q0 -' + size + ' ' + size + ' -' + size * .3 + ' Q' + size * .4 + ' ' + size + ' -' + size + ' 0Z" fill="' + colour + '"/>';
  if (kind === "spark") return '<path d="M0 -' + size + ' L' + size * .2 + ' -' + size * .2 + ' L' + size + ' 0 L' + size * .2 + ' ' + size * .2 + ' L0 ' + size + ' L-' + size * .2 + ' ' + size * .2 + ' L-' + size + ' 0 L-' + size * .2 + ' -' + size * .2 + 'Z" fill="' + colour + '"/>';
  if (kind === "gear") {
    const pts = Array.from({length:24}, (_v,i) => {
      const r = i % 2 ? size * .78 : size, a = Math.PI * 2 * i / 24 - Math.PI / 2;
      return (Math.cos(a) * r).toFixed(1) + "," + (Math.sin(a) * r).toFixed(1);
    });
    return '<polygon points="' + pts.join(" ") + '" fill="' + colour + '" opacity=".8"/><circle r="' + size * .28 + '" fill="#132738"/>';
  }
  if (kind === "ring") return '<ellipse rx="' + size + '" ry="' + size * .42 + '" fill="none" stroke="' + colour + '" stroke-width="5"/>';
  if (kind === "comet") return '<path d="M-' + size * 2.5 + ' 0 Q-' + size + ' -' + size * .7 + ' 0 0" stroke="' + colour + '" stroke-width="7" fill="none" opacity=".6"/><circle r="' + size * .22 + '" fill="#fff"/>';
  if (kind === "orb") return '<circle r="' + size + '" fill="' + colour + '" opacity=".24"/><circle r="' + size * .35 + '" fill="' + colour + '"/>';
  return '<circle r="' + size + '" fill="' + colour + '"/><circle r="' + size * 2 + '" fill="none" stroke="' + colour + '" stroke-opacity=".35" stroke-width="2"/>';
}
function allSceneNodes(scene, width, height) {
  if (!scene?.stagecraft) return { env: null, objects: [] };
  if (typeof scene.stagecraft !== "object" || Array.isArray(scene.stagecraft)) throw new TypeError("Stagecraft config must be an object.");
  const env = environmentFor(scene, width, height);
  const raw = scene.stagecraft.objects || [];
  if (!Array.isArray(raw) || raw.length > 24) throw new TypeError("A stagecraft scene may contain at most 24 moving objects.");
  const seen = new Set();
  const objects = raw.map(item => {
    if (!item || typeof item !== "object") throw new TypeError("Every moving object must be an object.");
    const key = safeId(item.id);
    if (seen.has(key)) throw new TypeError("Stagecraft object IDs must be unique: " + key);
    seen.add(key);
    const kind = String(item.kind || "particle").toLowerCase();
    const motion = String(item.motion || "float").toLowerCase();
    if (!KINDS.has(kind)) throw new TypeError("Unsupported stagecraft object kind: " + kind);
    if (!MOTIONS.has(motion)) throw new TypeError("Unsupported stagecraft object motion: " + motion);
    const colour = color(item.color, "#79d6d0");
    const size = bounded(item.size, 24, 8, 260);
    return createNode(
      safeId(scene.id), "object-" + key,
      bounded(item.x, .5, 0, 1) * width,
      bounded(item.y, .5, 0, 1) * height,
      objectShape(kind, size, colour),
      motion,
      bounded(item.amplitude, Math.max(16, size), 2, Math.max(width, height) * .8),
      bounded(item.period_seconds, 3.5, .6, 30)
    );
  });
  return { env, objects };
}
export function stagecraftMotionNodeIds(scene) {
  if (!scene?.stagecraft) return [];
  const { env, objects } = allSceneNodes(scene, 720, 1280);
  return [...env.nodes, ...objects].map(item => item.id);
}
export function stagecraftNodeCounts(scene) {
  if (!scene?.stagecraft) return { environment: 0, objects: 0, total: 0 };
  const { env, objects } = allSceneNodes(scene, 720, 1280);
  return { environment: env.nodes.length, objects: objects.length, total: env.nodes.length + objects.length };
}
export function renderStagecraftMarkup(scene, width = 720, height = 1280, sceneIndex = 0) {
  if (!scene?.stagecraft) return "";
  const { env, objects } = allSceneNodes(scene, width, height);
  const nodes = [...env.nodes, ...objects].map(nodeMarkup).join("");
  const start = Math.max(0, Number(scene.start) || 0);
  const duration = Math.max(.1, Number(scene.duration) || 1);
  const elementId = safeId(scene.id) + "-stagecraft";
  return '<div class="clip scene-stagecraft scene-stagecraft--' + env.theme +
    '" id="' + elementId + '" data-start="' + start + '" data-duration="' + duration +
    '" data-track-index="' + (5 + sceneIndex * 3) + '" aria-hidden="true">' +
    '<svg viewBox="0 0 ' + width + ' ' + height + '" preserveAspectRatio="xMidYMid slice">' +
    env.defs + env.base + nodes + '</svg></div>';
}
function motionFrames(type, amount) {
  const a = Math.max(2, Number(amount) || 16);
  switch (type) {
    case "float": case "bob":
      return ["translate(0px " + a + "px) rotate(-1deg)", "translate(" + a * .15 + "px -" + a + "px) rotate(1deg)", "translate(0px " + a + "px) rotate(-1deg)"];
    case "drift":
      return ["translateX(-" + a + "px)", "translateX(" + a + "px)", "translateX(-" + a + "px)"];
    case "orbit":
      return ["rotate(0deg) translateX(" + a + "px)", "rotate(180deg) translateX(" + a + "px)", "rotate(360deg) translateX(" + a + "px)"];
    case "rotate":
      return ["rotate(0deg)", "rotate(180deg)", "rotate(360deg)"];
    case "pulse": case "flicker":
      return ["scale(.78)", "scale(1.18)", "scale(.78)"];
    case "sway":
      return ["rotate(-" + a * .6 + "deg)", "rotate(" + a * .6 + "deg)", "rotate(-" + a * .6 + "deg)"];
    case "travel_left":
      return ["translateX(" + a + "px)", "translateX(-" + a + "px)", "translateX(" + a + "px)"];
    case "travel_right":
      return ["translateX(-" + a + "px)", "translateX(" + a + "px)", "translateX(-" + a + "px)"];
    default:
      return ["translateY(" + a + "px)", "translateY(-" + a + "px)", "translateY(" + a + "px)"];
  }
}
export function buildStagecraftMotion(scene, { fps = 25, width = 720, height = 1280 } = {}) {
  if (!scene?.stagecraft) return [];
  const { env, objects } = allSceneNodes(scene, width, height);
  const start = Math.max(0, Number(scene.start) || 0);
  const duration = Math.max(.1, Number(scene.duration) || 1);
  const sceneEnd = start + duration;
  const cues = scene.stagecraft.music_sync_cues || [];
  if (!Array.isArray(cues) || cues.length > 24) {
    throw new TypeError("A stagecraft scene may contain at most 24 music-sync cues.");
  }
  const musicTracks = cues.map((cue, index) => {
    const time = Number(cue?.time_seconds);
    const event = String(cue?.event || "").trim();
    const reason = String(cue?.reason || "").trim();
    if (!Number.isFinite(time) || time < start - 0.001 || time >= sceneEnd - 0.08 || !event || !reason) {
      throw new TypeError("Music-sync cues must have an event and reason, and occur inside the animated scene.");
    }
    if (!objects.length) {
      throw new TypeError("Music-sync cues require at least one authored moving stagecraft object.");
    }
    const target = objects[index % objects.length].id;
    const requested = Number(cue.requested_time_seconds);
    const alignmentError = Number(cue.alignment_error_seconds);
    const timingSource = String(cue.timing_source || "");
    if (
      !Number.isFinite(requested) || !Number.isFinite(alignmentError)
      || alignmentError < 0 || alignmentError > 0.45
      || !["decoded_audio_beat_grid", "decoded_audio_onset", "preview_generated_beat_grid"].includes(timingSource)
    ) {
      throw new TypeError("Music-sync cue must be aligned to a measured audio beat or onset.");
    }
    return {
      target,
      property: "filter",
      start: time,
      duration: Math.min(0.42, sceneEnd - time),
      easing: "ease-out",
      offsets: [0, .2, .68, 1],
      loop: false,
      values: [
        "brightness(1)",
        "brightness(1.85) saturate(1.2)",
        "brightness(1.14) saturate(1.04)",
        "brightness(1)"
      ],
      music_sync_event: event,
      music_sync_reason: reason,
      music_sync_timing_source: timingSource,
      music_sync_alignment_error_seconds: alignmentError
    };
  });
  const ambientTracks = [...env.nodes, ...objects].flatMap(item => {
    const base = {
      target: item.id,
      start,
      duration: Math.max(1 / Math.max(1, fps), Math.min(duration, item.period)),
      easing: "ease-in-out",
      offsets: [0, .5, 1],
      loop: true
    };
    const tracks = [{ ...base, property: "transform", values: motionFrames(item.motion, item.amplitude) }];
    if (item.motion === "pulse" || item.motion === "flicker") {
      tracks.push({ ...base, property: "opacity", values: item.motion === "flicker" ? [.24, 1, .34] : [.6, 1, .6] });
    }
    return tracks;
  });
  return [...ambientTracks, ...musicTracks];
}
