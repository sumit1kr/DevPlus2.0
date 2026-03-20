from __future__ import annotations

from datetime import datetime, timezone

from state.state import AgentResult, DevPulseState
from tools.trace_logger import TraceLogger


def run_git_history(state: DevPulseState) -> DevPulseState:
    trace = TraceLogger("git_history_agent", state)

    commits = state.get("commit_samples", [])
    trace.add_tool_call("analyze_commits", {"count": len(commits)})

    if not commits:
        result: AgentResult = {
            "summary": "No commit history available.",
            "findings": [],
            "risk_level": "medium",
            "confidence": 0.5,
            "metrics": {"commit_count": 0, "active_last_30d": False},
        }
        trace_entry = trace.finalize(status="degraded", output={"git_history_result": result})
        return {"git_history_result": result, "run_trace": [trace_entry]}

    conventional = 0
    short_messages = 0
    active_last_30d = False
    now = datetime.now(timezone.utc)

    for c in commits:
        msg = (c.get("message") or "").strip()
        if ":" in msg and msg.split(":", 1)[0] in {
            "feat",
            "fix",
            "docs",
            "refactor",
            "test",
            "chore",
            "ci",
            "perf",
        }:
            conventional += 1
        if len(msg) < 12:
            short_messages += 1

        date_raw = c.get("date", "")
        try:
            dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            if (now - dt).days <= 30:
                active_last_30d = True
        except Exception:
            pass

    findings = []
    if short_messages > max(2, len(commits) // 4):
        findings.append(
            {
                "title": "Low-quality commit messages",
                "severity": "medium",
                "evidence": f"{short_messages}/{len(commits)} commit messages are very short.",
                "recommendation": "Adopt clearer commit messages with intent and scope.",
                "confidence": 0.75,
                "evidence_depth": "moderate",
            }
        )

    summary = (
        f"Analyzed {len(commits)} recent commits. "
        f"Conventional-style messages: {conventional}. "
        f"Activity in last 30 days: {'yes' if active_last_30d else 'no'}."
    )

    risk_level = "low"
    if not active_last_30d:
        risk_level = "medium"
    if short_messages > len(commits) // 3:
        risk_level = "medium"

    result: AgentResult = {
        "summary": summary,
        "findings": findings,
        "risk_level": risk_level,
        "confidence": 0.75,
        "metrics": {
            "commit_count": len(commits),
            "conventional_messages": conventional,
            "active_last_30d": active_last_30d,
            "short_messages": short_messages,
        },
    }

    trace_entry = trace.finalize(status="success", output={"git_history_result": result})
    return {"git_history_result": result, "run_trace": [trace_entry]}
