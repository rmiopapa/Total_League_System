from __future__ import annotations

from pathlib import Path
import csv


class CsvReporter:
    """
    Phoenix Beta1.2

    解析結果をCSVへ出力する。
    Excel出力前の土台。
    """

    def write_all(self, analysis, out_dir: str | Path):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        self.write_score_judgments(analysis, out_dir / "score_judgments.csv")
        self.write_reviews(analysis, out_dir / "reviews.csv")
        self.write_pitcher_summary(analysis, out_dir / "pitcher_summary.csv")
        self.write_play_debug(analysis, out_dir / "play_debug.csv")
        self.write_runner_history(analysis, out_dir / "runner_history.csv")
        self.write_pitcher_changes(analysis, out_dir / "pitcher_changes.csv")
        self.write_debug_trace(analysis, out_dir / "debug_trace.csv")
        self.write_pitcher_runtime_debug(analysis, out_dir / "pitcher_runtime_debug.csv")

    def write_score_judgments(self, analysis, path: Path):
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["半イニング", "点目", "走者", "判定", "理由", "信頼度"])
            for half in analysis.halves:
                for j in half.compare_result.judgments:
                    w.writerow([
                        half.title,
                        j.score_no,
                        j.runner_text,
                        j.judgment,
                        j.reason,
                        j.confidence,
                    ])

    def write_reviews(self, analysis, path: Path):
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["半イニング", "レベル", "場所", "内容", "提案", "信頼度"])
            for half in analysis.halves:
                for item in half.review_result.items:
                    w.writerow([
                        half.title,
                        item.level,
                        item.location,
                        item.message,
                        item.suggestion,
                        item.confidence,
                    ])

    def write_pitcher_summary(self, analysis, path: Path):
        # Beta1.4: runner_historyをもとに責任投手別に集計
        summary = {}

        for half in analysis.halves:
            # 判定がついた得点走者をrunner_textから責任投手へ寄せる
            runner_pitcher = {}
            for row in getattr(half.actual_report, "runner_history", []):
                parts = row.split(",", 7)
                if len(parts) == 8:
                    runner_id, name, pitcher, cause, eligible, status, base, hist = parts
                    runner_pitcher[runner_id] = pitcher

            for j in half.compare_result.judgments:
                runner_id = ""
                if ":" in j.runner_text:
                    runner_id = j.runner_text.split(":", 1)[0].strip()
                pitcher = runner_pitcher.get(runner_id, "不明")

                if pitcher not in summary:
                    summary[pitcher] = {"失点": 0, "自責": 0, "非自責": 0, "自責候補": 0}

                summary[pitcher]["失点"] += 1
                if j.judgment == "非自責点":
                    summary[pitcher]["非自責"] += 1
                elif j.judgment == "自責点":
                    summary[pitcher]["自責"] += 1
                else:
                    summary[pitcher]["自責候補"] += 1

        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["投手", "失点", "自責", "非自責", "自責候補"])
            for pitcher, row in summary.items():
                w.writerow([pitcher, row["失点"], row["自責"], row["非自責"], row["自責候補"]])

    def write_play_debug(self, analysis, path: Path):
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["半イニング", "種別", "No", "本文", "Before", "Moves/Notes", "After"])

            for half in analysis.halves:
                for pr in half.actual_report.plays:
                    w.writerow([
                        half.title,
                        "Actual",
                        pr.seq,
                        pr.raw_text,
                        f"{pr.before_text} / {pr.outs_before}死",
                        " | ".join(pr.moves_text),
                        f"{pr.after_text} / {pr.outs_after}死",
                    ])

                for pr in half.virtual_report.plays:
                    w.writerow([
                        half.title,
                        "Virtual",
                        pr.seq,
                        pr.raw_text,
                        f"{pr.before_text} / {pr.outs_before}死",
                        " | ".join(pr.notes + pr.moves_text),
                        f"{pr.after_text} / {pr.outs_after}死",
                    ])


    def write_runner_history(self, analysis, path: Path):
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["半イニング", "RunnerID", "氏名", "責任投手", "出塁原因", "自責対象", "状態", "最終塁", "履歴"])
            for half in analysis.halves:
                for row in getattr(half.actual_report, "runner_history", []):
                    parts = row.split(",", 7)
                    if len(parts) == 8:
                        w.writerow([half.title] + parts)


    def write_pitcher_changes(self, analysis, path: Path):
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["半イニング", "Seq", "旧投手", "新投手", "原文"])
            for half in analysis.halves:
                for row in getattr(half.actual_report, "pitcher_changes", []):
                    parts = row.split(",", 3)
                    if len(parts) == 4:
                        w.writerow([half.title] + parts)


    def write_debug_trace(self, analysis, path: Path):
        from src.pitcher.pitcher_state import report_state_simple_text
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Inning", "Seq", "Event", "Actual", "Team Virtual", "Pitcher Virtual", "Δ"])
            for half in analysis.halves:
                title = self._clean_half_title(half.title)
                w.writerow([f"── {title} ──", "", "", "", "", "", ""])

                actual_by_seq = {getattr(p, "seq", None): p for p in getattr(half.actual_report, "plays", [])}
                virtual_by_seq = {getattr(p, "seq", None): p for p in getattr(half.virtual_report, "plays", [])}
                pitcher_changes = {}
                for row in getattr(half.actual_report, "pitcher_changes", []):
                    parts = row.split(",", 3)
                    if len(parts) == 4:
                        try:
                            pitcher_changes[int(parts[0])] = parts
                        except Exception:
                            pass
                seqs = sorted({s for s in set(actual_by_seq) | set(virtual_by_seq) | set(pitcher_changes) if s is not None})

                last_actual = ""
                last_virtual = ""
                for seq in seqs:
                    ap = actual_by_seq.get(seq)
                    vp = virtual_by_seq.get(seq)
                    if seq in pitcher_changes and not ap and not vp:
                        w.writerow([title, seq, "投手交代", last_actual, last_virtual, last_virtual, "責任投手更新"])
                        continue
                    src = ap or vp
                    event = self._short_event(getattr(src, "raw_text", ""))
                    actual = report_state_simple_text(getattr(ap, "after_text", ""), getattr(ap, "outs_after", 0)) if ap else last_actual
                    virtual = report_state_simple_text(getattr(vp, "after_text", ""), getattr(vp, "outs_after", 0)) if vp else last_virtual
                    delta = self._delta(ap, vp)
                    w.writerow([title, seq, event, actual, virtual, virtual, delta])
                    last_actual = actual or last_actual
                    last_virtual = virtual or last_virtual

    def write_pitcher_runtime_debug(self, analysis, path: Path):
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Half", "Mode", "Seq", "Event", "Current Pitcher", "Pitcher Virtual", "Virtual Outs", "Responsible Runner Count", "Inherited Runner Count", "Note"])
            for half in analysis.halves:
                for mode, report in [("Actual", half.actual_report), ("Virtual", half.virtual_report)]:
                    for row in getattr(report, "pitcher_runtime_debug", []):
                        parts = row.split(",", 7)
                        if len(parts) == 8:
                            w.writerow([self._clean_half_title(half.title), mode] + parts)

    def _clean_half_title(self, title: str) -> str:
        return str(title or "").replace("Actual ", "").replace("Virtual ", "")

    def _short_event(self, line: str) -> str:
        from src.event.event_labeler import short_event_label
        return short_event_label(line)
    def _delta(self, ap, vp) -> str:
        items = []
        if vp is not None:
            try:
                diff = int(getattr(vp, "outs_after", 0) or 0) - int(getattr(vp, "outs_before", 0) or 0)
            except Exception:
                diff = 0
            if diff > 0:
                items.append(f"Virtual Out +{diff}")
            if getattr(vp, "scored_text", []):
                items.append("Runner Score")
        if ap is not None and getattr(ap, "scored_text", []):
            if "Runner Score" not in items:
                items.append("Runner Score")
        if ap is not None:
            before = str(getattr(ap, "before_text", ""))
            after = str(getattr(ap, "after_text", ""))
            if before != after and "Runner Score" not in items:
                if "一塁[空]" in before and "一塁[空]" not in after:
                    items.append("Runner Add")
                else:
                    items.append("Runner Advance")
        return "\n".join(items)
