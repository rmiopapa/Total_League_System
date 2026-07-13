from __future__ import annotations

from src.event.event_dictionary import lookup_event_label


def short_event_label(line: str) -> str:
    """DebugTrace / PitcherRuntimeDebug 用の短縮イベント名。

    Event辞書に集約し、表示専用として判定ロジックから分離する。
    """
    return lookup_event_label(line)
