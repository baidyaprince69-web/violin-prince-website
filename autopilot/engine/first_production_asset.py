"""Fetch a genuinely downloadable CC0 violin mesh for the first Blender production.

The resolver only follows public download links exposed by the providers' pages.
It does not scrape interactive viewers, bypass authentication, or guess protected URLs.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests

PROVIDERS = [
    {
        "name": "Grab3D",
        "page": "https://grab3d.com/models/music/violin/",
        "license_markers": ("cc0", "cc0-1.0", "no attribution"),
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    },
    {
        "name": "Innerscene",
        "page": "https://www.innerscene.com/tools/library/3d-parts/violin-f404517d",
        "license_markers": ("cc0", "public domain"),
        "license": "CC0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    },
]
MAX_BYTES = 40 * 1024 * 1024
USER_AGENT = "ViolinPrinceProduction/1.0 (licensed public model downloader)"


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.text_parts = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            href = attrs.get("href")
            if href:
                self.links.append((href, " ".join(
                    str(attrs.get(key) or "") for key in ("download", "title", "aria-label", "class")
                )))
        if tag == "script":
            self._in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.text_parts.append(data)


def _normalise_url(value: str, base: str) -> str | None:
    value = html.unescape(str(value or "")).replace("\\/", "/").replace("\\u002F", "/")
    value = value.replace("\\u0026", "&")
    value = value.strip().strip("\"'")
    if not value:
        return None
    url = urljoin(base, value)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return url


def _find_candidates(source: str, collector: LinkCollector, base: str) -> list[str]:
    raw: list[tuple[str, str]] = list(collector.links)
    for script in collector.text_parts:
        raw.extend((match, "embedded model data") for match in re.findall(
            r"""(?P<url>(?:https?:)?//[^"'<>\\\s]{1,700}\.glb(?:\?[^"'<>\\\s]*)?|/[^"'<>\\\s]{1,700}\.glb(?:\?[^"'<>\\\s]*)?)""",
            script, flags=re.IGNORECASE
        ))
    decoded = source.replace("\\/", "/").replace("\\u002F", "/")
    raw.extend((match, "page source") for match in re.findall(
        r"""(?P<url>(?:https?:)?//[^"'<>\\\s]{1,700}\.glb(?:\?[^"'<>\\\s]*)?|/[^"'<>\\\s]{1,700}\.glb(?:\?[^"'<>\\\s]*)?)""",
        decoded, flags=re.IGNORECASE
    ))

    candidates = []
    seen = set()
    for href, label in raw:
        url = _normalise_url(href, base)
        if not url or url in seen:
            continue
        lowered = (url + " " + label).casefold()
        if ".glb" not in lowered and not (
            "download" in lowered and "glb" in lowered
        ):
            continue
        seen.add(url)
        candidates.append(url)
    return candidates


def _download_candidate(session: requests.Session, url: str, folder: Path) -> Path:
    with session.get(url, stream=True, allow_redirects=True, timeout=(15, 90)) as response:
        response.raise_for_status()
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_BYTES:
            raise RuntimeError(f"Model download is larger than {MAX_BYTES // (1024 * 1024)} MB.")
        destination = folder / "violin.glb.part"
        total = 0
        with destination.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_BYTES:
                    destination.unlink(missing_ok=True)
                    raise RuntimeError("Model download exceeded the configured size limit.")
                output.write(chunk)

    with destination.open("rb") as model:
        magic = model.read(4)
    if magic != b"glTF":
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            "The candidate did not return a binary glTF model (GLB). "
            f"Final URL: {response.url}; content type: {response.headers.get('Content-Type')}"
        )
    final_path = folder / "violin.glb"
    destination.replace(final_path)
    return final_path


def resolve_cc0_violin(output_dir: str | Path) -> dict:
    folder = Path(output_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    attempts = []

    for provider in PROVIDERS:
        try:
            page = session.get(provider["page"], timeout=(15, 45))
            page.raise_for_status()
            source = page.text
            lower = source.casefold()
            if not any(marker in lower for marker in provider["license_markers"]):
                raise RuntimeError("The provider page did not expose the expected CC0/public-domain licence text.")

            collector = LinkCollector()
            collector.feed(source)
            candidates = _find_candidates(source, collector, page.url)
            if not candidates:
                # Keep only public links from the page for diagnostics; never invent a model URL.
                public_links = [
                    _normalise_url(href, page.url)
                    for href, _label in collector.links
                ]
                public_links = [
                    value for value in public_links
                    if value and urlparse(value).hostname == urlparse(page.url).hostname
                ]
                attempts.append({
                    "provider": provider["name"],
                    "reason": "No public GLB download link exposed in provider HTML.",
                    "public_links": public_links[:20],
                    "page_title": re.search(r"<title[^>]*>(.*?)</title>", source, re.I | re.S).group(1).strip()
                    if re.search(r"<title[^>]*>(.*?)</title>", source, re.I | re.S) else "",
                    "source_markers": [
                        word for word in ("glb", "download", "violin.glb", "cc0")
                        if word in lower
                    ],
                })
                continue

            errors = []
            for url in candidates:
                try:
                    model_path = _download_candidate(session, url, folder)
                    payload = model_path.read_bytes()
                    record = {
                        "provider": provider["name"],
                        "model_name": "Violin",
                        "source_url": provider["page"],
                        "download_url": url,
                        "license": provider["license"],
                        "license_url": provider["license_url"],
                        "commercial_use_allowed": True,
                        "attribution_required": False,
                        "model_format": "GLB",
                        "model_path": str(model_path),
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "resolution": "downloaded_model",
                    }
                    manifest = folder / "asset-provenance.json"
                    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    record["manifest_path"] = str(manifest)
                    return record
                except Exception as exc:
                    errors.append({"url": url, "error": str(exc)[:350]})
            attempts.append({
                "provider": provider["name"],
                "reason": "All public GLB download candidates failed validation.",
                "candidate_errors": errors[:10],
            })
        except Exception as exc:
            attempts.append({"provider": provider["name"], "reason": str(exc)[:700]})

    diagnostic = folder / "asset-resolution-diagnostic.json"
    diagnostic.write_text(json.dumps(attempts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise RuntimeError(
        "No verified CC0 violin GLB could be downloaded. Diagnostic: "
        + str(diagnostic) + " | " + json.dumps(attempts, ensure_ascii=False)[:1800]
    )


if __name__ == "__main__":
    try:
        result = resolve_cc0_violin(sys.argv[1] if len(sys.argv) > 1 else "work/first-production/assets")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print("CC0 violin asset resolution failed: " + str(exc), file=sys.stderr)
        raise
