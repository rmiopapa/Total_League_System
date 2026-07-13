from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
import shutil
import subprocess
import sys

from src.fetch.easyscore_fetcher import EasyScoreTextFetcher
from src.game.day_runner import DayRunner, DayAnalysis
from src.report.day_xlsx_reporter import DayXlsxReporter
from src.debug.debug_reporter import DebugReporter
from src.event.score_event_builder import ScoreEventBuilder
from src.regression.correct_case_saver import CorrectCaseSaver
from src.regression.regression_case_runner import RegressionCaseRunner
from src.version import APP_NAME, VERSION


GAMES_DIR = Path("games")
HTML_CACHE_DIR = Path("html_cache")
REPORTS_DIR = Path("reports")
URL_TMP = Path("urls") / "_review_window_urls.txt"


class PhoenixReviewWindow:
    def __init__(self, developer_mode: bool = False):
        self.developer_mode = developer_mode
        self.root = tk.Tk()
        suffix = "Developer" if developer_mode else "User"
        self.root.title(f"{VERSION} - {suffix}")
        self.root.geometry("1180x820" if developer_mode else "1040x720")
        self.root.minsize(980, 680)
        try:
            self.root.state("zoomed")
        except tk.TclError:
            self.root.attributes("-zoomed", True)

        # V2.5.1: 実運用で見やすいように12ポイント中心に統一
        self.default_font = ("Yu Gothic UI", 12)
        self.bold_font = ("Yu Gothic UI", 12, "bold")
        self.small_font = ("Yu Gothic UI", 11)

        style = ttk.Style()
        style.configure(".", font=self.default_font)
        style.configure("Treeview", font=self.default_font, rowheight=30)
        style.configure("Treeview.Heading", font=self.bold_font)
        style.configure("TButton", font=self.default_font)
        style.configure("TCheckbutton", font=self.default_font)
        style.configure("TLabel", font=self.default_font)

        self.day = None
        self.save_vars: dict[int, tk.BooleanVar] = {}

        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="EasyScore テキスト速報URL（1～3試合）", font=self.bold_font).pack(anchor="w")

        self.url_entries = []
        for i in range(3):
            row = ttk.Frame(top)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=f"第{i+1}試合", width=8).pack(side="left")
            ent = ttk.Entry(row)
            ent.pack(side="left", fill="x", expand=True)
            self.url_entries.append(ent)

        btns = ttk.Frame(top)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="解析する", command=self.analyze).pack(side="left")
        if self.developer_mode:
            ttk.Button(btns, text="GoldData保存", command=self.save_selected).pack(side="left", padx=8)
            ttk.Button(btns, text="保存済み正解データを検証（Team/Pitcher）", command=self.run_saved_regression).pack(side="left", padx=8)

            btns2 = ttk.Frame(top)
            btns2.pack(fill="x", pady=(6, 0))
            ttk.Button(btns2, text="DebugReport表示", command=self.open_debug_report).pack(side="left")

        self.status = tk.StringVar(value=("Developer Mode：解析するとDebugReportを自動保存します。保存・検証も実行できます。" if self.developer_mode else "URLを入力して［解析する］を押してください。"))
        ttk.Label(top, textvariable=self.status).pack(anchor="w", pady=(8, 0))

        # V2.5.2:
        # 保存対象の試合選択は、判定一覧の下ではなく上に固定表示する。
        # 画面サイズが小さくてもチェック欄が隠れない。
        self.check_frame = ttk.LabelFrame(self.root, text=("保存対象試合" if self.developer_mode else "解析対象試合"), padding=10)
        if self.developer_mode:
            self.check_frame.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(
            self.check_frame,
            text="解析後、GoldDataとして保存したい試合にチェックを入れてください。\n※責任投手検証用データも同じRCフォルダへ自動保存します。",
            font=self.small_font,
        ).pack(anchor="w")

        self.check_items_frame = ttk.Frame(self.check_frame)
        self.check_items_frame.pack(fill="x", pady=(4, 0))

        # Main display
        main = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        main.pack(fill="both", expand=True)

        columns = ("game", "location", "judgment", "reason", "runner")
        self.tree = ttk.Treeview(main, columns=columns, show="headings", height=14)
        self.tree.heading("game", text="試合")
        self.tree.heading("location", text="場所")
        self.tree.heading("judgment", text="判定")
        self.tree.heading("reason", text="責任投手/理由・比較")
        self.tree.heading("runner", text="走者")

        self.tree.column("game", width=220)
        self.tree.column("location", width=130, anchor="center")
        self.tree.column("judgment", width=110, anchor="center")
        self.tree.column("reason", width=240, anchor="center")
        self.tree.column("runner", width=390)

        yscroll = ttk.Scrollbar(main, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="left", fill="y")

        memo_frame = ttk.LabelFrame(self.root, text="保存メモ（任意）", padding=10)
        memo_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.memo = tk.Text(memo_frame, height=3, font=self.default_font)
        self.memo.pack(fill="x")

    def analyze(self):
        urls = [e.get().strip() for e in self.url_entries if e.get().strip()]
        if not urls:
            messagebox.showwarning("URL未入力", "少なくとも1試合分のURLを入力してください。")
            return

        try:
            self._clear_work_dirs()
            URL_TMP.parent.mkdir(exist_ok=True)
            URL_TMP.write_text("\n".join(urls[:3]) + "\n", encoding="utf-8")

            self.status.set("HTML取得・解析中です...")
            self.root.update_idletasks()

            fetcher = EasyScoreTextFetcher()
            fetcher.fetch_urls_file(URL_TMP, GAMES_DIR, limit=3)

            self.day = DayRunner().run_folder(GAMES_DIR, pitcher="P", limit=3)

            REPORTS_DIR.mkdir(exist_ok=True)
            DayXlsxReporter().write(self.day, REPORTS_DIR / "daily_check.xlsx")
            if self.developer_mode:
                DebugReporter().write(self.day, REPORTS_DIR / "debug_report.xlsx")

            self._populate_results()
            suffix = " / DebugReport自動生成済" if self.developer_mode else ""
            self.status.set(
                f"解析完了：{self.day.total_games}試合 / 得点 {self.day.total_scores} / 補正対象 {self.day.total_work_items}{suffix}"
            )
        except Exception as e:
            messagebox.showerror("解析エラー", str(e))
            self.status.set("解析エラーが発生しました。")

    def _clear_work_dirs(self):
        GAMES_DIR.mkdir(exist_ok=True)
        for p in GAMES_DIR.glob("*.txt"):
            p.unlink()
        HTML_CACHE_DIR.mkdir(exist_ok=True)
        for p in HTML_CACHE_DIR.glob("*.html"):
            p.unlink()

    def _populate_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for child in self.check_items_frame.winfo_children():
            child.destroy()
        self.save_vars.clear()

        if not self.day:
            return

        builder = ScoreEventBuilder()

        for game in self.day.games:
            var = tk.BooleanVar(value=False)
            self.save_vars[game.game_no] = var
            ttk.Checkbutton(
                self.check_items_frame,
                text=f"第{game.game_no}試合：{game.game_name}",
                variable=var,
            ).pack(side="left", padx=(0, 18), pady=2)

            team_events = builder.build_for_game(game, judgment_source="team")
            events = builder.build_for_game(game, judgment_source="pitcher")
            if not events:
                self.tree.insert("", "end", values=(game.game_name, "得点なし", "", "", ""))
            for ev in events:
                self.tree.insert(
                    "",
                    "end",
                    values=(game.game_name, ev.location, builder.label(ev.judgment), ev.reason, ev.runner),
                )

            # WARN/ERRORも画面表示
            if self.developer_mode:
                self._append_team_pitcher_comparison(game, team_events, events)

            for half in game.analysis.halves:
                for item in half.review_result.items:
                    if item.level in {"WARN", "ERROR"}:
                        loc = item.location
                        if loc.startswith("Actual #") or loc.startswith("Virtual #"):
                            loc = half.title
                        self.tree.insert(
                            "",
                            "end",
                            values=(game.game_name, loc, item.level, item.message, ""),
                        )

    def save_selected(self):
        if not self.day:
            messagebox.showwarning("未解析", "先に解析してください。")
            return

        selected = self._selected_game_nos()
        if not selected:
            messagebox.showwarning("未選択", "保存する試合にチェックを入れてください。")
            return

        memo = self.memo.get("1.0", "end").strip()
        try:
            saved = CorrectCaseSaver().save_day(
                self.day,
                GAMES_DIR,
                REPORTS_DIR / "daily_check.xlsx",
                memo=memo,
                html_cache_dir=HTML_CACHE_DIR,
                selected_game_nos=selected,
            )
            messagebox.showinfo("保存完了", "GoldDataとして保存しました。\nPitcherGoldDataも同じRCフォルダへ保存済みです。\n\n" + "\n".join(str(p) for p in saved))
            self.status.set(f"保存完了：{len(saved)}試合（Team/Pitcher）")
        except Exception as e:
            messagebox.showerror("保存エラー", str(e))


    def _append_team_pitcher_comparison(self, game, team_events, pitcher_events):
        """Developer UI: Team自責点と投手自責点合計を同じ一覧で確認する。"""
        team_runs = len(team_events)
        team_earned = sum(1 for ev in team_events if ev.judgment == "自責点")
        by_pitcher: dict[str, dict[str, int]] = {}
        for ev in pitcher_events:
            pitcher = ev.charged_pitcher or "(責任投手不明)"
            by_pitcher.setdefault(pitcher, {"runs": 0, "earned": 0})
            by_pitcher[pitcher]["runs"] += 1
            if ev.judgment == "自責点":
                by_pitcher[pitcher]["earned"] += 1
        pitcher_runs = sum(v["runs"] for v in by_pitcher.values())
        pitcher_earned = sum(v["earned"] for v in by_pitcher.values())
        status = "PASS" if (team_runs == pitcher_runs and team_earned == pitcher_earned) else "DIFF"
        self.tree.insert(
            "", "end",
            values=(game.game_name, "Team/Pitcher比較", status, f"Team ER {team_earned} / Pitcher ER {pitcher_earned}", f"Team R {team_runs} / Pitcher R {pitcher_runs}"),
        )
        for pitcher, v in sorted(by_pitcher.items()):
            self.tree.insert(
                "", "end",
                values=(game.game_name, "投手別", pitcher, f"失点 {v['runs']} / 自責 {v['earned']}", ""),
            )

    def run_stable_gate(self):
        try:
            self.status.set("StableGate実行中です...")
            self.root.update_idletasks()
            runner = RegressionCaseRunner()
            team = runner.run_golddata98(pitcher="P")
            pitcher = runner.run_pitcher_golddata17(pitcher="P")
            result = {
                "team": team,
                "pitcher": pitcher,
                "passed": team.get("failed", 0) == 0 and pitcher.get("failed", 0) == 0,
            }
            self._populate_stable_gate_results(result)
            status = "PASS" if result["passed"] else "FAIL"
            self.status.set(
                f"StableGate {status}：GoldData {team['passed']}/{team['total']}、PitcherGoldData {pitcher['passed']}/{pitcher['total']}"
            )
        except Exception as e:
            messagebox.showerror("StableGateエラー", str(e))
            self.status.set("StableGateエラーが発生しました。")

    def _populate_stable_gate_results(self, result: dict):
        for item in self.tree.get_children():
            self.tree.delete(item)
        team = result.get("team", {})
        pitcher = result.get("pitcher", {})
        status = "PASS" if result.get("passed") else "FAIL"
        self.tree.insert("", "end", values=("保存済み正解データ検証", "総合", status, "GoldData / PitcherGoldData", f"Version {VERSION}"))
        self.tree.insert("", "end", values=("GoldData", "全RCフォルダ", "PASS" if team.get("failed") == 0 else "FAIL", f"{team.get('passed')}/{team.get('total')}", "Team判定"))
        self.tree.insert("", "end", values=("PitcherGoldData", "全RCフォルダ", "PASS" if pitcher.get("failed") == 0 else "FAIL", f"{pitcher.get('passed')}/{pitcher.get('total')}", "責任投手判定"))
        for group_name, group in [("GoldData", team), ("PitcherGoldData", pitcher)]:
            for r in group.get("results", []):
                if r.get("passed"):
                    continue
                self.tree.insert("", "end", values=(group_name, r.get("case", ""), "FAIL", r.get("message", "差分あり"), f"missing={r.get('missing')} extra={r.get('extra')}"))


    def _selected_game_nos(self) -> list[int]:
        return [no for no, var in self.save_vars.items() if var.get()]

    def _selected_day(self) -> DayAnalysis:
        selected = set(self._selected_game_nos())
        day = DayAnalysis()
        if self.day:
            day.games = [g for g in self.day.games if g.game_no in selected]
        return day

    def create_debug_report_selected(self):
        if not self.day:
            messagebox.showwarning("未解析", "先に解析してください。")
            return

        selected = self._selected_game_nos()
        if not selected:
            messagebox.showwarning("未選択", "DebugReportを作成する試合にチェックを入れてください。")
            return

        try:
            REPORTS_DIR.mkdir(exist_ok=True)
            selected_day = self._selected_day()
            out = DebugReporter().write(selected_day, REPORTS_DIR / "debug_report.xlsx")
            self.status.set(f"DebugReport作成完了：{out}")
            messagebox.showinfo("DebugReport作成完了", f"DebugReportを作成しました。\n\n{out}")
        except Exception as e:
            messagebox.showerror("DebugReport作成エラー", str(e))

    def open_debug_report(self):
        path = REPORTS_DIR / "debug_report.xlsx"
        if not path.exists():
            messagebox.showwarning("未作成", "reports/debug_report.xlsx がまだありません。先にDebugReportを作成してください。")
            return
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("DebugReport表示エラー", str(e))

    def run_saved_regression(self):
        """
        保存済み正解データを検証する。

        V3.0 Stable Finalでは、開発者向けUIの検証ボタンは
        GoldData（Team判定）とPitcherGoldData（責任投手判定）の
        両方を一括で確認する。
        """
        try:
            self.status.set("保存済み正解データ検証中です...（GoldData / PitcherGoldData）")
            self.root.update_idletasks()

            runner = RegressionCaseRunner()
            team = runner.run_golddata98(pitcher="P")
            pitcher = runner.run_pitcher_golddata17(pitcher="P")
            result = {
                "team": team,
                "pitcher": pitcher,
                "passed": team.get("failed", 0) == 0 and pitcher.get("failed", 0) == 0,
            }
            self._populate_stable_gate_results(result)

            status = "PASS" if result["passed"] else "FAIL"
            self.status.set(
                f"保存済み正解データ検証 {status}："
                f"GoldData {team['passed']}/{team['total']}、"
                f"PitcherGoldData {pitcher['passed']}/{pitcher['total']}"
            )
        except Exception as e:
            messagebox.showerror("検証エラー", str(e))
            self.status.set("保存済み正解データ検証エラーが発生しました。")

    def _populate_regression_results(self, result: dict):
        for item in self.tree.get_children():
            self.tree.delete(item)

        total = result.get("total", 0)
        passed = result.get("passed", 0)
        failed = result.get("failed", 0)

        self.tree.insert(
            "",
            "end",
            values=(
                "GoldData検証",
                f"検証総数 {total}",
                f"PASS {passed}",
                f"エラー {failed}",
                "",
            ),
        )

        if failed == 0:
            return

        for r in result.get("results", []):
            if r.get("passed"):
                continue

            case_name = r.get("case", "不明")
            message = r.get("message")
            if message:
                self.tree.insert(
                    "",
                    "end",
                    values=(case_name, "ERROR", "検証不可", message, ""),
                )
                continue

            missing = r.get("missing") or []
            extra = r.get("extra") or []

            if missing:
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        case_name,
                        "ERROR",
                        "不足",
                        "expectedにある得点判定がactualにありません",
                        str(missing),
                    ),
                )

            if extra:
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        case_name,
                        "ERROR",
                        "余分",
                        "actualに余分な得点判定があります",
                        str(extra),
                    ),
                )

    def run(self):
        self.root.mainloop()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true", help="開発者向けUIで起動")
    args = parser.parse_args()
    PhoenixReviewWindow(developer_mode=args.dev).run()


if __name__ == "__main__":
    main()
