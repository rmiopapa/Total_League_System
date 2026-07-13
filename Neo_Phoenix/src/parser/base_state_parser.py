from __future__ import annotations

import re
from src.move.models import BaseState


class BaseStateParser:
    """
    Phoenix alpha3.6

    TextLive末尾の塁状況をBaseStateへ変換する完成版。

    alpha3.6 修正:
      - 「チェンジ、一、二塁残塁」を {1,2} として確実に読む
      - 残塁表現は通常の塁状況より優先
      - 部分一致（二塁だけ拾う等）を避ける
    """

    STATE_PATTERNS = [
        ("一、二、三塁", {1, 2, 3}),
        ("満塁", {1, 2, 3}),
        ("一、三塁", {1, 3}),
        ("一、二塁", {1, 2}),
        ("二、三塁", {2, 3}),
        ("一塁", {1}),
        ("二塁", {2}),
        ("三塁", {3}),
    ]

    OUT_WORDS = ["無死", "１死", "２死", "３死", "一死", "二死", "三死"]

    def parse(self, text: str) -> BaseState:
        bases = self.parse_set(text)
        return BaseState(
            first="unknown" if 1 in bases else None,
            second="unknown" if 2 in bases else None,
            third="unknown" if 3 in bases else None,
        )

    def parse_set(self, text: str) -> set[int]:
        text = text or ""

        # 1. 残塁表現を最優先
        lob = self._parse_left_on_base(text)
        if lob is not None:
            return lob

        # 2. アウトカウント直後の最終塁状況
        candidates: list[tuple[int, set[int]]] = []
        for out_word in self.OUT_WORDS:
            for label, bases in self.STATE_PATTERNS:
                token = out_word + label
                pos = text.rfind(token)
                if pos >= 0:
                    candidates.append((pos, set(bases)))

        if candidates:
            return sorted(candidates, key=lambda x: x[0])[-1][1]

        # 3. 文末付近の塁状況を採用
        candidates = []
        for label, bases in self.STATE_PATTERNS:
            start = 0
            while True:
                pos = text.find(label, start)
                if pos < 0:
                    break

                after = text[pos + len(label):pos + len(label) + 2]

                # 「満塁走者」は状態ではない
                if label == "満塁" and after.startswith("走者"):
                    start = pos + len(label)
                    continue

                candidates.append((pos, set(bases)))
                start = pos + len(label)

        if candidates:
            return sorted(candidates, key=lambda x: x[0])[-1][1]

        return set()

    def _parse_left_on_base(self, text: str) -> set[int] | None:
        """
        残塁表現を専用処理する。

        例:
          チェンジ、一、二塁残塁 => {1,2}
          チェンジ、二塁残塁     => {2}
          チェンジ、３者残塁     => {1,2,3}
        """
        if "残塁" not in text:
            return None

        if "３者残塁" in text or "三者残塁" in text:
            return {1, 2, 3}

        # 「チェンジ、○○残塁」の○○部分だけ取り出す
        m = re.search(r"チェンジ、(.+?)残塁", text)
        if m:
            phrase = m.group(1)
        else:
            # フォールバック: 残塁の直前を対象
            phrase = text[:text.rfind("残塁")]

        # 複合表現を優先
        for label, bases in self.STATE_PATTERNS:
            if label in phrase:
                return set(bases)

        return set()
