from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameSnapshot:
    """Phoenix V3.0 Sprint01 Foundation.

    状態をDebugへ渡すための読み取り専用スナップショット。
    Sprint01では基盤定義のみ。判定ロジックには接続しない。
    """

    inning: str
    seq: int
    event: str
    actual: str
    team_virtual: str
    pitcher_virtual: str
    current_pitcher: str
    delta: str = ""
