"""ISBN 查询结果的轻量级 SQLite 缓存。"""

import json
import os
import sqlite3
import threading
import time


DEFAULT_POSITIVE_TTL = 90 * 24 * 60 * 60
DEFAULT_NEGATIVE_TTL = 24 * 60 * 60


class QueryCache:
    """按 ISBN 缓存查询成功和未收录结果。"""

    def __init__(
        self,
        path=None,
        positive_ttl=DEFAULT_POSITIVE_TTL,
        negative_ttl=DEFAULT_NEGATIVE_TTL,
        clock=time.time,
    ):
        default_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data",
            "query_cache.sqlite3",
        )
        self.path = path or os.environ.get("ISBN_CLC_CACHE_PATH", default_path)
        self.positive_ttl = positive_ttl
        self.negative_ttl = negative_ttl
        self.clock = clock
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS isbn_query_cache (
                    isbn TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload TEXT,
                    cached_at REAL NOT NULL
                )
                """
            )

    def get(self, isbn):
        """返回 ``(是否命中, 值)``；未收录的缓存值为 ``None``。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, payload, cached_at FROM isbn_query_cache WHERE isbn = ?",
                (isbn,),
            ).fetchone()

            if row is None:
                return False, None

            status, payload, cached_at = row
            ttl = self.positive_ttl if status == "success" else self.negative_ttl
            if self.clock() - cached_at > ttl:
                connection.execute(
                    "DELETE FROM isbn_query_cache WHERE isbn = ?",
                    (isbn,),
                )
                return False, None

            if status == "not_found":
                return True, None

            try:
                return True, json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                connection.execute(
                    "DELETE FROM isbn_query_cache WHERE isbn = ?",
                    (isbn,),
                )
                return False, None

    def set_success(self, isbn, result):
        payload = json.dumps(result, ensure_ascii=False)
        self._set(isbn, "success", payload)

    def set_not_found(self, isbn):
        self._set(isbn, "not_found", None)

    def _set(self, isbn, status, payload):
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO isbn_query_cache (isbn, status, payload, cached_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(isbn) DO UPDATE SET
                    status = excluded.status,
                    payload = excluded.payload,
                    cached_at = excluded.cached_at
                """,
                (isbn, status, payload, self.clock()),
            )

    def clear(self):
        with self._connect() as connection:
            connection.execute("DELETE FROM isbn_query_cache")


_default_cache = None
_default_cache_lock = threading.Lock()


def get_default_cache():
    global _default_cache
    if _default_cache is None:
        with _default_cache_lock:
            if _default_cache is None:
                _default_cache = QueryCache()
    return _default_cache
