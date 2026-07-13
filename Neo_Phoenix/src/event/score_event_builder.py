from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScoreEvent:
    game_name: str
    half: str
    score_no: int
    judgment: str
    reason: str
    runner: str
    confidence: str
    charged_pitcher: str = ""

    @property
    def location(self) -> str:
        return f"{self.half} {self.score_no}点目"


class ScoreEventBuilder:
    """
    V2.6 Sprint4.2

    CompareResultの得点判定を、帳票用ScoreEventへ変換する。
    Reviewの内部番号（Actual #など）はここには混ぜない。
    """

    def build_for_game(self, game, judgment_source: str = "team") -> list[ScoreEvent]:
        events: list[ScoreEvent] = []
        source = str(judgment_source or "team").lower()
        for half in game.analysis.halves:
            pitcher_by_runner = self.runner_pitcher_map(half)
            compare = getattr(half, "compare_result", None)
            if source == "pitcher":
                judgments = list(getattr(compare, "pitcher_judgments", []) or getattr(compare, "judgments", []) or [])
            else:
                judgments = list(getattr(compare, "team_judgments", []) or getattr(compare, "judgments", []) or [])
            for j in judgments:
                runner_id = self.runner_id(j.runner_text)
                charged_pitcher = pitcher_by_runner.get(runner_id, "")
                display_reason = charged_pitcher if j.judgment == "自責点" else self.short_reason(j.reason, j.runner_text, j.judgment)
                events.append(
                    ScoreEvent(
                        game_name=game.game_name,
                        half=half.title,
                        score_no=j.score_no,
                        judgment=j.judgment,
                        reason=display_reason,
                        runner=self.display_runner(j.runner_text),
                        confidence=str(j.confidence),
                        charged_pitcher=charged_pitcher,
                    )
                )
        return events


    def runner_id(self, runner_text: str) -> str:
        if not runner_text:
            return ""
        return str(runner_text).split(":", 1)[0].strip()

    def runner_pitcher_map(self, half) -> dict[str, str]:
        mapping = self.pitcher_display_map(half)
        out: dict[str, str] = {}
        for line in getattr(getattr(half, "actual_report", None), "runner_history", []) or []:
            parts = str(line).split(",", 7)
            if len(parts) >= 3:
                out[parts[0]] = self.display_pitcher(parts[2], mapping)
        return out

    def pitcher_display_map(self, half) -> dict[str, str]:
        mapping: dict[str, str] = {}
        first_old = ""
        for row in getattr(getattr(half, "actual_report", None), "pitcher_changes", []) or []:
            parts = str(row).split(",", 3)
            if len(parts) >= 3:
                old = parts[1].strip()
                new = parts[2].strip()
                old_name = self.clean_pitcher_name(old)
                new_name = self.clean_pitcher_name(new)
                if old and old != "P" and old_name and not first_old:
                    first_old = old_name
                if old:
                    mapping[old] = old_name
                if new:
                    mapping[new] = new_name
        if first_old:
            mapping["P"] = first_old
        return mapping

    def display_pitcher(self, pitcher_id: str, mapping: dict[str, str]) -> str:
        key = str(pitcher_id or "").strip().lstrip("*")
        return mapping.get(key, self.clean_pitcher_name(key))

    def clean_pitcher_name(self, name: str) -> str:
        import re
        s = str(name or "").strip().lstrip("*").strip()
        s = s.lstrip("】］]）) ")
        s = re.sub(r"[（(][^）)]*球[^）)]*[）)]", "", s)
        s = re.sub(r"[（(][^）)]*[）)]", "", s)
        s = s.strip(" 、。:：->→－-")
        return s or str(name or "").strip().lstrip("*")

    def display_runner(self, runner_text: str) -> str:
        if not runner_text:
            return ""
        text = runner_text.split(" / ", 1)[0]
        if ":" in text:
            text = text.split(":", 1)[1]
        return text.strip()

    def short_reason(self, reason: str, runner_text: str = "", judgment: str = "") -> str:
        text = f"{reason} {runner_text}"
        if ("同一走者ID" in text and "未生還" in text) or "生還不能" in text:
            return "Virtual生還不能"
        if judgment == "自責点":
            return "自責対象"

        # RC009: Virtual進塁不能は、Virtual3アウトとは別理由として表示する。
        # genericな「Virtual」判定より先に置かないと、画面表示がVirtual3アウトに丸められる。
        if "Virtual進塁" in text and ("生還不能" in text or "不能" in text):
            return "Virtual生還不能"
        if "Virtual進塁" in text and "判定不能" in text:
            return "要確認"

        # Sprint4.2: Virtual3アウトは、Virtual進塁不能ではない場合だけ短縮表示する。
        if "Virtual" in text or "3アウト" in text:
            return "Virtual3アウト"
        if "reached=tiebreak" in text or "タイブレーク" in text:
            return "タイブレーク走者"
        if "score_cause=field_error" in text or "失策により生還" in text or "悪送球生還" in text:
            return "失策生還"
        if "score_cause=passed_ball" in text or "捕逸により生還" in text or "捕逸生還" in text:
            return "捕逸生還"

        if "field_error" in text or "失策" in text or "落球" in text or "悪送球" in text or "ファンブル" in text:
            return "失策出塁"
        if "fielder_choice" in text or "野選" in text:
            return "野選"
        if "passed_ball" in text or "捕逸" in text:
            return "捕逸"
        if "wild_pitch" in text or "暴投" in text:
            return "暴投"
        if "継承" in text:
            return "継承走者"
        if "自責対象外" in text:
            return "自責対象外出塁"
        if "自責対象" in text:
            return "自責対象"
        return reason[:12] if reason else ""

    def label(self, judgment: str) -> str:
        if judgment == "非自責点":
            return "非自責"
        if judgment == "自責点":
            return "自責"
        if judgment == "自責点候補":
            return "要確認"
        return judgment
