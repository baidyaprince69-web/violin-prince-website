import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const source = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));

assert.match(html, /data-composition-id="main"/, "Composition ID must match the registered root timeline");
assert.match(html, /data-width="720"/, "Prototype must render at 720px wide");
assert.match(html, /data-height="1280"/, "Prototype must render at 1280px high");
assert.match(html, /data-duration="10"/, "Prototype must be exactly 10 seconds");
assert.match(html, /id="opening"[\s\S]*?data-start="0"/, "Opening scene timing is missing");
assert.match(html, /id="wave-section"[\s\S]*?data-track-index="1"/, "Waveform scene timing is missing");
assert.match(html, /id="outro"[\s\S]*?data-track-index="2"/, "Outro scene timing is missing");
assert.match(source, /animate\(/, "Motion must drive the composition");
assert.doesNotMatch(source, /document\.(getElementById|createElement)|appendChild/, "Scene elements must be authored statically for deterministic rendering");
assert.equal((html.match(/class="waveform-bar"/g) || []).length, 46, "Waveform must contain 46 authored bars");
for (const id of ["particles-opening", "particles-wave", "particles-outro"]) {
  assert.match(html, new RegExp(`id="${id}"`), `Missing authored particle field: ${id}`);
}
assert.match(source, /motionTimeline\.time\s*=/, "Motion must be explicitly seekable");
assert.match(source, /window\.__timelines\.main\s*=/, "HyperFrames root timeline must be registered");
assert.equal(manifest.dependencies.motion, "14.14.0");
assert.equal(manifest.dependencies.hyperframes, "0.9.52");
assert.equal(manifest.dependencies.gsap, "3.15.0");

console.log("Composition contract checks passed.");
