import test from "node:test";
import assert from "node:assert/strict";
import { fitCharacterToCanvas } from "../src/character-layout.mjs";

test("landscape character is centered and fit to a portrait Shorts canvas", () => {
  const layout = fitCharacterToCanvas(
    { canvas: { width: 2032, height: 1104 } },
    720,
    1280
  );
  assert.ok(Math.abs(layout.scale - (720 / 2032)) < 1e-9);
  assert.ok(Math.abs(layout.width - 720) < 1e-9);
  assert.ok(layout.height < 400);
  assert.equal(layout.offsetX, 0);
  assert.ok(layout.offsetY > 400);
});

test("matching character and composition dimensions do not shift or scale", () => {
  const layout = fitCharacterToCanvas(
    { canvas: { width: 2032, height: 1104 } },
    2032,
    1104
  );
  assert.equal(layout.scale, 1);
  assert.equal(layout.offsetX, 0);
  assert.equal(layout.offsetY, 0);
  assert.equal(layout.width, 2032);
  assert.equal(layout.height, 1104);
});

test("invalid canvas dimensions fail clearly", () => {
  assert.throws(
    () => fitCharacterToCanvas({ canvas: { width: 0, height: 100 } }, 720, 1280),
    /positive finite numbers/
  );
});
