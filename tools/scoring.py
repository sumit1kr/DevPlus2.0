from __future__ import annotations

from typing import Dict


SCORE_WEIGHTS: Dict[str, float] = {
    "code_quality": 0.30,
    "dependency": 0.30,
    "git_history": 0.20,
    "security": 0.20,
}


def compute_weighted_base(scores: Dict[str, int | float]) -> int:
    code = float(scores.get("code_quality", 0))
    dep = float(scores.get("dependency", 0))
    git = float(scores.get("git_history", 0))
    sec = float(scores.get("security", 0))

    weighted = (
        code * SCORE_WEIGHTS["code_quality"]
        + dep * SCORE_WEIGHTS["dependency"]
        + git * SCORE_WEIGHTS["git_history"]
        + sec * SCORE_WEIGHTS["security"]
    )
    return int(round(weighted))