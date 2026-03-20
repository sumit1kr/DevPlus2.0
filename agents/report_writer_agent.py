from __future__ import annotations

import json
from typing import Dict, List

from state.state import DevPulseState
from tools.llm_router import LLMRouter
from tools.trace_logger import TraceLogger


def _emoji_for_score(score: int) -> str:
    if score < 50:
        return "🔴"
    if score < 75:
        return "🟡"
    return "🟢"


def _plain_report(state: DevPulseState) -> str:
    agg = state.get("aggregated_result", {})
    analysis_mode = state.get("analysis_mode", "repo")
    score = state.get("score_breakdown", {}).get("overall", 0)
    dep_count = state.get("dependency_result", {}).get("metrics", {}).get("vulnerable_dependencies", 0)
    top: List[Dict] = agg.get("top_findings", [])
    warnings = agg.get("warnings", [])

    lines = [
        f"📊 DevPulse Report - github.com/{state.get('owner', 'unknown')}/{state.get('repo', 'unknown')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{_emoji_for_score(score)} Code Quality Score : {score}/100",
        f"{'🔴' if dep_count else '🟢'} Dependency Risk    : {dep_count} vulnerable dependencies",
        f"{'🟢' if state.get('git_history_result', {}).get('metrics', {}).get('active_last_30d', False) else '🟡'} Commit Health      : {state.get('git_history_result', {}).get('summary', 'unknown')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "Top Issues Found:",
    ]

    if not top:
        lines.append(" - No critical issues found in scanned scope")
    else:
        for item in top[:5]:
            lines.append(f" - {item.get('title', 'Issue')} ({item.get('severity', 'low')})")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if warnings:
        lines.append("Warnings:")
        for w in warnings[:3]:
            lines.append(f" - {w}")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if analysis_mode == "pr":
        pr_summary = state.get("pr_risk_summary", {})
        if pr_summary:
            lines.append(f"PR Risk Level: {str(pr_summary.get('risk_level', 'unknown')).upper()}")
            lines.append("Changed Hotspots:")
            for item in pr_summary.get("changed_hotspots", [])[:5]:
                lines.append(f" - {item.get('title', 'Issue')} ({item.get('severity', 'low')})")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💬 Ask me anything about this report...")
    return "\n".join(lines)


def run_report_writer(state: DevPulseState) -> DevPulseState:
    trace = TraceLogger("report_writer_agent", state)

    llm = LLMRouter()
    agg = state.get("aggregated_result", {})
    analysis_mode = state.get("analysis_mode", "repo")
    model_usage = list(state.get("model_usage", []))
    warnings_out = list(state.get("warnings", []))
    checklist = _default_review_checklist(state)

    if not llm.available():
        model_usage.append({"node": "report_writer", "provider": "none", "attempts": 0})
        trace_entry = trace.finalize(
            status="degraded",
            output={"final_report": "deterministic_fallback", "pr_checklist": len(checklist)},
            fallback_reason="llm_unavailable",
        )
        return {
            "final_report": _plain_report(state),
            "model_usage": model_usage,
            "pr_review_checklist": checklist,
            "run_trace": [trace_entry],
        }

    system_prompt = (
        "You are DevPulse Report Writer. "
        "Write a concise technical health report in clean markdown. "
        "Structure it with these sections in order: "
        "## Summary, ## Health Score, ## Top Issues, "
        "## Recommendations. "
        "Use bullet points for issues and recommendations. "
        "Be specific - name actual files, functions, and packages. "
        "Do not wrap output in JSON. Do not use code fences. "
        "Return only the markdown report text."
    )
    user_prompt = (
        "Write a technical health report from this repository "
        "audit data. Be specific and actionable.\n\n"
        + json.dumps(agg)
    )
    report = llm.invoke_text(
        system_prompt,
        user_prompt,
        primary="groq",
        fallback="gemini",
        temperature=0.2,
    )
    trace.add_tool_call("llm.invoke_text", {"primary": "groq", "fallback": "gemini"})
    report = report.strip() if report else ""

    if not report and llm.last_provider:
        warnings_out.append(
            f"Report writer: provider {llm.last_provider} responded but returned empty text. "
            f"Using built-in report format."
        )

    if analysis_mode == "pr":
        trace.add_tool_call("generate_pr_review_checklist", {"mode": "pr"})
        checklist = _generate_pr_review_checklist(state, llm) or checklist

    fallback_reason = llm.last_fallback_reason if hasattr(llm, "last_fallback_reason") else ""

    model_usage.append(
        {
            "node": "report_writer",
            "provider": llm.last_provider or "none",
            "attempts": llm.last_attempts,
        }
    )
    return {
        "final_report": report or _plain_report(state),
        "model_usage": model_usage,
        "warnings": warnings_out,
        "pr_review_checklist": checklist,
        "run_trace": [
            trace.finalize(
                status="success",
                output={"final_report": "llm_or_fallback", "pr_checklist": len(checklist)},
                token_count=getattr(llm, "last_token_count", None),
                fallback_reason=fallback_reason,
            )
        ],
    }


def run_followup_answer(state: DevPulseState) -> DevPulseState:
    trace = TraceLogger("followup_agent", state)

    question = (state.get("user_question") or "").strip()
    report = state.get("final_report", "")
    if not question:
        return {
            "followup_answer": "Please provide a follow-up question.",
            "run_trace": [trace.finalize(status="degraded", output={"followup_answer": "empty_question"})],
        }

    llm = LLMRouter()
    model_usage = list(state.get("model_usage", []))
    if not llm.available():
        trace_entry = trace.finalize(
            status="degraded",
            output={"followup_answer": "llm_unavailable"},
            fallback_reason="llm_unavailable",
        )
        return {
            "followup_answer": (
                "LLM provider is not configured. Add GROQ_API_KEY or GEMINI_API_KEY to answer follow-up questions."
            ),
            "model_usage": model_usage + [{"node": "followup", "provider": "none", "attempts": 0}],
            "run_trace": [trace_entry],
        }

    system_prompt = (
        "You answer questions about a repository audit using provided evidence. "
        "Be specific, cite concrete details from context, and do not invent facts. "
        "If context is insufficient, clearly say what is missing."
    )

    aggregated = state.get("aggregated_result", {})
    findings = aggregated.get("top_findings", [])
    coverage = state.get("scan_coverage", {})
    files_index = state.get("files_index", [])
    fetched_files = state.get("fetched_files", {})
    chat_history = state.get("chat_history", [])

    sample_paths = [str(f.get("path", "")) for f in files_index[:40] if f.get("path")]
    readme_excerpt = ""
    for path, content in fetched_files.items():
        if str(path).lower().endswith(("readme.md", "readme.rst", "readme.txt")):
            readme_excerpt = str(content)[:4000]
            break

    context_payload = {
        "repo_url": state.get("repo_url", ""),
        "repo": f"{state.get('owner', 'unknown')}/{state.get('repo', 'unknown')}",
        "analysis_mode": state.get("analysis_mode", "repo"),
        "pr_risk_summary": state.get("pr_risk_summary", {}),
        "pr_review_checklist": state.get("pr_review_checklist", []),
        "report_summary": aggregated.get("summaries", {}),
        "top_findings": findings[:12],
        "coverage": coverage,
        "sample_paths": sample_paths,
        "readme_excerpt": readme_excerpt,
        "chat_history": chat_history[-10:],
    }

    user_prompt = (
        "Answer the user question using the context below. "
        "Prefer repository-purpose explanation first when asked.\n\n"
        f"Report:\n{report}\n\n"
        f"Context:\n{json.dumps(context_payload)}\n\n"
        f"Question:\n{question}"
    )

    answer = llm.invoke_text(system_prompt, user_prompt, primary="gemini", fallback="groq", temperature=0.1)
    trace.add_tool_call("llm.invoke_text", {"primary": "gemini", "fallback": "groq"})
    model_usage.append(
        {
            "node": "followup",
            "provider": llm.last_provider or "none",
            "attempts": llm.last_attempts,
        }
    )
    return {
        "followup_answer": answer or "I could not generate an answer.",
        "model_usage": model_usage,
        "run_trace": [
            trace.finalize(
                status="success" if answer else "degraded",
                output={"followup_answer": "generated" if answer else "empty"},
                token_count=getattr(llm, "last_token_count", None),
                fallback_reason=getattr(llm, "last_fallback_reason", ""),
            )
        ],
    }


def _default_review_checklist(state: DevPulseState) -> list[str]:
    if state.get("analysis_mode", "repo") != "pr":
        return []
    return [
        "Validate changed high-complexity functions with targeted unit tests.",
        "Confirm each new dependency has a pinned version and changelog review.",
        "Review changed error-handling paths and rollback behavior.",
        "Check sensitive paths (auth, IO, networking) for new side effects.",
        "Ensure PR includes tests for modified logic branches.",
    ]


def _generate_pr_review_checklist(state: DevPulseState, llm: LLMRouter) -> list[str]:
    if not llm.available():
        return []

    payload = {
        "pr_number": state.get("pr_number"),
        "risk_summary": state.get("pr_risk_summary", {}),
        "dependency_delta": state.get("pr_dependency_delta", {}),
        "top_findings": state.get("aggregated_result", {}).get("top_findings", [])[:10],
    }

    system_prompt = (
        "You generate pull request review checklists. Return JSON with one key 'checklist' as list of short bullets."
    )
    user_prompt = f"Build a practical PR review checklist from this data:\n{json.dumps(payload)}"
    response = llm.invoke_json(
        system_prompt,
        user_prompt,
        primary="groq",
        fallback="gemini",
        required_keys=["checklist"],
    )
    checklist = response.get("checklist", []) if response else []
    if not isinstance(checklist, list):
        return []
    return [str(item) for item in checklist[:12] if str(item).strip()]
