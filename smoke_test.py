from __future__ import annotations

import os
from pprint import pprint

from dotenv import load_dotenv

from graph.devpulse_graph import build_graph
from state.state import default_state


TEST_REPOS = [
    "https://github.com/pallets/flask",
    "https://github.com/psf/requests",
    "https://github.com/tiangolo/fastapi",
]


def run_one(repo_url: str) -> None:
    graph, _ = build_graph()
    init_state = default_state(repo_url=repo_url, scan_depth=20)
    result = graph.invoke(init_state)

    print("=" * 80)
    print(repo_url)
    print("overall score:", result.get("score_breakdown", {}).get("overall"))
    print("warnings:")
    for w in result.get("warnings", []):
        print(" -", w)
    print("coverage:")
    pprint(result.get("scan_coverage", {}))
    print("errors:")
    for err in result.get("errors", []):
        print(" -", err)


if __name__ == "__main__":
    load_dotenv()

    if not os.getenv("GITHUB_TOKEN"):
        print("warning: GITHUB_TOKEN not set, you may hit low GitHub rate limits")

    for url in TEST_REPOS:
        run_one(url)
