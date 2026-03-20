from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any


CACHE_DIR = os.path.join(os.getcwd(), ".cache", "devpulse")


def _cache_file(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"{digest}.json")


def get_cache(key: str, ttl_seconds: int) -> Any:
    path = _cache_file(key)
    if not os.path.exists(path):
        return None

    try:
        payload = json.loads(open(path, "r", encoding="utf-8").read())
    except Exception:
        return None

    created = float(payload.get("created", 0))
    if time.time() - created > ttl_seconds:
        return None
    return payload.get("data")


def set_cache(key: str, data: Any) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_file(key)
    payload = {"created": time.time(), "data": data}
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(payload))
