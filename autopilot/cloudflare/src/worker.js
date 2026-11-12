const corsHeaders = {
  "Access-Control-Allow-Origin": "https://baidyaprince69-web.github.io",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Authorization,Content-Type,X-Filename,X-Rights-Confirmed",
  "Access-Control-Max-Age": "86400"
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json", "Cache-Control": "no-store" }
  });
}

function isoNow() {
  return new Date().toISOString();
}

function safeName(value) {
  return String(value || "upload.bin")
    .split(/[\\/]/).pop()
    .replace(/[^a-zA-Z0-9._-]/g, "_")
    .slice(0, 100) || "upload.bin";
}

function bearer(request) {
  return (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "").trim();
}

function equalsConstantTime(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i++) result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return result === 0;
}

function isAuthed(request, secret) {
  return Boolean(secret && equalsConstantTime(bearer(request), secret));
}

async function event(env, message, level = "info", runId = null) {
  if (!env.DB) return;
  await env.DB.prepare(
    "INSERT INTO events (run_id, level, message, created_at) VALUES (?, ?, ?, ?)"
  ).bind(runId, level, String(message).slice(0, 1000), isoNow()).run();
}

async function hmacHex(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value));
  return [...new Uint8Array(signature)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function signedMediaUrl(request, env, key, lifetimeSeconds = 86400) {
  const url = new URL(request.url);
  const expires = Math.floor(Date.now() / 1000) + lifetimeSeconds;
  const signature = await hmacHex(env.MEDIA_SIGNING_SECRET, key + ":" + expires);
  return url.origin + "/media/" + encodeURIComponent(key) + "?e=" + expires + "&s=" + signature;
}

async function dispatchWorkflow(env, mode = "scheduled") {
  if (env.AUTOPILOT_ENABLED !== "true") {
    await event(env, "Autopilot is disabled. No workflow was dispatched.", "warning");
    return { ok: false, reason: "disabled" };
  }
  if (!env.GITHUB_DISPATCH_TOKEN || !env.GITHUB_OWNER || !env.GITHUB_REPO || !env.GITHUB_WORKFLOW) {
    await event(env, "GitHub dispatch is not configured.", "error");
    return { ok: false, reason: "not_configured" };
  }

  const day = new Date().toISOString().slice(0, 10);
  const count = await env.DB.prepare(
    "SELECT COUNT(*) AS n FROM video_runs WHERE day_utc = ?"
  ).bind(day).first();
  if ((count && count.n ? count.n : 0) >= 1) {
    await event(env, "Daily video limit already reached; skipping this cycle.", "warning");
    return { ok: false, reason: "daily_limit" };
  }

  const active = await env.DB.prepare(
    "SELECT id FROM runs WHERE status IN ('queued','running') AND created_at >= ? LIMIT 1"
  ).bind(new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString()).first();
  if (active) {
    await event(env, "A recent run is still active; duplicate dispatch blocked.", "warning", active.id);
    return { ok: false, reason: "already_running" };
  }

  const runId = crypto.randomUUID();
  // Insert the run before dispatch so a fast GitHub runner cannot be overwritten by a later queued insert.
  await env.DB.prepare(
    "INSERT INTO runs (id,status,mode,created_at,updated_at) VALUES (?,?,?,?,?)"
  ).bind(runId, "queued", mode, isoNow(), isoNow()).run();
  const response = await fetch(
    "https://api.github.com/repos/" + env.GITHUB_OWNER + "/" + env.GITHUB_REPO +
      "/actions/workflows/" + env.GITHUB_WORKFLOW + "/dispatches",
    {
      method: "POST",
      headers: {
        "Authorization": "Bearer " + env.GITHUB_DISPATCH_TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "violin-prince-autopilot"
      },
      body: JSON.stringify({
        ref: env.GITHUB_REF || "main",
        inputs: { run_id: runId, mode: mode }
      })
    }
  );

  if (!response.ok) {
    const detail = (await response.text()).slice(0, 600);
    await env.DB.prepare("UPDATE runs SET status=?,message=?,updated_at=? WHERE id=?")
      .bind("failed", "GitHub dispatch failed: " + response.status, isoNow(), runId).run();
    await event(env, "GitHub dispatch failed: " + response.status + " " + detail, "error", runId);
    return { ok: false, reason: "github_dispatch_failed" };
  }

  await event(env, "Cloud workflow dispatched.", "success", runId);
  return { ok: true, run_id: runId };
}

async function handleApi(request, env) {
  const url = new URL(request.url);
  const path = url.pathname;

  if (path === "/api/health" && request.method === "GET") {
    return json({ ok: true, service: "violin-prince-autopilot", time: isoNow() });
  }

  const isInternal = path.startsWith("/internal/");
  if (isInternal) {
    if (!isAuthed(request, env.JOB_TOKEN)) return json({ error: "unauthorised" }, 401);
  } else {
    if (!isAuthed(request, env.DASHBOARD_TOKEN)) return json({ error: "unauthorised" }, 401);
  }

  if (path === "/api/status" && request.method === "GET") {
    const [latest, assetCount, todayCount, recentEvents] = await Promise.all([
      env.DB.prepare("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1").first(),
      env.DB.prepare("SELECT COUNT(*) AS n FROM assets WHERE active=1 AND rights_confirmed=1").first(),
      env.DB.prepare("SELECT COUNT(*) AS n FROM video_runs WHERE day_utc=?").bind(new Date().toISOString().slice(0, 10)).first(),
      env.DB.prepare("SELECT id,level,message,created_at FROM events ORDER BY id DESC LIMIT 8").all()
    ]);
    return json({
      enabled: env.AUTOPILOT_ENABLED === "true",
      latest_run: latest || null,
      approved_assets: assetCount && assetCount.n ? assetCount.n : 0,
      videos_today_utc: todayCount && todayCount.n ? todayCount.n : 0,
      daily_video_limit: 1,
      recent_events: recentEvents.results || []
    });
  }

  if (path === "/api/events" && request.method === "GET") {
    const rows = await env.DB.prepare(
      "SELECT id,run_id,level,message,created_at FROM events ORDER BY id DESC LIMIT 50"
    ).all();
    return json({ events: rows.results || [] });
  }

  if (path === "/api/assets" && request.method === "GET") {
    const rows = await env.DB.prepare(
      "SELECT id,filename,kind,size_bytes,rights_confirmed,active,created_at FROM assets ORDER BY created_at DESC LIMIT 100"
    ).all();
    return json({ assets: rows.results || [] });
  }

  if (path === "/api/assets" && request.method === "POST") {
    if (request.headers.get("X-Rights-Confirmed") !== "true") {
      return json({ error: "Confirm that you own or are licensed to use this media." }, 400);
    }
    const size = Number(request.headers.get("Content-Length") || 0);
    if (size > 90 * 1024 * 1024) return json({ error: "File exceeds the 90 MB upload limit." }, 413);
    const filename = safeName(request.headers.get("X-Filename"));
    const kind = url.searchParams.get("kind") || "audio";
    if (!["audio","video"].includes(kind)) return json({ error: "Unsupported asset type." }, 400);
    const allowed = /\.(mp3|wav|flac|m4a|aac|ogg|mp4|mov|webm)$/i.test(filename);
    if (!allowed) return json({ error: "Unsupported file extension." }, 400);
    const contentType = request.headers.get("Content-Type") || "application/octet-stream";
    const id = crypto.randomUUID();
    const key = "library/" + id + "/" + filename;
    await env.MEDIA.put(key, request.body, {
      httpMetadata: { contentType: contentType },
      customMetadata: { originalFilename: filename, assetId: id }
    });
    await env.DB.prepare(
      "INSERT INTO assets (id,object_key,filename,kind,content_type,size_bytes,rights_confirmed,active,created_at) VALUES (?,?,?,?,?,?,?,?,?)"
    ).bind(id,key,filename,kind,contentType,size,1,1,isoNow()).run();
    await event(env, "Library asset uploaded: " + filename);
    return json({ ok: true, id: id, filename: filename, size_bytes: size });
  }

  if (path === "/api/trigger" && request.method === "POST") {
    const result = await dispatchWorkflow(env, "manual");
    return json(result, result.ok ? 202 : 409);
  }

  if (path === "/internal/assets" && request.method === "GET") {
    const rows = await env.DB.prepare(
      "SELECT id,filename,kind,content_type,size_bytes,object_key FROM assets WHERE active=1 AND rights_confirmed=1 AND kind='audio' ORDER BY created_at DESC LIMIT 50"
    ).all();
    return json({ assets: rows.results || [] });
  }

  if (path.startsWith("/internal/assets/") && request.method === "GET") {
    const id = decodeURIComponent(path.split("/").pop());
    const asset = await env.DB.prepare(
      "SELECT object_key,filename,content_type FROM assets WHERE id=? AND active=1 AND rights_confirmed=1"
    ).bind(id).first();
    if (!asset) return json({ error: "asset_not_found" }, 404);
    const object = await env.MEDIA.get(asset.object_key);
    if (!object) return json({ error: "media_not_found" }, 404);
    return new Response(object.body, {
      headers: {
        "Content-Type": asset.content_type,
        "Content-Disposition": 'attachment; filename="' + safeName(asset.filename) + '"',
        "Cache-Control": "private, no-store"
      }
    });
  }

  if (path === "/internal/render" && request.method === "POST") {
    const size = Number(request.headers.get("Content-Length") || 0);
    if (size > 90 * 1024 * 1024) return json({ error: "Render exceeds the 90 MB upload limit." }, 413);
    const filename = safeName(request.headers.get("X-Filename") || "violin-prince-short.mp4");
    const key = "renders/" + new Date().toISOString().slice(0,10) + "/" + crypto.randomUUID() + "-" + filename;
    await env.MEDIA.put(key, request.body, {
      httpMetadata: { contentType: "video/mp4" },
      customMetadata: { filename: filename, generatedBy: "violin-prince-autopilot" }
    });
    const mediaUrl = await signedMediaUrl(request, env, key, 86400);
    return json({ ok: true, object_key: key, media_url: mediaUrl });
  }

  if (path === "/internal/report" && request.method === "POST") {
    const body = await request.json();
    const runId = String(body.run_id || "").slice(0, 80);
    if (!runId) return json({ error: "run_id_required" }, 400);
    const status = String(body.status || "unknown").slice(0, 40);
    const topic = String(body.topic || "").slice(0, 300);
    const title = String(body.title || "").slice(0, 300);
    const message = String(body.message || "").slice(0, 1000);
    const outputKey = String(body.output_key || "").slice(0, 500);
    const outputUrl = String(body.output_url || "").slice(0, 2000);
    await env.DB.prepare(
      "INSERT INTO runs (id,status,mode,topic,title,output_key,output_url,message,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?) " +
      "ON CONFLICT(id) DO UPDATE SET status=excluded.status,topic=excluded.topic,title=excluded.title,output_key=excluded.output_key,output_url=excluded.output_url,message=excluded.message,updated_at=excluded.updated_at"
    ).bind(runId,status,"scheduled",topic,title,outputKey,outputUrl,message,isoNow(),isoNow()).run();
    if (status === "rendered" || status === "published" || status === "partially_published") {
      const day = new Date().toISOString().slice(0,10);
      await env.DB.prepare("INSERT OR IGNORE INTO video_runs (run_id,day_utc,created_at) VALUES (?,?,?)")
        .bind(runId,day,isoNow()).run();
    }
    await event(env, message || ("Run status: " + status), status === "failed" ? "error" : "info", runId);
    return json({ ok: true });
  }

  return json({ error: "not_found" }, 404);
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders });
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/internal/")) {
      try { return await handleApi(request, env); }
      catch (error) {
        await event(env, "Worker error: " + (error && error.message ? error.message : error), "error");
        return json({ error: "internal_error", detail: String(error && error.message ? error.message : error).slice(0,300) }, 500);
      }
    }
    if (url.pathname.startsWith("/media/") && request.method === "GET") {
      try {
        const key = decodeURIComponent(url.pathname.slice("/media/".length));
        const expires = Number(url.searchParams.get("e") || 0);
        const signature = url.searchParams.get("s") || "";
        if (!key || !expires || expires < Math.floor(Date.now()/1000) || !env.MEDIA_SIGNING_SECRET) {
          return new Response("Link expired or invalid.", { status: 403 });
        }
        const expected = await hmacHex(env.MEDIA_SIGNING_SECRET, key + ":" + expires);
        if (!equalsConstantTime(signature, expected)) return new Response("Invalid signature.", { status: 403 });
        const object = await env.MEDIA.get(key);
        if (!object) return new Response("Not found.", { status: 404 });
        return new Response(object.body, {
          headers: { "Content-Type": "video/mp4", "Cache-Control": "public, max-age=300" }
        });
      } catch {
        return new Response("Unable to serve media.", { status: 500 });
      }
    }
    return json({ service: "Violin Prince Autopilot API", health: "/api/health" }, 200);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(dispatchWorkflow(env, "scheduled"));
  }
};
