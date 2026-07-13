from __future__ import annotations

from dataclasses import dataclass
from src.runner.runner import Runner


@dataclass
class EarnedRunResult:
    runner_id: str
    runner_name: str
    judgment: str
    reason: str


class EarnedRunJudge:
    """
    Phoenix alpha7 最小版

    まずは得点走者の earned_eligible だけを見る。
    Virtual比較は alpha8 以降。
    """

    def judge_scored_runner(self, runner: Runner) -> EarnedRunResult:
        if not runner.earned_eligible:
            return EarnedRunResult(
                runner_id=runner.id,
                runner_name=runner.name,
                judgment="非自責点",
                reason=f"得点走者が自責対象外の出塁: {runner.reached_cause_type} / {runner.reached_by}",
            )

        return EarnedRunResult(
            runner_id=runner.id,
            runner_name=runner.name,
            judgment="自責点候補",
            reason=f"得点走者は自責対象: {runner.reached_cause_type} / {runner.reached_by}",
        )
