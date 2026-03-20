from __future__ import annotations

import json
import re
from typing import Dict, List

from state.state import AgentResult, DevPulseState
from tools.trace_logger import TraceLogger


SECRET_PATTERNS = [
    ("api_key_openai", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("api_key_github", re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")),
    ("api_key_aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("hardcoded_password", re.compile(r"(?i)\bpassword\s*[:=]\s*['\"].+?['\"]")),
    ("hardcoded_secret", re.compile(r"(?i)\bsecret\s*[:=]\s*['\"].+?['\"]")),
    ("token_literal", re.compile(r"(?i)\btoken\s*[:=]\s*['\"][A-Za-z0-9_\-\.]{8,}['\"]")),
    ("private_key", re.compile(r"BEGIN (RSA|EC) PRIVATE KEY")),
]

UNSAFE_PATTERNS = [
    ("eval_usage", re.compile(r"\beval\s*\(")),
    ("exec_usage", re.compile(r"\bexec\s*\(")),
    ("os_system", re.compile(r"\bos\.system\s*\(")),
    ("subprocess_shell_true", re.compile(r"\bsubprocess\.[A-Za-z_]+\s*\([^\)]*shell\s*=\s*True")),
    ("pickle_loads", re.compile(r"\bpickle\.loads\s*\(")),
    ("raw_sql_format", re.compile(r"(?is)(select|insert|update|delete)\s+.+(%\(|\.format\(|f\")")),
]

GPL_TERMS = ("gpl", "agpl", "lgpl")
STRONG_SECURITY_CATEGORIES = {
    "private_key",
    "api_key_openai",
    "api_key_github",
    "api_key_aws",
    "subprocess_shell_true",
    "os_system",
    "eval_usage",
    "exec_usage",
    "pickle_loads",
}


def run_security_analysis(state: DevPulseState) -> DevPulseState:
    trace = TraceLogger("security_agent", state)

    files = state.get("fetched_files", {})
    dependency_files = state.get("dependency_files", {})
    trace.add_tool_call("collect_files", {"fetched_files": len(files), "dependency_files": len(dependency_files)})

    findings: List[Dict] = []

    secret_findings = _scan_secret_leaks(files)
    findings.extend(secret_findings)

    license_findings = _scan_license_risk(state, files, dependency_files)
    findings.extend(license_findings)

    unsafe_findings = _scan_unsafe_patterns(files)
    findings.extend(unsafe_findings)

    exploitability_findings = _build_exploitability_context(state)
    findings.extend(exploitability_findings)

    metrics = {
        "secret_leak_count": len(secret_findings),
        "license_risk_count": len(license_findings),
        "unsafe_pattern_count": len(unsafe_findings),
        "exploitability_items": len(exploitability_findings),
    }

    high_or_critical = sum(1 for f in findings if f.get("severity") in {"high", "critical"})
    if high_or_critical >= 3:
        risk_level = "high"
    elif high_or_critical >= 1 or len(findings) >= 4:
        risk_level = "medium"
    else:
        risk_level = "low"

    summary = (
        f"Security scan completed with {len(findings)} findings "
        f"(secrets={len(secret_findings)}, unsafe={len(unsafe_findings)}, license={len(license_findings)})."
    )

    result: AgentResult = {
        "summary": summary,
        "findings": findings[:20],
        "risk_level": risk_level,
        "confidence": 0.8,
        "metrics": metrics,
    }

    status = "success" if not findings else ("degraded" if high_or_critical == 0 else "success")
    trace_entry = trace.finalize(status=status, output={"security_result": result})

    return {
        "security_result": result,
        "run_trace": [trace_entry],
    }


def _finding_confidence_for_category(category: str) -> float:
    return 0.9 if category in STRONG_SECURITY_CATEGORIES else 0.75


def _evidence_depth_for_category(category: str) -> str:
    return "strong" if category in STRONG_SECURITY_CATEGORIES else "moderate"


def _scan_secret_leaks(files: Dict[str, str]) -> List[Dict]:
    findings: List[Dict] = []
    for path, content in files.items():
        for category, pattern in SECRET_PATTERNS:
            match = pattern.search(content)
            if match:
                findings.append(
                    {
                        "title": f"Potential secret leak ({category})",
                        "severity": "critical" if category == "private_key" else "high",
                        "evidence": f"category=secret_leak; file={path}; sample={match.group(0)[:80]}",
                        "recommendation": "Remove secret from source, rotate credentials, and use environment-based secret management.",
                        "confidence": _finding_confidence_for_category(category),
                        "evidence_depth": _evidence_depth_for_category(category),
                    }
                )
    return findings


def _scan_license_risk(state: DevPulseState, files: Dict[str, str], dependency_files: Dict[str, str]) -> List[Dict]:
    findings: List[Dict] = []

    repo_license_text = ""
    for path, content in files.items():
        if path.lower().endswith(("license", "license.md", "license.txt")):
            repo_license_text = content.lower()
            break

    declared_licenses = _collect_declared_licenses(dependency_files)

    commercial_repo = _is_probably_commercial_repo(repo_license_text)
    if not commercial_repo:
        return findings

    gpl_hits = [lic for lic in declared_licenses if any(term in lic.lower() for term in GPL_TERMS)]
    if any(term in repo_license_text for term in GPL_TERMS):
        gpl_hits.append("repo_license")

    if gpl_hits:
        findings.append(
            {
                "title": "Potential copyleft license risk for commercial usage",
                "severity": "medium",
                "evidence": f"category=license_risk; indicators={sorted(set(gpl_hits))}",
                "recommendation": "Review license obligations with legal/compliance before commercial distribution.",
                "confidence": _finding_confidence_for_category("license_risk"),
                "evidence_depth": _evidence_depth_for_category("license_risk"),
            }
        )

    return findings


def _collect_declared_licenses(dependency_files: Dict[str, str]) -> List[str]:
    licenses: List[str] = []
    for path, content in dependency_files.items():
        lowered = path.lower()
        try:
            if lowered.endswith("package.json"):
                payload = json.loads(content)
                if isinstance(payload.get("license"), str):
                    licenses.append(payload["license"])
                if isinstance(payload.get("licenses"), list):
                    licenses.extend([str(x) for x in payload["licenses"]])
            elif lowered.endswith("pyproject.toml"):
                # Lightweight extraction for license fields without requiring tomllib parse in this module.
                for line in content.splitlines():
                    raw = line.strip().lower()
                    if raw.startswith("license") and "=" in raw:
                        licenses.append(line.split("=", 1)[1].strip().strip("\"'"))
        except Exception:
            continue
    return licenses


def _is_probably_commercial_repo(repo_license_text: str) -> bool:
    if not repo_license_text:
        return True
    permissive_markers = ("mit license", "apache license", "bsd license", "mozilla public license", "mpl-2.0")
    if any(marker in repo_license_text for marker in permissive_markers):
        return False
    if "all rights reserved" in repo_license_text:
        return True
    return True


def _scan_unsafe_patterns(files: Dict[str, str]) -> List[Dict]:
    findings: List[Dict] = []
    for path, content in files.items():
        lowered = path.lower()
        if not lowered.endswith((".py", ".js", ".ts", ".tsx", ".jsx")):
            continue
        for category, pattern in UNSAFE_PATTERNS:
            match = pattern.search(content)
            if match:
                findings.append(
                    {
                        "title": f"Unsafe code pattern detected ({category})",
                        "severity": "medium" if category != "subprocess_shell_true" else "high",
                        "evidence": f"category=unsafe_pattern; file={path}; sample={match.group(0)[:100]}",
                        "recommendation": "Replace with safer alternatives and validate user-controlled input paths.",
                        "confidence": _finding_confidence_for_category(category),
                        "evidence_depth": _evidence_depth_for_category(category),
                    }
                )
    return findings


def _build_exploitability_context(state: DevPulseState) -> List[Dict]:
    findings: List[Dict] = []

    vuln_groups = state.get("pr_dependency_delta", {}).get("vulnerable_added", [])
    if not vuln_groups:
        return findings

    for item in vuln_groups:
        dep = item.get("dependency", {})
        vulns = item.get("vulns", [])
        for vuln in vulns:
            vector = str(vuln.get("cvss_vector", ""))
            if not vector:
                continue
            tag = _exploitability_tag(vector)
            findings.append(
                {
                    "title": f"Exploitability context for {dep.get('name', 'dependency')}",
                    "severity": "low",
                    "evidence": f"category=exploitability; vuln={vuln.get('id', 'unknown')}; tag={tag}; vector={vector}",
                    "recommendation": "Prioritize remediation based on exploitability and exposure in deployment environment.",
                    "confidence": _finding_confidence_for_category("exploitability"),
                    "evidence_depth": _evidence_depth_for_category("exploitability"),
                }
            )

    return findings


def _exploitability_tag(vector: str) -> str:
    upper = vector.upper()
    if "PR:H" in upper or "PR:L" in upper:
        return "requires-auth"
    if "AV:N" in upper:
        return "network-reachable"
    return "local-only"
