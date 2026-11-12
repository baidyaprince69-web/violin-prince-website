#!/usr/bin/env python3
"""Free-first cloud producer. Never switches to a paid service."""
import argparse, base64, json, os, re, shutil, subprocess, sys, textwrap, time, uuid
from io import BytesIO
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
CF_ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "")
CF_TOKEN = os.environ.get("CF_AI_TOKEN", "")
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
                final_host = urlparse(final_url).netloc.lower().removeprefix("www.")
                # Google News can return its own HTML page with HTTP 200 instead
                # of redirecting to the publisher. Preserve the RSS <source> domain.
                is_google_host = (final_host == "google.com" or final_host.endswith(".google.com"))
                if final_host and not is_google_host:
                    item["url"] = final_url
                    item["publisher_domain"] = final_host
                    item["publisher_url"] = final_url
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


def google_news_item_record(item, region, label):
    """Keep the publisher identity exposed by Google News RSS <source> metadata."""
    source_node = item.find("source")
    publisher_name = (source_node.text or "").strip() if source_node is not None else ""
    publisher_home = (source_node.get("url") or "").strip() if source_node is not None else ""
    publisher_domain = urlparse(publisher_home).netloc.lower().removeprefix("www.")
    raw_title = (item.findtext("title") or "").strip()
    if publisher_name and raw_title.casefold().endswith((" - " + publisher_name).casefold()):
        raw_title = raw_title[:-(len(publisher_name) + 3)].strip()
    description = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
    description = " ".join(description.split())
    return {
        "title": raw_title[:220],
        # Google News descriptions are often headline clusters, not article text.
        "summary": description[:500],
        "url": (item.findtext("link") or "").strip(),
        "date": (item.findtext("pubDate") or "")[:90],
        "source": publisher_name or ("Google News " + region + " - " + label),
        "publisher_name": publisher_name,
        "publisher_home": publisher_home,
        "publisher_domain": publisher_domain,
        "source_feed": "Google News " + region + " - " + label,
    }


def planner_research_items(items):
    """Prepare titled, traceable publisher leads for the editorial model."""
    fields = (
        "title", "summary", "evidence_text", "publisher_name",
        "publisher_home", "publisher_domain", "url", "date", "source"
    )
    selected = []
    for item in items[:40]:
        if not item.get("title") or not item.get("url"):
            continue
        domain = str(item.get("publisher_domain") or "").lower().removeprefix("www.")
        if not domain or domain == "news.google.com":
            continue
        selected.append({key: item.get(key, "") for key in fields})
    # A few feeds may expose headlines and links without publisher metadata.
    # Keep those only as a last-resort topic lead; the prompt restricts factual claims.
    if not selected:
        selected = [
            {key: item.get(key, "") for key in fields}
            for item in items[:40] if item.get("title") and item.get("url")
        ]
    return selected


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
                article_url = str(a["url"])
                article_domain = str(a.get("domain") or urlparse(article_url).netloc).lower().removeprefix("www.")
                items.append({
                    "title": str(a["title"])[:220], "summary": "",
                    "url": article_url, "date": str(a.get("seendate", "")),
                    "source": article_domain or "GDELT",
                    "publisher_name": article_domain,
                    "publisher_domain": article_domain,
                })
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
                        items.append(google_news_item_record(it, region, label))
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
        "For documentary topics, cite at least two exact article URLs from different publisher_domain values in the evidence. "
        "Use supplied article excerpts as evidence. Use publisher_domain and publisher_name as publisher identity, not news.google.com. "
        "A Google News headline is only a topic lead, not an article excerpt: when no evidence_text is supplied, "
        "limit factual narration to what the headline explicitly establishes and do not invent additional details. "
        "Avoid Google News URLs when original publisher URLs are available. Do not use song lyrics, copied scripts, "
        "named copyrighted characters, logos or identifiable living people in images. Return JSON only with "
        "topic,title,hook,description,hashtags,narration_script,narrative_style,scenes,sources. The narration_script "
        "must be 32 to 40 spoken words across exactly four short sentences. The first spoken sentence must be a 5-to-8-word curiosity hook that the video actually resolves. "
        "Then build context, reveal one memorable detail, and finish with a satisfying payoff. No greeting, generic introduction, or misleading clickbait. Use a cinematic storytelling style for human-interest "
        "topics and a clear documentary/fact-telling style for factual discoveries. Keep sentences short and "
        "pronunciation-friendly. Keep every sentence to 12 words maximum for readable subtitles. Every concrete factual statement must be supported by the supplied research. "
        "Exactly 3 scenes. Each scene needs a caption of 9 words maximum and an original symbolic cinematic "
        "image_prompt in English. The three scenes must form hook, development, and reveal/payoff, with a consistent main subject. If no suitable topic, return skip and reason."
    )
    compact = planner_research_items(items)
    if not compact:
        raise PipelineError("Research feeds returned no planner-ready headlines with traceable links.")
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
    if not 32 <= len(spoken_words) <= 40:
        raise PipelineError("Planner narration must contain 32–40 spoken words for the 24-second format.")
    spoken_sentences = [part.strip() for part in re.split("[.!?]+", narration_script) if part.strip()]
    if len(spoken_sentences) != 4:
        raise PipelineError("Planner narration must contain exactly four short story beats.")
    hook_words = spoken_sentences[0].split()
    if not 5 <= len(hook_words) <= 8:
        raise PipelineError("Opening hook must contain 5–8 words.")
    if any(len(sentence.split()) > 12 for sentence in spoken_sentences):
        raise PipelineError("Each narration sentence must contain no more than 12 words.")
    plan["narration_script"] = narration_script
    plan["narrative_style"] = str(plan.get("narrative_style", "documentary")).lower()
    if plan["narrative_style"] not in ("documentary", "cinematic_story"):
        plan["narrative_style"] = "documentary"
    def source_key(value):
        parsed = urlparse(str(value or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        return parsed.netloc.lower().removeprefix("www.") + parsed.path.rstrip("/")

    source_lookup = {source_key(item.get("url", "")): item for item in items if source_key(item.get("url", ""))}
    selected_sources = []
    for value in plan.get("sources", []):
        matched = source_lookup.get(source_key(value))
        if not matched and isinstance(value, str):
            matched = next((item for item in items if item.get("title", "").strip().casefold() == value.strip().casefold()), None)
        if matched and matched.get("url") not in [item.get("url") for item in selected_sources]:
            selected_sources.append(matched)
    plan["sources"] = [item["url"] for item in selected_sources[:5]]
    source_domains = {
        str(item.get("publisher_domain") or urlparse(item.get("url", "")).netloc).lower().removeprefix("www.")
        for item in selected_sources if item.get("url")
    }
    if plan["narrative_style"] == "documentary" and len(source_domains) == 1:
        # A single verifiable publisher is sufficient for a clearly labelled,
        # source-led human-interest story; do not present it as multi-source documentary.
        plan["narrative_style"] = "cinematic_story"
        log("Using a single-source cinematic story because two independent publishers were not verified.")
    elif plan["narrative_style"] == "documentary" and len(source_domains) < 1:
        raise PipelineError("No verifiable publisher source remained after URL verification.")
    if plan["narrative_style"] == "cinematic_story" and not plan["sources"]:
        raise PipelineError("Storytelling topic has no traceable research source.")
    for scene in scenes:
        if not scene.get("caption") and scene.get("visual_caption"):
            scene["caption"] = scene["visual_caption"]
        if not scene.get("caption") or not scene.get("image_prompt"):
            raise PipelineError("A scene is missing its caption or visual prompt.")
    (WORK / "creative_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def image_request_payload(prompt):
    """Build only the fields accepted by Cloudflare's FLUX.1-schnell REST schema."""
    value = str(prompt or "").strip()
    if not value:
        raise PipelineError("Image prompt is empty.")
    return {"prompt": value[:1800], "steps": 4}


def make_image(prompt, index):
    # FLUX.1-schnell's REST schema accepts prompt and steps only.
    # Do not send seed: Cloudflare's current endpoint rejects it as an extra property.
    result = ai(IMAGE_MODEL, image_request_payload(prompt), 240)
    if not result.get("image"):
        raise PipelineError("FLUX returned no image.")
    try:
        data = base64.b64decode(result["image"], validate=True)
        with Image.open(BytesIO(data)) as decoded:
            decoded.verify()
    except Exception as exc:
        raise PipelineError("FLUX returned invalid or undecodable image data.") from exc
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

def render(plan, audio_bytes, narration_path, narration_info, image_paths=None):
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
        if image_paths is not None:
            image = Path(image_paths[i])
            if not image.is_file():
                raise PipelineError(f"Prepared scene image {i + 1} is missing.")
        else:
            image = make_image(visual_prompt, i)
        card = make_card(image, scene["caption"], i, plan.get("title", ""))
        clip = OUT / f"scene-{i + 1}.mp4"
        if i == 0:
            camera = f"zoompan=z='min(zoom+0.00055,1.09)':x='(iw-iw/zoom)*0.50':y='(ih-ih/zoom)*0.43':d=200:s={W}x{H}:fps={FPS}"
        elif i == 1:
            camera = f"zoompan=z='min(zoom+0.00045,1.07)':x='(iw-iw/zoom)*(on/199)':y='(ih-ih/zoom)*0.52':d=200:s={W}x{H}:fps={FPS}"
        else:
            camera = f"zoompan=z='if(eq(on,0),1.08,max(1.0,zoom-0.00040))':x='(iw-iw/zoom)*0.48':y='(ih-ih/zoom)*0.50':d=200:s={W}x{H}:fps={FPS}"
        vf = (camera + ",fade=t=in:st=0:d=0.35,"
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



PACKAGE = WORK / "package"


def _package_paths():
    PACKAGE.mkdir(parents=True, exist_ok=True)
    return {
        "plan": PACKAGE / "creative_plan.json",
        "metadata": PACKAGE / "stage.json",
        "audio": PACKAGE / "soundtrack.wav",
        "narration": PACKAGE / "narration.wav",
        "research": PACKAGE / "research.json",
    }


def _read_package(require_images=False):
    paths = _package_paths()
    for key in ("plan", "metadata", "audio", "narration"):
        if not paths[key].is_file():
            raise PipelineError(f"Prepared package is missing {paths[key].name}. Download the correct earlier stage artifact.")
    try:
        plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError("Prepared package contains invalid JSON metadata.") from exc
    narration_info = metadata.get("narration_info")
    if not isinstance(plan.get("scenes"), list) or len(plan["scenes"]) != 3:
        raise PipelineError("Prepared package must contain exactly three planned scenes.")
    if not isinstance(narration_info, dict) or not narration_info.get("subtitle_cues"):
        raise PipelineError("Prepared package is missing narration subtitle timings.")
    image_paths = [PACKAGE / f"scene-{index + 1}.jpg" for index in range(3)]
    if require_images:
        for path in image_paths:
            if not path.is_file():
                raise PipelineError(f"Prepared visual package is missing {path.name}. Run the Visuals stage first.")
            try:
                with Image.open(path) as image:
                    image.verify()
            except Exception as exc:
                raise PipelineError(f"Prepared visual asset {path.name} is not a valid image.") from exc
    return plan, metadata, narration_info, paths, image_paths


def _scene_visual_prompt(scene, feedback=""):
    prompt = str(scene.get("image_prompt", "")).strip()
    if not prompt:
        raise PipelineError("A planned scene has no image prompt.")
    prompt += (
        ", premium cinematic storybook illustration, refined hand-painted digital artwork, "
        "rich but controlled colour palette, atmospheric cinematic lighting, layered foreground, "
        "midground and background for clear parallax depth, strong readable silhouette, "
        "crisp focal details, elegant composition, cohesive visual art direction across all scenes, "
        "portrait 9:16 composition, centred focal subject, no text, no logos, no watermark"
    )
    clean_feedback = re.sub(r"\s+", " ", str(feedback or "")).strip()[:600]
    if clean_feedback:
        prompt += ", additional visual direction: " + clean_feedback
    return prompt


def make_storyboard_preview(plan, image_paths, target):
    """Build a single review sheet so visual approval happens before video rendering."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (1280, 900), (12, 16, 24))
    draw = ImageDraw.Draw(canvas)
    draw.text((44, 30), "VIOLIN PRINCE  /  STORYBOARD REVIEW",
              font=font(25), fill=(236, 204, 146))
    title = textwrap.shorten(str(plan.get("title", "Untitled story")), width=58, placeholder="…")
    draw.text((44, 76), title, font=font(36), fill=(255, 250, 242))
    tile_width, tile_height = 360, 640
    lefts = (44, 460, 876)
    for index, (scene, image_path, left) in enumerate(zip(plan["scenes"], image_paths, lefts)):
        with Image.open(image_path) as source:
            tile = ImageOps.fit(
                source.convert("RGB"), (tile_width, tile_height),
                method=Image.Resampling.LANCZOS, centering=(0.5, 0.45)
            )
        canvas.paste(tile, (left, 150))
        draw.rectangle((left, 150, left + tile_width - 1, 150 + tile_height - 1),
                       outline=(210, 185, 142), width=2)
        caption = textwrap.shorten(str(scene.get("caption", "")), width=38, placeholder="…")
        draw.text((left, 810), f"SCENE {index + 1}  ·  {caption}",
                  font=font(18), fill=(245, 238, 226))
    draw.text((44, 862), "Approve the visual direction before creating the final MP4.",
              font=font(16), fill=(185, 194, 207))
    canvas.save(target, "PNG", optimize=True)
    return target


def _write_review_text(plan, target):
    lines = [
        "VIOLIN PRINCE — PRE-PRODUCTION REVIEW",
        "",
        "TITLE: " + str(plan.get("title", "")),
        "TOPIC: " + str(plan.get("topic", "")),
        "HOOK: " + str(plan.get("hook", "")),
        "",
        "NARRATION:",
        str(plan.get("narration_script", "")),
        "",
        "SCENE PLAN:",
    ]
    for index, scene in enumerate(plan.get("scenes", []), start=1):
        lines.extend([
            f"{index}. {scene.get('caption', '')}",
            "   Visual direction: " + str(scene.get("image_prompt", "")),
        ])
    lines.extend(["", "SOURCES:", *[str(value) for value in plan.get("sources", [])]])
    Path(target).write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_stage():
    """Create research, story, narration and soundtrack once; no images or MP4 yet."""
    claim_run()
    asset, audio = get_audio()
    report("running", "Preparing research, story, narration and original soundtrack.")
    items = research()
    log("Research sources collected: " + str(len(items)))
    plan = make_plan(items, recent_topics())
    topic, title = str(plan.get("topic", "")), str(plan.get("title", "Violin Prince Short"))
    from voiceover import synthesize_voiceover
    narration_path, narration_info = synthesize_voiceover(
        plan["narration_script"], OUT / "narration.wav"
    )
    paths = _package_paths()
    paths["audio"].write_bytes(audio)
    shutil.copy2(narration_path, paths["narration"])
    paths["plan"].write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["research"].write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["metadata"].write_text(json.dumps({
        "schema_version": 1,
        "prepared_run_id": RUN_ID,
        "asset": asset,
        "narration_info": narration_info,
        "topic": topic,
        "title": title,
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "stage": "prepared",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_review_text(plan, PACKAGE / "review.txt")
    log("Prepared package saved. Review review.txt before generating scene images.")
    report("prepared", "Story, narration and soundtrack are ready for review.", topic, title,
           metadata={"stage": "prepared"})
    return 0


def visuals_stage(feedback=""):
    """Generate only the three scene images from a previously prepared package."""
    if not CF_ACCOUNT or not CF_TOKEN:
        raise PipelineError("CF_ACCOUNT_ID and CF_AI_TOKEN are required for the Visuals stage.")
    plan, metadata, _narration_info, paths, image_paths = _read_package(require_images=False)
    for index, scene in enumerate(plan["scenes"]):
        prompt = _scene_visual_prompt(scene, feedback)
        generated = make_image(prompt, index)
        shutil.copy2(generated, image_paths[index])
        log(f"Prepared scene image {index + 1}/3.")
    storyboard = make_storyboard_preview(plan, image_paths, PACKAGE / "storyboard-preview.png")
    metadata["stage"] = "visuals_ready"
    metadata["visual_feedback"] = re.sub(r"\s+", " ", str(feedback or "")).strip()[:600]
    metadata["visuals_run_id"] = RUN_ID
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    log("Storyboard preview created: " + str(storyboard))
    return 0


def render_stage():
    """Assemble an approved visual package without calling any AI service."""
    plan, metadata, narration_info, paths, image_paths = _read_package(require_images=True)
    topic = str(plan.get("topic", ""))
    title = str(plan.get("title", "Violin Prince Short"))
    audio = paths["audio"].read_bytes()
    if len(audio) < 4096:
        raise PipelineError("Prepared soundtrack is missing or unexpectedly small.")
    log("Rendering from saved research, script, narration, soundtrack and scene images. No AI calls.")
    path, video_quality = render(plan, audio, paths["narration"], narration_info, image_paths=image_paths)
    stored = upload(path)
    from publisher import publish_all
    publish_result = publish_all(path, stored.get("media_url", ""), plan)
    has_publication = bool(publish_result.get("results"))
    final_status = "published" if has_publication and publish_result.get("all_succeeded") else (
        "partially_published" if has_publication else "rendered"
    )
    output_metadata = {
        "run_id": RUN_ID, "topic": topic, "title": title,
        "hook": plan.get("hook", ""), "description": plan.get("description", ""),
        "hashtags": plan.get("hashtags", []),
        "narration_script": plan.get("narration_script", ""),
        "narrative_style": plan.get("narrative_style", "documentary"),
        "narration": narration_info, "video_quality": video_quality,
        "captions": [scene["caption"] for scene in plan["scenes"]],
        "sources": plan.get("sources", []),
        "audio_asset": metadata.get("asset", {}).get("filename", paths["audio"].name),
        "audio_source": metadata.get("asset", {}).get("audio_source", "generated_synthetic_string"),
        "duration_seconds": 24, "format": "9:16",
        "publishing_status": final_status, "publish_results": publish_result,
        "output_key": stored.get("object_key"), "prepared_run_id": metadata.get("prepared_run_id"),
        "visuals_run_id": metadata.get("visuals_run_id"),
    }
    (OUT / "metadata.json").write_text(
        json.dumps(output_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report(final_status, "Production complete. " + json.dumps(publish_result, ensure_ascii=False)[:650],
           topic, title, stored.get("object_key", ""), stored.get("media_url", ""), output_metadata)
    if API:
        from analytics import collect_and_send
        analytics_result = collect_and_send(API, JOB_TOKEN)
    else:
        analytics_result = {"connected": False, "reason": "dashboard_api_not_configured"}
    (OUT / "analytics.json").write_text(
        json.dumps(analytics_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


def main(stage="full", visual_feedback=""):
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    try:
        if stage == "prepare":
            return prepare_stage()
        if stage == "visuals":
            return visuals_stage(visual_feedback)
        if stage == "render":
            return render_stage()
        if stage != "full":
            raise PipelineError("Unknown pipeline stage: " + str(stage))
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
    parser = argparse.ArgumentParser(description="Violin Prince staged short-video pipeline")
    parser.add_argument(
        "--stage", choices=("full", "prepare", "visuals", "render"), default="full",
        help="prepare story/audio, generate visuals from a saved package, or render without AI calls"
    )
    args = parser.parse_args()
    try:
        exit_code = main(stage=args.stage, visual_feedback=os.environ.get("VISUAL_FEEDBACK", ""))
    except Exception as exc:
        log("Stopped safely: " + str(exc))
        report("failed", str(exc))
        exit_code = 1
    sys.exit(exit_code)
