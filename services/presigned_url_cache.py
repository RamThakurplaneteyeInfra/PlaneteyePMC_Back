"""
In-process cache for presigned S3 URLs.

Signing is a local SigV4 operation (~1 ms). Caching those URLs in a remote
Redis instance (often 200–1000+ ms RTT from a laptop, and still non-trivial
cross-region) made View/download endpoints *slower* than signing every time.

This module keeps a small process-local TTL map so hot keys reuse URLs until
near expiry without a network hop. Never caches past URL lifetime.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

_lock = threading.Lock()
# key -> (url, expires_at_monotonic)
_store: dict[str, tuple[str, float]] = {}
_MAX_ENTRIES = 2048


def cached_presigned_url(
    *,
    cache_namespace: str,
    s3_key: str,
    expires_in: int,
    generator: Callable[..., str],
) -> str:
    """
    Return a presigned URL, reusing a local cached value when still fresh.

    Cache TTL is slightly shorter than *expires_in* so clients never receive
    a URL that is about to expire.
    """
    if not s3_key:
        return generator(s3_key, expires_in=expires_in)

    key_hash = hashlib.sha256(s3_key.encode("utf-8")).hexdigest()[:32]
    cache_key = f"{cache_namespace}:{expires_in}:{key_hash}"
    now = time.monotonic()
    ttl = max(int(expires_in) - 60, 30)

    with _lock:
        hit = _store.get(cache_key)
        if hit is not None:
            url, expires_at = hit
            if expires_at > now:
                return url
            _store.pop(cache_key, None)

    url = generator(s3_key, expires_in=expires_in)

    with _lock:
        if len(_store) >= _MAX_ENTRIES:
            # Drop expired first; if still full, clear oldest half.
            expired = [k for k, (_, exp) in _store.items() if exp <= now]
            for k in expired:
                _store.pop(k, None)
            if len(_store) >= _MAX_ENTRIES:
                for k in list(_store.keys())[: _MAX_ENTRIES // 2]:
                    _store.pop(k, None)
        _store[cache_key] = (url, now + ttl)

    return url
