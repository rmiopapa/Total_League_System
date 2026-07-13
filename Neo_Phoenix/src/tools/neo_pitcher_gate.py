from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.config import GOLDDATA_EXCLUDED_CASES, NEO_JUDGMENT_EXCLUDED_CASES
from src.event.score_event_builder import ScoreEventBuilder
from src.game.game_runner import GameRunner
from src.game.game_text_reader import GameTextReader
from src.neo.engine import NeoHalfInningEngine
from src.neo.judgment import NeoScoreJudgmentBuilder


def _entered_pitchers(actual_report) -> set[str]:
    entered: set[str] = set()
    builder = ScoreEventBuilder()
    mapping = builder.pitcher_display_map(type("Half", (), {"actual_report": actual_report})())
    for row in getattr(actual_report, "pitcher_changes", []) or []:
        parts = str(row).split(",", 3)
        if len(parts) >= 3:
            pitcher = builder.display_pitcher(parts[2].strip(), mapping)
            if pitcher:
                entered.add(pitcher)
    return entered


def _runner_pitcher_map(actual_report) -> dict[str, str]:
    half = type("Half", (), {"actual_report": actual_report})()
    return ScoreEventBuilder().runner_pitcher_map(half)


def _case_actual(case_dir: Path) -> dict[str, object]:
    sample_path = case_dir / "sample.txt"
    if not sample_path.exists():
        return {"pitchers": {}, "team": {"runs": 0, "earned": 0}, "details": []}

    phoenix = GameRunner().run_file(str(sample_path))
    blocks = GameTextReader().read(sample_path).half_innings
    judgment_builder = NeoScoreJudgmentBuilder()

    by_pitcher: dict[str, dict[str, int]] = {}
    details: list[dict[str, object]] = []

    for half_analysis, block in zip(phoenix.halves, blocks):
        team_neo = NeoHalfInningEngine(f"Neo Team {block.title}").run(block.lines)
        pitcher_neo = NeoHalfInningEngine(f"Neo Pitcher {block.title}", pitcher_split_mode=True).run(block.lines)
        team_judgments = list(judgment_builder.build(team_neo).judgments)
        pitcher_judgments = list(judgment_builder.build(pitcher_neo).judgments)
        runner_pitcher = _runner_pitcher_map(half_analysis.actual_report)
        entered = _entered_pitchers(half_analysis.actual_report)

        for idx, team_j in enumerate(team_judgments):
            pitcher_j = pitcher_judgments[idx] if idx < len(pitcher_judgments) else team_j
            runner_id = ScoreEventBuilder().runner_id(str(getattr(team_j, "runner_text", "")))
            charged = runner_pitcher.get(runner_id, "") or "(責任投手不明)"
            judgment = pitcher_j if charged in entered else team_j
            by_pitcher.setdefault(charged, {"runs": 0, "earned": 0})
            by_pitcher[charged]["runs"] += 1
            if str(getattr(judgment, "judgment", "")) == "自責点":
                by_pitcher[charged]["earned"] += 1
            details.append(
                {
                    "inning": block.title,
                    "score_no": int(getattr(team_j, "score_no", 0) or 0),
                    "runner": str(getattr(team_j, "runner_text", "")),
                    "charged_pitcher": charged,
                    "judgment": str(getattr(judgment, "judgment", "")),
                    "team_judgment": str(getattr(team_j, "judgment", "")),
                    "pitcher_judgment": str(getattr(pitcher_j, "judgment", "")),
                }
            )

    team = {
        "runs": sum(row["runs"] for row in by_pitcher.values()),
        "earned": sum(row["earned"] for row in by_pitcher.values()),
    }
    return {"pitchers": by_pitcher, "team": team, "details": details}


def run(root: Path, limit_cases: int = 10) -> dict[str, object]:
    excluded = GOLDDATA_EXCLUDED_CASES | NEO_JUDGMENT_EXCLUDED_CASES
    cases = sorted(
        p
        for p in root.glob("RC*")
        if p.is_dir() and p.name not in excluded and (p / "pitcher_expected.json").exists()
    )
    results: list[dict[str, object]] = []
    passed = 0
    failed = 0
    for case_dir in cases:
        expected = json.loads((case_dir / "pitcher_expected.json").read_text(encoding="utf-8"))
        actual = _case_actual(case_dir)
        pitcher_diff = (
            {"expected": expected.get("pitchers", {}), "actual": actual["pitchers"]}
            if expected.get("pitchers", {}) != actual["pitchers"]
            else {}
        )
        team_diff = (
            {"expected": expected.get("team", {}), "actual": actual["team"]}
            if expected.get("team", {}) != actual["team"]
            else {}
        )
        ok = not pitcher_diff and not team_diff
        passed += 1 if ok else 0
        failed += 0 if ok else 1
        if not ok and len(results) < limit_cases:
            results.append(
                {
                    "case": case_dir.name,
                    "pitcher_diff": pitcher_diff,
                    "team_diff": team_diff,
                    "details": actual["details"],
                }
            )
    return {"total": len(cases), "passed": passed, "failed": failed, "samples": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Neo Pitcher judgments with pitcher_expected.json.")
    parser.add_argument("--root", default="regression_cases")
    parser.add_argument("--limit-cases", type=int, default=10)
    args = parser.parse_args()

    result = run(Path(args.root), limit_cases=args.limit_cases)
    print("Neo_Phoenix Pitcher Judgment Gate")
    if GOLDDATA_EXCLUDED_CASES:
        print(f"Excluded invalid GoldData cases: {', '.join(sorted(GOLDDATA_EXCLUDED_CASES))}")
    if NEO_JUDGMENT_EXCLUDED_CASES:
        print(f"Excluded Neo review cases: {', '.join(sorted(NEO_JUDGMENT_EXCLUDED_CASES))}")
    print(f"total={result['total']} passed={result['passed']} failed={result['failed']}")
    for sample in result["samples"]:
        print(f"- {sample['case']}")
        if sample.get("team_diff"):
            print(f"  team_diff={sample['team_diff']}")
        if sample.get("pitcher_diff"):
            print(f"  pitcher_diff={sample['pitcher_diff']}")
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
