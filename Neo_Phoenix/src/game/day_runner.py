from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.game.game_runner import GameRunner


@dataclass
class GameDayResult:
    game_no: int
    game_name: str
    path: str
    analysis: object


@dataclass
class DayAnalysis:
    games: list[GameDayResult] = field(default_factory=list)

    @property
    def total_games(self) -> int:
        return len(self.games)

    @property
    def total_scores(self) -> int:
        return sum(g.analysis.total_scores for g in self.games)

    @property
    def total_reviews(self) -> int:
        return sum(g.analysis.review_items for g in self.games)

    @property
    def total_work_items(self) -> int:
        total = 0
        for g in self.games:
            for half in g.analysis.halves:
                for j in half.compare_result.judgments:
                    if j.judgment in {"非自責点", "自責点候補"}:
                        total += 1
                for item in half.review_result.items:
                    if item.level in {"WARN", "ERROR"}:
                        total += 1
        return total


class DayRunner:
    """
    Phoenix V2.1 StableCore

    gamesフォルダ内のtxtを最大3試合まで一括解析する。
    """

    def __init__(self):
        self.runner = GameRunner()

    def run_folder(self, folder: str | Path, pitcher: str = "向井", limit: int = 3) -> DayAnalysis:
        folder = Path(folder)
        files = sorted(folder.glob("*.txt"))[:limit]

        day = DayAnalysis()
        for idx, path in enumerate(files, 1):
            analysis = self.runner.run_file(str(path), pitcher=pitcher)
            day.games.append(GameDayResult(
                game_no=idx,
                game_name=path.stem,
                path=str(path),
                analysis=analysis,
            ))

        return day
