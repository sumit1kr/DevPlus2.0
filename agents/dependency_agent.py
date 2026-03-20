from __future__ import annotations

import time

from state.state import AgentResult, DevPulseState
from tools.trace_logger import TraceLogger
from tools.osv_tools import (
    normalize_dependency,
    parse_package_json,
    parse_package_lock_json,
    parse_poetry_lock,
    parse_pyproject_toml,
    parse_python_requirements,
    query_osv,
)


def run_dependency_analysis(state: DevPulseState) -> DevPulseState:
    trace = TraceLogger("dependency_agent", state)

    dependency_files = state.get("dependency_files", {})
    analysis_mode = state.get("analysis_mode", "repo")
    budgets = state.get("agent_budgets", {})
    max_osv_queries = int(budgets.get("dependency_osv_queries", 120))
    max_seconds = float(budgets.get("dependency_seconds", 20.0))
    deadline = time.monotonic() + max_seconds

    dependencies = []
    base_dependencies = []
    unresolved_files = []
    trace.add_tool_call("collect_dependency_files", {"count": len(dependency_files), "mode": analysis_mode})
    for path, content in dependency_files.items():
        lowered = path.lower()
        if lowered.endswith("requirements.txt") or lowered == "requirements.txt":
            dependencies.extend(parse_python_requirements(content))
        elif lowered.endswith("package.json") or lowered == "package.json":
            dependencies.extend(parse_package_json(content))
        elif lowered.endswith("pyproject.toml"):
            dependencies.extend(parse_pyproject_toml(content))
        elif lowered.endswith("poetry.lock"):
            dependencies.extend(parse_poetry_lock(content))
        elif lowered.endswith("package-lock.json"):
            dependencies.extend(parse_package_lock_json(content))
        else:
            unresolved_files.append(path)

    if analysis_mode == "pr":
        trace.add_tool_call("collect_base_dependency_files", {"count": len(state.get("pr_base_dependency_files", {}))})
        for path, content in state.get("pr_base_dependency_files", {}).items():
            lowered = path.lower()
            if lowered.endswith("requirements.txt") or lowered == "requirements.txt":
                base_dependencies.extend(parse_python_requirements(content))
            elif lowered.endswith("package.json") or lowered == "package.json":
                base_dependencies.extend(parse_package_json(content))
            elif lowered.endswith("pyproject.toml"):
                base_dependencies.extend(parse_pyproject_toml(content))
            elif lowered.endswith("poetry.lock"):
                base_dependencies.extend(parse_poetry_lock(content))
            elif lowered.endswith("package-lock.json"):
                base_dependencies.extend(parse_package_lock_json(content))

    normalized = [normalize_dependency(d["ecosystem"], d["name"], d.get("version", "")) for d in dependencies]
    unique = {(d["ecosystem"], d["name"], d.get("version", "")) for d in normalized}
    dependencies = [
        {"ecosystem": eco, "name": name, "version": ver}
        for eco, name, ver in sorted(unique, key=lambda x: (x[0], x[1]))
    ]

    base_normalized = [normalize_dependency(d["ecosystem"], d["name"], d.get("version", "")) for d in base_dependencies]
    base_unique = {(d["ecosystem"], d["name"], d.get("version", "")) for d in base_normalized}
    base_dependencies = [
        {"ecosystem": eco, "name": name, "version": ver}
        for eco, name, ver in sorted(base_unique, key=lambda x: (x[0], x[1]))
    ]

    head_set = {(d["ecosystem"], d["name"], d.get("version", "")) for d in dependencies}
    base_set = {(d["ecosystem"], d["name"], d.get("version", "")) for d in base_dependencies}
    added = sorted(list(head_set - base_set))
    removed = sorted(list(base_set - head_set))
    deps_for_vuln_scan = (
        [{"ecosystem": eco, "name": name, "version": ver} for eco, name, ver in added]
        if analysis_mode == "pr"
        else dependencies
    )

    vulnerable = []
    query_count = 0
    trace.add_tool_call("osv_query_plan", {"target_count": len(deps_for_vuln_scan), "budget": max_osv_queries})
    for dep in deps_for_vuln_scan:
        if query_count >= max_osv_queries or time.monotonic() >= deadline:
            break
        vulns = query_osv(dep["ecosystem"], dep["name"], dep.get("version", ""))
        query_count += 1
        if vulns:
            vulnerable.append({"dependency": dep, "vulns": vulns})

    warnings = list(state.get("warnings", []))
    if unresolved_files:
        warnings.append(
            f"Dependency coverage partial: unsupported manifest parsing for {len(unresolved_files)} file(s)."
        )
    if query_count < len(deps_for_vuln_scan):
        warnings.append(
            f"Dependency scan budget reached: queried {query_count}/{len(deps_for_vuln_scan)} dependencies."
        )

    findings = []
    for item in vulnerable[:10]:
        dep = item["dependency"]
        vuln = item["vulns"][0]
        mapped = _map_vuln_severity(vuln.get("severity", ""))
        has_version = bool(str(dep.get("version", "")).strip())
        findings.append(
            {
                "title": f"Vulnerability in {dep['name']}",
                "severity": mapped,
                "evidence": f"{dep['ecosystem']}:{dep['name']}@{dep.get('version', '')} -> {vuln['id']}",
                "recommendation": "Upgrade to a non-vulnerable version and verify changelog impact.",
                "confidence": 0.9 if has_version else 0.6,
                "evidence_depth": "strong" if has_version else "weak",
            }
        )

    if analysis_mode == "pr":
        summary = (
            f"PR dependency delta: +{len(added)} / -{len(removed)}. "
            f"Vulnerable newly added dependencies: {len(vulnerable)}."
        )
        risk_level = "high" if len(vulnerable) >= 1 else ("medium" if len(added) > 0 else "low")
    elif not dependencies:
        summary = "No supported dependency manifests found."
        risk_level = "low"
    elif vulnerable:
        summary = f"Detected {len(vulnerable)} vulnerable dependencies out of {len(dependencies)} analyzed."
        risk_level = "high" if len(vulnerable) >= 3 else "medium"
    else:
        summary = f"No known vulnerabilities found in {len(dependencies)} dependencies via OSV."
        risk_level = "low"

    result: AgentResult = {
        "summary": summary,
        "findings": findings,
        "risk_level": risk_level,
        "confidence": 0.8,
        "metrics": {
            "dependencies_analyzed": len(dependencies),
            "vulnerable_dependencies": len(vulnerable),
            "dependency_files_seen": len(dependency_files),
            "unsupported_manifest_files": len(unresolved_files),
            "osv_queries_executed": query_count,
            "osv_query_budget": max_osv_queries,
            "dependency_added": len(added),
            "dependency_removed": len(removed),
        },
    }

    status = "success"
    if unresolved_files or query_count < len(deps_for_vuln_scan):
        status = "degraded"
    trace_entry = trace.finalize(
        status=status,
        output={
            "dependency_result": result,
            "pr_dependency_delta": {
                "added": len(added),
                "removed": len(removed),
                "vulnerable_added": len(vulnerable),
            },
        },
    )

    return {
        "dependency_result": result,
        "warnings": warnings,
        "pr_dependency_delta": {
            "added": [{"ecosystem": eco, "name": name, "version": ver} for eco, name, ver in added],
            "removed": [{"ecosystem": eco, "name": name, "version": ver} for eco, name, ver in removed],
            "vulnerable_added": vulnerable,
        },
        "run_trace": [trace_entry],
    }


def _map_vuln_severity(raw: str) -> str:
    text = str(raw).upper()
    if "CVSS" not in text:
        return "high"

    match = None
    for token in text.replace(":", " ").replace("/", " ").split():
        try:
            value = float(token)
            match = value
            break
        except Exception:
            continue

    if match is None:
        return "high"
    if match >= 9.0:
        return "critical"
    if match >= 7.0:
        return "high"
    if match >= 4.0:
        return "medium"
    return "low"
