from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.event.score_event_builder import ScoreEventBuilder
from src.game.day_runner import DayAnalysis, GameDayResult
from src.game.game_runner import GameAnalysis, GameRunner
from src.game.game_text_reader import GameTextReader
from src.neo.engine import NeoHalfInningEngine
from src.neo.judgment import NeoScoreJudgmentBuilder
from src.review.review_engine import ReviewEngine
from src.report.text_reporter import TextReporter
from src.runner.half_inning_runner import HalfInningReport, PlayReport


class NeoGameRunner:
    """GameRunner-compatible facade that uses Neo judgments.

    The existing GUI and reports already understand GameAnalysis.  This runner
    keeps those integration points and replaces the earned-run judgment layer
    with Neo Team/Pitcher results.
    """

    def __init__(self):
        self.base_runner = GameRunner()
        self.reader = GameTextReader()
        self.judgment_builder = NeoScoreJudgmentBuilder()
        self.reviewer = ReviewEngine()
        self.reporter = TextReporter()
        self.score_builder = ScoreEventBuilder()

    def run_file(self, path: str, pitcher: str = "P") -> GameAnalysis:
        analysis = self.base_runner.run_file(path, pitcher=pitcher)
        blocks = self.reader.read(path).half_innings

        for half, block in zip(analysis.halves, blocks):
            team_neo = NeoHalfInningEngine(f"Neo Team {block.title}").run(block.lines)
            pitcher_neo = NeoHalfInningEngine(
                f"Neo Pitcher {block.title}",
                pitcher_split_mode=True,
            ).run(block.lines)

            team_compare = self.judgment_builder.build(team_neo)
            pitcher_compare = self.judgment_builder.build(pitcher_neo)

            team_judgments = self._with_actual_runner_text(
                team_compare.judgments,
                half.actual_report,
            )
            pitcher_judgments = self._with_actual_runner_text(
                pitcher_compare.judgments,
                half.actual_report,
            )
            adopted_judgments = self._adopt_pitcher_judgments(
                team_judgments,
                pitcher_judgments,
                half.actual_report,
            )

            team_compare.judgments = adopted_judgments
            team_compare.team_judgments = team_judgments
            team_compare.pitcher_judgments = adopted_judgments
            team_compare.adopted_source = "Neo Team/Pitcher Virtual"
            team_compare.virtual_source = "Neo Virtual"

            half.virtual_report = self._neo_report_from_result(
                title=block.title,
                result=team_neo,
                runner_history=getattr(half.actual_report, "runner_history", []),
                pitcher_changes=getattr(half.actual_report, "pitcher_changes", []),
            )
            half.pitcher_virtual_report = self._neo_report_from_result(
                title=block.title,
                result=pitcher_neo,
                runner_history=getattr(half.actual_report, "runner_history", []),
                pitcher_changes=getattr(half.actual_report, "pitcher_changes", []),
                include_pitcher_runtime=True,
            )
            half.compare_result = team_compare
            half.review_result = self.reviewer.review(
                half.actual_report,
                half.virtual_report,
                team_compare,
            )
            half.text_report = self.reporter.build(
                half.actual_report,
                half.virtual_report,
                team_compare,
                half.review_result,
            )

        return analysis

    def _neo_report_from_result(
        self,
        title: str,
        result,
        runner_history,
        pitcher_changes,
        include_pitcher_runtime: bool = False,
    ) -> HalfInningReport:
        report = HalfInningReport(title=title)
        for snap in getattr(result, "plays", []) or []:
            play = PlayReport(
                seq=int(getattr(snap, "seq", 0) or 0),
                raw_text=str(getattr(snap, "raw_text", "") or ""),
                before_text=str(getattr(snap, "virtual_before", "") or ""),
                after_text=str(getattr(snap, "virtual_after", "") or ""),
                outs_before=int(getattr(snap, "virtual_outs_before", 0) or 0),
                outs_after=int(getattr(snap, "virtual_outs_after", 0) or 0),
                moves_text=[
                    self._move_text(mv)
                    for mv in getattr(snap, "virtual_moves", []) or []
                ],
                scored_text=[
                    self._scored_fact_text(fact)
                    for fact in getattr(snap, "virtual_scored_runner_facts", []) or []
                ],
                warnings=list(getattr(snap, "warnings", []) or []),
            )
            play.notes = ["Neo Virtual"]
            report.plays.append(play)
        report.total_scores = int(getattr(result, "total_virtual_scores", 0) or 0)
        report.total_outs = int(getattr(result, "virtual_outs", 0) or 0)
        report.warnings = list(getattr(result, "warnings", []) or [])
        report.runner_history = list(runner_history or [])
        report.pitcher_changes = list(pitcher_changes or [])
        if include_pitcher_runtime:
            report.pitcher_runtime_debug = self._pitcher_runtime_rows(result)
        return report

    def _move_text(self, mv) -> str:
        return (
            f"{getattr(mv, 'source', '')}->{getattr(mv, 'target', '')}"
            f" / {getattr(mv, 'reason', '')}"
            f" / {getattr(mv, 'cause_type', '')}"
        )

    def _scored_fact_text(self, fact: dict[str, object]) -> str:
        runner_id = str(fact.get("id", "") or "")
        name = str(fact.get("name", "") or "")
        reached = str(fact.get("reached_cause_type", "") or "")
        score_cause = str(fact.get("score_cause_type", "") or "")
        score_reason = str(fact.get("score_reason", "") or "")
        return f"{runner_id}:{name} / reached={reached} / score_cause={score_cause} / score_reason={score_reason}"

    def _pitcher_runtime_rows(self, result) -> list[str]:
        rows: list[str] = []
        for snap in getattr(result, "plays", []) or []:
            seq = int(getattr(snap, "seq", 0) or 0)
            current = str(getattr(snap, "current_pitcher", "") or "")
            current_state = str(getattr(snap, "virtual_after", "") or "")
            outs = int(getattr(snap, "virtual_outs_after", 0) or 0)
            all_virtuals = "|".join(
                f"{name}={state}"
                for name, state in (getattr(snap, "pitcher_virtuals_after", {}) or {}).items()
            )
            rows.append(
                f"{seq},{self._short_event(str(getattr(snap, 'raw_text', '') or ''))},"
                f"{current},{current_state},{outs},0,0,{all_virtuals},Neo Pitcher Virtual"
            )
        return rows

    def _short_event(self, line: str) -> str:
        text = str(line or "")
        for token in ["投手交代", "四球", "死球", "三振", "失策", "安打", "犠飛", "ゴロ", "飛"]:
            if token in text:
                return token
        return text[:16]

    def _with_actual_runner_text(self, judgments, actual_report):
        actual_scored = self._actual_scored_texts(actual_report)
        out = []
        for idx, judgment in enumerate(judgments):
            runner_text = str(getattr(judgment, "runner_text", "") or "")
            if idx < len(actual_scored):
                actual_text = actual_scored[idx]
                actual_id = self.score_builder.runner_id(actual_text)
                if actual_id and actual_id == self.score_builder.runner_id(runner_text):
                    runner_text = actual_text
            out.append(replace(judgment, runner_text=runner_text))
        return out

    def _actual_scored_texts(self, actual_report) -> list[str]:
        scored: list[str] = []
        for play in getattr(actual_report, "plays", []) or []:
            scored.extend(str(row) for row in getattr(play, "scored_text", []) or [])
        return scored

    def _adopt_pitcher_judgments(self, team_judgments, pitcher_judgments, actual_report):
        runner_pitcher = self._runner_pitcher_map(actual_report)
        entered_pitchers = self._entered_pitchers(actual_report)
        inherited_replacement_ids = self._inherited_replacement_runner_ids(actual_report)

        adopted = []
        for idx, team_judgment in enumerate(team_judgments):
            pitcher_judgment = pitcher_judgments[idx] if idx < len(pitcher_judgments) else team_judgment
            runner_id = self.score_builder.runner_id(str(getattr(team_judgment, "runner_text", "")))
            charged = runner_pitcher.get(runner_id, "")
            if charged in entered_pitchers:
                adopted.append(pitcher_judgment)
            elif runner_id in inherited_replacement_ids:
                adopted.append(team_judgment)
            else:
                adopted.append(pitcher_judgment)
        return adopted

    def _runner_pitcher_map(self, actual_report) -> dict[str, str]:
        half = type("Half", (), {"actual_report": actual_report})()
        return self.score_builder.runner_pitcher_map(half)

    def _entered_pitchers(self, actual_report) -> set[str]:
        entered: set[str] = set()
        half = type("Half", (), {"actual_report": actual_report})()
        mapping = self.score_builder.pitcher_display_map(half)
        for row in getattr(actual_report, "pitcher_changes", []) or []:
            parts = str(row).split(",", 3)
            if len(parts) >= 3:
                pitcher = self.score_builder.display_pitcher(parts[2].strip(), mapping)
                if pitcher:
                    entered.add(pitcher)
        return entered

    def _inherited_replacement_runner_ids(self, actual_report) -> set[str]:
        runner_ids: set[str] = set()
        for row in getattr(actual_report, "runner_history", []) or []:
            parts = str(row).split(",", 7)
            if len(parts) == 8 and "得点責任継承" in parts[7]:
                runner_ids.add(parts[0].strip())
        return runner_ids


class NeoDayRunner:
    """DayRunner-compatible facade for the review window."""

    def __init__(self):
        self.runner = NeoGameRunner()

    def run_folder(self, folder: str | Path, pitcher: str = "P", limit: int = 3) -> DayAnalysis:
        folder = Path(folder)
        files = sorted(folder.glob("*.txt"))[:limit]

        day = DayAnalysis()
        for idx, path in enumerate(files, 1):
            analysis = self.runner.run_file(str(path), pitcher=pitcher)
            day.games.append(
                GameDayResult(
                    game_no=idx,
                    game_name=path.stem,
                    path=str(path),
                    analysis=analysis,
                )
            )
        return day
