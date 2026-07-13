from __future__ import annotations

from dataclasses import dataclass, field

from src.move.models import Move


@dataclass
class NeoPlaySnapshot:
    seq: int
    raw_text: str
    actual_before: str
    actual_after: str
    virtual_before: str
    virtual_after: str
    actual_outs_before: int = 0
    actual_outs_after: int = 0
    virtual_outs_before: int = 0
    virtual_outs_after: int = 0
    actual_moves: list[Move] = field(default_factory=list)
    virtual_moves: list[Move] = field(default_factory=list)
    scored_runner_ids: list[str] = field(default_factory=list)
    actual_scored_runner_ids: list[str] = field(default_factory=list)
    virtual_scored_runner_ids: list[str] = field(default_factory=list)
    actual_scored_runner_facts: list[dict[str, object]] = field(default_factory=list)
    virtual_scored_runner_facts: list[dict[str, object]] = field(default_factory=list)
    pitcher_virtual_outs_before_by_runner_id: dict[str, int] = field(default_factory=dict)
    pitcher_virtual_outs_after_by_runner_id: dict[str, int] = field(default_factory=dict)
    pitcher_virtual_scored_by_runner_id: dict[str, bool] = field(default_factory=dict)
    pitcher_virtuals_after: dict[str, str] = field(default_factory=dict)
    current_pitcher: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class NeoHalfInningResult:
    title: str
    plays: list[NeoPlaySnapshot] = field(default_factory=list)
    total_actual_scores: int = 0
    total_virtual_scores: int = 0
    actual_outs: int = 0
    virtual_outs: int = 0
    warnings: list[str] = field(default_factory=list)
