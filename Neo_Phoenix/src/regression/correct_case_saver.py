from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from datetime import datetime
import json
import re
import shutil

from src.event.score_event_builder import ScoreEventBuilder


class CorrectCaseSaver:
    """
    Phoenix V2.4

    実運用で確認済みの判定結果を「正解データ」として保存する。
    保存したデータは、将来の回帰テストに使う。
    """

    def __init__(self, root: Path | str = "regression_cases"):
        self.root = Path(root)

    def save_day(self, day, games_dir: Path | str, report_path: Path | str, memo: str = "", html_cache_dir: Path | str = "html_cache", selected_game_nos: list[int] | None = None, include_pitcher_expected: bool = True) -> list[Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        games_dir = Path(games_dir)
        report_path = Path(report_path)
        html_cache_dir = Path(html_cache_dir)

        saved_dirs: list[Path] = []

        selected_set = set(selected_game_nos or [])
        for idx, game in enumerate(day.games, 1):
            if selected_set and idx not in selected_set:
                continue

            # Phoenix V2.6 stable:
            # GoldData は長い日時＋試合名ではなく、RC021, RC022 ... の連番で保存する。
            # 既存の regression_cases/RC001～RC020 を読んで、常に次番号を採番する。
            case_name = self._next_rc_name()
            case_dir = self.root / case_name
            case_dir.mkdir(parents=True, exist_ok=False)

            # 元txtを保存
            src_txt = self._find_game_txt(games_dir, game.game_name, idx)
            if src_txt and src_txt.exists():
                shutil.copy2(src_txt, case_dir / "sample.txt")

            # V2.4: 自動保存されたHTMLも保存
            src_html = self._find_game_html(html_cache_dir, game.game_name, idx)
            if src_html and src_html.exists():
                shutil.copy2(src_html, case_dir / "sample.html")

            # レポートを保存
            if report_path.exists():
                shutil.copy2(report_path, case_dir / "report.xlsx")

            # expected.json を保存
            expected = self._build_expected(game, memo=memo)
            (case_dir / "expected.json").write_text(
                json.dumps(expected, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # V3.1 Quality09:
            # GoldData保存時に責任投手検証データも同一RCフォルダへ保存する。
            # PitcherGoldData専用保存ボタンは廃止し、重複フォルダを作らない。
            if include_pitcher_expected:
                pitcher_expected = self._build_pitcher_expected(game, memo=memo)
                (case_dir / "pitcher_expected.json").write_text(
                    json.dumps(pitcher_expected, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            # メモ
            (case_dir / "memo.txt").write_text(memo or "確認済み。正解データとして保存。", encoding="utf-8")

            saved_dirs.append(case_dir)

        return saved_dirs


    def _next_rc_name(self) -> str:
        """Return next GoldData case name such as RC021.

        Only directory names exactly matching RC### are used for numbering.
        Old timestamp-style folders, if any, are ignored so they do not disturb
        the official RC sequence.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        max_no = 0
        pattern = re.compile(r"^RC(\d{3})$")
        for p in self.root.iterdir():
            if not p.is_dir():
                continue
            m = pattern.match(p.name)
            if m:
                max_no = max(max_no, int(m.group(1)))
        return f"RC{max_no + 1:03d}"

    def _build_expected(self, game, memo: str = "") -> dict:
        builder = ScoreEventBuilder()
        events = builder.build_for_game(game, judgment_source="team")

        return {
            "format": "PhoenixRegressionCaseV1",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "game": game.game_name,
            "memo": memo,
            "expected": [
                {
                    "inning": ev.half,
                    "score_no": ev.score_no,
                    "judgment": ev.judgment,
                    "label": builder.label(ev.judgment),
                    "reason": ev.reason,
                    "runner": ev.runner,
                }
                for ev in events
            ],
        }


    def _build_pitcher_expected(self, game, memo: str = "") -> dict:
        """投手別失点・自責点の正解候補を保存する。

        Team判定の expected.json は従来互換のまま維持し、
        PitcherGoldData用の責任投手集計だけを別ファイルにする。
        """
        builder = ScoreEventBuilder()
        events = builder.build_for_game(game, judgment_source="pitcher")
        by_pitcher: dict[str, dict[str, int]] = {}
        details = []
        for ev in events:
            pitcher = ev.charged_pitcher or "(責任投手不明)"
            by_pitcher.setdefault(pitcher, {"runs": 0, "earned": 0})
            by_pitcher[pitcher]["runs"] += 1
            if ev.judgment == "自責点":
                by_pitcher[pitcher]["earned"] += 1
            details.append({
                "inning": ev.half,
                "score_no": ev.score_no,
                "runner": ev.runner,
                "charged_pitcher": pitcher,
                "judgment": ev.judgment,
                "earned": 1 if ev.judgment == "自責点" else 0,
                "reason": ev.reason,
            })
        total_runs = sum(v["runs"] for v in by_pitcher.values())
        total_earned = sum(v["earned"] for v in by_pitcher.values())
        return {
            "format": "PhoenixPitcherRegressionCaseV1",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "game": game.game_name,
            "memo": memo,
            "team": {"runs": total_runs, "earned": total_earned},
            "pitchers": by_pitcher,
            "details": details,
        }

    def _find_game_txt(self, games_dir: Path, game_name: str, idx: int) -> Path | None:
        txts = sorted(games_dir.glob("*.txt"))
        if not txts:
            return None

        safe = self._safe_name(game_name)
        for p in txts:
            if safe in self._safe_name(p.stem):
                return p

        if 1 <= idx <= len(txts):
            return txts[idx - 1]
        return txts[0]


    def _find_game_html(self, html_cache_dir: Path, game_name: str, idx: int) -> Path | None:
        htmls = sorted(html_cache_dir.glob("*.html"))
        if not htmls:
            return None

        safe = self._safe_name(game_name)
        for p in htmls:
            if safe in self._safe_name(p.stem):
                return p

        if 1 <= idx <= len(htmls):
            return htmls[idx - 1]
        return htmls[0]

    def _safe_name(self, name: str) -> str:
        name = name or "game"
        name = name.replace("－", "_").replace("-", "_").replace(" vs ", "_").replace("vs", "_")
        name = re.sub(r'[\\/:*?"<>| \t\r\n]+', "_", name)
        name = re.sub(r"_+", "_", name).strip("_")
        return name[:80] or "game"
