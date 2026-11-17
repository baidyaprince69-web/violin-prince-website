import test from "node:test";
import assert from "node:assert/strict";
import { gestureKeyframes } from "../src/contract.mjs";

test("character rig preview gestures resolve to independently animated parts", () => {
  for (const name of ["wave", "explain", "point_left", "point_right", "open_palms"]) {
    const gesture = gestureKeyframes(name);
    assert.ok(Object.keys(gesture).length > 0, name + " should have keyframes");
    for (const [role, properties] of Object.entries(gesture)) {
      assert.ok(role.endsWith("arm") || role.endsWith("forearm") || role.endsWith("hand"));
      for (const values of Object.values(properties)) {
        assert.ok(Array.isArray(values) && values.length >= 2);
      }
    }
  }
});
