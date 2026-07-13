from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any


@dataclass
class PitcherState:
    """Phoenix V3.0 Sprint01 Foundation.

    投手ごとのVirtual状態を保持する器。
    Sprint01では判定には接続せず、Team/Current Virtualと同じ状態を可視化する。
    """

    pitcher_id: str
    name: str = ""
    virtual_bases: dict[int, Any | None] = field(default_factory=lambda: {1: None, 2: None, 3: None})
    virtual_outs: int = 0
    responsible_runners: set[str] = field(default_factory=set)
    inherited_runners: set[str] = field(default_factory=set)
    earned_runs: int = 0
    history: list[str] = field(default_factory=list)

    def copy_virtual_from_runner_state(self, state: Any) -> None:
        """RunnerStateから現在のVirtual状態をコピーする。"""
        self.virtual_bases = deepcopy(getattr(state, "bases", {1: None, 2: None, 3: None}))
        self.virtual_outs = int(getattr(state, "outs_count", 0) or 0)
        self.responsible_runners = {
            str(getattr(r, "id", ""))
            for r in self.virtual_bases.values()
            if r is not None and str(getattr(r, "responsible_pitcher", "")) == self.pitcher_id
        }

    def copy_virtual_from_pitcher(self, other: "PitcherState") -> None:
        """投手交代時、新投手の初期Virtualとして直前状態をコピーする。"""
        self.virtual_bases = deepcopy(other.virtual_bases)
        self.virtual_outs = int(other.virtual_outs or 0)
        self.history.append(f"Virtual copied from {other.pitcher_id}")

    def virtual_text(self) -> str:
        bases = [base for base in (1, 2, 3) if self.virtual_bases.get(base) is not None]
        return format_simple_state(self.virtual_outs, bases)


def format_simple_state(outs: int, bases: list[int] | tuple[int, ...] | set[int]) -> str:
    """無死一塁 / 1死二三塁 / 3死 のような簡潔表記。"""
    try:
        outs_i = int(outs or 0)
    except Exception:
        outs_i = 0
    out_text = "無死" if outs_i == 0 else f"{outs_i}死"
    if outs_i >= 3:
        return "3死"
    base_set = set(int(b) for b in bases if b in {1, 2, 3})
    if not base_set:
        return out_text
    base_names = {1: "一", 2: "二", 3: "三"}
    return out_text + "".join(base_names[b] for b in (1, 2, 3) if b in base_set) + "塁"


def runner_state_simple_text(state: Any) -> str:
    bases_dict = getattr(state, "bases", {}) or {}
    bases = [base for base in (1, 2, 3) if bases_dict.get(base) is not None]
    return format_simple_state(getattr(state, "outs_count", 0), bases)


def report_state_simple_text(text: str, outs: int | str) -> str:
    """PlayReportのbase_textから簡潔表記へ変換する。"""
    raw = str(text or "")
    bases = []
    if "一塁[" in raw and "一塁[空]" not in raw:
        bases.append(1)
    if "二塁[" in raw and "二塁[空]" not in raw:
        bases.append(2)
    if "三塁[" in raw and "三塁[空]" not in raw:
        bases.append(3)
    try:
        outs_i = int(outs or 0)
    except Exception:
        outs_i = 0
    return format_simple_state(outs_i, bases)
