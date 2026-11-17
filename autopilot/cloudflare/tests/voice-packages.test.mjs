import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const workerSource = await readFile(new URL("../src/worker.js", import.meta.url), "utf8");
const workerModuleUrl = "data:text/javascript;base64," + Buffer.from(workerSource).toString("base64");
const { default: worker } = await import(workerModuleUrl);

const DASHBOARD_TOKEN = "dashboard-test-token";
const JOB_TOKEN = "job-test-token";

function encryptedPackage(size = 96) {
  const bytes = new Uint8Array(size);
  bytes.set(new TextEncoder().encode("VPRVOICE"), 0);
  new DataView(bytes.buffer).setUint32(36, 600000, false);
  // Test payload bytes are opaque ciphertext-like bytes. This fixture never
  // attempts to decrypt or interpret the user recording.
  for (let index = 40; index < bytes.length; index++) bytes[index] = (index * 29) & 0xff;
  return bytes;
}

function makeEnvironment() {
  const stored = new Map();
  return {
    stored,
    env: {
      DASHBOARD_TOKEN,
      JOB_TOKEN,
      MEDIA: {
        async put(key, value, options = {}) {
          const bytes = value instanceof Uint8Array
            ? new Uint8Array(value)
            : new Uint8Array(await new Response(value).arrayBuffer());
          stored.set(key, { bytes, customMetadata: options.customMetadata || {} });
        },
        async get(key) {
          const item = stored.get(key);
          if (!item) return null;
          return {
            body: new Blob([item.bytes]).stream(),
            customMetadata: item.customMetadata
          };
        },
        async delete(keyOrKeys) {
          for (const key of Array.isArray(keyOrKeys) ? keyOrKeys : [keyOrKeys]) stored.delete(key);
        },
        async list({ prefix = "" } = {}) {
          return {
            objects: [...stored.keys()]
              .filter(key => key.startsWith(prefix))
              .map(key => ({ key, uploaded: new Date() })),
            truncated: false
          };
        }
      }
    }
  };
}

async function call(env, path, { method = "GET", token = DASHBOARD_TOKEN, headers = {}, body } = {}) {
  const requestHeaders = new Headers(headers);
  if (token) requestHeaders.set("Authorization", "Bearer " + token);
  return await worker.fetch(new Request("https://voice-test.example" + path, {
    method,
    headers: requestHeaders,
    body
  }), env);
}

test("voice package upload requires dashboard authentication", async () => {
  const { env, stored } = makeEnvironment();
  const response = await call(env, "/api/voice-packages", {
    method: "POST",
    token: "",
    headers: { "X-Filename": "voice.vprvoice", "X-File-Size": "96" },
    body: encryptedPackage()
  });
  assert.equal(response.status, 401);
  assert.equal(stored.size, 0);
});

test("only a valid encrypted .vprvoice package is accepted", async () => {
  const { env, stored } = makeEnvironment();
  const wrongExtension = await call(env, "/api/voice-packages", {
    method: "POST",
    headers: { "X-Filename": "voice.wav", "X-File-Size": "96" },
    body: encryptedPackage()
  });
  assert.equal(wrongExtension.status, 400);

  const wrongMagic = encryptedPackage();
  wrongMagic.set(new TextEncoder().encode("NOTVOICE"), 0);
  const badPackage = await call(env, "/api/voice-packages", {
    method: "POST",
    headers: { "X-Filename": "voice.vprvoice", "X-File-Size": String(wrongMagic.length) },
    body: wrongMagic
  });
  assert.equal(badPackage.status, 400);

  const wrongIterations = encryptedPackage();
  new DataView(wrongIterations.buffer).setUint32(36, 1000, false);
  const badHeader = await call(env, "/api/voice-packages", {
    method: "POST",
    headers: { "X-Filename": "voice.vprvoice", "X-File-Size": String(wrongIterations.length) },
    body: wrongIterations
  });
  assert.equal(badHeader.status, 400);
  assert.equal(stored.size, 0);
});

test("upload enforces the 50 MB limit and exact declared byte count", async () => {
  const { env, stored } = makeEnvironment();
  const oversized = await call(env, "/api/voice-packages", {
    method: "POST",
    headers: { "X-Filename": "voice.vprvoice", "X-File-Size": String(50 * 1024 * 1024 + 1) }
  });
  assert.equal(oversized.status, 413);

  const bytes = encryptedPackage();
  const mismatched = await call(env, "/api/voice-packages", {
    method: "POST",
    headers: { "X-Filename": "voice.vprvoice", "X-File-Size": String(bytes.length + 1) },
    body: bytes
  });
  assert.equal(mismatched.status, 400);
  assert.equal(stored.size, 0);
});

test("encrypted package is private, retrievable only with JOB_TOKEN, and deletable by dashboard", async () => {
  const { env, stored } = makeEnvironment();
  const bytes = encryptedPackage();
  const uploaded = await call(env, "/api/voice-packages", {
    method: "POST",
    headers: {
      "X-Filename": "violin-prince-voice.vprvoice",
      "X-File-Size": String(bytes.length),
      "Content-Type": "application/octet-stream"
    },
    body: bytes
  });
  assert.equal(uploaded.status, 201);
  const result = await uploaded.json();
  assert.equal(result.ok, true);
  assert.match(result.package_id, /^[0-9a-f-]{36}$/i);
  assert.equal(result.size_bytes, bytes.length);
  assert.equal(stored.size, 1);
  assert.ok(stored.has("voice-packages/" + result.package_id + ".vprvoice"));

  const denied = await call(env, "/internal/voice-packages/" + result.package_id, {
    token: DASHBOARD_TOKEN
  });
  assert.equal(denied.status, 401);

  const downloaded = await call(env, "/internal/voice-packages/" + result.package_id, {
    token: JOB_TOKEN
  });
  assert.equal(downloaded.status, 200);
  assert.equal(downloaded.headers.get("cache-control"), "private, no-store");
  assert.equal(downloaded.headers.get("content-type"), "application/octet-stream");
  assert.match(downloaded.headers.get("content-disposition"), /attachment/);
  assert.deepEqual(new Uint8Array(await downloaded.arrayBuffer()), bytes);

  const deleted = await call(env, "/api/voice-packages/" + result.package_id, {
    method: "DELETE"
  });
  assert.equal(deleted.status, 200);
  assert.equal((await deleted.json()).deleted, true);
  assert.equal(stored.size, 0);
});

test("unknown package IDs return 404 and internal retrieval remains private", async () => {
  const { env } = makeEnvironment();
  const response = await call(env, "/internal/voice-packages/00000000-0000-4000-8000-000000000000", {
    token: JOB_TOKEN
  });
  assert.equal(response.status, 404);
  assert.equal(response.headers.get("cache-control"), "no-store");
});
