from __future__ import annotations

from src.compare.actual_virtual_comparator import CompareResult, ScoreJudgment
from src.neo.models import NeoHalfInningResult


class NeoScoreJudgmentBuilder:
    """Build earned-run judgments directly from Neo runner-id timelines.

    Japanese scoring judges earned runs when the actual runner scores. Neo keeps
    that rule simple: the actual run is earned only if the same runner id has
    also scored in the virtual inning by that scoring point.
    """

    UNEARNED_CAUSES = {"field_error", "passed_ball", "interference"}

    def build(self, result: NeoHalfInningResult) -> CompareResult:
        compare = CompareResult(
            actual_scores=result.total_actual_scores,
            virtual_scores=result.total_virtual_scores,
            actual_outs=result.actual_outs,
            virtual_outs=result.virtual_outs,
            virtual_source="Neo Virtual",
        )

        virtual_scored_by_time: set[str] = set()
        score_no = 0

        for snap in result.plays:
            virtual_scored_by_time.update(
                rid
                for rid in getattr(snap, "virtual_scored_runner_ids", []) or []
                if rid
            )
            facts_by_id = {
                str(fact.get("id", "")): fact
                for fact in getattr(snap, "actual_scored_runner_facts", []) or []
            }
            for runner_id in getattr(snap, "actual_scored_runner_ids", []) or []:
                if not runner_id:
                    continue
                score_no += 1
                fact = facts_by_id.get(runner_id, {})
                reached_cause = str(fact.get("reached_cause_type", "") or "")
                score_cause = str(fact.get("score_cause_type", "") or "")
                earned_eligible = bool(fact.get("earned_eligible", True))
                virtual_outs_before = int(getattr(snap, "virtual_outs_before", 0) or 0)
                virtual_outs_after = int(getattr(snap, "virtual_outs_after", 0) or 0)
                scored_by_time = runner_id in virtual_scored_by_time
                pitcher_outs_before = getattr(snap, "pitcher_virtual_outs_before_by_runner_id", {}) or {}
                pitcher_outs_after = getattr(snap, "pitcher_virtual_outs_after_by_runner_id", {}) or {}
                pitcher_scored = getattr(snap, "pitcher_virtual_scored_by_runner_id", {}) or {}
                if runner_id in pitcher_outs_before:
                    virtual_outs_before = int(pitcher_outs_before.get(runner_id, virtual_outs_before) or 0)
                    virtual_outs_after = int(pitcher_outs_after.get(runner_id, virtual_outs_after) or 0)
                    scored_by_time = bool(pitcher_scored.get(runner_id, False))
                if virtual_outs_before >= 3:
                    judgment = "非自責点"
                    reason = "Neo Virtualでは得点プレー前に3アウト成立"
                elif (
                    virtual_outs_before > int(getattr(snap, "actual_outs_before", 0) or 0)
                    and virtual_outs_after >= 3
                ):
                    judgment = "非自責点"
                    reason = "Neo Virtualでは得点プレーで第3アウト成立"
                elif not earned_eligible:
                    judgment = "非自責点"
                    reason = f"得点走者が自責対象外の出塁: {reached_cause}"
                elif score_cause in self.UNEARNED_CAUSES:
                    judgment = "非自責点"
                    reason = f"失策・捕逸等による生還: {score_cause}"
                elif scored_by_time:
                    judgment = "自責点"
                    reason = "Neo Virtualで同一走者IDが得点時点までに生還"
                else:
                    judgment = "非自責点"
                    reason = "Neo Virtualで同一走者IDが得点時点までに未生還"
                compare.judgments.append(
                    ScoreJudgment(
                        score_no=score_no,
                        runner_text=runner_id,
                        judgment=judgment,
                        reason=reason,
                        confidence=100,
                    )
                )

        compare.team_judgments = list(compare.judgments)
        compare.pitcher_judgments = list(compare.judgments)
        compare.adopted_source = "Neo Virtual"
        return compare
