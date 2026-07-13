from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReviewItem:
    level: str
    location: str
    message: str
    suggestion: str
    confidence: int


@dataclass
class ReviewResult:
    items: list[ReviewItem] = field(default_factory=list)

    @property
    def score(self) -> int:
        if not self.items:
            return 100
        penalty = sum(5 if item.level == "INFO" else 10 if item.level == "WARN" else 20 for item in self.items)
        return max(0, 100 - penalty)


class ReviewEngine:
    """
    Phoenix Beta1-Start

    入力品質・解析品質を確認するReview Engineの最小版。
    """

    def review(self, actual_report, virtual_report, compare_result) -> ReviewResult:
        result = ReviewResult()

        for pr in actual_report.plays:
            for w in pr.warnings:
                result.items.append(
                    ReviewItem(
                        level="WARN",
                        location=f"Actual #{pr.seq}",
                        message=w,
                        suggestion="走者状態またはMove補完を確認してください",
                        confidence=90,
                    )
                )

        for pr in virtual_report.plays:
            for w in pr.warnings:
                result.items.append(
                    ReviewItem(
                        level="WARN",
                        location=f"Virtual #{pr.seq}",
                        message=w,
                        suggestion="VirtualMoveFilterの対象か確認してください",
                        confidence=90,
                    )
                )
            for note in pr.notes:
                # V3.1 Quality06:
                # 「Virtual上に走者なし」は、失策/PB等でActualだけに残った走者の後続移動であり、
                # 正常な自然差分。警告・INFOとして画面に出さない。
                if note.startswith("V安全除外") and "Virtual上に走者なし" not in note:
                    result.items.append(
                        ReviewItem(
                            level="INFO",
                            location=f"Virtual #{pr.seq}",
                            message=note,
                            suggestion="ActualとVirtualの差分により安全除外されました",
                            confidence=100,
                        )
                    )

        if actual_report.total_scores != len(compare_result.judgments):
            result.items.append(
                ReviewItem(
                    level="ERROR",
                    location="Comparator",
                    message="Actual得点数と判定数が一致しません",
                    suggestion="得点抽出ロジックを確認してください",
                    confidence=100,
                )
            )

        return result
