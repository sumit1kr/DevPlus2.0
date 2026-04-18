from __future__ import annotations

import base64
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from tools.cache_store import get_cache, set_cache
from tools.http_utils import request_with_retry


GITHUB_API = "https://api.github.com"
SKIP_PREFIXES = (
    "node_modules/",
    ".git/",
    "dist/",
    "build/",
    ".venv/",
    "venv/",
    "__pycache__/",
)


def _headers() -> Dict[str, str]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_github_url(repo_url: str) -> Tuple[str, str]:
    parsed = urlparse(repo_url)
    if parsed.netloc not in {"github.com", "www.github.com"}:
        raise ValueError("Only github.com URLs are supported")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repository URL")

    owner, repo = parts[0], parts[1]
    repo = re.sub(r"\.git$", "", repo)
    return owner, repo


def parse_github_pr_url(pr_url: str) -> Tuple[str, str, int]:
    parsed = urlparse(pr_url)
    if parsed.netloc not in {"github.com", "www.github.com"}:
        raise ValueError("Only github.com URLs are supported")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 4 or parts[2] != "pull":
        raise ValueError("Invalid GitHub pull request URL")

    owner, repo = parts[0], re.sub(r"\.git$", "", parts[1])
    try:
        pull_number = int(parts[3])
    except Exception as exc:
        raise ValueError("Invalid pull request number") from exc
    return owner, repo, pull_number


def is_github_pr_url(url: str) -> bool:
    try:
        parse_github_pr_url(url)
        return True
    except Exception:
        return False


def get_repo_default_branch(owner: str, repo: str) -> str:
    cache_key = f"github:default_branch:{owner}:{repo}"
    cached = get_cache(cache_key, ttl_seconds=3600)
    if cached:
        return str(cached)

    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    resp = request_with_retry("GET", url, headers=_headers(), timeout=20)
    resp.raise_for_status()
    branch = resp.json().get("default_branch", "main")
    set_cache(cache_key, branch)
    return branch


def fetch_repo_tree(owner: str, repo: str, branch: str, max_files: int = 300) -> List[Dict[str, Any]]:
    cache_key = f"github:tree:{owner}:{repo}:{branch}:{max_files}"
    cached = get_cache(cache_key, ttl_seconds=900)
    if cached:
        return list(cached)

    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    resp = request_with_retry("GET", url, headers=_headers(), timeout=30)
    resp.raise_for_status()
    tree = resp.json().get("tree", [])

    files: List[Dict[str, Any]] = []
    for node in tree:
        if node.get("type") != "blob":
            continue
        path = node.get("path", "")
        if not path or path.startswith(SKIP_PREFIXES):
            continue
        if any(path.startswith(prefix) for prefix in SKIP_PREFIXES):
            continue
        files.append({"path": path, "size": node.get("size", 0), "sha": node.get("sha")})

    files.sort(key=lambda x: x.get("size", 0), reverse=True)
    limited = files[:max_files]
    set_cache(cache_key, limited)
    return limited


def fetch_file_content(owner: str, repo: str, path: str) -> str:
    cache_key = f"github:file:{owner}:{repo}:{path}"
    cached = get_cache(cache_key, ttl_seconds=900)
    if cached is not None:
        return str(cached)

    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    resp = request_with_retry("GET", url, headers=_headers(), timeout=20)
    if resp.status_code >= 400:
        return ""
    payload = resp.json()
    encoded = payload.get("content", "")
    if not encoded:
        return ""
    try:
        decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
        set_cache(cache_key, decoded)
        return decoded
    except Exception:
        return ""


def fetch_file_content_at_ref(owner: str, repo: str, path: str, ref: str) -> str:
    cache_key = f"github:file:{owner}:{repo}:{ref}:{path}"
    cached = get_cache(cache_key, ttl_seconds=900)
    if cached is not None:
        return str(cached)

    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    resp = request_with_retry("GET", url, headers=_headers(), params={"ref": ref}, timeout=20)
    if resp.status_code >= 400:
        return ""
    payload = resp.json()
    encoded = payload.get("content", "")
    if not encoded:
        return ""
    try:
        decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
        set_cache(cache_key, decoded)
        return decoded
    except Exception:
        return ""


def fetch_key_files(owner: str, repo: str, files_index: List[Dict[str, Any]], max_source_files: int = 30) -> Dict[str, str]:
    dependency_names = {
        "requirements.txt",
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "poetry.lock",
        "pipfile",
        "pipfile.lock",
    }

    dependency_paths: List[str] = []
    source_items: List[Tuple[int, str]] = []
    doc_paths: List[str] = []

    for item in files_index:
        path = str(item.get("path", ""))
        if not path:
            continue
        lowered = path.lower()
        size = int(item.get("size", 0) or 0)

        is_dependency = lowered in dependency_names
        is_source = lowered.endswith((".py", ".js", ".ts", ".tsx", ".jsx"))
        is_doc = lowered in {"readme.md", "readme.rst", "readme.txt"} or lowered.endswith("/readme.md")

        if is_dependency:
            dependency_paths.append(path)
        if is_source:
            # Prioritize smaller source files first to reduce latency on first response.
            source_items.append((max(size, 0), path))
        if is_doc:
            doc_paths.append(path)

    source_items.sort(key=lambda x: (x[0], x[1]))
    selected_sources = [path for _, path in source_items[: max(0, int(max_source_files))]]
    selected_docs = doc_paths[:2]

    selected_paths: List[str] = []
    seen = set()
    for path in dependency_paths + selected_docs + selected_sources:
        if path in seen:
            continue
        selected_paths.append(path)
        seen.add(path)

    if not selected_paths:
        return {}

    max_workers = min(8, max(1, len(selected_paths)))
    resolved: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_file_content, owner, repo, path): path for path in selected_paths}
        for future in as_completed(futures):
            path = futures[future]
            try:
                content = future.result()
            except Exception:
                content = ""
            if content:
                resolved[path] = content

    # Preserve deterministic order for downstream display/reporting.
    file_map: Dict[str, str] = {}
    for path in selected_paths:
        if path in resolved:
            file_map[path] = resolved[path]

    return file_map


def fetch_recent_commits(owner: str, repo: str, branch: str, limit: int = 30) -> List[Dict[str, Any]]:
    cache_key = f"github:commits:{owner}:{repo}:{branch}:{limit}"
    cached = get_cache(cache_key, ttl_seconds=300)
    if cached:
        return list(cached)

    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    params = {"sha": branch, "per_page": min(max(limit, 1), 100)}
    resp = request_with_retry("GET", url, headers=_headers(), params=params, timeout=20)
    resp.raise_for_status()
    commits = []
    for item in resp.json():
        commit = item.get("commit", {})
        author = commit.get("author", {})
        commits.append(
            {
                "sha": item.get("sha", "")[:8],
                "message": commit.get("message", "").split("\n")[0],
                "author": author.get("name", "unknown"),
                "date": author.get("date", ""),
            }
        )
    set_cache(cache_key, commits)
    return commits


def fetch_pull_request_details(owner: str, repo: str, pull_number: int) -> Dict[str, Any]:
    cache_key = f"github:pr:details:{owner}:{repo}:{pull_number}"
    cached = get_cache(cache_key, ttl_seconds=300)
    if cached:
        return dict(cached)

    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}"
    resp = request_with_retry("GET", url, headers=_headers(), timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    details = {
        "number": payload.get("number"),
        "title": payload.get("title", ""),
        "base_ref": payload.get("base", {}).get("ref", ""),
        "base_sha": payload.get("base", {}).get("sha", ""),
        "head_ref": payload.get("head", {}).get("ref", ""),
        "head_sha": payload.get("head", {}).get("sha", ""),
    }
    set_cache(cache_key, details)
    return details


def fetch_pull_request_files(owner: str, repo: str, pull_number: int) -> List[Dict[str, Any]]:
    cache_key = f"github:pr:files:{owner}:{repo}:{pull_number}"
    cached = get_cache(cache_key, ttl_seconds=180)
    if cached:
        return list(cached)

    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/files"
    resp = request_with_retry("GET", url, headers=_headers(), params={"per_page": 100}, timeout=20)
    resp.raise_for_status()
    files: List[Dict[str, Any]] = []
    for item in resp.json():
        files.append(
            {
                "path": item.get("filename", ""),
                "status": item.get("status", "modified"),
                "additions": item.get("additions", 0),
                "deletions": item.get("deletions", 0),
                "changes": item.get("changes", 0),
                "patch": item.get("patch", ""),
            }
        )
    set_cache(cache_key, files)
    return files
