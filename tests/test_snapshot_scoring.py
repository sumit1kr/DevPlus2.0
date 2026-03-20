import json
from pathlib import Path

from agents.aggregator_node import run_aggregator
from state.state import default_state


def test_score_breakdown_snapshot_keys():
    snapshot_path = Path("tests/snapshots/aggregator_snapshot.json")
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))

    state = default_state("https://github.com/a/b")
    state["files_index"] = [{"path": "app.py"}]
    state["code_quality_result"] = {
        "summary": "ok",
        "findings": [],
        "risk_level": "medium",
        "confidence": 0.9,
        "metrics": {},
    }
    state["dependency_result"] = {
        "summary": "ok",
        "findings": [],
        "risk_level": "medium",
        "confidence": 0.9,
        "metrics": {},
    }
    state["git_history_result"] = {
        "summary": "ok",
        "findings": [],
        "risk_level": "low",
        "confidence": 0.9,
        "metrics": {"active_last_30d": True},
    }

    out = run_aggregator(state)
    score_breakdown = out["score_breakdown"]
    for key in expected["expected_keys"]:
        assert key in score_breakdown
