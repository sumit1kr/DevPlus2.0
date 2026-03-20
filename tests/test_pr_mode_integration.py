import agents.fetcher_agent as fetcher
import agents.report_writer_agent as report_writer
from graph.devpulse_graph import build_graph
from state.state import default_state


def test_pr_mode_flow(monkeypatch):
    monkeypatch.setattr(fetcher, "is_github_pr_url", lambda _url: True)
    monkeypatch.setattr(fetcher, "parse_github_pr_url", lambda _url: ("owner", "repo", 12))
    monkeypatch.setattr(
        fetcher,
        "fetch_pull_request_details",
        lambda *_args, **_kwargs: {
            "number": 12,
            "title": "Update parser",
            "base_ref": "main",
            "base_sha": "base123",
            "head_ref": "feature-x",
            "head_sha": "head123",
        },
    )
    monkeypatch.setattr(
        fetcher,
        "fetch_pull_request_files",
        lambda *_args, **_kwargs: [
            {"path": "src/app.py", "status": "modified", "additions": 20, "deletions": 4, "changes": 24, "patch": "@@"},
            {"path": "requirements.txt", "status": "modified", "additions": 1, "deletions": 0, "changes": 1, "patch": "@@"},
        ],
    )
    monkeypatch.setattr(
        fetcher,
        "fetch_file_content_at_ref",
        lambda _owner, _repo, path, ref: "requests==2.31.0" if path.endswith("requirements.txt") else "def run():\n    return 1\n",
    )
    monkeypatch.setattr(report_writer.LLMRouter, "available", lambda _self: False)

    graph, _ = build_graph()
    result = graph.invoke(default_state("https://github.com/owner/repo/pull/12", scan_depth=20))

    assert result.get("analysis_mode") == "pr"
    assert result.get("pr_number") == 12
    assert isinstance(result.get("pr_changed_files", []), list)
    assert "pr_risk_summary" in result
    assert "pr_review_checklist" in result
