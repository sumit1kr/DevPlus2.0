import agents.fetcher_agent as fetcher
import agents.report_writer_agent as report_writer
from graph.devpulse_graph import build_graph
from state.state import default_state


def test_graph_invoke_with_mocked_fetch(monkeypatch):
    monkeypatch.setattr(fetcher, "parse_github_url", lambda _: ("owner", "repo"))
    monkeypatch.setattr(fetcher, "get_repo_default_branch", lambda *_: "main")
    monkeypatch.setattr(
        fetcher,
        "fetch_repo_tree",
        lambda *_args, **_kwargs: [
            {"path": "app/main.py", "size": 10, "sha": "1"},
            {"path": "requirements.txt", "size": 10, "sha": "2"},
        ],
    )
    monkeypatch.setattr(
        fetcher,
        "fetch_key_files",
        lambda *_args, **_kwargs: {
            "app/main.py": "def x():\n    return 1\n",
            "requirements.txt": "requests==2.31.0",
        },
    )
    monkeypatch.setattr(fetcher, "fetch_recent_commits", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(report_writer.LLMRouter, "available", lambda _self: False)

    graph, _ = build_graph()
    result = graph.invoke(default_state("https://github.com/owner/repo", scan_depth=5))

    assert "score_breakdown" in result
    assert "final_report" in result
    assert isinstance(result.get("warnings", []), list)
