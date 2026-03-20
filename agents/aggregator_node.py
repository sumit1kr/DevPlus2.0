from __future__ import annotations

from typing import Any, Dict, List

from state.state import DevPulseState
from tools.agent_result_validator import validate_agent_result
from tools.trace_logger import TraceLogger


RISK_TO_SCORE = {
    "low": 90,
    "medium": 70,
    "high": 45,
    "critical": 20,
}


def _safe_score(risk: str) -> int:
    return RISK_TO_SCORE.get(risk, 60)


def _collect_findings(state: DevPulseState) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for key in ("code_quality_result", "dependency_result", "git_history_result", "security_result"):
        result = state.get(key, {})
        for f in result.get("findings", []):
            finding = {"source": key, **f}

            confidence = finding.get("confidence", result.get("confidence", 0.75))
            try:
                confidence = float(confidence)
            except Exception:
                confidence = 0.75
            confidence = max(0.0, min(1.0, confidence))
            finding["confidence"] = confidence

            evidence_depth = str(finding.get("evidence_depth", "moderate")).lower()
            if evidence_depth not in {"strong", "moderate", "weak"}:
                evidence_depth = "moderate"
            finding["evidence_depth"] = evidence_depth

            if evidence_depth == "weak" and finding.get("severity") in {"high", "critical"}:
                finding["severity"] = "medium"

            title = str(finding.get("title", "Issue"))
            if confidence < 0.5 and not title.lower().endswith("(low confidence)"):
                finding["title"] = f"{title} (low confidence)"

            findings.append(finding)
    return findings


def _compute_penalties(state: DevPulseState, findings: List[Dict[str, Any]]) -> Dict[str, int]:
    analysis_mode = state.get("analysis_mode", "repo")
    files = [str(f.get("path", "")).lower() for f in state.get("files_index", [])]
    has_tests = any(
        p.startswith("tests/")
        or "/tests/" in p
        or p.endswith("_test.py")
        or p.endswith(".spec.js")
        or p.endswith(".test.js")
        or p.endswith(".spec.ts")
        or p.endswith(".test.ts")
        for p in files
    )

    critical_vulns = sum(
        1 for f in findings if f.get("source") == "dependency_result" and f.get("severity") == "critical"
    )
    stale_commit_activity = (
        analysis_mode != "pr"
        and not bool(state.get("git_history_result", {}).get("metrics", {}).get("active_last_30d", False))
    )

    penalties = {
        "missing_tests": 12 if not has_tests else 0,
        "critical_vulnerabilities": min(critical_vulns * 10, 30),
        "stale_commit_activity": 8 if stale_commit_activity else 0,
    }
    penalties["total"] = penalties["missing_tests"] + penalties["critical_vulnerabilities"] + penalties["stale_commit_activity"]
    return penalties


def run_aggregator(state: DevPulseState) -> DevPulseState:
    trace = TraceLogger("aggregator_node", state)

    warnings = list(state.get("warnings", []))
    analysis_mode = state.get("analysis_mode", "repo")
    trace.add_tool_call("validate_agent_results", {"mode": analysis_mode})

    code, code_warnings = validate_agent_result("code_quality", state.get("code_quality_result", {}))
    dep, dep_warnings = validate_agent_result("dependency", state.get("dependency_result", {}))
    git, git_warnings = validate_agent_result("git_history", state.get("git_history_result", {}))
    sec, sec_warnings = validate_agent_result("security", state.get("security_result", {}))
    warnings.extend(code_warnings + dep_warnings + git_warnings + sec_warnings)

    score_breakdown = {
        "code_quality": _safe_score(code.get("risk_level", "medium")),
        "dependency": _safe_score(dep.get("risk_level", "medium")),
        "git_history": _safe_score(git.get("risk_level", "medium")),
        "security": _safe_score(sec.get("risk_level", "medium")),
    }

    weighted_score = int(
        score_breakdown["code_quality"] * 0.30
        + score_breakdown["dependency"] * 0.30
        + score_breakdown["git_history"] * 0.20
        + score_breakdown["security"] * 0.20
    )

    findings = _collect_findings(state)
    findings.sort(
        key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.get("severity", "low"), 4)
    )

    penalties = _compute_penalties(state, findings)
    final_score = max(0, weighted_score - penalties["total"])

    score_breakdown_payload = {
        **score_breakdown,
        "weighted_base": weighted_score,
        "penalty_missing_tests": penalties["missing_tests"],
        "penalty_critical_vulnerabilities": penalties["critical_vulnerabilities"],
        "penalty_stale_commit_activity": penalties["stale_commit_activity"],
        "penalty_total": penalties["total"],
        "overall": final_score,
    }
    aggregated_result = {
        "overall_score": final_score,
        "top_findings": findings[:12],
        "summaries": {
            "code": code.get("summary", "n/a"),
            "dependency": dep.get("summary", "n/a"),
            "git": git.get("summary", "n/a"),
            "security": sec.get("summary", "n/a"),
        },
        "warnings": warnings,
        "coverage": state.get("scan_coverage", {}),
    }

    pr_risk_summary = {}
    if analysis_mode == "pr":
        trace.add_tool_call("build_pr_risk_summary", {"changed_files": len(state.get("pr_changed_files", []))})
        dep_delta = state.get("pr_dependency_delta", {})
        added_deps = dep_delta.get("added", [])
        vulnerable_added = dep_delta.get("vulnerable_added", [])
        hotspots = [
            {
                "title": f.get("title", "Issue"),
                "evidence": f.get("evidence", "n/a"),
                "severity": f.get("severity", "low"),
            }
            for f in findings
            if f.get("source") == "code_quality_result"
        ][:8]

        pr_risk_level = "low"
        if any(h.get("severity") in {"high", "critical"} for h in hotspots) or len(added_deps) >= 3:
            pr_risk_level = "medium"
        if len(vulnerable_added) > 0 or any(h.get("severity") == "critical" for h in hotspots):
            pr_risk_level = "high"

        pr_risk_summary = {
            "risk_level": pr_risk_level,
            "changed_hotspots": hotspots,
            "dependency_delta": {
                "added": added_deps,
                "removed": dep_delta.get("removed", []),
                "vulnerable_added": vulnerable_added,
            },
        }
        aggregated_result["pr_risk_summary"] = pr_risk_summary

    status = "success"
    if code_warnings or dep_warnings or git_warnings or sec_warnings:
        status = "degraded"
    trace_entry = trace.finalize(
        status=status,
        output={
            "overall_score": final_score,
            "warnings": len(warnings),
            "findings": len(findings),
            "mode": analysis_mode,
        },
    )

    return {
        "code_quality_result": code,
        "dependency_result": dep,
        "git_history_result": git,
        "security_result": sec,
        "score_breakdown": score_breakdown_payload,
        "aggregated_result": aggregated_result,
        "warnings": warnings,
        "pr_risk_summary": pr_risk_summary,
        "run_trace": [trace_entry],
    }
