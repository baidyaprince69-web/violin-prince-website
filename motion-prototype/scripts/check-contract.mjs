import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const source = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));

assert.ok(html.includes('data-composition-id="main"'), "Composition ID must be present");
assert.ok(html.includes("data-no-timeline"), "Root must opt out of GSAP timeline registration");
assert.ok(html.includes('data-width="720"'), "Prototype width must be 720px");
assert.ok(html.includes('data-height="1280"'), "Prototype height must be 1280px");
assert.ok(html.includes('data-duration="10"'), "Prototype duration must be 10 seconds");
assert.ok(html.includes('id="opening"') && html.includes('data-start="0"'), "Opening scene timing is missing");
assert.ok(html.includes('id="wave-section"') && html.includes('data-track-index="1"'), "Waveform scene is missing");
assert.ok(html.includes('id="outro"') && html.includes('data-track-index="2"'), "Outro scene is missing");
assert.equal(html.split('class="waveform-bar"').length - 1, 46, "Waveform must contain 46 authored bars");

for (const id of ["particles-opening", "particles-wave", "particles-outro"]) {
  assert.ok(html.includes('id="' + id + '"'), "Missing authored particle field: " + id);
}
assert.ok(source.includes('animate('), "Motion must drive the composition");
assert.ok(source.includes('controls.time ='), "Motion controls must be explicitly seekable");
assert.ok(source.includes('addEventListener("hf-seek"'), "Motion must respond to HyperFrames frame seeks");
assert.ok(!source.includes('gsap') && !source.includes('window.__timelines'), "Motion adapter must not register a dummy GSAP timeline");
assert.equal(manifest.dependencies.motion, "14.14.0");
assert.equal(manifest.dependencies.hyperframes, "0.9.52");
assert.ok(!manifest.dependencies.gsap, "GSAP should not be required");

console.log("Motion frame-adapter contract checks passed.");
