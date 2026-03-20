from __future__ import annotations

from typing import Any, Dict, List, Tuple

ALLOWED_RISK = {"low", "medium", "high", "critical"}
ALLOWED_SEVERITY = {"low", "medium", "high", "critical"}
ALLOWED_EVIDENCE_DEPTH = {"strong", "moderate", "weak"}


def validate_agent_result(agent_name: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    result = payload if isinstance(payload, dict) else {}

    summary = result.get("summary", "")
    if not isinstance(summary, str):
        warnings.append(f"{agent_name}: invalid summary type, replaced with fallback string")
        summary = "Result summary unavailable due to validation fallback."

    risk_level = str(result.get("risk_level", "medium")).lower()
    if risk_level not in ALLOWED_RISK:
        warnings.append(f"{agent_name}: invalid risk_level '{risk_level}', defaulted to medium")
        risk_level = "medium"

    confidence = result.get("confidence", 0.5)
    if not isinstance(confidence, (float, int)):
        warnings.append(f"{agent_name}: invalid confidence type, defaulted to 0.5")
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))

    metrics = result.get("metrics", {})
    if not isinstance(metrics, dict):
        warnings.append(f"{agent_name}: invalid metrics type, replaced with empty dict")
        metrics = {}

    findings: List[Dict[str, Any]] = []
    raw_findings = result.get("findings", [])
    if not isinstance(raw_findings, list):
        warnings.append(f"{agent_name}: findings must be a list, replaced with empty list")
        raw_findings = []

    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "Unnamed finding")
        severity = str(item.get("severity", "low")).lower()
        evidence = item.get("evidence", "n/a")
        recommendation = item.get("recommendation", "Review this issue and apply an appropriate fix.")
        finding_confidence = item.get("confidence", confidence)
        evidence_depth = str(item.get("evidence_depth", "moderate")).lower()

        if severity not in ALLOWED_SEVERITY:
            severity = "low"
        if not isinstance(finding_confidence, (float, int)):
            finding_confidence = confidence
        finding_confidence = max(0.0, min(1.0, float(finding_confidence)))
        if evidence_depth not in ALLOWED_EVIDENCE_DEPTH:
            evidence_depth = "moderate"

        findings.append(
            {
                "title": str(title),
                "severity": severity,
                "evidence": str(evidence),
                "recommendation": str(recommendation),
                "confidence": finding_confidence,
                "evidence_depth": evidence_depth,
            }
        )

    validated = {
        "summary": summary,
        "findings": findings,
        "risk_level": risk_level,
        "confidence": confidence,
        "metrics": metrics,
    }
    return validated, warnings
