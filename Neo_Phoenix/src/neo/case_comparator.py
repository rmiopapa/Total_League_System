from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from src.game.game_runner import GameRunner
from src.game.game_text_reader import GameTextReader
from src.neo.engine import NeoHalfInningEngine
from src.config import GOLDDATA_EXCLUDED_CASES


EMPTY_STATE = "一塁[空] 二塁[空] 三塁[空]"


@dataclass
class NeoPlayDiff:
    half: str
    raw_text: str
    seq: int
    kind: str
    phoenix: str
    neo: str
    policy_expected: bool = False


@dataclass
class NeoCaseResult:
    case: str
    passed: bool
    diffs: list[NeoPlayDiff] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message: str = ""


class NeoCaseComparator:
    """Compares current Phoenix play states with the experimental Neo core."""

    def __init__(self, root: Path | str = "regression_cases"):
        self.root = Path(root)
        self.reader = GameTextReader()
        self.game_runner = GameRunner()

    def run_all(self, limit_diffs_per_case: int = 5) -> dict:
        cases = sorted([
            p for p in self.root.glob("RC*")
            if p.is_dir() and p.name not in GOLDDATA_EXCLUDED_CASES
        ])
        results: list[dict] = []
        passed = 0
        failed = 0
        total_diffs = 0
        total_blocking_diffs = 0
        total_policy_diffs = 0
        categories: dict[str, int] = {}
        policy_categories: dict[str, int] = {}

        for case_dir in cases:
            result = self.run_case(case_dir, limit_diffs_per_case=limit_diffs_per_case)
            total_diffs += len(result.diffs)
            for diff in result.diffs:
                categories[diff.kind] = categories.get(diff.kind, 0) + 1
                if diff.policy_expected:
                    total_policy_diffs += 1
                    policy_categories[diff.kind] = policy_categories.get(diff.kind, 0) + 1
                else:
                    total_blocking_diffs += 1
            results.append(self._as_dict(result, limit_diffs_per_case))
            if result.passed:
                passed += 1
            else:
                failed += 1

        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "total_diffs": total_diffs,
            "total_blocking_diffs": total_blocking_diffs,
            "total_policy_diffs": total_policy_diffs,
            "categories": dict(sorted(categories.items(), key=lambda item: (-item[1], item[0]))),
            "policy_categories": dict(sorted(policy_categories.items(), key=lambda item: (-item[1], item[0]))),
            "results": results,
        }

    def run_case(self, case_dir: Path, limit_diffs_per_case: int = 5) -> NeoCaseResult:
        sample_path = case_dir / "sample.txt"
        if not sample_path.exists():
            return NeoCaseResult(case=case_dir.name, passed=False, message="sample.txt not found")

        try:
            phoenix = self.game_runner.run_file(str(sample_path))
            blocks = self.reader.read(sample_path).half_innings
        except Exception as exc:
            return NeoCaseResult(case=case_dir.name, passed=False, message=f"Phoenix read/run failed: {exc}")

        diffs: list[NeoPlayDiff] = []
        warnings: list[str] = []

        for half_analysis, block in zip(phoenix.halves, blocks):
            try:
                neo = NeoHalfInningEngine(f"Neo {block.title}").run(block.lines)
            except Exception as exc:
                diffs.append(
                    NeoPlayDiff(
                        half=block.title,
                        raw_text="",
                        seq=0,
                        kind="neo_exception",
                        phoenix="",
                        neo=str(exc),
                    )
                )
                continue

            warnings.extend([f"{block.title}: {w}" for w in neo.warnings])
            diffs.extend(self._compare_report(block.title, half_analysis.actual_report, neo, "actual"))
            diffs.extend(self._compare_report(block.title, half_analysis.virtual_report, neo, "virtual"))

        blocking = [d for d in diffs if not d.policy_expected]
        return NeoCaseResult(
            case=case_dir.name,
            passed=not blocking,
            diffs=diffs,
            warnings=warnings,
        )

    def _compare_report(self, half: str, phoenix_report, neo_result, mode: str) -> list[NeoPlayDiff]:
        diffs: list[NeoPlayDiff] = []
        policy_seen = False
        neo_by_raw = {}
        for snap in neo_result.plays:
            neo_by_raw.setdefault(str(getattr(snap, "raw_text", "")), []).append(snap)

        for pr in getattr(phoenix_report, "plays", []) or []:
            raw = str(getattr(pr, "raw_text", ""))
            if self._is_ignored_line(raw):
                continue
            snaps = neo_by_raw.get(raw) or []
            snap = snaps.pop(0) if snaps else None
            if snap is None:
                diffs.append(
                    NeoPlayDiff(
                        half=half,
                        raw_text=raw,
                        seq=int(getattr(pr, "seq", 0) or 0),
                        kind=f"{mode}_missing_neo_play",
                        phoenix=str(getattr(pr, "after_text", "")),
                        neo="",
                    )
                )
                continue

            phoenix_after = str(getattr(pr, "after_text", ""))
            neo_after = str(getattr(snap, f"{mode}_after", ""))
            if self._normalize_state_text(phoenix_after) == self._normalize_state_text(neo_after):
                continue

            kind = self._classify_diff(mode, raw, phoenix_after, neo_after, snap, policy_seen)
            policy_expected = self._is_policy_expected_diff(kind, mode)
            diffs.append(
                NeoPlayDiff(
                    half=half,
                    raw_text=raw,
                    seq=int(getattr(pr, "seq", 0) or 0),
                    kind=kind,
                    phoenix=phoenix_after,
                    neo=neo_after,
                    policy_expected=policy_expected,
                )
            )
            if mode == "virtual" and policy_expected:
                policy_seen = True

        return diffs

    def _normalize_state_text(self, text: str) -> str:
        normalized = str(text or "")
        normalized = re.sub(r"(R\d+):[^\]]+", r"\1", normalized)
        return normalized

    def _classify_diff(self, mode: str, raw: str, phoenix: str, neo: str, snap=None, policy_seen: bool = False) -> str:
        text = str(raw or "")
        p = self._normalize_state_text(phoenix)
        n = self._normalize_state_text(neo)
        if mode == "actual" and p == EMPTY_STATE and n != p:
            return "actual_extra_runner_left"
        if mode == "actual" and self._has_batter_out_text(text) and p != n:
            return "actual_batter_out_or_final_state"
        if mode == "virtual" and self._has_error_or_pb_text(text):
            return "virtual_error_or_pb_advance"
        if mode == "virtual" and snap is not None:
            actual_after = self._normalize_state_text(str(getattr(snap, "actual_after", "")))
            if n == actual_after:
                return "virtual_matches_actual_policy"
        if mode == "virtual" and policy_seen:
            return "virtual_policy_cascade"
        if mode == "virtual" and self._has_normal_offense_text(text):
            return "virtual_normal_advance"
        if self._is_inning_end_text(text) and n != EMPTY_STATE:
            return f"{mode}_inning_end_not_cleared"
        return f"{mode}_after"

    def _is_policy_expected_diff(self, kind: str, mode: str) -> bool:
        return mode == "virtual" and kind in {
            "virtual_error_or_pb_advance",
            "virtual_matches_actual_policy",
            "virtual_normal_advance",
            "virtual_policy_cascade",
        }

    def _is_ignored_line(self, raw: str) -> bool:
        text = str(raw or "")
        if "タイブレーク" in text:
            return not ("一、二塁" in text or "二塁" in text or "満塁" in text)
        return any(
            word in text
            for word in ["投手交代", "守備位置変更", "守備交代", "代打", "代走", "マウンド", "先発は"]
        )

    def _is_inning_end_text(self, text: str) -> bool:
        return ("チェンジ" in text and "チェンジアップ" not in text) or "試合終了" in text

    def _has_batter_out_text(self, text: str) -> bool:
        return any(word in text for word in ["三振", "飛", "直", "ゴロ", "併殺"])

    def _has_error_or_pb_text(self, text: str) -> bool:
        return any(word in text for word in ["失策", "悪送球", "後逸", "ファンブル", "落球", "捕逸"])

    def _has_normal_offense_text(self, text: str) -> bool:
        return any(
            word in text
            for word in [
                "四球",
                "敬遠申告",
                "死球",
                "安打",
                "ヒット",
                "適時打",
                "二塁打",
                "三塁打",
                "本塁打",
                "盗塁",
                "重盗",
                "犠飛",
                "野手選択",
                "野選",
                "暴投",
                "その間に打者が出塁",
                "走者が",
                "封殺",
            ]
        )

    def _as_dict(self, result: NeoCaseResult, limit: int) -> dict:
        diffs = result.diffs[:limit]
        return {
            "case": result.case,
            "passed": result.passed,
            "diff_count": len(result.diffs),
            "blocking_diff_count": len([d for d in result.diffs if not d.policy_expected]),
            "policy_diff_count": len([d for d in result.diffs if d.policy_expected]),
            "warning_count": len(result.warnings),
            "message": result.message,
            "diffs": [
                {
                    "half": d.half,
                    "seq": d.seq,
                    "kind": d.kind,
                    "policy_expected": d.policy_expected,
                    "raw_text": d.raw_text,
                    "phoenix": d.phoenix,
                    "neo": d.neo,
                }
                for d in diffs
            ],
            "warnings": result.warnings[:limit],
        }
