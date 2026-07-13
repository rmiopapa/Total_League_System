from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunDetailRow:
    """1得点ごとの責任明細。

    Phoenix V3.0では RunDetail を Single Source of Truth とし、
    Team / Pitcher summary はこの明細を集計して作る。
    """

    game_no: str
    game: str
    inning: str
    run_no: int | str
    scored_runner_id: str
    scored_runner: str
    charged_pitcher: str
    run_charged: int
    earned_run: int
    judgment: str
    reason: str
    virtual_source: str = "Team Virtual"
