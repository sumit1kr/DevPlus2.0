from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests


def request_with_retry(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    json_payload: Optional[Dict[str, Any]] = None,
    timeout: int = 20,
    retries: int = 3,
    backoff_seconds: float = 0.8,
) -> requests.Response:
    last_exc: Exception | None = None
    response: requests.Response | None = None

    for attempt in range(retries + 1):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_payload,
                timeout=timeout,
            )
            if response.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(backoff_seconds * (attempt + 1))
                continue
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff_seconds * (attempt + 1))
                continue
            raise

    if response is not None:
        return response
    raise RuntimeError(f"request failed and no response available: {last_exc}")
