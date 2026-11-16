const SVG_NS = "http://www.w3.org/2000/svg";

function node(tag, attrs = {}, parent = null) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== undefined && value !== null) el.setAttribute(key, String(value));
  }
  if (parent) parent.appendChild(el);
  return el;
}

function text(parent, x, y, value, size = 32, color = "#e8edf6", extra = {}) {
  const el = node("text", {
    x, y, fill: color, "font-size": size,
    "font-family": "Arial, Helvetica, sans-serif",
    "font-weight": 700, "letter-spacing": 1.1, ...extra
  }, parent);
  el.textContent = String(value || "");
  return el;
}

function defs(svg) {
  const d = node("defs", {}, svg);
  const bg = node("linearGradient", { id: "vp-full-bg", x1: "0", y1: "0", x2: "1", y2: "1" }, d);
  node("stop", { offset: "0%", "stop-color": "#17243e" }, bg);
  node("stop", { offset: "52%", "stop-color": "#0c1429" }, bg);
  node("stop", { offset: "100%", "stop-color": "#070b17" }, bg);
  const gold = node("linearGradient", { id: "vp-full-gold", x1: "0", y1: "0", x2: "1", y2: "1" }, d);
  node("stop", { offset: "0%", "stop-color": "#f5dfb9" }, gold);
  node("stop", { offset: "100%", "stop-color": "#ac7540" }, gold);
  const glow = node("filter", { id: "vp-full-glow", x: "-70%", y: "-70%", width: "240%", height: "240%" }, d);
  node("feGaussianBlur", { stdDeviation: "10", result: "blur" }, glow);
  const merge = node("feMerge", {}, glow);
  node("feMergeNode", { in: "blur" }, merge);
  node("feMergeNode", { in: "SourceGraphic" }, merge);
}

function background(svg, accent) {
  node("rect", { x: 0, y: 0, width: 1080, height: 1920, fill: "url(#vp-full-bg)" }, svg);
  node("circle", { cx: 540, cy: 1010, r: 500, fill: accent, "fill-opacity": 0.05 }, svg);
  node("path", { d: "M0 500 Q540 390 1080 500 M0 1450 Q540 1550 1080 1450", fill: "none", stroke: "#d8bd91", "stroke-opacity": 0.1, "stroke-width": 2 }, svg);
  for (let i = 0; i < 18; i += 1) {
    const x = (i * 173 + 61) % 1040 + 20;
    const y = (i * 227 + 560) % 840 + 500;
    node("circle", { cx: x, cy: y, r: 2 + (i % 3), fill: i % 2 ? "#70cfc4" : "#d8bd91", "fill-opacity": 0.22 }, svg);
  }
}

function speaker(parent, x, y, scale = 1) {
  const g = node("g", { class: "room-monitor", transform: "translate(" + x + " " + y + ") scale(" + scale + ")" }, parent);
  node("rect", { x: 0, y: 0, width: 150, height: 280, rx: 20, fill: "#101a2c", stroke: "#d8bd91", "stroke-width": 4 }, g);
  node("rect", { x: 13, y: 13, width: 124, height: 254, rx: 14, fill: "#243653", stroke: "#8397b8", "stroke-opacity": 0.6, "stroke-width": 2 }, g);
  node("circle", { cx: 75, cy: 78, r: 30, fill: "#0b1324", stroke: "#d8bd91", "stroke-width": 4 }, g);
  node("circle", { cx: 75, cy: 190, r: 54, fill: "#0b1324", stroke: "#70cfc4", "stroke-width": 4 }, g);
  node("circle", { cx: 75, cy: 190, r: 24, fill: "url(#vp-full-gold)" }, g);
  return g;
}

function reveal(parent, order, extra = "") {
  return node("g", { class: ("reveal-part " + extra).trim(), "data-reveal-order": order }, parent);
}

function buildRoom(world) {
  const subject = node("g", { class: "scene-subject room-subject" }, world);
  node("path", { d: "M70 530 L1010 530 L1010 1125 L70 1125 Z", fill: "#182944", stroke: "#7388a8", "stroke-opacity": 0.5, "stroke-width": 4 }, subject);
  node("path", { d: "M70 1125 L1010 1125 L1080 1510 L0 1510 Z", fill: "#0d1729", stroke: "#8796ad", "stroke-opacity": 0.24, "stroke-width": 3 }, subject);
  for (let i = 0; i < 9; i += 1) {
    const x = 130 + i * 102;
    node("path", { d: "M" + x + " 545 L" + (x - 24) + " 1115", stroke: "#9baac0", "stroke-opacity": 0.11, "stroke-width": 12 }, subject);
  }
  speaker(reveal(subject, 0), 115, 785, 1.12);
  speaker(reveal(subject, 0), 815, 785, 1.12);
  const reflections = reveal(subject, 1, "room-reflections");
  [
    "M280 905 C350 700 465 720 510 920",
    "M280 905 C365 600 510 620 560 920",
    "M800 905 C730 700 615 720 570 920",
    "M800 905 C715 600 570 620 520 920",
    "M210 1090 C370 1280 710 1280 870 1090",
    "M160 1150 C370 1400 710 1400 920 1150"
  ].forEach((d, i) => node("path", {
    d, class: "sound-wave", fill: "none", stroke: i % 2 ? "#70cfc4" : "#d8bd91",
    "stroke-width": i > 3 ? 5 : 7, "stroke-linecap": "round",
    "stroke-dasharray": "18 22", "stroke-opacity": 0.82
  }, reflections));
  const listener = reveal(subject, 1, "listener-character");
  node("path", { d: "M390 1160 Q390 970 540 955 Q690 970 690 1160 L740 1425 L340 1425 Z", fill: "#17243c", stroke: "#8da3c6", "stroke-width": 5 }, listener);
  node("circle", { cx: 540, cy: 865, r: 78, fill: "#bd9161", stroke: "#f4d9b2", "stroke-width": 4 }, listener);
  node("path", { d: "M463 866 Q455 760 545 760 Q632 765 620 885 Q580 830 520 838 Q495 845 463 866 Z", fill: "#0a1120" }, listener);
  node("path", { d: "M418 1070 Q325 1100 285 1215 L320 1250 Q400 1195 474 1180 M660 1070 Q755 1100 795 1215 L760 1250 Q680 1195 606 1180", fill: "none", stroke: "#bd9161", "stroke-width": 38, "stroke-linecap": "round" }, listener);
  node("path", { d: "M415 1410 L385 1500 M665 1410 L695 1500", stroke: "#0b1425", "stroke-width": 48, "stroke-linecap": "round" }, listener);
  const desk = reveal(subject, 2);
  node("path", { d: "M180 1435 L900 1435 L860 1490 L220 1490 Z", fill: "#654b37", stroke: "#d8bd91", "stroke-width": 4 }, desk);
}

function buildInterface(world) {
  const subject = node("g", { class: "scene-subject interface-subject" }, world);
  node("path", { d: "M540 520 L540 620 M540 1415 L540 1510", stroke: "#d8bd91", "stroke-opacity": 0.42, "stroke-width": 5, "stroke-dasharray": "10 18" }, subject);
  const chassis = reveal(subject, 0, "interface-chassis");
  node("rect", { x: 145, y: 555, width: 790, height: 800, rx: 38, fill: "#101b30", stroke: "#d8bd91", "stroke-width": 7 }, chassis);
  node("rect", { x: 174, y: 585, width: 732, height: 740, rx: 24, fill: "#1b2b45", stroke: "#7489a8", "stroke-opacity": 0.5, "stroke-width": 3 }, chassis);
  node("path", { d: "M205 950 L875 950", stroke: "#d8bd91", "stroke-opacity": 0.48, "stroke-width": 4 }, chassis);
  text(chassis, 540, 665, "CONSOLE-STYLE PREAMPS", 38, "#d8bd91", { "text-anchor": "middle" });
  for (let i = 0; i < 4; i += 1) {
    const cx = 300 + i * 160;
    node("circle", { cx, cy: 785, r: 62, fill: "#0b1425", stroke: "#d8bd91", "stroke-width": 5 }, chassis);
    node("circle", { cx, cy: 785, r: 42, fill: "#263c5d", stroke: "#7188ad", "stroke-width": 3 }, chassis);
    node("path", { d: "M" + cx + " 785 L" + (cx + 30) + " 755", stroke: "#f2d9b2", "stroke-width": 8, "stroke-linecap": "round", class: "interface-knob", "data-knob-index": i }, chassis);
    node("circle", { cx, cy: 785, r: 8, fill: "#70cfc4" }, chassis);
  }
  const screen = reveal(subject, 1, "interface-screen");
  node("rect", { x: 255, y: 1000, width: 570, height: 125, rx: 16, fill: "#081321", stroke: "#70cfc4", "stroke-width": 4 }, screen);
  for (let i = 0; i < 24; i += 1) {
    const height = 24 + ((i * 31) % 82);
    node("rect", { x: 285 + i * 22, y: 1110 - height, width: 11, height, rx: 5, fill: i % 3 ? "#70cfc4" : "#d8bd91", class: "interface-meter", "data-meter-height": height }, screen);
  }
  text(screen, 540, 1050, "ONBOARD DIGITAL PROCESSING", 29, "#e8edf6", { "text-anchor": "middle" });
  const dsp = reveal(subject, 2, "interface-dsp");
  [
    { x: 250, label: "EQ" }, { x: 455, label: "COMP" }, { x: 660, label: "REVERB" }
  ].forEach((item) => {
    node("rect", { x: item.x, y: 1185, width: 170, height: 72, rx: 15, fill: "#0b1728", stroke: "#d8bd91", "stroke-width": 3 }, dsp);
    text(dsp, item.x + 85, 1233, item.label, 31, "#d8bd91", { "text-anchor": "middle" });
  });
}

function buildRoomTune(world) {
  const subject = node("g", { class: "scene-subject roomtune-subject" }, world);
  const mic = reveal(subject, 0, "measurement-mic");
  node("path", { d: "M540 580 L540 800 M475 800 L605 800", stroke: "#d8bd91", "stroke-width": 10, "stroke-linecap": "round" }, mic);
  node("rect", { x: 495, y: 485, width: 90, height: 145, rx: 44, fill: "url(#vp-full-gold)", stroke: "#fff0d1", "stroke-width": 5 }, mic);
  node("path", { d: "M516 515 L516 600 M540 515 L540 600 M564 515 L564 600", stroke: "#5f6270", "stroke-width": 5 }, mic);
  [0, 1, 2].forEach((i) => {
    const left = 410 - i * 45, right = 670 + i * 45, top = 545 - i * 45, rise = 365 - i * 48;
    node("path", { d: "M" + left + " " + top + " Q540 " + rise + " " + right + " " + top, fill: "none", stroke: "#70cfc4", "stroke-width": 5, "stroke-dasharray": "12 18", class: "sound-wave", "stroke-opacity": 0.75 }, mic);
  });
  const steps = [
    { y: 735, label: "1  MEASURE", detail: "Microphone captures the room response" },
    { y: 915, label: "2  ANALYSE", detail: "The system identifies acoustic changes" },
    { y: 1095, label: "3  CORRECT", detail: "Monitor playback is adjusted" }
  ];
  steps.forEach((step, index) => {
    const process = reveal(subject, index + 1, "roomtune-step roomtune-step-" + index);
    node("rect", { x: 145, y: step.y, width: 790, height: 155, rx: 24, fill: "#14243c", stroke: index === 1 ? "#d8bd91" : "#70cfc4", "stroke-width": 4 }, process);
    text(process, 540, step.y + 62, step.label, 39, "#f3dfbb", { "text-anchor": "middle" });
    text(process, 540, step.y + 112, step.detail, 28, "#c6d1e1", { "text-anchor": "middle", "font-weight": 500, "letter-spacing": 0.2 });
    if (index < 2) {
      node("path", { d: "M540 " + (step.y + 158) + " L540 " + (step.y + 202) + " M525 " + (step.y + 188) + " L540 " + (step.y + 203) + " L555 " + (step.y + 188), fill: "none", stroke: "#d8bd91", "stroke-width": 6, "stroke-linecap": "round", "stroke-linejoin": "round" }, process);
    }
  });
}

function buildDspStages(world) {
  const subject = node("g", { class: "scene-subject dsp-subject" }, world);
  const stages = [
    { y: 550, label: "EQUALISATION", detail: "Shape the tonal balance", type: "eq" },
    { y: 820, label: "COMPRESSION", detail: "Control changing dynamics", type: "compress" },
    { y: 1090, label: "REVERB", detail: "Add a sense of space", type: "reverb" }
  ];
  stages.forEach((stage, index) => {
    const card = reveal(subject, index, "dsp-stage dsp-" + stage.type);
    node("rect", { x: 125, y: stage.y, width: 830, height: 220, rx: 30, fill: "#14233b", stroke: index === 1 ? "#d8bd91" : "#70cfc4", "stroke-width": 4 }, card);
    node("rect", { x: 155, y: stage.y + 28, width: 250, height: 184, rx: 20, fill: "#0b1425", stroke: "#526985", "stroke-width": 2 }, card);
    if (stage.type === "eq") {
      node("path", { d: "M180 " + (stage.y + 178) + " Q225 " + (stage.y + 176) + " 260 " + (stage.y + 105) + " T380 " + (stage.y + 65), fill: "none", stroke: "#8de6d7", "stroke-width": 9, "stroke-linecap": "round" }, card);
    } else if (stage.type === "compress") {
      node("path", { d: "M180 " + (stage.y + 130) + " L210 " + (stage.y + 60) + " L240 " + (stage.y + 195) + " L270 " + (stage.y + 90) + " L300 " + (stage.y + 165) + " L330 " + (stage.y + 110) + " L380 " + (stage.y + 130), fill: "none", stroke: "#8de6d7", "stroke-width": 8, "stroke-linejoin": "round" }, card);
    } else {
      for (let i = 0; i < 4; i += 1) {
        node("path", { d: "M" + (190 + i * 38) + " " + (stage.y + 82 + i * 18) + " Q" + (310 + i * 22) + " " + (stage.y + 10 + i * 18) + " " + (380 + i * 18) + " " + (stage.y + 130 + i * 18), fill: "none", stroke: i % 2 ? "#d8bd91" : "#70cfc4", "stroke-width": 5, "stroke-opacity": 0.8 - i * 0.12 }, card);
      }
    }
    text(card, 455, stage.y + 108, stage.label, 42, "#f2e5d1");
    text(card, 455, stage.y + 165, stage.detail, 28, "#bfcce0", { "font-weight": 500, "letter-spacing": 0.2 });
    for (let i = 0; i < 12; i += 1) {
      node("rect", { x: 455 + i * 34, y: stage.y + 205, width: 16, height: 10 + (i % 4) * 8, rx: 4, fill: i % 3 ? "#70cfc4" : "#d8bd91", class: "dsp-meter" }, card);
    }
  });
}

function buildViolin(world) {
  const subject = node("g", { class: "scene-subject violin-subject" }, world);
  const performer = reveal(subject, 0, "performer-character");
  node("path", { d: "M0 1200 Q140 900 360 980 L485 1510 L0 1510 Z", fill: "#1c2c47", stroke: "#8da3c6", "stroke-width": 5 }, performer);
  node("circle", { cx: 185, cy: 850, r: 92, fill: "#c89b67", stroke: "#f2d9b2", "stroke-width": 5 }, performer);
  node("path", { d: "M95 850 Q95 700 210 725 Q285 755 270 880 Q210 805 150 830 Z", fill: "#0a1120" }, performer);
  node("path", { d: "M285 1050 Q410 1010 485 1130", fill: "none", stroke: "#c89b67", "stroke-width": 48, "stroke-linecap": "round", class: "performer-arm" }, performer);
  const instrument = reveal(subject, 1, "illustrated-violin");
  node("path", { d: "M520 585 L560 585 L548 925 L530 960 L510 925 Z", fill: "#995d35", stroke: "#f0d4a6", "stroke-width": 5 }, instrument);
  node("circle", { cx: 540, cy: 560, r: 42, fill: "#995d35", stroke: "#f0d4a6", "stroke-width": 5 }, instrument);
  node("path", { d: "M520 650 L560 650 L550 1015 L530 1015 Z", fill: "#182238", stroke: "#d8bd91", "stroke-width": 3 }, instrument);
  node("path", { d: "M536 920 C440 845 345 895 355 1015 C285 1090 320 1235 405 1280 C425 1370 485 1440 540 1480 C595 1440 655 1370 675 1280 C760 1235 795 1090 725 1015 C735 895 640 845 544 920 Z", fill: "url(#vp-full-gold)", stroke: "#ffe5bd", "stroke-width": 7 }, instrument);
  node("path", { d: "M390 1045 Q450 1005 505 1050 L505 1245 Q445 1280 390 1225 M690 1045 Q630 1005 575 1050 L575 1245 Q635 1280 690 1225", fill: "none", stroke: "#70472c", "stroke-width": 12 }, instrument);
  node("path", { d: "M535 1105 L545 1105 M535 1180 L545 1180", stroke: "#493a32", "stroke-width": 9 }, instrument);
  node("path", { d: "M520 1260 L560 1260 L580 1400 L500 1400 Z", fill: "#754a2e", stroke: "#d8bd91", "stroke-width": 4 }, instrument);
  for (let i = 0; i < 4; i += 1) {
    node("path", { d: "M" + (526 + i * 9) + " 595 L" + (520 + i * 9) + " 1380", stroke: i === 1 ? "#fff3d9" : "#5b5046", "stroke-width": i === 1 ? 4 : 3, "stroke-opacity": 0.95 }, instrument);
  }
  const bow = reveal(subject, 2, "bow-rig");
  node("path", { d: "M180 1120 Q530 960 920 1110", fill: "none", stroke: "#d8bd91", "stroke-width": 15, "stroke-linecap": "round" }, bow);
  node("path", { d: "M180 1140 Q530 980 920 1130", fill: "none", stroke: "#fff0d1", "stroke-width": 4, "stroke-linecap": "round" }, bow);
  const notes = reveal(subject, 3, "violin-accents");
  node("path", { d: "M760 760 Q900 650 1010 750 M785 820 Q920 710 1035 810 M800 880 Q930 780 1060 880", fill: "none", stroke: "#70cfc4", "stroke-width": 6, "stroke-linecap": "round", "stroke-dasharray": "12 18", class: "sound-wave" }, notes);
  text(notes, 835, 650, "MUSIC", 38, "#d8bd91", { "text-anchor": "middle" });
}

const BUILDERS = {
  room_acoustics: buildRoom,
  audio_interface: buildInterface,
  roomtune_process: buildRoomTune,
  dsp_stages: buildDspStages,
  violin_performance_2d: buildViolin,
  signal_chain: buildRoomTune
};

function renderSceneIllustration(scene, topic = "") {
  const type = String(scene?.graphic_data?.type || "").toLowerCase();
  const caption = String(scene?.caption || topic || "Illustrated explanation");
  const svg = node("svg", {
    viewBox: "0 0 1080 1920", preserveAspectRatio: "xMidYMid slice",
    class: "scene-illustration", role: "img", "aria-label": caption,
    "data-scene-type": type
  });
  defs(svg);
  background(svg, type === "violin_performance_2d" ? "#bd9161" : "#70cfc4");
  const world = node("g", { class: "scene-world" }, svg);
  const builder = BUILDERS[type];
  if (builder) builder(world);
  else {
    const subject = node("g", { class: "scene-subject" }, world);
    text(subject, 540, 1050, caption || topic, 48, "#e8edf6", { "text-anchor": "middle" });
    text(subject, 540, 1150, "VISUAL EXPLANATION", 30, "#d8bd91", { "text-anchor": "middle" });
  }
  return svg;
}

function syncSceneIllustration(svg, seconds, progress = 0, sceneIndex = 0) {
  if (!svg) return;
  const t = Math.max(0, Number(seconds) || 0);
  const p = Math.max(0, Math.min(1, Number(progress) || 0));
  const world = svg.querySelector(".scene-world");
  if (world) {
    const scale = 1.015 + p * 0.065;
    const driftX = Math.sin(t * 0.32 + sceneIndex) * (sceneIndex === 4 ? 14 : 22);
    const driftY = -18 * p + Math.cos(t * 0.24) * 8;
    const tx = 540 * (1 - scale) + driftX;
    const ty = 960 * (1 - scale) + 180 + driftY;
    world.setAttribute("transform", "matrix(" + scale.toFixed(5) + " 0 0 " + scale.toFixed(5) + " " + tx.toFixed(2) + " " + ty.toFixed(2) + ")");
  }
  svg.querySelectorAll(".reveal-part").forEach((part) => {
    const order = Number(part.getAttribute("data-reveal-order") || 0);
    const revealValue = Math.max(0, Math.min(1, (p - order * 0.23) / 0.18));
    part.style.opacity = revealValue.toFixed(4);
    part.setAttribute("transform", "translate(0 " + ((1 - revealValue) * 26).toFixed(2) + ")");
  });
  svg.querySelectorAll(".sound-wave").forEach((path, index) => {
    path.setAttribute("stroke-dashoffset", String(-((t * 34 + index * 27) % 360)));
    path.setAttribute("opacity", String(0.56 + 0.34 * Math.sin(t * 1.8 + index)));
  });
  const listener = svg.querySelector(".listener-character");
  if (listener) listener.setAttribute("transform", "translate(0 " + (Math.sin(t * 1.35) * 8).toFixed(2) + ")");
  svg.querySelectorAll(".interface-knob").forEach((knob, index) => {
    const angle = -38 + ((t * 12 + index * 28) % 76);
    knob.setAttribute("transform", "rotate(" + angle.toFixed(2) + " " + (300 + index * 160) + " 785)");
  });
  svg.querySelectorAll(".interface-meter").forEach((meter, index) => {
    const height = 20 + 68 * (0.5 + 0.5 * Math.sin(t * 5 + index * 0.7));
    meter.setAttribute("height", String(height));
    meter.setAttribute("y", String(1120 - height));
  });
  const bow = svg.querySelector(".bow-rig");
  if (bow) bow.setAttribute("transform", "translate(0 " + (Math.sin(t * 5.2) * 26).toFixed(2) + ") rotate(" + (Math.sin(t * 5.2) * 3.6).toFixed(2) + " 540 1080)");
  const arm = svg.querySelector(".performer-arm");
  if (arm) arm.setAttribute("transform", "rotate(" + (Math.sin(t * 5.2) * 4.4).toFixed(2) + " 360 1080)");
  const violin = svg.querySelector(".illustrated-violin");
  if (violin) violin.setAttribute("transform", "rotate(" + (Math.sin(t * 1.1) * 1.8).toFixed(2) + " 540 1110)");
  svg.querySelectorAll(".dsp-meter").forEach((bar, index) => {
    const height = 10 + 30 * (0.5 + 0.5 * Math.sin(t * 4.4 + index));
    bar.setAttribute("height", String(height));
  });
}

export { renderSceneIllustration, syncSceneIllustration };
