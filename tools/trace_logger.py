from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Dict, List


class TraceLogger:
    def __init__(self, agent_name: str, state: Dict[str, Any] | None = None) -> None:
        self.agent_name = agent_name
        self.started_at_ts = time.perf_counter()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.tool_calls: List[Dict[str, Any]] = []
        self.input_summary = self._truncate(self._summarize_state(state or {}))

    def add_tool_call(self, name: str, args: Dict[str, Any] | None = None) -> None:
        self.tool_calls.append(
            {
                "name": name,
                "args": args or {},
            }
        )

    def finalize(
        self,
        *,
        status: str,
        output: Dict[str, Any] | None = None,
        token_count: int | None = None,
        fallback_reason: str | None = None,
    ) -> Dict[str, Any]:
        ended_at = datetime.now(timezone.utc).isoformat()
        duration_ms = int((time.perf_counter() - self.started_at_ts) * 1000)
        return {
            "agent": self.agent_name,
            "start_time": self.started_at,
            "end_time": ended_at,
            "duration_ms": duration_ms,
            "status": status,
            "input_summary": self.input_summary,
            "output_summary": self._truncate(self._summarize_state(output or {})),
            "tool_calls": self.tool_calls,
            "token_count": token_count,
            "fallback_reason": fallback_reason or "",
        }

    def _summarize_state(self, payload: Dict[str, Any]) -> str:
        if not payload:
            return "empty"

        parts: List[str] = []
        for key in sorted(payload.keys()):
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)) or value is None:
                text = str(value)
                parts.append(f"{key}={text[:80]}")
            elif isinstance(value, list):
                parts.append(f"{key}[len={len(value)}]")
            elif isinstance(value, dict):
                parts.append(f"{key}{{keys={len(value)}}}")
            else:
                parts.append(f"{key}<{type(value).__name__}>")
        return "; ".join(parts)

    def _truncate(self, text: str, limit: int = 600) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."
