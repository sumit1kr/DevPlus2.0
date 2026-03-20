from __future__ import annotations

import time

try:
    from radon.complexity import cc_visit  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover
    cc_visit = None

from state.state import AgentResult, DevPulseState
from tools.trace_logger import TraceLogger


def run_code_quality(state: DevPulseState) -> DevPulseState:
    trace = TraceLogger("code_quality_agent", state)

    files = state.get("fetched_files", {})
    py_files = {p: c for p, c in files.items() if p.lower().endswith(".py")}
    trace.add_tool_call("select_python_files", {"count": len(py_files)})
    budgets = state.get("agent_budgets", {})
    max_seconds = float(budgets.get("code_quality_seconds", 12.0))
    deadline = time.monotonic() + max_seconds

    high_complex = []
    analyzed = 0

    for path, content in py_files.items():
        if time.monotonic() >= deadline:
            break
        try:
            if cc_visit is None:
                continue
            blocks = cc_visit(content)
            analyzed += 1
            for block in blocks:
                if block.complexity > 15:
                    high_complex.append(
                        {
                            "path": path,
                            "name": block.name,
                            "complexity": block.complexity,
                        }
                    )
        except Exception:
            continue

    findings = [
        {
            "title": f"High complexity in {item['name']}",
            "severity": "medium" if item["complexity"] <= 20 else "high",
            "evidence": f"{item['path']} ({item['name']}), complexity={item['complexity']}",
            "recommendation": "Refactor into smaller functions and add targeted unit tests.",
            "confidence": 0.95,
            "evidence_depth": "strong",
        }
        for item in high_complex[:10]
    ]

    if not py_files:
        summary = "No Python files detected, code complexity analysis skipped."
        risk_level = "low"
    elif high_complex:
        summary = f"Detected {len(high_complex)} high-complexity function blocks across {analyzed} Python files."
        risk_level = "high" if len(high_complex) >= 5 else "medium"
    else:
        summary = f"No high-complexity blocks detected across {analyzed} Python files."
        risk_level = "low"

    result: AgentResult = {
        "summary": summary,
        "findings": findings,
        "risk_level": risk_level,
        "confidence": 0.85,
        "metrics": {
            "python_files_analyzed": analyzed,
            "high_complexity_count": len(high_complex),
            "time_budget_seconds": max_seconds,
        },
    }
    status = "success"
    if py_files and analyzed == 0:
        status = "degraded"
    trace_entry = trace.finalize(status=status, output={"code_quality_result": result})
    return {
        "code_quality_result": result,
        "run_trace": [trace_entry],
    }
