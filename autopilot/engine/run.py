#!/usr/bin/env python3
"""Free-first cloud producer. Never switches to a paid service."""
import base64, json, os, re, subprocess, sys, textwrap, time, uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

API = os.environ["AUTOPILOT_API_URL"].rstrip("/")
JOB_TOKEN = os.environ["AUTOPILOT_JOB_TOKEN"]
CF_ACCOUNT = os.environ["CF_ACCOUNT_ID"]
CF_TOKEN = os.environ["CF_AI_TOKEN"]
RUN_ID = os.environ.get("RUN_ID", str(uuid.uuid4()))
TEXT_MODEL = "@cf/google/gemma-4-26b-a4b-it"
IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
WORK, OUT, IMAGES = Path("work"), Path("work/output"), Path("work/images")
W, H, FPS, SECONDS = 720, 1280, 25, 8
http = requests.Session()
http.headers["User-Agent"] = "ViolinPrinceAutopilot/0.1"


class PipelineError(RuntimeError):
    pass


def log(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", flush=True)


def auth():
    return {"Authorization": "Bearer " + JOB_TOKEN}


def report(status, message, topic="", title="", key="", url="", metadata=None):
    try:
        r = http.post(API + "/internal/report", headers={**auth(), "Content-Type": "application/json"},
                      json={"run_id": RUN_ID, "status": status, "message": str(message)[:900],
                            "topic": topic[:300], "title": title[:300],
                            "output_key": key[:500], "output_url": url[:2000],
                            "metadata": metadata}, timeout=30)
        r.raise_for_status()
    except Exception as exc:
        log("Status report failed: " + str(exc))


def claim_run():
    r = http.post(API + "/internal/claim", headers={**auth(), "Content-Type": "application/json"},
                  json={"run_id": RUN_ID, "mode": os.environ.get("RUN_MODE", "scheduled")}, timeout=30)
    if r.status_code == 409:
        reason = r.json().get("reason", "run_not_claimed")
        raise PipelineError("Production run was not claimed: " + str(reason))
    r.raise_for_status()
    if not r.json().get("ok"):
        raise PipelineError("Production run was not authorised by the daily quota controller.")


def get_audio():
    r = http.get(API + "/internal/assets", headers=auth(), timeout=30)
    r.raise_for_status()
    assets = r.json().get("assets", [])
    if assets:
        asset = assets[0]
        media = http.get(API + "/internal/assets/" + quote(asset["id"], safe=""),
                         headers=auth(), timeout=120)
        media.raise_for_status()
        if len(media.content) < 4096:
            raise PipelineError("Selected audio file is empty or invalid.")
        return {**asset, "audio_source": "uploaded_recording"}, media.content

    # No upload is required: create a fresh, original synthetic string-style
    # soundtrack on the GitHub cloud runner. This is not a real violin take.
    from synth_audio import create_original_soundtrack
    audio_path = WORK / "original-synthetic-string-soundtrack.wav"
    day_seed = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    create_original_soundtrack(audio_path, seed_text=day_seed + ":" + RUN_ID)
    return {
        "filename": audio_path.name,
        "audio_source": "generated_synthetic_string",
        "kind": "generated_audio"
    }, audio_path.read_bytes()


def research():
    items = []
    try:
        r = http.get("https://api.gdeltproject.org/api/v2/doc/doc",
                     params={"query": "(music OR violin OR entertainment OR culture OR film OR science OR technology)",
                             "mode": "ArtList", "format": "json", "maxrecords": "30",
                             "sort": "HybridRel", "timespan": "24h"}, timeout=25)
        r.raise_for_status()
        for a in r.json().get("articles", []):
            if a.get("title") and a.get("url"):
                items.append({"title": str(a["title"])[:220], "summary": "",
                              "url": str(a["url"]), "date": str(a.get("seendate", "")),
                              "source": str(a.get("domain", "GDELT"))})
    except Exception as exc:
        log("GDELT unavailable: " + str(exc)[:160])

    qs = [
        ("violin OR instrumental music OR orchestral music", "Music"),
        ("global entertainment OR cinema OR film music", "Entertainment"),
        ("science OR technology discoveries OR space", "Discovery"),
        ("world culture OR art OR popular culture", "Culture"),
        ("music artist OR music festival OR music charts", "Music trends"),
    ]
    for query, label in qs:
        try:
            req = requests.Request("GET", "https://news.google.com/rss/search",
                                   params={"q": query, "hl": "en", "gl": "US", "ceid": "US:en"}).prepare()
            r = http.get(req.url, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for it in root.findall(".//item")[:10]:
                title, link = (it.findtext("title") or "").strip(), (it.findtext("link") or "").strip()
                if title and link:
                    desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
                    items.append({"title": title[:220], "summary": re.sub(r"\s+", " ", desc)[:300],
                                  "url": link, "date": (it.findtext("pubDate") or "")[:90],
                                  "source": "Google News - " + label})
        except Exception as exc:
            log(label + " RSS unavailable: " + str(exc)[:140])

    unique = {}
    for item in items:
        unique.setdefault(item["url"].split("?")[0].rstrip("/"), item)
    result = list(unique.values())[:45]
    if not result:
        raise PipelineError("All free research feeds were unavailable; no video created.")
    WORK.mkdir(exist_ok=True)
    (WORK / "research.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def ai(model, payload, timeout=180):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/{model}"
    r = http.post(url, headers={"Authorization": "Bearer " + CF_TOKEN}, json=payload, timeout=timeout)
    if r.status_code in (402, 403, 429):
        raise PipelineError(f"Workers AI refused the request (HTTP {r.status_code}). Free quota may be exhausted or token permissions missing. No paid fallback.")
    if not r.ok:
        raise PipelineError(f"Workers AI HTTP {r.status_code}: {r.text[:400]}")
    body = r.json()
    if not body.get("success", True) or not isinstance(body.get("result"), dict):
        raise PipelineError("Workers AI returned an unsuccessful or unexpected response.")
    return body["result"]


def make_plan(items):
    system = (
        "You are the editorial director of Violin Prince, a violin creator. Choose one timely, "
        "well-supported, family-friendly subject from these headlines and transform it into an original "
        "short visual story accompanied by an original string-style instrumental soundtrack and spoken narration. Prioritise music, art, culture, discovery, science and positive "
        "global interests. Reject tragedies, graphic events, violence, disasters and crimes. Do not invent "
        "facts, dates, statistics or quotations. Use only factual claims supported by the supplied research; "
        "prefer a topic corroborated by multiple independent headlines. Do not use song lyrics, copied scripts, "
        "named copyrighted characters, logos or identifiable living people in images. Return JSON only with "
        "topic,title,hook,description,hashtags,narration_script,narrative_style,scenes,sources. The narration_script "
        "must be 35 to 45 spoken words, written for a natural narrator: a strong opening hook, clear explanation, "
        "one memorable detail and a satisfying ending. Use a cinematic storytelling style for human-interest "
        "topics and a clear documentary/fact-telling style for factual discoveries. Keep sentences short and "
        "pronunciation-friendly. Every concrete factual statement must be supported by the supplied headlines. "
        "Exactly 3 scenes. Each scene needs a caption of 9 words maximum and an original symbolic cinematic "
        "image_prompt in English. If no suitable topic, return skip and reason."
    )
    compact = [{k: x.get(k, "") for k in ("title", "summary", "url", "date", "source")} for x in items[:35]]
    result = ai(TEXT_MODEL, {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": "Create a 24-second story from these current research headlines:\n" +
         json.dumps(compact, ensure_ascii=False)}
    ], "max_tokens": 1000, "temperature": 0.55})
    raw = str(result.get("response", "")).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise PipelineError("Planner did not return JSON.")
    try:
        plan = json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise PipelineError("Planner JSON invalid: " + str(exc)) from exc
    if plan.get("skip"):
        raise PipelineError("Editorial agent skipped: " + str(plan.get("reason", ""))[:200])
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        raise PipelineError("Planner must provide exactly three scenes.")
    narration_script = str(plan.get("narration_script", "")).strip()
    spoken_words = re.findall(r"\b[\w’'-]+\b", narration_script)
    if not 35 <= len(spoken_words) <= 45:
        raise PipelineError("Planner narration must contain 35–45 spoken words.")
    plan["narration_script"] = narration_script
    plan["narrative_style"] = str(plan.get("narrative_style", "documentary")).lower()
    if plan["narrative_style"] not in ("documentary", "cinematic_story"):
        plan["narrative_style"] = "documentary"
    allowed = {x["url"] for x in items}
    plan["sources"] = [u for u in plan.get("sources", []) if u in allowed][:5]
    for scene in scenes:
        if not scene.get("caption") or not scene.get("image_prompt"):
            raise PipelineError("A scene is missing its caption or visual prompt.")
    (WORK / "creative_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def make_image(prompt, index):
    result = ai(IMAGE_MODEL, {"prompt": prompt[:1800], "steps": 4, "seed": int(time.time()) + index}, 240)
    if not result.get("image"):
        raise PipelineError("FLUX returned no image.")
    try:
        data = base64.b64decode(result["image"], validate=True)
    except Exception as exc:
        raise PipelineError("FLUX image data was invalid.") from exc
    IMAGES.mkdir(parents=True, exist_ok=True)
    path = IMAGES / f"scene-{index + 1}.jpg"
    path.write_bytes(data)
    return path


def font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def make_card(source, caption, index):
    image = Image.open(source).convert("RGB")
    bg = ImageOps.fit(image, (W, H), method=Image.Resampling.LANCZOS)
    bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(24))).enhance(0.44)
    canvas = bg.convert("RGBA")
    fg = ImageOps.contain(image, (W - 36, 780), method=Image.Resampling.LANCZOS)
    y = 185 + max(0, (780 - fg.height) // 2)
    canvas.alpha_composite(fg.convert("RGBA"), ((W - fg.width) // 2, y))
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 48), "VIOLIN PRINCE / ORIGINAL VISUAL STORY",
              font=font(17), fill=(239, 216, 170, 255))
    ty = 1030
    for line in textwrap.wrap(caption.strip(), width=22)[:3]:
        f = font(40)
        box = draw.textbbox((0, 0), line, font=f, stroke_width=1)
        x = (W - (box[2] - box[0])) // 2
        draw.text((x, ty), line, font=f, fill=(255, 250, 241, 255),
                  stroke_width=2, stroke_fill=(0, 0, 0, 210))
        ty += 54
    draw.text((28, 1220), f"SCENE {index + 1:02d} / ORIGINAL SOUNDTRACK",
              font=font(15), fill=(225, 225, 225, 240))
    p = OUT / f"card-{index + 1}.png"
    canvas.convert("RGB").save(p, "PNG", optimize=True)
    return p


def command(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise PipelineError("FFmpeg failed: " + p.stderr[-1200:])


def write_subtitles(script, narration_path, subtitle_path):
    """Make simple timed word-group subtitles from the exact narrated script."""
    import soundfile as sf

    info = sf.info(str(narration_path))
    duration = min(24.0, info.duration)
    words = str(script).split()
    if not words or duration <= 0:
        raise PipelineError("Cannot create subtitles without valid narration audio.")
    groups = [words[i:i + 6] for i in range(0, len(words), 6)]

    def stamp(seconds):
        ms = max(0, int(seconds * 1000))
        hours, rem = divmod(ms, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        seconds_part, millis = divmod(rem, 1000)
        return f"{hours:02}:{minutes:02}:{seconds_part:02},{millis:03}"

    lines = []
    word_cursor = 0
    total_words = len(words)
    for index, group in enumerate(groups, start=1):
        start = duration * word_cursor / total_words
        word_cursor += len(group)
        end = duration * word_cursor / total_words
        lines.extend([str(index), f"{stamp(start)} --> {stamp(end)}", " ".join(group), ""])
    subtitle_path.write_text("\n".join(lines), encoding="utf-8")


def render(plan, audio_bytes, narration_path):
    OUT.mkdir(parents=True, exist_ok=True)
    audio_path = WORK / "approved-audio"
    audio_path.write_bytes(audio_bytes)
    clips = []
    for i, scene in enumerate(plan["scenes"]):
        image = make_image(scene["image_prompt"], i)
        card = make_card(image, scene["caption"], i)
        clip = OUT / f"scene-{i + 1}.mp4"
        vf = ("zoompan=z='min(zoom+0.00055,1.10)':d=200:"
              f"s={W}x{H}:fps={FPS},fade=t=in:st=0:d=0.35,"
              f"fade=t=out:st={SECONDS - 0.35}:d=0.35,format=yuv420p")
        command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-loop", "1", "-framerate", str(FPS), "-i", str(card),
                 "-t", str(SECONDS), "-vf", vf, "-an", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p", str(clip)])
        clips.append(clip)

    concat = WORK / "concat.txt"
    concat.write_text("".join(f"file '{p.resolve()}'\n" for p in clips), encoding="utf-8")
    silent = OUT / "silent.mp4"
    command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(silent)])
    final = OUT / "violin-prince-short.mp4"
    subtitle_path = OUT / "narration.srt"
    write_subtitles(plan["narration_script"], narration_path, subtitle_path)
    audio_filter = (
        "[1:a]volume=0.20[bed];"
        "[2:a]highpass=f=75,acompressor=threshold=-20dB:ratio=3:attack=12:release=180[voice];"
        "[bed][voice]amix=inputs=2:duration=longest:dropout_transition=1,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,"
        "afade=t=in:st=0:d=0.5,afade=t=out:st=22:d=2[aout]"
    )
    video_filter = (
        "subtitles=work/output/narration.srt:"
        "force_style='FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H90000000,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=100',"
        "format=yuv420p"
    )
    command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(silent), "-stream_loop", "-1", "-i", str(audio_path),
             "-i", str(narration_path),
             "-map", "0:v:0", "-filter_complex", audio_filter, "-map", "[aout]",
             "-t", "24", "-vf", video_filter, "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(final)])
    if not final.exists() or final.stat().st_size < 100000:
        raise PipelineError("Final MP4 is missing or too small.")
    return final


def upload(path):
    with path.open("rb") as f:
        r = http.post(API + "/internal/render", headers={
            **auth(), "Content-Type": "video/mp4", "X-Filename": path.name
        }, data=f, timeout=300)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise PipelineError("Private cloud storage rejected the MP4.")
    return data


def main():
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    try:
        claim_run()
        asset, audio = get_audio()
        report("running",
               ("Using uploaded recording: " + asset["filename"] if asset.get("audio_source") == "uploaded_recording"
                else "Generated an original synthetic string-style soundtrack.") + " Started global research.")
        items = research()
        log("Research sources collected: " + str(len(items)))
        plan = make_plan(items)
        topic, title = str(plan.get("topic", "")), str(plan.get("title", "Violin Prince Short"))
        from voiceover import synthesize_voiceover
        narration_path, narration_info = synthesize_voiceover(
            plan["narration_script"], OUT / "narration.wav"
        )
        report("producing", "Generated spoken narration; creating 3 visual scenes and mixing the soundtrack.", topic, title)
        path = render(plan, audio, narration_path)
        stored = upload(path)
        from publisher import publish_all
        publish_result = publish_all(path, stored.get("media_url", ""), plan)
        has_publication = bool(publish_result.get("results"))
        final_status = "published" if has_publication and publish_result.get("all_succeeded") else (
            "partially_published" if has_publication else "rendered"
        )
        metadata = {
            "run_id": RUN_ID, "topic": topic, "title": title,
            "hook": plan.get("hook", ""), "description": plan.get("description", ""),
            "hashtags": plan.get("hashtags", []),
            "narration_script": plan.get("narration_script", ""),
            "narrative_style": plan.get("narrative_style", "documentary"),
            "narration": narration_info,
            "captions": [x["caption"] for x in plan["scenes"]],
            "sources": plan.get("sources", []), "audio_asset": asset["filename"],
            "audio_source": asset.get("audio_source", "uploaded_recording"),
            "duration_seconds": 24, "format": "9:16",
            "publishing_status": final_status, "publish_results": publish_result,
            "output_key": stored.get("object_key")
        }
        (OUT / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report(final_status,
               "Production complete. " + json.dumps(publish_result, ensure_ascii=False)[:650],
               topic, title, stored.get("object_key", ""), stored.get("media_url", ""), metadata)
        from analytics import collect_and_send
        analytics_result = collect_and_send(API, JOB_TOKEN)
        (OUT / "analytics.json").write_text(
            json.dumps(analytics_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 0
    except Exception as exc:
        log("Stopped safely: " + str(exc))
        report("failed", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
