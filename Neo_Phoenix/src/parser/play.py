from dataclasses import dataclass, field
from src.move.models import BaseState


@dataclass
class Play:
    inning: int
    half: str
    seq: int
    raw_text: str
    pitcher: str = ""
    batter: str = ""
    outs_before: int = 0
    outs_after: int = 0
    runs_scored: int = 0
    final_base_state: BaseState = field(default_factory=BaseState)

    is_hit: bool = False
    is_error: bool = False
    is_walk: bool = False
    is_hbp: bool = False
    is_wild_pitch: bool = False
    is_passed_ball: bool = False
    is_interference: bool = False
    is_steal: bool = False
    is_force_out: bool = False
    is_batter_event: bool = True
