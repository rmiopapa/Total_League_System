from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import customtkinter as ctk

from src.config import GOLDDATA_EXCLUDED_CASES, NEO_JUDGMENT_EXCLUDED_CASES
from src.debug.debug_reporter import DebugReporter
from src.event.score_event_builder import ScoreEventBuilder
from src.fetch.easyscore_fetcher import EasyScoreTextFetcher
from src.game.day_runner import DayAnalysis
from src.neo.game_runner import NeoDayRunner
from src.regression.correct_case_saver import CorrectCaseSaver
from src.report.day_xlsx_reporter import DayXlsxReporter
from src.tools import neo_judgment_gate, neo_pitcher_gate
from src.version import VERSION


GAMES_DIR = Path("games")
HTML_CACHE_DIR = Path("html_cache")
REPORTS_DIR = Path("reports")
URL_TMP = Path("urls") / "_review_window_urls.txt"
APP_FONT = "Yu Gothic UI"
APP_FONT_SIZE = 18


class NeoPhoenixCTkWindow:
    def __init__(self, developer_mode: bool = False):
        self.developer_mode = developer_mode
        self.day = None
        self.save_vars: dict[int, tk.BooleanVar] = {}

        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        suffix = "Developer" if developer_mode else "User"
        self.root.title(f"NeoPhoenix {VERSION} - {suffix}")
        self.root.geometry("1280x860")
        self.root.minsize(1100, 720)
        self._set_icon()
        self.root.after(100, self._maximize)

        self.font = ctk.CTkFont(family=APP_FONT, size=APP_FONT_SIZE)
        self.bold_font = ctk.CTkFont(family=APP_FONT, size=APP_FONT_SIZE, weight="bold")
        self.small_font = ctk.CTkFont(family=APP_FONT, size=16)
        self.status = tk.StringVar(value="URLを入力して解析してください。")

        self._configure_tree_style()
        self._build_ui()

    def _set_icon(self):
        icon = Path("Phoenix.ico")
        if icon.exists():
            try:
                self.root.iconbitmap(str(icon))
            except Exception:
                pass

    def _maximize(self):
        try:
            self.root.state("zoomed")
        except tk.TclError:
            try:
                self.root.attributes("-zoomed", True)
            except tk.TclError:
                pass

    def _configure_tree_style(self):
        style = ttk.Style()
        style.configure(".", font=(APP_FONT, APP_FONT_SIZE))
        style.configure("Treeview", font=(APP_FONT, APP_FONT_SIZE), rowheight=38)
        style.configure("Treeview.Heading", font=(APP_FONT, APP_FONT_SIZE, "bold"))

    def _build_ui(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self.root, corner_radius=0)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        top.grid_columnconfigure(1, weight=1)

        title = "EasyScore 一球速報URL"
        ctk.CTkLabel(top, text=title, font=self.bold_font).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 6))

        self.url_entries: list[ctk.CTkEntry] = []
        for i in range(3):
            ctk.CTkLabel(top, text=f"第{i + 1}試合", font=self.font, width=90).grid(row=i + 1, column=0, sticky="w", padx=10, pady=4)
            entry = ctk.CTkEntry(top, font=self.font, height=40)
            entry.grid(row=i + 1, column=1, sticky="ew", padx=10, pady=4)
            self.url_entries.append(entry)

        buttons = ctk.CTkFrame(top, fg_color="transparent")
        buttons.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkButton(buttons, text="解析する", font=self.bold_font, height=42, command=self.analyze).pack(side="left", padx=(0, 10))
        if self.developer_mode:
            ctk.CTkButton(buttons, text="GoldData保存", font=self.bold_font, height=42, command=self.save_selected).pack(side="left", padx=10)
            ctk.CTkButton(buttons, text="保存済み正解データ検証", font=self.bold_font, height=42, command=self.run_saved_regression).pack(side="left", padx=10)
            ctk.CTkButton(buttons, text="DebugReport作成", font=self.bold_font, height=42, command=self.create_debug_report_selected).pack(side="left", padx=10)
            ctk.CTkButton(buttons, text="DebugReport表示", font=self.bold_font, height=42, command=self.open_debug_report).pack(side="left", padx=10)

        ctk.CTkLabel(top, textvariable=self.status, font=self.small_font, anchor="w").grid(
            row=5, column=0, columnspan=2, sticky="ew", padx=10, pady=(6, 10)
        )

        self.check_frame = ctk.CTkFrame(self.root)
        if self.developer_mode:
            self.check_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
            self.check_frame.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(self.check_frame, text="保存対象試合", font=self.bold_font).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))
            self.check_items_frame = ctk.CTkFrame(self.check_frame, fg_color="transparent")
            self.check_items_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        else:
            self.check_items_frame = ctk.CTkFrame(self.root)

        main = ctk.CTkFrame(self.root)
        main.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        columns = ("game", "location", "judgment", "reason", "runner")
        self.tree = ttk.Treeview(main, columns=columns, show="headings")
        headings = {
            "game": "試合",
            "location": "場所",
            "judgment": "判定",
            "reason": "責任投手/理由",
            "runner": "走者",
        }
        widths = {"game": 280, "location": 150, "judgment": 130, "reason": 300, "runner": 520}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center" if col != "runner" else "w")
        yscroll = ttk.Scrollbar(main, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(main, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        memo_frame = ctk.CTkFrame(self.root)
        memo_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        memo_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(memo_frame, text="保存メモ", font=self.bold_font).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        self.memo = ctk.CTkTextbox(memo_frame, font=self.font, height=100)
        self.memo.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))

    def analyze(self):
        urls = [entry.get().strip() for entry in self.url_entries if entry.get().strip()]
        if not urls:
            messagebox.showwarning("URL未入力", "少なくとも1試合分のURLを入力してください。")
            return
        try:
            self._clear_work_dirs()
            URL_TMP.parent.mkdir(exist_ok=True)
            URL_TMP.write_text("\n".join(urls[:3]) + "\n", encoding="utf-8")
            self.status.set("HTML取得とNeo解析を実行中...")
            self.root.update_idletasks()

            EasyScoreTextFetcher().fetch_urls_file(URL_TMP, GAMES_DIR, limit=3)
            self.day = NeoDayRunner().run_folder(GAMES_DIR, pitcher="P", limit=3)

            REPORTS_DIR.mkdir(exist_ok=True)
            DayXlsxReporter().write(self.day, REPORTS_DIR / "daily_check.xlsx")
            if self.developer_mode:
                DebugReporter().write(self.day, REPORTS_DIR / "debug_report.xlsx")

            self._populate_results()
            suffix = " / DebugReport自動生成済み" if self.developer_mode else ""
            self.status.set(
                f"解析完了: {self.day.total_games}試合 / 得点 {self.day.total_scores} / 確認対象 {self.day.total_work_items}{suffix}"
            )
        except Exception as exc:
            messagebox.showerror("解析エラー", str(exc))
            self.status.set("解析エラーが発生しました。")

    def _clear_work_dirs(self):
        GAMES_DIR.mkdir(exist_ok=True)
        for path in GAMES_DIR.glob("*.txt"):
            path.unlink()
        HTML_CACHE_DIR.mkdir(exist_ok=True)
        for path in HTML_CACHE_DIR.glob("*.html"):
            path.unlink()

    def _populate_results(self):
        self._clear_tree()
        self._clear_checks()
        if not self.day:
            return
        builder = ScoreEventBuilder()
        for game in self.day.games:
            if self.developer_mode:
                var = tk.BooleanVar(value=False)
                self.save_vars[game.game_no] = var
                ctk.CTkCheckBox(
                    self.check_items_frame,
                    text=f"第{game.game_no}試合: {game.game_name}",
                    variable=var,
                    font=self.font,
                ).pack(side="left", padx=(0, 18), pady=4)

            team_events = builder.build_for_game(game, judgment_source="team")
            pitcher_events = builder.build_for_game(game, judgment_source="pitcher")
            if not pitcher_events:
                self.tree.insert("", "end", values=(game.game_name, "得点なし", "", "", ""))
            for ev in pitcher_events:
                self.tree.insert("", "end", values=(game.game_name, ev.location, builder.label(ev.judgment), ev.reason, ev.runner))
            if self.developer_mode:
                self._append_team_pitcher_comparison(game, team_events, pitcher_events)
            for half in game.analysis.halves:
                for item in half.review_result.items:
                    if item.level in {"WARN", "ERROR"}:
                        loc = half.title if item.location.startswith(("Actual #", "Virtual #")) else item.location
                        self.tree.insert("", "end", values=(game.game_name, loc, item.level, item.message, ""))

    def _append_team_pitcher_comparison(self, game, team_events, pitcher_events):
        team_earned = sum(1 for ev in team_events if ev.judgment == "自責点")
        by_pitcher: dict[str, dict[str, int]] = {}
        for ev in pitcher_events:
            pitcher = ev.charged_pitcher or "(責任投手不明)"
            by_pitcher.setdefault(pitcher, {"runs": 0, "earned": 0})
            by_pitcher[pitcher]["runs"] += 1
            if ev.judgment == "自責点":
                by_pitcher[pitcher]["earned"] += 1
        pitcher_earned = sum(row["earned"] for row in by_pitcher.values())
        status = "PASS" if (len(team_events), team_earned) == (len(pitcher_events), pitcher_earned) else "DIFF"
        self.tree.insert("", "end", values=(game.game_name, "Team/Pitcher比較", status, f"Team ER {team_earned} / Pitcher ER {pitcher_earned}", ""))
        for pitcher, row in sorted(by_pitcher.items()):
            self.tree.insert("", "end", values=(game.game_name, "投手別", pitcher, f"失点 {row['runs']} / 自責 {row['earned']}", ""))
        self.tree.insert("", "end", values=(game.game_name, "Neo output", "INFO", "Screen rows use Neo Pitcher judgment; DebugReport uses Neo Team/Pitcher traces.", ""))

    def save_selected(self):
        if not self.day:
            messagebox.showwarning("未解析", "先に解析してください。")
            return
        selected = self._selected_game_nos()
        if not selected:
            messagebox.showwarning("未選択", "保存する試合にチェックを入れてください。")
            return
        try:
            memo = self.memo.get("1.0", "end").strip()
            saved = CorrectCaseSaver().save_day(
                self.day,
                GAMES_DIR,
                REPORTS_DIR / "daily_check.xlsx",
                memo=memo,
                html_cache_dir=HTML_CACHE_DIR,
                selected_game_nos=selected,
            )
            messagebox.showinfo("保存完了", "GoldDataとして保存しました。\n\n" + "\n".join(str(path) for path in saved))
            self.status.set(f"保存完了: {len(saved)}試合")
        except Exception as exc:
            messagebox.showerror("保存エラー", str(exc))

    def run_saved_regression(self):
        try:
            self.status.set("Neo保存済み正解データ検証中...")
            self.root.update_idletasks()
            team = neo_judgment_gate.run(Path("regression_cases"), limit_cases=20, limit_diffs=5)
            pitcher = neo_pitcher_gate.run(Path("regression_cases"), limit_cases=20)
            passed = team.get("different", 0) == 0 and pitcher.get("failed", 0) == 0
            self._populate_neo_gate_results(team, pitcher, passed)
            self.status.set(
                f"Neo Gate {'PASS' if passed else 'FAIL'}: Team {team.get('matched', 0)}/{team.get('total', 0)}, "
                f"Pitcher {pitcher.get('passed', 0)}/{pitcher.get('total', 0)}"
            )
        except Exception as exc:
            messagebox.showerror("Neo Gate Error", str(exc))
            self.status.set("Neo Gate error.")

    def _populate_neo_gate_results(self, team: dict, pitcher: dict, passed: bool):
        self._clear_tree()
        excluded = sorted(GOLDDATA_EXCLUDED_CASES | NEO_JUDGMENT_EXCLUDED_CASES)
        self.tree.insert("", "end", values=("Neo saved GoldData gate", "Summary", "PASS" if passed else "FAIL", f"Excluded: {', '.join(excluded) if excluded else '-'}", f"Version {VERSION}"))
        self.tree.insert("", "end", values=("Neo Team", "regression_cases", "PASS" if team.get("different", 0) == 0 else "FAIL", f"{team.get('matched', 0)}/{team.get('total', 0)}", f"missing={team.get('missing', 0)} extra={team.get('extra', 0)}"))
        self.tree.insert("", "end", values=("Neo Pitcher", "regression_cases", "PASS" if pitcher.get("failed", 0) == 0 else "FAIL", f"{pitcher.get('passed', 0)}/{pitcher.get('total', 0)}", ""))
        for sample in team.get("samples", []):
            self.tree.insert("", "end", values=("Neo Team", sample.get("case", ""), "FAIL", str(sample), ""))
        for sample in pitcher.get("samples", []):
            self.tree.insert("", "end", values=("Neo Pitcher", sample.get("case", ""), "FAIL", str(sample.get("team_diff") or sample.get("pitcher_diff") or ""), ""))

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
            out = DebugReporter().write(self._selected_day(), REPORTS_DIR / "debug_report.xlsx")
            self.status.set(f"DebugReport作成完了: {out}")
            messagebox.showinfo("DebugReport作成完了", f"DebugReportを作成しました。\n\n{out}")
        except Exception as exc:
            messagebox.showerror("DebugReport作成エラー", str(exc))

    def open_debug_report(self):
        path = REPORTS_DIR / "debug_report.xlsx"
        if not path.exists():
            messagebox.showwarning("未作成", "reports/debug_report.xlsx がまだありません。")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showerror("DebugReport表示エラー", str(exc))

    def _selected_game_nos(self) -> list[int]:
        return [no for no, var in self.save_vars.items() if var.get()]

    def _selected_day(self) -> DayAnalysis:
        selected = set(self._selected_game_nos())
        day = DayAnalysis()
        if self.day:
            day.games = [game for game in self.day.games if game.game_no in selected]
        return day

    def _clear_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _clear_checks(self):
        for child in self.check_items_frame.winfo_children():
            child.destroy()
        self.save_vars.clear()

    def run(self):
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", action="store_true", help="start in developer mode")
    args = parser.parse_args()
    NeoPhoenixCTkWindow(developer_mode=args.dev).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
