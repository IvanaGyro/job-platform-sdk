"""Durable at-most-once HTTP mutation guard without storing resume data.

The SQLite file stores only SHA-256 hashes of the request identity and
request fingerprint. It records a reservation before a remote mutation.
After restart, any reserved key returns an indeterminate/tombstoned state:
never re-submit the mutation automatically, whether it previously succeeded
or failed. Successful response replays are only possible in the same process
using the separate in-memory result cache.

Protection is optional and intended for a local single-service deployment.
It does not reconcile uncertain upstream commits or make multiple requests
atomic.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from fastapi import HTTPException


class DurableIdempotencyLedger:
    """Dict-compatible get and assignment API for the 104 HTTP service."""

    def __init__(self, file_path: str):
        path = Path(file_path).expanduser()
        parent = path.parent
        if not parent.is_dir():
            raise ValueError("Idempotency database parent directory must exist")
        if parent.stat().st_mode & 0o002:
            raise ValueError("Idempotency database directory must not be world writable")
        if path.is_symlink():
            raise ValueError("Idempotency database must not be a symbolic link")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self._conn = sqlite3.connect(str(path), isolation_level=None)
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS mutation_reservations (
                request_key_hash TEXT PRIMARY KEY,
                fingerprint TEXT
            )
        """)
        self._current: dict[tuple[Any, ...], dict] = {}

    @staticmethod
    def _hashed_key(key: tuple[Any, ...]) -> str:
        if not isinstance(key, tuple):
            raise ValueError("Idempotency key must be a tuple")
        serialized = json.dumps(
            key, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    def get(self, key: tuple[Any, ...], default=None):
        """Persisted keys are intentionally not replayable after restart."""
        if key in self._current:
            return self._current[key]
        digest = self._hashed_key(key)
        row = self._conn.execute(
            "SELECT fingerprint FROM mutation_reservations WHERE request_key_hash = ?",
            (digest,),
        ).fetchone()
        if row is None:
            return default
        return {"fingerprint": row[0], "state": "indeterminate"}

    def __setitem__(self, key: tuple[Any, ...], value: dict) -> None:
        if not isinstance(value, dict) or value.get("state") not in {
            "indeterminate", "succeeded",
        }:
            raise ValueError("Unsupported idempotency reservation state")
        if key not in self._current:
            digest = self._hashed_key(key)
            fingerprint = value.get("fingerprint")
            if fingerprint is not None and (
                not isinstance(fingerprint, str) or len(fingerprint) != 64
            ):
                raise ValueError("Idempotency fingerprint must be SHA-256")
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO mutation_reservations "
                "(request_key_hash, fingerprint) VALUES (?, ?)",
                (digest, fingerprint),
            )
            if cursor.rowcount != 1:
                raise HTTPException(
                    409, "Previously used idempotency key; inspect remote state",
                )
        # Response bodies (which can contain resume data) exist only in memory.
        self._current[key] = value

    def close(self):
        self._conn.close()
