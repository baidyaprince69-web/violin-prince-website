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
  renderStagecraftForegroundMarkup,
  stagecraftMotionNodeIds,
  stagecraftNodeCounts
} from "../src/stagecraft.mjs";
import {
  compileMotionTracks,
  directorDepthPlaneParallaxKeyframes
} from "../src/motion-build.mjs";

for (const environment of ["city_night", "forest_dusk", "space", "concert_stage", "laboratory", "abstract"]) {
  test(environment + " produces a moving vector environment", () => {
    const scene = { id: "stage-test", start: 1, duration: 6, stagecraft: { environment } };
    const markup = renderStagecraftMarkup(scene);
    const ids = stagecraftMotionNodeIds(scene);
    const tracks = buildStagecraftMotion(scene);
    assert.ok(markup.includes("<svg"));
    assert.ok(markup.includes("scene-stagecraft--" + environment));
    assert.ok(markup.includes('class="clip scene-stagecraft'));
    if (environment === "laboratory") {
      assert.ok(markup.includes('stroke="#9ad7d5"'), "laboratory should retain its full-frame grid");
      assert.ok(markup.includes('fill="#62d7d1"'), "laboratory should retain soft atmospheric light");
      assert.ok(!markup.includes('rx="26"'), "laboratory must not render a rounded display card");
      assert.ok(!markup.includes('fill="#092a3a"'), "laboratory must not render a filled information panel");
    }
    if (environment === "concert_stage") {
      assert.ok(markup.includes('class="concert-stage-architecture"'));
      assert.ok(markup.includes("beam-teal"), "concert hall must include volumetric light shafts");
      assert.ok(markup.includes("velvet"), "concert hall must include velvet curtain material");
      assert.ok(stagecraftNodeCounts(scene).environment >= 14,
        "premium concert stage must animate lighting and atmospheric depth");
      const foreground = renderStagecraftForegroundMarkup(scene);
      assert.ok(foreground.includes('class="clip scene-stagecraft-foreground"'));
      assert.ok(foreground.includes("audience-fade"), "foreground audience plate must establish cinematic depth");
    }
    assert.ok(markup.includes('data-start="1"'));
    assert.ok(markup.includes('data-duration="6"'));
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

test("measured music cues create timed non-looping accents on animated props", () => {
  const scene = {
    id: "sync-test", start: 2, duration: 4,
    stagecraft: {
      environment: "concert_stage",
      objects: [{ id: "music-note", kind: "music_note", x: .5, y: .4, motion: "float" }],
      music_sync_cues: [{
        time_seconds: 3.5,
        requested_time_seconds: 3.5,
        event: "String reveal",
        reason: "The reveal lands on the measured beat.",
        timing_source: "decoded_audio_beat_grid",
        alignment_error_seconds: 0
      }]
    }
  };
  const tracks = buildStagecraftMotion(scene);
  const pulse = tracks.find(item => item.music_sync_event === "String reveal");
  assert.ok(pulse);
  assert.equal(pulse.property, "filter");
  assert.equal(pulse.start, 3.5);
  assert.equal(pulse.loop, false);
  assert.ok(pulse.target.includes("object-music-note"));
  assert.equal(pulse.music_sync_timing_source, "decoded_audio_beat_grid");
});

test("music cues outside the scene or without measured timing are rejected", () => {
  const base = {
    id: "sync-invalid", start: 2, duration: 4,
    stagecraft: {
      environment: "concert_stage",
      objects: [{ id: "note", kind: "music_note" }],
      music_sync_cues: [{
        time_seconds: 6.1,
        requested_time_seconds: 6.1,
        event: "Late cue",
        reason: "It is outside the scene.",
        timing_source: "decoded_audio_beat_grid",
        alignment_error_seconds: 0
      }]
    }
  };
  assert.throws(() => buildStagecraftMotion(base), /occur inside the animated scene/);
  base.stagecraft.music_sync_cues[0].time_seconds = 3;
  base.stagecraft.music_sync_cues[0].timing_source = "guessed_timing";
  assert.throws(() => buildStagecraftMotion(base), /aligned to a measured audio beat or onset/);
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
        visual_mode: "full_body_performance",
        director_camera: { movement: "truck_left", shot_size: "wide", direction: "left" },
        caption: "The city moves around the performer",
        stagecraft: {
          environment: "city_night",
          music_sync_cues: [{
            time_seconds: 1.5, requested_time_seconds: 1.5,
            event: "Beat accent", reason: "The visual reveal lands on the measured beat.",
            timing_source: "decoded_audio_beat_grid", alignment_error_seconds: 0
          }],
          objects: [
            { id: "foreground-note", kind: "music_note", x: .82, y: .32, size: 28, color: "#e8c98f", motion: "float", depth_plane: "midground" },
            { id: "passing-light", kind: "light_streak", x: .23, y: .81, size: 54, color: "#66d9d5", motion: "travel_right", depth_plane: "foreground" }
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
    assert.equal(report.music_sync_event_count, 1);
    assert.equal(report.music_sync_events[0].event, "Beat accent");
    assert.ok(report.animated_stagecraft_node_count >= 6);
    assert.equal(report.stagecraft_camera_parallax_track_count, 3);
    assert.equal(report.stagecraft_camera_parallax_scene_count, 1);
    assert.deepEqual(report.stagecraft_camera_parallax_depth_planes,
      ["background", "midground", "foreground"]);
    assert.ok(report.scenes[0].stagecraft_depth_plane_node_counts.background >= 1);
    assert.ok(report.scenes[0].stagecraft_depth_plane_node_counts.midground >= 1);
    assert.ok(report.scenes[0].stagecraft_depth_plane_node_counts.foreground >= 3);
    assert.ok(html.includes("scene-stagecraft--city_night"));
    assert.ok(html.includes("night-drive-stagecraft-plane-background"));
    assert.ok(html.includes("night-drive-stagecraft-plane-midground"));
    assert.ok(html.includes("night-drive-stagecraft-plane-foreground"));
    assert.ok(html.includes("night-drive-stagecraft-traffic-a"));
    assert.ok(html.includes("night-drive-stagecraft-object-foreground-note"));
    assert.ok(html.includes('"camera_parallax_depth_plane":"foreground"'));
    assert.ok(html.includes('"loop":true'), "composition must preserve looping track metadata");
    assert.ok(html.includes('"music_sync_event":"Beat accent"'), "composition must preserve the timed music cue animation");
    assert.ok(html.includes('id="night-drive-camera-world"'), "the environment must be placed in a camera-controlled scene world");
    assert.ok(html.includes('"target":"night-drive-camera-world"'), "camera motion must target the complete scene world");

    const lint = spawnSync(resolve(engineDirectory, "node_modules/.bin/hyperframes"), [
      "lint", outputDirectory
    ], { cwd: engineDirectory, encoding: "utf8" });
    assert.equal(lint.status, 0, lint.stderr || lint.stdout || "HyperFrames rejected the procedural stagecraft composition");
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});

test("float and bob motions use valid comma-separated CSS translate arguments", () => {
  const scene = {
    id: "motion-css-test",
    start: 0,
    duration: 4,
    stagecraft: {
      environment: "abstract",
      objects: [
        { id: "float-note", kind: "music_note", x: .35, y: .35, motion: "float", amplitude: 24 },
        { id: "bob-orb", kind: "orb", x: .65, y: .65, motion: "bob", amplitude: 18 }
      ]
    }
  };
  const tracks = buildStagecraftMotion(scene);
  for (const id of stagecraftMotionNodeIds(scene).filter(value => value.includes("-object-"))) {
    const track = tracks.find(item => item.target === id && item.property === "transform");
    assert.ok(track, "missing ambient motion for " + id);
    for (const value of track.values) {
      if (String(value).includes("translate(")) {
        const transform = String(value).slice(String(value).indexOf("translate("), String(value).indexOf(")") + 1);
        assert.ok(transform.includes(","), "two-axis translate must separate coordinates with a comma: " + value);
      }
    }
  }
});


test("every environment has its own moving near-camera depth plane", () => {
  for (const environment of ["city_night", "forest_dusk", "space", "concert_stage", "laboratory", "abstract"]) {
    const scene = { id: "depth-" + environment, start: 0, duration: 8, stagecraft: { environment } };
    const ids = stagecraftMotionNodeIds(scene);
    const nearIds = ids.filter(value => value.includes("-depth-foreground-"));
    const markup = renderStagecraftMarkup(scene);
    const counts = stagecraftNodeCounts(scene);
    const tracks = buildStagecraftMotion(scene);

    assert.ok(nearIds.length >= 1, environment + " must define a near-camera element");
    assert.equal(counts.foreground_depth, nearIds.length);
    assert.ok(markup.includes('data-depth-plane="foreground"'), environment + " must mark the near plane");
    assert.ok(markup.includes("stagecraft-node--foreground"), environment + " must render a distinct foreground node class");
    for (const id of nearIds) {
      const track = tracks.find(item => item.target === id && item.property === "transform");
      assert.ok(track, environment + " is missing independent foreground motion for " + id);
      assert.equal(track.loop, true);
      assert.equal(track.start, 0);
      assert.ok(track.duration <= scene.duration);
    }
  }
});



test("story objects render into explicit background, midground and foreground planes", () => {
  const scene = {
    id: "story-depth-planes", start: 0, duration: 4,
    stagecraft: {
      environment: "concert_stage",
      objects: [
        { id: "far-lights", kind: "spark", x: .2, y: .2, depth_plane: "background" },
        { id: "story-core", kind: "orb", x: .5, y: .5, depth_plane: "midground" },
        { id: "lens-trail", kind: "light_streak", x: .8, y: .8, depth_plane: "foreground" }
      ]
    }
  };
  const html = renderStagecraftMarkup(scene);
  const counts = stagecraftNodeCounts(scene);
  assert.ok(html.includes('id="story-depth-planes-stagecraft-plane-background"'));
  assert.ok(html.includes('id="story-depth-planes-stagecraft-plane-midground"'));
  assert.ok(html.includes('id="story-depth-planes-stagecraft-plane-foreground"'));
  assert.ok(html.includes('data-depth-plane="background"'));
  const backgroundStart = html.indexOf('id="story-depth-planes-stagecraft-plane-background"');
  const midgroundStart = html.indexOf('id="story-depth-planes-stagecraft-plane-midground"');
  const foregroundStart = html.indexOf('id="story-depth-planes-stagecraft-plane-foreground"');
  const backgroundObject = html.indexOf('id="story-depth-planes-stagecraft-object-far-lights"');
  const midgroundObject = html.indexOf('id="story-depth-planes-stagecraft-object-story-core"');
  const foregroundObject = html.indexOf('id="story-depth-planes-stagecraft-object-lens-trail"');
  assert.ok(backgroundObject > backgroundStart && backgroundObject < midgroundStart,
    "background-authored story object must be inside the background plane");
  assert.ok(midgroundObject > midgroundStart && midgroundObject < foregroundStart,
    "midground-authored story object must be inside the midground plane");
  assert.ok(foregroundObject > foregroundStart,
    "foreground-authored story object must be inside the foreground plane");
  assert.equal(counts.background_depth, 2);
  assert.ok(counts.midground_depth >= 1, "the concert environment also contributes midground nodes");
  assert.ok(counts.foreground_depth >= 1, "the story foreground object must be counted");
  assert.equal(counts.objects, 3);
  assert.throws(() => renderStagecraftMarkup({
    id: "bad-depth", stagecraft: { environment: "space", objects: [
      { id: "bad", kind: "spark", depth_plane: "foreground-ish" }
    ]}
  }), /depth_plane must be background, midground or foreground/);
});

test("shot camera movement drives graduated background, midground and foreground parallax", () => {
  const camera = { movement: "truck_left", shot_size: "wide" };
  const background = directorDepthPlaneParallaxKeyframes(camera, 0, "background");
  const midground = directorDepthPlaneParallaxKeyframes(camera, 0, "midground");
  const foreground = directorDepthPlaneParallaxKeyframes(camera, 0, "foreground");
  const firstTranslate = values => Number(String(values[0]).match(/translateX\((-?[0-9.]+)px\)/)?.[1]);
  assert.equal(background.length, 2);
  assert.equal(midground.length, 2);
  assert.equal(foreground.length, 2);
  assert.ok(Math.abs(firstTranslate(background)) < Math.abs(firstTranslate(midground)));
  assert.ok(Math.abs(firstTranslate(midground)) < Math.abs(firstTranslate(foreground)));

  const scene = {
    id: "director-parallax-shot",
    start: 2,
    duration: 3,
    visual_mode: "full_body_performance",
    editorial_index: 1,
    director_camera: camera,
    stagecraft: { environment: "forest_dusk", objects: [
      { id: "far-beacon", kind: "spark", depth_plane: "background" },
      { id: "story-pulse", kind: "orb", depth_plane: "midground" },
      { id: "near-leaf", kind: "leaf", depth_plane: "foreground" }
    ]}
  };
  const tracks = compileMotionTracks({ scenes: [scene], characters: [] }, { fps: 25 });
  const planeTracks = ["background", "midground", "foreground"].map(plane =>
    tracks.find(track =>
      track.target === "director-parallax-shot-stagecraft-plane-" + plane &&
      track.property === "transform"
    )
  );
  assert.ok(planeTracks.every(Boolean), "all depth planes must receive camera-linked transform tracks");
  assert.deepEqual(planeTracks.map(track => track.camera_parallax_depth_plane),
    ["background", "midground", "foreground"]);
  assert.ok(planeTracks.every(track => track.camera_parallax_source === "master_director_shot_camera"));
  assert.ok(planeTracks.every(track => track.start === 2 && track.duration === 3));
});

