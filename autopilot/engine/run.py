#!/usr/bin/env python3
"""Free-first cloud producer. Never switches to a paid service."""
import argparse, base64, hashlib, json, os, re, shutil, subprocess, sys, textwrap, time, uuid, wave
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from html import unescape as html_unescape
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, parse_qs, urljoin
import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

try:
    from .seo_intelligence import build_topic_queries, discover as seo_discover, load_profile as seo_load_profile
    from .seo_intelligence.storage import load_learning_signals
except ImportError:  # Direct script execution from the engine directory.
    from seo_intelligence import build_topic_queries, discover as seo_discover, load_profile as seo_load_profile
    from seo_intelligence.storage import load_learning_signals

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


def _is_google_host(host):
    host = str(host or "").lower().removeprefix("www.")
    return host == "google.com" or host.endswith(".google.com") or host == "googleusercontent.com" or host.endswith(".googleusercontent.com")


def _is_news_aggregator_host(host):
    """Identify search/news portals that can never serve as final publisher evidence."""
    value = str(host or "").lower().removeprefix("www.").rstrip(".")
    if not value:
        return True
    if _is_google_host(value):
        return True
    blocked_roots = (
        "bing.com", "bing.net", "msn.com", "microsoft.com",
        "duckduckgo.com", "search.yahoo.com", "newsnow.com",
        "flipboard.com", "feedly.com",
    )
    return any(value == root or value.endswith("." + root) for root in blocked_roots)


def _publisher_article_url_from_html(page_text, expected_domain=""):
    """Find a publisher article URL embedded in a news/search interstitial page."""
    expected = _normalized_publisher_domain(expected_domain)
    text_value = html_unescape(str(page_text or "")).replace("\\u003d", "=").replace("\\/", "/")
    candidates = re.findall(r"https?://[^\s\"'<>]+", text_value, flags=re.IGNORECASE)
    expanded = []
    for candidate in candidates:
        candidate = candidate.rstrip("),;\\")
        expanded.append(candidate)
        try:
            parsed = urlparse(candidate)
            for values in parse_qs(parsed.query).values():
                for value in values:
                    decoded = unquote(value)
                    if decoded.startswith(("http://", "https://")):
                        expanded.append(decoded)
        except Exception:
            continue

    ranked = []
    seen_urls = set()
    for candidate in expanded:
        try:
            parsed = urlparse(candidate)
            host = (parsed.hostname or "").lower().removeprefix("www.")
            path = (parsed.path or "").rstrip("/")
            key = source_key(candidate)
            if parsed.scheme not in ("http", "https") or not host or _is_news_aggregator_host(host):
                continue
            if not path or path in ("/rss", "/feed", "/news", "/"):
                continue
            if key in seen_urls:
                continue
            if expected and not (host == expected or host.endswith("." + expected) or expected.endswith("." + host)):
                continue
            seen_urls.add(key)
            ranked.append((3 if expected and host == expected else 1, candidate))
        except Exception:
            continue
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1] if ranked else ""




FRESHNESS_PREFERRED_HOURS = 50
FRESHNESS_MAX_AGE_HOURS = 168


def parse_publication_timestamp(value):
    """Parse an article publication date/time and normalize it to UTC."""
    if isinstance(value, datetime):
        parsed, precision = value, "timestamp"
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        precision = "date"
    else:
        raw = str(value or "").strip()
        if not raw:
            return None, "unknown"
        precision = "date" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else "timestamp"
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                return None, "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), precision


def article_freshness(item, as_of=None):
    """Prefer articles <=50h old; accept verified publication dates up to seven days."""
    item = item if isinstance(item, dict) else {}
    published, precision = parse_publication_timestamp(
        item.get("published_at_utc") or item.get("date")
    )
    if published is None:
        return {
            "published_at_utc": "",
            "publication_precision": "unknown",
            "age_hours": None,
            "freshness_status": "unknown",
            "freshness_eligible": False,
        }
    now, _ = parse_publication_timestamp(as_of or datetime.now(timezone.utc))
    if now is None:
        now = datetime.now(timezone.utc)
    age_hours = (now - published).total_seconds() / 3600.0
    if age_hours < -5.0 / 60.0:
        status, eligible = "invalid_future_date", False
    else:
        age_hours = max(0.0, age_hours)
        if age_hours <= FRESHNESS_PREFERRED_HOURS:
            status, eligible = "preferred", True
        elif age_hours <= FRESHNESS_MAX_AGE_HOURS:
            status, eligible = "acceptable", True
        else:
            status, eligible = "stale", False
    return {
        "published_at_utc": published.isoformat().replace("+00:00", "Z"),
        "publication_precision": precision,
        "age_hours": round(age_hours, 2),
        "freshness_status": status,
        "freshness_eligible": eligible,
    }




def _google_news_article_id(url):
    """Return the opaque article token from a Google News RSS/article URL."""
    try:
        parsed = urlparse(str(url or ""))
        if (parsed.hostname or "").lower().removeprefix("www.") != "news.google.com":
            return ""
        match = re.search(r"/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)", parsed.path)
        return match.group(1) if match else ""
    except Exception:
        return ""


def resolve_google_news_article_url(url, interstitial_html, expected_domain=""):
    """Decode a modern Google News wrapper through its article-page RPC."""
    article_id = _google_news_article_id(url)
    if not article_id:
        raise ValueError("Not a Google News article URL.")
    page = str(interstitial_html or "")
    signature_match = re.search(
        r"""data-n-a-sg\s*=\s*(["'])(.*?)\1""", page, flags=re.IGNORECASE | re.DOTALL
    )
    timestamp_match = re.search(
        r"""data-n-a-ts\s*=\s*(["'])(\d+)\1""", page, flags=re.IGNORECASE
    )
    if not signature_match or not timestamp_match:
        raise ValueError("Google News article page did not expose its decoding signature.")
    signature = html_unescape(signature_match.group(2))
    timestamp = int(timestamp_match.group(2))
    try:
        locale = (parse_qs(urlparse(str(url)).query).get("ceid") or ["US:en"])[0]
        if not re.fullmatch(r"[A-Za-z]{2}:[A-Za-z]{2}", locale):
            locale = "US:en"
    except Exception:
        locale = "US:en"

    inner_request = [
        "garturlreq",
        [
            ["X", "X", ["X", "X"], None, None, 1, 1, locale, None, 1,
             None, None, None, None, None, 0, 1],
            "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
        ],
        article_id,
        timestamp,
        signature,
    ]
    rpc_request = [[[
        "Fbv4je",
        json.dumps(inner_request, ensure_ascii=False, separators=(",", ":")),
        None,
        "generic",
    ]]]
    body = "f.req=" + quote(
        json.dumps(rpc_request, ensure_ascii=False, separators=(",", ":")),
        safe="",
    )
    response = requests.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; ViolinPrinceAutopilot/0.2)",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": "https://news.google.com",
            "Referer": str(url),
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=(5, 15),
    )
    response.raise_for_status()

    publisher_url = ""
    for line in str(response.text or "").splitlines():
        candidate_line = line.strip()
        if not candidate_line.startswith("[["):
            continue
        try:
            rows = json.loads(candidate_line)
        except json.JSONDecodeError:
            continue
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, list) or len(row) < 3 or row[1] != "Fbv4je":
                continue
            try:
                decoded = json.loads(row[2])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(decoded, list) and len(decoded) > 1:
                value = str(decoded[1] or "").strip()
                if value.startswith(("http://", "https://")):
                    publisher_url = value
                    break
        if publisher_url:
            break

    if not publisher_url:
        raise ValueError("Google News did not return a publisher URL for this article.")
    parsed = urlparse(publisher_url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    expected = _normalized_publisher_domain(expected_domain)
    if parsed.scheme not in ("http", "https") or not host or _is_news_aggregator_host(host):
        raise ValueError("Google News returned a non-publisher destination.")
    if expected and not (
        host == expected or host.endswith("." + expected) or expected.endswith("." + host)
    ):
        raise ValueError("Google News destination did not match its RSS publisher identity.")
    return publisher_url


def extract_article_page_metadata(html):
    """Read publication date and article identity signals from publisher HTML."""
    text_value = str(html or "")[:1_500_000]
    meta = {}

    def attributes(tag_text):
        return {
            str(key).casefold(): html_unescape(value.strip())
            for key, _quote, value in re.findall(
                r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(["'])(.*?)\2""",
                str(tag_text or ""),
                flags=re.DOTALL,
            )
        }

    for match in re.finditer(r"<meta\b[^>]*>", text_value, flags=re.IGNORECASE | re.DOTALL):
        attrs = attributes(match.group(0))
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").casefold()
        value = attrs.get("content") or attrs.get("datetime") or ""
        if key and value:
            meta[key] = value.strip()

    page_title = meta.get("og:title") or meta.get("twitter:title") or ""
    headline = meta.get("headline") or meta.get("itemprop:headline") or ""
    if not page_title:
        title_match = re.search(
            r"<title\b[^>]*>(.*?)</title\s*>", text_value,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if title_match:
            page_title = re.sub(
                r"\s+", " ",
                html_unescape(re.sub(r"<[^>]+>", " ", title_match.group(1))),
            ).strip()

    og_type_article = str(meta.get("og:type") or "").casefold() == "article"
    published_value = ""
    for key in (
        "article:published_time", "datepublished", "parsely-pub-date",
        "publish-date", "pubdate", "date.created", "dc.date.issued",
    ):
        if meta.get(key):
            published_value = meta[key]
            break

    # Some publishers expose the publication timestamp only in a <time> element.
    if not published_value:
        for match in re.finditer(r"<time\b[^>]*>", text_value, flags=re.IGNORECASE | re.DOTALL):
            attrs = attributes(match.group(0))
            itemprop = str(attrs.get("itemprop") or "").casefold()
            class_or_id = " ".join((str(attrs.get("class") or ""), str(attrs.get("id") or ""))).casefold()
            is_publication_time = (
                "datepublished" in itemprop
                or "date-published" in class_or_id
                or "published" in class_or_id
                or "publish-date" in class_or_id
            )
            if is_publication_time and attrs.get("datetime"):
                published_value = attrs["datetime"]
                break

    article_types = {
        "article", "newsarticle", "reportagenewsarticle", "analysisnewsarticle",
        "opinionnewsarticle", "blogposting", "liveblogposting", "techarticle",
    }
    structured_article = False

    def inspect_jsonld(node):
        nonlocal structured_article, published_value, headline, page_title
        if isinstance(node, dict):
            raw_type = node.get("@type")
            types = raw_type if isinstance(raw_type, list) else [raw_type]
            if any(str(value or "").casefold() in article_types for value in types):
                structured_article = True
                if not published_value:
                    published_value = str(node.get("datePublished") or "")
                if not headline:
                    headline = str(node.get("headline") or "")
                if not page_title:
                    page_title = str(node.get("headline") or node.get("name") or "")
            for value in node.values():
                inspect_jsonld(value)
        elif isinstance(node, list):
            for value in node:
                inspect_jsonld(value)

    for match in re.finditer(
        r"<script\b[^>]*type\s*=\s*['\"]application/ld\+json['\"][^>]*>(.*?)</script\s*>",
        text_value,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            inspect_jsonld(json.loads(html_unescape(match.group(1)).strip()))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    published, _ = parse_publication_timestamp(published_value)
    return {
        "is_article": bool(structured_article or og_type_article),
        "structured_article": structured_article,
        "og_type_article": og_type_article,
        "has_publication_metadata": bool(published),
        "published_at_utc": published.isoformat().replace("+00:00", "Z") if published else "",
        "headline": re.sub(r"\s+", " ", str(headline or "")).strip()[:260],
        "page_title": re.sub(r"\s+", " ", str(page_title or "")).strip()[:260],
    }


def _article_page_url_is_directory(url):
    """Reject category, archive, tag, event-listing and other non-story routes."""
    try:
        parsed = urlparse(str(url or ""))
        segments = [part.casefold() for part in (parsed.path or "").split("/") if part]
        blocked = {
            "category", "categories", "tag", "tags", "tagged", "topic", "topics",
            "archive", "archives", "section", "sections", "search", "latest",
            "directory", "directories", "author", "authors", "page", "all",
            "events", "event", "concerts", "concert", "calendar",
            "programme", "program", "tickets", "schedule", "listings",
            "feed", "rss", "video", "videos",
        }
        if any(segment in blocked for segment in segments):
            return True
        if segments and segments[0] in {"c", "sections", "topics"}:
            return True
        if len(segments) == 1 and segments[0] in {
            "news", "features", "culture", "arts", "music", "entertainment",
            "research", "science", "technology",
        }:
            return True
        return False
    except Exception:
        return True


def _article_page_verified(item, url, html, metadata):
    """Require a matching story headline; OG article tags alone are not proof."""
    if _article_page_url_is_directory(url):
        return False
    supplied_title = str((item or {}).get("title") or "").strip()
    page_title = str(metadata.get("headline") or metadata.get("page_title") or "").strip()
    supplied_tokens = source_tokens(supplied_title)
    page_tokens = source_tokens(page_title)
    if len(supplied_tokens) < 2 or len(page_tokens) < 2:
        return False
    overlap = len(supplied_tokens.intersection(page_tokens)) / max(
        1, min(len(supplied_tokens), len(page_tokens))
    )
    # Even pages with Article JSON-LD or og:type=article must match the RSS/search
    # headline; section landing pages often emit those generic metadata tags too.
    if overlap < 0.45:
        return False
    if not metadata.get("is_article") and len(
        [part for part in urlparse(str(url or "")).path.split("/") if part]
    ) < 2:
        return False
    return True


def _story_article_eligibility(item, as_of=None):
    """Return the first auditable reason an article cannot corroborate a story."""
    freshness = article_freshness(item, as_of=as_of)
    if not is_direct_publisher_article(item):
        return False, "not_an_article_specific_publisher_page", freshness
    if item.get("article_page_verified") is not True:
        return False, "article_page_not_verified", freshness
    if len(str(item.get("evidence_text") or "").strip()) < 90:
        return False, "readable_article_evidence_too_short", freshness
    if freshness["freshness_status"] == "unknown":
        return False, "publication_date_missing", freshness
    if freshness["freshness_status"] == "invalid_future_date":
        return False, "publication_date_is_in_the_future", freshness
    if freshness["freshness_status"] == "stale":
        return False, "published_more_than_seven_days_ago", freshness
    return True, "", freshness



def is_direct_publisher_article(item):
    """Reject aggregators, encyclopedia pages, homepages and known directory routes."""
    if isinstance(item, dict):
        url = str(item.get("url") or item.get("publisher_url") or "").strip()
        if item.get("article_page_verified") is False:
            return False
        if str(item.get("article_page_kind") or "").casefold() in {
            "category", "archive", "directory", "event_listing", "homepage",
        }:
            return False
    else:
        url = str(item or "").strip()
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = (parsed.path or "").rstrip("/")
        if parsed.scheme not in ("http", "https") or not host:
            return False
        if _is_news_aggregator_host(host) or host in ("youtube.com", "youtu.be"):
            return False
        if host == "wikipedia.org" or host.endswith(".wikipedia.org") or host == "wikimedia.org" or host.endswith(".wikimedia.org"):
            return False
        if not path or path == "/" or _article_page_url_is_directory(url):
            return False
        return True
    except Exception:
        return False


def enrich_source_evidence(items):
    """Resolve discovery URLs, then retain evidence only from a verified article page."""
    request_headers = {"User-Agent": "Mozilla/5.0 (compatible; ViolinPrinceAutopilot/0.3)"}

    def promote_publisher_response(response, item, original_url, resolution_status):
        content_type = response.headers.get("Content-Type", "").lower()
        final_url = str(response.url or original_url)
        final_host = (urlparse(final_url).hostname or "").lower().removeprefix("www.")
        if response.status_code != 200 or "html" not in content_type:
            return None
        if _is_news_aggregator_host(final_host) or not is_direct_publisher_article(final_url):
            return None
        metadata = extract_article_page_metadata(response.text)
        if not _article_page_verified(item, final_url, response.text, metadata):
            return None
        parser = ParagraphExtractor()
        parser.feed(response.text[:1_500_000])
        excerpt = " ".join(parser.paragraphs[:14])[:2200]
        if len(excerpt) < 90:
            return None

        item["source_url_original"] = str(original_url or "")
        item["url"] = final_url
        item["publisher_url"] = final_url
        item["publisher_domain"] = final_host
        item["evidence_text"] = excerpt
        item["link_type"] = "publisher_article"
        item["article_page_verified"] = True
        item["article_page_kind"] = (
            "structured_article_title_matched" if metadata.get("structured_article")
            else "og_article_title_matched" if metadata.get("og_type_article")
            else "article_title_matched"
        )
        item["publisher_resolution_status"] = resolution_status
        item.pop("publisher_resolution_error", None)
        if metadata.get("published_at_utc"):
            item["published_at_utc"] = metadata["published_at_utc"]
            item["publication_date_source"] = "publisher_article_metadata"
        elif item.get("date"):
            published, _precision = parse_publication_timestamp(item.get("date"))
            if published:
                # Google/Bing RSS dates remain attached to this exact, publisher-
                # matched article. They are a fallback only when the page has none.
                item["published_at_utc"] = published.isoformat().replace("+00:00", "Z")
                item["publication_date_source"] = "publisher_matched_rss_pubdate"
        return item

    def publisher_page(url, source_item, original_url, resolution_status):
        response = requests.get(
            url,
            headers=request_headers,
            timeout=(5, 12),
            allow_redirects=True,
        )
        return promote_publisher_response(
            response, source_item, original_url, resolution_status
        )

    def fetch_one(item, google_decode_allowed=False):
        original_url = str(item.get("url") or "")
        if not original_url.startswith(("http://", "https://")):
            return item
        try:
            response = requests.get(
                original_url,
                headers=request_headers,
                timeout=(5, 12),
                allow_redirects=True,
            )
            final_url = str(response.url or original_url)
            final_host = (urlparse(final_url).hostname or "").lower().removeprefix("www.")
            content_type = response.headers.get("Content-Type", "").lower()

            if response.status_code == 200 and "html" in content_type:
                # Direct publisher URLs need only one fetch. Article title matching is
                # still mandatory; Article/OG metadata alone cannot qualify a section page.
                if not _is_news_aggregator_host(final_host) and is_direct_publisher_article(final_url):
                    promoted = promote_publisher_response(
                        response, item, original_url, "direct_publisher_url"
                    )
                    if promoted:
                        return promoted

                # Current Google News RSS IDs are opaque. The article wrapper embeds a
                # signature and timestamp for Google's batchexecute resolver; a plain
                # redirect or URL scrape does not reliably expose the publisher URL.
                if _google_news_article_id(original_url):
                    if google_decode_allowed:
                        try:
                            resolved_url = resolve_google_news_article_url(
                                original_url,
                                response.text,
                                expected_domain=item.get("publisher_domain", ""),
                            )
                            promoted = publisher_page(
                                resolved_url,
                                item,
                                original_url,
                                "resolved_via_google_news_batchexecute",
                            )
                            if promoted:
                                return promoted
                            item["publisher_resolution_error"] = (
                                "Decoded publisher page failed article-title or readable-body verification."
                            )
                        except Exception as exc:
                            item["publisher_resolution_error"] = str(exc)[:220]
                    else:
                        item["publisher_resolution_error"] = (
                            "Google News decode budget reached for this research pass."
                        )
                    item["publisher_resolution_status"] = "unresolved_google_news"
                else:
                    # Bing and other discovery pages may expose a direct publisher link
                    # in their HTML; resolve it only when the publisher identity matches.
                    expected_domain = item.get("publisher_domain", "")
                    resolved = _publisher_article_url_from_html(
                        response.text[:1_500_000], expected_domain
                    )
                    if resolved:
                        promoted = publisher_page(
                            resolved, item, original_url, "resolved_from_discovery_interstitial"
                        )
                        if promoted:
                            return promoted
                        item["publisher_resolution_error"] = (
                            "Extracted publisher page failed article-title or readable-body verification."
                        )

            item.pop("publisher_url", None)
            item.pop("evidence_text", None)
            item["article_page_verified"] = False
            item["article_page_kind"] = "non_article_or_unverified_page"
            item["link_type"] = "discovery_lead"
            item.setdefault("publisher_resolution_status", "article_page_unverified")
        except Exception as exc:
            item.pop("publisher_url", None)
            item.pop("evidence_text", None)
            item["article_page_verified"] = False
            item["article_page_kind"] = "non_article_or_unverified_page"
            item["link_type"] = "discovery_lead"
            item["publisher_resolution_status"] = "fetch_failed"
            item["publisher_resolution_error"] = str(exc)[:220]
            log("Article evidence unavailable: " + str(exc)[:120])
        return item

    candidates = items[:240]
    if not candidates:
        return items
    # Decoding costs two requests per Google News article. Bound the first pass and
    # prioritize the most relevant (already ranked) Google links to avoid rate bursts.
    google_urls = [
        str(item.get("url") or "") for item in candidates
        if _google_news_article_id(item.get("url"))
    ]
    google_decode_allowlist = set(google_urls[:18])
    completed = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(
                fetch_one,
                dict(item),
                str(item.get("url") or "") in google_decode_allowlist,
            ): item.get("url")
            for item in candidates
        }
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
    """Give the planner topic leads while keeping stable, traceable source IDs."""
    fields = (
        "title", "summary", "evidence_text", "publisher_name",
        "publisher_home", "publisher_domain", "url", "date", "source",
        "published_at_utc", "publication_date_source",
        "article_page_verified", "article_page_kind", "source_url_original",
        "publisher_resolution_status", "publisher_resolution_error"
    )
    selected = []
    for item in items[:350]:
        if not item.get("title") or not item.get("url"):
            continue
        direct = is_direct_publisher_article(item)
        domain = str(item.get("publisher_domain") or urlparse(item.get("url", "")).netloc).lower().removeprefix("www.")
        record = {key: item.get(key, "") for key in fields}
        record["publisher_domain"] = domain
        record["source_eligibility"] = "direct_publisher_article" if direct else "discovery_only"
        record["link_type"] = "publisher_article" if direct else "discovery_lead"
        if not direct:
            record["summary"] = ""
            record["evidence_text"] = ""
        stable_url = source_key(item.get("url"))
        stable_identity = stable_url or (
            str(domain) + "|" + re.sub(r"\s+", " ", str(item.get("title", "")).casefold()).strip()
        )
        digest = hashlib.sha256(stable_identity.encode("utf-8")).hexdigest()[:16].upper()
        record["source_id"] = str(item.get("source_id") or ("SRC_" + digest))
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
    """Measure overlap with the full story claim, not only its short title."""
    core = source_tokens(" ".join(
        str(plan.get(key, ""))
        for key in ("topic", "title", "description")
    ))
    if not core:
        core = source_tokens(plan.get("narration_script", ""))
    article = source_tokens(" ".join(str(item.get(key, "")) for key in (
        "title", "evidence_text"
    )))
    if not core or not article:
        return 0.0
    return len(core.intersection(article)) / len(core)


_GENERIC_ENTITY_WORDS = {
    "about", "advanced", "album", "artist", "artists", "classical", "computer",
    "concert", "digital", "discovery", "future", "instrument", "instruments",
    "music", "musical", "new", "performance", "real", "realistic", "science",
    "scientific", "song", "sound", "sounds", "space", "technology", "the",
    "traditional", "violin", "virtual", "world",
}


def story_entity_anchor_groups(plan):
    """Extract named subject anchors that a source must mention to corroborate the story."""
    values = " ".join(
        str(plan.get(key, ""))
        for key in ("topic", "title", "description", "hook", "narration_script")
    )
    groups = []
    seen = set()

    # Acronyms and initialisms are strong, compact identifiers (MIT, NASA, ESA).
    for match in re.findall(r"\b[A-Z]{2,}\b", values):
        token = match.casefold()
        if token not in _GENERIC_ENTITY_WORDS and token not in seen:
            seen.add(token)
            groups.append({token})

    # Multi-word proper names, such as "Roman Space Telescope" or "Alena Baeva".
    for match in re.findall(
        r"\b[A-Z][a-zÀ-ÖØ-öø-ÿ’'-]+(?:\s+[A-Z][a-zÀ-ÖØ-öø-ÿ’'-]+)+\b",
        values,
    ):
        tokens = source_tokens(match)
        tokens = {token for token in tokens if token not in _GENERIC_ENTITY_WORDS}
        if tokens and tokens not in groups:
            groups.append(tokens)

    # Single distinctive title/topic names such as "Mozart" or "Eurovision".
    for field in ("topic", "title"):
        for match in re.findall(r"\b[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ’'-]{2,}\b", str(plan.get(field, ""))):
            token = match.casefold()
            if token in _GENERIC_ENTITY_WORDS or token in seen:
                continue
            seen.add(token)
            groups.append({token})

    return groups


def source_supports_story(plan, item, minimum_score=0.20):
    """Require both story-level relevance and a named-entity anchor when one exists."""
    score = source_relevance_score(plan, item)
    if score < minimum_score:
        return False
    anchors = story_entity_anchor_groups(plan)
    if not anchors:
        return True
    article = source_tokens(" ".join(
        str(item.get(key, "")) for key in ("title", "evidence_text")
    ))
    return any(group.issubset(article) for group in anchors)


def _normalized_publisher_domain(value):
    """Normalize a publisher hostname supplied with or without a URL scheme."""
    text_value = str(value or "").strip().lower()
    if not text_value:
        return ""
    parsed = urlparse(text_value if "://" in text_value else "//" + text_value)
    return (parsed.hostname or "").lower().removeprefix("www.").rstrip(".")


_COMMON_SECOND_LEVEL_PUBLIC_SUFFIXES = {
    "ac.uk", "co.uk", "gov.uk", "ltd.uk", "me.uk", "net.uk", "org.uk", "plc.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.in", "firm.in", "net.in", "org.in", "gen.in", "ind.in",
    "co.nz", "net.nz", "org.nz", "govt.nz", "ac.nz",
    "com.br", "net.br", "org.br",
    "com.cn", "net.cn", "org.cn", "gov.cn",
    "com.sg", "net.sg", "org.sg", "gov.sg",
    "co.za", "net.za", "org.za",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp",
}


def publisher_family_domain(value):
    """Collapse subdomains to one publisher family (e.g. news.mit.edu → mit.edu)."""
    host = _normalized_publisher_domain(value)
    if not host:
        return ""
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in _COMMON_SECOND_LEVEL_PUBLIC_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def _publisher_domains_match(left, right):
    """Match an exact publisher host or a genuine parent/subdomain relationship."""
    a = _normalized_publisher_domain(left)
    b = _normalized_publisher_domain(right)
    return bool(a and b and (a == b or a.endswith("." + b) or b.endswith("." + a)))


def resolve_plan_sources(plan, research_items):
    """Resolve stable IDs, URLs, titles, and publisher domains to direct articles."""
    candidates = [
        item for item in research_items
        if item.get("title") and is_direct_publisher_article(item)
        and _normalized_publisher_domain(item.get("publisher_domain") or urlparse(item.get("url", "")).netloc)
    ]
    by_id = {str(item.get("source_id", "")).strip().upper(): item for item in candidates}
    by_url = {source_key(item.get("url", "")): item for item in candidates if source_key(item.get("url", ""))}

    references = plan.get("sources") or plan.get("source_reference_hints") or []
    if isinstance(references, (str, dict)):
        references = [references]
    if not isinstance(references, list):
        references = []

    selected = []
    for reference in references[:8]:
        if isinstance(reference, dict):
            hints = [
                reference.get("source_id"), reference.get("id"), reference.get("url"),
                reference.get("title"), reference.get("publisher_domain"),
                reference.get("publisher_name"), reference.get("publisher"),
            ]
        else:
            hints = [reference]

        matched = None
        for raw_hint in hints:
            value = str(raw_hint or "").strip()
            if not value:
                continue
            matched = by_id.get(value.upper())
            if matched:
                break
            normalized_url = source_key(value)
            if normalized_url:
                matched = by_url.get(normalized_url)
                if matched:
                    break

            normalized = " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
            for item in candidates:
                title = " ".join(re.findall(r"[a-z0-9]+", str(item.get("title", "")).casefold()))
                publisher = " ".join(re.findall(r"[a-z0-9]+", str(item.get("publisher_name", "")).casefold()))
                domain = _normalized_publisher_domain(item.get("publisher_domain"))
                if normalized and normalized in (title, publisher):
                    matched = item
                    break
                if _publisher_domains_match(value, domain):
                    matched = item
                    break
            if matched:
                break

        if matched and matched.get("url") not in [item.get("url") for item in selected]:
            selected.append(matched)

    if selected:
        return selected[:5]

    ranked = sorted(
        ((source_relevance_score(plan, item), item) for item in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if ranked and ranked[0][0] >= 0.16:
        score, item = ranked[0]
        log(
            "Planner source references did not resolve; selected the closest supplied "
            f"direct publisher article by topic overlap ({score:.0%}): "
            f"{item.get('publisher_name') or item.get('publisher_domain')}."
        )
        return [item]
    return []


def research():
    """Discover publisher article leads broadly, prioritising music-relevant direct links."""
    items = []
    try:
        r = http.get("https://api.gdeltproject.org/api/v2/doc/doc",
                     params={"query": "(music OR violin OR entertainment OR culture OR film OR science OR technology)",
                             "mode": "ArtList", "format": "json", "maxrecords": "40",
                             "sort": "HybridRel", "timespan": "7d"}, timeout=25)
        r.raise_for_status()
        for article in r.json().get("articles", []):
            if article.get("title") and article.get("url"):
                article_url = str(article["url"])
                article_domain = str(article.get("domain") or urlparse(article_url).netloc).lower().removeprefix("www.")
                items.append({
                    "title": str(article["title"])[:220], "summary": "",
                    "url": article_url, "date": "",
                            "discovered_at": str(article.get("seendate", "")),
                    "source": article_domain or "GDELT",
                    "publisher_name": article_domain,
                    "publisher_domain": article_domain,
                    "source_feed": "GDELT broad research",
                    "link_type": "discovery_lead",
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

    # DuckDuckGo exposes direct outbound publisher URLs. These are still only
    # discovery leads until enrich_source_evidence fetches and reads the article.
    ddg_queries = [
        "violin music orchestra instrument research news",
        "classical music performers festivals competitions news",
        "music technology instruments research discoveries",
        "film music composers soundtrack industry news",
        "music culture arts discoveries performance news",
    ]
    ddg_count = 0
    for query in ddg_queries:
        try:
            request = requests.Request(
                "GET",
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            ).prepare()
            response = http.get(
                request.url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ViolinPrinceAutopilot/0.2)"},
                timeout=12,
            )
            response.raise_for_status()
            records = duckduckgo_search_records(response.text, label="DuckDuckGo broad publisher discovery")
            items.extend(records[:18])
            ddg_count += len(records[:18])
        except Exception as exc:
            log("DuckDuckGo broad research unavailable for " + query[:55] + ": " + str(exc)[:130])

    unique = {}
    for item in items:
        key = source_key(item.get("url")) or str(item.get("url") or "").split("?")[0].rstrip("/")
        if key:
            unique.setdefault(key, item)

    # Prefer real publisher article URLs over aggregator redirects during the
    # bounded enrichment pass; direct URLs are not trusted until their bodies load.
    def discovery_priority(item):
        direct_url = is_direct_publisher_article(item)
        feed = str(item.get("source_feed") or "")
        feed_priority = 0 if "DuckDuckGo" in feed else (1 if "GDELT" in feed else 2)
        title_quality = min(len(source_tokens(item.get("title", ""))), 20)
        return (0 if direct_url else 1, feed_priority, -title_quality)

    result = sorted(unique.values(), key=discovery_priority)[:120]
    if not result:
        raise PipelineError("All free research feeds were unavailable; no video created.")
    result = enrich_source_evidence(result)
    WORK.mkdir(exist_ok=True)
    (WORK / "research.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    readable = sum(
        1 for item in result
        if is_direct_publisher_article(item) and len(str(item.get("evidence_text") or "").strip()) >= 90
    )
    log(
        f"Broad research collected {len(result)} unique leads, including {ddg_count} DuckDuckGo publisher links; "
        f"{readable} direct publisher pages have readable article evidence."
    )
    return result

def story_search_phrases(plan, existing_items=None):
    """Build searches from the factual description and named story subject first."""
    values = []
    topic = re.sub(r"\s+", " ", str(plan.get("topic") or "")).strip()
    title = re.sub(r"\s+", " ", str(plan.get("title") or "")).strip()
    description = re.sub(r"\s+", " ", str(plan.get("description") or "")).strip()

    def add(value):
        phrase = re.sub(r"\s+", " ", str(value or "")).strip(" -:;,.")
        if len(phrase) >= 6 and len(phrase.split()) >= 2:
            if phrase.casefold() not in {item.casefold() for item in values}:
                values.append(phrase[:160])

    # Search the named subject stated in the factual description before generic
    # topic/title wording. This prevents a broad theme replacing the real story.
    for match in re.findall(
        r"\b[A-Z][A-Za-z’'-]+(?:\s+[A-Z][A-Za-z’'-]+){1,4}\b",
        description,
    ):
        phrase = re.sub(r"\s+", " ", match).strip()
        if phrase.casefold().split()[0] not in {"from", "how", "why", "what", "when", "where", "the", "this"}:
            add(phrase)

    for text_value in (topic, title):
        for match in re.findall(r"\b[A-Z][A-Za-z’'-]+(?:\s+[A-Z][A-Za-z’'-]+){1,3}\b", text_value):
            phrase = re.sub(r"\s+", " ", match).strip()
            if phrase.casefold().split()[0] not in {"from", "how", "why", "what", "when", "where", "the", "this"}:
                add(phrase)

    add(description)
    add(topic)
    add(title)

    stopwords = {
        "about", "after", "also", "and", "are", "from", "how", "into", "its",
        "new", "of", "our", "the", "their", "this", "through", "was", "what",
        "when", "where", "which", "with", "uses", "using", "exploring",
    }
    keywords = [
        word for word in re.findall(r"[a-z0-9]+", (description + " " + topic + " " + title).casefold())
        if len(word) > 2 and word not in stopwords
    ]
    compact_keywords = list(dict.fromkeys(keywords))[:10]
    if len(compact_keywords) >= 2:
        add(" ".join(compact_keywords))

    # Search only strong seed-headline matches. Discovery leads remain untrusted
    # until their publisher article is fetched and its body verified.
    ranked_seed = sorted(
        (
            (source_relevance_score(plan, item), item)
            for item in (existing_items or [])
            if isinstance(item, dict) and item.get("title")
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    for score, item in ranked_seed:
        seed_minimum = 0.15 if str(plan.get("description") or "").strip() else 0.30
        if source_supports_story(plan, item, minimum_score=seed_minimum):
            add(item.get("title", ""))
        if len(values) >= 6:
            break

    return values[:6]


def story_primary_entity_groups(plan):
    """Identify the actual named subject from the factual description."""
    description = str(plan.get("description") or "").strip()
    groups = []
    for match in re.findall(
        r"\b[A-Z][A-Za-zÀ-ÖØ-öø-ÿ’'-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ’'-]+)+\b",
        description,
    ):
        tokens = source_tokens(match) - _GENERIC_ENTITY_WORDS
        acronyms = {
            token.casefold() for token in re.findall(r"\b[A-Z]{2,}\b", match)
        }
        # A named object such as "Roman Space Telescope" is the primary anchor;
        # the organization acronym (NASA) is useful but should not be mandatory.
        tokens -= acronyms
        if len(tokens) >= 2 and tokens not in groups:
            groups.append(tokens)

    # Prefer the longest named entity, e.g. {"roman", "telescope"}, over a
    # broad acronym such as NASA that could appear in unrelated space coverage.
    groups.sort(key=lambda value: (len(value), len(" ".join(sorted(value)))), reverse=True)
    if groups:
        return groups[:2]

    for match in re.findall(r"\b[A-Z]{2,}\b", description):
        token = match.casefold()
        if token not in _GENERIC_ENTITY_WORDS:
            groups.append({token})
    return groups[:2]


def story_description_claim_tokens(plan):
    """Return the distinctive factual words a source should corroborate."""
    description = source_tokens(plan.get("description", ""))
    generic_verbs = {
        "exploring", "explores", "uses", "using", "use", "helps", "help",
        "shows", "showing", "offers", "provides", "features", "featuring",
        "about", "based", "designed", "describes", "examines",
    }
    entity_tokens = set().union(*story_primary_entity_groups(plan)) if story_primary_entity_groups(plan) else set()
    return description - _GENERIC_ENTITY_WORDS - SOURCE_MATCH_STOPWORDS - generic_verbs - entity_tokens


def source_supports_story(plan, item, minimum_score=0.20):
    """Require the named subject and a substantive match to the factual description."""
    score = source_relevance_score(plan, item)
    if score < minimum_score:
        return False

    article = source_tokens(" ".join(
        str(item.get(key, "")) for key in ("title", "evidence_text")
    ))

    primary_entities = story_primary_entity_groups(plan)
    if not primary_entities:
        # When the factual description is absent (e.g. a seed-search helper),
        # fall back to the story's named entities rather than generic topic words.
        primary_entities = story_entity_anchor_groups(plan)
    if primary_entities and not any(group.issubset(article) for group in primary_entities):
        return False

    claim_tokens = story_description_claim_tokens(plan)
    if len(claim_tokens) >= 2:
        matched = len(claim_tokens.intersection(article))
        required = min(2, len(claim_tokens))
        if matched < required:
            return False
    elif claim_tokens and not claim_tokens.issubset(article):
        return False

    return True


def validate_and_bind_timeline_sources(plan, verified_sources):
    """Bind each dated/factual timeline event to a verified article supporting it."""
    timeline = plan.get("timeline", [])
    if isinstance(timeline, dict):
        timeline = [timeline]
    if not isinstance(timeline, list) or not timeline:
        plan["timeline"] = []
        return []

    evidence = []
    for index, entry in enumerate(timeline[:20]):
        if not isinstance(entry, dict):
            raise PipelineError(
                "Story quality gate blocked: timeline contains a malformed event without a source record."
            )
        event = str(entry.get("event") or entry.get("description") or "").strip()
        event_date = str(entry.get("date") or entry.get("event_date") or "").strip()
        status = str(entry.get("status") or "unknown").strip().casefold()
        source_ids = entry.get("source_ids", [])
        if isinstance(source_ids, str):
            source_ids = [source_ids]
        if not isinstance(source_ids, list):
            source_ids = []

        # Undated unknown placeholders are not factual timeline claims.
        if not event and not event_date and status == "unknown":
            continue
        if not event:
            raise PipelineError(
                "Story quality gate blocked: a dated timeline item has no event description."
            )

        event_plan = {"topic": event, "title": event, "description": event}
        matching = []
        for source in verified_sources:
            event_score = source_relevance_score(event_plan, source)
            if event_score < 0.25:
                continue
            if not source_supports_story(plan, source):
                continue
            matching.append((event_score, source))

        if not matching:
            raise PipelineError(
                "Story quality gate blocked: timeline event '" + event[:100] +
                "' cannot be linked to any verified direct publisher article with matching evidence."
            )

        matching.sort(key=lambda pair: pair[0], reverse=True)
        bound_sources = [item for _, item in matching[:2]]
        if event_date:
            validate_timeline_date_against_sources(event_date, bound_sources, event)
        bound_ids = [str(item.get("source_id") or "").strip() for item in bound_sources]
        if not all(bound_ids):
            raise PipelineError(
                "Story quality gate blocked: a timeline event matched an article without a stable source ID."
            )

        # Replace discovery-only or stale source IDs with the verified publisher IDs.
        entry["source_ids"] = bound_ids
        evidence.append({
            "event": event,
            "date": event_date,
            "verified_source_ids": bound_ids,
            "verified_publisher_families": sorted({
                publisher_family_domain(item.get("publisher_domain") or urlparse(item.get("url", "")).netloc)
                for item in bound_sources
            }),
        })

    plan["timeline"] = timeline
    plan["timeline_evidence"] = evidence
    return evidence




def bing_news_item_record(item, label="Bing News story search"):
    """Convert Bing RSS into a discovery record, never final evidence by itself."""
    # Bing's RSS format can namespace News:Source, so find it by local XML name.
    source_node = next(
        (
            child for child in list(item)
            if str(child.tag).split("}")[-1].split(":")[-1].casefold() == "source"
        ),
        None,
    )
    publisher_name = (source_node.text or "").strip() if source_node is not None else ""
    publisher_home = ""
    if source_node is not None:
        publisher_home = next(
            (str(value).strip() for key, value in source_node.attrib.items()
             if str(key).split("}")[-1].casefold() == "url" and str(value).strip()),
            "",
        )
    raw_title = (item.findtext("title") or "").strip()
    if publisher_name and raw_title.casefold().endswith((" - " + publisher_name).casefold()):
        raw_title = raw_title[:-(len(publisher_name) + 3)].strip()
    url = (item.findtext("link") or "").strip()
    publisher_domain = _normalized_publisher_domain(publisher_home)
    if not publisher_domain:
        link_host = _normalized_publisher_domain(url)
        if link_host and not _is_news_aggregator_host(link_host):
            publisher_domain = link_host
    return {
        "title": raw_title[:220],
        "summary": "",
        "url": url,
        "date": (item.findtext("pubDate") or "")[:90],
        "source": publisher_name or publisher_domain or label,
        "publisher_name": publisher_name or publisher_domain,
        "publisher_home": publisher_home,
        "publisher_domain": publisher_domain,
        "source_feed": label,
        "link_type": "discovery_lead",
    }


class SearchResultAnchorParser(HTMLParser):
    """Extract title links from DuckDuckGo's lightweight HTML result page."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._active = False
        self._depth = 0
        self._href = ""
        self._text = []

    def handle_starttag(self, tag, attrs):
        values = {str(key).casefold(): value for key, value in attrs}
        if tag == "a" and not self._active:
            classes = set(str(values.get("class") or "").casefold().split())
            test_id = str(values.get("data-testid") or "").casefold()
            if "result__a" in classes or test_id == "result-title-a":
                self._active = True
                self._depth = 1
                self._href = str(values.get("href") or "")
                self._text = []
        elif self._active:
            self._depth += 1

    def handle_endtag(self, tag):
        if not self._active:
            return
        self._depth -= 1
        if self._depth <= 0:
            title = re.sub(r"\s+", " ", " ".join(self._text)).strip()
            if self._href and title:
                self.results.append({"href": self._href, "title": title})
            self._active = False
            self._depth = 0
            self._href = ""
            self._text = []

    def handle_data(self, data):
        if self._active:
            self._text.append(data)


def duckduckgo_search_records(page_text, label="DuckDuckGo web search"):
    """Turn search-result anchors into discovery links, never trusted article evidence."""
    parser = SearchResultAnchorParser()
    parser.feed(str(page_text or "")[:2_000_000])
    records = []
    for result in parser.results[:25]:
        href = html_unescape(str(result.get("href") or "")).strip()
        if not href:
            continue
        absolute = urljoin("https://html.duckduckgo.com", href)
        parsed = urlparse(absolute)
        candidate = absolute
        if _is_news_aggregator_host(parsed.hostname or ""):
            query = parse_qs(parsed.query)
            candidate = ""
            for key in ("uddg", "url", "target", "u"):
                values = query.get(key) or []
                for value in values:
                    decoded = unquote(value)
                    if decoded.startswith(("http://", "https://")):
                        candidate = decoded
                        break
                if candidate:
                    break
        candidate = candidate.strip()
        candidate_host = _normalized_publisher_domain(candidate)
        if not candidate or not candidate_host or _is_news_aggregator_host(candidate_host):
            continue
        records.append({
            "title": str(result["title"])[:220],
            "summary": "",
            "url": candidate,
            "date": "",
            "source": candidate_host,
            "publisher_name": candidate_host,
            "publisher_domain": candidate_host,
            "source_feed": label,
            "link_type": "discovery_lead",
        })
    return records

def research_story_sources(plan, existing_items, max_phrases=6):
    """Search GDELT, Google/Bing RSS, and direct-link web results; verify publisher pages."""
    targeted = []
    phrases = story_search_phrases(plan, existing_items)[:max(1, min(6, int(max_phrases)))]
    gdelt_rate_limited = False
    gdelt_queries = 0
    google_items = 0
    bing_items = 0
    duckduckgo_items = 0

    for phrase in phrases:
        # GDELT is a useful free source but can rate-limit bursts. After the first
        # HTTP 429, skip further calls in this run and continue with other providers.
        if not gdelt_rate_limited:
            try:
                response = http.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={
                        "query": phrase,
                        "mode": "ArtList",
                        "format": "json",
                        "maxrecords": "40",
                        "sort": "HybridRel",
                        "timespan": "90d",
                    },
                    timeout=15,
                )
                gdelt_queries += 1
                if response.status_code == 429:
                    gdelt_rate_limited = True
                    log("GDELT returned HTTP 429; pausing GDELT for this run and continuing with other search providers.")
                else:
                    response.raise_for_status()
                    for article in response.json().get("articles", []):
                        if not article.get("title") or not article.get("url"):
                            continue
                        article_url = str(article["url"])
                        domain = str(article.get("domain") or urlparse(article_url).netloc).lower().removeprefix("www.")
                        targeted.append({
                            "title": str(article.get("title", ""))[:220],
                            "summary": "",
                            "url": article_url,
                            "date": "",
                            "discovered_at": str(article.get("seendate", "")),
                            "source": domain,
                            "publisher_name": domain,
                            "publisher_domain": domain,
                            "source_feed": "GDELT story search",
                            "link_type": "discovery_lead",
                        })
            except Exception as exc:
                if getattr(getattr(exc, "response", None), "status_code", None) == 429:
                    gdelt_rate_limited = True
                    log("GDELT returned HTTP 429; pausing GDELT for this run and continuing with other search providers.")
                else:
                    log("Targeted GDELT search unavailable for " + phrase[:60] + ": " + str(exc)[:130])

        # Google News RSS is a discovery source. Use natural unquoted queries so
        # minor wording differences do not suppress otherwise relevant articles.
        for region in ("GB", "US", "IN"):
            try:
                request = requests.Request(
                    "GET",
                    "https://news.google.com/rss/search",
                    params={
                        "q": phrase,
                        "hl": "en",
                        "gl": region,
                        "ceid": region + ":en",
                    },
                ).prepare()
                response = http.get(request.url, timeout=10)
                response.raise_for_status()
                root = ET.fromstring(response.content)
                for item in root.findall(".//item")[:10]:
                    if item.findtext("title") and item.findtext("link"):
                        record = google_news_item_record(item, region, "Story verification")
                        record["source_feed"] = "Google News targeted story search"
                        targeted.append(record)
                        google_items += 1
            except Exception as exc:
                log(region + " targeted Google News unavailable: " + str(exc)[:120])

        # Bing News is a second RSS discovery route; publisher metadata is parsed
        # separately so a Bing redirect can never become the final publisher.
        try:
            request = requests.Request(
                "GET",
                "https://www.bing.com/news/search",
                params={"q": phrase, "format": "rss", "setmkt": "en-US"},
            ).prepare()
            response = http.get(request.url, timeout=10)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for item in root.findall(".//item")[:12]:
                if item.findtext("title") and item.findtext("link"):
                    targeted.append(bing_news_item_record(item))
                    bing_items += 1
        except Exception as exc:
            log("Bing News RSS unavailable for " + phrase[:60] + ": " + str(exc)[:120])

        # DuckDuckGo's lightweight HTML results expose outbound publisher URLs
        # directly. These remain discovery leads until the final page is fetched.
        try:
            request = requests.Request(
                "GET",
                "https://html.duckduckgo.com/html/",
                params={"q": phrase},
            ).prepare()
            response = http.get(
                request.url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ViolinPrinceAutopilot/0.2)"},
                timeout=10,
            )
            response.raise_for_status()
            records = duckduckgo_search_records(response.text)
            targeted.extend(records[:18])
            duckduckgo_items += len(records[:18])
        except Exception as exc:
            log("DuckDuckGo HTML search unavailable for " + phrase[:60] + ": " + str(exc)[:120])

    unique = {}
    for item in targeted:
        key = source_key(item.get("url")) or str(item.get("url") or "")
        if key:
            unique.setdefault(key, item)

    # Rank by overlap with this selected story before making network requests.
    # This avoids spending many timeouts on unrelated search-result pages.
    ranked = sorted(
        unique.values(),
        key=lambda item: source_relevance_score(plan, item),
        reverse=True,
    )
    targeted = enrich_source_evidence(ranked[:180])

    combined = []
    seen = set()
    for item in list(targeted) + list(existing_items):
        key = source_key(item.get("url")) or str(item.get("url") or "")
        if key and key not in seen:
            seen.add(key)
            combined.append(item)
    WORK.mkdir(exist_ok=True)
    (WORK / "story_research.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    direct_count = sum(1 for item in combined if is_direct_publisher_article(item))
    log(
        f"Story search summary: {len(phrases)} queries, {gdelt_queries} GDELT attempts"
        f"{' (rate-limited)' if gdelt_rate_limited else ''}, {google_items} Google News leads, "
        f"{bing_items} Bing News leads, {duckduckgo_items} DuckDuckGo links; "
        f"{direct_count} direct publisher pages from {len(combined)} records."
    )
    return combined



def source_content_similarity(left, right):
    """Detect syndicated copies even when publishers add boilerplate or trim the article."""
    left_words = re.findall(r"[a-z0-9]{3,}", str(left.get("evidence_text", "")).casefold())
    right_words = re.findall(r"[a-z0-9]{3,}", str(right.get("evidence_text", "")).casefold())
    if min(len(left_words), len(right_words)) < 30:
        return 0.0

    left_tokens = source_tokens(left.get("evidence_text", ""))
    right_tokens = source_tokens(right.get("evidence_text", ""))
    if min(len(left_tokens), len(right_tokens)) < 30:
        return 0.0

    shared_tokens = len(left_tokens.intersection(right_tokens))
    token_union = len(left_tokens.union(right_tokens))
    token_jaccard = shared_tokens / token_union if token_union else 0.0
    token_containment = shared_tokens / min(len(left_tokens), len(right_tokens))

    def word_shingles(words, width=5):
        return {
            tuple(words[index:index + width])
            for index in range(max(0, len(words) - width + 1))
        }

    left_shingles = word_shingles(left_words)
    right_shingles = word_shingles(right_words)
    shared_shingles = len(left_shingles.intersection(right_shingles))
    shingle_containment = (
        shared_shingles / min(len(left_shingles), len(right_shingles))
        if left_shingles and right_shingles else 0.0
    )

    # High containment is strong evidence of the same article body, even if
    # one publisher adds a credit notice or truncates the final paragraphs.
    return max(
        token_jaccard,
        token_containment if token_containment >= 0.82 else 0.0,
        shingle_containment if shingle_containment >= 0.72 else 0.0,
    )


_STORY_GROUP_GENERIC_TERMS = {
    "ai", "about", "announced", "announces", "announcement", "artist", "artists",
    "artificial", "breaking", "computer", "computers", "culture", "digital",
    "discovery", "entertainment", "feature", "features", "future", "global",
    "intelligence", "latest", "machine", "machines", "music", "musical", "new",
    "news", "performance", "performances", "report", "reports", "research",
    "researcher", "researchers", "science", "scientific", "show", "shows",
    "study", "technology", "today", "trend", "trends", "update", "updates",
    "violin", "world",
}


def _story_group_tokens(value):
    return {
        token for token in source_tokens(value)
        if token not in _STORY_GROUP_GENERIC_TERMS
    }


def _story_article_anchors(item):
    title = str(item.get("title") or "")
    anchors = story_entity_anchor_groups({"topic": title, "title": title})
    return {
        frozenset(anchor) for anchor in anchors
        if anchor and not set(anchor).issubset(_STORY_GROUP_GENERIC_TERMS)
    }


def story_articles_cover_same_subject(left, right):
    """Strictly pair readable articles about the same subject, not merely the same genre."""
    left_family = publisher_family_domain(
        left.get("publisher_domain") or urlparse(left.get("url", "")).netloc
    )
    right_family = publisher_family_domain(
        right.get("publisher_domain") or urlparse(right.get("url", "")).netloc
    )
    if not left_family or not right_family or left_family == right_family:
        return False
    if source_content_similarity(left, right) >= 0.82:
        return False

    left_title = _story_group_tokens(left.get("title", ""))
    right_title = _story_group_tokens(right.get("title", ""))
    shared_title = left_title.intersection(right_title)
    title_overlap = len(shared_title) / max(1, min(len(left_title), len(right_title)))

    left_body = _story_group_tokens(left.get("evidence_text", ""))
    right_body = _story_group_tokens(right.get("evidence_text", ""))
    shared_body = left_body.intersection(right_body)
    body_overlap = len(shared_body) / max(1, min(len(left_body), len(right_body)))

    shared_anchors = _story_article_anchors(left).intersection(_story_article_anchors(right))
    if shared_anchors and len(shared_body) >= 3 and body_overlap >= 0.08:
        return True
    if len(shared_title) >= 2 and title_overlap >= 0.30:
        return True
    if len(shared_body) >= 6 and body_overlap >= 0.18 and len(shared_title) >= 1:
        return True
    return False


def build_verified_story_groups(research_items, minimum_publishers=2, maximum_groups=8, as_of=None):
    """Group specific, readable publisher articles with independent reporting and dated evidence."""
    minimum_publishers = max(2, int(minimum_publishers))
    compact = planner_research_items(research_items)
    candidates = []
    for item in compact:
        eligible, _reason, freshness = _story_article_eligibility(item, as_of=as_of)
        if not eligible:
            continue
        domain = _normalized_publisher_domain(
            item.get("publisher_domain") or urlparse(item.get("url", "")).netloc
        )
        family = publisher_family_domain(domain)
        key = source_key(item.get("url"))
        source_id = str(item.get("source_id") or "").strip()
        if not domain or not family or not key or not source_id:
            continue
        candidate = dict(item)
        candidate.update(freshness)
        candidate["publisher_domain"] = domain
        candidate["publisher_family"] = family
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            len(str(item.get("evidence_text") or "")),
            len(str(item.get("title") or "")),
        ),
        reverse=True,
    )

    groups = []
    for seed in candidates:
        related = [seed]
        related.extend(
            item for item in candidates
            if item is not seed and story_articles_cover_same_subject(seed, item)
        )
        selected = []
        families = set()
        for item in related:
            family = str(item.get("publisher_family") or "")
            if not family or family in families:
                continue
            if any(source_content_similarity(item, chosen) >= 0.82 for chosen in selected):
                continue
            selected.append(item)
            families.add(family)
            if len(selected) >= 4:
                break

        if len(families) < minimum_publishers:
            continue

        source_ids = [str(item["source_id"]) for item in selected]
        group_identity = "|".join(sorted(source_key(item.get("url")) for item in selected))
        group_id = "STORY_" + hashlib.sha256(group_identity.encode("utf-8")).hexdigest()[:12].upper()
        groups.append({
            "group_id": group_id,
            "topic_hint": str(seed.get("title") or "")[:220],
            "source_ids": source_ids,
            "publisher_families": sorted(families),
            "independent_publisher_count": len(families),
            "sources": selected,
            "evidence_characters": sum(len(str(item.get("evidence_text") or "")) for item in selected),
            "preferred_source_count": sum(1 for item in selected if item.get("freshness_status") == "preferred"),
            "oldest_source_age_hours": max(float(item.get("age_hours") or 0) for item in selected),
            "freshness_policy": {"preferred_hours": FRESHNESS_PREFERRED_HOURS, "maximum_age_hours": FRESHNESS_MAX_AGE_HOURS},
        })

    # Several seed articles can describe the same story. Keep one strongest
    # group so the editorial planner sees distinct candidates, not duplicates.
    deduplicated = []
    for group in sorted(
        groups,
        key=lambda value: (
            value.get("preferred_source_count", 0),
            -value.get("oldest_source_age_hours", FRESHNESS_MAX_AGE_HOURS),
            value["independent_publisher_count"],
            len(value["source_ids"]),
            value["evidence_characters"],
        ),
        reverse=True,
    ):
        ids = set(group["source_ids"])
        if any(
            len(ids.intersection(set(existing["source_ids"])))
            / max(1, len(ids.union(set(existing["source_ids"])))) >= 0.55
            for existing in deduplicated
        ):
            continue
        deduplicated.append(group)
        if len(deduplicated) >= max(1, int(maximum_groups)):
            break
    return deduplicated


def discover_source_first_story_groups(research_items, max_seed_queries=2, max_phrases=3, as_of=None):
    """Find fresh corroborated story groups before asking the editorial planner to choose a topic."""
    pooled = [dict(item) for item in research_items if isinstance(item, dict)]
    groups = build_verified_story_groups(pooled, as_of=as_of)
    represented_urls = {
        source_key(source.get("url"))
        for group in groups for source in group.get("sources", [])
    }

    music_terms = {
        "violin", "orchestra", "instrument", "music", "classical", "composer",
        "film", "soundtrack", "concert", "festival", "piano", "opera",
        "performer", "symphony", "musician", "acoustic", "conductor",
    }
    seed_candidates = []
    seen_titles = set()
    for item in pooled:
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        url = str(item.get("url") or "").strip()
        key = source_key(url)
        if not title or not url or not key or title.casefold() in seen_titles:
            continue
        seen_titles.add(title.casefold())
        topical = len(_story_group_tokens(title).intersection(music_terms))
        direct = 1 if is_direct_publisher_article(item) else 0
        seed_candidates.append((topical * 3 + direct, len(title), item))

    seed_candidates.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    queried = 0
    for _score, _length, seed in seed_candidates:
        seed_url = source_key(seed.get("url"))
        if seed_url in represented_urls:
            continue
        provisional_title = str(seed.get("title") or "").strip()
        provisional_plan = {
            "topic": provisional_title,
            "title": provisional_title,
            "description": provisional_title,
        }
        expanded = research_story_sources(
            provisional_plan,
            pooled,
            max_phrases=max_phrases,
        )
        queried += 1
        seen = {source_key(item.get("url")) for item in pooled}
        pooled.extend(
            item for item in expanded
            if source_key(item.get("url")) and source_key(item.get("url")) not in seen
        )
        groups = build_verified_story_groups(pooled, as_of=as_of)
        represented_urls = {
            source_key(source.get("url"))
            for group in groups for source in group.get("sources", [])
        }
        log(
            f"Source-first discovery checked article seed {queried}/{max_seed_queries}; "
            f"{len(groups)} corroborated story group(s) currently qualify."
        )
        if queried >= max(0, int(max_seed_queries)) or len(groups) >= 6:
            break

    WORK.mkdir(exist_ok=True)
    diagnostics = {
        "schema_version": 1,
        "research_record_count": len(pooled),
        "google_news_wrappers_seen": sum(1 for item in pooled if _google_news_article_id(item.get("url")) or _google_news_article_id(item.get("source_url_original"))),
        "google_news_resolved_count": sum(1 for item in pooled if item.get("publisher_resolution_status") == "resolved_via_google_news_batchexecute"),
        "google_news_unresolved_count": sum(1 for item in pooled if item.get("publisher_resolution_status") == "unresolved_google_news"),
        "publisher_resolution_failures": sum(1 for item in pooled if item.get("publisher_resolution_status") in ("fetch_failed", "unresolved_google_news")),
        "verified_article_count": sum(
            1 for item in planner_research_items(pooled)
            if _story_article_eligibility(item, as_of=as_of)[0]
        ),
        "as_of_utc": (
            parse_publication_timestamp(as_of)[0].isoformat().replace("+00:00", "Z")
            if parse_publication_timestamp(as_of)[0] else datetime.now(timezone.utc).isoformat()
        ),
        "freshness_policy": {
            "preferred_hours": FRESHNESS_PREFERRED_HOURS,
            "maximum_age_hours": FRESHNESS_MAX_AGE_HOURS,
            "rule": "Prefer publication within 50 hours; accept verified publisher articles up to 168 hours old.",
        },
        "article_audit": [
            {
                "source_id": item.get("source_id"),
                "title": item.get("title"),
                "publisher_domain": item.get("publisher_domain"),
                "url": item.get("url"),
                "source_url_original": item.get("source_url_original"),
                "publisher_resolution_status": item.get("publisher_resolution_status"),
                "publisher_resolution_error": item.get("publisher_resolution_error"),
                "article_page_verified": item.get("article_page_verified") is True,
                "publication_date": article_freshness(item, as_of=as_of).get("published_at_utc"),
                "age_hours": article_freshness(item, as_of=as_of).get("age_hours"),
                "freshness_status": article_freshness(item, as_of=as_of).get("freshness_status"),
                "eligible": _story_article_eligibility(item, as_of=as_of)[0],
                "exclusion_reason": _story_article_eligibility(item, as_of=as_of)[1],
            }
            for item in planner_research_items(pooled)
        ],
        "grouping_rule": (
            "Specific readable publisher article pages with a known publication date no older than seven days; "
            "prefer <=50 hours; at least two independent publisher families; "
            "syndicated/near-identical bodies and directory pages excluded."
        ),
        "groups": [
            {
                "group_id": group["group_id"],
                "topic_hint": group["topic_hint"],
                "source_ids": group["source_ids"],
                "publisher_families": group["publisher_families"],
                "independent_publisher_count": group["independent_publisher_count"],
                "sources": [
                    {
                        "source_id": source.get("source_id"),
                        "title": source.get("title"),
                        "publisher_name": source.get("publisher_name"),
                        "publisher_domain": source.get("publisher_domain"),
                        "url": source.get("url"),
                        "source_url_original": source.get("source_url_original"),
                        "publisher_resolution_status": source.get("publisher_resolution_status"),
                        "published_at_utc": source.get("published_at_utc"),
                        "age_hours": source.get("age_hours"),
                        "freshness_status": source.get("freshness_status"),
                        "article_page_verified": source.get("article_page_verified") is True,
                        "evidence_excerpt": str(source.get("evidence_text") or "")[:1200],
                    }
                    for source in group["sources"]
                ],
            }
            for group in groups
        ],
    }
    (WORK / "story_candidates.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(
        f"Evidence-first selection produced {len(groups)} eligible story group(s) "
        f"from {diagnostics['verified_article_count']} readable direct publisher article(s)."
    )
    return groups


_NARRATION_EVIDENCE_FILLER = {
    "highly", "now", "currently", "today", "really", "very",
}
_NARRATION_ASSERTION_MODIFIERS = {
    "breakthrough", "exceptionally", "entire", "fundamentally",
    "gamechanging", "groundbreaking", "incredibly", "revolutionary",
    "sophisticated", "transformative", "transforming", "unprecedented",
    "vastly", "worldchanging", "soul", "feel", "feels", "feeling", "understand", "understands", "understanding", "conscious", "consciousness",
}


def _normalized_narration_claim_tokens(value):
    """Keep distinctive claim words while normalizing simple plurals."""
    tokens = source_tokens(value) - _GENERIC_ENTITY_WORDS - _NARRATION_EVIDENCE_FILLER
    normalized = set()
    for token in tokens:
        if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        normalized.add(token)
    return normalized


def validate_narration_against_sources(plan, verified_sources):
    """Require each factual narration sentence to match a verified article body."""
    sentences = narration_sentences(plan.get("narration_script", ""))
    if len(sentences) != 4:
        raise PipelineError(
            "Story quality gate blocked: narration evidence check requires exactly four sentences."
        )

    evidence_records = []
    issues = []
    for sentence_number, sentence in enumerate(sentences, start=1):
        # The opening is a curiosity hook, not a factual assertion.
        if sentence_number == 1:
            continue

        claim_tokens = _normalized_narration_claim_tokens(sentence)
        if not claim_tokens:
            issues.append(
                f"narration sentence {sentence_number} contains no verifiable factual detail"
            )
            continue

        sentence_tokens = source_tokens(sentence)
        modifiers = sentence_tokens.intersection(_NARRATION_ASSERTION_MODIFIERS)
        candidates = []
        for source in verified_sources:
            source_text = " ".join(
                str(source.get(key, ""))
                for key in ("title", "evidence_text")
            )
            source_terms = _normalized_narration_claim_tokens(source_text)
            source_words = source_tokens(source_text)
            matched = claim_tokens.intersection(source_terms)
            unsupported_modifiers = sorted(
                modifier for modifier in modifiers if modifier not in source_words
            )
            coverage = len(matched) / len(claim_tokens)
            candidates.append((
                not unsupported_modifiers,
                len(matched),
                coverage,
                source,
                matched,
                unsupported_modifiers,
            ))

        if not candidates:
            issues.append(
                f"narration sentence {sentence_number} has no verified publisher article to support it"
            )
            continue

        candidates.sort(key=lambda value: (value[0], value[1], value[2]), reverse=True)
        (
            _modifiers_supported,
            matched_count,
            coverage,
            source,
            matched_terms,
            unsupported_modifiers,
        ) = candidates[0]
        required_matches = min(2, len(claim_tokens))
        if (
            matched_count < required_matches
            or coverage < 0.30
            or unsupported_modifiers
        ):
            detail = f"{matched_count}/{len(claim_tokens)} distinctive terms matched"
            if matched_terms:
                detail += "; matched: " + ", ".join(sorted(matched_terms))
            if unsupported_modifiers:
                detail += "; unsupported emphasis: " + ", ".join(unsupported_modifiers)
            issues.append(
                f"narration sentence {sentence_number} is not sufficiently supported "
                f"by any verified publisher article ({detail})"
            )
            continue

        evidence_records.append({
            "sentence_number": sentence_number,
            "sentence": sentence,
            "source_id": str(source.get("source_id") or ""),
            "publisher_name": str(source.get("publisher_name") or source.get("publisher_domain") or ""),
            "publisher_domain": str(source.get("publisher_domain") or ""),
            "matched_terms": sorted(matched_terms),
            "claim_terms": sorted(claim_tokens),
            "coverage": round(coverage, 3),
        })

    if issues:
        raise PipelineError("Story quality gate blocked: " + "; ".join(issues))

    plan["narration_evidence"] = evidence_records
    return evidence_records


def select_verified_story_sources(
    plan, research_items, minimum_sources=2, allowed_source_ids=None, as_of=None
):
    """Select only eligible articles from the planner's immutable source group."""
    compact = planner_research_items(research_items)
    allowed_ids = (
        {str(value).strip() for value in allowed_source_ids if str(value).strip()}
        if allowed_source_ids is not None else None
    )
    ranked = []
    for item in compact:
        source_id = str(item.get("source_id") or "").strip()
        if allowed_ids is not None and source_id not in allowed_ids:
            continue
        eligible, _reason, freshness = _story_article_eligibility(item, as_of=as_of)
        if not eligible or not source_supports_story(plan, item):
            continue
        score = source_relevance_score(plan, item)
        ranked.append((
            score,
            freshness.get("freshness_status") == "preferred",
            -float(freshness.get("age_hours") or 0),
            item,
        ))
    ranked.sort(key=lambda pair: (pair[0], pair[1], pair[2]), reverse=True)

    selected = []
    publisher_families = set()
    seen_urls = set()
    for score, _preferred, _age_rank, item in ranked:
        url = str(item.get("url") or "")
        domain = str(item.get("publisher_domain") or urlparse(url).netloc).lower().removeprefix("www.")
        family = publisher_family_domain(domain)
        key = source_key(url)
        if not domain or not family or not key or family in publisher_families or key in seen_urls:
            continue

        duplicate_of = next(
            (
                chosen for chosen in selected
                if source_content_similarity(item, chosen) >= 0.82
            ),
            None,
        )
        if duplicate_of:
            log(
                "Excluded copied/syndicated source content from "
                f"{domain}; it substantially duplicates the article from "
                f"{duplicate_of.get('publisher_domain') or urlparse(duplicate_of.get('url', '')).netloc}."
            )
            continue

        selected.append(item)
        publisher_families.add(family)
        seen_urls.add(key)
        if len(selected) >= 4:
            break

    if len(selected) < minimum_sources:
        available = ", ".join(sorted(publisher_families)) or "none"
        scope_note = " inside the selected story group" if allowed_ids is not None else ""
        raise PipelineError(
            f"Story quality gate blocked: only {len(selected)} relevant direct publisher source(s){scope_note} "
            f"inside the seven-day publication window were found; at least {minimum_sources} independent publishers are required. "
            f"Verified domains: {available}. No visuals were generated."
        )
    if allowed_ids is not None and not {
        str(item.get("source_id") or "") for item in selected
    }.issubset(allowed_ids):
        raise PipelineError("Story quality gate blocked: final citations drifted outside the selected source group.")
    return selected


def prepare_story_with_source_recovery(items, recent=None, seo_context=None, max_candidates=2, as_of=None):
    """Select only from article groups already corroborated by independent publishers."""
    story_groups = discover_source_first_story_groups(items, as_of=as_of)
    if not story_groups:
        raise PipelineError(
            "Evidence-first research found no story group with at least two independent, "
            "readable direct publisher articles. No topic was selected and no narration or visuals were created."
        )

    excluded_group_ids = []
    failures = []
    candidate_limit = min(max(1, int(max_candidates)), len(story_groups))
    for candidate_number in range(1, candidate_limit + 1):
        selected_group_id = ""
        topic = "unselected source-first candidate"
        try:
            plan = make_plan(
                items,
                recent=list(recent or []) + [entry.split(":", 1)[0] for entry in failures],
                seo_context=seo_context,
                story_groups=story_groups,
                excluded_group_ids=excluded_group_ids,
            )
            selected_group_id = str((plan.get("source_group") or {}).get("group_id") or "")
            selected_group = next(
                (group for group in story_groups if group.get("group_id") == selected_group_id),
                None,
            )
            if not selected_group:
                raise PipelineError(
                    "Story quality gate blocked: selected plan is not attached to a verified source group."
                )
            topic = str(plan.get("topic") or plan.get("title") or selected_group.get("topic_hint") or "untitled story").strip()

            # Topic-specific search is now corroboration and enrichment. The story
            # already had two independent readable publisher sources before planning.
            story_items = research_story_sources(
                plan,
                selected_group["sources"],
                max_phrases=4,
            )
            verified_sources = select_verified_story_sources(
                plan,
                story_items,
                minimum_sources=2,
                allowed_source_ids=selected_group.get("source_ids", []),
                as_of=as_of,
            )
            try:
                validate_narration_against_sources(plan, verified_sources)
            except PipelineError as evidence_error:
                sentence_numbers = sorted({
                    int(value) for value in re.findall(
                        r"narration sentence (\d+)", str(evidence_error)
                    )
                    if 2 <= int(value) <= 4
                })
                if not sentence_numbers:
                    raise

                sentence_indices = [number - 1 for number in sentence_numbers]
                log(
                    "Narration evidence check found unsupported sentence(s) "
                    + ", ".join(str(number) for number in sentence_numbers)
                    + "; correcting only those sentences from verified publisher articles."
                )
                try:
                    compose_narration(
                        plan,
                        verified_sources,
                        evidence_sources=verified_sources,
                        force_sentence_indices=sentence_indices,
                    )
                    validate_narration_against_sources(plan, verified_sources)
                except PipelineError as repair_error:
                    raise PipelineError(
                        "Story quality gate blocked: narration evidence repair did not pass: "
                        + str(repair_error)
                    ) from repair_error

            validate_and_bind_timeline_sources(plan, verified_sources)
            verified_ids = [str(source.get("source_id") or "") for source in verified_sources]
            if not set(verified_ids).issubset(set(selected_group.get("source_ids", []))):
                raise PipelineError(
                    "Story quality gate blocked: final verified citations do not match the selected source group."
                )
            if len({
                publisher_family_domain(source.get("publisher_domain") or urlparse(source.get("url", "")).netloc)
                for source in verified_sources
            }) < 2:
                raise PipelineError(
                    "Story quality gate blocked: final citations do not retain two independent publisher families."
                )
            plan["source_group"]["verified_source_ids"] = verified_ids
            log(
                "Selected source-first story group " + selected_group_id + " with "
                + str(len(verified_sources)) + " independently verified publisher articles."
            )
            return plan, story_items, verified_sources
        except PipelineError as exc:
            message = str(exc)
            if not message.startswith("Story quality gate blocked:"):
                raise
            failures.append(topic + ": " + message)
            if selected_group_id:
                excluded_group_ids.append(selected_group_id)
            if candidate_number < candidate_limit and selected_group_id:
                log(
                    f"Source-first story group {candidate_number}/{candidate_limit} failed final claim/date "
                    "verification. Excluding that group and asking the planner to choose another eligible group."
                )
                continue
            details = " | ".join(failures)
            raise PipelineError(
                f"Evidence-first selection checked {candidate_number} eligible story group(s), "
                "but none passed final story verification. " + details
            ) from exc
    raise PipelineError("Evidence-first story selection ended without a verified candidate.")

_MONTHS = {
    name.casefold(): index for index, name in enumerate(
        ("January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"), start=1
    )
}


def parse_story_date(value):
    """Parse ISO or common English publication/event-date formats to a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    patterns = (
        r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>20\d{2})\b",
        r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<year>20\d{2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text_value, flags=re.IGNORECASE)
        if match:
            try:
                month = _MONTHS[match.group("month").casefold()]
                return date(int(match.group("year")), month, int(match.group("day")))
            except (ValueError, KeyError):
                return None
    return None




def _source_event_date_claims(text_value):
    """Extract explicit month/day/year claims from article prose for timeline cross-checks."""
    claims = []
    months = (
        "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        "Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
    )
    month_to_number = {
        name[:3].casefold(): index for index, name in enumerate(
            ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"), start=1
        )
    }
    pattern = (
        r"\b(?P<month>" + months + r")\.?\s+(?P<start>\d{1,2})"
        r"(?:st|nd|rd|th)?(?:\s*(?:[-–—]|to)\s*(?P<end>\d{1,2})(?:st|nd|rd|th)?)?"
        r"\s*,?\s+(?P<year>20\d{2})\b"
    )
    for match in re.finditer(pattern, str(text_value or ""), flags=re.IGNORECASE):
        month = month_to_number.get(match.group("month")[:3].casefold())
        if month:
            try:
                start, end = int(match.group("start")), int(match.group("end") or match.group("start"))
                claims.append({
                    "year": int(match.group("year")), "month": month,
                    "start_day": min(start, end), "end_day": max(start, end),
                    "text": match.group(0),
                })
            except ValueError:
                pass
    for match in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", str(text_value or "")):
        try:
            year, month, day = map(int, match.groups())
            date(year, month, day)
            claims.append({"year": year, "month": month, "start_day": day, "end_day": day, "text": match.group(0)})
        except ValueError:
            pass
    return claims


def validate_timeline_date_against_sources(event_date, sources, event):
    """Reject a model-generated year that conflicts with the selected articles."""
    parsed = parse_story_date(event_date)
    if parsed is None:
        return
    conflicts = []
    for source in sources:
        for claim in _source_event_date_claims(source.get("evidence_text") or ""):
            if (
                claim["month"] == parsed.month
                and claim["start_day"] <= parsed.day <= claim["end_day"]
                and claim["year"] != parsed.year
            ):
                conflicts.append((str(source.get("source_id") or ""), claim["text"]))
    if conflicts:
        details = "; ".join(f"{claim} in {source_id or 'a selected article'}" for source_id, claim in conflicts[:3])
        raise PipelineError(
            f"Story quality gate blocked: timeline date for '{str(event)[:80]}' conflicts with publisher date evidence: {details}."
        )


def validate_story_dates(plan, as_of=None):
    """Block dated event claims with stale or ambiguous chronology."""
    today = as_of or datetime.now(timezone.utc).date()
    if isinstance(today, datetime):
        today = today.date()
    script = " ".join(
        str(plan.get(key) or "")
        for key in ("title", "topic", "hook", "description", "narration_script")
    )
    patterns = (
        r"\b20\d{2}-\d{2}-\d{2}\b",
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+20\d{2}\b",
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}\b",
    )
    issues = []
    checked_dates = []
    for pattern in patterns:
        for match in re.finditer(pattern, script, flags=re.IGNORECASE):
            parsed = parse_story_date(match.group(0))
            if not parsed:
                continue
            checked_dates.append({"text": match.group(0), "date": parsed.isoformat()})
            sentence_start = max(
                script.rfind(".", 0, match.start()),
                script.rfind("!", 0, match.start()),
                script.rfind("?", 0, match.start()),
            ) + 1
            preceding = script[sentence_start:match.start()]
            future_claim = re.search(
                r"\b(?:will|upcoming|next|set\s+to|scheduled\s+to|due\s+to|expected\s+to|"
                r"is\s+going\s+to|are\s+going\s+to|is\s+due\s+to)\b",
                preceding,
                flags=re.IGNORECASE,
            )
            if parsed <= today and future_claim:
                issues.append(
                    f"Past event date {parsed.isoformat()} is described with future wording: "
                    f"{match.group(0)}."
                )

    timeline = plan.get("timeline", [])
    if isinstance(timeline, dict):
        timeline = [timeline]
    timeline = timeline if isinstance(timeline, list) else []
    valid_future_event = False
    for entry in timeline[:20]:
        if isinstance(entry, dict):
            event_date = parse_story_date(entry.get("date") or entry.get("event_date"))
            status = str(entry.get("status") or "unknown").strip().casefold()
            if event_date and event_date > today and status in ("upcoming", "future", "scheduled", "not_yet_occurred"):
                valid_future_event = True

    future_event_claim = re.search(
        r"\b(?:will\s+(?:perform|compete|play|appear|take part|be crowned|be named|be announced|"
        r"take place|be held|debut|release|launch|open)|scheduled\s+to|set\s+to|due\s+to)\b",
        script,
        flags=re.IGNORECASE,
    )
    if future_event_claim and not valid_future_event:
        issues.append("Narration contains future event wording without a verified future-dated timeline entry.")

    for entry in timeline[:20]:
        if not isinstance(entry, dict):
            continue
        event_date = parse_story_date(entry.get("date") or entry.get("event_date"))
        status = str(entry.get("status") or "unknown").strip().casefold()
        event = str(entry.get("event") or entry.get("description") or "event").strip()[:100]
        if status in ("upcoming", "future", "scheduled", "not_yet_occurred"):
            if event_date is None:
                issues.append(f"Timeline marks '{event}' as upcoming but supplies no verifiable date.")
            elif event_date <= today:
                issues.append(
                    f"Timeline marks '{event}' as upcoming even though {event_date.isoformat()} has passed."
                )
        if status in ("completed", "complete", "past", "already_happened"):
            if event_date and event_date > today:
                issues.append(
                    f"Timeline marks '{event}' as completed even though {event_date.isoformat()} is in the future."
                )
        if status == "unknown" and event_date and event_date <= today:
            issues.append(
                f"Timeline event '{event}' has a past date ({event_date.isoformat()}) but its status is unknown."
            )
    return {
        "status": "blocked" if issues else "passed",
        "checked_on": today.isoformat(),
        "dates_found_in_story": checked_dates,
        "issues": issues,
    }


def build_story_quality_report(plan, selected_sources, date_check, as_of=None):
    """Create an auditable source/date report; human review remains mandatory."""
    domains = sorted({
        str(item.get("publisher_domain") or urlparse(item.get("url", "")).netloc).lower().removeprefix("www.")
        for item in selected_sources
    })
    publisher_families = sorted({
        publisher_family_domain(item.get("publisher_domain") or urlparse(item.get("url", "")).netloc)
        for item in selected_sources
    })
    direct_links = all(
        is_direct_publisher_article(item) and item.get("article_page_verified") is True
        for item in selected_sources
    )
    expected_claim_sentences = max(
        0, len(narration_sentences(plan.get("narration_script", ""))) - 1
    )
    narration_evidence = plan.get("narration_evidence", [])
    narration_evidence_passed = (
        isinstance(narration_evidence, list)
        and len(narration_evidence) == expected_claim_sentences
    )
    freshness_records = [
        {
            "source_id": str(item.get("source_id") or ""),
            "publisher_domain": str(item.get("publisher_domain") or ""),
            **article_freshness(item, as_of=as_of),
        }
        for item in selected_sources
    ]
    freshness_passed = (
        len(freshness_records) >= 2
        and all(
            item.get("freshness_status") in ("preferred", "acceptable")
            and item.get("age_hours") is not None
            and item.get("age_hours") <= FRESHNESS_MAX_AGE_HOURS
            for item in freshness_records
        )
    )
    freshness_report = {
        "status": "passed" if freshness_passed else "blocked",
        "as_of_utc": (
            parse_publication_timestamp(as_of)[0].isoformat().replace("+00:00", "Z")
            if parse_publication_timestamp(as_of)[0] else datetime.now(timezone.utc).isoformat()
        ),
        "preferred_hours": FRESHNESS_PREFERRED_HOURS,
        "maximum_age_hours": FRESHNESS_MAX_AGE_HOURS,
        "preferred_source_count": sum(1 for item in freshness_records if item.get("freshness_status") == "preferred"),
        "acceptable_older_source_count": sum(1 for item in freshness_records if item.get("freshness_status") == "acceptable"),
        "oldest_verified_source_age_hours": max(
            [float(item.get("age_hours") or 0) for item in freshness_records] or [0]
        ),
        "verified_sources": freshness_records,
        "rule": "Prefer articles published within 50 hours; accept verified article pages up to 168 hours old.",
    }
    passed = (
        len(selected_sources) >= 2
        and len(publisher_families) >= 2
        and direct_links
        and freshness_passed
        and date_check.get("status") == "passed"
        and narration_evidence_passed
    )
    return {
        "schema_version": 1,
        "status": "passed" if passed else "blocked",
        "narration_evidence_status": "passed" if narration_evidence_passed else "not_checked",
        "narration_claim_sentence_count": len(narration_evidence) if isinstance(narration_evidence, list) else 0,
        "narration_evidence": narration_evidence if isinstance(narration_evidence, list) else [],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "minimum_independent_publishers": 2,
        "verified_source_count": len(selected_sources),
        "publisher_domains": domains,
        "publisher_families": publisher_families,
        "independent_publisher_count": len(publisher_families),
        "freshness": freshness_report,
        "timeline_event_count": len(plan.get("timeline_evidence", [])),
        "timeline_events_have_verified_sources": (
            len(plan.get("timeline_evidence", [])) ==
            sum(1 for item in (plan.get("timeline", []) or [])
                if isinstance(item, dict) and (
                    item.get("event") or item.get("description") or item.get("date") or item.get("event_date")
                ))
        ),
        "direct_publisher_article_links": direct_links,
        "date_check": date_check,
        "human_review_required": True,
        "human_review_status": "awaiting_approval",
    }


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


def narration_sentences(script):
    """Split a short spoken script into sentence strings while retaining punctuation."""
    value = str(script or "").strip()
    if not value:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", value) if part.strip()]


def narration_word_count(value):
    """Count spoken word tokens consistently for the full script and each sentence."""
    return len(re.findall(r"\b[\w’'-]+\b", str(value or "")))


def narration_validation_error(script):
    """Enforce the actual short-form requirements, not arbitrary per-sentence quotas."""
    text_value = re.sub(r"\s+", " ", str(script or "")).strip()
    total_words = narration_word_count(text_value)
    if not 40 <= total_words <= 44:
        return f"it has {total_words} spoken words; the required range is 40–44"

    sentences = narration_sentences(text_value)
    if len(sentences) != 4:
        return f"it has {len(sentences)} sentences; exactly 4 are required"

    counts = [narration_word_count(sentence) for sentence in sentences]
    if not 5 <= counts[0] <= 8:
        return f"the opening hook has {counts[0]} words; 5–8 are required"

    for index, (sentence, count) in enumerate(zip(sentences, counts), start=1):
        if count > 12:
            return f"sentence {index} has {count} words; no sentence may exceed 12"
        if not sentence.endswith((".", "!", "?")):
            return f"sentence {index} is missing closing punctuation"

    return ""


def narration_sentence_budget(sentences, target_total=None):
    """Allocate a feasible, per-sentence word range from the actual draft."""
    values = [re.sub(r"\s+", " ", str(value or "")).strip() for value in list(sentences or [])[:4]]
    values.extend([""] * (4 - len(values)))
    limits = (8, 12, 12, 12)
    floors = (5, 5, 5, 5)
    actual_total = sum(narration_word_count(value) for value in values)
    if target_total is None:
        target_total = actual_total if 40 <= actual_total <= 44 else 42
    target_total = max(40, min(44, int(target_total)))

    counts = [
        min(limits[index], max(floors[index], narration_word_count(value)))
        for index, value in enumerate(values)
    ]
    priority = (1, 2, 3, 0)

    difference = target_total - sum(counts)
    body_priority = (1, 2, 3)
    hook_priority = (0,)
    while difference > 0:
        available = [index for index in body_priority if counts[index] < limits[index]]
        if not available:
            available = [index for index in hook_priority if counts[index] < limits[index]]
        if not available:
            raise PipelineError("Narration word allocation cannot reach the required minimum.")
        chosen = min(available, key=lambda index: (counts[index] / limits[index], body_priority.index(index) if index in body_priority else len(body_priority)))
        counts[chosen] += 1
        difference -= 1

    while difference < 0:
        available = [index for index in body_priority if counts[index] > floors[index]]
        if not available:
            available = [index for index in hook_priority if counts[index] > floors[index]]
        if not available:
            raise PipelineError("Narration word allocation cannot fit the required maximum.")
        chosen = max(available, key=lambda index: (counts[index] / limits[index], -(body_priority.index(index) if index in body_priority else len(body_priority))))
        counts[chosen] -= 1
        difference += 1

    maxima = list(counts)
    extra_capacity = 44 - target_total
    while extra_capacity > 0:
        available = [index for index in body_priority if maxima[index] < limits[index]]
        if not available:
            available = [index for index in hook_priority if maxima[index] < limits[index]]
        if not available:
            break
        chosen = min(available, key=lambda index: (maxima[index] / limits[index], body_priority.index(index) if index in body_priority else len(body_priority)))
        maxima[chosen] += 1
        extra_capacity -= 1

    return [
        {"min_words": counts[index], "max_words": maxima[index]}
        for index in range(4)
    ]


def _sentence_needs_correction(sentence, index, budget):
    """Check one independently generated sentence against its own hard limits."""
    value = re.sub(r"\s+", " ", str(sentence or "")).strip()
    parts = narration_sentences(value)
    count = narration_word_count(value)
    if len(parts) != 1:
        return True
    if not value.endswith((".", "!", "?")):
        return True
    if count < budget["min_words"] or count > budget["max_words"]:
        return True
    if index == 0 and not 5 <= count <= 8:
        return True
    if index > 0 and count > 12:
        return True
    return False


def _plan_sentence_fields(plan):
    """Read the new four-field plan format, with a safe legacy-script fallback."""
    raw = plan.get("narration_sentences")
    if isinstance(raw, dict):
        values = [raw.get("sentence_" + str(index), "") for index in range(1, 5)]
    elif isinstance(raw, list):
        values = raw
    else:
        values = narration_sentences(plan.get("narration_script", ""))
    values = [re.sub(r"\s+", " ", str(value or "")).strip() for value in values]
    if len(values) > 4:
        values = values[:3] + [" ".join(values[3:])]
    values.extend([""] * (4 - len(values)))
    return values


def _parse_narration_tool_response(result, expected_fields):
    """Extract word arrays from the forced structured narration function call."""
    candidates = []
    if isinstance(result, dict):
        candidates.append(result)
        if isinstance(result.get("response"), dict):
            candidates.append(result["response"])

    def decode_arguments(arguments):
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return None
        if isinstance(arguments, dict):
            return {key: arguments.get(key) for key in expected_fields}
        return None

    for candidate in candidates:
        choices = candidate.get("choices", [])
        if isinstance(choices, list):
            for choice in choices:
                message = choice.get("message", {}) if isinstance(choice, dict) else {}
                if not isinstance(message, dict):
                    continue
                for call in message.get("tool_calls", []) or []:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    if not isinstance(function, dict):
                        continue
                    if function.get("name") != "submit_narration_sentence_corrections":
                        continue
                    parsed = decode_arguments(function.get("arguments"))
                    if parsed is not None:
                        return parsed

                function_call = message.get("function_call")
                if (
                    isinstance(function_call, dict)
                    and function_call.get("name") == "submit_narration_sentence_corrections"
                ):
                    parsed = decode_arguments(function_call.get("arguments"))
                    if parsed is not None:
                        return parsed

        response = candidate.get("response")
        if isinstance(response, str):
            parsed = decode_arguments(response)
            if parsed is not None:
                return parsed

    raise PipelineError("Workers AI did not return the required structured narration word arrays.")


def _assemble_narration_sentence_words(words, expected_count, field, max_count=None):
    """Normalize word-array items and validate the actual spoken-word range."""
    if not isinstance(words, list):
        return "", f"{field} must be an array of word text"

    maximum = max(expected_count, int(max_count if max_count is not None else expected_count))
    tokens = []
    for index, raw_word in enumerate(words):
        if not isinstance(raw_word, str):
            return "", f"{field} item {index + 1} is not text"
        # Some model responses accidentally put two words in one array item.
        # Split them before validation instead of discarding an otherwise valid sentence.
        parts = re.sub(r"\s+", " ", raw_word).strip().split()
        if not parts:
            return "", f"{field} item {index + 1} is empty"
        for word in parts:
            if narration_word_count(word) != 1:
                return "", f"{field} item {index + 1} contains invalid spoken-word text"
            tokens.append(word)

    if not tokens:
        return "", f"{field} contains no spoken words"
    if len(tokens) < expected_count or len(tokens) > maximum:
        return "", (
            f"{field} normalizes to {len(tokens)} spoken words; "
            f"the allowed range is {expected_count}–{maximum}"
        )

    for word in tokens[:-1]:
        if word.endswith((".", "!", "?")):
            return "", f"{field} has sentence-ending punctuation before its final word"
    if not tokens[-1].endswith((".", "!", "?")):
        return "", f"{field} final word must carry sentence-ending punctuation"
    sentence = " ".join(tokens)
    if len(narration_sentences(sentence)) != 1:
        return "", f"{field} must form exactly one complete sentence"
    return sentence, ""


def compose_narration(
    plan,
    research_items,
    evidence_sources=None,
    force_sentence_indices=None,
):
    """Repair narration length or selected sentences against verified article evidence."""
    sentences = _plan_sentence_fields(plan)
    original_sentences = list(sentences)
    original_script = " ".join(value for value in sentences if value).strip()
    issue = narration_validation_error(original_script)
    forced_indices = sorted({
        int(index) for index in (force_sentence_indices or [])
        if 0 <= int(index) < 4
    })
    plan["narration_sentences"] = sentences

    if not issue and not forced_indices:
        plan["narration_script"] = original_script
        return original_script

    repair_sources = (
        list(evidence_sources)
        if evidence_sources is not None
        else resolve_plan_sources(plan, research_items)
    )
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
            for item in research_items[:3]
        ]

    repair_history = []
    debug_path = WORK / "creative_plan_debug.json"

    def save_debug(status):
        WORK.mkdir(parents=True, exist_ok=True)
        current_script = " ".join(sentences).strip()
        debug_path.write_text(
            json.dumps(
                {
                    "stage": "narration_composer",
                    "status": status,
                    "initial_script": original_script,
                    "initial_sentences": original_sentences,
                    "initial_plan": plan,
                    "correction_attempts": repair_history,
                    "current_sentences": sentences,
                    "current_script": current_script,
                    "final_diagnostics": {
                        "word_count": narration_word_count(current_script),
                        "sentence_count": len(narration_sentences(current_script)),
                        "sentence_word_counts": [
                            narration_word_count(sentence) for sentence in sentences
                        ],
                        "validation_error": narration_validation_error(current_script),
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    save_debug("in_progress")
    function_name = "submit_narration_sentence_corrections"

    for attempt in (1, 2):
        current_script = " ".join(sentences).strip()
        current_issue = narration_validation_error(current_script)
        current_total = narration_word_count(current_script)

        # Aim for the nearest valid boundary, not an arbitrary 42-word target.
        if current_total < 40:
            target_total = 40
        elif current_total > 44:
            target_total = 44
        else:
            target_total = current_total

        budgets = narration_sentence_budget(sentences, target_total=target_total)
        target_indices = (
            list(forced_indices)
            if forced_indices
            else [
                index for index, sentence in enumerate(sentences)
                if _sentence_needs_correction(sentence, index, budgets[index])
            ]
        )

        # A global mismatch should normally resolve through the dynamic sentence budgets.
        # Keep this fallback limited to the body rather than rewriting a valid hook.
        if current_issue and not target_indices:
            target_indices = [1, 2, 3]

        target_fields = ["sentence_" + str(index + 1) + "_words" for index in target_indices]
        required_word_counts = {
            "sentence_" + str(index + 1) + "_words": budgets[index]["min_words"]
            for index in target_indices
        }
        properties = {}
        for index in target_indices:
            field = "sentence_" + str(index + 1) + "_words"
            required_count = required_word_counts[field]
            role = ("curiosity hook", "story context", "distinctive sourced detail", "narrative payoff")[index]
            properties[field] = {
                "type": "array",
                "description": (
                    "Return exactly " + str(required_count) + " individual spoken words for the "
                    + role + ". One word per array item, with no spaces inside an item. "
                    "Place sentence-ending punctuation on the final item only. "
                    "Preserve supported facts and chronology."
                ),
                "items": {"type": "string", "minLength": 1},
                "minItems": required_count,
                "maxItems": required_count,
            }

        tool = {
            "type": "function",
            "function": {
                "name": function_name,
                "description": "Return word arrays only for the requested narration sentence fields.",
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": target_fields,
                    "additionalProperties": False,
                },
            },
        }
        locked = {
            "sentence_" + str(index + 1): sentences[index]
            for index in range(4) if index not in target_indices
        }
        evidence_repair = evidence_sources is not None
        prompt = (
            "Correct only the requested sentence fields. Return each as an array of individual words. "
            "The array length is exact and is stated in the function schema; do not add or omit words. "
            "Python will join the words into sentences. Do not return or rewrite any locked sentence. "
            "The complete narration must remain exactly four sentences and total 40–44 spoken words. "
            "Use only facts stated in the supplied direct publisher article excerpts. Do not invent dates, "
            "statistics, quotes, names, motives, abilities, or outcomes. No padding, repeated ideas, generic "
            "filler, metaphor presented as fact, or unsupported claims. Do not personify AI as feeling, "
            "understanding, or having a soul unless an article explicitly establishes that. "
            + (
                "This is an evidence-grounding repair: replace each requested claim with a concrete fact, "
                "technical detail, or limitation explicitly supported by the verified articles. Sentence four "
                "must deliver a factual payoff, not a poetic interpretation. "
                if evidence_repair else ""
            )
            + "Return the forced function call and nothing else."
        )
        user_content = (
            "Selected story: " + str(plan.get("topic", ""))[:300]
            + "\nTitle: " + str(plan.get("title", ""))[:220]
            + "\nHook concept: " + str(plan.get("hook", ""))[:220]
            + "\nCurrent four sentence fields: " + json.dumps(
                {"sentence_" + str(index + 1): sentences[index] for index in range(4)},
                ensure_ascii=False,
            )
            + "\nLocked sentence fields (must remain unchanged): "
            + json.dumps(locked, ensure_ascii=False)
            + "\nDynamic word budgets for the requested fields: "
            + json.dumps(required_word_counts, ensure_ascii=False)
            + "\nVerified direct article evidence: " + json.dumps(repair_evidence, ensure_ascii=False)
            + "\nValidation issue: " + (
                current_issue or (
                    "Evidence grounding failed for narration sentence(s): " +
                    ", ".join(str(index + 1) for index in forced_indices)
                )
            )
            + "\nCorrection cycle: " + str(attempt) + " of 2."
        )
        payload = {
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_content},
            ],
            "tools": [tool],
            "tool_choice": {"type": "function", "function": {"name": function_name}},
            "parallel_tool_calls": False,
            "chat_template_kwargs": {"enable_thinking": False, "clear_thinking": True},
            "max_completion_tokens": 650,
            "temperature": 0.2,
        }

        response = ai(TEXT_MODEL, payload)
        try:
            corrected = _parse_narration_tool_response(response, target_fields)
        except PipelineError as exc:
            repair_history.append(
                {
                    "attempt": attempt,
                    "corrected_sentence_numbers": [index + 1 for index in target_indices],
                    "required_word_counts": required_word_counts,
                    "received_word_counts": {},
                    "array_diagnostics": {"tool_response": str(exc)[:400]},
                    "validation_error": str(exc)[:400],
                }
            )
            save_debug("in_progress")
            log("Narration word-array correction cycle " + str(attempt) + "/2 returned an invalid structure; retrying.")
            continue

        assembled = {}
        array_diagnostics = {}
        received_word_counts = {}
        for index in target_indices:
            field = "sentence_" + str(index + 1) + "_words"
            words = corrected.get(field)
            received_word_counts[field] = (
                sum(narration_word_count(part) for value in words if isinstance(value, str)
                    for part in re.sub(r"\s+", " ", value).strip().split())
                if isinstance(words, list) else None
            )
            sentence, array_error = _assemble_narration_sentence_words(
                words,
                required_word_counts[field],
                field,
                max_count=budgets[index]["max_words"],
            )
            if array_error:
                array_diagnostics[field] = array_error
            else:
                assembled[index] = sentence

        if array_diagnostics:
            repair_history.append(
                {
                    "attempt": attempt,
                    "corrected_sentence_numbers": [index + 1 for index in target_indices],
                    "required_word_counts": required_word_counts,
                    "received_word_counts": received_word_counts,
                    "array_diagnostics": array_diagnostics,
                    "validation_error": "; ".join(array_diagnostics.values()),
                }
            )
            save_debug("in_progress")
            log(
                "Narration word-array correction cycle " + str(attempt) + "/2 did not pass: "
                + "; ".join(array_diagnostics.values()) + "."
            )
            continue

        for index, value in assembled.items():
            sentences[index] = value

        updated_script = " ".join(sentences).strip()
        updated_issue = narration_validation_error(updated_script)
        repair_history.append(
            {
                "attempt": attempt,
                "corrected_sentence_numbers": [index + 1 for index in target_indices],
                "required_word_counts": required_word_counts,
                "received_word_counts": received_word_counts,
                "word_count": narration_word_count(updated_script),
                "sentence_count": len(narration_sentences(updated_script)),
                "sentence_word_counts": [
                    narration_word_count(sentence) for sentence in sentences
                ],
                "validation_error": updated_issue,
                "narration_sentences": list(sentences),
            }
        )
        save_debug("in_progress")

        if not updated_issue:
            plan["narration_sentences"] = list(sentences)
            plan["narration_script"] = updated_script
            save_debug("repaired")
            log(
                "Sentence-based narration passed validation after correction cycle "
                + str(attempt) + "/2 (" + str(narration_word_count(updated_script))
                + " words; only requested sentence words changed)."
            )
            return updated_script

        log(
            "Sentence-based narration correction cycle " + str(attempt) + "/2 did not pass: "
            + updated_issue + "."
        )

    save_debug("failed")
    final_script = " ".join(sentences).strip()
    raise PipelineError(
        "Narration composer stopped safely after two targeted correction cycles. "
        "The narration must contain 40–44 words, exactly four complete sentences, "
        "a 5–8-word hook, and no sentence over 12 words. Final diagnostic: "
        + narration_validation_error(final_script)
    )

def recent_seo_learning():
    """Decrypt the latest GitHub-native SEO snapshot; never call Cloudflare or poll YouTube."""
    report_path = os.environ.get("SEO_LEARNING_REPORT_PATH", "").strip()
    encryption_key = os.environ.get("YOUTUBE_STATE_ENCRYPTION_KEY", "").strip()
    if not report_path:
        log("SEO learning snapshot path is not configured; using the balanced language mix.")
        return None
    if not encryption_key:
        log("SEO learning key is not configured; using the balanced language mix.")
        return None
    try:
        learning = load_learning_signals(report_path, encryption_key)
        if not isinstance(learning, dict):
            log("No completed SEO learning snapshot exists yet; using the balanced language mix.")
            return None
        log(
            "Loaded encrypted SEO learning snapshot from " +
            str(learning.get("captured_at") or "an undated report") +
            "; only bounded SEO signals will be passed into Discover."
        )
        return learning
    except Exception as exc:
        log("SEO learning snapshot could not be decrypted; using the balanced language mix: " + str(exc)[:180])
        return None


def recent_youtube_access_token():
    """Refresh one read-only Discover token per Prepare run; never log or persist it."""
    required = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    if not all(os.environ.get(name) for name in required):
        return None
    try:
        response = http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": os.environ["YOUTUBE_CLIENT_ID"],
                "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
                "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        return str(token).strip() if token else None
    except Exception as exc:
        log("YouTube OAuth token refresh unavailable for Discover: " + str(exc)[:180])
        return None


def compact_seo_discovery(discovery):
    """Give the planner a compact audience-interest summary, not a raw API dump."""
    discovery = discovery if isinstance(discovery, dict) else {}
    return {
        "status": discovery.get("status", "unavailable"),
        "region_code": discovery.get("region_code", "IN"),
        "queries_sampled": discovery.get("queries_sampled", 0),
        "search_volume": None,
        "search_volume_note": discovery.get("search_volume_note", ""),
        "opportunities": [
            {
                "language": item.get("language"),
                "language_name": item.get("language_name"),
                "query": item.get("query"),
                "results_returned": item.get("results_returned"),
                "median_views_per_day_observed": item.get("median_views_per_day_observed"),
                "recent_upload_share_30d": item.get("recent_upload_share_30d"),
                "opportunity_score": item.get("opportunity_score"),
                "top_result_titles": [
                    result.get("title", "") for result in item.get("top_results", [])[:2]
                ],
            }
            for item in discovery.get("recommended_opportunities", [])[:6]
        ],
        "learned_language_signals_used": discovery.get("learned_language_signals_used", []),
        # Actual owner search phrases are used in the in-memory planner context only;
        # they are deliberately not copied into the prepared artifact.
        "learned_search_term_signal_count": len(discovery.get("learned_search_terms_used", [])),
    }


def make_plan(items, recent=None, seo_context=None, story_groups=None, excluded_group_ids=None):
    groups_by_id = {}
    eligible_story_groups = []
    if story_groups is not None:
        excluded = {str(value) for value in (excluded_group_ids or [])}
        for group in story_groups:
            group_id = str(group.get("group_id") or "").strip()
            if not group_id or group_id in excluded:
                continue
            group_sources = [
                item for item in group.get("sources", [])
                if isinstance(item, dict)
                and is_direct_publisher_article(item)
                and item.get("article_page_verified") is True
                and item.get("freshness_eligible") is True
            ]
            families = {
                publisher_family_domain(
                    item.get("publisher_domain") or urlparse(item.get("url", "")).netloc
                )
                for item in group_sources
            }
            families.discard("")
            source_ids = [
                str(item.get("source_id") or "").strip()
                for item in group_sources
                if str(item.get("source_id") or "").strip()
            ]
            if len(families) < 2 or len(source_ids) < 2:
                continue
            verified_group = dict(group)
            verified_group["sources"] = group_sources
            verified_group["source_ids"] = source_ids
            verified_group["publisher_families"] = sorted(families)
            verified_group["independent_publisher_count"] = len(families)
            groups_by_id[group_id] = verified_group
            eligible_story_groups.append({
                "group_id": group_id,
                "topic_hint": str(group.get("topic_hint") or "")[:220],
                "independent_publisher_count": len(families),
                "source_ids": source_ids,
                "articles": [
                    {
                        "source_id": item.get("source_id"),
                        "title": item.get("title"),
                        "publisher_name": item.get("publisher_name"),
                        "publisher_domain": item.get("publisher_domain"),
                        "date": item.get("date"),
                        "evidence": str(item.get("evidence_text") or "")[:1200],
                    }
                    for item in group_sources
                ],
            })
        if not eligible_story_groups:
            raise PipelineError(
                "Story quality gate blocked: no source-first candidate group contains "
                "two independent readable direct publishers."
            )
        items = [
            source
            for group in groups_by_id.values()
            for source in group.get("sources", [])
        ]

    system = (
        "You are the editorial director of Violin Prince, a violin creator. Choose one timely, "
        "well-supported, family-friendly subject from these headlines and turn it into an original "
        "short visual story with spoken narration and an original string-style instrumental soundtrack. "
        "Choose for a music-loving audience: prioritise violin and instruments, classical and contemporary music, "
        "Treat YouTube SEO Discovery context as limited audience-interest evidence only. Never choose a topic solely "
        "because a sampled opportunity score is high; it must still be well-supported by the research and relevant "
        "to violin/music listeners. Never describe public result samples as search demand or search volume. "
        "film music, artists, performances, festivals and music culture. Art, culture, science or discovery may be "
        "chosen when the story has a clear, compelling connection to music or a strong visual idea. Reject unrelated "
        "retail promotions and generic technology announcements, as well as tragedies, graphic events, violence, "
        "disasters and crimes. Pick the strongest specific story, not merely the loudest headline. "
        "Evidence-first selection is mandatory when eligible story groups are supplied: choose exactly one "
        "provided group_id, include it as story_group_id, and base every factual detail only on articles "
        "inside that group. Never combine separate groups or invent a new subject. The sources field must "
        "contain at least two exact source_id values from the selected group, representing independent "
        "publisher families. "
        "Do not invent facts, dates, statistics, motives, quotations or outcomes. Use only factual claims supported "
        "by supplied research. Every non-hook narration sentence must be supported by the wording of at least one "
        "readable direct article body, not merely a headline or broad topic overlap. Build each body sentence from "
        "a specific statement in a readable article paragraph. Do not personify AI as feeling music, understanding "
        "human experience, having a soul, or learning the deep meaning of every note unless the article explicitly "
        "demonstrates that exact capability. Do not convert technical classification or emotion recognition into "
        "a claim about consciousness or human-like feelings. The final sentence must present a sourced result, "
        "limitation, or concrete implication rather than a poetic metaphor. Avoid unsupported emphasis such as "
        "revolutionary, groundbreaking, exceptionally, fundamentally transforming, or claims about changing the "
        "entire future of a field. When a source describes a current limitation or says a capability is future work, "
        "state that limitation clearly and do not imply the complete capability already exists. Every research item "
        "has a source_id. Prefer at least two source_id values from "
        "different publisher_domain values. The sources field MUST contain one to three exact source_id values "
        "copied from supplied research; never invent IDs or rewrite URLs. Items marked discovery_only may guide "
        "topic selection but cannot support facts or be cited. Google News headline links are discovery leads only "
        "and are not final citations. Only direct publisher article pages with readable evidence can be "
        "retained in the final package. Do not output publisher homepages as article URLs. "
        "Return a timeline array for dated events, each with event, date (YYYY-MM-DD), status "
        "(completed, upcoming, ongoing, or unknown), and source_ids. Judge status against today's date. "
        "Never describe an event as upcoming, scheduled, or something that 'will' happen when its date has passed. "
        "Do not use song lyrics, copied scripts, named copyrighted characters, logos or identifiable living people in images. "
        "Return JSON only with topic,title,story_group_id,hook,description,hashtags,narration_sentences,narrative_style,scenes,sources,timeline. "
        "The narration_sentences field must be an array of exactly four separate, natural, complete spoken sentences. "
        "Sentence 1 is a concise curiosity hook of 5–8 words and must be resolved by the ending. "
        "No sentence may exceed 12 words; twelve is a maximum, not a target. "
        "Vary sentence lengths naturally for spoken rhythm. Do not force equal lengths or any fixed per-sentence word budget. "
        "Make every sentence complete and natural when spoken aloud, never padded. The Python composer checks each sentence independently and may correct only fields outside dynamic word limits. "
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
             "\nYouTube SEO Discovery context (directional samples, not search volume): " +
             json.dumps(seo_context or {}, ensure_ascii=False) +
             "\n" + (
                 "Eligible source-first story groups (choose exactly one group_id; do not mix them): "
                 + json.dumps(eligible_story_groups, ensure_ascii=False)
                 if story_groups is not None
                 else "Research evidence: " + json.dumps(compact, ensure_ascii=False)
             )}        ],
        # Gemma 4 supports this parameter; disabling reasoning keeps the response
        # focused on the machine-readable plan expected by the renderer.
        "chat_template_kwargs": {"enable_thinking": False, "clear_thinking": True},
        "max_completion_tokens": 1800,
        "temperature": 0.35
    })

    plan = parse_planner_result(result)
    if plan.get("skip"):
        raise PipelineError("Editorial agent skipped: " + str(plan.get("reason", ""))[:200])

    if story_groups is not None:
        selected_group_id = str(plan.get("story_group_id") or "").strip()
        selected_group = groups_by_id.get(selected_group_id)
        if not selected_group:
            raise PipelineError(
                "Story quality gate blocked: editorial planner did not select an eligible "
                "source-first story_group_id."
            )
        allowed_ids = set(selected_group.get("source_ids", []))
        references = plan.get("sources") or []
        if isinstance(references, (str, dict)):
            references = [references]
        if not isinstance(references, list):
            references = []
        referenced_ids = []
        for reference in references:
            if isinstance(reference, dict):
                value = reference.get("source_id") or reference.get("id")
            else:
                value = reference
            value = str(value or "").strip()
            if value:
                referenced_ids.append(value)
        if len(set(referenced_ids)) < 2 or not set(referenced_ids).issubset(allowed_ids):
            raise PipelineError(
                "Story quality gate blocked: planner citations must be at least two exact "
                "source IDs from the one selected eligible story group."
            )
        referenced_families = {
            publisher_family_domain(
                source.get("publisher_domain") or urlparse(source.get("url", "")).netloc
            )
            for source in selected_group["sources"]
            if str(source.get("source_id") or "") in set(referenced_ids)
        }
        referenced_families.discard("")
        if len(referenced_families) < 2:
            raise PipelineError(
                "Story quality gate blocked: planner citations do not represent two independent publishers."
            )
        plan["source_group"] = {
            "group_id": selected_group_id,
            "topic_hint": selected_group.get("topic_hint", ""),
            "publisher_families": selected_group.get("publisher_families", []),
            "independent_publisher_count": selected_group.get("independent_publisher_count", 0),
            "source_ids": list(selected_group["source_ids"]),
        }
        plan["sources"] = list(selected_group["source_ids"])
        items = selected_group["sources"]
        compact = planner_research_items(items)

    # The planner returns four sentence fields; the composer handles targeted
    # correction and assembles the canonical narration_script for downstream stages.
    compose_narration(plan, compact)

    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        raise PipelineError("Planner must provide exactly three scenes.")
    narration_script = str(plan.get("narration_script", "")).strip()
    final_narration_issue = narration_validation_error(narration_script)
    if final_narration_issue:
        raise PipelineError("Planner narration failed validation: " + final_narration_issue)
    plan["narration_script"] = narration_script
    plan["narrative_style"] = str(plan.get("narrative_style", "documentary")).lower()
    if plan["narrative_style"] not in ("documentary", "cinematic_story"):
        plan["narrative_style"] = "documentary"

    planner_source_references = plan.get("sources") or []
    plan["source_reference_hints"] = planner_source_references
    debug_path = WORK / "creative_plan_debug.json"
    existing_debug = {}
    if debug_path.is_file():
        try:
            existing_debug = json.loads(debug_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_debug = {}
    if existing_debug.get("stage") == "narration_composer":
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
    plan["source_resolution"] = {
        "status": "seed_sources_resolved" if selected_sources else "pending_targeted_verification",
        "seed_direct_source_count": len(selected_sources),
        "note": (
            "Only direct publisher articles with readable evidence can enter the final package. "
            "Discovery-only links are search leads, not citations."
        ),
    }
    if not selected_sources:
        log(
            "Planner references were discovery-only or unmatched in the seed research. "
            "Continuing to mandatory story-specific publisher research instead of rejecting the story early."
        )
    elif len(selected_sources) == 1:
        log(
            "One direct seed source matched. Mandatory story-specific research will seek "
            "a second independent publisher before the package can pass."
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
        "volume=1.15,asplit=2[voice_sc][voice_mix];"
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
        "quality_control": PACKAGE / "quality_control.json",
    }


def _read_package(require_images=False):
    paths = _package_paths()
    for key in ("plan", "metadata", "audio", "narration", "quality_control"):
        if not paths[key].is_file():
            raise PipelineError(f"Prepared package is missing {paths[key].name}. Download the correct earlier stage artifact.")
    try:
        plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        quality = json.loads(paths["quality_control"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError("Prepared package contains invalid JSON metadata.") from exc
    narration_info = metadata.get("narration_info")
    if not isinstance(plan.get("scenes"), list) or len(plan["scenes"]) != 3:
        raise PipelineError("Prepared package must contain exactly three planned scenes.")
    if not isinstance(narration_info, dict) or not narration_info.get("subtitle_cues"):
        raise PipelineError("Prepared package is missing narration subtitle timings.")
    if (
        quality.get("status") != "passed"
        or quality.get("date_check", {}).get("status") != "passed"
        or quality.get("freshness", {}).get("status") != "passed"
    ):
        raise PipelineError("Story quality-control, date or seven-day freshness report is not passed; Visuals and Render are blocked.")
    sources = plan.get("sources", [])
    domains = {
        str(source.get("publisher_domain") or urlparse(source.get("url", "")).netloc).lower().removeprefix("www.")
        for source in sources if isinstance(source, dict) and is_direct_publisher_article(source)
    }
    direct_count = sum(
        1 for source in sources
        if isinstance(source, dict)
        and is_direct_publisher_article(source)
        and source.get("article_page_verified") is True
    )
    if direct_count < 2 or len(domains) < 2:
        raise PipelineError("Prepared story must retain at least two direct publisher articles from independent domains.")
    source_group = plan.get("source_group") or {}
    allowed_ids = {str(value) for value in source_group.get("source_ids", [])}
    verified_ids = {str(value) for value in source_group.get("verified_source_ids", [])}
    actual_ids = {str(source.get("source_id") or "") for source in sources if isinstance(source, dict)}
    if not allowed_ids or not verified_ids or not verified_ids.issubset(allowed_ids) or actual_ids != verified_ids:
        raise PipelineError("Prepared story citations do not match the exact verified source group.")
    freshness_sources = quality.get("freshness", {}).get("verified_sources", [])
    freshness_ids = {
        str(item.get("source_id") or "") for item in freshness_sources if isinstance(item, dict)
    }
    if (
        len(freshness_sources) < 2
        or len(freshness_ids) != len(freshness_sources)
        or freshness_ids != verified_ids
        or any(
            not isinstance(item, dict)
            or item.get("freshness_status") not in ("preferred", "acceptable")
            or item.get("age_hours") is None
            or float(item.get("age_hours")) > FRESHNESS_MAX_AGE_HOURS
            for item in freshness_sources
        )
    ):
        raise PipelineError("Prepared story does not have two dated publisher articles within the seven-day window.")
    review = metadata.get("story_review") or {}
    if require_images and review.get("approved") is not True:
        raise PipelineError("Render blocked: the story has not received explicit human approval before Visuals.")
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
        "VIOLIN PRINCE — PRE-PRODUCTION STORY REVIEW",
        "",
        "HUMAN REVIEW REQUIRED: Visual generation is locked until you approve this story.",
        "Check the narration, event dates, and every direct publisher source below.",
        "",
        "TITLE: " + str(plan.get("title", "")),
        "TOPIC: " + str(plan.get("topic", "")),
        "HOOK: " + str(plan.get("hook", "")),
        "",
        "NARRATION:",
        str(plan.get("narration_script", "")),
        "",
        "DATE CHECK:",
        json.dumps((plan.get("quality_control") or {}).get("date_check", {}), ensure_ascii=False, indent=2),
        "",
        "SCENE PLAN:",
    ]
    for index, scene in enumerate(plan.get("scenes", []), start=1):
        lines.extend([
            f"{index}. {scene.get('caption', '')}",
            "   Visual direction: " + str(scene.get("image_prompt", "")),
        ])
    lines.extend(["", "FRESHNESS POLICY: Prefer sources within 50 hours; accept verified articles up to 168 hours old.", ""])
    lines.extend(["", "DIRECT PUBLISHER SOURCES:"])
    for index, source in enumerate(plan.get("sources", []), start=1):
        if isinstance(source, dict):
            lines.extend([
                f"{index}. {source.get('publisher_name') or source.get('publisher_domain') or 'Publisher'} — {source.get('title', '')}",
                "   Publisher domain: " + str(source.get("publisher_domain", "")),
                "   Published: " + str(source.get("published_at_utc") or source.get("date", "")),
                "   Freshness: " + str(source.get("freshness_status") or "checked in quality_control.json"),
                "   Direct article URL: " + str(source.get("url", "")),
                "   Evidence excerpt: " + str(source.get("evidence_excerpt", ""))[:900],
                "",
            ])
        else:
            lines.append(f"{index}. {source}")
    lines.extend([
        "",
        "QUALITY GATE:",
        json.dumps(plan.get("quality_control", {}), ensure_ascii=False, indent=2),
        "",
        "VISUAL APPROVAL:",
        "Do not start Visuals until you have reviewed this file and explicitly approve the story.",
    ])
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
    readable_direct = [
        item for item in items
        if item.get("article_page_verified") is True
        and _story_article_eligibility(item)[0]
    ]
    if not readable_direct:
        log(
            "Preserved research artifact contains no readable direct publisher articles; "
            "discarding the stale lead-only cache and running fresh publisher discovery."
        )
        return None
    WORK.mkdir(exist_ok=True)
    (WORK / "research.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"Reusing {len(items)} preserved research sources from an earlier run; research feeds will not be called again.")
    return items


def prepare_stage():
    """Create research, a source-audited story, narration and soundtrack; no visuals or MP4."""
    as_of = datetime.now(timezone.utc)
    claim_run()
    asset, audio = get_audio()
    report("running", "Preparing research, source verification, story, narration and background music bed.")
    items = load_reusable_research()
    if items is None:
        items = research()
        log("Research sources collected: " + str(len(items)))
    # DISCOVER: consume the latest encrypted Phase 5 learning snapshot, then sample
    # a bounded English/Hindi/Bengali search mix before the editorial planner chooses.
    learning = recent_seo_learning()
    access_token = recent_youtube_access_token()
    discovery = seo_discover(
        profile=seo_load_profile(),
        api_key=os.environ.get("YOUTUBE_API_KEY", ""),
        access_token=access_token,
        learned_signals=learning,
        max_queries=6,
    )
    log(
        "SEO Discover prepared " + str(discovery.get("queries_sampled", 0)) +
        " live YouTube query samples; learned language groups used: " +
        str(len(discovery.get("learned_language_signals_used", []))) +
        "; learned search terms applied: " +
        str(len(discovery.get("learned_search_terms_used", []))) +
        ". Search volume is not available from this API."
    )
    plan, story_items, verified_sources = prepare_story_with_source_recovery(
        items,
        recent=recent_topics(),
        seo_context=compact_seo_discovery(discovery),
        max_candidates=2,
        as_of=as_of,
    )
    date_check = validate_story_dates(plan, as_of=as_of.date())
    if date_check["status"] != "passed":
        raise PipelineError(
            "Story date quality gate blocked this draft: " +
            " ".join(date_check.get("issues", [])) +
            " No narration or visuals were created."
        )
    plan["sources"] = [
        {
            "source_id": source.get("source_id", ""),
            "publisher_name": source.get("publisher_name") or source.get("publisher_domain", ""),
            "publisher_domain": source.get("publisher_domain", ""),
            "title": source.get("title", ""),
            "url": source.get("url", ""),
            "date": source.get("date", ""),
            "published_at_utc": source.get("published_at_utc") or article_freshness(source, as_of=as_of).get("published_at_utc", ""),
            "freshness_status": article_freshness(source, as_of=as_of).get("freshness_status"),
            "age_hours": article_freshness(source, as_of=as_of).get("age_hours"),
            "article_page_verified": source.get("article_page_verified") is True,
            "evidence_excerpt": str(source.get("evidence_text") or source.get("summary") or "")[:1400],
            "link_type": "publisher_article",
        }
        for source in verified_sources
    ]

    # Validate the selected story topic in the same three languages; this remains
    # read-only and cannot change video metadata or publication permissions.
    topic_queries = build_topic_queries(plan.get("topic") or plan.get("title"))
    topic_validation = seo_discover(
        profile=seo_load_profile(),
        api_key=os.environ.get("YOUTUBE_API_KEY", ""),
        access_token=access_token,
        learned_signals=learning,
        query_plan_override=topic_queries,
    )
    plan["seo_discovery_summary"] = {
        "status": discovery.get("status", "unavailable"),
        "queries_sampled": discovery.get("queries_sampled", 0),
        "topic_validation_status": topic_validation.get("status", "unavailable"),
        "topic_validation_queries_sampled": topic_validation.get("queries_sampled", 0),
        "learned_language_groups_used": len(discovery.get("learned_language_signals_used", [])),
        "learned_search_terms_applied": len(discovery.get("learned_search_terms_used", [])),
        "region_code": discovery.get("region_code", "IN"),
        "search_volume": None,
    }
    plan["seo_learning_snapshot"] = {
        "captured_at": (learning or {}).get("captured_at"),
        "sample_count": (learning or {}).get("sample_count", 0),
        "learning_ready": bool((learning or {}).get("learning_ready")),
    }
    plan["quality_control"] = build_story_quality_report(plan, verified_sources, date_check, as_of=as_of)
    if plan["quality_control"]["status"] != "passed":
        raise PipelineError("Story quality-control report did not pass. No narration or visuals were created.")
    topic, title = str(plan.get("topic", "")), str(plan.get("title", "Violin Prince Short"))
    from voiceover import synthesize_voiceover
    narration_path, narration_info = synthesize_voiceover(
        plan["narration_script"], OUT / "narration.wav"
    )
    paths = _package_paths()
    paths["audio"].write_bytes(audio)
    shutil.copy2(narration_path, paths["narration"])
    paths["plan"].write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["research"].write_text(json.dumps(story_items, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["quality_control"].write_text(
        json.dumps(plan["quality_control"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["metadata"].write_text(json.dumps({
        "schema_version": 2,
        "prepared_run_id": RUN_ID,
        "asset": asset,
        "narration_info": narration_info,
        "topic": topic,
        "title": title,
        "prepared_at": as_of.isoformat(),
        "stage": "prepared",
        "story_review": {
            "status": "awaiting_human_review",
            "approved": False,
            "approved_at": None,
            "approval_method": None,
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_review_text(plan, PACKAGE / "review.txt")
    log(
        "Story quality control passed: " +
        str(plan["quality_control"]["verified_source_count"]) +
        " direct publisher sources across independent domains; date checks passed."
    )
    log("Prepared package saved. Review review.txt and quality_control.json; Visuals remains locked pending approval.")
    report("prepared", "Source-audited story package is ready for human review; Visuals remains locked.", topic, title,
           metadata={"stage": "prepared", "story_review": "awaiting_human_review",
                     "verified_sources": len(verified_sources), "date_check": "passed"})
    return 0


def visuals_stage(feedback=""):
    """Generate scene images only after an explicit review of the prepared story."""
    if not CF_ACCOUNT or not CF_TOKEN:
        raise PipelineError("CF_ACCOUNT_ID and CF_AI_TOKEN are required for the Visuals stage.")
    if os.environ.get("STORY_APPROVED", "false").strip().lower() not in ("true", "1", "yes"):
        raise PipelineError(
            "Visuals blocked: review the prepared-package/review.txt and quality_control.json first, "
            "then re-run Visuals with story_approved=true."
        )
    plan, metadata, _narration_info, paths, image_paths = _read_package(require_images=False)
    review = metadata.setdefault("story_review", {})
    if review.get("approved") is not True:
        review.update({
            "status": "approved",
            "approved": True,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approval_method": "manual_workflow_dispatch_input",
        })
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
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
        "quality_control": plan.get("quality_control", {}),
        "story_review": metadata.get("story_review", {}),
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
