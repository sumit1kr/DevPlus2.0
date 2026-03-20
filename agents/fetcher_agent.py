from __future__ import annotations

import time
from typing import Dict

from state.state import DevPulseState
from tools.github_tools import (
    fetch_file_content_at_ref,
    fetch_key_files,
    fetch_pull_request_details,
    fetch_pull_request_files,
    fetch_recent_commits,
    fetch_repo_tree,
    get_repo_default_branch,
    is_github_pr_url,
    parse_github_pr_url,
    parse_github_url,
)
from tools.trace_logger import TraceLogger


def run_fetcher(state: DevPulseState) -> DevPulseState:
    trace = TraceLogger("fetcher_agent", state)

    try:
        url = state["repo_url"]
        trace.add_tool_call("detect_url_mode", {"repo_url": url})
        if is_github_pr_url(url):
            updates = _run_fetcher_pr_mode(state, trace)
            pr_warnings = updates.get("warnings", [])
            real_pr_issues = [
                w for w in pr_warnings
                if not w.startswith("PR partial source scan")
            ]
            status = "degraded" if real_pr_issues else "success"
            trace_entry = trace.finalize(status=status, output=updates)
            return {
                **updates,
                "run_trace": [trace_entry],
            }

        t0 = time.perf_counter()
        trace.add_tool_call("parse_github_url", {"repo_url": url})
        owner, repo = parse_github_url(url)
        t1 = time.perf_counter()
        trace.add_tool_call("get_repo_default_branch", {"owner": owner, "repo": repo})
        branch = get_repo_default_branch(owner, repo)
        t2 = time.perf_counter()
        trace.add_tool_call("fetch_repo_tree", {"owner": owner, "repo": repo, "branch": branch, "max_files": 400})
        files_index = fetch_repo_tree(owner, repo, branch, max_files=400)
        detected_languages = _detect_languages(files_index)
        t3 = time.perf_counter()
        base_depth = int(state.get("scan_depth", 30))
        adaptive_depth = _adaptive_scan_depth(base_depth, files_index)
        trace.add_tool_call("fetch_key_files", {"max_source_files": adaptive_depth})
        fetched_files = fetch_key_files(owner, repo, files_index, max_source_files=adaptive_depth)
        t4 = time.perf_counter()
        trace.add_tool_call("fetch_recent_commits", {"limit": 40})
        commits = fetch_recent_commits(owner, repo, branch, limit=40)
        t5 = time.perf_counter()
        source_candidates = sum(1 for f in files_index if str(f.get("path", "")).lower().endswith((".py", ".js", ".ts", ".tsx", ".jsx")))
        fetched_source = sum(1 for p in fetched_files if p.lower().endswith((".py", ".js", ".ts", ".tsx", ".jsx")))

        dependency_files = {
            p: c
            for p, c in fetched_files.items()
            if p.lower().endswith((
                "requirements.txt",
                "pyproject.toml",
                "poetry.lock",
                "package.json",
                "package-lock.json",
                "pipfile",
                "pipfile.lock",
            ))
            or p.lower() in {"requirements.txt", "package.json", "pipfile", "pipfile.lock"}
        }

        warnings = list(state.get("warnings", []))
        if adaptive_depth < base_depth:
            warnings.append(
                f"Adaptive scan depth applied: requested {base_depth}, used {adaptive_depth} due to repository size."
            )
        if source_candidates > fetched_source:
            warnings.append(
                f"Partial source scan: fetched {fetched_source}/{source_candidates} source files due to scan depth limit."
            )

        updates = {
            "analysis_mode": "repo",
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "detected_languages": detected_languages,
            "files_index": files_index,
            "fetched_files": fetched_files,
            "dependency_files": dependency_files,
            "commit_samples": commits,
            "scan_coverage": {
                "source_candidates": source_candidates,
                "source_fetched": fetched_source,
                "dependency_files_found": len(dependency_files),
                "tree_files_indexed": len(files_index),
                "scan_depth_requested": base_depth,
                "scan_depth_effective": adaptive_depth,
            },
            "runtime_profile": {
                "parse_url_ms": int((t1 - t0) * 1000),
                "default_branch_ms": int((t2 - t1) * 1000),
                "fetch_tree_ms": int((t3 - t2) * 1000),
                "fetch_files_ms": int((t4 - t3) * 1000),
                "fetch_commits_ms": int((t5 - t4) * 1000),
                "total_fetch_ms": int((t5 - t0) * 1000),
            },
            "warnings": warnings,
        }
        # Only mark degraded for real errors, not informational scan coverage warnings
        real_issues = [
            w for w in warnings
            if not w.startswith("Partial source scan")
            and not w.startswith("Adaptive scan depth")
        ]
        status = "degraded" if real_issues else "success"
        trace_entry = trace.finalize(status=status, output=updates)
        return {
            **updates,
            "run_trace": [trace_entry],
        }
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"fetcher_error: {exc}")
        trace_entry = trace.finalize(status="failed", output={"errors": errors})
        return {
            "errors": errors,
            "run_trace": [trace_entry],
        }


def _run_fetcher_pr_mode(state: DevPulseState, trace: TraceLogger) -> DevPulseState:
    t0 = time.perf_counter()
    trace.add_tool_call("parse_github_pr_url", {"repo_url": state["repo_url"]})
    owner, repo, pull_number = parse_github_pr_url(state["repo_url"])
    t1 = time.perf_counter()

    trace.add_tool_call("fetch_pull_request_details", {"owner": owner, "repo": repo, "pull_number": pull_number})
    details = fetch_pull_request_details(owner, repo, pull_number)
    t2 = time.perf_counter()
    trace.add_tool_call("fetch_pull_request_files", {"owner": owner, "repo": repo, "pull_number": pull_number})
    changed_files = fetch_pull_request_files(owner, repo, pull_number)
    t3 = time.perf_counter()

    base_sha = details.get("base_sha", "")
    head_sha = details.get("head_sha", "")

    files_index = [{"path": f.get("path", ""), "size": 0, "sha": "", "status": f.get("status", "modified")} for f in changed_files if f.get("path")]
    detected_languages = _detect_languages(files_index)
    source_suffixes = (".py", ".js", ".ts", ".tsx", ".jsx")
    dep_suffixes = ("requirements.txt", "pyproject.toml", "poetry.lock", "package.json", "package-lock.json")

    fetched_files: dict[str, str] = {}
    head_dep_files: dict[str, str] = {}
    base_dep_files: dict[str, str] = {}

    for item in changed_files:
        path = str(item.get("path", ""))
        if not path:
            continue
        lowered = path.lower()
        is_source = lowered.endswith(source_suffixes)
        is_dep = lowered.endswith(dep_suffixes)
        is_doc = lowered.endswith(("readme.md", "readme.rst", "readme.txt"))

        if not (is_source or is_dep or is_doc):
            continue

        status = str(item.get("status", "modified"))
        if status != "removed" and head_sha:
            trace.add_tool_call("fetch_file_content_at_ref", {"path": path, "ref": head_sha})
            head_content = fetch_file_content_at_ref(owner, repo, path, head_sha)
            if head_content:
                fetched_files[path] = head_content
                if is_dep:
                    head_dep_files[path] = head_content

        if is_dep and base_sha:
            trace.add_tool_call("fetch_file_content_at_ref", {"path": path, "ref": base_sha})
            base_content = fetch_file_content_at_ref(owner, repo, path, base_sha)
            if base_content:
                base_dep_files[path] = base_content

    t4 = time.perf_counter()

    source_changed = sum(1 for f in changed_files if str(f.get("path", "")).lower().endswith(source_suffixes))
    source_fetched = sum(1 for p in fetched_files if p.lower().endswith(source_suffixes))
    warnings = list(state.get("warnings", []))
    if source_changed > source_fetched:
        warnings.append(f"PR partial source scan: fetched {source_fetched}/{source_changed} changed source files.")

    return {
        "analysis_mode": "pr",
        "owner": owner,
        "repo": repo,
        "branch": details.get("head_ref", ""),
        "pr_number": pull_number,
        "detected_languages": detected_languages,
        "files_index": files_index,
        "pr_changed_files": changed_files,
        "fetched_files": fetched_files,
        "dependency_files": head_dep_files,
        "pr_head_dependency_files": head_dep_files,
        "pr_base_dependency_files": base_dep_files,
        "commit_samples": [],
        "scan_coverage": {
            "source_candidates": source_changed,
            "source_fetched": source_fetched,
            "dependency_files_found": len(head_dep_files),
            "tree_files_indexed": len(changed_files),
            "scan_depth_requested": state.get("scan_depth", 30),
            "scan_depth_effective": len([p for p in fetched_files if p.lower().endswith(source_suffixes)]),
            "mode": "pr",
        },
        "runtime_profile": {
            "parse_url_ms": int((t1 - t0) * 1000),
            "fetch_pr_details_ms": int((t2 - t1) * 1000),
            "fetch_pr_files_ms": int((t3 - t2) * 1000),
            "fetch_changed_content_ms": int((t4 - t3) * 1000),
            "total_fetch_ms": int((t4 - t0) * 1000),
        },
        "warnings": warnings,
    }


def _adaptive_scan_depth(base_depth: int, files_index: list[dict]) -> int:
    tree_count = len(files_index)
    source_count = sum(
        1 for f in files_index if str(f.get("path", "")).lower().endswith((".py", ".js", ".ts", ".tsx", ".jsx"))
    )

    depth = max(10, base_depth)
    if tree_count > 2000 or source_count > 700:
        depth = min(depth, 20)
    elif tree_count > 1200 or source_count > 350:
        depth = min(depth, 30)
    elif tree_count > 700 or source_count > 180:
        depth = min(depth, 45)

    return depth


def _detect_languages(files_index: list[dict]) -> Dict[str, int]:
    mapping = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".jsx": "JavaScript",
        ".java": "Java",
        ".go": "Go",
        ".rs": "Rust",
        ".rb": "Ruby",
        ".php": "PHP",
        ".cpp": "C++",
        ".c": "C",
        ".cs": "C#",
        ".swift": "Swift",
        ".kt": "Kotlin",
        ".tex": "TeX",
        ".bib": "BibTeX",
        ".sh": "Shell",
        ".bash": "Shell",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".html": "HTML",
        ".css": "CSS",
        ".sql": "SQL",
        ".r": "R",
        ".scala": "Scala",
    }

    counts: Dict[str, int] = {}
    total = 0
    for item in files_index:
        path = str(item.get("path", ""))
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        lang = mapping.get(ext)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
            total += 1

    if total == 0:
        return {}

    filtered = [
        (lang, count)
        for lang, count in counts.items()
        if (count / total) >= 0.01
    ]
    filtered.sort(key=lambda x: x[1], reverse=True)
    return {lang: count for lang, count in filtered}
