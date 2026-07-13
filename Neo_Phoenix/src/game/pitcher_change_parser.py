from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PitcherChange:
    old_pitcher: str
    new_pitcher: str
    raw_text: str


class PitcherChangeParser:
    """
    Phoenix V3.0 Sprint04 PitcherNameFix.

    TextLiveの投手変更系表記を検出する。
    対応例:
      【投手交代】末富 翼(77球) → 寺廻 志郎 （投手）
      投手交代：向井→佐藤
      投手：向井から佐藤
      向井に代わり佐藤
      【守備位置変更】 安井幹也 一塁手 → 投手
    """

    def _clean_name(self, s: str) -> str:
        s = str(s or "").strip()
        s = re.sub(r"^[【\[]?投手交代[】\]]?", "", s).strip()
        s = s.lstrip("】］]）) ")
        s = re.sub(r"[（(][^）)]*球[^）)]*[）)]", "", s)
        s = re.sub(r"[（(]\s*(?:投手|捕手|一塁手|二塁手|三塁手|遊撃手|左翼手|中堅手|右翼手)\s*[）)]", "", s)
        s = s.strip(" 、。:：->→－-")
        return s.strip()

    def parse(self, line: str) -> PitcherChange | None:
        text = str(line or "").strip()
        if not text:
            return None

        explicit_pitcher_change = "【投手交代】" in text
        if explicit_pitcher_change:
            pos = re.search(r"[（(](?P<pos>[^）)]*)[）)]\s*$", text)
            if pos and "投手" not in pos.group("pos"):
                return None

        m = re.search(r"【守備位置変更】\s*(?P<new>.+?)\s+(?:投手|捕手|一塁手|二塁手|三塁手|遊撃手|左翼手|中堅手|右翼手)\s*→\s*投手\s*$", text)
        if m:
            new_name = re.sub(r"[（(].*$", "", m.group("new")).strip()
            if new_name:
                return PitcherChange(old_pitcher="", new_pitcher=new_name, raw_text=text)

        m = re.search(r"【投手交代】\s*(?P<old>.+?)(?:[（(].*?[）)])?\s*→\s*(?P<new>.+?)\s*[（(]投手[）)]\s*$", text)
        if m:
            old_name = re.sub(r"[（(].*$", "", m.group("old")).strip()
            new_name = re.sub(r"[（(].*$", "", m.group("new")).strip()
            if new_name:
                return PitcherChange(old_pitcher=old_name, new_pitcher=new_name, raw_text=text)

        # 1) 守備位置変更で誰かが投手に入る表記。
        #    旧投手は行内に出ないことが多いため、PitcherManager側の current_pitcher を使わせる。
        m = re.search(r"守備位置変更[^】］]*[】］]?\s*(?P<new>.+?)\s+(?:捕手|一塁手|二塁手|三塁手|遊撃手|左翼手|中堅手|右翼手)\s*(?:→|->|－|-)\s*投手", text)
        if m:
            new_name = self._clean_name(m.group("new"))
            if new_name:
                return PitcherChange(old_pitcher="", new_pitcher=new_name, raw_text=text)

        if "投手交代" not in text and "に代わり" not in text and "投手" not in text:
            return None

        # 2) 一般的な投手交代。氏名内スペース、球数、末尾（投手）に対応。
        m = re.search(r"(?:【?投手交代】?|投手交代[:：]?)\s*(?P<old>.+?)\s*(?:→|->|－|-)\s*(?P<new>.+?)(?:\s*[（(].*?[）)]\s*)?$", text)
        if m:
            old_name = self._clean_name(m.group("old"))
            new_name = self._clean_name(m.group("new"))
            if new_name:
                return PitcherChange(old_pitcher=old_name, new_pitcher=new_name, raw_text=text)

        # 3) 投手：向井から佐藤
        m = re.search(r"投手[:：]\s*(?P<old>.+?)から(?P<new>[^、。\s]+(?:\s+[^、。\s]+)?)", text)
        if m:
            old_name = self._clean_name(m.group("old"))
            new_name = self._clean_name(m.group("new"))
            if new_name:
                return PitcherChange(old_pitcher=old_name, new_pitcher=new_name, raw_text=text)

        # 4) 向井に代わり佐藤
        m = re.search(r"(?P<old>[^、。]+?)に代わり(?P<new>[^、。\s]+(?:\s+[^、。\s]+)?)", text)
        if m:
            old_name = self._clean_name(m.group("old"))
            new_name = self._clean_name(m.group("new"))
            if new_name:
                return PitcherChange(old_pitcher=old_name, new_pitcher=new_name, raw_text=text)

        return None
