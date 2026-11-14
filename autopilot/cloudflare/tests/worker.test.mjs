import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workerSource = await readFile(
  new URL("../src/worker.js", import.meta.url),
  "utf8",
);
const testableWorkerSource = workerSource + "\nexport { dispatchWorkflow };\n";
const workerModuleUrl =
  "data:text/javascript;base64," + Buffer.from(testableWorkerSource).toString("base64");
const { dispatchWorkflow } = await import(workerModuleUrl);

function makeEnvironment(overrides = {}) {
  const statements = [];
  let reservedRunId = null;
  const env = {
    AUTOPILOT_ENABLED: "false",
    GITHUB_DISPATCH_TOKEN: "dispatch-token-for-test",
    GITHUB_OWNER: "example-owner",
    GITHUB_REPO: "example-repo",
    GITHUB_WORKFLOW: "autopilot.yml",
    GITHUB_REF: "main",
    DB: {
      prepare(sql) {
        return {
          sql,
          args: [],
          bind(...args) {
            this.args = args;
            return this;
          },
          async first() {
            if (this.sql.includes("COUNT(*) AS n FROM video_runs")) return { n: 0 };
            if (this.sql.startsWith("SELECT id FROM runs")) return null;
            if (this.sql.startsWith("SELECT run_id FROM daily_dispatches")) {
              return reservedRunId ? { run_id: reservedRunId } : null;
            }
            return null;
          },
          async run() {
            statements.push({ sql: this.sql, args: this.args });
            if (this.sql.startsWith("INSERT OR IGNORE INTO daily_dispatches")) {
              reservedRunId = this.args[1];
            }
            if (this.sql.startsWith("DELETE FROM daily_dispatches") && reservedRunId === this.args[1]) {
              reservedRunId = null;
            }
            return { success: true };
          },
        };
      },
    },
    ...overrides,
  };
  return { env, statements, getReservation: () => reservedRunId };
}
async function withFetch(t, implementation) {
  const previous = globalThis.fetch;
  globalThis.fetch = implementation;
  t.after(() => {
    globalThis.fetch = previous;
  });
}

test("manual Worker dispatch sends the workflow inputs and preserves its run ID", async (t) => {
  const { env } = makeEnvironment();
  let requestedUrl = "";
  let requestBody;
  await withFetch(t, async (url, options) => {
    requestedUrl = String(url);
    requestBody = JSON.parse(options.body);
    assert.equal(options.method, "POST");
    return new Response(null, { status: 204 });
  });

  const result = await dispatchWorkflow(env, "manual");

  assert.equal(result.ok, true);
  assert.match(result.run_id, /^[0-9a-f-]{36}$/i);
  assert.equal(
    requestedUrl,
    "https://api.github.com/repos/example-owner/example-repo/actions/workflows/autopilot.yml/dispatches",
  );
  assert.deepEqual(requestBody.inputs, {
    stage: "full",
    run_id: result.run_id,
    run_mode: "manual",
  });
});

test("scheduled Worker dispatch is blocked while the scheduler flag is disabled", async (t) => {
  const { env } = makeEnvironment();
  let fetchCalled = false;
  await withFetch(t, async () => {
    fetchCalled = true;
    return new Response(null, { status: 204 });
  });

  const result = await dispatchWorkflow(env, "scheduled");

  assert.deepEqual(result, { ok: false, reason: "disabled" });
  assert.equal(fetchCalled, false);
});

test("a rejected GitHub dispatch marks the run failed and releases the daily lock", async (t) => {
  const { env, statements, getReservation } = makeEnvironment();
  await withFetch(t, async () => new Response("Invalid workflow input", { status: 422 }));

  const result = await dispatchWorkflow(env, "manual");

  assert.deepEqual(result, { ok: false, reason: "github_dispatch_failed" });
  const failedRun = statements.find((item) => item.sql.startsWith("UPDATE runs SET status="));
  const releasedLock = statements.find((item) => item.sql.startsWith("DELETE FROM daily_dispatches"));
  assert.ok(failedRun, "failed run status should be persisted");
  assert.equal(failedRun.args[0], "failed");
  assert.match(failedRun.args[1], /422/);
  assert.ok(releasedLock, "daily dispatch reservation should be released after rejection");
  assert.equal(releasedLock.args[1], failedRun.args[3]);
  assert.equal(getReservation(), null, "the fake D1 reservation should be clear after an explicit rejection");
});

test("a network failure records an unknown outcome and retains the daily lock", async (t) => {
  const { env, statements, getReservation } = makeEnvironment();
  await withFetch(t, async () => {
    throw new Error("simulated network outage");
  });

  const result = await dispatchWorkflow(env, "manual");

  assert.deepEqual(result, { ok: false, reason: "dispatch_outcome_unknown" });
  const unresolvedRun = statements.find((item) => item.sql.startsWith("UPDATE runs SET status="));
  const releasedLock = statements.find((item) => item.sql.startsWith("DELETE FROM daily_dispatches"));
  assert.ok(unresolvedRun);
  assert.equal(unresolvedRun.args[0], "dispatch_unknown");
  assert.match(unresolvedRun.args[1], /simulated network outage/);
  assert.equal(releasedLock, undefined, "an ambiguous delivery must retain the daily lock to prevent duplicate dispatch");
  assert.equal(getReservation(), unresolvedRun.args[3], "the reservation remains held until the outcome is reconciled");
});
