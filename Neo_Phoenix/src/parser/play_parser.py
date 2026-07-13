from __future__ import annotations

import re
from src.parser.play import Play
from src.parser.base_state_parser import BaseStateParser


class PlayParser:
    """
    Phoenix alpha2

    TextLiveの1プレー行をPlayへ変換する。
    Moveは生成しない。
    """

    def __init__(self):
        self.base_parser = BaseStateParser()

    def parse_line(self, line: str, inning: int = 0, half: str = "", seq: int = 0, pitcher: str = "", batter: str = "") -> Play:
        text = line.strip()

        play = Play(
            inning=inning,
            half=half,
            seq=seq,
            raw_text=text,
            pitcher=pitcher,
            batter=batter,
            runs_scored=self._parse_runs(text),
            final_base_state=self.base_parser.parse(text),
        )

        play.outs_after = self._parse_outs_after(text)

        play.is_walk = ("四球" in text) or ("敬遠" in text)
        play.is_hbp = "死球" in text
        play.is_wild_pitch = "暴投" in text
        play.is_passed_ball = "捕逸" in text
        play.is_interference = "打撃妨害" in text
        play.is_steal = "盗塁" in text
        play.is_error = any(k in text for k in ["失策", "悪送球", "後逸", "ファンブル", "落球"])
        play.is_force_out = "封殺" in text

        play.is_hit = self._is_hit(text)

        # RC069:
        # 「捕手の捕逸により振り逃げ出塁、打者が出塁」のような行は、
        # 文中に「捕逸」を含むため従来の非打者イベント判定に巻き込まれやすい。
        # しかし実体は打者の振り逃げ出塁なので、打者イベントとして扱う。
        is_dropped_third_safe = self._is_dropped_third_strike_safe(text)
        play.is_batter_event = is_dropped_third_safe or not any(k in text for k in ["暴投", "捕逸", "盗塁成功", "盗塁死", "走塁死", "牽制死"])

        return play

    def _is_dropped_third_strike_safe(self, text: str) -> bool:
        text = str(text or "")
        return (
            any(k in text for k in ["振逃", "振り逃げ", "振り逃"])
            or ("三振" in text and "出塁" in text and ("捕逸" in text or "暴投" in text))
        )

    def _parse_runs(self, text: str) -> int:
        m = re.search(r"\+(\d+)点", text)
        if m:
            return int(m.group(1))
        if "生還" in text:
            return 1
        return 0

    def _parse_outs_after(self, text: str) -> int:
        if "３死" in text or "チェンジ" in text or "試合終了" in text:
            return 3
        if "２死" in text:
            return 2
        if "１死" in text:
            return 1
        if "無死" in text:
            return 0
        return 0

    def _is_hit(self, text: str) -> bool:
        # 「左安打、打者が左翼手の後逸で二塁へ」のように
        # 安打＋失策追加進塁が同居する表記は、出塁原因としては安打。
        hit_words = ["安打", "内野安打", "バントヒット", "左安打", "中安打", "右安打", "適時打", "適時二塁打", "適時三塁打", "二塁打", "三塁打", "本塁打", "ホームラン"]
        has_hit = any(k in text for k in hit_words)
        if not has_hit:
            return False
        if "打って" in text and any(k in text for k in ["失策", "悪送球", "ファンブル", "落球"]) and not any(k in text for k in ["安打", "左安打", "中安打", "右安打", "適時打", "二塁打", "三塁打", "本塁打", "ホームラン"]):
            return False
        return True
