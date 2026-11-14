"""Encrypted, GitHub-native persistence for SEO-only YouTube learning signals.

The repository is public, so only AES-256-GCM ciphertext is committed to the
seo-learning-data branch. Raw channel analytics and OAuth credentials are never
written to the branch or to the Actions summary.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AAD = b"violin-prince-seo-learning-v1"
KEY_CONTEXT = b"violin-prince-seo-learning-key-v1\0"


def _derive_key(root_key_b64: str) -> bytes:
    """Derive a purpose-specific AES key from the existing 32-byte upload key."""
    value = str(root_key_b64 or "").strip()
    try:
        padded = value + "=" * (-len(value) % 4)
        root_key = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:
        raise ValueError(
            "YOUTUBE_STATE_ENCRYPTION_KEY must be URL-safe base64 for 32 random bytes."
        ) from exc
    if len(root_key) != 32:
        raise ValueError(
            "YOUTUBE_STATE_ENCRYPTION_KEY must decode to exactly 32 bytes."
        )
    return hashlib.sha256(KEY_CONTEXT + root_key).digest()


def encrypt_learning_snapshot(snapshot: dict[str, Any], root_key_b64: str) -> dict[str, Any]:
    """Return a JSON-safe AES-256-GCM envelope; never return plaintext analytics."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("seo_learning"), dict):
        raise ValueError("SEO learning snapshot must contain a seo_learning object.")
    key = _derive_key(root_key_b64)
    nonce = os.urandom(12)
    plaintext = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, AAD)
    return {
        "version": 1,
        "algorithm": "AES-256-GCM",
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def write_encrypted_snapshot(
    snapshot: dict[str, Any],
    path: str | Path,
    root_key_b64: str,
) -> Path:
    """Atomically write an encrypted snapshot to a workflow-local file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    envelope = encrypt_learning_snapshot(snapshot, root_key_b64)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(envelope, separators=(",", ":")), encoding="utf-8"
    )
    os.replace(temporary, target)
    return target


def read_encrypted_snapshot(
    path: str | Path,
    root_key_b64: str,
) -> dict[str, Any] | None:
    """Decrypt one committed snapshot; return None only when no snapshot exists."""
    target = Path(path)
    if not target.is_file():
        return None
    try:
        envelope = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(envelope, dict) or envelope.get("version") != 1:
            raise ValueError("Unsupported encrypted SEO snapshot version.")
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        if len(nonce) != 12:
            raise ValueError("Invalid SEO snapshot nonce.")
        plaintext = AESGCM(_derive_key(root_key_b64)).decrypt(nonce, ciphertext, AAD)
        snapshot = json.loads(plaintext.decode("utf-8"))
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("seo_learning"), dict):
            raise ValueError("Decrypted SEO snapshot has an invalid schema.")
        return snapshot
    except Exception as exc:
        raise ValueError(
            "Encrypted SEO learning snapshot is corrupt or the encryption key is incorrect."
        ) from exc


def load_learning_signals(
    path: str | Path,
    root_key_b64: str,
) -> dict[str, Any] | None:
    """Return only the SEO signals consumed by Discover, never the full report."""
    snapshot = read_encrypted_snapshot(path, root_key_b64)
    if snapshot is None:
        return None
    learning = dict(snapshot["seo_learning"])
    learning["captured_at"] = snapshot.get("captured_at")
    return learning
