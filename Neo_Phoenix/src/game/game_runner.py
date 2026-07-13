from __future__ import annotations

from dataclasses import dataclass, field

from src.game.game_text_reader import GameTextReader, HalfInningBlock
from src.runner.half_inning_runner import HalfInningRunner
from src.runner.virtual_half_inning_runner import VirtualHalfInningRunner
from src.compare.actual_virtual_comparator import ActualVirtualComparator
from src.review.review_engine import ReviewEngine
from src.report.text_reporter import TextReporter


@dataclass
class HalfInningAnalysis:
    title: str
    actual_report: object
    virtual_report: object
    pitcher_virtual_report: object
    compare_result: object
    review_result: object
    text_report: str


@dataclass
class GameAnalysis:
    path: str
    halves: list[HalfInningAnalysis] = field(default_factory=list)

    @property
    def total_scores(self) -> int:
        return sum(h.actual_report.total_scores for h in self.halves)

    @property
    def review_items(self) -> int:
        return sum(len(h.review_result.items) for h in self.halves)


class GameRunner:
    """
    Phoenix Beta1.1

    game.txtを読み、半イニングごとにActual/Virtual/Comparator/Review/Reportを実行する。
    """

    def __init__(self):
        self.reader = GameTextReader()
        self.comparator = ActualVirtualComparator()
        self.reviewer = ReviewEngine()
        self.reporter = TextReporter()

    def run_file(self, path: str, pitcher: str = "P") -> GameAnalysis:
        game_text = self.reader.read(path)
        analysis = GameAnalysis(path=game_text.path)

        # V3.0 Sprint04 RC025 fix:
        # HalfInningRunner は半イニングごとに新規作成されるため、
        # 「先発は」がない2回以降の半イニングでは従来 fallback の P に戻っていた。
        # 表=後攻側守備、裏=先攻側守備として、同じ守備側の現在投手を次回へ引き継ぐ。
        pitcher_by_half = {"表": pitcher, "裏": pitcher}

        for block in game_text.half_innings:
            side = self._half_side(block.title)
            half_pitcher = pitcher_by_half.get(side, pitcher)
            half_analysis = self._run_half(block, pitcher=half_pitcher)
            analysis.halves.append(half_analysis)
            if side:
                current = getattr(half_analysis.actual_report, "current_pitcher", "") or half_pitcher
                pitcher_by_half[side] = current

        return analysis

    def _half_side(self, title: str) -> str:
        text = str(title or "")
        if "表" in text:
            return "表"
        if "裏" in text:
            return "裏"
        return ""

    def _run_half(self, block: HalfInningBlock, pitcher: str) -> HalfInningAnalysis:
        actual = HalfInningRunner(f"Actual {block.title}")
        actual_report = actual.run(block.lines, pitcher=pitcher)

        virtual = VirtualHalfInningRunner(f"Virtual {block.title}")
        virtual_report = virtual.run(block.lines, pitcher=pitcher)

        # RC037 / Quality17:
        # 投手別自責点は、投手交代時点でActualのアウト・塁上走者を
        # 救援投手のPitcher Virtual開始状態にする必要があるため、
        # Team Virtualとは別にPitcher Virtual専用ランナーを走らせる。
        pitcher_virtual = VirtualHalfInningRunner(f"Pitcher Virtual {block.title}", pitcher_split_mode=True)
        pitcher_virtual_report = pitcher_virtual.run(block.lines, pitcher=pitcher)

        compare_result = self.comparator.compare(actual_report, virtual_report, pitcher_virtual_report=pitcher_virtual_report)
        review_result = self.reviewer.review(actual_report, virtual_report, compare_result)
        text_report = self.reporter.build(actual_report, virtual_report, compare_result, review_result)

        return HalfInningAnalysis(
            title=block.title,
            actual_report=actual_report,
            virtual_report=virtual_report,
            pitcher_virtual_report=pitcher_virtual_report,
            compare_result=compare_result,
            review_result=review_result,
            text_report=text_report,
        )
