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
        }
      }],
      characters: []
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
  assert.ok(html.includes("visual-motif--rings"), "Macro illustration scenes should get the animated motif layer");
  assert.ok(report.total_motion_tracks >= 15, "The scene should include both infographic and ambient motion");
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
