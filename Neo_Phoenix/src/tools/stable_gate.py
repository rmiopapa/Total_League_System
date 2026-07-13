from __future__ import annotations

from pathlib import Path
from src.regression.regression_case_runner import RegressionCaseRunner
from src.config import GOLDDATA_EXCLUDED_CASES


def _print_result(title: str, result: dict) -> None:
    print(f"\n[{title}]")
    print(f"total={result['total']} passed={result['passed']} failed={result['failed']}")
    for r in result.get('results', []):
        if not r.get('passed'):
            print(f"  NG {r.get('case')}: missing={r.get('missing')} extra={r.get('extra')} message={r.get('message')}")


def main() -> int:
    runner = RegressionCaseRunner(Path('regression_cases'))
    print('Phoenix V3.1 Regression Gate')
    print('Target: all existing regression_cases/RC*** folders')
    if GOLDDATA_EXCLUDED_CASES:
        print(f"Excluded invalid GoldData cases: {', '.join(sorted(GOLDDATA_EXCLUDED_CASES))}")

    team = runner.run_golddata98()
    pitcher = runner.run_pitcher_golddata17()
    _print_result('GoldData / Team Regression', team)
    _print_result('PitcherGoldData / Responsibility Regression', pitcher)
    return 0 if team['failed'] == 0 and pitcher['failed'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
