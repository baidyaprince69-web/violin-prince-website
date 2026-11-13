#!/usr/bin/env python3
"""Free-first cloud producer. Never switches to a paid service."""
import argparse, base64, hashlib, json, os, re, shutil, subprocess, sys, textwrap, time, uuid, wave
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

API = os.environ.get("AUTOPILOT_API_URL", "").rstrip("/")
JOB_TOKEN = os.environ.get("AUTOPILOT_JOB_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "")
CF_TOKEN = os.environ.get("CF_AI_TOKEN", "")
RUN_ID = os.environ.get("RUN_ID", str(uuid.uuid4()))
TEXT_MODEL = "@cf/google/gemma-4-26b-a4b-it"
IMAGE_MODEL = "@cf/black-forest-labs/flux-1-schnell"
VISION_MODEL = os.environ.get("CF_VISION_MODEL", "@cf/moondream/moondream3.1-9B-A2B")
MAX_IMAGE_PROMPT_CHARS = 1800
MAX_IMAGE_QA_ATTEMPTS = 2
MAX_STORYBOARD_REPAIR_ATTEMPTS = 1
MIN_IMAGE_QA_SCORE = 80
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


def _validate_creator_violin_recording(path):
    """Accept a real PCM WAV take; never mistake an instrument bank for audio."""
    path = Path(path)
    if path.stat().st_size > 25 * 1024 * 1024:
        raise PipelineError("The violin recording is larger than 25 MB. Export a 24–30 second PCM WAV.")
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            sample_width = source.getsampwidth()
            duration = source.getnframes() / max(1, sample_rate)
    except (wave.Error, EOFError, OSError) as exc:
        raise PipelineError(
            "The custom violin asset must be an uncompressed PCM WAV recording. "
            "An SF2/SFZ instrument library is not an audio recording."
        ) from exc
    if channels not in (1, 2):
        raise PipelineError("The violin recording must be mono or stereo.")
    if sample_rate < 22050 or sample_width not in (2, 3, 4):
        raise PipelineError("Export the violin recording as 16-, 24- or 32-bit PCM at 22.05 kHz or higher.")
    if duration < 24.0:
        raise PipelineError(
            f"The violin recording is {duration:.1f} seconds. It must be at least 24 seconds "
            "to avoid abrupt automatic looping."
        )
    return {"duration_seconds": round(duration, 2), "channels": channels, "sample_rate": sample_rate}


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

    configured_path = os.environ.get("VIOLIN_RECORDING_PATH", "").strip()
    recording_path = (
        Path(configured_path) if configured_path
        else Path(__file__).resolve().parent / "assets" / "violin-performance.wav"
    )
    if recording_path.is_file():
        recording_info = _validate_creator_violin_recording(recording_path)
        log("Using the creator's real violin recording as the music bed.")
        return {
            "filename": recording_path.name,
            "audio_source": "creator_recorded_violin",
            "kind": "uploaded_recording",
            **recording_info,
        }, recording_path.read_bytes()
    if configured_path:
        log("VIOLIN_RECORDING_PATH was not found; trying the CC0 sampled violin instrument.")

    # Use a small, checksum-verified CC0 multisample pack to render a new violin
    # phrase. Network or sample-render failures fall back quietly instead of
    # failing Prepare or introducing a paid service.
    day_seed = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        from violin_sampler import create_sampled_violin_bed
        audio_path = WORK / "sampled-violin-background.wav"
        audio_path, sample_info = create_sampled_violin_bed(
            audio_path, seed_text=day_seed + ":" + RUN_ID
        )
        log(
            "Rendered a 24-second solo-violin bed from the CC0 sample pack "
            f"({sample_info.get('zones_used', 0)} sample zones)."
        )
        return {
            **sample_info,
            "filename": audio_path.name,
            "kind": "generated_sampled_instrument",
        }, audio_path.read_bytes()
    except Exception as exc:
        log("CC0 sampled violin unavailable; using the quiet ambient fallback: " + str(exc)[:220])

    from synth_audio import create_ambient_fallback
    audio_path = WORK / "ambient-background-fallback.wav"
    create_ambient_fallback(audio_path, seed_text=day_seed + ":" + RUN_ID)
    return {
        "filename": audio_path.name,
        "audio_source": "generated_ambient_fallback",
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
    """Prepare publisher leads with stable IDs the model can cite without rewriting URLs."""
    fields = (
        "title", "summary", "evidence_text", "publisher_name",
        "publisher_home", "publisher_domain", "url", "date", "source"
    )
    selected = []
    for index, item in enumerate(items[:40], start=1):
        if not item.get("title") or not item.get("url"):
            continue
        domain = str(item.get("publisher_domain") or "").lower().removeprefix("www.")
        if not domain or domain == "news.google.com":
            continue
        record = {key: item.get(key, "") for key in fields}
        record["source_id"] = f"S{index:04d}"
        selected.append(record)
    # A few feeds may expose headlines and links without publisher metadata.
    # Keep those only as a last-resort topic lead; the prompt restricts factual claims.
    if not selected:
        for index, item in enumerate(items[:40], start=1):
            if not item.get("title") or not item.get("url"):
                continue
            record = {key: item.get(key, "") for key in fields}
            record["source_id"] = f"S{index:04d}"
            selected.append(record)
    return selected


SOURCE_MATCH_STOPWORDS = {
    "about", "after", "again", "also", "and", "are", "around", "been", "before",
    "being", "but", "can", "could", "from", "have", "into", "its", "just", "more",
    "most", "new", "now", "one", "our", "out", "over", "she", "some", "than",
    "that", "the", "their", "them", "there", "these", "they", "this", "through",
    "today", "very", "was", "were", "what", "when", "where", "which", "with",
    "would", "you", "your", "music", "song", "songs", "story", "global", "world",
}


def source_key(value):
    """Normalize URLs so tracking queries, fragments, and www do not break matching."""
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = unquote(parsed.path or "").rstrip("/")
    return host + path


def source_tokens(value):
    words = re.findall(r"[a-z0-9]{3,}", str(value or "").casefold())
    return {word for word in words if word not in SOURCE_MATCH_STOPWORDS}


def source_relevance_score(plan, item):
    """Estimate whether a publisher headline supports the selected story topic."""
    core = source_tokens(" ".join(str(plan.get(key, "")) for key in ("topic", "title", "hook")))
    if not core:
        core = source_tokens(plan.get("narration_script", ""))
    article = source_tokens(" ".join(str(item.get(key, "")) for key in (
        "title", "summary", "evidence_text", "publisher_name"
    )))
    if not core or not article:
        return 0.0
    return len(core.intersection(article)) / len(core)


def resolve_plan_sources(plan, research_items):
    """Resolve source IDs, URLs, titles, or publisher names to collected research records."""
    candidates = [
        item for item in research_items
        if item.get("title") and item.get("url")
        and str(item.get("publisher_domain") or urlparse(item.get("url", "")).netloc)
            .lower().removeprefix("www.") not in ("", "news.google.com")
    ]
    by_id = {str(item.get("source_id", "")).strip().upper(): item for item in candidates}
    by_url = {source_key(item.get("url", "")): item for item in candidates if source_key(item.get("url", ""))}

    references = plan.get("sources", [])
    if isinstance(references, (str, dict)):
        references = [references]
    if not isinstance(references, list):
        references = []

    selected = []
    for reference in references[:8]:
        if isinstance(reference, dict):
            value = str(
                reference.get("source_id") or reference.get("id") or
                reference.get("url") or reference.get("title") or ""
            ).strip()
        else:
            value = str(reference or "").strip()
        if not value:
            continue

        matched = by_id.get(value.upper())
        if not matched:
            matched = by_url.get(source_key(value))

        if not matched:
            normalized = " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
            for item in candidates:
                title = " ".join(re.findall(r"[a-z0-9]+", str(item.get("title", "")).casefold()))
                publisher = " ".join(re.findall(r"[a-z0-9]+", str(item.get("publisher_name", "")).casefold()))
                domain = str(item.get("publisher_domain", "")).lower().removeprefix("www.")
                if normalized and normalized in (title, publisher, domain):
                    matched = item
                    break

        if matched and matched.get("url") not in [item.get("url") for item in selected]:
            selected.append(matched)

    if selected:
        return selected[:5]

    # Some model responses rewrite a Google News redirect as a publisher URL,
    # or omit citations despite selecting a source-led topic. Recover the closest
    # matching supplied headline, never a URL invented by the model.
    ranked = sorted(
        ((source_relevance_score(plan, item), item) for item in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if ranked and ranked[0][0] >= 0.16:
        score, item = ranked[0]
        log(
            "Planner source references did not resolve; selected the closest supplied "
            f"headline by topic overlap ({score:.0%}): {item.get('publisher_name') or item.get('publisher_domain')}."
        )
        return [item]
    return []


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
    """Call Workers AI with one bounded retry for transient transport/5xx failures only."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/{model}"
    headers = {"Authorization": "Bearer " + CF_TOKEN}
    transient_statuses = {500, 502, 503, 504}
    response = None
    for attempt in range(2):
        try:
            response = http.post(url, headers=headers, json=payload, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == 0:
                log("Temporary Workers AI network issue; retrying once.")
                time.sleep(1)
                continue
            raise PipelineError("Workers AI request failed after one retry: " + str(exc)[:240]) from exc
        if response.status_code in (402, 403, 429):
            raise PipelineError(
                f"Workers AI refused the request (HTTP {response.status_code}). "
                "Free quota may be exhausted or token permissions missing. No paid fallback."
            )
        if response.status_code in transient_statuses and attempt == 0:
            log(f"Temporary Workers AI server error (HTTP {response.status_code}); retrying once.")
            time.sleep(1)
            continue
        if not response.ok:
            raise PipelineError(f"Workers AI HTTP {response.status_code}: {response.text[:400]}")
        break
    if response is None:
        raise PipelineError("Workers AI request did not return a response.")
    try:
        body = response.json()
    except ValueError as exc:
        raise PipelineError("Workers AI returned invalid JSON.") from exc
    if not isinstance(body, dict) or not body.get("success", True) or not isinstance(body.get("result"), dict):
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


def parse_planner_result(result):
    """Parse the Workers AI response into one complete creative-plan object."""
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

        cleaned = raw.strip()
        fence = chr(96) * 3
        if cleaned.startswith(fence):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.rstrip().endswith(fence):
                cleaned = cleaned.rstrip()[:-3].strip()
        start = cleaned.find("{")
        if start < 0:
            preview = re.sub(r"\s+", " ", raw[:240])
            raise PipelineError("Planner did not return JSON. Response preview: " + (preview or "[empty response]"))
        try:
            plan, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError as exc:
            preview = re.sub(r"\s+", " ", raw[:240])
            raise PipelineError("Planner JSON was invalid: " + str(exc) + ". Response preview: " + preview) from exc

    if not isinstance(plan, dict):
        raise PipelineError("Planner response JSON must be an object.")
    return plan


def narration_validation_error(script):
    """Return a precise narration constraint failure, or an empty string."""
    text_value = str(script or "").strip()
    words = re.findall(r"\b[\w’'-]+\b", text_value)
    if not 40 <= len(words) <= 44:
        return f"it has {len(words)} spoken words; the required range is 40–44"
    sentences = [part.strip() for part in re.split(r"[.!?]+", text_value) if part.strip()]
    if len(sentences) != 4:
        return f"it has {len(sentences)} sentences; exactly 4 are required"
    hook_words = sentences[0].split()
    if not 5 <= len(hook_words) <= 8:
        return f"the opening hook has {len(hook_words)} words; 5–8 are required"
    if any(len(sentence.split()) > 12 for sentence in sentences):
        return "one or more sentences exceed the 12-word subtitle limit"
    return ""


NARRATION_SENTENCE_WORD_TARGETS = (8, 9, 12, 12)


def narration_sentences(script):
    """Split a short spoken script into sentence strings while retaining punctuation."""
    value = str(script or "").strip()
    if not value:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", value) if part.strip()]


def narration_word_count(value):
    """Use the same token rule for each sentence and the complete narration."""
    return len(re.findall(r"\b[\w’'-]+\b", str(value or "")))


def narration_sentence_error(sentence, target_words):
    """Validate one generated beat independently of the other narration sentences."""
    value = re.sub(r"\s+", " ", str(sentence or "")).strip()
    if not value:
        return "the sentence is empty"
    if len(narration_sentences(value)) != 1:
        return "the response must contain exactly one sentence"
    count = narration_word_count(value)
    if count != target_words:
        return f"it has {count} words; exactly {target_words} are required"
    if len(value.split()) > 12:
        return "the sentence exceeds the 12-word subtitle limit"
    if not value.endswith((".", "!", "?")):
        return "the sentence is not grammatically closed with punctuation"
    return ""


def narration_sentence_budget_error(script):
    """Require four story beats with a deliberate 8/9/12/12 spoken-word rhythm."""
    sentences = narration_sentences(script)
    if len(sentences) != 4:
        return f"it has {len(sentences)} sentences; exactly 4 are required"
    counts = [narration_word_count(sentence) for sentence in sentences]
    if tuple(counts) != NARRATION_SENTENCE_WORD_TARGETS:
        return (
            "sentence word counts are " + "/".join(str(value) for value in counts) +
            "; the required rhythm is 8/9/12/12"
        )
    return ""


def make_plan(items, recent=None):
    system = (
        "You are the editorial director of Violin Prince, a violin creator. Choose one timely, "
        "well-supported, family-friendly subject from these headlines and turn it into an original "
        "short visual story with spoken narration and an original string-style instrumental soundtrack. "
        "Choose for a music-loving audience: prioritise violin and instruments, classical and contemporary music, "
        "film music, artists, performances, festivals and music culture. Art, culture, science or discovery may be "
        "chosen when the story has a clear, compelling connection to music or a strong visual idea. Reject unrelated "
        "retail promotions and generic technology announcements, as well as tragedies, graphic events, violence, "
        "disasters and crimes. Pick the strongest specific story, not merely the loudest headline. "
        "Do not invent facts, dates, statistics, motives, quotations or outcomes. Use only factual claims supported "
        "by supplied research. For documentary topics, cite at least two source_id values from different publisher_domain "
        "values when available. Every research item has a source_id. The sources field MUST contain one to three exact "
        "source_id values copied from the supplied research; never invent IDs or rewrite URLs. A single-source "
        "cinematic story may cite one ID. Use article excerpts as evidence. A Google News headline is only a topic lead, "
        "not an article excerpt: without evidence_text, limit factual narration to what the headline explicitly states. "
        "The pipeline resolves source IDs to original article URLs. Do not output publisher homepages as article URLs. "
        "Do not use song lyrics, copied scripts, named copyrighted characters, logos or identifiable living people in images. "
        "Return JSON only with topic,title,hook,description,hashtags,narration_script,narrative_style,scenes,sources. "
        "The narration_script must have 40 to 44 spoken words across exactly four natural, complete sentences. Aim for 41 words. "
        "Aim for 41 words with this exact sentence budget: sentence 1 has 8 words, sentence 2 has 9 words, "
        "sentence 3 has 12 words, and sentence 4 has 12 words. Sentence 1 is the curiosity hook and must be resolved. "
        "Keep every sentence at 12 words or fewer and make the wording sound natural when spoken aloud, never padded. "
        "Build context, reveal one memorable sourced detail, "
        "and finish with a satisfying payoff. No greeting, filler padding, generic introduction or misleading clickbait. "
        "Use a cinematic storytelling style for human-interest topics and a clear documentary style for factual discoveries. "
        "Exactly 3 scenes. Each scene needs a concise caption of 9 words maximum, an original specific image_prompt "
        "in English, a graphic_label of 1–3 words, and a graphic_detail of 4–10 words. The graphic_detail must clarify "
        "the scene using only facts already supported by the supplied research or narration. Never invent a number, "
        "date, measurement, comparison, quote, statistic, or causal claim for a graphic. If exact data is unavailable, "
        "write a concise explanatory phrase rather than a statistic. Scene 1 must visualise the hook, scene 2 must show "
        "the exact object/action/detail that makes this story distinctive, and scene 3 must visually resolve the story. "
        "Use three clearly different compositions, not three unrelated stock images. Avoid generic musician portraits "
        "unless the story specifically concerns a person. "
        "Do not illustrate a metaphor as a factual event: for example, if only one instrument component travelled to orbit, "
        "show that component in space rather than an entire violin floating there. Keep the main subject and visual motif "
        "consistent across the three scenes. If no suitable story exists, return skip and reason."
    )
    compact = planner_research_items(items)
    if not compact:
        raise PipelineError("Research feeds returned no planner-ready headlines with traceable links.")
    result = ai(TEXT_MODEL, {
        "messages": [
            {"role": "system", "content": system + " Do not show reasoning. Return exactly one JSON object and no preamble or Markdown."},
            {"role": "user", "content":
             "Create a 24-second story for Violin Prince's music-loving audience from these current research headlines. "
             "Choose relevance and a strong visual story over generic trendiness. Avoid repeating prior topics. " +
             "Previously published topics to avoid: " + json.dumps(recent or [], ensure_ascii=False) +
             "\nResearch evidence: " + json.dumps(compact, ensure_ascii=False)}
        ],
        # Gemma 4 supports this parameter; disabling reasoning keeps the response
        # focused on the machine-readable plan expected by the renderer.
        "chat_template_kwargs": {"enable_thinking": False, "clear_thinking": True},
        "max_completion_tokens": 1800,
        "temperature": 0.35
    })

    plan = parse_planner_result(result)
    if plan.get("skip"):
        raise PipelineError("Editorial agent skipped: " + str(plan.get("reason", ""))[:200])

    # Repair only the sentence beats that miss their exact word budgets. This keeps
    # the selected story, its sources, and all visual prompts untouched.
    narration_script = str(plan.get("narration_script", "")).strip()
    narration_issue = narration_validation_error(narration_script)
    budget_issue = narration_sentence_budget_error(narration_script)
    if narration_issue or budget_issue:
        log(
            "Planner narration needs sentence-level correction: " +
            (narration_issue or budget_issue) +
            ". Keeping the selected story, scenes and research unchanged."
        )

        repair_sources = resolve_plan_sources(plan, compact)
        repair_evidence = [
            {
                "title": str(item.get("title", ""))[:180],
                "publisher": str(item.get("publisher_name") or item.get("publisher_domain") or "")[:100],
                "evidence": str(item.get("evidence_text") or item.get("summary") or "")[:800],
            }
            for item in repair_sources[:3]
        ]
        if not repair_evidence:
            repair_evidence = [
                {
                    "title": str(item.get("title", ""))[:180],
                    "publisher": str(item.get("publisher_name") or item.get("publisher_domain") or "")[:100],
                    "evidence": str(item.get("evidence_text") or item.get("summary") or "")[:800],
                }
                for item in compact[:3]
            ]

        original_script = narration_script
        original_sentences = narration_sentences(original_script)
        # If the first draft has the wrong number of sentences, regenerate all
        # four beats individually from the same plan instead of guessing how to split it.
        sentences = original_sentences if len(original_sentences) == 4 else ["", "", "", ""]
        sentence_roles = (
            "opening curiosity hook",
            "brief story context",
            "distinctive sourced detail or central development",
            "meaningful payoff that resolves the opening hook",
        )
        repair_attempts = []
        debug_path = WORK / "creative_plan_debug.json"

        def save_narration_debug(status, current_script=""):
            WORK.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(
                json.dumps(
                    {
                        "stage": "narration_repair",
                        "status": status,
                        "initial_script": original_script,
                        "initial_plan": plan,
                        "repair_attempts": repair_attempts,
                        "current_script": current_script,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        save_narration_debug("in_progress", original_script)

        for index, target_words in enumerate(NARRATION_SENTENCE_WORD_TARGETS):
            current_sentence = sentences[index]
            current_error = narration_sentence_error(current_sentence, target_words)
            if not current_error:
                continue

            completed = False
            for attempt in (1, 2, 3):
                previous_sentence = sentences[index - 1] if index > 0 else ""
                next_sentence = sentences[index + 1] if index < 3 else ""
                previous_count = narration_word_count(current_sentence)
                if attempt == 3 and previous_count == target_words - 1:
                    correction_instruction = (
                        f"The last two revisions still had {previous_count} words, exactly one too few. "
                        f"Preserve the current sentence's existing words verbatim and in the same order. "
                        f"Insert exactly ONE additional useful, fact-safe word to make {target_words}; "
                        "do not replace, delete, shorten, or reorder any existing word. "
                        "Choose a word supported by the supplied plan, source evidence, or existing narration. "
                        "Count every space-separated part of a person's name as its own word. "
                        "Do not use filler, dates, or unsupported claims."
                    )
                elif attempt == 3 and previous_count == target_words + 1:
                    correction_instruction = (
                        f"The last revisions still have {previous_count} words, exactly one too many. "
                        "Preserve every other word and remove exactly one non-essential word. "
                        "Do not rewrite or shorten the sentence in any other way."
                    )
                elif attempt == 2 and previous_count == target_words - 1:
                    correction_instruction = (
                        f"The previous version had {previous_count} words, exactly one too few. "
                        f"Keep its meaning and sentence structure, then add exactly ONE useful, "
                        f"fact-safe word to make {target_words}. Do not paraphrase it into a shorter "
                        "sentence. The added word must improve specificity or natural phrasing, not act as filler."
                    )
                elif attempt == 2 and previous_count == target_words + 1:
                    correction_instruction = (
                        f"The previous version had {previous_count} words, exactly one too many. "
                        "Remove only one non-essential word while preserving meaning and natural phrasing."
                    )
                elif attempt > 1:
                    correction_instruction = (
                        f"The previous version failed because {current_error}. Make a visibly different, "
                        "carefully counted revision and verify its word count before returning it."
                    )
                else:
                    correction_instruction = (
                        f"Count the words before returning. The sentence must have exactly {target_words} words."
                    )
                payload = {
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a precise spoken-documentary script editor. Return exactly one JSON "
                                "object with one field named sentence, and no Markdown or commentary. "
                                "The sentence field must contain exactly " + str(target_words) +
                                " spoken words, counted as ordinary space-separated words. Count each word by position before answering; count each space-separated part of a multi-part name separately. Use simple words; "
                                "avoid contractions and hyphenated compounds. Write exactly one complete, "
                                "natural sentence, with no more than 12 words. Its role is: " +
                                sentence_roles[index] + ". Preserve the story's meaning and emotional purpose. "
                                "Use only claims supported by the supplied plan or research evidence. "
                                "Do not add invented facts, dates, statistics, quotations, motives or outcomes. "
                                "Do not pad, repeat ideas, add generic reflections, or use filler. "
                                "Every word must contribute useful context, clarity, imagery or narrative payoff."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Rewrite only narration sentence " + str(index + 1) + " of 4. "
                                "It must contain exactly " + str(target_words) + " spoken words. "
                                "Current sentence: " + (current_sentence or "[no usable sentence in this position]") +
                                "\nCurrent complete narration draft: " + original_script +
                                "\nTopic: " + str(plan.get("topic", ""))[:300] +
                                "\nTitle: " + str(plan.get("title", ""))[:220] +
                                "\nOpening hook: " + str(plan.get("hook", ""))[:220] +
                                "\nPrevious beat for continuity: " + previous_sentence +
                                "\nNext beat for continuity: " + next_sentence +
                                "\nVerified research evidence: " +
                                json.dumps(repair_evidence, ensure_ascii=False) +
                                "\nCorrection instruction: " + correction_instruction +
                                ("\nPrevious validation result: " + current_error if attempt > 1 else "") +
                                "\nReturn JSON only: {\"sentence\":\"one complete sentence\"}."
                            ),
                        },
                    ],
                    "chat_template_kwargs": {"enable_thinking": False, "clear_thinking": True},
                    "max_completion_tokens": 260,
                    "temperature": 0.0,
                }

                repaired = parse_planner_result(ai(TEXT_MODEL, payload))
                candidate = re.sub(r"\s+", " ", str(repaired.get("sentence", "") or "")).strip()
                # Missing terminal punctuation is a formatting defect, not a reason
                # to regenerate an otherwise correctly counted spoken sentence.
                punctuation_added = bool(candidate and not candidate.endswith((".", "!", "?")))
                if punctuation_added:
                    candidate = candidate.rstrip(" ,;:") + "."
                issue = narration_sentence_error(candidate, target_words)
                repair_attempts.append(
                    {
                        "sentence_number": index + 1,
                        "target_words": target_words,
                        "attempt": attempt,
                        "requested_words": target_words,
                        "returned_words": narration_word_count(candidate),
                        "punctuation_added": punctuation_added,
                        "validation_error": issue,
                        "sentence": candidate,
                    }
                )
                save_narration_debug("in_progress", " ".join(sentences))

                if not issue:
                    sentences[index] = candidate
                    completed = True
                    log(
                        f"Narration beat {index + 1}/4 repaired and verified "
                        f"({target_words} words; attempt {attempt}/2)."
                    )
                    save_narration_debug("in_progress", " ".join(sentences))
                    break

                current_sentence = candidate
                current_error = issue
                log(
                    f"Narration beat {index + 1}/4 did not meet its {target_words}-word target "
                    f"on attempt {attempt}: {issue}."
                )

            if not completed:
                save_narration_debug("failed", " ".join(sentences))
                raise PipelineError(
                    f"Narration sentence {index + 1} could not be repaired to exactly "
                    f"{target_words} natural, evidence-supported words after three focused attempts. "
                    "The original story and visuals were preserved; no filler was inserted."
                )

        narration_script = " ".join(sentences)
        final_issue = narration_validation_error(narration_script)
        final_budget_issue = narration_sentence_budget_error(narration_script)
        if final_issue or final_budget_issue:
            save_narration_debug("failed", narration_script)
            raise PipelineError(
                "Sentence-level narration repair did not pass the complete script checks: " +
                (final_issue or final_budget_issue) +
                ". No filler or unsupported facts were inserted."
            )

        plan["narration_script"] = narration_script
        save_narration_debug("repaired", narration_script)
        log("All four narration beats passed their exact 8/9/12/12-word budgets and full script validation.")


    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        raise PipelineError("Planner must provide exactly three scenes.")
    narration_script = str(plan.get("narration_script", "")).strip()
    spoken_words = re.findall(r"\b[\w’'-]+\b", narration_script)
    if not 40 <= len(spoken_words) <= 44:
        raise PipelineError("Planner narration must contain 40–44 spoken words for the 24-second format.")
    spoken_sentences = narration_sentences(narration_script)
    budget_issue = narration_sentence_budget_error(narration_script)
    if len(spoken_sentences) != 4:
        raise PipelineError("Planner narration must contain exactly four short story beats.")
    if budget_issue:
        raise PipelineError("Planner narration must follow the exact 8/9/12/12-word sentence budget: " + budget_issue)
    hook_words = spoken_sentences[0].split()
    if not 5 <= len(hook_words) <= 8:
        raise PipelineError("Opening hook must contain 5–8 words.")
    if any(len(sentence.split()) > 12 for sentence in spoken_sentences):
        raise PipelineError("Each narration sentence must contain no more than 12 words.")
    plan["narration_script"] = narration_script
    plan["narrative_style"] = str(plan.get("narrative_style", "documentary")).lower()
    if plan["narrative_style"] not in ("documentary", "cinematic_story"):
        plan["narrative_style"] = "documentary"

    planner_source_references = plan.get("sources") or []
    # Preserve the planner's original references and any narration-repair history.
    # A later successful validation must not overwrite the diagnostic trail.
    debug_path = WORK / "creative_plan_debug.json"
    existing_debug = {}
    if debug_path.is_file():
        try:
            existing_debug = json.loads(debug_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_debug = {}
    if existing_debug.get("stage") == "narration_repair":
        existing_debug["final_plan_before_source_resolution"] = plan
        existing_debug["current_script"] = str(plan.get("narration_script", ""))
        existing_debug["status"] = "repaired"
        debug_path.write_text(
            json.dumps(existing_debug, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        debug_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    compact = planner_research_items(items)
    selected_sources = resolve_plan_sources(plan, compact)
    plan["sources"] = [item["url"] for item in selected_sources[:5]]
    source_domains = {
        str(item.get("publisher_domain") or urlparse(item.get("url", "")).netloc)
            .lower().removeprefix("www.")
        for item in selected_sources if item.get("url")
    }
    if plan["narrative_style"] == "documentary" and len(source_domains) == 1:
        # A single verifiable publisher is sufficient for a clearly labelled,
        # source-led human-interest story; do not present it as multi-source documentary.
        plan["narrative_style"] = "cinematic_story"
        log("Using a single-source cinematic story because two independent publishers were not verified.")
    elif plan["narrative_style"] == "documentary" and len(source_domains) < 1:
        refs = planner_source_references
        if isinstance(refs, str):
            refs = [refs]
        ref_preview = ", ".join(str(value)[:90] for value in refs[:3]) or "(none returned)"
        headline_preview = "; ".join(str(item.get("title", ""))[:70] for item in compact[:4])
        raise PipelineError(
            "No supplied publisher source could be matched to the selected story. "
            f"Planner references: {ref_preview}. Available headline examples: {headline_preview}."
        )
    if plan["narrative_style"] == "cinematic_story" and not plan["sources"]:
        refs = plan.get("sources") or []
        raise PipelineError(
            "Storytelling topic has no traceable research source after ID, URL, title, "
            f"publisher, and topic matching. Planner references: {str(refs)[:240]}."
        )
    graphic_labels = ("THE HOOK", "THE KEY DETAIL", "THE PAYOFF")
    narration_beats = narration_sentences(narration_script)
    for index, scene in enumerate(scenes):
        if not scene.get("caption") and scene.get("visual_caption"):
            scene["caption"] = scene["visual_caption"]
        if not scene.get("caption") or not scene.get("image_prompt"):
            raise PipelineError("A scene is missing its caption or visual prompt.")
        scene["graphic_label"] = re.sub(
            r"\s+", " ", str(scene.get("graphic_label") or graphic_labels[index])
        ).strip()[:32]
        detail = re.sub(r"\s+", " ", str(scene.get("graphic_detail") or "")).strip()
        if not detail:
            beat_index = min(index, max(0, len(narration_beats) - 1))
            detail = narration_beats[beat_index] if narration_beats else str(scene["caption"])
        scene["graphic_detail"] = textwrap.shorten(detail, width=88, placeholder="…")
    (WORK / "creative_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def image_request_payload(prompt):
    """Build the FLUX.1-schnell request without silently clipping important instructions."""
    value = str(prompt or "").strip()
    if not value:
        raise PipelineError("Image prompt is empty.")
    if len(value) > MAX_IMAGE_PROMPT_CHARS:
        raise PipelineError(
            f"Image prompt is {len(value)} characters; the safe model limit is "
            f"{MAX_IMAGE_PROMPT_CHARS}. Shorten the prompt instead of truncating it."
        )
    return {"prompt": value, "steps": 4}


def portrait_scene_frame(source, focus=(0.5, 0.45)):
    """Place a square AI image into a 9:16 frame without cutting off the subject."""
    source = ImageOps.exif_transpose(source).convert("RGB")
    target = (W, H)
    if source.size == target:
        return source

    # A softened, darkened full-frame extension fills the vertical canvas.
    background = ImageOps.fit(
        source, target, method=Image.Resampling.LANCZOS, centering=focus
    )
    background = background.filter(ImageFilter.GaussianBlur(radius=34))
    background = ImageEnhance.Brightness(background).enhance(0.43)
    background = ImageEnhance.Color(background).enhance(0.66)
    canvas = background.convert("RGBA")

    # Keep the complete source image sharp in the middle instead of cropping
    # away the violin, hands or bow to manufacture a portrait ratio.
    foreground = ImageOps.contain(
        source, (W, int(H * 0.72)), method=Image.Resampling.LANCZOS
    )
    x = (W - foreground.width) // 2
    y = max(0, int((H - foreground.height) * focus[1]))
    foreground_layer = foreground.convert("RGBA")
    mask = Image.new("L", foreground.size, 255)
    mask_draw = ImageDraw.Draw(mask)
    fade = min(42, max(1, foreground.height // 12))
    for row in range(foreground.height):
        alpha = min(255, int(255 * (row + 1) / fade), int(255 * (foreground.height - row) / fade))
        mask_draw.line((0, row, foreground.width, row), fill=max(0, alpha))
    foreground_layer.putalpha(mask)
    canvas.alpha_composite(foreground_layer, (x, y))
    return canvas.convert("RGB")


def make_image(prompt, index):
    # FLUX.1-schnell accepts prompt and steps only; its output is square.
    # Normalize locally to portrait without asking the API for unsupported dimensions.
    result = ai(IMAGE_MODEL, image_request_payload(prompt), 240)
    if not result.get("image"):
        raise PipelineError("FLUX returned no image.")
    try:
        data = base64.b64decode(result["image"], validate=True)
        with Image.open(BytesIO(data)) as decoded:
            decoded.load()
            source = ImageOps.exif_transpose(decoded).convert("RGB")
            frame = portrait_scene_frame(source)
    except Exception as exc:
        raise PipelineError("FLUX returned invalid or undecodable image data.") from exc
    IMAGES.mkdir(parents=True, exist_ok=True)
    path = IMAGES / f"scene-{index + 1}.jpg"
    frame.save(path, "JPEG", quality=94, optimize=True)
    if not is_valid_portrait_scene_image(path):
        path.unlink(missing_ok=True)
        raise PipelineError("Normalized AI image did not meet the required 9:16 portrait dimensions.")
    return path

def _vision_query(image_data, question, timeout=120):
    """Use a short deterministic, non-streaming Moondream answer without reasoning traces."""
    return ai(
        VISION_MODEL,
        {
            "task": "query",
            "image": image_data,
            "question": question,
            "reasoning": False,
            "stream": False,
            "temperature": 0,
            "max_tokens": 192,
        },
        timeout,
    )


def _vision_text(value):
    """Extract the model's final answer from Workers AI wrapper and Moondream response shapes."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_vision_text(item) for item in value]
        return "".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        preferred = (
            "answer", "response", "text", "content", "output_text", "caption",
            "chunk", "value", "result", "data", "output", "message", "choices", "delta",
        )
        for key in preferred:
            if key in value:
                text_value = _vision_text(value[key])
                if text_value:
                    return text_value
        ignored = {"usage", "metrics", "reasoning", "reasoning_details", "request_id",
                   "finish_reason", "model", "token_ids", "timings"}
        for key, child in value.items():
            if str(key).casefold() in ignored:
                continue
            text_value = _vision_text(child)
            if text_value:
                return text_value
    return ""


def _vision_result_diagnostic(result):
    """Describe nested response field names/types when a provider wrapper has no answer text."""
    def describe(value, path="result", depth=0):
        if depth > 3:
            return []
        if isinstance(value, dict):
            rows = []
            for key, child in list(value.items())[:16]:
                child_path = f"{path}.{key}"
                rows.append(f"{child_path}={type(child).__name__}")
                if isinstance(child, (dict, list)):
                    rows.extend(describe(child, child_path, depth + 1))
                elif isinstance(child, str) and str(key).casefold() in {
                    "answer", "response", "text", "content", "output_text", "caption"
                } and child.strip():
                    rows.append(f"{child_path}_preview={child.strip()[:160]!r}")
            return rows
        if isinstance(value, list):
            rows = []
            for index, child in enumerate(value[:4]):
                rows.extend(describe(child, f"{path}[{index}]", depth + 1))
            return rows
        return [f"{path}={type(value).__name__}"]

    details = describe(result)
    return "Workers AI response shape: " + "; ".join(details[:30]) if details else "Workers AI returned an empty response."


def _parse_vision_assessment(result, label="visual reviewer", required_checks=None):
    """Require a scored JSON review or every explicitly named visual check."""
    raw = _vision_text(result)
    assessment = None
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            candidate, _ = decoder.raw_decode(raw[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            assessment = candidate
            break

    if assessment is not None:
        try:
            score_value = assessment["score"]
            model_passed = assessment["passed"]
            issues = assessment["issues"]
            if isinstance(score_value, bool) or not isinstance(score_value, (int, float)):
                raise ValueError("score must be numeric")
            if not isinstance(model_passed, bool) or not isinstance(issues, list):
                raise ValueError("passed must be boolean and issues must be a list")
            if not 0 <= score_value <= 100:
                raise ValueError("score must be between 0 and 100")
            score = int(round(score_value))
            issues = [str(value).strip()[:240] for value in issues if str(value).strip()]
            summary = str(assessment.get("summary", ""))[:500]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            assessment = None
        else:
            checks_result = {}
            if required_checks:
                checks_object = assessment.get("checks")
                if not isinstance(checks_object, dict):
                    issues.append("required per-feature checks object is missing")
                else:
                    for check in required_checks:
                        value = checks_object.get(check)
                        if value is True or (isinstance(value, str) and value.strip().upper() == "YES"):
                            checks_result[check] = "YES"
                        elif value is False or (isinstance(value, str) and value.strip().upper() == "NO"):
                            checks_result[check] = "NO"
                            issues.append(f"{check}: reviewer marked NO")
                        else:
                            issues.append(f"{check}: missing or invalid check verdict")
            passed = bool(model_passed and score >= MIN_IMAGE_QA_SCORE and not issues)
            return {
                "model": VISION_MODEL,
                "score": score,
                "passed": passed,
                "issues": issues[:8],
                "summary": summary,
                "assessment_mode": "structured_json",
                "checks": checks_result,
            }

    compact = re.sub(r"\s+", " ", raw).strip()
    if required_checks:
        results = {}
        duplicate_checks = set()
        for check in required_checks:
            matches = re.findall(
                rf"(?<![A-Za-z0-9_]){re.escape(check)}\s*[:=]\s*(YES|NO)\b",
                compact,
                flags=re.IGNORECASE,
            )
            if len(matches) == 1:
                results[check] = matches[0].upper()
            elif len(matches) > 1:
                duplicate_checks.add(check)

        issues = []
        for check in required_checks:
            if check in duplicate_checks:
                issues.append(f"{check}: duplicate or conflicting verdict")
            elif check not in results:
                issues.append(f"{check}: missing verdict")
            elif results[check] != "YES":
                issues.append(f"{check}: reviewer marked NO")

        passed = not issues and len(results) == len(required_checks)
        diagnostic = compact[:500] if compact else _vision_result_diagnostic(result)
        return {
            "model": VISION_MODEL,
            "score": MIN_IMAGE_QA_SCORE if passed else 0,
            "passed": passed,
            "issues": issues[:8] if issues else [],
            "summary": diagnostic,
            "assessment_mode": "per_requirement_checklist",
            "checks": results,
        }

    diagnostic = compact[:420] if compact else _vision_result_diagnostic(result)
    return {
        "model": VISION_MODEL,
        "score": 0,
        "passed": False,
        "issues": [f"{label} response lacked structured JSON or a required checklist"],
        "summary": diagnostic,
        "assessment_mode": "unresolved_text_response",
    }


def review_scene_image(path, plan, scene, index):
    """Inspect generated pixels with a vision model; reject ambiguous or defective artwork."""
    try:
        image_bytes = Path(path).read_bytes()
    except OSError as exc:
        raise PipelineError(f"Visual QA could not read scene {index + 1}: {exc}") from exc
    image_data = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")

    story_identity = " ".join((
        str(plan.get("topic", "")), str(plan.get("title", "")),
        str(plan.get("visual_motif", "")),
    )).casefold()
    scene_identity = " ".join((
        str(scene.get("image_prompt", "")), str(scene.get("caption", "")),
    )).casefold()
    is_violin_macro = (
        index == 1
        and bool(re.search(r"\bviolin(?:ist)?\b", story_identity))
        and bool(re.search(r"\bbow\b", scene_identity))
    )

    if is_violin_macro:
        required_checks = [
            "bridge", "four_strings", "fingerboard", "bow_stick",
            "horsehair", "hair_contact", "all_in_focus",
        ]
        checklist = (
            "Inspect the actual pixels as a technical violin macro photograph. bridge=YES only if one "
            "complete upright maple bridge is visible with both feet. four_strings=YES only if exactly "
            "four separate, parallel, individually countable strings are visible. fingerboard=YES only "
            "if the ebony fingerboard is clearly distinct behind the bridge. bow_stick=YES only if one "
            "slim, straight, dark wooden bow stick is clearly visible. horsehair=YES only if one narrow "
            "pale horsehair ribbon is separately visible, parallel to the stick, with a visible gap "
            "between the two parts except at frog and tip. hair_contact=YES only if the hair ribbon—not "
            "the stick—visibly touches exactly one string at one point between bridge and fingerboard. "
            "all_in_focus=YES only if bridge, four strings, fingerboard, both bow parts and contact point "
            "are all fully inside the frame and simultaneously sharp. Any hidden, merged, cropped, "
            "duplicated, malformed or unclear component means NO."
        )
    else:
        required_checks = ["subject", "action", "instrument", "composition", "photorealism"]
        checklist = (
            "Inspect the actual pixels. subject=YES only if the intended main subject is recognizable. "
            "action=YES only if the depicted action matches the scene brief. instrument=YES only if the "
            "correct instrument is visible with plausible anatomy and handling. composition=YES only if "
            "the subject and essential objects are fully readable, not awkwardly cropped, fused or "
            "duplicated. photorealism=YES only if materials and anatomy look like plausible cinematic "
            "photography rather than a diagram or illustration."
        )

    question = (
        "You are a strict visual quality inspector. Inspect the actual pixels in the image itself, not the written prompt. "
        "Scene title: " + str(plan.get("title", ""))[:120] +
        ". Scene brief: " + str(scene.get("image_prompt", ""))[:420] +
        ". Recurring visual identity: " + str(plan.get("visual_motif", ""))[:160] +
        ". " + checklist +
        " Return exactly one line containing every required key exactly once as key=YES or key=NO, "
        "separated by semicolons. Do not output a generic PASS, a paragraph, JSON or a Markdown list. "
        "Do not omit a key. Never guess; use NO whenever the detail is hidden or uncertain. "
        "Example format only: " + "; ".join(f"{key}=NO" for key in required_checks) + "."
    )

    result = _vision_query(image_data, question, timeout=120)
    return _parse_vision_assessment(result, "visual reviewer", required_checks=required_checks)


def review_storyboard_consistency(path, plan):
    """Inspect all three scene images together for one coherent visual identity."""
    try:
        image_bytes = Path(path).read_bytes()
    except OSError as exc:
        raise PipelineError(f"Storyboard visual QA could not read the contact sheet: {exc}") from exc
    image_data = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
    required_checks = ["same_performer", "same_violin", "macro_anatomy", "consistent_palette"]
    question = (
        "You are the continuity supervisor for a three-scene short video. Inspect the actual image panels "
        "from left to right, not the captions. Story: " + str(plan.get("title", ""))[:120] +
        ". Topic: " + str(plan.get("topic", ""))[:180] +
        ". Recurring visual identity: " + str(plan.get("visual_motif", ""))[:180] +
        ". Panel 1 is the hook, panel 2 is the macro/detail, panel 3 is the payoff, with distinct compositions for the three story beats. "
        "same_performer=YES only if Scene 1 and Scene 3 show the same identifiable adult performer, "
        "matching face, hairstyle and clothing. same_violin=YES only if all scenes visibly use the same "
        "amber-varnished violin design and recognizable body/tailpiece/fingerboard details. "
        "macro_anatomy=YES only if Scene 2 clearly shows the complete bridge, exactly four countable "
        "strings, distinct fingerboard, separate bow stick and horsehair ribbon, and visible hair-to-string "
        "contact at one point. consistent_palette=YES only if the three scenes share a coherent warm "
        "cinematic palette and realistic photographic style. Any missing, changed or uncertain requirement "
        "must be NO. Return exactly one line containing every required key exactly once as key=YES or key=NO, "
        "separated by semicolons. Never output a generic PASS, prose, JSON or Markdown. Do not omit any key. "
        "Example format only: same_performer=NO; same_violin=NO; macro_anatomy=NO; consistent_palette=NO."
    )
    result = _vision_query(image_data, question, timeout=120)
    return _parse_vision_assessment(result, "storyboard continuity reviewer", required_checks=required_checks)


def is_valid_portrait_scene_image(path):
    """Return true only for a readable image already normalized to the V3 portrait canvas."""
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.size == (W, H)
    except Exception:
        return False


def should_reuse_scene_image(path, plan, scene, index, metadata=None):
    """Reuse only an image that passed vision review and still matches its recorded hash."""
    if not is_valid_portrait_scene_image(path):
        return False
    assets = (metadata or {}).get("visual_assets", [])
    if not isinstance(assets, list) or index >= len(assets):
        return False
    record = assets[index]
    if not isinstance(record, dict):
        return False
    review = record.get("visual_review", {})
    if record.get("mode") != "cloudflare_flux_portrait_extended":
        return False
    if (
        not isinstance(review, dict)
        or review.get("passed") is not True
        or review.get("issues")
        or int(review.get("score", 0)) < MIN_IMAGE_QA_SCORE
    ):
        return False
    expected_plan_hash = hashlib.sha256(
        json.dumps(plan, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    recorded_plan_hash = str(record.get("plan_sha256") or "")
    if recorded_plan_hash and recorded_plan_hash != expected_plan_hash:
        return False
    expected_hash = str(record.get("sha256") or "")
    if not expected_hash:
        return False
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected_hash
    except OSError:
        return False


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

    draw.line((34, 1190, W - 34, 1190), fill=(235, 202, 139, 135), width=1)
    draw.text((34, 1207), "ORIGINAL STORY • ORIGINAL SOUNDTRACK",
              font=font(13), fill=(242, 230, 208, 240))
    draw.text((W - 110, 1207), f"{index + 1:02d}/03",
              font=font(13), fill=(242, 230, 208, 240))

    p = OUT / f"card-{index + 1}.png"
    canvas.convert("RGB").save(p, "PNG", optimize=True)
    return p

def make_motion_graphic_card(scene, index, plan, target):
    """Create a transparent, source-grounded infographic panel for one story beat."""
    width, height = 620, 245
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    gold = (235, 202, 139, 255)
    ivory = (255, 250, 241, 255)
    muted = (191, 202, 214, 255)
    draw.rounded_rectangle(
        (4, 4, width - 4, height - 4), radius=24,
        fill=(7, 13, 24, 222), outline=(235, 202, 139, 220), width=2
    )
    draw.rounded_rectangle((24, 26, 32, height - 26), radius=4, fill=gold)
    label = re.sub(r"\s+", " ", str(scene.get("graphic_label") or ("STORY BEAT " + str(index + 1)))).strip().upper()
    label = textwrap.shorten(label, width=30, placeholder="…")
    draw.text((54, 25), f"{index + 1:02d}  /  03     {label}", font=font(16), fill=gold)

    headline = textwrap.wrap(str(scene.get("caption") or plan.get("title", "")).strip(), width=28)[:2]
    y = 66
    for line in headline:
        draw.text((54, y), line, font=font(30), fill=ivory)
        y += 38

    detail = textwrap.wrap(str(scene.get("graphic_detail") or "").strip(), width=47)[:2]
    detail_y = 151 if len(headline) > 1 else 145
    for line in detail:
        draw.text((54, detail_y), line, font=font(17), fill=muted)
        detail_y += 24

    # A restrained three-step progress motif makes the sequence legible without
    # adding unsupported data or pretending the story contains a measured chart.
    line_y = height - 22
    draw.line((width - 112, line_y, width - 26, line_y), fill=(235, 202, 139, 105), width=2)
    for step in range(3):
        x = width - 112 + step * 43
        fill = gold if step <= index else (120, 133, 151, 180)
        draw.ellipse((x - 5, line_y - 5, x + 5, line_y + 5), fill=fill)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG", optimize=True)
    return target


def _ass_timestamp(seconds):
    centiseconds = max(0, int(round(float(seconds) * 100)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{whole_seconds:02}.{fraction:02}"


def write_kinetic_ass(cues, output_path):
    """Write animated sentence-level captions aligned to Kokoro's measured cue times."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "[Script Info]",
        "Title: Violin Prince Kinetic Captions",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: VP,DejaVu Sans,39,&H00F8F5EF,&H008BCEEA,&HCC07111F,&HCC07111F,-1,0,3,1.6,0,2,54,54,162,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    events = []
    stopwords = {"the", "and", "for", "with", "from", "that", "this", "into", "was", "are", "its", "one", "when", "their"}
    for cue in cues:
        start = float(cue.get("start", 0))
        end = float(cue.get("end", 0))
        phrase = re.sub(r"\s+", " ", str(cue.get("text", "")).strip())
        if not phrase or end <= start:
            continue
        words = re.findall(r"[A-Za-z0-9’'-]+", phrase)
        candidates = [word for word in words if word.casefold() not in stopwords and len(word) >= 4]
        emphasis = max(candidates or words or [""], key=len)
        caption_lines = textwrap.wrap(phrase, width=27)[:2]
        formatted_lines = []
        for line in caption_lines:
            safe_line = line.replace("{", r"\{").replace("}", r"\}")
            if emphasis:
                safe_line = re.sub(
                    rf"(?i)\b({re.escape(emphasis)})\b",
                    lambda match: (
                        r"{\c&H008BCEEA&\b1}" + match.group(1) +
                        r"{\c&H00F8F5EF&\b0}"
                    ),
                    safe_line,
                    count=1,
                )
            formatted_lines.append(safe_line)
        wrapped = r"\N".join(formatted_lines)
        animated = r"{\fad(180,220)\fscx96\fscy96\t(0,180,\fscx100\fscy100)}" + wrapped
        events.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},VP,,0,0,0,,{animated}"
        )
    if not events:
        raise PipelineError("No valid narration cues were available for kinetic captions.")
    target.write_text("\n".join(header + events) + "\n", encoding="utf-8")
    return target


def command(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise PipelineError("FFmpeg failed: " + p.stderr[-1200:])


def validate_final_video(path, narration_info=None, text_audit_path=None, report_path=None):
    """Fail closed unless encoded media, timing, captions and audio all pass Phase 2 QC."""
    from quality_control import QualityGateError, run_quality_gate

    info = narration_info if isinstance(narration_info, dict) else {}
    cues = info.get("word_cues") or info.get("subtitle_cues")
    try:
        result = run_quality_gate(
            path,
            report_path=report_path,
            expected_width=W,
            expected_height=H,
            expected_duration=24.0,
            expected_fps=float(FPS),
            frame_rate_tolerance=0.5,
            check_freeze=float(FPS) >= 20.0,
            narration_cues=cues if cues else None,
            word_count=info.get("word_count"),
            require_word_timing=(
                info.get("word_timing_method") == "kokoro_predicted_phoneme_durations"
                and bool(info.get("word_cues"))
            ),
            text_audit_path=text_audit_path,
        )
    except QualityGateError as exc:
        error = PipelineError(str(exc))
        error.retry_stage = exc.retry_stage
        error.quality_report = exc.report
        raise error from exc

    metrics = dict(result.get("metrics", {}))
    metrics.update({
        "quality_gate_status": result.get("status"),
        "quality_gate_report": (
            Path(report_path).name if report_path
            else Path(path).parent.joinpath("quality-control-report.json").name
        ),
        "quality_gate_checks_passed": sum(1 for item in result.get("checks", []) if item.get("passed")),
        "quality_gate_checks_total": len(result.get("checks", [])),
    })
    return metrics


def scene_durations_from_narration(narration_info, total_seconds=24.0):
    """Allocate scene lengths around spoken beats, leaving a short music-only ending."""
    cues = narration_info.get("subtitle_cues", []) if isinstance(narration_info, dict) else []
    cues = sorted(
        [cue for cue in cues if isinstance(cue, dict) and "start" in cue and "end" in cue],
        key=lambda cue: float(cue.get("start", 0)),
    )
    if not cues:
        return (8.0, 8.0, round(float(total_seconds) - 16.0, 2))

    first_end = max(0.0, float(cues[0].get("end", 0)))
    last_start = max(0.0, float(cues[-1].get("start", 0)))
    first_boundary = min(max(first_end + 1.4, 4.8), 7.5)
    second_boundary = min(
        max(last_start - 0.3, first_boundary + 5.5),
        float(total_seconds) - 5.0,
    )
    first = round(first_boundary, 2)
    second = round(second_boundary - first_boundary, 2)
    third = round(float(total_seconds) - first - second, 2)
    return (first, second, third)


def camera_motion_filter(frame_count, scene_index=0):
    """Use a gentle, eased push with a different continuous drift in each scene."""
    count = max(1, int(frame_count))
    progress = f"min(1,on/{max(1, count - 1)})"
    eased = f"({progress}*{progress}*(3-2*{progress}))"
    if int(scene_index) % 3 == 0:
        x_position = f"(0.40+0.20*{eased})"
        y_position = "0.5"
    elif int(scene_index) % 3 == 1:
        x_position = "0.5"
        y_position = f"(0.42+0.16*{eased})"
    else:
        x_position = f"(0.60-0.20*{eased})"
        y_position = "0.5"
    return (
        f"zoompan=z='1.005+0.055*{eased}':"
        f"x='(iw-iw/zoom)*{x_position}':y='(ih-ih/zoom)*{y_position}':"
        f"d={count}:s={W}x{H}:fps={FPS}"
    )


def render(plan, audio_bytes, narration_path, narration_info, image_paths=None,
           audio_source="generated_ambient_fallback"):
    OUT.mkdir(parents=True, exist_ok=True)
    audio_path = WORK / "approved-audio"
    audio_path.write_bytes(audio_bytes)
    clips = []
    scene_durations = scene_durations_from_narration(narration_info)
    for i, (scene, scene_seconds) in enumerate(zip(plan["scenes"], scene_durations)):
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
        graphic = make_motion_graphic_card(
            scene, i, plan, OUT / f"motion-graphic-{i + 1}.png"
        )
        clip = OUT / f"scene-{i + 1}.mp4"
        frame_count = max(1, int(round(scene_seconds * FPS)))
        camera = camera_motion_filter(frame_count, i)
        panel_fade_out = max(0.0, scene_seconds - 0.34)
        scene_filter = (
            f"[0:v]{camera},format=rgba[base];"
            f"[1:v]format=rgba,fade=t=in:st=0:d=0.30:alpha=1,"
            f"fade=t=out:st={panel_fade_out:.3f}:d=0.28:alpha=1[panel];"
            "[base][panel]overlay=x='(W-w)/2':"
            "y='H-h-340-18*(1-min(1,t/0.30))':format=auto,format=yuv420p[v]"
        )
        command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-loop", "1", "-framerate", str(FPS), "-i", str(card),
                 "-loop", "1", "-framerate", str(FPS), "-i", str(graphic),
                 "-t", f"{scene_seconds:.3f}", "-filter_complex", scene_filter,
                 "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast",
                 "-crf", "25", "-pix_fmt", "yuv420p", str(clip)])
        clips.append(clip)

    silent = OUT / "silent.mp4"
    transition_seconds = 0.35
    first_offset = max(0.0, scene_durations[0] - transition_seconds)
    second_offset = max(0.0, scene_durations[0] + scene_durations[1] - 2 * transition_seconds)
    transition_filter = (
        f"[0:v][1:v]xfade=transition=fade:duration={transition_seconds:.3f}:"
        f"offset={first_offset:.3f}[v1];"
        f"[v1][2:v]xfade=transition=fade:duration={transition_seconds:.3f}:"
        f"offset={second_offset:.3f}[v2];"
        f"[v2]tpad=stop_mode=clone:stop_duration={2 * transition_seconds:.3f},"
        "format=yuv420p[vout]"
    )
    command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(clips[0]), "-i", str(clips[1]), "-i", str(clips[2]),
             "-filter_complex", transition_filter, "-map", "[vout]", "-an",
             "-t", "24", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "25", "-pix_fmt", "yuv420p", str(silent)])
    final = OUT / "violin-prince-short.mp4"
    subtitle_path = OUT / "narration.srt"
    from voiceover import write_srt
    write_srt(narration_info.get("subtitle_cues", []), subtitle_path)
    ass_path = OUT / "narration.ass"
    write_kinetic_ass(narration_info.get("subtitle_cues", []), ass_path)
    if audio_source == "generated_ambient_fallback":
        bed_volume = "0.18"
    elif audio_source == "sampled_violin_cc0":
        bed_volume = "0.24"
    else:
        bed_volume = "0.26"
    audio_filter = (
        f"[1:a]volume={bed_volume}[bed];"
        "[2:a]highpass=f=75,acompressor=threshold=-20dB:ratio=3:attack=12:release=180,"
        "volume=1.15,asplit=2[voice_sc_raw][voice_mix];"
        "[voice_sc_raw]apad=whole_dur=24[voice_sc];"
        "[bed][voice_sc]sidechaincompress=threshold=0.035:ratio=10:attack=18:release=620:knee=4:makeup=1[duckedbed];"
        "[duckedbed][voice_mix]amix=inputs=2:duration=longest:dropout_transition=1,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,"
        "afade=t=in:st=0:d=0.5,afade=t=out:st=22:d=2[aout]"
    )
    video_filter = "subtitles=work/output/narration.ass,format=yuv420p"
    command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(silent), "-stream_loop", "-1", "-i", str(audio_path),
             "-i", str(narration_path),
             "-map", "0:v:0", "-filter_complex", audio_filter, "-map", "[aout]",
             "-t", "24", "-vf", video_filter, "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(final)])
    quality = validate_final_video(final, narration_info)
    narration_end = max(
        [float(cue.get("end", 0)) for cue in narration_info.get("subtitle_cues", [])]
        or [float(narration_info.get("duration_seconds", 0))]
    )
    if narration_end < 17.0:
        raise PipelineError(
            f"Narration covers only {narration_end:.1f}s of the 24-second video. "
            "The script or voice pacing must be improved before the video is accepted."
        )
    quality.update({
        "scene_durations_seconds": list(scene_durations),
        "narration_duration_seconds": round(narration_end, 2),
        "voice_coverage_percent": round(min(100.0, narration_end / 24.0 * 100.0), 1),
        "music_only_ending_seconds": round(max(0.0, 24.0 - narration_end), 2),
        "minimum_narration_coverage_seconds": 17.0,
        "camera_motion": "scene-specific eased push-in and gentle drift",
        "motion_graphics": 3,
        "subtitle_style": "animated sentence-level kinetic typography",
        "scene_transition": "0.35-second crossfade",
        "audio_source": audio_source,
        "audio_mix": "voice-priority sidechain ducking with music recovery in pauses",
        "creative_quality_version": 4,
    })
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
    if require_images:
        assets = metadata.get("visual_assets", [])
        required_status = "all_scenes_and_storyboard_passed_ai_review_human_review_still_required"
        if metadata.get("stage") != "visuals_ready" or metadata.get("visual_review_status") != required_status:
            raise PipelineError(
                "Visual package has not passed AI image review. Run the Visuals stage again before rendering."
            )
        if not isinstance(assets, list) or len(assets) != 3:
            raise PipelineError("Visual package is missing the three scene-by-scene review records.")
        storyboard_review = metadata.get("storyboard_review", {})
        if (
            not isinstance(storyboard_review, dict)
            or storyboard_review.get("passed") is not True
            or storyboard_review.get("issues")
            or int(storyboard_review.get("score", 0)) < MIN_IMAGE_QA_SCORE
        ):
            raise PipelineError("The three-scene storyboard has not passed AI continuity review.")
        for index, (asset, image_path) in enumerate(zip(assets, image_paths)):
            if not isinstance(asset, dict):
                raise PipelineError(f"Visual review record {index + 1} is invalid.")
            review = asset.get("visual_review", {})
            if (
                not isinstance(review, dict)
                or review.get("passed") is not True
                or review.get("issues")
                or int(review.get("score", 0)) < MIN_IMAGE_QA_SCORE
            ):
                raise PipelineError(f"Scene {index + 1} has not passed AI visual review.")
            expected_hash = str(asset.get("sha256") or "")
            actual_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
            if not expected_hash or actual_hash != expected_hash:
                raise PipelineError(f"Scene {index + 1} changed after visual approval; run Visuals again.")
    return plan, metadata, narration_info, paths, image_paths


def _scene_visual_prompt(scene, feedback="", index=0, plan=None):
    """Build a compact, complete image prompt; never let the model API clip key constraints."""
    raw_prompt = re.sub(r"\s+", " ", str(scene.get("image_prompt", ""))).strip()
    if not raw_prompt:
        raise PipelineError("A planned scene has no image prompt.")

    story = plan or {}
    subject = str(story.get("topic") or story.get("title") or "the story")[:140]
    anchor_raw = str(
        story.get("visual_motif")
        or story.get("visual_anchor")
        or scene.get("visual_anchor")
        or subject
    ).strip()
    context = " ".join([
        subject, anchor_raw, str(scene.get("caption", "")),
        str(scene.get("graphic_label", "")), str(scene.get("graphic_detail", "")),
        raw_prompt,
    ]).lower()
    performance_related = bool(re.search(
        r"\b(violinist|virtuoso|musician|performer|performance|playing|bowing|concert|"
        r"rapid|difficult|speed|fingerboard|bow hand|left hand|right hand|technique)\b",
        context,
    ))
    story_identity = " ".join((
        str(story.get("topic", "")),
        str(story.get("title", "")),
        str(story.get("visual_motif", "")),
        str(story.get("character_identity", "")),
    )).casefold()
    scene_identity = " ".join((
        raw_prompt,
        str(scene.get("caption", "")),
        str(scene.get("graphic_detail", "")),
    )).casefold()
    has_violin_identity = bool(re.search(r"\bviolin(?:ist)?\b", story_identity))
    competing_instrument = bool(re.search(
        r"\b(cello|cellist|viola|violist|double bass|contrabass|guitarist|guitar|pianist|piano)\b",
        story_identity,
    ))
    violin_performance = (
        performance_related
        and has_violin_identity
        and not competing_instrument
        and bool(re.search(r"\bbow\b", scene_identity))
    )
    scene_index = max(0, min(2, int(index)))
    compact_prompt = textwrap.shorten(
        raw_prompt, width=105 if violin_performance and scene_index == 1 else 250, placeholder="…"
    )
    if violin_performance and scene_index == 1:
        compact_prompt = "Violin bow hair contacting one string"
    anchor = textwrap.shorten(
        re.sub(r"\s+", " ", anchor_raw),
        width=88 if violin_performance and scene_index == 1 else 125,
        placeholder="…",
    )

    if violin_performance and scene_index == 1:
        # Put the physical contact geometry before stylistic detail. FLUX receives
        # this entire prompt; the bow/strings requirements are never beyond a cut-off.
        prompt_parts = [
            "SUBJECT & ACTION: " + compact_prompt + ".",
            "SHOT 2 MACRO CLOSE-UP: string-height side three-quarter photograph, moderate depth of field; the bridge, all four strings, fingerboard, both bow parts and contact point must be simultaneously sharp.",
            "VIOLIN GEOMETRY: one complete upright maple bridge with both feet resting on the amber top plate. Exactly four separate strings run lengthwise in parallel and are individually countable. A distinct ebony fingerboard extends away from the bridge. Keep all four strings visible on both sides of the bridge.",
            "BOW GEOMETRY: exactly one bow crosses the strings horizontally at 90 degrees. Show the slim dark wooden stick and narrow pale horsehair ribbon as two separate, continuous parallel parts with a visible gap between them; they join only at frog and tip. Neither part hides the other. No extra rods or duplicate bows.",
            "CONTACT POINT: the pale horsehair alone touches exactly one string at one clear point between bridge and fingerboard. The dark stick must not touch the strings. Keep the other three strings visibly separate.",
            "FRAMING & FOCUS: portrait 9:16, bridge across the lower-middle frame and fingerboard extending behind it; keep the complete bridge, exactly four strings, fingerboard, slim dark wooden stick, narrow pale horsehair ribbon and contact point inside frame, simultaneously sharp. No cropping, blur, merging or warped parts.",
            "RECURRING ASSET ANCHOR: " + anchor + "; maintain believable violin proportions.",
            "STYLE & LIGHT: photorealistic macro editorial photograph, real maple, ebony, steel strings and amber varnish; warm 3200K key, neutral fill, soft amber rim. No illustration or 3D render.",
            "BACKGROUND: quiet charcoal and walnut tones, no text, logos or watermarks.",
        ]
    else:
        shot_roles = (
            "SHOT 1 — TWO-SECOND HOOK: instantly readable performer, instrument and active playing posture.",
            "SHOT 2 — EXTREME CLOSE-UP DETAIL: isolate one tactile physical interaction and its precise focal point.",
            "SHOT 3 — EMOTIONAL PAYOFF: widen back out to connect the detail with the full performance.",
        )
        camera_profiles = (
            "50mm medium close-up, eye-level three-quarter view, slow push-in.",
            "85mm macro lens, close three-quarter view, very shallow depth of field and one exact focal plane.",
            "50mm wider portrait view, slightly low angle, slow pull-back reveal.",
        )
        prompt_parts = [
            "SUBJECT & ACTION: " + compact_prompt + ". " + shot_roles[scene_index],
            "RECURRING ASSET ANCHOR: " + anchor + "; keep recognizable subject design and believable proportions.",
            "STYLE & MATERIAL: photorealistic cinematic editorial photography, believable anatomy and authentic material texture; no illustration, no 3D render, no anime, no plastic or stock-photo look.",
            "LIGHTING & CAMERA: " + camera_profiles[scene_index] + " Warm 3200K key, neutral 4300K fill and amber 2800K rim.",
            "BACKGROUND & ATMOSPHERE: charcoal, walnut, oxblood, copper, antique gold and warm ivory. Avoid blue, teal, cyan or cold-blue backgrounds. Layered foreground, midground and background.",
            "COMPOSITION RULES: clear focal hierarchy, realistic perspective, Portrait 9:16 composition, no text, no lettering, no logo, no watermark.",
        ]
        if performance_related and scene_index == 0:
            if violin_performance:
                prompt_parts.append(
                    "PERFORMANCE ACCURACY: natural violin under jaw/shoulder; plausible left hand on fingerboard and right hand on bow."
                )
            else:
                prompt_parts.append(
                    "PERFORMANCE ACCURACY: believable instrument support, natural posture and anatomically plausible playing hands."
                )
        elif performance_related and scene_index == 2:
            if violin_performance:
                prompt_parts.append(
                    "PERFORMANCE PAYOFF: performer, violin, both hands and bow in a natural, connected playing posture."
                )
            else:
                prompt_parts.append(
                    "PERFORMANCE PAYOFF: performer and instrument resolve in a natural, connected playing posture."
                )
        elif scene_index == 1:
            prompt_parts.append(
                "MACRO FOCUS: one exact surface or material interaction, narrow focus plane and quiet background."
            )

    performer_lock = textwrap.shorten(
        re.sub(r"\s+", " ", str(story.get("character_identity", ""))).strip(),
        width=220,
        placeholder="…",
    )
    if violin_performance and scene_index in (0, 2) and performer_lock:
        prompt_parts.append(
            "PERFORMER IDENTITY LOCK: " + performer_lock
            + " Scene 1 and Scene 3 must show the SAME identifiable person, hairstyle, face and outfit; do not substitute another performer."
        )

    base_prompt = " ".join(prompt_parts)
    clean_feedback = textwrap.shorten(re.sub(r"\s+", " ", str(feedback or "")).strip(), width=90, placeholder="…")
    if clean_feedback:
        optional = " ADDITIONAL DIRECTION: " + clean_feedback
        if len(base_prompt) + len(optional) <= MAX_IMAGE_PROMPT_CHARS:
            base_prompt += optional

    if len(base_prompt) > MAX_IMAGE_PROMPT_CHARS:
        raise PipelineError(
            f"Scene {scene_index + 1} prompt is {len(base_prompt)} characters; "
            f"the maximum is {MAX_IMAGE_PROMPT_CHARS}. Reduce optional wording."
        )
    return base_prompt

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
        caption = "\n".join(textwrap.wrap(str(scene.get("caption", "")), width=28)[:2])
        draw.multiline_text((left, 808), f"SCENE {index + 1}  ·  {caption}",
                            font=font(16), fill=(245, 238, 226), spacing=3)
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


def load_reusable_research():
    """Load a preserved research.json from a previous failed Prepare artifact, if supplied."""
    saved = WORK / "reuse" / "research.json"
    if not saved.is_file():
        return None
    try:
        items = json.loads(saved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError("The supplied previous-run research file is unreadable.") from exc
    if not isinstance(items, list) or not items:
        raise PipelineError("The supplied previous-run research file contains no headlines.")
    items = [
        item for item in items
        if isinstance(item, dict) and item.get("title") and item.get("url")
    ]
    if not items:
        raise PipelineError("The supplied previous-run research file has no usable titled article links.")
    WORK.mkdir(exist_ok=True)
    (WORK / "research.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"Reusing {len(items)} preserved research sources from an earlier run; research feeds will not be called again.")
    return items


def _write_json_atomic(path, payload):
    """Persist a recoverable stage checkpoint without leaving partial JSON behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_json_checkpoint(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _valid_wav_checkpoint(path):
    try:
        with wave.open(str(path), "rb") as source:
            return (
                source.getnchannels() in (1, 2)
                and source.getframerate() >= 16000
                and source.getnframes() > 0
                and source.getnframes() / source.getframerate() > 0.1
            )
    except (OSError, wave.Error, EOFError):
        return False


def prepare_stage():
    """Prepare once and checkpoint audio, research, story and narration independently."""
    claim_run()
    paths = _package_paths()
    metadata = _read_json_checkpoint(paths["metadata"])
    if not isinstance(metadata, dict):
        metadata = {}

    # A complete prepared package is a reusable checkpoint. A render retry must not
    # call research, the story model, or Kokoro again.
    if all(paths[key].is_file() for key in ("plan", "metadata", "audio", "narration")):
        try:
            plan, _saved_metadata, _narration_info, _saved_paths, _images = _read_package(require_images=False)
            if paths["audio"].stat().st_size >= 4096 and _valid_wav_checkpoint(paths["narration"]):
                topic = str(plan.get("topic", ""))
                title = str(plan.get("title", "Violin Prince Short"))
                log("Reusing the complete prepared-package checkpoint; preparation stages were not repeated.")
                report("prepared", "Reused the saved story, narration and soundtrack checkpoint.", topic, title,
                       metadata={"stage": "prepared", "reused_checkpoint": True})
                return 0
        except (PipelineError, OSError):
            pass

    report("running", "Preparing research, story, narration and background music bed with stage checkpoints.")

    # Checkpoint 1: soundtrack. Preserve the selected source and exact bytes.
    cached_asset = metadata.get("asset")
    if paths["audio"].is_file() and paths["audio"].stat().st_size >= 4096 and isinstance(cached_asset, dict):
        asset = cached_asset
        audio = paths["audio"].read_bytes()
        log("Reusing checkpointed soundtrack; audio selection was not repeated.")
    else:
        asset, audio = get_audio()
        if len(audio) < 4096:
            raise PipelineError("Selected soundtrack is empty or unexpectedly small.")
        paths["audio"].write_bytes(audio)
        metadata.update({
            "schema_version": 2,
            "prepared_run_id": metadata.get("prepared_run_id") or RUN_ID,
            "asset": asset,
            "stage": "audio_ready",
        })
        _write_json_atomic(paths["metadata"], metadata)
        log("Soundtrack checkpoint saved.")

    # Checkpoint 2: research. Prefer the package, then a restored prior-run file,
    # and only then call external research feeds.
    items = None
    if paths["research"].is_file():
        saved_items = _read_json_checkpoint(paths["research"])
        if isinstance(saved_items, list):
            items = [
                item for item in saved_items
                if isinstance(item, dict) and item.get("title") and item.get("url")
            ]
    if not items:
        items = load_reusable_research()
    if not items:
        items = research()
        log("Research sources collected: " + str(len(items)))
    _write_json_atomic(paths["research"], items)
    metadata["stage"] = "research_ready"
    _write_json_atomic(paths["metadata"], metadata)

    # Checkpoint 3: creative plan. A later narration or render failure must not
    # trigger another story-planning call.
    plan = _read_json_checkpoint(paths["plan"])
    if (
        not isinstance(plan, dict)
        or not isinstance(plan.get("scenes"), list)
        or len(plan.get("scenes", [])) != 3
        or not str(plan.get("narration_script") or "").strip()
    ):
        plan = make_plan(items, recent_topics())
        _write_json_atomic(paths["plan"], plan)
        log("Creative-plan checkpoint saved.")
    else:
        log("Reusing checkpointed creative plan; story planning was not repeated.")

    topic = str(plan.get("topic", ""))
    title = str(plan.get("title", "Violin Prince Short"))
    narration_script_hash = hashlib.sha256(
        str(plan["narration_script"]).encode("utf-8")
    ).hexdigest()
    metadata.update({
        "schema_version": 2,
        "prepared_run_id": metadata.get("prepared_run_id") or RUN_ID,
        "asset": asset,
        "topic": topic,
        "title": title,
        "stage": "story_ready",
    })
    _write_json_atomic(paths["metadata"], metadata)

    # Checkpoint 4: exact narration WAV and its native timing metadata.
    narration_info = metadata.get("narration_info")
    if not (
        isinstance(narration_info, dict)
        and narration_info.get("subtitle_cues")
        and metadata.get("narration_script_sha256") == narration_script_hash
        and _valid_wav_checkpoint(paths["narration"])
    ):
        from voiceover import synthesize_voiceover
        narration_path, narration_info = synthesize_voiceover(
            plan["narration_script"], OUT / "narration.wav"
        )
        if not _valid_wav_checkpoint(narration_path):
            raise PipelineError("Narration checkpoint is not a readable non-empty WAV file.")
        shutil.copy2(narration_path, paths["narration"])
        metadata["narration_info"] = narration_info
        metadata["narration_script_sha256"] = narration_script_hash
        metadata["stage"] = "narration_ready"
        _write_json_atomic(paths["metadata"], metadata)
        log("Narration WAV and its timing metadata checkpointed.")
    else:
        log("Reusing checkpointed narration and native timing cues; Kokoro was not called again.")

    metadata.update({
        "schema_version": 2,
        "prepared_run_id": metadata.get("prepared_run_id") or RUN_ID,
        "asset": asset,
        "narration_info": narration_info,
        "narration_script_sha256": narration_script_hash,
        "topic": topic,
        "title": title,
        "prepared_at": metadata.get("prepared_at") or datetime.now(timezone.utc).isoformat(),
        "stage": "prepared",
    })
    _write_json_atomic(paths["metadata"], metadata)
    _write_review_text(plan, PACKAGE / "review.txt")
    log("Prepared package saved. Review review.txt before generating scene images.")
    report("prepared", "Story, narration and soundtrack are ready for review.", topic, title,
           metadata={"stage": "prepared", "checkpointed": True})
    return 0


def _storyboard_repair_scene_index(issues):
    """Choose the smallest continuity repair: macro anatomy or the final wide-shot performer."""
    combined = " ".join(str(item) for item in (issues or [])).casefold()
    if any(term in combined for term in (
        "bridge", "bow", "string", "fingerboard", "macro", "contact point",
    )):
        return 1
    # Scene 1 remains the character reference; repair the final wide shot by default.
    return 2


def visuals_stage(feedback=""):
    """Generate only the three scene images from a previously prepared package."""
    if not CF_ACCOUNT or not CF_TOKEN:
        raise PipelineError("CF_ACCOUNT_ID and CF_AI_TOKEN are required for the Visuals stage.")
    plan, metadata, _narration_info, paths, image_paths = _read_package(require_images=False)
    plan_hash = hashlib.sha256(
        json.dumps(plan, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    saved_assets = metadata.get("visual_assets", [])
    if not isinstance(saved_assets, list):
        saved_assets = []
    visual_assets = (saved_assets + [None] * 3)[:3]
    metadata["visual_assets"] = visual_assets
    # Keep the checkpoint metadata aligned with the exact creative plan being visually reviewed.
    metadata["title"] = str(plan.get("title") or metadata.get("title") or "")
    metadata["topic"] = str(plan.get("topic") or metadata.get("topic") or "")
    metadata["visual_motif"] = str(plan.get("visual_motif") or "")
    metadata["visual_plan_sha256"] = plan_hash
    metadata["stage"] = "visuals_in_progress"
    metadata["visual_checkpoint"] = {
        "completed_scene_indices": [
            index + 1 for index, record in enumerate(visual_assets)
            if isinstance(record, dict) and record.get("visual_review", {}).get("passed") is True
        ],
        "total_scenes": 3,
    }
    _write_json_atomic(paths["metadata"], metadata)
    for index, scene in enumerate(plan["scenes"]):
        if image_paths[index].is_file() and should_reuse_scene_image(
            image_paths[index], plan, scene, index, metadata
        ):
            record = dict(metadata["visual_assets"][index])
            log(f"Reusing vision-reviewed scene image {index + 1}/3.")
            visual_assets[index] = record
            continue

        if image_paths[index].exists():
            log(f"Replacing scene image {index + 1}/3 because it has no current visual-quality approval.")
            image_paths[index].unlink(missing_ok=True)

        feedback_for_attempt = str(feedback or "")
        review = None
        generated = None
        for attempt in range(1, MAX_IMAGE_QA_ATTEMPTS + 1):
            prompt = _scene_visual_prompt(
                scene, feedback_for_attempt, index=index, plan=plan
            )
            seed_candidate = IMAGES / f"scene-{index + 1}.jpg"
            if attempt == 1 and seed_candidate.is_file() and is_valid_portrait_scene_image(seed_candidate):
                generated = seed_candidate
                log(f"Re-reviewing preserved unapproved candidate for scene {index + 1}; no new image generation for this candidate.")
            else:
                generated = make_image(prompt, index)
            if not is_valid_portrait_scene_image(generated):
                raise PipelineError(
                    f"Scene {index + 1} generator produced an invalid portrait image; "
                    "the visual package was not marked complete."
                )
            review = review_scene_image(generated, plan, scene, index)
            review["attempt"] = attempt
            if review["passed"]:
                break
            issues = review.get("issues") or [
                review.get("summary") or "composition did not meet the visual brief"
            ]
            feedback_for_attempt = (
                "Correct these specific visual defects from the previous attempt: "
                + "; ".join(str(issue)[:140] for issue in issues[:5])
                + ". Preserve the requested subject, framing and recurring visual identity."
            )
            log(
                f"Scene {index + 1}/3 visual review rejected attempt {attempt}: "
                + "; ".join(str(issue)[:100] for issue in issues[:3])
            )
            diagnostic = str((review or {}).get("summary", "")).strip()
            if diagnostic:
                log(f"Scene {index + 1}/3 reviewer diagnostic: {diagnostic[:220]}")

        if not review or not review["passed"]:
            details = "; ".join(
                str(issue)[:140] for issue in (review or {}).get("issues", [])[:5]
            )
            raise PipelineError(
                f"Scene {index + 1} failed AI visual review after {MAX_IMAGE_QA_ATTEMPTS} attempts. "
                f"Rejected defects: {details or 'the reviewer did not approve the composition'}. "
                "The pipeline stopped before rendering instead of accepting defective artwork."
            )

        shutil.copy2(generated, image_paths[index])
        if not is_valid_portrait_scene_image(image_paths[index]):
            raise PipelineError(
                f"Scene {index + 1} failed portrait validation after copying into the package."
            )

        image_hash = hashlib.sha256(image_paths[index].read_bytes()).hexdigest()
        asset_record = {
            "file": image_paths[index].name,
            "mode": "cloudflare_flux_portrait_extended",
            "width": W,
            "height": H,
            "sha256": image_hash,
            "plan_sha256": plan_hash,
            "generated_run_id": str(RUN_ID),
            "visual_review": review,
        }
        visual_assets[index] = asset_record
        metadata["visual_assets"] = visual_assets
        metadata["visual_checkpoint"] = {
            "completed_scene_indices": [
                scene_index + 1 for scene_index, record in enumerate(visual_assets)
                if isinstance(record, dict) and record.get("visual_review", {}).get("passed") is True
            ],
            "total_scenes": 3,
        }
        _write_json_atomic(paths["metadata"], metadata)
        log(
            f"Scene {index + 1}/3 generated and vision-reviewed "
            f"(score {review['score']}/100, attempt {review['attempt']})."
        )
    storyboard = make_storyboard_preview(plan, image_paths, PACKAGE / "storyboard-preview.png")
    storyboard_review = review_storyboard_consistency(storyboard, plan)
    for repair_attempt in range(1, MAX_STORYBOARD_REPAIR_ATTEMPTS + 1):
        if storyboard_review["passed"] and not storyboard_review.get("issues"):
            break

        issues = storyboard_review.get("issues", [])
        details = "; ".join(str(issue)[:140] for issue in issues[:5])
        repair_index = _storyboard_repair_scene_index(issues)
        scene = plan["scenes"][repair_index]
        if repair_index == 2:
            repair_feedback = (
                "CONTINUITY REPAIR: this must be the exact same adult male violinist as Scene 1: "
                "same short swept dark-brown hair, clean-shaven face, white dress shirt, charcoal waistcoat, "
                "same amber-varnished violin and warm walnut concert room. Do not introduce a different person."
            )
        else:
            repair_feedback = (
                "CONTINUITY REPAIR: match the exact amber-varnished violin shown in the wide shots. "
                "Show the complete bridge, exactly four strings, ebony fingerboard, one separate dark bow stick, "
                "one pale horsehair ribbon and one visible hair-to-string contact point. Keep every part sharp."
            )
        repair_feedback += " Fix only the storyboard review defects: " + (details or storyboard_review.get("summary", "visual continuity drift"))
        log(
            f"Storyboard continuity rejected; targeted repair {repair_attempt}/"
            f"{MAX_STORYBOARD_REPAIR_ATTEMPTS} regenerates scene {repair_index + 1} only."
        )
        repair_prompt = _scene_visual_prompt(
            scene, repair_feedback, index=repair_index, plan=plan
        )
        repaired_image = make_image(repair_prompt, repair_index)
        if not is_valid_portrait_scene_image(repaired_image):
            raise PipelineError(
                f"Storyboard repair generated an invalid portrait image for scene {repair_index + 1}."
            )
        repair_review = review_scene_image(
            repaired_image, plan, scene, repair_index
        )
        repair_review["attempt"] = 1
        repair_review["continuity_repair_attempt"] = repair_attempt
        if not repair_review.get("passed") or repair_review.get("issues"):
            repair_details = "; ".join(
                str(issue)[:140] for issue in repair_review.get("issues", [])[:5]
            )
            raise PipelineError(
                f"Storyboard repair scene {repair_index + 1} did not pass its individual visual gate: "
                + (repair_details or repair_review.get("summary", "visual approval withheld"))
            )
        shutil.copy2(repaired_image, image_paths[repair_index])
        image_hash = hashlib.sha256(image_paths[repair_index].read_bytes()).hexdigest()
        visual_assets[repair_index] = {
            "file": image_paths[repair_index].name,
            "mode": "cloudflare_flux_portrait_extended",
            "width": W,
            "height": H,
            "sha256": image_hash,
            "plan_sha256": plan_hash,
            "generated_run_id": str(RUN_ID),
            "visual_review": repair_review,
        }
        metadata["visual_assets"] = visual_assets
        _write_json_atomic(paths["metadata"], metadata)
        storyboard = make_storyboard_preview(
            plan, image_paths, PACKAGE / "storyboard-preview.png"
        )
        storyboard_review = review_storyboard_consistency(storyboard, plan)

    if not storyboard_review["passed"] or storyboard_review.get("issues"):
        details = "; ".join(str(issue)[:140] for issue in storyboard_review.get("issues", [])[:5])
        raise PipelineError(
            "The three scenes did not pass storyboard continuity review after targeted repair. "
            + (details or storyboard_review.get("summary", "Visual identity was not consistent."))
        )
    metadata["storyboard_review"] = storyboard_review
    metadata["stage"] = "visuals_ready"
    metadata["visual_feedback"] = re.sub(r"\s+", " ", str(feedback or "")).strip()[:600]
    metadata["visuals_run_id"] = RUN_ID
    metadata["visual_assets"] = visual_assets
    metadata["visual_modes"] = [item["mode"] for item in visual_assets]
    metadata["portrait_dimensions"] = [W, H]
    metadata["visual_review_model"] = VISION_MODEL
    metadata["visual_review_status"] = "all_scenes_and_storyboard_passed_ai_review_human_review_still_required"
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
    audio_source = str(metadata.get("asset", {}).get("audio_source", "generated_ambient_fallback"))
    path, video_quality = render(
        plan, audio, paths["narration"], narration_info,
        image_paths=image_paths, audio_source=audio_source
    )
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
        "audio_source": audio_source,
        "audio_license": metadata.get("asset", {}).get("license", ""),
        "audio_source_library": metadata.get("asset", {}).get("source_library", ""),
        "audio_attribution": metadata.get("asset", {}).get("attribution", ""),
        "duration_seconds": 24, "format": "9:16",
        "publishing_status": final_status, "publish_results": publish_result,
        "output_key": stored.get("object_key"), "prepared_run_id": metadata.get("prepared_run_id"),
        "visuals_run_id": metadata.get("visuals_run_id"),
        "visual_review_status": metadata.get("visual_review_status", "not_reviewed"),
        "visual_review_model": metadata.get("visual_review_model", ""),
        "visual_asset_reviews": [
            item.get("visual_review", {}) for item in metadata.get("visual_assets", [])
            if isinstance(item, dict)
        ],
        "storyboard_review": metadata.get("storyboard_review", {}),
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
        if stage == "full":
            # One-click mode: keep each successful intermediate package before
            # continuing, so later failures never force the earlier stages to repeat.
            if prepare_stage() != 0:
                return 1
            if visuals_stage(visual_feedback) != 0:
                return 1
            return render_stage()
        raise PipelineError("Unknown pipeline stage: " + str(stage))
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
