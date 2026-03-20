from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from tools.llm_router import LLMRouter


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def build_report(state: dict, mode: str) -> str:
    report_mode = "detailed" if str(mode).lower() == "detailed" else "moderate"
    readme_text = _extract_readme(state)

    sections: List[str] = []
    sections.append(_cover_block(state, report_mode))
    sections.append(_executive_summary(state, readme_text))
    sections.append(_repository_structure(state))
    sections.append(_health_score_breakdown(state))
    sections.append(_top_findings(state, report_mode))
    sections.append(_code_quality_details(state, report_mode))
    sections.append(_dependency_details(state, report_mode))
    sections.append(_git_health_details(state, report_mode))
    sections.append(_scan_coverage_and_warnings(state, report_mode))
    sections.append(_recommendations(state, report_mode))

    return "\n\n".join(sections).strip() + "\n"


def _cover_block(state: dict, mode: str) -> str:
    owner = str(state.get("owner", "")).strip() or "unknown"
    repo = str(state.get("repo", "")).strip() or "unknown"
    branch = str(state.get("branch", "")).strip() or "unknown"
    score = int(state.get("score_breakdown", {}).get("overall", 0))
    label = _score_label(score)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    mode_label = "Detailed" if mode == "detailed" else "Moderate"

    return (
        "# DevPulse Report\n"
        "\n"
        f"**Repository:** {owner}/{repo}  \n"
        f"**Branch:** {branch}  \n"
        f"**Scan Date & Time:** {now}  \n"
        f"**Report Mode:** {mode_label}  \n"
        f"**Overall Health Score:** **{score}/100 ({label})**"
    )


def _extract_readme(state: dict) -> str:
    fetched_files = state.get("fetched_files", {}) or {}
    for path, content in fetched_files.items():
        lowered = str(path).lower()
        if lowered.endswith(("readme.md", "readme.rst", "readme.txt")):
            return str(content)[:2000]
    return ""


def _executive_summary(state: dict, readme_text: str) -> str:
    code = state.get("code_quality_result", {})
    dep = state.get("dependency_result", {})
    git = state.get("git_history_result", {})
    sec = state.get("security_result", {})
    score_breakdown = state.get("score_breakdown", {})

    overall = int(score_breakdown.get("overall", 0))
    overall_label = _score_label(overall)
    dep_vulns = int(dep.get("metrics", {}).get("vulnerable_dependencies", 0))
    code_issues = int(code.get("metrics", {}).get("high_complexity_count", 0))
    commits = int(git.get("metrics", {}).get("commit_count", 0))
    active = bool(git.get("metrics", {}).get("active_last_30d", False))
    sec_findings = len(sec.get("findings", []))
    file_count = int(state.get("scan_coverage", {}).get("tree_files_indexed", len(state.get("files_index", []))))

    detected_languages = state.get("detected_languages", {}) or {}
    if detected_languages:
        language = next(iter(detected_languages.keys()))
    else:
        fallback_langs = _detect_languages(state.get("files_index", []) or [])
        language = fallback_langs[0] if fallback_langs else "Python"

    llm_summary = ""
    if readme_text:
        try:
            router = LLMRouter()
            if router.available():
                system_prompt = (
                    "You write plain English summaries for non-technical readers like managers and stakeholders. "
                    "Be specific about what the project does. "
                    "Never use phrases like 'software project' or 'codebase'. "
                    "Write exactly 3 sentences. No bullet points."
                )
                user_prompt = (
                    "Write a 3-sentence plain English summary of this repository "
                    "for a non-technical reader. Use the README below to explain "
                    "what this project actually does and who it is for.\n"
                    "Then mention the scan findings naturally in the third sentence.\n\n"
                    f"README:\n{readme_text}\n\n"
                    "Scan findings to mention:\n"
                    f"- Overall health score: {overall}/100 ({overall_label})\n"
                    f"- Vulnerable dependencies found: {dep_vulns}\n"
                    f"- High complexity functions: {code_issues}\n"
                    f"- Security pattern findings: {sec_findings}\n"
                    f"- Active development: {str(active).lower()}\n\n"
                    "Rules:\n"
                    "- Sentence 1: What does this project do in plain English?\n"
                    "- Sentence 2: Who uses it and what does it produce?\n"
                    "- Sentence 3: What did the scan find? Keep it factual and simple."
                )
                llm_summary = router.invoke_text(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    primary="gemini",
                    fallback="groq",
                    temperature=0.2,
                ).strip()
        except Exception:
            llm_summary = ""

    if llm_summary:
        return (
            "## Executive Summary\n"
            "This section explains the overall repository condition in plain language.\n\n"
            f"{llm_summary}"
        )

    summary = (
        "## Executive Summary\n"
        "This section explains the overall repository condition in plain language.\n\n"
        f"Based on the repository name and structure, this project contains {file_count} files across {language} "
        f"and has {commits} recent commits. "
        f"The scan found an overall health score of {overall}/100 ({overall_label}), with {dep_vulns} vulnerable dependencies, "
        f"{code_issues} high-complexity functions, and {sec_findings} security pattern findings."
    )
    return summary


def _repository_structure(state: dict) -> str:
    files_index = state.get("files_index", []) or []
    coverage = state.get("scan_coverage", {}) or {}
    dependency_files = state.get("dependency_files", {}) or {}
    detected_languages = state.get("detected_languages", {}) or {}
    branch = str(state.get("branch", "")).strip() or "unknown"

    source_scanned = int(coverage.get("source_fetched", 0))
    source_available = int(coverage.get("source_candidates", 0))
    indexed_files = int(coverage.get("tree_files_indexed", len(files_index)))
    dep_count = int(coverage.get("dependency_files_found", len(dependency_files)))
    depth = int(coverage.get("scan_depth_effective", state.get("scan_depth", 0) or 0))

    lang_text = _format_detected_languages(detected_languages)
    if not lang_text:
        lang_text = "Python"

    return (
        "## Repository Structure\n"
        "This section shows what repository content was scanned and how much was covered.\n\n"
        "| Item | Value |\n"
        "|---|---|\n"
        f"| Total files indexed | {indexed_files} |\n"
        f"| Source files scanned vs available | {source_scanned} / {source_available} |\n"
        f"| Languages detected | {lang_text} |\n"
        f"| Dependency files found | {dep_count} |\n"
        f"| Scan depth used | {depth} |\n"
        f"| Branch analysed | {branch} |"
    )


def _format_detected_languages(detected_languages: Dict[str, Any]) -> str:
    if not isinstance(detected_languages, dict) or not detected_languages:
        return ""

    ordered = []
    for lang, count in detected_languages.items():
        try:
            parsed_count = int(count)
        except Exception:
            continue
        if parsed_count <= 0:
            continue
        ordered.append((str(lang), parsed_count))

    if not ordered:
        return ""

    ordered.sort(key=lambda x: x[1], reverse=True)
    total_lang_files = sum(count for _, count in ordered)
    if total_lang_files <= 0:
        return ""

    parts = []
    for lang, count in ordered:
        pct = round((count / total_lang_files) * 100)
        parts.append(f"{lang} ({pct}%)")

    return ", ".join(parts)


def _health_score_breakdown(state: dict) -> str:
    sb = state.get("score_breakdown", {}) or {}

    code = int(sb.get("code_quality", 0))
    dep = int(sb.get("dependency", 0))
    git = int(sb.get("git_history", 0))

    weighted_base = int(round(code * 0.45 + dep * 0.35 + git * 0.20))
    penalty_missing = int(sb.get("penalty_missing_tests", 0))
    penalty_critical = int(sb.get("penalty_critical_vulnerabilities", 0))
    penalty_stale = int(sb.get("penalty_stale_commit_activity", 0))
    penalty_total = int(sb.get("penalty_total", penalty_missing + penalty_critical + penalty_stale))

    final_score = int(sb.get("overall", max(0, weighted_base - penalty_total)))
    final_label = _score_label(final_score)

    return (
        "## Health Score Breakdown\n"
        "This section explains how the final health score was composed.\n\n"
        "| Area | Score | Weight | Status |\n"
        "|---|---:|---:|---|\n"
        f"| Code Quality | {code}/100 | 45% | {_score_label(code)} |\n"
        f"| Dependency Risk | {dep}/100 | 35% | {_score_label(dep)} |\n"
        f"| Git Health | {git}/100 | 20% | {_score_label(git)} |\n\n"
        f"**Weighted Base Score:** **{weighted_base}/100**\n\n"
        f"- Missing tests penalty: **{penalty_missing}**\n"
        f"- Critical vulnerabilities penalty: **{penalty_critical}**\n"
        f"- Stale commit activity penalty: **{penalty_stale}**\n"
        f"- Total penalties: **{penalty_total}**\n\n"
        f"**Final Overall Score:** **{final_score}/100 ({final_label})**"
    )


def _top_findings(state: dict, mode: str) -> str:
    findings = _collect_all_findings(state)
    findings.sort(key=lambda x: SEVERITY_ORDER.get(str(x.get("severity", "low")).lower(), 4))

    if mode == "moderate":
        findings = [f for f in findings if str(f.get("severity", "low")).lower() in {"critical", "high", "medium"}]

    findings = _deduplicate_findings(findings)
    findings = findings[:15]

    lines = [
        "## Top Findings",
        "This section lists the most important issues in priority order.",
        "",
        "| Severity | Issue Title | What it means | Fix suggestion |",
        "|---|---|---|---|",
    ]

    if not findings:
        lines.append("| LOW | No major findings detected | The scan did not identify urgent issues. | Keep monitoring changes over time. |")
        return "\n".join(lines)

    for item in findings:
        sev = str(item.get("severity", "low")).upper()
        title = _clean_cell(str(item.get("title", "Issue")))
        meaning = _clean_cell(_plain_english_meaning(item))
        rec = _clean_cell(str(item.get("recommendation", "Review and fix this issue.")))
        lines.append(f"| {sev} | {title} | {meaning} | {rec} |")

    return "\n".join(lines)


def _extract_location_hint(evidence: str) -> str:
    text = str(evidence or "").strip()
    if not text:
        return ""

    if "file=" in text:
        try:
            part = text.split("file=", 1)[1]
            return part.split(";", 1)[0].strip()
        except Exception:
            pass

    if " (" in text:
        return text.split(" (", 1)[0].strip()

    return text


def _deduplicate_findings(findings: list[dict]) -> list[dict]:
    seen: Dict[str, Dict[str, Any]] = {}

    for f in findings:
        title = str(f.get("title", "")).strip()
        key = title.lower().strip()
        location = _extract_location_hint(str(f.get("evidence", "")))
        if key not in seen:
            seen[key] = {
                **f,
                "locations": [location] if location else [],
                "count": 1,
            }
        else:
            seen[key]["count"] += 1
            if location and location not in seen[key]["locations"]:
                seen[key]["locations"].append(location)

    result: list[dict] = []
    for _, item in seen.items():
        count = int(item.get("count", 1))
        title = str(item.get("title", "Issue"))

        if count > 1:
            locs = [str(x) for x in item.get("locations", []) if str(x).strip()]
            loc_preview = locs[:3]
            suffix = f" (+{count - 3} more)" if count > 3 else ""
            if loc_preview:
                item["evidence"] = f"Found in {count} locations: {'; '.join(loc_preview)}{suffix}"
            else:
                item["evidence"] = f"Found in {count} locations"

            if title.startswith("High complexity in "):
                func_name = title.replace("High complexity in ", "").strip()
                item["title"] = f"{func_name} ({count} locations)"
            elif title.startswith("Unsafe code pattern detected"):
                pattern_name = title.replace("Unsafe code pattern detected", "").strip().strip("()")
                item["title"] = f"Unsafe code pattern ({pattern_name})"

        item.pop("locations", None)
        item.pop("count", None)
        result.append(item)

    result.sort(key=lambda x: SEVERITY_ORDER.get(str(x.get("severity", "low")).lower(), 4))
    return result


def _code_quality_details(state: dict, mode: str) -> str:
    result = state.get("code_quality_result", {}) or {}
    findings = result.get("findings", []) or []

    filtered = findings
    if mode == "moderate":
        filtered = [f for f in findings if str(f.get("severity", "low")).lower() in {"high", "critical"}]

    lines = [
        "## Code Quality Details",
        "This section explains maintainability risks caused by complex code blocks.",
        "",
        str(result.get("summary", "No code quality summary available.")),
        "",
        "| File | Function | Complexity Score | Risk Level |",
        "|---|---|---:|---|",
    ]

    if not filtered:
        lines.append("| n/a | n/a | n/a | Low |")
        return "\n".join(lines)

    for f in filtered:
        file_name, func, complexity = _parse_complexity_evidence(str(f.get("evidence", "")))
        risk = str(f.get("severity", "low")).upper()
        lines.append(f"| {_clean_cell(file_name)} | {_clean_cell(func)} | {complexity} | {risk} |")

    return "\n".join(lines)


def _dependency_details(state: dict, mode: str) -> str:
    result = state.get("dependency_result", {}) or {}
    findings = result.get("findings", []) or []

    if mode == "moderate":
        findings = [f for f in findings if str(f.get("severity", "low")).lower() in {"critical", "high"}]

    lines = [
        "## Dependency & Vulnerability Details",
        "This section highlights external packages that may introduce known security issues.",
        "",
        str(result.get("summary", "No dependency summary available.")),
        "",
        "| Package | Version | Vulnerability ID | Severity | Fix Action |",
        "|---|---|---|---|---|",
    ]

    if not findings:
        lines.append("No vulnerable dependencies detected in scanned packages.")
        return "\n".join(lines)

    explanation_lines = ["", "Plain English impact notes:"]

    for f in findings:
        parsed = _parse_dep_evidence(str(f.get("evidence", "")))
        pkg = parsed["package"]
        ver = parsed["version"]
        vuln_id = parsed["vuln_id"]
        sev = str(f.get("severity", "low")).upper()
        sev_lower = str(f.get("severity", "low")).lower()
        rec = _clean_cell(str(f.get("recommendation", "Update to a safe version.")))
        lines.append(f"| {_clean_cell(pkg)} | {_clean_cell(ver)} | {_clean_cell(vuln_id)} | {sev} | {rec} |")
        explanation_lines.append(f"- {_clean_cell(_vuln_plain_english(sev_lower, pkg, vuln_id))}")

    return "\n".join(lines + explanation_lines)


def _git_health_details(state: dict, mode: str) -> str:
    result = state.get("git_history_result", {}) or {}
    metrics = result.get("metrics", {}) or {}

    commit_count = int(metrics.get("commit_count", 0))
    conventional = int(metrics.get("conventional_messages", 0))
    short_msgs = int(metrics.get("short_messages", 0))
    active = bool(metrics.get("active_last_30d", False))
    conventional_pct = 0
    if commit_count > 0:
        conventional_pct = int(round((conventional / commit_count) * 100))

    lines = [
        "## Git Health Details",
        "This section reflects development activity and commit quality signals.",
        "",
        str(result.get("summary", "No git health summary available.")),
    ]

    if mode == "moderate":
        lines.append(
            f"Recent activity status: {'Active' if active else 'Not active'}; "
            f"commit quality trend: {conventional_pct}% conventional messages."
        )
        return "\n".join(lines)

    lines.extend(
        [
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Total commits analysed | {commit_count} |",
            f"| Conventional commits % | {conventional_pct}% |",
            f"| Active in last 30 days | {'Yes' if active else 'No'} |",
            f"| Short/bad messages count | {short_msgs} |",
        ]
    )
    return "\n".join(lines)


def _scan_coverage_and_warnings(state: dict, mode: str) -> str:
    coverage = state.get("scan_coverage", {}) or {}
    warnings = list(state.get("warnings", []) or [])

    if mode == "moderate":
        warnings = [w for w in warnings if _is_high_impact_warning(w)]

    lines = [
        "## Scan Coverage & Warnings",
        "This section explains scan completeness and any cautions that may affect confidence.",
        "",
        "| Coverage Item | Value |",
        "|---|---|",
        f"| Total files indexed | {int(coverage.get('tree_files_indexed', 0))} |",
        f"| Source candidates | {int(coverage.get('source_candidates', 0))} |",
        f"| Source fetched | {int(coverage.get('source_fetched', 0))} |",
        f"| Dependency files found | {int(coverage.get('dependency_files_found', 0))} |",
        f"| Scan depth requested | {int(coverage.get('scan_depth_requested', 0))} |",
        f"| Scan depth effective | {int(coverage.get('scan_depth_effective', 0))} |",
        "",
        "Warnings:",
    ]

    if not warnings:
        lines.append("- No warnings were recorded for this scan.")
    else:
        for w in warnings:
            lines.append(f"- {w}")
            lower_w = str(w).lower()
            if "dependency scan budget reached" in lower_w:
                lines.append("  -> To scan all dependencies, increase scan depth in the UI slider before re-running the audit.")
            elif "partial source scan" in lower_w:
                lines.append("  -> Increase the scan depth slider to cover more files.")

    return "\n".join(lines)


def _recommendations(state: dict, mode: str) -> str:
    recs: List[Dict[str, Any]] = []

    dep_findings = state.get("dependency_result", {}).get("findings", []) or []
    vuln_packages: List[str] = []
    for f in dep_findings:
        evidence = str(f.get("evidence", ""))
        parsed = _parse_dep_evidence(evidence)
        pkg = parsed.get("package", "—")
        vuln_id = parsed.get("vuln_id", "—")
        if pkg == "—" and vuln_id == "—":
            vuln_packages.append("vulnerable dependency")
        else:
            vuln_packages.append(f"`{pkg}` (fixes {vuln_id})")

    vuln_packages = list(dict.fromkeys(vuln_packages))
    if vuln_packages:
        recs.append(
            {
                "priority": 1,
                "label": "SECURITY",
                "text": (
                    f"Upgrade {', '.join(vuln_packages)} to patched versions to close known security vulnerabilities."
                ),
            }
        )

    sec_findings = state.get("security_result", {}).get("findings", []) or []
    if sec_findings:
        sec_types = list(
            {
                str(f.get("title", ""))
                .replace("Unsafe code pattern detected", "")
                .strip()
                .strip("()")
                for f in sec_findings
                if str(f.get("title", "")).startswith("Unsafe code pattern detected")
            }
        )
        if sec_types:
            recs.append(
                {
                    "priority": 2,
                    "label": "SECURITY",
                    "text": (
                        f"Review and replace unsafe code patterns: {', '.join(sec_types[:3])}. "
                        f"Validate all user-controlled inputs reaching these."
                    ),
                }
            )

    cq_findings = state.get("code_quality_result", {}).get("findings", []) or []
    if cq_findings:
        worst_finding = max(cq_findings, key=_extract_complexity, default=cq_findings[0])
        worst_score = _extract_complexity(worst_finding)
        worst_file, _, _ = _parse_complexity_evidence(str(worst_finding.get("evidence", "")))
        worst_func = str(worst_finding.get("title", "")).replace("High complexity in", "").strip()
        count = len(cq_findings)
        recs.append(
            {
                "priority": 3,
                "label": "CODE QUALITY",
                "text": (
                    f"Refactor {count} high-complexity functions - the worst is `{worst_func}` in {worst_file} "
                    f"with a complexity score of {worst_score}. Break large functions into smaller focused ones "
                    f"and add unit tests per function."
                ),
            }
        )

    score_breakdown = state.get("score_breakdown", {}) or {}
    if int(score_breakdown.get("penalty_missing_tests", 0)) > 0:
        recs.append(
            {
                "priority": 4,
                "label": "TESTING",
                "text": (
                    "Add test files to the repository. No test files were detected which increases the risk "
                    "of undetected regressions."
                ),
            }
        )

    if int(score_breakdown.get("penalty_stale_commit_activity", 0)) > 0:
        recs.append(
            {
                "priority": 5,
                "label": "MAINTENANCE",
                "text": "Resume active development - no commits detected in the last 30 days signals low maintenance.",
            }
        )

    recs.append(
        {
            "priority": 99,
            "label": "PROCESS",
            "text": "Re-run DevPulse after applying fixes to confirm score improvement and track health trend over time.",
        }
    )

    recs.sort(key=lambda x: int(x.get("priority", 99)))
    if mode == "moderate":
        recs = recs[:3]

    lines = [
        "## Recommendations",
        "This section provides a prioritized action plan to improve repository health.",
    ]

    for idx, rec in enumerate(recs, start=1):
        lines.append(f"{idx}. [{rec['label']}] {rec['text']}")

    return "\n".join(lines)


def _collect_all_findings(state: dict) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key in ("code_quality_result", "dependency_result", "git_history_result", "security_result"):
        payload = state.get(key, {}) or {}
        for f in payload.get("findings", []) or []:
            item = dict(f)
            item["source"] = key
            out.append(item)
    return out


def _plain_english_meaning(finding: Dict[str, Any]) -> str:
    text = f"{finding.get('title', '')} {finding.get('evidence', '')}".lower()

    if "complex" in text or "complexity" in text:
        return "This part of the code is hard to understand and may be risky to change quickly."
    if "vulnerability" in text or "cve" in text or "osv" in text:
        return "A known security issue exists in a library, so attackers may exploit it if not patched."
    if "secret" in text or "token" in text or "password" in text or "private key" in text:
        return "Sensitive credentials may be exposed, which could allow unauthorized access."
    if "license" in text:
        return "There may be legal usage obligations that need review before commercial use."
    if "commit" in text:
        return "Development history signals possible process quality or maintenance concerns."
    if "unsafe" in text or "eval" in text or "exec" in text:
        return "This coding pattern can increase security risk if untrusted input reaches it."
    return "This issue may reduce reliability, security, or maintainability if left unresolved."


def _parse_complexity_evidence(evidence: str) -> Tuple[str, str, str]:
    file_name = "unknown"
    function_name = "unknown"
    complexity = "n/a"

    if ", complexity=" in evidence:
        left, complexity = evidence.rsplit(", complexity=", 1)
        complexity = complexity.strip()
    else:
        left = evidence

    if " (" in left and left.endswith(")"):
        file_name, rest = left.split(" (", 1)
        function_name = rest[:-1]
    else:
        file_name = left.strip() or "unknown"

    return file_name.strip(), function_name.strip(), complexity


def _extract_complexity(finding: dict) -> int:
    evidence = str(finding.get("evidence", ""))
    try:
        if "complexity=" in evidence:
            return int(evidence.split("complexity=")[-1].strip())
    except Exception:
        pass
    return 0


def _parse_dep_evidence(evidence: str) -> Dict[str, str]:
    ecosystem = "—"
    package = "—"
    version = "—"
    vuln_id = "—"

    try:
        left, right = evidence.split(" -> ", 1)
        vuln_id = right.strip() or "—"
    except Exception:
        left = evidence

    try:
        eco_part, pkg_part = left.split(":", 1)
        ecosystem = eco_part.strip() or "—"
    except Exception:
        pkg_part = left

    try:
        pkg, ver = pkg_part.split("@", 1)
        package = pkg.strip() or "—"
        version = ver.strip() or "—"
    except Exception:
        package = (pkg_part or "").strip() or "—"

    # Keep the parser robust even when ecosystem is absent; package output stays useful.
    _ = ecosystem
    return {
        "package": package,
        "version": version,
        "vuln_id": vuln_id,
    }


def _vuln_plain_english(severity: str, package: str, vuln_id: str) -> str:
    sev = str(severity or "").lower()
    pkg = package or "dependency"
    vid = vuln_id or "known advisory"

    if sev == "critical":
        return (
            f"{pkg} ({vid}): This is a critical security flaw. "
            f"Attackers can actively exploit this right now. "
            f"Upgrade immediately before deploying."
        )
    if sev == "high":
        return (
            f"{pkg} ({vid}): A serious vulnerability exists. "
            f"This could allow attackers to access or corrupt data. "
            f"Upgrade as soon as possible."
        )
    if sev == "medium":
        return (
            f"{pkg} ({vid}): A moderate security issue. "
            f"Risk is lower but should be patched in the next release."
        )
    return (
        f"{pkg} ({vid}): A low-severity known issue. "
        f"Upgrade when convenient as part of regular maintenance."
    )


def _detect_languages(files_index: List[Dict[str, Any]]) -> List[str]:
    ext_map = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".jsx": "JavaScript",
        ".java": "Java",
        ".go": "Go",
        ".rs": "Rust",
        ".cpp": "C++",
        ".c": "C",
        ".cs": "C#",
        ".rb": "Ruby",
        ".php": "PHP",
        ".swift": "Swift",
        ".kt": "Kotlin",
    }

    found = set()
    for item in files_index:
        path = str(item.get("path", "")).lower()
        for ext, lang in ext_map.items():
            if path.endswith(ext):
                found.add(lang)

    return sorted(found)


def _score_label(score: int) -> str:
    if score >= 75:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Needs Attention"


def _is_high_impact_warning(text: str) -> bool:
    lower = str(text).lower()
    keywords = ("critical", "vulnerab", "failed", "error", "timed out", "budget reached")
    return any(k in lower for k in keywords)


def _clean_cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _recommendation_style(text: str) -> str:
    value = text.strip()
    if not value:
        return "You should review this issue and apply a fix."

    lower = value.lower()
    if lower.startswith("you should"):
        return value

    action_verbs = (
        "update",
        "upgrade",
        "refactor",
        "remove",
        "add",
        "review",
        "adopt",
        "replace",
        "rotate",
        "monitor",
    )
    if any(lower.startswith(v) for v in action_verbs):
        return value[0].upper() + value[1:]

    return f"You should {value[0].lower() + value[1:]}"
