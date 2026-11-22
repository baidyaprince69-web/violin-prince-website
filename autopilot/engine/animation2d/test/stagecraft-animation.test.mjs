import test from "node:test";
import assert from "node:assert/strict";
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
