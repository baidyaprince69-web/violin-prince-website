"""Shared, report-driven SEO intelligence.

Discover samples public YouTube search results for the Violin Prince channel profile.
Optimize prepares conservative metadata for review after a video is rendered.
Learn derives transparent, rules-based signals from actual owner analytics reports.
No search-volume values are fabricated and no AI call is made by Learn.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import requests

API_ROOT = "https://www.googleapis.com/youtube/v3"
ENGINE_VERSION = "1.0.0"
PROFILE_PATH = Path(__file__).with_name("channel_profile.json")


def load_profile(path: str | Path | None = None) -> dict[str, Any]:
    """Load the editable public Violin Prince channel-search profile."""
    target = Path(path) if path else PROFILE_PATH
    try:
        profile = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("SEO channel profile is missing or invalid: " + str(exc)) from exc
    if not isinstance(profile, dict):
        raise ValueError("SEO channel profile must be a JSON object.")
    languages = profile.get("search_languages")
    if not isinstance(languages, list) or not languages:
        raise ValueError("SEO channel profile must contain search_languages.")
    seen = set()
    for language in languages:
        if not isinstance(language, dict):
            raise ValueError("Each SEO language profile must be an object.")
        code = str(language.get("code") or "").strip().lower()
        queries = language.get("queries")
        if not code or code in seen or not isinstance(queries, list) or not queries:
            raise ValueError("Each SEO language needs a unique code and at least one query.")
        seen.add(code)
    return profile


def build_queries(
    profile: dict[str, Any] | None = None,
    *,
    max_queries: int | None = None,
    rotation_index: int | None = None,
) -> list[dict[str, str]]:
    """Build a bounded, multilingual plan and rotate through each channel phrase set."""
    profile = profile or load_profile()
    budget = max_queries if max_queries is not None else int(profile.get("query_budget_per_run", 9))
    budget = max(1, min(int(budget), 20))
    slot = (
        int(rotation_index) if rotation_index is not None
        else datetime.now(timezone.utc).timetuple().tm_yday
    )
    chosen = []
    languages = profile.get("search_languages", [])
    cursors = [0] * len(languages)
    starts = [
        (slot % len(language.get("queries", []))) if language.get("queries") else 0
        for language in languages
    ]
    while len(chosen) < budget:
        progressed = False
        for index, language in enumerate(languages):
            phrases = language.get("queries", [])
            if cursors[index] < len(phrases) and len(chosen) < budget:
                phrase_index = (starts[index] + cursors[index]) % max(1, len(phrases))
                phrase = re.sub(r"\s+", " ", str(phrases[phrase_index] or "")).strip()
                cursors[index] += 1
                if phrase:
                    code = str(language.get("code") or "").strip().lower()
                    name = str(language.get("name") or code).strip()
                    chosen.append({"language": code, "language_name": name, "query": phrase})
                progressed = True
        if not progressed:
            break
    return chosen


def build_topic_queries(topic: str) -> list[dict[str, str]]:
    """Create video-specific multilingual searches from the selected story topic."""
    clean = re.sub(r"\s+", " ", str(topic or "")).strip()[:100]
    if not clean:
        return []
    return [
        {"language": "en", "language_name": "English", "query": clean + " violin cover"},
        {"language": "hi", "language_name": "Hindi", "query": clean + " वायलिन कवर"},
        {"language": "bn", "language_name": "Bengali", "query": clean + " বেহালা কভার"},
    ]



def _get_json(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("YouTube API returned an unexpected response.")
    return value


def _published_age_days(value: str, now: datetime) -> float | None:
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return max(0.0, (now - published.astimezone(timezone.utc)).total_seconds() / 86400.0)
    except (TypeError, ValueError):
        return None


def _language_signals(learned: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    output = {}
    for item in (learned or {}).get("language_signals", []):
        if not isinstance(item, dict):
            continue
        code = str(item.get("language") or "").strip().lower()
        try:
            count = int(item.get("sample_count", 0))
        except (TypeError, ValueError):
            count = 0
        # Unknown/script-ambiguous titles must never bias English, Hindi or Bengali.
        if code in {"en", "hi", "bn"} and count >= 3:
            output[code] = item
    return output


def _learned_search_term_signals(learned: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Accept only actual YouTube Search report terms supported by multiple videos."""
    output = []
    for item in (learned or {}).get("search_term_signals", []):
        if not isinstance(item, dict):
            continue
        language = str(item.get("language") or "").lower()
        term = re.sub(r"\s+", " ", str(item.get("search_term") or "")).strip()[:160]
        try:
            video_count = int(item.get("video_sample_count", 0))
            views = float(item.get("views", 0) or 0)
        except (TypeError, ValueError):
            continue
        if language in {"en", "hi", "bn"} and term and video_count >= 3 and views >= 3:
            output.append({
                "language": language,
                "search_term": term,
                "video_sample_count": video_count,
                "views": views,
            })
    output.sort(key=lambda item: item["views"], reverse=True)
    return output[:6]


def discover(
    *,
    profile: dict[str, Any] | None = None,
    api_key: str | None = None,
    access_token: str | None = None,
    session: requests.Session | None = None,
    learned_signals: dict[str, Any] | None = None,
    max_queries: int | None = None,
    query_plan_override: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Sample search-result performance; never represent samples as search volume."""
    profile = profile or load_profile()
    query_plan = query_plan_override or build_queries(profile, max_queries=max_queries)
    learned_terms = _learned_search_term_signals(learned_signals)
    learned_terms_used = []
    if query_plan_override is None:
        # Replace one lower-priority query per language with a real search term
        # that generated views for at least three of the channel's videos.
        language_names = {
            str(item.get("code") or "").lower(): str(item.get("name") or item.get("code") or "")
            for item in profile.get("search_languages", [])
        }
        for term in learned_terms:
            language = term["language"]
            matches = [index for index, item in enumerate(query_plan) if item.get("language") == language]
            if not matches:
                continue
            phrase = term["search_term"]
            if any(str(item.get("query") or "").casefold() == phrase.casefold() for item in query_plan):
                continue
            query_plan[matches[-1]] = {
                "language": language,
                "language_name": language_names.get(language, language),
                "query": phrase,
            }
            learned_terms_used.append(term)
    query_plan = [
        {
            "language": str(item.get("language") or "en").lower(),
            "language_name": str(item.get("language_name") or item.get("language") or "English"),
            "query": re.sub(r"\s+", " ", str(item.get("query") or "")).strip()[:160],
        }
        for item in query_plan if isinstance(item, dict) and str(item.get("query") or "").strip()
    ]
    region = str(profile.get("region_code") or "IN").upper()
    now = now or datetime.now(timezone.utc)
    learned_by_language = _language_signals(learned_signals)
    base = {
        "engine_version": ENGINE_VERSION,
        "stage": "discover",
        "available": False,
        "region_code": region,
        "market": profile.get("primary_market", "India"),
        "query_plan": query_plan,
        "queries_sampled": 0,
        "query_results": [],
        "recommended_opportunities": [],
        "search_volume": None,
        "search_volume_note": "Not provided by the YouTube Data API. Public result samples are not search-volume measurements.",
        "learned_language_signals_used": sorted(learned_by_language),
        "learned_search_terms_used": learned_terms_used,
    }
    use_oauth = bool(str(access_token or "").strip())
    use_api_key = bool(str(api_key or "").strip()) and not use_oauth
    if not use_oauth and not use_api_key:
        base["status"] = "search_authorization_missing"
        base["note"] = "Search seeds are prepared, but live sampling needs the connected YouTube OAuth token or YOUTUBE_API_KEY."
        return base

    client = session or requests.Session()
    client.headers.update({"User-Agent": "ViolinPrinceAutopilot/SEO-Intelligence"})
    if use_oauth:
        client.headers.update({"Authorization": "Bearer " + str(access_token).strip()})
    sampled = []
    errors = []
    video_by_id: dict[str, dict[str, Any]] = {}
    for item in query_plan:
        try:
            search_params = {
                "part": "snippet",
                "type": "video",
                "q": item["query"],
                "regionCode": region,
                "relevanceLanguage": item["language"],
                "safeSearch": "moderate",
                "maxResults": min(10, max(1, int(profile.get("max_results_per_query", 10)))),
                "order": "relevance",
            }
            if use_api_key:
                search_params["key"] = str(api_key).strip()
            result = _get_json(client, API_ROOT + "/search", search_params)
            rows = []
            for raw in result.get("items", []):
                video_id = str((raw.get("id") or {}).get("videoId") or "").strip()
                snippet = raw.get("snippet") or {}
                if not video_id:
                    continue
                video = {
                    "video_id": video_id,
                    "title": str(snippet.get("title") or "")[:180],
                    "channel_title": str(snippet.get("channelTitle") or "")[:100],
                    "published_at": str(snippet.get("publishedAt") or ""),
                    "description_excerpt": re.sub(r"\s+", " ", str(snippet.get("description") or ""))[:240],
                    "url": "https://www.youtube.com/watch?v=" + video_id,
                }
                rows.append(video)
                video_by_id.setdefault(video_id, video)
            sampled.append({**item, "results": rows})
        except Exception as exc:
            errors.append({
                "query": item["query"],
                "language": item["language"],
                "error": str(exc)[:220],
            })
            sampled.append({**item, "results": [], "error": str(exc)[:220]})

    stats = {}
    ids = list(video_by_id)
    if ids:
        try:
            stats_params = {
                "part": "statistics,contentDetails,snippet",
                "id": ",".join(ids[:50]),
            }
            if use_api_key:
                stats_params["key"] = str(api_key).strip()
            details = _get_json(client, API_ROOT + "/videos", stats_params)
            for raw in details.get("items", []):
                video_id = str(raw.get("id") or "")
                stats[video_id] = {
                    "view_count": int((raw.get("statistics") or {}).get("viewCount") or 0),
                    "like_count": int((raw.get("statistics") or {}).get("likeCount") or 0),
                    "comment_count": int((raw.get("statistics") or {}).get("commentCount") or 0),
                }
        except Exception as exc:
            errors.append({"query": "__video_statistics__", "error": str(exc)[:220]})

    summaries = []
    for item in sampled:
        videos = []
        velocities = []
        ages = []
        for base_video in item.get("results", []):
            video = dict(base_video)
            video.update(stats.get(video["video_id"], {}))
            age = _published_age_days(video.get("published_at", ""), now)
            if age is not None:
                video["age_days"] = round(age, 2)
                ages.append(age)
            if age is not None and "view_count" in video:
                velocity = video["view_count"] / max(age, 1.0)
                video["views_per_day_observed"] = round(velocity, 2)
                velocities.append(velocity)
            videos.append(video)
        med_velocity = median(velocities) if velocities else None
        med_views = median([v["view_count"] for v in videos if "view_count" in v]) if videos else None
        fresh_share = (sum(1 for age in ages if age <= 30) / len(ages)) if ages else 0.0
        sample_coverage = len(videos) / max(1, int(profile.get("max_results_per_query", 10)))
        velocity_signal = min(40.0, 10.0 * math.log10(1.0 + max(0.0, med_velocity or 0.0)))
        freshness_signal = 20.0 * fresh_share
        sample_signal = 40.0 * min(1.0, sample_coverage)
        language_signal = learned_by_language.get(item["language"])
        learning_note = "no reliable language-level learning signal yet"
        learning_bonus = 0.0
        if language_signal:
            performance = str(language_signal.get("relative_performance") or "")
            if performance == "above_channel_median":
                learning_bonus = 5.0
                learning_note = "prior channel report showed above-median watch percentage; treated as a small test-priority signal"
            elif performance == "below_channel_median":
                learning_note = "prior channel report showed below-median watch percentage; language remains in the test mix"
        score = round(min(100.0, velocity_signal + freshness_signal + sample_signal + learning_bonus), 1)
        summary = {
            "language": item["language"],
            "language_name": item["language_name"],
            "query": item["query"],
            "results_returned": len(videos),
            "videos_with_view_counts": sum(1 for v in videos if "view_count" in v),
            "median_views": int(med_views) if med_views is not None else None,
            "median_views_per_day_observed": round(med_velocity, 2) if med_velocity is not None else None,
            "recent_upload_share_30d": round(fresh_share, 3),
            "opportunity_score": score,
            "opportunity_score_basis": "Observed result count, sampled views-per-day and recent-upload share; not search volume.",
            "learning_note": learning_note,
            "top_results": sorted(
                videos,
                key=lambda v: float(v.get("views_per_day_observed", 0)),
                reverse=True,
            )[:4],
        }
        summaries.append(summary)

    summaries.sort(key=lambda x: x["opportunity_score"], reverse=True)
    base.update({
        "available": bool(any(item.get("results") for item in sampled)),
        "status": "sampled" if any(item.get("results") for item in sampled) else "no_search_results",
        "queries_sampled": len(sampled) - sum(1 for item in sampled if item.get("error")),
        "query_results": summaries,
        "recommended_opportunities": summaries[:6],
        "errors": errors[:8],
        "sampled_at": now.astimezone(timezone.utc).isoformat(),
    })
    return base


def _normalise_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[,\n]", value)
    elif isinstance(value, (tuple, list)):
        values = value
    else:
        return []
    output = []
    seen = set()
    for raw in values:
        tag = re.sub(r"\s+", " ", str(raw or "")).strip().lstrip("#")
        if tag and tag.casefold() not in seen:
            output.append(tag)
            seen.add(tag.casefold())
    return output


def _normalise_hashtags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[,\s]+", value)
    elif isinstance(value, (tuple, list)):
        values = value
    else:
        return []
    output = []
    seen = set()
    for raw in values:
        tag = re.sub(r"[^\w]", "", str(raw or "").strip().lstrip("#"), flags=re.UNICODE)
        if tag and ("#" + tag).casefold() not in seen:
            output.append("#" + tag)
            seen.add(("#" + tag).casefold())
    # Keep every proposed hashtag so the publisher can reject an over-limit
    # plan explicitly; silently trimming would hide a metadata-review problem.
    return output


def optimize(
    plan: dict[str, Any],
    *,
    discovery: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare conservative metadata suggestions; always require review/approval."""
    if not isinstance(plan, dict):
        raise ValueError("SEO optimization needs a creative plan object.")
    profile = profile or load_profile()
    discovery = discovery or plan.get("seo_discovery") or {}
    result = dict(plan)
    title = str(plan.get("seo_title") or plan.get("title") or "").strip()
    topic = str(plan.get("topic") or title).strip()
    declared_language = str(plan.get("language") or plan.get("default_language") or "").strip().lower()
    language = declared_language or _detect_language({"title": title + " " + topic})
    language = language or str(profile.get("default_language") or "en").lower()
    hook = str(plan.get("hook") or "").strip()

    topic_validation = discovery.get("topic_validation")
    topic_opportunities = (
        topic_validation.get("recommended_opportunities", [])
        if isinstance(topic_validation, dict) else []
    )
    opportunities = topic_opportunities or discovery.get("recommended_opportunities", [])
    best = next((item for item in opportunities if str(item.get("language", "")).lower() == language), None)
    if best is None and opportunities:
        best = opportunities[0]
    keyword = str(plan.get("primary_keyword") or (best or {}).get("query") or topic or title).strip()
    if not keyword:
        keyword = str(profile.get("creator_keywords", ["Violin Prince"])[0])

    description = str(plan.get("seo_description") or plan.get("description") or "").strip()
    if not description:
        description = topic + (("\n\n" + hook) if hook else "")
    if keyword and keyword.casefold() not in description.casefold():
        description = description.rstrip() + "\n\n" + keyword

    tags = _normalise_tags(plan.get("seo_tags", plan.get("tags", [])))
    # Put the actual topic keyword first so Phase 5 can associate performance
    # with the optimized query; keep the stable channel identity after topic tags.
    if keyword and keyword.casefold() not in {item.casefold() for item in tags}:
        tags.insert(0, keyword)
    brand = str(profile.get("brand_name") or "Violin Prince").strip()
    if brand and brand.casefold() not in {item.casefold() for item in tags}:
        tags.append(brand)
    tags = tags[:12]

    hashtags = _normalise_hashtags(plan.get("seo_hashtags", plan.get("hashtags", [])))
    if not hashtags:
        hashtags = ["#ViolinPrince"]
        if language == "hi":
            hashtags.append("#HindiMusic")
        elif language == "bn":
            hashtags.append("#BengaliMusic")
        else:
            hashtags.append("#ViolinMusic")
        if re.search(r"\bcover\b|কভার|कवर", (topic + " " + title).casefold()):
            hashtags.append("#ViolinCover")

    candidates = []
    for value in (
        title,
        (keyword + " | " + title) if title and keyword else "",
        (title + " — " + keyword) if title and keyword else "",
    ):
        value = re.sub(r"\s+", " ", str(value)).strip()
        if value and len(value) <= 100 and value.casefold() not in {x.casefold() for x in candidates}:
            candidates.append(value)

    metadata_approved = (
        plan.get("seo_metadata_approved") is True or plan.get("metadata_approved") is True
    )
    result.update({
        "language": language,
        "primary_keyword": keyword,
        "seo_title": title or keyword,
        "seo_description": description,
        "seo_tags": tags,
        "seo_hashtags": hashtags,
        "seo_metadata_approved": metadata_approved,
        "seo_optimization": {
            "engine_version": ENGINE_VERSION,
            "language": language,
            "primary_keyword": keyword,
            "matched_query": (best or {}).get("query"),
            "title_candidates": candidates,
            "metadata_review_required": True,
            "approval_preserved_from_input": metadata_approved,
            "search_volume": None,
            "search_volume_note": "No search-volume number is available from the connected YouTube search sample.",
        },
    })
    return result


def _detect_language(video: dict[str, Any]) -> str:
    declared = str(video.get("default_language") or video.get("language") or "").lower()
    if declared.startswith("hi"):
        return "hi"
    if declared.startswith("bn"):
        return "bn"
    if declared.startswith("en"):
        return "en"
    title = str(video.get("title") or "")
    if any(0x0980 <= ord(char) <= 0x09FF for char in title):
        return "bn"
    if any(0x0900 <= ord(char) <= 0x097F for char in title):
        return "hi"
    # Do not assume a Latin-script title is English without language evidence.
    return "unknown"


def learn(report: dict[str, Any], *, minimum_group_size: int = 3) -> dict[str, Any]:
    """Convert actual per-video analytics into cautious SEO-only feedback signals."""
    raw_search_terms = report.get("search_terms", [])
    search_term_signals = []
    for raw_term in raw_search_terms if isinstance(raw_search_terms, list) else []:
        if not isinstance(raw_term, dict):
            continue
        term = re.sub(r"\s+", " ", str(raw_term.get("search_term") or raw_term.get("term") or "")).strip()[:160]
        language = str(raw_term.get("language") or "").lower()
        try:
            views = float(raw_term.get("views", 0) or 0)
            video_count = int(raw_term.get("video_sample_count", 0))
        except (TypeError, ValueError):
            continue
        if term and language in {"en", "hi", "bn"} and video_count >= minimum_group_size and views > 0:
            search_term_signals.append({
                "language": language,
                "search_term": term,
                "views": views,
                "video_sample_count": video_count,
                "evidence": "actual_youtube_search_traffic",
            })
    search_term_signals.sort(key=lambda item: item["views"], reverse=True)
    search_term_signals = search_term_signals[:12]

    raw_rows = report.get("videos", report.get("per_video", []))
    rows = []
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        row["language"] = _detect_language(row)
        for metric in (
            "views", "watch_minutes", "average_view_duration_seconds",
            "average_view_percentage", "likes", "comments", "shares",
            "subscribers_gained", "thumbnail_impressions_ctr",
        ):
            try:
                row[metric] = float(row[metric]) if row.get(metric) is not None else None
            except (TypeError, ValueError):
                row[metric] = None
        rows.append(row)

    if not rows:
        return {
            "engine_version": ENGINE_VERSION,
            "stage": "learn",
            "sample_count": 0,
            "learning_ready": False,
            "language_signals": [],
            "keyword_signals": [],
            "search_term_signals": search_term_signals,
            "search_term_learning_ready": bool(search_term_signals),
            "recommendations": [
                "Use the current balanced search coverage; no per-video retention rows were available."
            ] + (["Actual YouTube search terms from channel traffic are available for the next Discover run."] if search_term_signals else []),
            "metrics_used": ["actual_youtube_search_terms"] if search_term_signals else [],
            "metrics_not_available": ["thumbnail_impressions_ctr"],
        }

    available_metrics = [
        metric for metric in (
            "views", "watch_minutes", "average_view_duration_seconds",
            "average_view_percentage", "likes", "comments", "shares",
            "subscribers_gained", "thumbnail_impressions_ctr",
        )
        if any(row.get(metric) is not None for row in rows)
    ]
    views_values = [row["views"] for row in rows if row.get("views") is not None]
    global_view_median = median(views_values) if views_values else None
    language_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    keyword_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        language_groups[row["language"]].append(row)
        context = row.get("seo_context") if isinstance(row.get("seo_context"), dict) else {}
        keyword = str(context.get("primary_keyword") or row.get("primary_keyword") or "").strip()
        if keyword:
            keyword_groups[keyword.casefold()].append(row)

    language_signals = []
    for language, group in sorted(language_groups.items()):
        percentages = [r["average_view_percentage"] for r in group if r.get("average_view_percentage") is not None]
        signal = {
            "language": language,
            "sample_count": len(group),
            "retention_sample_count": len(percentages),
            "median_views": round(median([r["views"] for r in group if r.get("views") is not None]), 2)
                if any(r.get("views") is not None for r in group) else None,
            "median_average_view_percentage": round(median(percentages), 2) if percentages else None,
            "relative_performance": "insufficient_data",
        }
        if len(percentages) >= minimum_group_size:
            all_percentages = [r["average_view_percentage"] for r in rows if r.get("average_view_percentage") is not None]
            overall = median(all_percentages) if all_percentages else None
            if overall is not None:
                signal["relative_performance"] = (
                    "above_channel_median" if signal["median_average_view_percentage"] > overall
                    else "below_channel_median"
                )
        language_signals.append(signal)

    keyword_signals = []
    for keyword, group in sorted(keyword_groups.items()):
        if len(group) < minimum_group_size:
            continue
        percentages = [r["average_view_percentage"] for r in group if r.get("average_view_percentage") is not None]
        keyword_signals.append({
            "keyword": keyword,
            "sample_count": len(group),
            "median_views": round(median([r["views"] for r in group if r.get("views") is not None]), 2)
                if any(r.get("views") is not None for r in group) else None,
            "median_average_view_percentage": round(median(percentages), 2) if percentages else None,
        })

    recommendations = []
    learned_languages = [item for item in language_signals if item["relative_performance"] == "above_channel_median"]
    if learned_languages:
        recommendations.append(
            "Give a small additional test allocation to " +
            ", ".join(item["language"] for item in learned_languages) +
            " searches; keep every configured language in the research mix."
        )
    if len(rows) < minimum_group_size:
        recommendations.append(
            "Learning sample is still small. Collect at least three comparable videos before changing SEO priorities."
        )
    if not any(row.get("average_view_percentage") is not None for row in rows):
        recommendations.append("Average percentage watched was unavailable; do not infer retention from views alone.")
    if search_term_signals:
        recommendations.append(
            "Feed actual YouTube search terms with views from at least three videos back into the next Discover run."
        )
    else:
        recommendations.append(
            "No usable actual YouTube search-term rows were returned; keep the balanced English, Hindi and Bengali mix."
        )

    top_rows = sorted(
        rows,
        key=lambda row: (
            row.get("average_view_percentage") if row.get("average_view_percentage") is not None else -1,
            row.get("views") if row.get("views") is not None else -1,
        ),
        reverse=True,
    )[:5]
    top_videos = []
    for row in top_rows:
        top_videos.append({
            "video_id": str(row.get("video_id") or row.get("video") or "")[:80],
            "title": str(row.get("title") or "")[:140],
            "language": row["language"],
            "views": row.get("views"),
            "average_view_percentage": row.get("average_view_percentage"),
            "average_view_duration_seconds": row.get("average_view_duration_seconds"),
            "primary_keyword": str((row.get("seo_context") or {}).get("primary_keyword") or row.get("primary_keyword") or "")[:100],
        })

    return {
        "engine_version": ENGINE_VERSION,
        "stage": "learn",
        "sample_count": len(rows),
        "learning_ready": len(rows) >= minimum_group_size,
        "period": report.get("period", {}),
        "metrics_used": available_metrics,
        "metrics_not_available": [] if any(r.get("thumbnail_impressions_ctr") is not None for r in rows) else ["thumbnail_impressions_ctr"],
        "median_views_for_sample": round(global_view_median, 2) if global_view_median is not None else None,
        "language_signals": language_signals,
        "keyword_signals": keyword_signals,
        "search_term_signals": search_term_signals,
        "search_term_learning_ready": bool(search_term_signals),
        "top_videos": top_videos,
        "recommendations": recommendations,
        "method_note": "Rules-based analysis of owner analytics reports. Correlation is directional, not proof of causation; small groups do not change query priority.",
    }
