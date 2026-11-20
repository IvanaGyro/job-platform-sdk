"""Opt-in, owner-only SQLite idempotency journal for the local HTTP API.

The journal protects against *replaying* an already-reserved operation after
process restart. Pending/uncertain operations persist as indeterminate and
are never retried. It does NOT provide a transaction with the remote 104
service, and a single HTTP server worker remains the supported setup.

Only keyed hashes of request identity and the route's existing fingerprint,
state, and successful safe result are retained. The database is private to
its operating-system owner; do not place it in a synced/public folder.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from typing import Any


class DuplicateReservationError(RuntimeError):
    """A second process reserved this key; never submit the same operation."""


class PersistentEntry(dict):
    """Cache entry whose in-place `update` commits before HTTP success reply."""

    def __init__(self, journal: 'SQLiteIdempotencyJournal', key: tuple[str, ...], value: dict):
        super().__init__(value)
        self._journal = journal
        self._key = key

    def update(self, *args, **kwargs) -> None:
        candidate = dict(self)
        candidate.update(*args, **kwargs)
        self._journal._update_existing(self._key, candidate)
        super().clear()
        super().update(candidate)

    def __setitem__(self, field, value) -> None:
        self.update({field: value})


class SQLiteIdempotencyJournal:
    """Small dict-compatible store for the service's idempotency records.

    The supported API is get/[]/[]= and PersistentEntry.update(). Keys are
    non-empty tuples of strings and are stored only as opaque keyed hashes.
    The local API's existing asyncio lock serializes per-worker calls;
    SQLite's PRIMARY KEY safely rejects competing process reservations.
    """

    def __init__(self, path: str | Path):
        # Windows ACL inspection is not provided by Python's os.stat() API.
        # Do not pretend POSIX 0600 gives equivalent security on Windows.
        if os.name == 'nt':
            raise NotImplementedError(
                'Persistent idempotency requires POSIX owner-only file permissions'
            )
        location = Path(path)
        if not location.is_absolute():
            raise ValueError('Idempotency database path must be absolute')
        if not location.parent.is_dir():
            raise ValueError('Idempotency database parent folder must exist')
        try:
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            fd = os.open(location, flags, 0o600)
        except FileExistsError:
            info = location.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                raise PermissionError('Idempotency database must be private owner-only regular file') from None
        else:
            os.close(fd)
        self._connection = sqlite3.connect(str(location), timeout=10, isolation_level=None)
        try:
            self._connection.execute('PRAGMA busy_timeout=10000')
            self._connection.execute('PRAGMA journal_mode=DELETE')
            self._connection.execute('PRAGMA synchronous=FULL')
            self._connection.execute('CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self._connection.execute('''CREATE TABLE IF NOT EXISTS idempotency (
                key_hash TEXT PRIMARY KEY, record_json TEXT NOT NULL
            )''')
            self._connection.execute('INSERT OR IGNORE INTO metadata (name,value) VALUES (?,?)',
                                     ('hmac_secret', secrets.token_hex(32)))
            raw = self._connection.execute('SELECT value FROM metadata WHERE name=?',
                                           ('hmac_secret',)).fetchone()[0]
            if type(raw) is not str or len(raw) != 64:
                raise ValueError('Idempotency journal key metadata invalid')
            self._secret = bytes.fromhex(raw)
        except Exception:
            self._connection.close()
            raise

    def _hash_key(self, key: tuple[str, ...]) -> str:
        if (not isinstance(key, tuple) or not key or
                any(type(part) is not str or not part for part in key)):
            raise TypeError('Idempotency key must be a tuple of nonempty strings')
        serialized = json.dumps(key, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
        return hmac.new(self._secret, serialized, hashlib.sha256).hexdigest()

    @staticmethod
    def _encode(record: dict) -> str:
        if (not isinstance(record, dict) or record.get('state') not in ('indeterminate', 'succeeded')
                or set(record) - {'state', 'result', 'fingerprint'}
                or (record['state'] == 'succeeded') != ('result' in record)
                or ('fingerprint' in record and (
                    type(record['fingerprint']) is not str or len(record['fingerprint']) != 64
                ))):
            raise ValueError('Invalid idempotency record')
        return json.dumps(record, sort_keys=True, ensure_ascii=True, allow_nan=False,
                          separators=(',', ':'))

    def __setitem__(self, key: tuple[str, ...], record: dict) -> None:
        digest = self._hash_key(key)
        encoded = self._encode(record)
        try:
            self._connection.execute('INSERT INTO idempotency (key_hash,record_json) VALUES (?,?)',
                                     (digest, encoded))
        except sqlite3.IntegrityError as exc:
            raise DuplicateReservationError('Idempotency key was already reserved') from exc

    def _update_existing(self, key: tuple[str, ...], record: dict) -> None:
        digest = self._hash_key(key)
        encoded = self._encode(record)
        # The journal must never convert an indeterminate result back to a
        # second remote operation. Update is only a state transition.
        with self._connection:
            row = self._connection.execute('SELECT record_json FROM idempotency WHERE key_hash=?',
                                           (digest,)).fetchone()
            if row is None:
                raise DuplicateReservationError('Missing reservation, refusing to acknowledge write')
            previous = json.loads(row[0])
            if previous.get('state') != 'indeterminate' or record.get('state') != 'succeeded':
                raise ValueError('Only pending to succeeded idempotency transition is allowed')
            if previous.get('fingerprint') != record.get('fingerprint'):
                raise ValueError('Idempotency operation fingerprint changed')
            changed = self._connection.execute(
                'UPDATE idempotency SET record_json=? WHERE key_hash=? AND record_json=?',
                (encoded, digest, row[0]),
            )
            if changed.rowcount != 1:
                raise DuplicateReservationError('Idempotency state changed concurrently')

    def __getitem__(self, key: tuple[str, ...]) -> PersistentEntry:
        row = self._connection.execute('SELECT record_json FROM idempotency WHERE key_hash=?',
                                       (self._hash_key(key),)).fetchone()
        if row is None:
            raise KeyError(key)
        value: Any = json.loads(row[0])
        self._encode(value)  # fail closed on journal corruption
        return PersistentEntry(self, key, value)

    def get(self, key: tuple[str, ...], default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
