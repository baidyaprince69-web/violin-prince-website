#!/usr/bin/env python3
"""Free-first cloud producer. Never switches to a paid service."""
import argparse, base64, json, os, re, shutil, subprocess, sys, textwrap, time, uuid, wave
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
    """Require four short beats with a deliberate 8/9/12/12 spoken-word rhythm."""
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
        "The narration_script must have 40 to 44 spoken words across exactly four natural, complete sentences. "
        "Aim for 41 words with this exact sentence budget: sentence 1 has 8 words, sentence 2 has 9 words, "
        "sentence 3 has 12 words, and sentence 4 has 12 words. Sentence 1 is the curiosity hook and must be resolved. "
        "Keep every sentence at 12 words or fewer and make the wording sound natural when spoken aloud, never padded. "
        "Build context, reveal one memorable sourced detail, "
        "and finish with a satisfying payoff. No greeting, filler padding, generic introduction or misleading clickbait. "
        "Use a cinematic storytelling style for human-interest topics and a clear documentary style for factual discoveries. "
        "Exactly 3 scenes. Each scene needs a concise caption of 9 words maximum and an original, specific image_prompt "
        "in English. Scene 1 must visualise the hook, scene 2 must show the exact object/action/detail that makes this "
        "story distinctive, and scene 3 must visually resolve the story. Use three clearly different compositions, "
        "not three unrelated stock images. Avoid generic musician portraits unless the story specifically concerns a person. "
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
            for attempt in (1, 2):
                previous_sentence = sentences[index - 1] if index > 0 else ""
                next_sentence = sentences[index + 1] if index < 3 else ""
                payload = {
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a precise spoken-documentary script editor. Return exactly one JSON "
                                "object with one field named sentence, and no Markdown or commentary. "
                                "The sentence field must contain exactly " + str(target_words) +
                                " spoken words, counted as ordinary space-separated words. Use simple words; "
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
                                ("\nYour previous attempt " + str(attempt - 1) + " " + current_error + ". "
                                 "Correct the count without adding filler." if attempt > 1 else "") +
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
                issue = narration_sentence_error(candidate, target_words)
                repair_attempts.append(
                    {
                        "sentence_number": index + 1,
                        "target_words": target_words,
                        "attempt": attempt,
                        "returned_words": narration_word_count(candidate),
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
                    f"{target_words} natural, evidence-supported words after two focused attempts. "
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
    # Preserve the planner's original references in the artifact if source matching
    # needs diagnosis; this is safe metadata and contains no credentials.
    (WORK / "creative_plan_debug.json").write_text(
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

    caption_lines = textwrap.wrap(str(caption).strip(), width=27)[:2]
    caption_font = font(34)
    caption_y = 1010 - max(0, len(caption_lines) - 1) * 22
    for line in caption_lines:
        box = draw.textbbox((0, 0), line, font=caption_font, stroke_width=1)
        x = max(30, (W - (box[2] - box[0])) // 2)
        draw.text((x, caption_y), line, font=caption_font, fill=white,
                  stroke_width=2, stroke_fill=(0, 0, 0, 210))
        caption_y += 46

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


def camera_motion_filter(frame_count):
    """Create one slow, centered push-in with cubic ease-in/ease-out motion."""
    count = max(1, int(frame_count))
    progress = f"min(1,on/{max(1, count - 1)})"
    eased = f"({progress}*{progress}*(3-2*{progress}))"
    return (
        f"zoompan=z='1.01+0.05*{eased}':"
        "x='(iw-iw/zoom)*0.5':y='(ih-ih/zoom)*0.5':"
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
        clip = OUT / f"scene-{i + 1}.mp4"
        frame_count = max(1, int(round(scene_seconds * FPS)))
        # Keep the same gentle camera direction in every shot. The cubic easing
        # removes the stop/start feel and avoids the previous alternating pan.
        camera = camera_motion_filter(frame_count)
        vf = camera + ",format=yuv420p"
        command(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-loop", "1", "-framerate", str(FPS), "-i", str(card),
                 "-t", f"{scene_seconds:.3f}", "-vf", vf, "-an", "-c:v", "libx264",
                 "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p", str(clip)])
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
    if audio_source == "generated_ambient_fallback":
        bed_volume = "0.12"
    elif audio_source == "sampled_violin_cc0":
        bed_volume = "0.16"
    else:
        bed_volume = "0.20"
    audio_filter = (
        f"[1:a]volume={bed_volume}[bed];"
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
    narration_end = max(
        [float(cue.get("end", 0)) for cue in narration_info.get("subtitle_cues", [])]
        or [float(narration_info.get("duration_seconds", 0))]
    )
    quality.update({
        "scene_durations_seconds": list(scene_durations),
        "narration_duration_seconds": round(narration_end, 2),
        "voice_coverage_percent": round(min(100.0, narration_end / 24.0 * 100.0), 1),
        "music_only_ending_seconds": round(max(0.0, 24.0 - narration_end), 2),
        "camera_motion": "smooth centered ease-in-out push-in",
        "scene_transition": "0.35-second crossfade",
        "audio_source": audio_source,
        "creative_quality_version": 3,
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
    return plan, metadata, narration_info, paths, image_paths


def _scene_visual_prompt(scene, feedback="", index=0, plan=None):
    """Lock every image to one visual identity while giving each scene a distinct role."""
    prompt = str(scene.get("image_prompt", "")).strip()
    if not prompt:
        raise PipelineError("A planned scene has no image prompt.")
    shot_roles = (
        "SHOT 1 — HOOK: an immediately readable establishing composition with one intriguing "
        "focal subject and a strong silhouette; make the viewer curious.",
        "SHOT 2 — DISTINCTIVE DETAIL: a closer, more intimate composition showing the exact "
        "object, action or detail that makes this story different; avoid a generic posed portrait.",
        "SHOT 3 — PAYOFF: a wider emotional resolution that visually connects back to the opening "
        "image and makes the story feel complete.",
    )
    subject = str((plan or {}).get("topic") or (plan or {}).get("title") or "the story")[:140]
    prompt += (
        f". Story subject: {subject}. {shot_roles[max(0, min(2, int(index)))]} "
        "Keep the same visual world, recurring subject design and lighting logic across all three images. "
        "Violin Prince visual identity: premium hand-painted cinematic editorial illustration, "
        "clearly illustrated concept art rather than photography, refined painterly texture, "
        "deep midnight navy, muted teal, antique gold and warm ivory highlights. "
        "Layered foreground, midground and background with clear depth for gentle camera movement; "
        "intentional negative space for subtitles, elegant cinematic lighting, precise focal detail. "
        "No generic stock photography, no unrelated people, no text, no lettering, no logos, no watermark. "
        "Respect real-world scale and the supplied story; symbolic imagery must not imply an unsupported fact. "
        "Portrait 9:16 composition."
    )
    clean_feedback = re.sub(r"\s+", " ", str(feedback or "")).strip()[:600]
    if clean_feedback:
        prompt += ", additional visual direction: " + clean_feedback
    return prompt[:1800]


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


def prepare_stage():
    """Create research, story, narration and soundtrack once; no images or MP4 yet."""
    claim_run()
    asset, audio = get_audio()
    report("running", "Preparing research, story, narration and background music bed.")
    items = load_reusable_research()
    if items is None:
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
        # Reuse any valid image already present when recovering a partially completed
        # visual stage; do not spend another model call on work already completed.
        if image_paths[index].is_file():
            try:
                with Image.open(image_paths[index]) as existing:
                    existing.verify()
                log(f"Reusing valid scene image {index + 1}/3 from an earlier attempt.")
                continue
            except Exception:
                image_paths[index].unlink(missing_ok=True)

        prompt = _scene_visual_prompt(scene, feedback, index=index, plan=plan)
        try:
            generated = make_image(prompt, index)
        except (requests.Timeout, requests.ConnectionError):
            log(f"Temporary connection issue for scene {index + 1}; retrying once.")
            time.sleep(2)
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
