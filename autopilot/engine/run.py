#!/usr/bin/env python3
"""Free-first cloud producer. Never switches to a paid service."""
import base64, json, os, re, subprocess, sys, textwrap, time, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

API = os.environ.get("AUTOPILOT_API_URL", "").rstrip("/")
JOB_TOKEN = os.environ.get("AUTOPILOT_JOB_TOKEN", "")
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


class ParagraphExtractor(HTMLParser):
    """Extract readable paragraph text from public article pages."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._in_paragraph = False
        self._blocked = 0
        self._current = []
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "nav", "footer", "header"):
            self._blocked += 1
        elif tag == "p" and self._blocked == 0:
            self._in_paragraph = True
            self._current = []

    def handle_endtag(self, tag):
        if tag == "p" and self._in_paragraph:
            text_value = re.sub(r"\s+", " ", " ".join(self._current)).strip()
            if len(text_value) > 50:
                self.paragraphs.append(text_value)
            self._current = []
            self._in_paragraph = False
        elif tag in ("script", "style", "noscript", "nav", "footer", "header"):
            self._blocked = max(0, self._blocked - 1)

    def handle_data(self, data):
        if self._in_paragraph and self._blocked == 0:
            self._current.append(data)


def log(message):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {message}", flush=True)


def auth():
    return {"Authorization": "Bearer " + JOB_TOKEN}


def report(status, message, topic="", title="", key="", url="", metadata=None):
    if not API:
        log("Status: " + str(status) + " — " + str(message)[:400])
        return
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
    if not API:
        log("Standalone GitHub Actions mode: no Worker claim is required.")
        return
    r = http.post(API + "/internal/claim", headers={**auth(), "Content-Type": "application/json"},
                  json={"run_id": RUN_ID, "mode": os.environ.get("RUN_MODE", "scheduled")}, timeout=30)
    if r.status_code == 409:
        reason = r.json().get("reason", "run_not_claimed")
        raise PipelineError("Production run was not claimed: " + str(reason))
    r.raise_for_status()
    if not r.json().get("ok"):
        raise PipelineError("Production run was not authorised by the daily quota controller.")


def get_audio():
    if API:
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

    # Standalone mode creates a fresh original soundtrack because no R2 asset
    # library is configured. This is not a real recording of the creator.
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


def enrich_source_evidence(items):
    """Fetch short public-page excerpts for better fact-checking context."""
    def fetch_one(item):
        url = str(item.get("url", ""))
        if not url.startswith(("http://", "https://")):
            return item
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ViolinPrinceAutopilot/0.1)"},
                timeout=(5, 9),
                allow_redirects=True,
            )
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status_code != 200 or "html" not in content_type:
                return item
            parser = ParagraphExtractor()
            parser.feed(response.text[:1_200_000])
            excerpt = " ".join(parser.paragraphs[:12])[:1500]
            final_url = response.url
            if final_url.startswith(("http://", "https://")):
                item["url"] = final_url
                item["publisher_domain"] = urlparse(final_url).netloc.lower().removeprefix("www.")
            if excerpt:
                item["evidence_text"] = excerpt
        except Exception as exc:
            log("Article evidence unavailable: " + str(exc)[:120])
        return item

    # Resolve Google News redirect links to their original publisher pages.
    candidates = items[:40]
    if not candidates:
        return items
    completed = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_one, dict(item)): item.get("url") for item in candidates}
        for future in as_completed(futures):
            try:
                result = future.result()
                completed[futures[future]] = result
            except Exception:
                pass
    enriched = [completed.get(item.get("url"), item) for item in candidates]
    enriched_urls = {item.get("url") for item in candidates}
    return enriched + [item for item in items if item.get("url") not in enriched_urls]


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
    for region in ("US", "GB", "IN"):
        for query, label in qs:
            try:
                req = requests.Request(
                    "GET",
                    "https://news.google.com/rss/search",
                    params={"q": query, "hl": "en", "gl": region, "ceid": region + ":en"}
                ).prepare()
                r = http.get(req.url, timeout=20)
                r.raise_for_status()
                root = ET.fromstring(r.content)
                for it in root.findall(".//item")[:8]:
                    title, link = (it.findtext("title") or "").strip(), (it.findtext("link") or "").strip()
                    if title and link:
                        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
                        items.append({"title": title[:220], "summary": re.sub(r"\s+", " ", desc)[:500],
                                      "url": link, "date": (it.findtext("pubDate") or "")[:90],
                                      "source": "Google News " + region + " - " + label})
            except Exception as exc:
                log(region + " " + label + " RSS unavailable: " + str(exc)[:140])

    unique = {}
    for item in items:
        unique.setdefault(item["url"].split("?")[0].rstrip("/"), item)
    result = list(unique.values())[:75]
    if not result:
        raise PipelineError("All free research feeds were unavailable; no video created.")
    result = enrich_source_evidence(result)
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


def recent_topics():
    """Read recent successful topics from D1 when the optional Worker is configured."""
    if not API:
        return []
    r = http.get(API + "/internal/recent-topics", headers=auth(), timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    topics = r.json().get("topics", [])
    return [str(item)[:180] for item in topics if str(item).strip()][:25]


def make_plan(items, recent=None):
    system = (
        "You are the editorial director of Violin Prince, a violin creator. Choose one timely, "
        "well-supported, family-friendly subject from these headlines and transform it into an original "
        "short visual story accompanied by an original string-style instrumental soundtrack and spoken narration. Prioritise music, art, culture, discovery, science and positive "
        "global interests. Reject tragedies, graphic events, violence, disasters and crimes. Do not invent "
        "facts, dates, statistics or quotations. Use only factual claims supported by the supplied research; "
        "prefer a topic supported by multiple independent publisher sources. Use supplied article excerpts as evidence. Do not use song lyrics, copied scripts, "
        "named copyrighted characters, logos or identifiable living people in images. Return JSON only with "
        "topic,title,hook,description,hashtags,narration_script,narrative_style,scenes,sources. The narration_script "
        "must be 30 to 42 spoken words, written for a natural narrator: a strong opening hook, clear explanation, "
        "one memorable detail and a satisfying ending. Use a cinematic storytelling style for human-interest "
        "topics and a clear documentary/fact-telling style for factual discoveries. Keep sentences short and "
        "pronunciation-friendly. Every concrete factual statement must be supported by the supplied headlines. "
        "Exactly 3 scenes. Each scene needs a caption of 9 words maximum and an original symbolic cinematic "
        "image_prompt in English. If no suitable topic, return skip and reason."
    )
    compact = [{k: x.get(k, "") for k in ("title", "summary", "evidence_text", "publisher_domain", "url", "date", "source")} for x in items[:35]]
    result = ai(TEXT_MODEL, {
        "messages": [
            {"role": "system", "content": system + " Do not show reasoning. Return exactly one JSON object and no preamble or Markdown."},
            {"role": "user", "content":
             "Create a 24-second story from these current research headlines. Avoid repeating prior topics. " +
             "Previously published topics to avoid: " + json.dumps(recent or [], ensure_ascii=False) +
             "\nResearch evidence: " + json.dumps(compact, ensure_ascii=False)}
        ],
        # Gemma 4 supports this parameter; disabling reasoning keeps the response
        # focused on the machine-readable plan expected by the renderer.
        "chat_template_kwargs": {"enable_thinking": False, "clear_thinking": True},
        "max_completion_tokens": 1800,
        "temperature": 0.35
    })

    candidate = result.get("response", "")
    if isinstance(candidate, dict):
        plan = candidate
        raw = json.dumps(candidate, ensure_ascii=False)
    else:
        if isinstance(candidate, list):
            raw = "\n".join(
                str(part.get("text", "")) for part in candidate
                if isinstance(part, dict) and part.get("type") == "text"
            ).strip()
        else:
            raw = str(candidate or "").strip()

        # Also accept the standard chat-completions shape in case the API
        # response is wrapped differently by a compatible endpoint.
        if not raw and isinstance(result.get("choices"), list) and result["choices"]:
            message = result["choices"][0].get("message", {})
            content = message.get("content", "") if isinstance(message, dict) else ""
            if isinstance(content, list):
                raw = "\n".join(
                    str(part.get("text", "")) for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ).strip()
            else:
                raw = str(content or "").strip()

        # Remove an occasional Markdown code fence, then parse the first object.
        cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.I)
        start = cleaned.find("{")
        if start < 0:
            preview = re.sub(r"\s+", " ", raw[:240])
            raise PipelineError("Planner did not return JSON. Response preview: " + (preview or "[empty response]"))
        try:
            plan, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError as exc:
            preview = re.sub(r"\s+", " ", raw[:240])
            raise PipelineError("Planner JSON was invalid: " + str(exc) + ". Response preview: " + preview) from exc
    if plan.get("skip"):
        raise PipelineError("Editorial agent skipped: " + str(plan.get("reason", ""))[:200])
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        raise PipelineError("Planner must provide exactly three scenes.")
    narration_script = str(plan.get("narration_script", "")).strip()
    spoken_words = re.findall(r"\b[\w’'-]+\b", narration_script)
    if not 30 <= len(spoken_words) <= 48:
        raise PipelineError("Planner narration must contain 30–48 spoken words.")
    plan["narration_script"] = narration_script
    plan["narrative_style"] = str(plan.get("narrative_style", "documentary")).lower()
    if plan["narrative_style"] not in ("documentary", "cinematic_story"):
        plan["narrative_style"] = "documentary"
    allowed = {x["url"] for x in items}
    plan["sources"] = [u for u in plan.get("sources", []) if u in allowed][:5]
    source_domains = {
        urlparse(u).netloc.lower().removeprefix("www.")
        for u in plan["sources"]
        if urlparse(u).netloc
    }
    if plan["narrative_style"] == "documentary" and len(source_domains) < 2:
        raise PipelineError("Documentary narration needs at least two independent publisher sources.")
    if plan["narrative_style"] == "cinematic_story" and not plan["sources"]:
        raise PipelineError("Storytelling topic has no traceable research source.")
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


def make_card(source, caption, index, title=""):
    """Create a full-bleed vertical cinematic frame with restrained branding."""
    image = Image.open(source).convert("RGB")
    # Use a portrait crop with a centred safe area instead of a small square inset.
    image = ImageOps.fit(image, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.46))
    image = ImageEnhance.Color(image).enhance(0.92)
    image = ImageEnhance.Contrast(image).enhance(1.04)
    canvas = image.convert("RGBA")

    # Soft top and bottom gradients keep type legible without heavy boxes.
    gradient = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(gradient)
    for y in range(H):
        if y < 330:
            alpha = int(150 * (1.0 - y / 330.0))
        elif y > 850:
            alpha = int(190 * ((y - 850) / (H - 850)))
        else:
            alpha = 0
        if alpha:
            gd.line((0, y, W, y), fill=(5, 8, 14, alpha))
    canvas = Image.alpha_composite(canvas, gradient)
    draw = ImageDraw.Draw(canvas)

    gold = (235, 202, 139, 255)
    white = (255, 250, 241, 255)
    draw.text((34, 36), "VIOLIN PRINCE", font=font(20), fill=gold,
              stroke_width=1, stroke_fill=(0, 0, 0, 120))
    draw.line((34, 72, W - 34, 72), fill=(235, 202, 139, 150), width=1)

    if index == 0 and title:
        title_lines = textwrap.wrap(str(title).strip(), width=27)[:2]
        title_y = 105
        title_font = font(31)
        for line in title_lines:
            draw.text((34, title_y), line, font=title_font, fill=white,
                      stroke_width=2, stroke_fill=(0, 0, 0, 170))
            title_y += 43

    caption_lines = textwrap.wrap(str(caption).strip(), width=24)[:3]
    caption_font = font(43)
    caption_y = 955 - max(0, len(caption_lines) - 1) * 25
    for line in caption_lines:
        box = draw.textbbox((0, 0), line, font=caption_font, stroke_width=1)
        x = max(30, (W - (box[2] - box[0])) // 2)
        draw.text((x, caption_y), line, font=caption_font, fill=white,
                  stroke_width=2, stroke_fill=(0, 0, 0, 210))
        caption_y += 56

    draw.line((34, 1190, W - 34, 1190), fill=(235, 202, 139, 135), width=1)
    draw.text((34, 1207), "ORIGINAL STORY • ORIGINAL SOUNDTRACK",
              font=font(13), fill=(242, 230, 208, 240))
    draw.text((W - 110, 1207), f"{index + 1:02d}/03",
              font=font(13), fill=(242, 230, 208, 240))

    p = OUT / f"card-{index + 1}.png"
    canvas.convert("RGB").save(p, "PNG", optimize=True)
    return p

def command(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise PipelineError("FFmpeg failed: " + p.stderr[-1200:])


def validate_final_video(path):
    """Fail closed unless the final file contains valid vertical video and audio."""
    if not path.exists() or path.stat().st_size < 150000:
        raise PipelineError("Final MP4 is missing or unexpectedly small.")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,sample_rate,channels",
         "-of", "json", str(path)],
        capture_output=True, text=True
    )
    if probe.returncode:
        raise PipelineError("ffprobe could not inspect the final MP4: " + probe.stderr[-800:])
    try:
        data = json.loads(probe.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        streams = data.get("streams", [])
    except (TypeError, ValueError) as exc:
        raise PipelineError("ffprobe returned invalid MP4 metadata.") from exc

    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise PipelineError("Final MP4 must contain both video and mixed narration/music audio.")
    if int(video.get("width", 0)) != W or int(video.get("height", 0)) != H:
        raise PipelineError("Final MP4 is not the required 720x1280 vertical format.")
    if not 23.5 <= duration <= 24.5:
        raise PipelineError(f"Final MP4 duration is outside the 24-second target: {duration:.2f}s.")
    if int(audio.get("sample_rate", 0)) < 22050:
        raise PipelineError("Final audio sample rate is unexpectedly low.")

    return {
        "duration_seconds": round(duration, 2),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "audio_sample_rate": int(audio["sample_rate"]),
        "file_size_bytes": path.stat().st_size,
    }

def render(plan, audio_bytes, narration_path, narration_info):
    OUT.mkdir(parents=True, exist_ok=True)
    audio_path = WORK / "approved-audio"
    audio_path.write_bytes(audio_bytes)
    clips = []
    for i, scene in enumerate(plan["scenes"]):
        visual_prompt = (
            str(scene["image_prompt"]) +
            ", portrait 9:16 composition, centred focal subject, vertical framing, "
            "cinematic natural lighting, no text, no logos, no watermark"
        )
        image = make_image(visual_prompt, i)
        card = make_card(image, scene["caption"], i, plan.get("title", ""))
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
    from voiceover import write_srt
    write_srt(narration_info.get("subtitle_cues", []), subtitle_path)
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
    quality = validate_final_video(final)
    (OUT / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return final, quality


def upload(path):
    if not API:
        # GitHub Actions uploads this MP4 as a workflow artifact after this script exits.
        return {"ok": True, "object_key": "", "media_url": ""}
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
        prior_topics = recent_topics()
        plan = make_plan(items, prior_topics)
        topic, title = str(plan.get("topic", "")), str(plan.get("title", "Violin Prince Short"))
        from voiceover import synthesize_voiceover
        narration_path, narration_info = synthesize_voiceover(
            plan["narration_script"], OUT / "narration.wav"
        )
        report("producing", "Generated spoken narration; creating 3 visual scenes and mixing the soundtrack.", topic, title)
        path, video_quality = render(plan, audio, narration_path, narration_info)
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
            "video_quality": video_quality,
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
        if API:
            analytics_result = collect_and_send(API, JOB_TOKEN)
        else:
            analytics_result = {"connected": False, "reason": "dashboard_api_not_configured"}
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
