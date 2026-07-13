from __future__ import annotations

import argparse
from pathlib import Path

import v30_review_window as phoenix_ui
from src.config import GOLDDATA_EXCLUDED_CASES, NEO_JUDGMENT_EXCLUDED_CASES
from src.neo.game_runner import NeoDayRunner
from src.tools import neo_judgment_gate, neo_pitcher_gate
from src.version import VERSION


phoenix_ui.DayRunner = NeoDayRunner


class NeoPhoenixReviewWindow(phoenix_ui.PhoenixReviewWindow):
    def __init__(self, developer_mode: bool = False):
        super().__init__(developer_mode=developer_mode)
        suffix = "Developer" if developer_mode else "User"
        self.root.title(f"NeoPhoenix {VERSION} - {suffix}")
        self.status.set(
            "NeoPhoenix mode: URLを入力して解析してください。"
            if not developer_mode
            else "NeoPhoenix Developer mode: 解析後にdaily_check/debug_reportをNeo判定で保存します。"
        )

    def run_saved_regression(self):
        """Run Neo-only saved GoldData gates from the developer GUI."""
        try:
            self.status.set("Neo saved GoldData gate running... (Team/Pitcher)")
            self.root.update_idletasks()

            root = Path("regression_cases")
            team = neo_judgment_gate.run(root, limit_cases=20, limit_diffs=5)
            pitcher = neo_pitcher_gate.run(root, limit_cases=20)
            result = {
                "team": team,
                "pitcher": pitcher,
                "passed": team.get("different", 0) == 0 and pitcher.get("failed", 0) == 0,
            }
            self._populate_neo_gate_results(result)

            status = "PASS" if result["passed"] else "FAIL"
            self.status.set(
                f"Neo saved GoldData gate {status}: "
                f"Team {team.get('matched', 0)}/{team.get('total', 0)}, "
                f"Pitcher {pitcher.get('passed', 0)}/{pitcher.get('total', 0)}"
            )
        except Exception as exc:
            phoenix_ui.messagebox.showerror("Neo Gate Error", str(exc))
            self.status.set("Neo saved GoldData gate error.")

    def _append_team_pitcher_comparison(self, game, team_events, pitcher_events):
        super()._append_team_pitcher_comparison(game, team_events, pitcher_events)
        self.tree.insert(
            "",
            "end",
            values=(
                game.game_name,
                "Neo output",
                "INFO",
                "Screen rows use Neo Pitcher judgment; DebugReport uses Neo Team/Pitcher traces.",
                "",
            ),
        )

    def _populate_neo_gate_results(self, result: dict):
        for item in self.tree.get_children():
            self.tree.delete(item)

        team = result.get("team", {})
        pitcher = result.get("pitcher", {})
        status = "PASS" if result.get("passed") else "FAIL"
        excluded = sorted(GOLDDATA_EXCLUDED_CASES | NEO_JUDGMENT_EXCLUDED_CASES)

        self.tree.insert(
            "",
            "end",
            values=(
                "Neo saved GoldData gate",
                "Summary",
                status,
                f"Excluded: {', '.join(excluded) if excluded else '-'}",
                f"Version {VERSION}",
            ),
        )
        self.tree.insert(
            "",
            "end",
            values=(
                "Neo Team",
                "regression_cases",
                "PASS" if team.get("different", 0) == 0 else "FAIL",
                f"{team.get('matched', 0)}/{team.get('total', 0)}",
                f"missing={team.get('missing', 0)} extra={team.get('extra', 0)}",
            ),
        )
        self.tree.insert(
            "",
            "end",
            values=(
                "Neo Pitcher",
                "regression_cases",
                "PASS" if pitcher.get("failed", 0) == 0 else "FAIL",
                f"{pitcher.get('passed', 0)}/{pitcher.get('total', 0)}",
                "",
            ),
        )

        for sample in team.get("samples", []):
            case = sample.get("case", "")
            if sample.get("error"):
                self.tree.insert("", "end", values=("Neo Team", case, "ERROR", sample.get("error", ""), ""))
                continue
            self.tree.insert(
                "",
                "end",
                values=(
                    "Neo Team",
                    case,
                    "FAIL",
                    f"expected={sample.get('expected_count', '')} actual={sample.get('actual_count', '')}",
                    f"missing={sample.get('missing', [])} extra={sample.get('extra', [])}",
                ),
            )

        for sample in pitcher.get("samples", []):
            case = sample.get("case", "")
            self.tree.insert(
                "",
                "end",
                values=(
                    "Neo Pitcher",
                    case,
                    "FAIL",
                    str(sample.get("team_diff") or sample.get("pitcher_diff") or ""),
                    "",
                ),
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true", help="start in developer mode")
    args = parser.parse_args()
    NeoPhoenixReviewWindow(developer_mode=args.dev).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
