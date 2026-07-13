from dataclasses import dataclass, field
from typing import Literal

BaseSource = Literal["B", "1", "2", "3"]
MoveTarget = Literal["1", "2", "3", "H", "OUT"]


@dataclass
class Move:
    source: BaseSource
    target: MoveTarget
    reason: str
    cause_type: str = "unknown"
    pitcher_charge: bool = False
    virtual_allow: bool = True
    explicit: bool = True


@dataclass
class BaseState:
    first: str | None = None
    second: str | None = None
    third: str | None = None

    def occupied(self, base: int) -> bool:
        return {
            1: self.first is not None,
            2: self.second is not None,
            3: self.third is not None,
        }.get(base, False)

    def as_set(self) -> set[int]:
        result = set()
        if self.first is not None:
            result.add(1)
        if self.second is not None:
            result.add(2)
        if self.third is not None:
            result.add(3)
        return result
