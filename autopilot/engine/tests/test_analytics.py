"""Offline checks for Phase 5 report parsing and safe no-credential behavior."""
import os
import unittest
from unittest.mock import patch

from autopilot.engine.analytics import _number, _report_rows, _youtube_search_terms, collect_and_send


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSearchTermsSession:
    def __init__(self):
        self.calls = []

    def get(self, url, headers, params, timeout):
        self.calls.append((url, dict(params)))
        return FakeResponse({
            "columnHeaders": [
                {"name": "insightTrafficSourceDetail"},
                {"name": "views"},
            ],
            "rows": [["violin cover search phrase", 12]],
        })


class AnalyticsParsingTests(unittest.TestCase):
    def test_report_rows_map_column_headers_to_values(self):
        report = {
            "columnHeaders": [{"name": "video"}, {"name": "views"}, {"name": "averageViewPercentage"}],
            "rows": [["video-1", 120, 67.5]],
        }
        self.assertEqual(_report_rows(report), [{
            "video": "video-1",
            "views": 120,
            "averageViewPercentage": 67.5,
        }])

    def test_numeric_values_are_parsed_without_fabricating_missing_metrics(self):
        self.assertEqual(_number({"views": "125"}, "views"), 125.0)
        self.assertIsNone(_number({"views": None}, "views"))
        self.assertIsNone(_number({}, "thumbnail_impressions_ctr"))

    def test_youtube_search_terms_are_collected_separately_by_video_language(self):
        session = FakeSearchTermsSession()
        videos = []
        for language in ("en", "hi", "bn"):
            for index in range(3):
                videos.append({
                    "video_id": language + "-" + str(index),
                    "default_language": language,
                    "title": "Channel video " + str(index),
                })
        terms, report = _youtube_search_terms(
            session, "fake-token", "2026-10-17", "2026-11-13", videos
        )
        self.assertEqual(len(session.calls), 3)
        self.assertEqual({item["language"] for item in terms}, {"en", "hi", "bn"})
        self.assertTrue(all(item["video_sample_count"] == 3 for item in terms))
        self.assertTrue(report["available"])
        for _url, params in session.calls:
            self.assertEqual(params["dimensions"], "insightTrafficSourceDetail")
            self.assertIn("insightTrafficSourceType==YT_SEARCH", params["filters"])
            self.assertEqual(params["maxResults"], 10)

    def test_collector_skips_before_network_when_oauth_credentials_are_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            result = collect_and_send("https://example.invalid", "unused")
        self.assertFalse(result["connected"])
        self.assertEqual(result["reason"], "credentials_missing")


if __name__ == "__main__":
    unittest.main()
