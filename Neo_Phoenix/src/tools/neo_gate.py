from __future__ import annotations

import argparse
from pathlib import Path

from src.neo.case_comparator import NeoCaseComparator
from src.config import GOLDDATA_EXCLUDED_CASES


def _print_result(result: dict, limit_cases: int) -> None:
    print("\n[Neo / Phoenix State Comparison]")
    print(
        f"total={result['total']} passed={result['passed']} "
        f"failed={result['failed']} total_diffs={result['total_diffs']} "
        f"blocking_diffs={result.get('total_blocking_diffs', 0)} "
        f"policy_diffs={result.get('total_policy_diffs', 0)}"
    )
    categories = result.get("categories", {})
    if categories:
        print("categories:")
        for name, count in list(categories.items())[:12]:
            print(f"  {name}: {count}")
    policy_categories = result.get("policy_categories", {})
    if policy_categories:
        print("policy categories:")
        for name, count in list(policy_categories.items())[:8]:
            print(f"  {name}: {count}")
    shown = 0
    for row in result.get("results", []):
        if row.get("passed"):
            continue
        print(
            f"  DIFF {row.get('case')}: "
            f"diffs={row.get('diff_count')} blocking={row.get('blocking_diff_count')} "
            f"policy={row.get('policy_diff_count')} warnings={row.get('warning_count')} "
            f"message={row.get('message')}"
        )
        for diff in row.get("diffs", []):
            mark = " policy" if diff.get("policy_expected") else ""
            print(
                f"    {diff.get('half')} seq={diff.get('seq')} {diff.get('kind')}{mark}: "
                f"Phoenix={diff.get('phoenix')} | Neo={diff.get('neo')} | {diff.get('raw_text')}"
            )
        for warning in row.get("warnings", []):
            print(f"    warning: {warning}")
        shown += 1
        if shown >= limit_cases:
            remaining = result.get("failed", 0) - shown
            if remaining > 0:
                print(f"  ... {remaining} more differing cases")
            break


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare current Phoenix states with Neo_Phoenix states.")
    parser.add_argument("--root", default="regression_cases", help="Regression case root directory.")
    parser.add_argument("--limit-cases", type=int, default=10, help="Number of differing cases to print.")
    parser.add_argument("--limit-diffs", type=int, default=5, help="Number of diffs to keep per case.")
    parser.add_argument("--report-only", action="store_true", help="Always exit 0 after printing comparison.")
    args = parser.parse_args()

    print("Neo_Phoenix Comparison Gate")
    print(f"Target: {Path(args.root)}")
    if GOLDDATA_EXCLUDED_CASES:
        print(f"Excluded invalid GoldData cases: {', '.join(sorted(GOLDDATA_EXCLUDED_CASES))}")
    comparator = NeoCaseComparator(Path(args.root))
    result = comparator.run_all(limit_diffs_per_case=args.limit_diffs)
    _print_result(result, limit_cases=args.limit_cases)
    if args.report_only:
        return 0
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
