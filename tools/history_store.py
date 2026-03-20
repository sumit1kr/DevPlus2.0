from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HISTORY_DIR = os.path.join(ROOT_DIR, ".devpulse_history")


def _history_file(owner: str, repo: str) -> str:
    safe_owner = str(owner).strip().replace("/", "_")
    safe_repo = str(repo).strip().replace("/", "_")
    return os.path.join(HISTORY_DIR, f"{safe_owner}_{safe_repo}.json")


def load_scan_history(owner: str, repo: str) -> List[Dict[str, Any]]:
    path = _history_file(owner, repo)
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []

    if not isinstance(payload, list):
        return []

    records: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "timestamp": str(item.get("timestamp", "")),
                "overall_score": int(item.get("overall_score", 0)),
                "code_quality": int(item.get("code_quality", 0)),
                "dependency": int(item.get("dependency", 0)),
                "git_history": int(item.get("git_history", 0)),
                "penalty_total": int(item.get("penalty_total", 0)),
            }
        )

    records = [
        r for r in records
        if isinstance(r.get("overall_score"), int)
        and r.get("overall_score", 0) > 0
        and str(r.get("timestamp", "")).strip() != ""
    ]

    records.sort(key=lambda x: x.get("timestamp", ""))
    return records


def save_scan_result(owner: str, repo: str, score_breakdown: Dict[str, Any], timestamp: str) -> None:
    os.makedirs(HISTORY_DIR, exist_ok=True)

    records = load_scan_history(owner, repo)
    record = {
        "timestamp": timestamp or (datetime.utcnow().isoformat() + "Z"),
        "overall_score": int(score_breakdown.get("overall", 0)),
        "code_quality": int(score_breakdown.get("code_quality", 0)),
        "dependency": int(score_breakdown.get("dependency", 0)),
        "git_history": int(score_breakdown.get("git_history", 0)),
        "penalty_total": int(score_breakdown.get("penalty_total", 0)),
    }
    records.append(record)

    path = _history_file(owner, repo)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
