from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from state.state import default_state


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_observation(result: Dict[str, Any]) -> Dict[str, Any]:
    score_breakdown = result.get("score_breakdown", {}) or {}
    coverage = result.get("scan_coverage", {}) or {}
    warnings = result.get("warnings", []) or []

    source_candidates = int(coverage.get("source_candidates", 0) or 0)
    source_fetched = int(coverage.get("source_fetched", 0) or 0)
    coverage_ratio = (source_fetched / source_candidates) if source_candidates > 0 else 1.0

    return {
        "overall_score": int(score_breakdown.get("overall", 0) or 0),
        "analysis_mode": str(result.get("analysis_mode", "repo")),
        "warnings_count": len(warnings),
        "source_coverage_ratio": round(coverage_ratio, 3),
        "errors_count": len(result.get("errors", []) or []),
    }


def _should_refine(result: Dict[str, Any], current_depth: int, max_depth: int) -> bool:
    if current_depth >= max_depth:
        return False

    coverage = result.get("scan_coverage", {}) or {}
    source_candidates = int(coverage.get("source_candidates", 0) or 0)
    source_fetched = int(coverage.get("source_fetched", 0) or 0)
    coverage_ratio = (source_fetched / source_candidates) if source_candidates > 0 else 1.0

    warnings = [str(w) for w in (result.get("warnings", []) or [])]
    has_partial_scan_warning = any(
        w.startswith("Partial source scan") or w.startswith("Adaptive scan depth")
        for w in warnings
    )

    return bool(has_partial_scan_warning or coverage_ratio < 0.6)


def run_meta_controller(
    *,
    repo_url: str,
    scan_depth: int,
    report_graph: Any,
    max_iterations: int = 2,
    max_scan_depth: int = 80,
) -> Dict[str, Any]:
    logs: List[Dict[str, Any]] = []
    depth = max(10, int(scan_depth))
    result: Dict[str, Any] = {}

    for iteration in range(1, max_iterations + 1):
        thought = (
            "Decide the next analysis action based on current scan coverage and prior observations."
            if iteration > 1
            else "Start a baseline repository audit run with the requested scan depth."
        )
        action = {
            "tool": "devpulse_graph.invoke",
            "params": {
                "repo_url": repo_url,
                "scan_depth": depth,
            },
        }

        started_at = _utc_now()
        result = report_graph.invoke(default_state(repo_url=repo_url, scan_depth=depth))
        ended_at = _utc_now()

        observation = _make_observation(result)
        logs.append(
            {
                "step": iteration,
                "start_time": started_at,
                "end_time": ended_at,
                "thought": thought,
                "action": action,
                "observation": observation,
            }
        )

        if not _should_refine(result, depth, max_scan_depth):
            break

        depth = min(max_scan_depth, depth + 15)

    final_thought = "Stop the loop and return the final structured result with controller trace."
    final_observation = _make_observation(result)
    logs.append(
        {
            "step": len(logs) + 1,
            "start_time": _utc_now(),
            "end_time": _utc_now(),
            "thought": final_thought,
            "action": {
                "tool": "finalize",
                "params": {
                    "iterations_executed": len(logs),
                },
            },
            "observation": final_observation,
        }
    )

    return {
        **result,
        "meta_loop_trace": logs,
    }