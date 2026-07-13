from __future__ import annotations

from pathlib import Path
import json
import sys

from src.game.game_runner import GameRunner
from src.event.score_event_builder import ScoreEventBuilder
from src.config import GOLDDATA_EXCLUDED_CASES


class RegressionCaseRunner:
    """
    regression_cases/*/expected.json と sample.txt を使って回帰テストする。
    """

    def __init__(self, root: Path | str = "regression_cases"):
        # PyInstaller onedir 版では、同梱データが exe フォルダ直下ではなく
        # _internal または sys._MEIPASS 配下に展開されることがある。
        # 開発時は従来どおり ./regression_cases を使い、EXE時だけ同梱先を探索する。
        requested = Path(root)
        self.root = self._resolve_root(requested)

    @staticmethod
    def _resolve_root(requested: Path) -> Path:
        if requested.exists():
            return requested

        candidates: list[Path] = []

        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.extend([
                exe_dir / requested,
                exe_dir / "_internal" / requested,
            ])

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / requested)

        module_root = Path(__file__).resolve().parents[2]
        candidates.append(module_root / requested)

        for c in candidates:
            if c.exists():
                return c

        # 見つからない場合も、エラーメッセージ上のパスを分かりやすくするため
        # 元の指定値を返す。
        return requested

    def run_all(self, pitcher: str = "P", exclude_invalid: bool = False) -> dict:
        cases = sorted([p for p in self.root.glob("*") if p.is_dir()])
        if exclude_invalid:
            cases = [p for p in cases if p.name not in GOLDDATA_EXCLUDED_CASES]
        results = []
        passed = 0
        failed = 0

        for case_dir in cases:
            r = self.run_case(case_dir, pitcher=pitcher)
            if exclude_invalid:
                r["regression_set"] = "GoldData98"
            results.append(r)
            if r["passed"]:
                passed += 1
            else:
                failed += 1

        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": results,
        }


    def run_golddata98(self, pitcher: str = "P") -> dict:
        """互換名。V3.1では除外指定を使わず、存在するRCフォルダを全件検証する。

        検証から外したいケースは regression_cases/RC*** フォルダ自体を削除する。
        """
        return self.run_all(pitcher=pitcher, exclude_invalid=True)

    def run_pitcher_golddata17(self, pitcher: str = "P") -> dict:
        """互換名。V3.1では固定17件ではなく、全RCのPitcherGoldDataを検証する。"""
        return self.run_pitcher_golddata_all(pitcher=pitcher)

    def run_pitcher_golddata_all(self, pitcher: str = "P") -> dict:
        """regression_cases/RC***/pitcher_expected.json を持つ全RCを検証する。

        GoldData保存時に pitcher_expected.json も同じRCフォルダへ保存するため、
        PitcherGoldData専用フォルダや固定リストは不要。
        """
        cases = sorted([
            p for p in self.root.glob("RC*")
            if p.is_dir() and p.name not in GOLDDATA_EXCLUDED_CASES
        ])
        results = []
        passed = 0
        failed = 0
        for case_dir in cases:
            r = self.run_pitcher_case(case_dir, pitcher=pitcher)
            r["regression_set"] = "PitcherGoldData"
            results.append(r)
            if r.get("passed"):
                passed += 1
            else:
                failed += 1
        return {"total": len(results), "passed": passed, "failed": failed, "results": results}


    def run_pitcher_case(self, case_dir: Path, pitcher: str = "P") -> dict:
        expected_path = case_dir / "pitcher_expected.json"
        sample_path = case_dir / "sample.txt"

        if not expected_path.exists() or not sample_path.exists():
            return {
                "case": case_dir.name,
                "passed": False,
                "message": "pitcher_expected.json または sample.txt がありません",
            }

        expected_data = json.loads(expected_path.read_text(encoding="utf-8"))
        analysis = GameRunner().run_file(str(sample_path), pitcher=pitcher)

        game_obj = type("GameObj", (), {})()
        game_obj.game_name = expected_data.get("game", case_dir.name)
        game_obj.analysis = analysis

        builder = ScoreEventBuilder()
        events = builder.build_for_game(game_obj, judgment_source="pitcher")
        actual_pitchers: dict[str, dict[str, int]] = {}
        details = []
        for ev in events:
            charged = ev.charged_pitcher or "(責任投手不明)"
            actual_pitchers.setdefault(charged, {"runs": 0, "earned": 0})
            actual_pitchers[charged]["runs"] += 1
            if ev.judgment == "自責点":
                actual_pitchers[charged]["earned"] += 1
            details.append((ev.half, int(ev.score_no), ev.runner, charged, ev.judgment))

        actual_team = {
            "runs": sum(v["runs"] for v in actual_pitchers.values()),
            "earned": sum(v["earned"] for v in actual_pitchers.values()),
        }
        expected_pitchers = expected_data.get("pitchers", {})
        expected_team = expected_data.get("team", {})

        pitcher_diff = {
            "expected": expected_pitchers,
            "actual": actual_pitchers,
        } if expected_pitchers != actual_pitchers else {}
        team_diff = {
            "expected": expected_team,
            "actual": actual_team,
        } if expected_team != actual_team else {}

        return {
            "case": case_dir.name,
            "passed": not pitcher_diff and not team_diff,
            "message": "" if not pitcher_diff and not team_diff else "責任投手集計に差分あり",
            "pitcher_diff": pitcher_diff,
            "team_diff": team_diff,
            "expected_count": expected_team.get("runs", 0),
            "actual_count": actual_team.get("runs", 0),
        }

    def run_case(self, case_dir: Path, pitcher: str = "P") -> dict:
        expected_path = case_dir / "expected.json"
        sample_path = case_dir / "sample.txt"

        if not expected_path.exists() or not sample_path.exists():
            return {
                "case": case_dir.name,
                "passed": False,
                "message": "expected.json または sample.txt がありません",
            }

        expected_data = json.loads(expected_path.read_text(encoding="utf-8"))
        analysis = GameRunner().run_file(str(sample_path), pitcher=pitcher)

        game_obj = type("GameObj", (), {})()
        game_obj.game_name = expected_data.get("game", case_dir.name)
        game_obj.analysis = analysis

        builder = ScoreEventBuilder()
        actual_events = builder.build_for_game(game_obj, judgment_source="team")
        actual = [(e.half, e.score_no, e.judgment) for e in actual_events]

        expected = [
            (e["inning"], int(e["score_no"]), e["judgment"])
            for e in expected_data.get("expected", [])
        ]

        missing = [e for e in expected if e not in actual]
        extra = [a for a in actual if a not in expected]

        return {
            "case": case_dir.name,
            "passed": not missing and not extra,
            "missing": missing,
            "extra": extra,
            "expected_count": len(expected),
            "actual_count": len(actual),
        }
