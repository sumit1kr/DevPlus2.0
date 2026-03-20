from agents.aggregator_node import run_aggregator
from graph.devpulse_graph import route_after_fetch
from state.state import default_state


def test_router_selects_expected_branches():
    state = default_state("https://github.com/a/b")
    state["files_index"] = [
        {"path": "src/main.py"},
        {"path": "pyproject.toml"},
    ]
    routes = route_after_fetch(state)
    assert "code_quality" in routes
    assert "dependency" in routes
    assert "git_history" in routes


def test_scoring_applies_penalties():
    state = default_state("https://github.com/a/b")
    state["files_index"] = [{"path": "src/main.py"}]
    state["code_quality_result"] = {
        "summary": "ok",
        "findings": [],
        "risk_level": "low",
        "confidence": 0.9,
        "metrics": {},
    }
    state["dependency_result"] = {
        "summary": "dep",
        "findings": [
            {
                "title": "Critical vuln",
                "severity": "critical",
                "evidence": "pkg",
                "recommendation": "upgrade",
            }
        ],
        "risk_level": "high",
        "confidence": 0.9,
        "metrics": {"vulnerable_dependencies": 1},
    }
    state["git_history_result"] = {
        "summary": "stale",
        "findings": [],
        "risk_level": "medium",
        "confidence": 0.9,
        "metrics": {"active_last_30d": False},
    }

    out = run_aggregator(state)
    sb = out["score_breakdown"]

    assert sb["penalty_missing_tests"] > 0
    assert sb["penalty_critical_vulnerabilities"] > 0
    assert sb["penalty_stale_commit_activity"] > 0
    assert sb["overall"] <= sb["weighted_base"]
