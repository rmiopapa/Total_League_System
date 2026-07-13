from __future__ import annotations


class TextReporter:
    """
    Phoenix Beta1-Start

    解析結果を人が読めるテキストに整形する。
    """

    def build(self, actual_report, virtual_report, compare_result, review_result) -> str:
        lines: list[str] = []

        lines.append("=" * 80)
        lines.append("EasyScoreJudge V2.0 Phoenix Beta1-Start")
        lines.append("=" * 80)
        lines.append("")
        lines.append("[Summary]")
        lines.append(f"Actual Scores : {actual_report.total_scores}")
        lines.append(f"Virtual Scores: {virtual_report.total_scores}")
        lines.append(f"Actual Outs   : {actual_report.total_outs}")
        lines.append(f"Virtual Outs  : {virtual_report.total_outs}")
        lines.append(f"Review Score  : {review_result.score}")
        lines.append("")

        lines.append("[Score Judgments]")
        if not compare_result.judgments:
            lines.append("  得点なし")
        for j in compare_result.judgments:
            lines.append(f"  {j.score_no}点目: {j.judgment} / confidence={j.confidence}%")
            lines.append(f"    Runner: {j.runner_text}")
            lines.append(f"    Reason: {j.reason}")
        lines.append("")

        lines.append("[Review]")
        if not review_result.items:
            lines.append("  REVIEWなし")
        for item in review_result.items:
            lines.append(f"  {item.level} / {item.location} / confidence={item.confidence}%")
            lines.append(f"    {item.message}")
            lines.append(f"    Suggestion: {item.suggestion}")
        lines.append("")

        lines.append("[Pitcher Changes]")
        pitcher_changes = getattr(actual_report, "pitcher_changes", [])
        if not pitcher_changes:
            lines.append("  投手交代なし")
        else:
            for row in pitcher_changes:
                lines.append("  " + row)
        lines.append("")

        lines.append("[Runner History]")
        runner_history = getattr(actual_report, "runner_history", [])
        if not runner_history:
            lines.append("  Runner履歴なし")
        else:
            for row in runner_history:
                lines.append("  " + row)
        lines.append("")

        lines.append("[Actual]")
        for pr in actual_report.plays:
            lines.append("-" * 70)
            lines.append(f"#{pr.seq}: {pr.raw_text}")
            lines.append(f"Before: {pr.before_text} / {pr.outs_before}死")
            for m in pr.moves_text:
                lines.append(f"  {m}")
            lines.append(f"After : {pr.after_text} / {pr.outs_after}死")
            if pr.scored_text:
                lines.append(f"Scored: {pr.scored_text}")
            if pr.outs_text:
                lines.append(f"Outs  : {pr.outs_text}")

        lines.append("")
        lines.append("[Virtual]")
        for pr in virtual_report.plays:
            lines.append("-" * 70)
            lines.append(f"#{pr.seq}: {pr.raw_text}")
            lines.append(f"Before: {pr.before_text} / {pr.outs_before}死")
            for note in pr.notes:
                lines.append(f"  {note}")
            for m in pr.moves_text:
                lines.append(f"  {m}")
            lines.append(f"After : {pr.after_text} / {pr.outs_after}死")

        return "\n".join(lines)
