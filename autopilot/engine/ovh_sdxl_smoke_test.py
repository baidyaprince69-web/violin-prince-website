#!/usr/bin/env python3
"""One-request smoke test for OVHcloud's free anonymous SDXL endpoint.

This is a diagnostic only. It does not unlock the production illustration gate
or upload the generated preview anywhere except a short-lived Actions artifact.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

import requests
from PIL import Image

API_URL = "https://stable-diffusion-xl.endpoints.kepler.ai.cloud.ovh.net/api/text2image"
MODEL = "stable-diffusion-xl-base-v10"

PROMPT = (
    "Premium 2D editorial illustration for a violin music explainer: one taut violin "
    "string visibly vibrating above a detailed warm-ivory wooden bridge, subtle antique "
    "gold resonance waves, midnight-navy background, muted teal and antique-gold palette, "
    "confident contour linework, layered painted shading, refined educational illustration, "
    "clear composition, no text, no typography, no logo, no watermark"
)
NEGATIVE_PROMPT = (
    "photograph, photorealistic, 3D render, CGI, malformed violin, extra strings, "
    "deformed bridge, duplicate objects, text, letters, logos, watermarks, border"
)


def generate_preview(output_path: Path) -> dict:
    """Generate one image without requiring or creating an account credential."""
    headers = {
        "Accept": "application/octet-stream",
        "Content-Type": "application/json",
        "User-Agent": "ViolinPrince-IllustrationProvider-SmokeTest/1.0",
    }
    token = os.environ.get("OVH_AI_ENDPOINTS_ACCESS_TOKEN", "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token

    try:
        response = requests.post(
            API_URL,
            headers=headers,
            json={"prompt": PROMPT, "negative_prompt": NEGATIVE_PROMPT},
            timeout=(20, 180),
        )
    except requests.RequestException as exc:
        raise RuntimeError("Could not reach the OVHcloud SDXL endpoint.") from exc

    if response.status_code != 200:
        detail = " ".join(response.text.split())[:300]
        raise RuntimeError(
            f"OVHcloud SDXL returned HTTP {response.status_code}: {detail or 'no response body'}"
        )

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        raise RuntimeError(
            f"Expected image bytes from OVHcloud SDXL, received Content-Type {content_type or '[missing]'}."
        )
    if not response.content or len(response.content) > 20 * 1024 * 1024:
        raise RuntimeError("The returned image is empty or exceeds the 20 MB safety limit.")

    try:
        image = Image.open(io.BytesIO(response.content))
        image.verify()
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception as exc:
        raise RuntimeError("OVHcloud SDXL returned an image that Pillow could not verify.") from exc

    if image.size != (1024, 1024):
        raise RuntimeError(f"Expected a 1024x1024 image, received {image.width}x{image.height}.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return {
        "provider": "OVHcloud AI Endpoints",
        "model": MODEL,
        "status": "passed",
        "dimensions": f"{image.width}x{image.height}",
        "source_content_type": content_type,
        "output_bytes": output_path.stat().st_size,
        "anonymous_mode": not bool(token),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="work/ovh-sdxl-preview.png")
    args = parser.parse_args()
    try:
        result = generate_preview(Path(args.output))
    except Exception as exc:
        print("OVHcloud SDXL smoke test failed: " + str(exc), file=sys.stderr)
        return 1
    print("OVHcloud SDXL smoke test passed.")
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
