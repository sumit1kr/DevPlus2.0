from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

try:
    from langchain_groq import ChatGroq
except Exception:  # pragma: no cover
    ChatGroq = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception:  # pragma: no cover
    ChatGoogleGenerativeAI = None


class LLMRouter:
    def __init__(self) -> None:
        self._provider_state: Dict[str, Dict[str, float]] = {
            "groq": {"fail_count": 0.0, "blocked_until": 0.0},
            "gemini": {"fail_count": 0.0, "blocked_until": 0.0},
        }
        self.groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.max_retries = 2
        self.base_backoff_seconds = 0.8
        self.cooldown_seconds = 25
        self.last_provider: str = ""
        self.last_attempts: int = 0
        self.last_token_count: int | None = None
        self.last_fallback_reason: str = ""

    def available(self) -> bool:
        return bool((self.groq_api_key and ChatGroq) or (self.gemini_api_key and ChatGoogleGenerativeAI))

    def invoke_json(
        self,
        system_prompt: str,
        user_prompt: str,
        primary: str = "groq",
        fallback: str = "gemini",
        temperature: float = 0.0,
        required_keys: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        text = self.invoke_text(system_prompt, user_prompt, primary, fallback, temperature)
        if not text:
            return {}

        try:
            payload = json.loads(text)
            return payload if self._has_required_keys(payload, required_keys) else {}
        except Exception:
            # Attempt to salvage fenced JSON.
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    payload = json.loads(text[start : end + 1])
                    return payload if self._has_required_keys(payload, required_keys) else {}
                except Exception:
                    return {}
            return {}

    def invoke_text(
        self,
        system_prompt: str,
        user_prompt: str,
        primary: str,
        fallback: str,
        temperature: float,
    ) -> str:
        self.last_provider = ""
        self.last_attempts = 0
        self.last_token_count = None
        self.last_fallback_reason = ""
        for provider in (primary, fallback):
            if self._is_provider_blocked(provider):
                continue
            model = self._build_model(provider, temperature)
            if model is None:
                continue
            for attempt in range(self.max_retries + 1):
                self.last_attempts += 1
                try:
                    response = model.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
                    self._record_success(provider)
                    self.last_provider = provider
                    self.last_token_count = self._extract_tokens(response)
                    if provider != primary:
                        self.last_fallback_reason = "primary_failed_or_unavailable"
                    return str(response.content)
                except Exception:
                    self._record_failure(provider)
                    if attempt < self.max_retries:
                        time.sleep(self.base_backoff_seconds * (attempt + 1))
            self._block_provider(provider)
        return ""

    def _extract_tokens(self, response: Any) -> int | None:
        try:
            usage = getattr(response, "usage_metadata", None) or getattr(response, "response_metadata", {}).get("token_usage", {})
            if not usage:
                return None
            for key in ("total_tokens", "total_token_count", "token_count"):
                if key in usage and isinstance(usage[key], int):
                    return int(usage[key])
            input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("input_token_count") or 0
            output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or usage.get("output_token_count") or 0
            total = int(input_tokens) + int(output_tokens)
            return total if total > 0 else None
        except Exception:
            return None

    def _has_required_keys(self, payload: Any, required_keys: Optional[list[str]]) -> bool:
        if not required_keys:
            return isinstance(payload, dict)
        if not isinstance(payload, dict):
            return False
        return all(k in payload for k in required_keys)

    def _is_provider_blocked(self, provider: str) -> bool:
        blocked_until = self._provider_state.get(provider, {}).get("blocked_until", 0.0)
        return blocked_until > time.time()

    def _block_provider(self, provider: str) -> None:
        if provider not in self._provider_state:
            return
        self._provider_state[provider]["blocked_until"] = time.time() + self.cooldown_seconds

    def _record_success(self, provider: str) -> None:
        if provider not in self._provider_state:
            return
        self._provider_state[provider]["fail_count"] = 0.0
        self._provider_state[provider]["blocked_until"] = 0.0

    def _record_failure(self, provider: str) -> None:
        if provider not in self._provider_state:
            return
        self._provider_state[provider]["fail_count"] += 1.0

    def _build_model(self, provider: str, temperature: float) -> Optional[Any]:
        if provider == "groq" and self.groq_api_key and ChatGroq:
            return ChatGroq(
                api_key=self.groq_api_key,
                model="llama-3.3-70b-versatile",
                temperature=temperature,
            )
        if provider == "gemini" and self.gemini_api_key and ChatGoogleGenerativeAI:
            return ChatGoogleGenerativeAI(
                api_key=self.gemini_api_key,
                model="gemini-1.5-flash",
                temperature=temperature,
            )
        return None
