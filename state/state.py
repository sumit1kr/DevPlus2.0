from __future__ import annotations

from operator import add
from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict


class Finding(TypedDict):
    title: str
    severity: Literal["low", "medium", "high", "critical"]
    evidence: str
    recommendation: str
    confidence: float
    evidence_depth: Literal["strong", "moderate", "weak"]


class AgentResult(TypedDict):
    summary: str
    findings: List[Finding]
    risk_level: Literal["low", "medium", "high", "critical"]
    confidence: float
    metrics: Dict[str, Any]


class DevPulseState(TypedDict, total=False):
    repo_url: str
    analysis_mode: Literal["repo", "pr"]
    owner: str
    repo: str
    branch: str
    scan_depth: int
    pr_number: int

    files_index: List[Dict[str, Any]]
    fetched_files: Dict[str, str]
    dependency_files: Dict[str, str]
    pr_base_dependency_files: Dict[str, str]
    pr_head_dependency_files: Dict[str, str]
    pr_changed_files: List[Dict[str, Any]]
    commit_samples: List[Dict[str, Any]]
    detected_languages: Dict[str, int]
    scan_coverage: Dict[str, Any]
    runtime_profile: Dict[str, Any]
    agent_budgets: Dict[str, Any]

    route_code_quality: bool
    route_dependency: bool
    route_git_history: bool

    code_quality_result: AgentResult
    dependency_result: AgentResult
    git_history_result: AgentResult
    security_result: AgentResult

    aggregated_result: Dict[str, Any]
    score_breakdown: Dict[str, int]
    final_report: str

    user_question: str
    followup_answer: str
    chat_history: List[Dict[str, str]]

    pr_dependency_delta: Dict[str, Any]
    pr_risk_summary: Dict[str, Any]
    pr_review_checklist: List[str]

    errors: List[str]
    warnings: List[str]
    model_usage: List[Dict[str, Any]]
    run_trace: Annotated[List[Dict[str, Any]], add]


def default_state(repo_url: str, scan_depth: int = 30) -> DevPulseState:
    return DevPulseState(
        repo_url=repo_url,
        analysis_mode="repo",
        scan_depth=scan_depth,
        files_index=[],
        fetched_files={},
        dependency_files={},
        pr_base_dependency_files={},
        pr_head_dependency_files={},
        pr_changed_files=[],
        commit_samples=[],
        detected_languages={},
        scan_coverage={},
        runtime_profile={},
        agent_budgets={
            "code_quality_seconds": 12.0,
            "dependency_seconds": 20.0,
            "dependency_osv_queries": 120,
        },
        route_code_quality=False,
        route_dependency=False,
        route_git_history=False,
        errors=[],
        warnings=[],
        model_usage=[],
        run_trace=[],
        chat_history=[],
        pr_dependency_delta={"added": [], "removed": [], "vulnerable_added": []},
        pr_risk_summary={},
        pr_review_checklist=[],
    )
