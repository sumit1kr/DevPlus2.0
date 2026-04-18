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


DEP_SUFFIXES = (
    "requirements.txt",
    "package.json",
    "pyproject.toml",
    "poetry.lock",
    "package-lock.json",
)


def _derive_routes_and_rationale(state: DevPulseState) -> tuple[List[str], list[dict]]:
    analysis_mode = state.get("analysis_mode", "repo")
    files = state.get("files_index", [])

    py_count = sum(1 for f in files if str(f.get("path", "")).lower().endswith(".py"))
    dep_count = sum(1 for f in files if str(f.get("path", "")).lower().endswith(DEP_SUFFIXES))

    route_security = True
    route_code_quality = py_count > 0
    route_dependency = dep_count > 0
    route_git_history = analysis_mode != "pr"

    routes: List[str] = ["security"]
    if route_code_quality:
        routes.append("code_quality")
    if route_dependency:
        routes.append("dependency")
    if route_git_history:
        routes.append("git_history")

    rationale = [
        {
            "agent": "security",
            "enabled": route_security,
            "reason": "Always enabled for baseline security checks.",
        },
        {
            "agent": "code_quality",
            "enabled": route_code_quality,
            "reason": (
                f"Detected {py_count} Python file(s), enabling complexity analysis."
                if route_code_quality
                else "No Python files detected, skipping complexity analysis."
            ),
        },
        {
            "agent": "dependency",
            "enabled": route_dependency,
            "reason": (
                f"Detected {dep_count} dependency manifest file(s), enabling vulnerability scan."
                if route_dependency
                else "No supported dependency manifests detected, skipping dependency scan."
            ),
        },
        {
            "agent": "git_history",
            "enabled": route_git_history,
            "reason": (
                "Repository mode run, enabling commit activity analysis."
                if route_git_history
                else "PR mode run, skipping git history to focus on changed scope."
            ),
        },
    ]

    return routes, rationale


def run_router(state: DevPulseState) -> DevPulseState:
    routes, rationale = _derive_routes_and_rationale(state)
    return {
        "route_code_quality": "code_quality" in routes,
        "route_dependency": "dependency" in routes,
        "route_git_history": "git_history" in routes,
        "routing_decision": routes,
        "routing_plan": rationale,
    }


def route_after_fetch(state: DevPulseState) -> List[str]:
    # Prefer explicit route flags set by the router node; keep fallback for direct tests.
    has_router_flags = bool(state.get("routing_decision") or state.get("routing_plan"))

    if has_router_flags:
        routes = ["security"]
        if state.get("route_code_quality", False):
            routes.append("code_quality")
        if state.get("route_dependency", False):
            routes.append("dependency")
        if state.get("route_git_history", False):
            routes.append("git_history")
    else:
        routes, _ = _derive_routes_and_rationale(state)

    if not routes:
        routes.append("aggregator")
    return routes


def build_graph():
    graph = StateGraph(DevPulseState)

    graph.add_node("fetcher", run_fetcher)
    graph.add_node("router", run_router)
    graph.add_node("code_quality", run_code_quality)
    graph.add_node("dependency", run_dependency_analysis)
    graph.add_node("git_history", run_git_history)
    graph.add_node("security", run_security_analysis)
    graph.add_node("aggregator", run_aggregator)
    graph.add_node("report_writer", run_report_writer)
    graph.add_node("followup", run_followup_answer)

    graph.set_entry_point("fetcher")
    graph.add_edge("fetcher", "router")

    graph.add_conditional_edges(
        "router",
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
