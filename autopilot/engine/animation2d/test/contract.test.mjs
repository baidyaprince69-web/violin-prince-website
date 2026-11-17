import test from "node:test";
import assert from "node:assert/strict";
import { clampTime, springKeyframes, gestureKeyframes } from "../src/contract.mjs";

test("frame seek time is finite and clamped to the composition", () => {
  assert.equal(clampTime(-2, 4), 0);
  assert.equal(clampTime(2.5, 4), 2.5);
  assert.equal(clampTime(9, 4), 4);
  assert.equal(clampTime(Number.NaN, 4), 0);
});

test("spring keyframes are finite, bounded in count and settle near target", () => {
  const values = springKeyframes(0, 100, 25, 900);
  assert.ok(values.length >= 2);
  assert.equal(values[0], 0);
  assert.ok(values.every(Number.isFinite));
  assert.ok(Math.abs(values.at(-1) - 100) < 1);
});

test("gesture library includes arm and head movement presets", () => {
  const wave = gestureKeyframes("wave");
  assert.ok(wave.right_upper_arm);
  assert.ok(wave.right_forearm);
  assert.ok(gestureKeyframes("nod").head);
  assert.deepEqual(gestureKeyframes("unknown"), {});
});
