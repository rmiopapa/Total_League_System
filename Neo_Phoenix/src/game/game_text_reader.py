from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path


@dataclass
class HalfInningBlock:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class GameText:
    path: str
    half_innings: list[HalfInningBlock] = field(default_factory=list)


class GameTextReader:
    """
    Phoenix Beta1.1

    EasyScore系 game.txt を半イニング単位へ分割する最小版。

    対応方針:
      - 「1回表」「１回裏」「一回表」などを半イニング見出しとして検出
      - 見出しがない場合は全体を1ブロックとして扱う
      - 空行、罫線、Summary行は除外
    """

    HALF_PATTERN = re.compile(
        r"^(?:={2,}\s*)?(?P<inning>[0-9０-９一二三四五六七八九十]+)\s*回\s*(?P<half>表|裏)"
    )

    SKIP_PREFIXES = (
        "====",
        "----",
        "[Summary]",
        "[Actual]",
        "[Virtual]",
        "[Review]",
        "[Score",
    )

    def read(self, path: str | Path) -> GameText:
        path = Path(path)
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        return self.parse_text(text, str(path))

    def parse_text(self, text: str, path: str = "") -> GameText:
        game = GameText(path=path)
        current: HalfInningBlock | None = None

        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith(self.SKIP_PREFIXES):
                continue

            title = self._detect_half_title(line)
            if title:
                current = HalfInningBlock(title=title)
                game.half_innings.append(current)
                continue

            if self._looks_like_play_line(line):
                if current is None:
                    current = HalfInningBlock(title="不明")
                    game.half_innings.append(current)
                current.lines.append(line)

        return game

    def _detect_half_title(self, line: str) -> str | None:
        m = self.HALF_PATTERN.search(line)
        if not m:
            return None
        return f"{m.group('inning')}回{m.group('half')}"

    def _looks_like_play_line(self, line: str) -> bool:
        # Beta1.1では広めに拾う
        keywords = [
            "番", "球目", "暴投", "捕逸", "盗塁", "牽制", "投手交代", "に代わり", "投手：", "投手:",
            "無死", "１死", "２死", "３死", "チェンジ", "+1点", "+2点", "+3点",
            "先発は", "マウンド", "守備位置変更", "タイブレーク"
        ]
        return any(k in line for k in keywords)
