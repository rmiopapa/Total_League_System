from __future__ import annotations

from dataclasses import dataclass, field
from src.move.models import Move
from src.runner.runner import Runner


@dataclass
class RunnerState:
    bases: dict[int, Runner | None] = field(default_factory=lambda: {1: None, 2: None, 3: None})
    scored: list[Runner] = field(default_factory=list)
    outs: list[Runner] = field(default_factory=list)
    outs_count: int = 0
    runner_registry: list[Runner] = field(default_factory=list)

    def clone_bases(self) -> dict[int, Runner | None]:
        return dict(self.bases)

    def copy_from(self, other: "RunnerState") -> None:
        """状態コピー。RC037のPitcher Virtual交代時Actual引継ぎ用。"""
        from copy import deepcopy
        self.bases = deepcopy(getattr(other, "bases", {1: None, 2: None, 3: None}))
        self.scored = list(getattr(other, "scored", []) or [])
        self.outs = list(getattr(other, "outs", []) or [])
        self.outs_count = int(getattr(other, "outs_count", 0) or 0)
        self.runner_registry = list(getattr(other, "runner_registry", []) or [])

    def base_text(self) -> str:
        def name(base: int) -> str:
            r = self.bases.get(base)
            return f"{r.id}:{r.name}" if r else "空"
        return f"一塁[{name(1)}] 二塁[{name(2)}] 三塁[{name(3)}]"


class AtomicRunner:
    """
    Phoenix V2.6 Sprint4.7 MovePrecision

    正規化済みMoveを一括適用するRunner。

    原則:
      - Moveを作らない
      - Moveを補完しない
      - TextLiveを読まない
      - 自責点を判定しない

    役割:
      - beforeの走者を退避
      - Moveを適用
      - after状態を返す
    """

    ORDER = {"3": 0, "2": 1, "1": 2, "B": 3}

    def __init__(self):
        self.runner_seq = 0
        self.warnings: list[str] = []



    def _phoenix_sort_moves_for_apply(self, moves):
        """
        Phoenix V2.6 Sprint2.1

        Move適用順の見える化検証用。
        走者の重なりを防ぐため、Runnerへの適用順だけを統一する。
        判定ロジック・Move生成内容は変更しない。
        """
        def src_base(mv):
            return {"3": 3, "2": 2, "1": 1, "B": 0}.get(str(getattr(mv, "source", "")), 0)

        def category(mv):
            source = str(getattr(mv, "source", ""))
            target = str(getattr(mv, "target", ""))
            # 塁を空ける処理を先に。三塁側から。
            if source in {"3", "2", "1"} and target in {"H", "OUT"}:
                return 0
            # 塁上走者の進塁。三塁側から。
            if source in {"3", "2", "1"}:
                return 1
            # 打者走者は最後。
            if source == "B":
                return 2
            return 3

        return sorted(moves, key=lambda mv: (category(mv), -src_base(mv)))


    def _phoenix_move_sort_key(self, mv):
        """
        Phoenix V2.6 Sprint3.3 / RC-001

        複数走者が同時に進む場面では、本塁側の走者から適用する。
        例: 満塁スクイズ・連続進塁
          3->H
          2->3
          1->2
          B->1

        これにより、3塁走者が生還する前に2塁走者を3塁へ入れて
        「3塁に既存走者あり」となる警告を防ぐ。
        """
        source = str(getattr(mv, "source", ""))
        target = str(getattr(mv, "target", ""))

        # 既存走者を本塁側から先に処理。打者走者は最後。
        source_order = {"3": 0, "2": 1, "1": 2, "B": 3}

        # 同一source内ではOUT/Hを先に処理。
        target_order = {"H": 0, "OUT": 0, "3": 1, "2": 2, "1": 3}

        return (source_order.get(source, 99), target_order.get(target, 99), source, target)

    def apply(self, state: RunnerState, moves: list[Move], batter_name: str = "打者", pitcher: str = "") -> RunnerState:
        self.warnings = []
        moves = sorted(moves, key=self._phoenix_move_sort_key)

        before = state.clone_bases()
        moving: dict[str, Runner] = {}

        # 既存走者を全員退避
        # Sprint4.7: source/targetは必ず文字列化して扱う。
        for mv in self._phoenix_sort_moves_for_apply(moves):
            source = str(getattr(mv, "source", ""))
            target = str(getattr(mv, "target", ""))
            if source in {"1", "2", "3"}:
                base = int(source)
                runner = before.get(base)
                if runner is None:
                    self.warnings.append(f"{source}塁に走者なし: {source}->{target}")
                    continue
                moving[source] = runner

        # Move対象の元塁を先に空にする
        for src in moving:
            state.bases[int(src)] = None

        # Move適用
        for mv in moves:
            source = str(getattr(mv, "source", ""))
            target_value = str(getattr(mv, "target", ""))

            if source == "B":
                runner = self._new_batter_runner(batter_name, pitcher, mv)

                # RC032:
                # 失策出塁走者が封殺され、その間に打者走者が一塁へ残る場合、
                # Phoenixでは「得点責任」を入れ替わった走者へ引き継ぐ。
                # 例: Aが失策出塁 → A封殺、Bが一塁残り → Bが生還しても非自責。
                reason = str(getattr(mv, "reason", "") or "")
                if "その間に打者が出塁" in reason or "打者が出塁" in reason:
                    replaced = self._phoenix_replaced_runner_for_batter_safe(moves, moving, batter_target=target_value)
                    if replaced is not None:
                        # RC153:
                        # 前任投手が残した走者が同一プレーでアウトになり、打者走者が塁上に残る場合、
                        # 打者走者の責任投手はアウトになった走者の責任投手を代位する。
                        runner.responsible_pitcher = getattr(replaced, "responsible_pitcher", runner.responsible_pitcher)
                        if not getattr(replaced, "earned_eligible", True):
                            runner.earned_eligible = False
                            runner.reached_cause_type = getattr(replaced, "reached_cause_type", runner.reached_cause_type)
                            runner.reached_by = f"走者入替継承: {getattr(replaced, 'reached_by', '')}"
                        runner.history.append(f"得点責任継承: {replaced.id}:{replaced.name}")

                state.runner_registry.append(runner)
            else:
                runner = moving.get(source)
                if runner is None:
                    continue

            if target_value == "H":
                runner.current_base = 4
                runner.scored = True
                # 得点した進塁原因を保持。
                # 出塁は自責対象でも、失策・捕逸による生還なら非自責になり得る。
                runner.score_cause_type = mv.cause_type
                runner.score_reason = mv.reason
                runner.history.append(f"得点: {mv.reason}")
                state.scored.append(runner)
            elif target_value == "OUT":
                runner.current_base = -1
                runner.out = True
                runner.history.append(f"アウト: {mv.reason}")
                state.outs.append(runner)
                state.outs_count += 1
            else:
                target = int(target_value)
                runner.current_base = target
                runner.history.append(f"{target}塁へ: {mv.reason}")
                if state.bases.get(target) is not None:
                    existing = state.bases[target]
                    self.warnings.append(f"{target}塁に既存走者あり: {existing.id}:{existing.name} / 新={runner.id}:{runner.name}")
                else:
                    state.bases[target] = runner

        return state

    def _phoenix_replaced_runner_for_batter_safe(self, moves: list[Move], moving: dict[str, Runner], batter_target: str = "1") -> Runner | None:
        """
        B->1（その間に打者が出塁）で、同一プレーに封殺/アウト走者がいる場合、
        そのアウト走者を「入れ替わった走者」として返す。

        RC071補強:
        打者が一塁へ残るときに三塁走者が本塁封殺されたケースは、
        打者が三塁走者の責任を引き継ぐ場面ではない。
        責任継承は、打者の到達塁と同じ塁から押し出されてアウトになった
        走者に限定する（B->1なら一塁走者、B->2なら二塁走者）。
        """
        target_to_source = {"1": "1", "2": "2", "3": "3"}
        expected_source = target_to_source.get(str(batter_target))
        if not expected_source:
            return None
        for mv in moves:
            source = str(getattr(mv, "source", ""))
            target = str(getattr(mv, "target", ""))
            if source == expected_source and target == "OUT":
                r = moving.get(source)
                if r is not None:
                    return r

        # タイブレーク走者・失策走者が失策等で生還し、同じ塁に打者走者が残る場合も、
        # 得点責任上は打者走者がその非自責走者を代位する。
        for mv in moves:
            source = str(getattr(mv, "source", ""))
            target = str(getattr(mv, "target", ""))
            cause = str(getattr(mv, "cause_type", ""))
            if source == expected_source and target == "H" and cause in {"field_error", "passed_ball", "interference"}:
                r = moving.get(source)
                if r is not None and not getattr(r, "earned_eligible", True):
                    return r

        # RC153:
        # B->1で打者走者が一塁に残り、同一プレーで三塁走者など別塁の既存走者が
        # アウトになった場合も、責任投手上はそのアウト走者を代位する。
        if str(batter_target) == "1":
            for mv in moves:
                source = str(getattr(mv, "source", ""))
                target = str(getattr(mv, "target", ""))
                if source in {"1", "2", "3"} and target == "OUT":
                    r = moving.get(source)
                    if r is not None:
                        return r

        # RC135:
        # B->1で一塁走者が二塁へ押し出され、二塁走者が封殺される形も
        # 得点責任上は打者走者がアウトになった二塁走者を代位する。
        # タイブレーク走者は失策出塁走者と同じく非自責対象なので、
        # その非自責属性を後からの走者へ継承する。
        if str(batter_target) == "1":
            has_first_forced = any(
                str(getattr(mv, "source", "")) == "1"
                and str(getattr(mv, "target", "")) in {"2", "3", "H"}
                for mv in moves
            )
            if has_first_forced:
                for mv in moves:
                    source = str(getattr(mv, "source", ""))
                    target = str(getattr(mv, "target", ""))
                    if source == "2" and target == "OUT":
                        r = moving.get(source)
                        if r is not None:
                            return r
        return None

    def _new_batter_runner(self, name: str, pitcher: str, mv: Move) -> Runner:
        self.runner_seq += 1
        runner = Runner(
            id=f"R{self.runner_seq:03d}",
            name=name or f"打者{self.runner_seq:03d}",
            responsible_pitcher=pitcher,
            reached_by=mv.reason,
            reached_cause_type=mv.cause_type,
            earned_eligible=mv.cause_type not in {"field_error", "passed_ball", "interference"},
            current_base=1,
        )
        runner.history.append(f"出塁: {mv.reason}")
        return runner
