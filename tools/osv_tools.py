from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import tomllib

from tools.cache_store import get_cache, set_cache
from tools.http_utils import request_with_retry


OSV_QUERY_URL = "https://api.osv.dev/v1/query"


def normalize_dependency(ecosystem: str, name: str, version: str = "") -> Dict[str, str]:
    clean_name = name.strip().lower().replace("_", "-")
    clean_version = _clean_version(version)
    return {"ecosystem": ecosystem, "name": clean_name, "version": clean_version}


def parse_python_requirements(content: str) -> List[Dict[str, str]]:
    deps: List[Dict[str, str]] = []
    for line in content.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("-"):
            continue

        match = re.match(r"^([A-Za-z0-9_.\-]+)\s*([<>=!~]{1,2})?\s*([A-Za-z0-9_.\-]+)?", raw)
        if not match:
            continue
        name, op, version = match.group(1), match.group(2), match.group(3)
        deps.append(normalize_dependency("PyPI", name, version if op in {"==", "==="} else ""))
    return deps


def parse_package_json(content: str) -> List[Dict[str, str]]:
    deps: List[Dict[str, str]] = []
    try:
        payload = json.loads(content)
    except Exception:
        return deps

    for section in ("dependencies", "devDependencies"):
        values = payload.get(section, {}) or {}
        for name, version in values.items():
            deps.append(normalize_dependency("npm", name, str(version)))
    return deps


def parse_pyproject_toml(content: str) -> List[Dict[str, str]]:
    deps: List[Dict[str, str]] = []
    try:
        payload = tomllib.loads(content)
    except Exception:
        return deps

    project_deps = payload.get("project", {}).get("dependencies", []) or []
    for item in project_deps:
        parsed = _parse_python_dep_str(str(item))
        if parsed:
            deps.append(normalize_dependency("PyPI", parsed["name"], parsed["version"]))

    opt = payload.get("project", {}).get("optional-dependencies", {}) or {}
    for _, items in opt.items():
        for item in items or []:
            parsed = _parse_python_dep_str(str(item))
            if parsed:
                deps.append(normalize_dependency("PyPI", parsed["name"], parsed["version"]))

    poetry_deps = payload.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
    for name, spec in poetry_deps.items():
        if str(name).lower() == "python":
            continue
        version = spec if isinstance(spec, str) else spec.get("version", "") if isinstance(spec, dict) else ""
        deps.append(normalize_dependency("PyPI", str(name), str(version)))

    return deps


def parse_poetry_lock(content: str) -> List[Dict[str, str]]:
    deps: List[Dict[str, str]] = []
    try:
        payload = tomllib.loads(content)
    except Exception:
        return deps

    for pkg in payload.get("package", []) or []:
        name = str(pkg.get("name", "")).strip()
        version = str(pkg.get("version", "")).strip()
        if not name:
            continue
        deps.append(normalize_dependency("PyPI", name, version))

    return deps


def parse_package_lock_json(content: str) -> List[Dict[str, str]]:
    deps: List[Dict[str, str]] = []
    try:
        payload = json.loads(content)
    except Exception:
        return deps

    root_deps = payload.get("dependencies", {}) or {}
    for name, data in root_deps.items():
        version = data.get("version", "") if isinstance(data, dict) else ""
        deps.append(normalize_dependency("npm", str(name), str(version)))

    packages = payload.get("packages", {}) or {}
    for pkg_path, data in packages.items():
        if not isinstance(data, dict):
            continue
        if not pkg_path.startswith("node_modules/"):
            continue
        name = pkg_path.split("node_modules/")[-1]
        version = str(data.get("version", ""))
        if not name:
            continue
        deps.append(normalize_dependency("npm", name, version))

    return deps


def query_osv(ecosystem: str, name: str, version: str = "") -> List[Dict[str, Any]]:
    normalized = normalize_dependency(ecosystem, name, version)
    cache_key = f"osv:{normalized['ecosystem']}:{normalized['name']}:{normalized['version']}"
    cached = get_cache(cache_key, ttl_seconds=3600)
    if cached is not None:
        return list(cached)

    payload: Dict[str, Any] = {
        "package": {
            "name": normalized["name"],
            "ecosystem": normalized["ecosystem"],
        }
    }
    if normalized["version"]:
        payload["version"] = normalized["version"]

    resp = request_with_retry("POST", OSV_QUERY_URL, json_payload=payload, timeout=20)
    if resp.status_code >= 400:
        return []
    vulns = resp.json().get("vulns", []) or []
    results: List[Dict[str, Any]] = []
    for vuln in vulns:
        vector = _extract_cvss_vector(vuln)
        results.append(
            {
                "id": vuln.get("id", "unknown"),
                "summary": vuln.get("summary", "No summary"),
                "severity": _pick_severity(vuln),
                "cvss_vector": vector,
            }
        )
    set_cache(cache_key, results)
    return results


def _pick_severity(vuln: Dict[str, Any]) -> str:
    severities = vuln.get("severity", []) or []
    if not severities:
        return "unknown"
    score = severities[0].get("score", "")
    if not score:
        return "unknown"
    if "CVSS" in score:
        return score
    return str(score)


def _clean_version(version: str) -> str:
    raw = str(version or "").strip()
    if not raw:
        return ""
    raw = raw.strip('"\'')
    raw = re.sub(r"^[\^~><=! ]+", "", raw)
    if "," in raw:
        raw = raw.split(",", 1)[0].strip()
    return raw


def _parse_python_dep_str(dep_text: str) -> Dict[str, str] | None:
    match = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?\s*([<>=!~]{1,2})?\s*([A-Za-z0-9_.\-]+)?", dep_text)
    if not match:
        return None
    name, op, version = match.group(1), match.group(2), match.group(3)
    return {
        "name": name,
        "version": version if op in {"==", "==="} and version else "",
    }


def _extract_cvss_vector(vuln: Dict[str, Any]) -> str:
    severities = vuln.get("severity", []) or []
    for entry in severities:
        score = str(entry.get("score", ""))
        if "AV:" in score:
            return score

    db_cvss = vuln.get("database_specific", {}).get("cvss", {})
    if isinstance(db_cvss, dict):
        vector = str(db_cvss.get("vectorString", "") or db_cvss.get("vector", "")).strip()
        if vector:
            return vector

    return ""
