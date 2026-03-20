from __future__ import annotations

import agents.fetcher_agent as fetcher
import agents.report_writer_agent as report_writer
from graph.devpulse_graph import build_graph
from state.state import default_state


def run_ci_smoke() -> None:
    fetcher.parse_github_url = lambda _url: ("owner", "repo")
    fetcher.get_repo_default_branch = lambda *_: "main"
    fetcher.fetch_repo_tree = lambda *_args, **_kwargs: [
        {"path": "app/main.py", "size": 10, "sha": "1"},
        {"path": "requirements.txt", "size": 10, "sha": "2"},
        {"path": "tests/test_main.py", "size": 10, "sha": "3"},
    ]
    fetcher.fetch_key_files = lambda *_args, **_kwargs: {
        "app/main.py": "def hello():\n    return 'ok'\n",
        "requirements.txt": "requests==2.31.0",
    }
    fetcher.fetch_recent_commits = lambda *_args, **_kwargs: []

    report_writer.LLMRouter.available = lambda _self: False

    graph, _ = build_graph()
    result = graph.invoke(default_state("https://github.com/owner/repo", scan_depth=20))

    assert "final_report" in result
    assert "score_breakdown" in result
    assert "aggregated_result" in result
    print("ci smoke passed")


if __name__ == "__main__":
    run_ci_smoke()
