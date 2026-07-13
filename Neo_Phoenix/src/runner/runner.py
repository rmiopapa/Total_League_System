from dataclasses import dataclass, field


@dataclass
class Runner:
    id: str
    name: str
    responsible_pitcher: str
    reached_by: str
    reached_cause_type: str = "unknown"
    earned_eligible: bool = True
    current_base: int = 1
    scored: bool = False
    out: bool = False
    history: list[str] = field(default_factory=list)
