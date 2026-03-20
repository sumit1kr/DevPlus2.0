from __future__ import annotations

from typing import List

from langgraph.graph import END, StateGraph

from agents.aggregator_node import run_aggregator
from agents.code_quality_agent import run_code_quality
from agents.dependency_agent import run_dependency_analysis
from agents.fetcher_agent import run_fetcher
from agents.git_history_agent import run_git_history
from agents.report_writer_agent import run_followup_answer, run_report_writer
from agents.security_agent import run_security_analysis
from state.state import DevPulseState


def route_after_fetch(state: DevPulseState) -> List[str]:
    analysis_mode = state.get("analysis_mode", "repo")
    files = state.get("files_index", [])
    has_python = any(str(f.get("path", "")).lower().endswith(".py") for f in files)
    dep_suffixes = (
        "requirements.txt",
        "package.json",
        "pyproject.toml",
        "poetry.lock",
        "package-lock.json",
    )
    has_deps = any(
        str(f.get("path", "")).lower().endswith(dep_suffixes)
        for f in files
    )

    routes = []
    routes.append("security")
    if has_python:
        routes.append("code_quality")
    if has_deps:
        routes.append("dependency")
    if analysis_mode != "pr":
        routes.append("git_history")

    if not routes:
        routes.append("aggregator")
    return routes


def build_graph():
    graph = StateGraph(DevPulseState)

    graph.add_node("fetcher", run_fetcher)
    graph.add_node("code_quality", run_code_quality)
    graph.add_node("dependency", run_dependency_analysis)
    graph.add_node("git_history", run_git_history)
    graph.add_node("security", run_security_analysis)
    graph.add_node("aggregator", run_aggregator)
    graph.add_node("report_writer", run_report_writer)
    graph.add_node("followup", run_followup_answer)

    graph.set_entry_point("fetcher")

    graph.add_conditional_edges(
        "fetcher",
        route_after_fetch,
        {
            "code_quality": "code_quality",
            "dependency": "dependency",
            "git_history": "git_history",
            "security": "security",
            "aggregator": "aggregator",
        },
    )

    graph.add_edge("security", "aggregator")
    graph.add_edge("code_quality", "aggregator")
    graph.add_edge("dependency", "aggregator")
    graph.add_edge("git_history", "aggregator")

    graph.add_edge("aggregator", "report_writer")
    graph.add_edge("report_writer", END)

    followup_graph = StateGraph(DevPulseState)
    followup_graph.add_node("followup", run_followup_answer)
    followup_graph.set_entry_point("followup")
    followup_graph.add_edge("followup", END)

    return graph.compile(), followup_graph.compile()
