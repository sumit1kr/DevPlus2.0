from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from graph.devpulse_graph import build_graph
from state.state import default_state
from tools.history_store import load_scan_history, save_scan_result
from tools.report_builder import build_report
from tools.runtime_config import load_runtime_config


loaded_keys = load_runtime_config()

st.set_page_config(page_title="DevPulse", page_icon="📊", layout="wide")
st.title("📊 DevPulse")
st.markdown(
    "### AI-powered code review for any GitHub repository\n"
    "Paste a repo URL and get a full health report in under "
    "60 seconds — code quality, security risks, vulnerable "
    "dependencies, and git activity. All in one place."
)

st.markdown(
        """
        <div style="display:flex;gap:8px;flex-wrap:wrap;
                                margin:0.5rem 0 1rem 0;">
            <span style="background:#1a3a2a;color:#4ade80;
                                     padding:4px 12px;border-radius:20px;
                                     font-size:0.8rem;font-weight:600;">
                Multi-agent AI
            </span>
            <span style="background:#1a2a3a;color:#60a5fa;
                                     padding:4px 12px;border-radius:20px;
                                     font-size:0.8rem;font-weight:600;">
                Security scan
            </span>
            <span style="background:#2a2a1a;color:#fbbf24;
                                     padding:4px 12px;border-radius:20px;
                                     font-size:0.8rem;font-weight:600;">
                Dependency check
            </span>
            <span style="background:#1a3a2a;color:#4ade80;
                                     padding:4px 12px;border-radius:20px;
                                     font-size:0.8rem;font-weight:600;">
                Downloadable report
            </span>
            <span style="background:#2a1a3a;color:#c084fc;
                                     padding:4px 12px;border-radius:20px;
                                     font-size:0.8rem;font-weight:600;">
                LangGraph orchestration
            </span>
        </div>
        """,
        unsafe_allow_html=True,
)

st.divider()

missing = [k for k in ("GROQ_API_KEY", "GEMINI_API_KEY") if k not in loaded_keys]
if len(missing) == 2:
    st.info("AI keys are not configured. The app will still run using built-in analysis mode.")

if "report_state" not in st.session_state:
    st.session_state.report_state = None

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "graph" not in st.session_state:
    report_graph, followup_graph = build_graph()
    st.session_state.graph = report_graph
    st.session_state.followup_graph = followup_graph

if "repo_url_input" not in st.session_state:
    st.session_state.repo_url_input = ""
if "pending_demo_url" not in st.session_state:
    st.session_state.pending_demo_url = ""

_trigger_run = False
with st.sidebar:
    st.markdown("## ⚙️ Scan Settings")

    scan_depth = st.slider(
        "Scan depth",
        min_value=10,
        max_value=80,
        value=30,
        step=5,
        help="Higher = more files scanned but slower.",
    )

    st.divider()

    st.markdown("## 🚀 Quick Demo")
    st.caption("No repo in mind? Try one of these:")

    if st.button("Try on Flask", width="stretch"):
        st.session_state.pending_demo_url = "https://github.com/pallets/flask"
        _trigger_run = True
    if st.button("Try on FastAPI", width="stretch"):
        st.session_state.pending_demo_url = "https://github.com/tiangolo/fastapi"
        _trigger_run = True
    if st.button("Try on Requests", width="stretch"):
        st.session_state.pending_demo_url = "https://github.com/psf/requests"
        _trigger_run = True

    st.divider()

    st.markdown("## 📊 About DevPulse")
    st.caption(
        "Multi-agent AI system that audits GitHub repositories for code quality, security risks, "
        "and dependency vulnerabilities."
    )
    st.caption("Built with LangGraph · Groq · Streamlit")

    if "GROQ_API_KEY" in loaded_keys:
        st.success("AI: Groq ready")
    elif "GEMINI_API_KEY" in loaded_keys:
        st.success("AI: Gemini ready")
    else:
        st.error("AI: No keys found")

if st.session_state.pending_demo_url:
    st.session_state.repo_url_input = st.session_state.pending_demo_url
    st.session_state.pending_demo_url = ""

repo_url = st.text_input(
    "GitHub repository or PR link",
    placeholder="https://github.com/owner/repo or https://github.com/owner/repo/pull/123",
    key="repo_url_input",
)

col1, col2 = st.columns([1, 3])
with col1:
    run_btn = st.button("Run Health Check", type="primary")

if run_btn or _trigger_run:
    if not repo_url.strip():
        st.error("Please paste a valid GitHub repository or PR link.")
    else:
        with st.spinner("Reviewing repository... this can take a moment."):
            if _trigger_run:
                st.info(
                    f"Running demo audit on {repo_url.split('/')[-1]}... "
                    "This takes about 30 seconds."
                )
            init_state = default_state(repo_url=repo_url.strip(), scan_depth=scan_depth)
            result = st.session_state.graph.invoke(init_state)
            owner = str(result.get("owner", "")).strip()
            repo = str(result.get("repo", "")).strip()
            score_breakdown = result.get("score_breakdown", {})
            if owner and repo and isinstance(score_breakdown, dict) and score_breakdown.get("overall") is not None:
                save_scan_result(
                    owner=owner,
                    repo=repo,
                    score_breakdown=score_breakdown,
                    timestamp=datetime.utcnow().isoformat() + "Z",
                )
            st.session_state.report_state = result
            st.session_state.chat_history = []

if st.session_state.report_state:
    result = st.session_state.report_state
    score_breakdown = result.get("score_breakdown", {})
    aggregated = result.get("aggregated_result", {})
    warnings = result.get("warnings", [])
    pr_risk_summary = result.get("pr_risk_summary", {})
    pr_review_checklist = result.get("pr_review_checklist", [])
    run_trace = result.get("run_trace", [])
    owner = str(result.get("owner", "")).strip()
    repo = str(result.get("repo", "")).strip()
    history_records = load_scan_history(owner, repo) if owner and repo else []

    def _friendly_severity(level: str) -> str:
        mapping = {
            "critical": "Critical",
            "high": "High",
            "medium": "Medium",
            "low": "Low",
        }
        return mapping.get(str(level).lower(), "Low")

    def _finding_title(finding: dict) -> str:
        severity = _friendly_severity(finding.get("severity", "low"))
        return f"{severity} priority - {finding.get('title', 'Issue')}"

    def _render_finding_meta(finding: dict) -> None:
        confidence = finding.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        st.caption(f"How sure we are: {int(confidence * 100)}%")
        st.progress(confidence)

        depth = str(finding.get("evidence_depth", "moderate")).lower()
        if depth not in {"strong", "moderate", "weak"}:
            depth = "moderate"

        depth_colors = {
            "strong": ("#1B5E20", "#E8F5E9"),
            "moderate": ("#7A5A00", "#FFF8E1"),
            "weak": ("#8E0000", "#FFEBEE"),
        }
        text_color, bg_color = depth_colors[depth]
        depth_label = {
            "strong": "Strong evidence",
            "moderate": "Moderate evidence",
            "weak": "Limited evidence",
        }[depth]
        st.markdown(
            (
                f"<span style=\"display:inline-block;padding:0.2rem 0.5rem;"
                f"border-radius:0.5rem;background:{bg_color};color:{text_color};"
                f"font-size:0.8rem;font-weight:600;\">{depth_label}</span>"
            ),
            unsafe_allow_html=True,
        )

    def _status_for(key: str) -> str:
        payload = result.get(key, {})
        if not payload:
            return "Not available"
        if payload.get("confidence", 0) < 0.6:
            return "Needs review"
        return "Good"

    st.subheader("Agent Check Status")

    # -- Overall score card ------------------------------------------------
    overall = score_breakdown.get("overall", 0)

    if overall >= 80:
        score_color = "normal"
        score_label = "Healthy"
        score_emoji = "🟢"
    elif overall >= 60:
        score_color = "off"
        score_label = "Fair"
        score_emoji = "🟡"
    else:
        score_color = "inverse"
        score_label = "Needs Attention"
        score_emoji = "🔴"

    st.markdown(
        f"""
        <div style="
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-radius: 16px;
            padding: 2rem 2.5rem;
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        ">
            <div>
                <p style="color:#aaa;font-size:0.9rem;margin:0;
                          font-weight:500;letter-spacing:0.05em;">
                    OVERALL HEALTH SCORE
                </p>
                <p style="color:white;font-size:0.85rem;margin:0.3rem 0 0;">
                    {result.get('owner','')}/{result.get('repo','')}
                    &nbsp;·&nbsp;branch: {result.get('branch','main')}
                </p>
            </div>
            <div style="text-align:right;">
                <p style="
                    font-size:3.5rem;
                    font-weight:800;
                    margin:0;
                    color:{'#4ade80' if overall >= 80 else
                           '#fbbf24' if overall >= 60 else '#f87171'};
                    line-height:1;
                ">{score_emoji} {overall}<span style="font-size:1.5rem;
                    color:#888;">/100</span></p>
                <p style="
                    color:{'#4ade80' if overall >= 80 else
                           '#fbbf24' if overall >= 60 else '#f87171'};
                    font-size:1rem;
                    font-weight:600;
                    margin:0.3rem 0 0;
                ">{score_label}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _ = score_color
    # ---------------------------------------------------------------------

    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Code Quality", _status_for("code_quality_result"))
    s2.metric("Dependencies", _status_for("dependency_result"))
    s3.metric("Team Activity", _status_for("git_history_result"))
    s4.metric("Security", _status_for("security_result"))

    st.divider()
    st.caption("Download the full audit report:")

    report_mode = st.radio(
        "Report Mode",
        options=["Detailed", "Moderate"],
        horizontal=True,
        index=0,
    )

    mode_value = "detailed" if report_mode.lower() == "detailed" else "moderate"
    export_markdown = build_report(result, mode_value)
    report_filename = f"devpulse_report_{mode_value}.md"

    export_json = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "repo_url": result.get("repo_url", repo_url),
        "branch": result.get("branch", ""),
        "score_breakdown": score_breakdown,
        "coverage": result.get("scan_coverage", {}),
        "warnings": warnings,
        "aggregated_result": aggregated,
        "analysis_mode": result.get("analysis_mode", "repo"),
        "pr_number": result.get("pr_number"),
        "pr_changed_files": result.get("pr_changed_files", []),
        "pr_dependency_delta": result.get("pr_dependency_delta", {}),
        "pr_risk_summary": pr_risk_summary,
        "pr_review_checklist": pr_review_checklist,
        "run_trace": run_trace,
        "code_quality_result": result.get("code_quality_result", {}),
        "dependency_result": result.get("dependency_result", {}),
        "git_history_result": result.get("git_history_result", {}),
        "security_result": result.get("security_result", {}),
    }

    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "Download Report (.md)",
            data=export_markdown,
            file_name=report_filename,
            mime="text/markdown",
            type="primary",
        )

        with st.expander("Preview report", expanded=False):
            st.markdown(export_markdown)

    with d2:
        st.download_button(
            "Download data (JSON)",
            data=json.dumps(export_json, indent=2),
            file_name="devpulse_report.json",
            mime="application/json",
        )

    st.divider()

    tab_overview, tab_code, tab_dep, tab_git, tab_sec, tab_cov, tab_history, tab_timeline = st.tabs(
        [
            "Big Picture",
            "Code Health",
            "Dependencies",
            "Team Activity",
            "Security",
            "Coverage & Notes",
            "Score History",
            "Step-by-Step Run",
        ]
    )

    with tab_overview:
        st.caption("Quick summary of what matters most and what to fix first.")
        st.subheader("Final Summary")
        st.markdown(result.get("final_report", "No report generated."))
        if result.get("analysis_mode") == "pr":
            st.subheader("PR Risk Summary")
            st.caption("How risky this pull request looks before merge.")
            st.json(pr_risk_summary)
            st.subheader("PR Review Checklist")
            if pr_review_checklist:
                for item in pr_review_checklist:
                    st.markdown(f"- {item}")
            else:
                st.info("No checklist generated for this PR run.")
        st.subheader("Score Breakdown")
        st.caption("Scores by area. Higher is better. "
                   "Penalties are deducted from the weighted base.")

        # Visual score bars
        _score_items = [
            ("Code Quality", score_breakdown.get("code_quality", 0), "45% weight"),
            ("Dependency Risk", score_breakdown.get("dependency", 0), "35% weight"),
            ("Git Health", score_breakdown.get("git_history", 0), "20% weight"),
        ]
        for _label, _val, _weight in _score_items:
            _col_label, _col_bar, _col_val = st.columns([2, 5, 1])
            with _col_label:
                st.caption(f"**{_label}**")
                st.caption(_weight)
            with _col_bar:
                st.progress(min(int(_val), 100) / 100)
            with _col_val:
                st.markdown(f"**{_val}**")

        # Penalty breakdown
        _penalty_total = score_breakdown.get("penalty_total", 0)
        _weighted_base = score_breakdown.get("weighted_base", 0)
        _overall = score_breakdown.get("overall", 0)

        st.markdown("---")
        _pc1, _pc2, _pc3 = st.columns(3)
        _pc1.metric("Weighted Base", f"{_weighted_base}/100")
        _pc2.metric(
            "Total Penalties",
            f"-{_penalty_total}",
            delta=f"-{_penalty_total}" if _penalty_total > 0 else None,
            delta_color="inverse",
        )
        _pc3.metric("Final Score", f"{_overall}/100")

        # Penalty detail in expander
        with st.expander("Show penalty breakdown"):
            st.write(f"Missing tests: -{score_breakdown.get('penalty_missing_tests', 0)}")
            st.write(f"Critical vulnerabilities: "
                     f"-{score_breakdown.get('penalty_critical_vulnerabilities', 0)}")
            st.write(f"Stale commit activity: "
                     f"-{score_breakdown.get('penalty_stale_commit_activity', 0)}")

        # Keep JSON for technical users in expander
        with st.expander("Show raw score data"):
            st.json(score_breakdown)
        if result.get("model_usage"):
            with st.expander("Show technical model usage details"):
                st.json(result.get("model_usage", []))

    with tab_code:
        st.caption("Code complexity and maintainability insights.")
        st.write(result.get("code_quality_result", {}).get("summary", "No code quality summary."))
        with st.expander("Show technical metrics"):
            st.json(result.get("code_quality_result", {}).get("metrics", {}))
        for f in result.get("code_quality_result", {}).get("findings", []):
            with st.expander(_finding_title(f)):
                _render_finding_meta(f)
                st.write(f"What we found: {f.get('evidence', 'n/a')}")
                st.write(f"Suggested action: {f.get('recommendation', 'n/a')}")

    with tab_dep:
        st.caption("Library and package risks that could affect reliability or security.")
        st.write(result.get("dependency_result", {}).get("summary", "No dependency summary."))
        with st.expander("Show technical metrics"):
            st.json(result.get("dependency_result", {}).get("metrics", {}))
        for f in result.get("dependency_result", {}).get("findings", []):
            with st.expander(_finding_title(f)):
                _render_finding_meta(f)
                st.write(f"What we found: {f.get('evidence', 'n/a')}")
                st.write(f"Suggested action: {f.get('recommendation', 'n/a')}")

    with tab_git:
        st.caption("Commit activity and collaboration quality signals.")
        st.write(result.get("git_history_result", {}).get("summary", "No git health summary."))
        with st.expander("Show technical metrics"):
            st.json(result.get("git_history_result", {}).get("metrics", {}))
        for f in result.get("git_history_result", {}).get("findings", []):
            with st.expander(_finding_title(f)):
                _render_finding_meta(f)
                st.write(f"What we found: {f.get('evidence', 'n/a')}")
                st.write(f"Suggested action: {f.get('recommendation', 'n/a')}")

    with tab_sec:
        st.caption("Potential security exposures and what to do next.")
        st.write(result.get("security_result", {}).get("summary", "No security summary."))
        with st.expander("Show technical metrics"):
            st.json(result.get("security_result", {}).get("metrics", {}))

        sec_findings = result.get("security_result", {}).get("findings", [])
        grouped: dict[str, list[dict]] = {
            "secret_leak": [],
            "license_risk": [],
            "unsafe_pattern": [],
            "exploitability": [],
            "other": [],
        }

        for finding in sec_findings:
            evidence = str(finding.get("evidence", ""))
            category = "other"
            if "category=secret_leak" in evidence:
                category = "secret_leak"
            elif "category=license_risk" in evidence:
                category = "license_risk"
            elif "category=unsafe_pattern" in evidence:
                category = "unsafe_pattern"
            elif "category=exploitability" in evidence:
                category = "exploitability"
            grouped[category].append(finding)

        category_labels = {
            "secret_leak": "Secrets exposed",
            "license_risk": "License concerns",
            "unsafe_pattern": "Unsafe coding patterns",
            "exploitability": "Exploitability notes",
            "other": "Other findings",
        }

        for category in ("secret_leak", "license_risk", "unsafe_pattern", "exploitability", "other"):
            items = grouped.get(category, [])
            if not items:
                continue
            st.subheader(category_labels.get(category, "Other findings"))
            for f in items:
                with st.expander(_finding_title(f)):
                    _render_finding_meta(f)
                    st.write(f"What we found: {f.get('evidence', 'n/a')}")
                    st.write(f"Suggested action: {f.get('recommendation', 'n/a')}")

    with tab_cov:
        st.caption("How much of the repository was scanned and notable run messages.")
        st.subheader("Scan Coverage")
        st.json(result.get("scan_coverage", {}))
        with st.expander("Show performance details"):
            st.json(result.get("runtime_profile", {}))
        st.subheader("Important Notes")
        if warnings:
            for w in warnings:
                st.warning(w)
        else:
            st.success("No important warnings in this run.")

    with tab_history:
        st.caption("Track whether this repository is improving over time.")
        st.subheader("Score History")

        if not owner or not repo:
            st.info("Repository details were not available for this scan, so history could not be loaded.")
        elif not history_records:
            st.info("No history found yet for this repository.")
        elif len(history_records) == 1:
            st.info("Run again later to see trend")
            st.dataframe(history_records, width="stretch")
        else:
            history_df = pd.DataFrame(history_records)
            chart_df = history_df[["timestamp", "overall_score"]].copy()
            chart_df["timestamp"] = pd.to_datetime(chart_df["timestamp"], errors="coerce", utc=True)
            chart_df["overall_score"] = pd.to_numeric(chart_df["overall_score"], errors="coerce")
            chart_df = chart_df.dropna(subset=["timestamp", "overall_score"]).sort_values("timestamp")

            if len(chart_df) >= 2:
                st.line_chart(chart_df.set_index("timestamp")["overall_score"])
            else:
                st.info("Not enough valid history points to draw a trend chart yet.")

            latest_score = int(history_records[-1].get("overall_score", 0))
            prev_score = int(history_records[-2].get("overall_score", 0))
            delta = latest_score - prev_score

            if delta > 0:
                st.success(f"Score improved by +{delta} since last scan")
            elif delta < 0:
                st.warning(f"Score dropped by {delta} since last scan")
            else:
                st.info("Score stayed the same since last scan")

            st.dataframe(history_records, width="stretch")

    with tab_timeline:
        st.caption("A timeline of what each analysis step did.")
        st.subheader("Run Timeline")
        if not run_trace:
            st.info("No timeline data available for this run.")
        else:
            timeline_rows = []
            total_tokens = 0
            token_rows = 0

            for idx, row in enumerate(run_trace):
                tokens = row.get("token_count")
                if isinstance(tokens, int) and tokens > 0:
                    total_tokens += tokens
                    token_rows += 1

                timeline_rows.append(
                    {
                        "step": idx + 1,
                        "agent": row.get("agent", "unknown"),
                        "start": row.get("start_time", ""),
                        "duration_ms": row.get("duration_ms", 0),
                        "status": row.get("status", "unknown"),
                        "tokens": tokens if tokens is not None else "n/a",
                    }
                )

            st.dataframe(timeline_rows, width="stretch")

            if token_rows > 0:
                # Lightweight estimate, blended across free/low-cost models.
                est_cost_usd = (total_tokens / 1000.0) * 0.002
                st.metric("Estimated AI Cost (USD)", f"${est_cost_usd:.4f}")
                st.caption(f"Estimate based on {total_tokens} total tracked tokens.")
            else:
                st.metric("Estimated AI Cost (USD)", "n/a")
                st.caption("Token usage was not available for this run.")

            for idx, row in enumerate(run_trace):
                title = f"Step {idx + 1}: {row.get('agent', 'unknown')} ({row.get('status', 'unknown')})"
                with st.expander(title):
                    st.write(f"Start time: {row.get('start_time', '')}")
                    st.write(f"End time: {row.get('end_time', '')}")
                    st.write(f"Duration: {row.get('duration_ms', 0)} ms")
                    st.write(f"Tokens used: {row.get('token_count', 'n/a')}")
                    if row.get("fallback_reason"):
                        st.write(f"Fallback reason: {row.get('fallback_reason')}")
                    st.write("Input summary:")
                    st.code(str(row.get("input_summary", "")))
                    st.write("Output summary:")
                    st.code(str(row.get("output_summary", "")))
                    st.write("Tools used:")
                    st.json(row.get("tool_calls", []))

    if result.get("errors"):
        st.subheader("Run Errors")
        st.error("\n".join(result["errors"]))

    st.subheader("Ask Follow-up Questions")
    clear_col, _ = st.columns([1, 5])
    with clear_col:
        if st.button("Clear conversation"):
            st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        role = msg.get("role", "assistant")
        content = msg.get("content", "")
        with st.chat_message(role):
            st.markdown(content)

    user_prompt = st.chat_input("Ask a question about this result")
    if user_prompt:
        st.session_state.chat_history.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                follow_state = {
                    **result,
                    "user_question": user_prompt,
                    "chat_history": st.session_state.chat_history,
                }
                answered = st.session_state.followup_graph.invoke(follow_state)
                answer_text = answered.get("followup_answer", "No answer generated.")
                st.markdown(answer_text)

        st.session_state.chat_history.append({"role": "assistant", "content": answer_text})
        st.session_state.report_state = {
            **result,
            **answered,
            "chat_history": st.session_state.chat_history,
        }

    # -- Footer ---------------------------------------------------------------
    st.divider()
    footer_col1, footer_col2, footer_col3 = st.columns(3)

    with footer_col1:
        st.caption("📊 **DevPulse**")
        st.caption(
            "AI-powered repository health analysis. "
            "Built as an agentic AI portfolio project."
        )

    with footer_col2:
        st.caption("🔧 **Stack**")
        st.caption("LangGraph · LangChain · Groq · Gemini")
        st.caption("Radon · OSV API · Streamlit · Python 3.11")

    with footer_col3:
        st.caption("🔗 **Links**")
        st.markdown(
            "[View on GitHub](https://github.com/sumit1kr/devpulse)"
            "  ·  "
            "[Report an issue](https://github.com/sumit1kr/devpulse/issues)"
        )

    st.caption(
        "DevPulse scans public GitHub repositories only. "
        "Results are indicative and should be reviewed by a developer."
    )
    # ------------------------------------------------------------------------
