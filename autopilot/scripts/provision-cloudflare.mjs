import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../../..");
const accountId = process.env.CF_ACCOUNT_ID || process.env.CLOUDFLARE_ACCOUNT_ID;
const token = process.env.CF_API_TOKEN || process.env.CLOUDFLARE_API_TOKEN;
const databaseName = "violin-prince-autopilot";
const bucketName = "violin-prince-media";

if (!accountId || !token) {
  throw new Error("Set CF_ACCOUNT_ID and CF_API_TOKEN in the GitHub Actions environment.");
}

async function cloudflare(path, method = "GET", body) {
  const response = await fetch("https://api.cloudflare.com/client/v4" + path, {
    method,
    headers: {
      Authorization: "Bearer " + token,
      "Content-Type": "application/json"
    },
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success !== true) {
    const messages = (data.errors || []).map((item) => item.message).join("; ");
    throw new Error("Cloudflare API " + method + " " + path + " failed (" +
      response.status + "): " + (messages || "No detailed error returned."));
  }
  return data.result;
}

const d1Result = await cloudflare(
  "/accounts/" + accountId + "/d1/database?name=" + encodeURIComponent(databaseName) + "&per_page=100"
);
const d1Rows = Array.isArray(d1Result) ? d1Result : (d1Result.results || []);
let database = d1Rows.find((item) => item.name === databaseName);
if (!database) {
  database = await cloudflare(
    "/accounts/" + accountId + "/d1/database",
    "POST",
    { name: databaseName }
  );
}
const databaseId = database.uuid || database.id;
if (!databaseId) throw new Error("Cloudflare created/listed D1 but returned no database UUID.");

const r2Result = await cloudflare(
  "/accounts/" + accountId + "/r2/buckets?name_contains=" + encodeURIComponent(bucketName)
);
const buckets = Array.isArray(r2Result) ? r2Result : (r2Result.buckets || []);
let bucket = buckets.find((item) => item.name === bucketName);
if (!bucket) {
  bucket = await cloudflare(
    "/accounts/" + accountId + "/r2/buckets",
    "POST",
    { name: bucketName, locationHint: "apac", storageClass: "Standard" }
  );
}

const sourceConfig = resolve(repoRoot, "autopilot/cloudflare/wrangler.toml");
const generatedConfig = resolve(repoRoot, "autopilot/cloudflare/wrangler.generated.toml");
let config = await readFile(sourceConfig, "utf8");
config = config.replace("REPLACE_WITH_YOUR_D1_DATABASE_ID", databaseId);
if (config.includes("REPLACE_WITH_YOUR_D1_DATABASE_ID")) {
  throw new Error("Could not replace the D1 database placeholder.");
}
await writeFile(generatedConfig, config, "utf8");

const output = {
  d1_database: databaseName,
  d1_database_id: databaseId,
  r2_bucket: bucket.name || bucketName,
  wrangler_config: "autopilot/cloudflare/wrangler.generated.toml"
};
console.log(JSON.stringify(output, null, 2));
