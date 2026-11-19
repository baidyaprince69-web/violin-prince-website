import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const engineDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const buildScript = resolve(engineDirectory, "build.mjs");

function buildFixture(graphicData) {
  const temporary = mkdtempSync(resolve(tmpdir(), "violin-prince-motion-"));
  try {
    const projectPath = resolve(temporary, "project.json");
    const outputDirectory = resolve(temporary, "render");
    const project = {
      title: "Motion graphic contract test",
      width: 720,
      height: 1280,
      fps: 25,
      duration_seconds: 4,
      scenes: [{
        id: "explainer",
        start: 0,
        duration: 4,
        visual_mode: "macro_illustration",
        title: "The explanation",
        caption: "Watch the signal move",
        graphic_data: graphicData,
        visual_composition: {
          layout: "graphic_left_presenter_right",
          graphic_area: "left_column",
          presenter_area: "right_column"
        },
        character_actions: {
          "violin-prince": {
            visible: true,
            x: 388,
            y: 180,
            scale: 0.46,
            start_offset: 0.18,
            duration: 3.82,
            gesture: "point_left",
            expression: "speaking"
          }
        }
      }],
      characters: [{
        id: "violin-prince",
        canvas: { width: 720, height: 1280 },
        layers: [
          { id: "left-upper-arm", role: "left_upper_arm", src: "left-upper-arm.png",
            x: 230, y: 330, width: 150, height: 190, pivot_x: 0.75, pivot_y: 0.25, z_index: 20 },
          { id: "left-forearm", role: "left_forearm", src: "left-forearm.png",
            x: 145, y: 475, width: 145, height: 140, pivot_x: 0.8, pivot_y: 0.22, z_index: 30 },
          { id: "left-hand", role: "left_hand", src: "left-hand.png",
            x: 100, y: 570, width: 80, height: 80, pivot_x: 0.85, pivot_y: 0.4, z_index: 40 }
        ],
        joints: {
          left_shoulder: { x: 0.44, y: 0.34 },
          left_elbow: { x: 0.34, y: 0.47 },
          left_wrist: { x: 0.25, y: 0.56 }
        },
        expressions: {},
        pose_assets: {}
      }]
    };
    writeFileSync(projectPath, JSON.stringify(project, null, 2));
    const result = spawnSync(process.execPath, [
      buildScript, "--project", projectPath, "--out-dir", outputDirectory
    ], { cwd: engineDirectory, encoding: "utf8" });
    return { temporary, outputDirectory, result };
  } catch (error) {
    rmSync(temporary, { recursive: true, force: true });
    throw error;
  }
}

const successful = buildFixture({
  type: "process_flow",
  title: "ROOMTUNE SIGNAL PATH",
  items: [
    { label: "MEASURE THE ROOM", reveal_at: 0.3 },
    { label: "APPLY DSP CORRECTION", reveal_at: 1.1 },
    { label: "ADJUST MONITOR OUTPUT", reveal_at: 2.0 }
  ]
});
try {
  assert.equal(successful.result.status, 0, successful.result.stderr || successful.result.stdout);
  const report = JSON.parse(readFileSync(resolve(successful.outputDirectory, "motion-report.json"), "utf8"));
  const html = readFileSync(resolve(successful.outputDirectory, "index.html"), "utf8");
  assert.equal(report.status, "passed");
  assert.equal(report.animated_graphic_scene_count, 1);
  assert.equal(report.animated_graphic_item_count, 3);
  assert.ok(report.total_motion_tracks >= 10, "The diagram should have its own motion timeline");
  for (const id of ["explainer-graphic-node-0", "explainer-graphic-node-1", "explainer-graphic-node-2"]) {
    assert.ok(html.includes(id), "Missing rendered animated graphic node " + id);
  }
  assert.ok(html.includes("ROOMTUNE SIGNAL PATH"));
  assert.ok(html.includes("graphic-connector"));
  assert.ok(html.includes("scene-brand__name"), "Every scene should carry the premium editorial brand rail");
  assert.ok(html.includes("scene-brand__chapter"), "Every scene should display its own chapter label");
  assert.ok(html.includes("scene-grade"), "Every scene should receive the cinematic grade layer");
  assert.ok(html.includes('"target":"explainer-grade","property":"opacity"'),
    "The cinematic grade must have its own entrance animation");
  assert.ok(html.includes("DMSerifDisplay"), "Premium display typography must be bundled into the composition");
  assert.ok(html.includes("DMSans"), "Premium supporting typography must be bundled into the composition");
  assert.ok(html.includes("scene-caption--intro"), "The opening hook should use its own caption treatment");
  assert.ok(html.includes("motion-graphic--with-presenter"), "The explainer should use the editorial split layout");
  assert.ok(html.includes("visual-motif--rings"), "Macro illustration scenes should get the animated motif layer");
  assert.ok(html.includes("explainer-violin-prince"), "The presenter must render in the combined explanatory scene");
  assert.ok(html.includes("motion-graphic--with-presenter"), "The diagram must use the presenter-aware split layout");
  assert.equal(report.animated_presenter_count, 1, "The presenter must have articulated motion tracks");
  assert.ok(report.total_motion_tracks >= 20, "The scene should include infographic, ambient and presenter motion");
} finally {
  rmSync(successful.temporary, { recursive: true, force: true });
}

const rejected = buildFixture({
  type: "process_flow",
  title: "Incomplete flow",
  items: [{ label: "ONLY ONE STEP" }]
});
try {
  assert.notEqual(rejected.result.status, 0, "A broken motion-graphic plan must not fall back to a static picture");
  assert.match(rejected.result.stderr + rejected.result.stdout, /two to four process items/);
} finally {
  rmSync(rejected.temporary, { recursive: true, force: true });
}

console.log("Scene graphics render and anti-static fallback contracts passed.");
