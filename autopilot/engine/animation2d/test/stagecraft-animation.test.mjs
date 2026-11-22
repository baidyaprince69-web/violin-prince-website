import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildStagecraftMotion,
  renderStagecraftMarkup,
  stagecraftMotionNodeIds,
  stagecraftNodeCounts
} from "../src/stagecraft.mjs";

for (const environment of ["city_night", "forest_dusk", "space", "concert_stage"]) {
  test(environment + " produces a moving vector environment", () => {
    const scene = { id: "stage-test", start: 1, duration: 6, stagecraft: { environment } };
    const markup = renderStagecraftMarkup(scene);
    const ids = stagecraftMotionNodeIds(scene);
    const tracks = buildStagecraftMotion(scene);
    assert.ok(markup.includes("<svg"));
    assert.ok(markup.includes("scene-stagecraft--" + environment));
    assert.ok(ids.length >= 3);
    for (const id of ids) {
      const track = tracks.find(item => item.target === id && item.property === "transform");
      assert.ok(track, "missing transform track for " + id);
      assert.equal(track.loop, true);
      assert.equal(track.start, 1);
      assert.notDeepEqual(track.values[0], track.values[1]);
    }
    assert.equal(stagecraftNodeCounts(scene).total, ids.length);
  });
}

test("story-specific props are separate, moving SVG objects", () => {
  const scene = {
    id: "object-test", start: 0, duration: 4,
    stagecraft: {
      environment: "space",
      objects: [
        { id: "note", kind: "music_note", x: .2, y: .3, motion: "float", color: "#f0d49a" },
        { id: "gear", kind: "gear", x: .5, y: .5, motion: "rotate", size: 50 },
        { id: "comet", kind: "comet", x: .8, y: .7, motion: "travel_left" }
      ]
    }
  };
  const markup = renderStagecraftMarkup(scene);
  const ids = stagecraftMotionNodeIds(scene);
  const tracks = buildStagecraftMotion(scene);
  assert.ok(markup.includes(">♪</text>"));
  assert.ok(markup.includes("<polygon"));
  assert.equal(stagecraftNodeCounts(scene).objects, 3);
  for (const id of ids.filter(value => value.includes("-object-"))) {
    assert.ok(tracks.some(track => track.target === id && track.property === "transform"));
  }
});

test("invalid environment, object kind, duplicate id and color are rejected", () => {
  assert.throws(() => renderStagecraftMarkup({ id:"bad", stagecraft:{ environment:"photo" } }), /Unsupported stagecraft environment/);
  assert.throws(() => renderStagecraftMarkup({ id:"bad", stagecraft:{ environment:"space", objects:[{id:"x",kind:"jpeg"}] } }), /Unsupported stagecraft object kind/);
  assert.throws(() => renderStagecraftMarkup({ id:"bad", stagecraft:{ environment:"space", objects:[{id:"x"},{id:"x"}] } }), /IDs must be unique/);
  assert.throws(() => renderStagecraftMarkup({ id:"bad", stagecraft:{ environment:"space", objects:[{id:"x",color:"url(javascript:alert(1))"}] } }), /six-digit hexadecimal/);
});

test("stagecraft enters the real Motion composition with independent loop tracks", () => {
  const engineDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const buildScript = resolve(engineDirectory, "build.mjs");
  const temporary = mkdtempSync(resolve(tmpdir(), "vp-stagecraft-build-"));
  try {
    const projectPath = resolve(temporary, "project.json");
    const outputDirectory = resolve(temporary, "composition");
    const project = {
      title: "Procedural stagecraft integration proof",
      width: 720,
      height: 1280,
      fps: 25,
      duration_seconds: 4,
      scenes: [{
        id: "night-drive",
        start: 0,
        duration: 4,
        caption: "The city moves around the performer",
        stagecraft: {
          environment: "city_night",
          objects: [
            { id: "foreground-note", kind: "music_note", x: .82, y: .32, size: 28, color: "#e8c98f", motion: "float" },
            { id: "passing-light", kind: "light_streak", x: .23, y: .81, size: 54, color: "#66d9d5", motion: "travel_right" }
          ]
        }
      }],
      characters: []
    };
    writeFileSync(projectPath, JSON.stringify(project, null, 2));
    const result = spawnSync(process.execPath, [
      buildScript, "--project", projectPath, "--out-dir", outputDirectory
    ], { cwd: engineDirectory, encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr || result.stdout);

    const report = JSON.parse(readFileSync(resolve(outputDirectory, "motion-report.json"), "utf8"));
    const html = readFileSync(resolve(outputDirectory, "index.html"), "utf8");
    assert.equal(report.status, "passed");
    assert.equal(report.animated_stagecraft_scene_count, 1);
    assert.ok(report.animated_stagecraft_environment_node_count >= 4);
    assert.equal(report.animated_stagecraft_object_count, 2);
    assert.ok(report.animated_stagecraft_node_count >= 6);
    assert.ok(html.includes("scene-stagecraft--city_night"));
    assert.ok(html.includes("night-drive-stagecraft-traffic-a"));
    assert.ok(html.includes("night-drive-stagecraft-object-foreground-note"));
    assert.ok(html.includes('"loop":true'), "composition must preserve looping track metadata");

    const lint = spawnSync(resolve(engineDirectory, "node_modules/.bin/hyperframes"), [
      "lint", outputDirectory
    ], { cwd: engineDirectory, encoding: "utf8" });
    assert.equal(lint.status, 0, lint.stderr || lint.stdout || "HyperFrames rejected the procedural stagecraft composition");
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
