import test from "node:test";
import assert from "node:assert/strict";
import { fingeringRolesForPerformanceCharacter } from "../src/full-body-performance-contract.mjs";

test("fingering remains mandatory for a normal full-body performance rig", () => {
  const contract = fingeringRolesForPerformanceCharacter({
    performance: { instrument_performance: true }
  });
  assert.equal(contract.enabled, true);
  assert.deepEqual(contract.controlRoles, [
    "finger_index", "finger_middle", "finger_ring", "finger_little"
  ]);
  assert.equal(contract.segmentRoles.length, 12);
  assert.ok(contract.segmentRoles.includes("finger_index_middle"));
  assert.ok(contract.segmentRoles.includes("finger_little_tip"));
});

test("only an explicit intact-hand setting disables separate finger requirements", () => {
  const candidate = fingeringRolesForPerformanceCharacter({
    performance: {
      instrument_performance: true,
      fingering_articulation_enabled: false
    }
  });
  assert.deepEqual(candidate, {
    enabled: false,
    controlRoles: [],
    segmentRoles: []
  });

  // Missing or undefined configuration must never silently bypass rig checks.
  assert.equal(fingeringRolesForPerformanceCharacter({}).enabled, true);
  assert.equal(fingeringRolesForPerformanceCharacter({
    performance: { fingering_articulation_enabled: null }
  }).enabled, true);
});
