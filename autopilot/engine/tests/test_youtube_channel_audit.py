"""Offline tests for the native YouTube uploads-playlist duplicate audit."""
from __future__ import annotations

import unittest

from youtube_channel_audit import (
    ChannelAuditError,
    DuplicateVideoFound,
    assert_title_absent,
    normalise_title,
    scan_uploads_playlist,
)


ENV = {
    "YOUTUBE_CLIENT_ID": "client-id",
    "YOUTUBE_CLIENT_SECRET": "client-secret",
    "YOUTUBE_REFRESH_TOKEN": "refresh-token",
    "YOUTUBE_EXPECTED_CHANNEL_ID": "UCGCfZij4Fn3Ga2j2HiCT45w",
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            from requests import HTTPError
            raise HTTPError(f"HTTP {self.status}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages=None, channel_id=None, fail_playlist=False):
        self.pages = pages or {}
        self.channel_id = channel_id or ENV["YOUTUBE_EXPECTED_CHANNEL_ID"]
        self.fail_playlist = fail_playlist
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return FakeResponse({"access_token": "test-access-token"})

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/channels"):
            return FakeResponse({
                "items": [{
                    "id": self.channel_id,
                    "contentDetails": {"relatedPlaylists": {"uploads": "uploads-playlist"}},
                }]
            })
        if url.endswith("/playlistItems"):
            if self.fail_playlist:
                return FakeResponse({"error": "denied"}, status=403)
            token = kwargs.get("params", {}).get("pageToken", "")
            return FakeResponse(self.pages.get(token, {"items": []}))
        raise AssertionError("Unexpected API endpoint: " + url)


class YouTubeChannelAuditTests(unittest.TestCase):
    def test_title_normalisation_ignores_case_and_repeated_whitespace(self):
        self.assertEqual(
            normalise_title("  Shape a   VIOLIN's Attack  "),
            normalise_title("shape a violin's attack"),
        )

    def test_complete_paginated_scan_passes_when_title_is_absent(self):
        session = FakeSession(pages={
            "": {
                "items": [{
                    "snippet": {"title": "Older video", "publishedAt": "2026-11-01T10:00:00Z"},
                    "contentDetails": {"videoId": "older123"},
                }],
                "nextPageToken": "page-2",
            },
            "page-2": {
                "items": [{
                    "snippet": {"title": "Another Short"},
                    "contentDetails": {"videoId": "another123"},
                }]
            },
        })
        result = assert_title_absent(
            "A completely new Short title",
            env=ENV,
            session=session,
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["uploads_checked_pages"], 2)
        self.assertEqual(result["uploads_examined"], 2)
        self.assertEqual(result["match_count"], 0)

    def test_matching_title_on_later_page_blocks(self):
        session = FakeSession(pages={
            "": {"items": [], "nextPageToken": "page-2"},
            "page-2": {
                "items": [{
                    "snippet": {
                        "title": "  SPLITEQ 2: Shape a Violin's Attack and Tone Separately ",
                        "publishedAt": "2026-11-20T18:53:17Z",
                    },
                    "contentDetails": {"videoId": "eb3D1Y9sSIM"},
                }]
            },
        })
        with self.assertRaises(DuplicateVideoFound) as caught:
            assert_title_absent(
                "SplitEQ 2: Shape a Violin's Attack and Tone Separately",
                env=ENV,
                session=session,
            )
        self.assertEqual(caught.exception.matches[0]["video_id"], "eb3D1Y9sSIM")

    def test_channel_identity_mismatch_fails_closed(self):
        session = FakeSession(channel_id="not-the-configured-channel")
        with self.assertRaisesRegex(ChannelAuditError, "did not verify"):
            scan_uploads_playlist(env=ENV, session=session)

    def test_playlist_api_error_fails_closed(self):
        session = FakeSession(fail_playlist=True)
        with self.assertRaisesRegex(ChannelAuditError, "uploads playlist request failed"):
            scan_uploads_playlist(env=ENV, session=session)

    def test_page_limit_fails_closed_instead_of_accepting_partial_scan(self):
        session = FakeSession(pages={
            "": {"items": [], "nextPageToken": "page-2"},
        })
        with self.assertRaisesRegex(ChannelAuditError, "page limit"):
            scan_uploads_playlist(env=ENV, session=session, max_pages=1)

    def test_missing_credentials_fail_before_api_calls(self):
        session = FakeSession()
        with self.assertRaisesRegex(ChannelAuditError, "YOUTUBE_REFRESH_TOKEN"):
            scan_uploads_playlist(
                env={"YOUTUBE_CLIENT_ID": "x", "YOUTUBE_CLIENT_SECRET": "y"},
                session=session,
            )
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
