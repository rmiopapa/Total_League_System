from __future__ import annotations

from src.move.models import Move


class NeoAdvanceClassifier:
    """Classifies which Actual advances can be mirrored by Virtual.

    Neo policy:
      - Exclude fielding errors, passed balls, throwing errors and similar
        non-earned defensive/catcher advances.
      - Do not exclude wild pitches or fielder's-choice/force-out movement.
    """

    EXCLUDED_CAUSES = {
        "field_error",
        "passed_ball",
        "interference",
    }

    def is_virtual_excluded(self, move: Move) -> bool:
        cause = str(getattr(move, "cause_type", "") or "")
        if cause == "wild_pitch":
            return False
        if cause in {"out", "fielder_choice", "force_out"}:
            return False
        if cause in self.EXCLUDED_CAUSES:
            return True
        return bool(getattr(move, "virtual_allow", True) is False)

    def is_normal_advance(self, move: Move) -> bool:
        return not self.is_virtual_excluded(move)
