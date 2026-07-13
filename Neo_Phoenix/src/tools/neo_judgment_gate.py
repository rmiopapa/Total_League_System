from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.config import GOLDDATA_EXCLUDED_CASES, NEO_JUDGMENT_EXCLUDED_CASES
from src.game.game_text_reader import GameTextReader
from src.neo.engine import NeoHalfInningEngine
from src.neo.judgment import NeoScoreJudgmentBuilder


def _case_expected(case_dir: Path) -> list[tuple[str, int, str]]:
    expected_path = case_dir / "expected.json"
    if not expected_path.exists():
        return []
    data = json.loads(expected_path.read_text(encoding="utf-8"))
    return [
        (str(item.get("inning", "")), int(item.get("score_no", 0) or 0), str(item.get("judgment", "")))
        for item in data.get("expected", [])
    ]


def _case_actual(case_dir: Path) -> list[dict[str, object]]:
    sample_path = case_dir / "sample.txt"
    if not sample_path.exists():
        return []

    reader = GameTextReader()
    judgment_builder = NeoScoreJudgmentBuilder()
    actual: list[dict[str, object]] = []

    for block in reader.read(sample_path).half_innings:
        neo = NeoHalfInningEngine(f"Neo {block.title}").run(block.lines)
        compare = judgment_builder.build(neo)
        judgments = list(compare.judgments)
        score_index = 0
        for snap in neo.plays:
            same_seq_scored = set(getattr(snap, "virtual_scored_runner_ids", []) or [])
            facts_by_id = {
                str(fact.get("id", "")): fact
                for fact in getattr(snap, "actual_scored_runner_facts", []) or []
            }
            for runner_id in getattr(snap, "actual_scored_runner_ids", []) or []:
                if score_index >= len(judgments):
                    continue
                judgment = judgments[score_index]
                score_index += 1
                fact = facts_by_id.get(str(runner_id), {})
                actual.append(
                    {
                        "key": (block.title, int(judgment.score_no), str(judgment.judgment)),
                        "reason": str(judgment.reason),
                        "runner": str(judgment.runner_text),
                        "seq": int(getattr(snap, "seq", 0) or 0),
                        "same_seq_virtual_scored": str(runner_id) in same_seq_scored,
                        "virtual_outs_before": int(getattr(snap, "virtual_outs_before", 0) or 0),
                        "virtual_outs_after": int(getattr(snap, "virtual_outs_after", 0) or 0),
                        "reached_cause_type": str(fact.get("reached_cause_type", "") or ""),
                        "score_cause_type": str(fact.get("score_cause_type", "") or ""),
                    }
                )

    return actual


def run(root: Path, limit_cases: int = 10, limit_diffs: int = 5) -> dict:
    cases = sorted(
        p
        for p in root.glob("RC*")
        if p.is_dir() and p.name not in GOLDDATA_EXCLUDED_CASES | NEO_JUDGMENT_EXCLUDED_CASES
    )
    results: list[dict] = []
    passed = 0
    failed = 0
    total_missing = 0
    total_extra = 0
    direction_counts: dict[str, int] = {}
    global_reason_counts: dict[str, int] = {}
    direction_reason_counts: dict[str, int] = {}
    review_rows: list[dict[str, object]] = []

    for case_dir in cases:
        try:
            expected = _case_expected(case_dir)
            actual_records = _case_actual(case_dir)
            actual = [record["key"] for record in actual_records]
            actual_by_slot = {
                (item[0], item[1]): record
                for record in actual_records
                for item in [record["key"]]
            }
            missing = [item for item in expected if item not in actual]
            extra = [item for item in actual if item not in expected]
            ok = not missing and not extra
            passed += 1 if ok else 0
            failed += 0 if ok else 1
            total_missing += len(missing)
            total_extra += len(extra)
            for exp in missing:
                counterpart = next(
                    (
                        act
                        for act in extra
                        if act[0] == exp[0] and act[1] == exp[1]
                    ),
                    None,
                )
                if counterpart is None:
                    direction = f"missing_{exp[2]}"
                else:
                    direction = f"{exp[2]}_to_{counterpart[2]}"
                direction_counts[direction] = direction_counts.get(direction, 0) + 1
                if counterpart is not None:
                    record = actual_by_slot.get((counterpart[0], counterpart[1]), {})
                    reason = str(record.get("reason", ""))
                    key = f"{direction} / {reason}"
                    direction_reason_counts[key] = direction_reason_counts.get(key, 0) + 1
                    review_rows.append(
                        {
                            "case": case_dir.name,
                            "inning": exp[0],
                            "score_no": exp[1],
                            "golddata": exp[2],
                            "neo": counterpart[2],
                            "direction": direction,
                            "runner": str(record.get("runner", "")),
                            "reason": reason,
                            "seq": record.get("seq", ""),
                            "same_seq_virtual_scored": record.get("same_seq_virtual_scored", ""),
                            "virtual_outs_before": record.get("virtual_outs_before", ""),
                            "virtual_outs_after": record.get("virtual_outs_after", ""),
                            "reached_cause_type": record.get("reached_cause_type", ""),
                            "score_cause_type": record.get("score_cause_type", ""),
                        }
                    )
            reason_counts: dict[str, int] = {}
            for item in extra:
                record = actual_by_slot.get((item[0], item[1]), {})
                reason = str(record.get("reason", ""))
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                global_reason_counts[reason] = global_reason_counts.get(reason, 0) + 1
            if not ok and len(results) < limit_cases:
                results.append(
                    {
                        "case": case_dir.name,
                        "missing": missing[:limit_diffs],
                        "extra": [
                            {
                                "key": item,
                                "reason": str(actual_by_slot.get((item[0], item[1]), {}).get("reason", "")),
                                "runner": str(actual_by_slot.get((item[0], item[1]), {}).get("runner", "")),
                                "seq": actual_by_slot.get((item[0], item[1]), {}).get("seq", ""),
                                "same_seq_virtual_scored": actual_by_slot.get((item[0], item[1]), {}).get("same_seq_virtual_scored", ""),
                                "virtual_outs_before": actual_by_slot.get((item[0], item[1]), {}).get("virtual_outs_before", ""),
                            }
                            for item in extra[:limit_diffs]
                        ],
                        "neo_reasons": dict(sorted(reason_counts.items(), key=lambda row: (-row[1], row[0]))),
                        "expected_count": len(expected),
                        "actual_count": len(actual),
                    }
                )
        except Exception as exc:
            failed += 1
            if len(results) < limit_cases:
                results.append({"case": case_dir.name, "error": str(exc)})

    return {
        "total": len(cases),
        "matched": passed,
        "different": failed,
        "missing": total_missing,
        "extra": total_extra,
        "directions": dict(sorted(direction_counts.items(), key=lambda item: (-item[1], item[0]))),
        "neo_reasons": dict(sorted(global_reason_counts.items(), key=lambda item: (-item[1], item[0]))),
        "direction_reasons": dict(sorted(direction_reason_counts.items(), key=lambda item: (-item[1], item[0]))),
        "review_rows": review_rows,
        "samples": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Neo runner-id judgments with team GoldData.")
    parser.add_argument("--root", default="regression_cases")
    parser.add_argument("--limit-cases", type=int, default=10)
    parser.add_argument("--limit-diffs", type=int, default=5)
    parser.add_argument("--csv", default="")
    args = parser.parse_args()

    result = run(Path(args.root), limit_cases=args.limit_cases, limit_diffs=args.limit_diffs)

    print("Neo_Phoenix Judgment Comparison")
    if GOLDDATA_EXCLUDED_CASES:
        print(f"Excluded invalid GoldData cases: {', '.join(sorted(GOLDDATA_EXCLUDED_CASES))}")
    if NEO_JUDGMENT_EXCLUDED_CASES:
        print(f"Excluded Neo review cases: {', '.join(sorted(NEO_JUDGMENT_EXCLUDED_CASES))}")
    print(
        f"total={result['total']} matched={result['matched']} different={result['different']} "
        f"missing={result['missing']} extra={result['extra']}"
    )
    if result["directions"]:
        print("directions:")
        for key, count in result["directions"].items():
            print(f"  {key}: {count}")
    if result["neo_reasons"]:
        print("neo reasons:")
        for key, count in result["neo_reasons"].items():
            print(f"  {key}: {count}")
    if result["direction_reasons"]:
        print("direction reasons:")
        for key, count in result["direction_reasons"].items():
            print(f"  {key}: {count}")
    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "case",
                    "inning",
                    "score_no",
                    "golddata",
                    "neo",
                    "direction",
                    "runner",
                    "reason",
                    "seq",
                    "same_seq_virtual_scored",
                    "virtual_outs_before",
                    "virtual_outs_after",
                    "reached_cause_type",
                    "score_cause_type",
                ],
            )
            writer.writeheader()
            writer.writerows(result["review_rows"])
        print(f"csv={csv_path}")
    for sample in result["samples"]:
        print(f"- {sample['case']}")
        if "error" in sample:
            print(f"  error: {sample['error']}")
            continue
        for item in sample.get("missing", []):
            print(f"  missing expected: {item}")
        for item in sample.get("extra", []):
            print(
                f"  extra neo: {item['key']} / runner={item['runner']} / "
                f"seq={item['seq']} / same_seq={item['same_seq_virtual_scored']} / "
                f"v_outs_before={item['virtual_outs_before']} / reason={item['reason']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
