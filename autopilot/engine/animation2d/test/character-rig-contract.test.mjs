import test from "node:test";
import assert from "node:assert/strict";
import { gestureKeyframes } from "../src/contract.mjs";

test("character rig preview gestures resolve to independently animated parts", () => {
  for (const name of ["wave", "explain", "point_left", "point_right", "open_palms"]) {
    const gesture = gestureKeyframes(name);
    assert.ok(Object.keys(gesture).length > 0, name + " should have keyframes");
    for (const [role, properties] of Object.entries(gesture)) {
      assert.ok(
        role.endsWith("arm") || role.endsWith("forearm") ||
        role.endsWith("hand") || role === "head",
        role + " should be an articulated arm, hand or head layer"
      );
      for (const values of Object.values(properties)) {
        assert.ok(Array.isArray(values) && values.length >= 2);
      }
    }
  }

  for (const name of ["point_left", "point_right"]) {
    const gesture = gestureKeyframes(name);
    assert.ok(gesture.head, name + " should include a coordinated head gesture");
    assert.ok(
      Object.values(gesture).some(properties =>
        Object.values(properties).some(values => values.length >= 4)
      ),
      name + " should retain multiple emphasis beats"
    );
  }
});
