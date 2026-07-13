from __future__ import annotations

from copy import deepcopy
import re

from src.move.models import BaseState, Move
from src.move.move_completer import MoveCompleter
from src.move.move_generator import MoveGenerator
from src.neo.advance_classifier import NeoAdvanceClassifier
from src.neo.models import NeoHalfInningResult, NeoPlaySnapshot
from src.parser.play_parser import PlayParser
from src.runner.atomic_runner import AtomicRunner, RunnerState
from src.runner.runner import Runner
from src.game.pitcher_change_parser import PitcherChangeParser


class NeoHalfInningEngine:
    """Experimental Phoenix successor core.

    Actual is the official final-base fact model. Virtual is rebuilt from
    normal Actual movement by runner id/base, with defensive/catcher-error
    advances removed.
    """

    def __init__(self, title: str = "Neo Half Inning", pitcher_split_mode: bool = False):
        self.title = title
        self.pitcher_split_mode = bool(pitcher_split_mode)
        self.parser = PlayParser()
        self.pitcher_parser = PitcherChangeParser()
        self.generator = MoveGenerator()
        self.actual_completer = MoveCompleter()
        self.actual_atomic = AtomicRunner()
        self.virtual_atomic = AtomicRunner()
        self.classifier = NeoAdvanceClassifier()
        self.actual_state = RunnerState()
        self.virtual_state = RunnerState()
        self.result = NeoHalfInningResult(title=title)
        self.pitcher_virtual_states: dict[str, RunnerState] = {}
        self.pitcher_virtual_atomics: dict[str, AtomicRunner] = {}
        self.current_pitcher = ""

    def run(self, lines: list[str], pitcher: str = "P") -> NeoHalfInningResult:
        current_pitcher, play_lines = self._extract_initial_pitcher(lines, pitcher)
        self.current_pitcher = current_pitcher
        if self.pitcher_split_mode:
            self._ensure_pitcher_virtual(current_pitcher)
        for seq, line in enumerate(play_lines, 1):
            pc = self.pitcher_parser.parse(line)
            if pc:
                current_pitcher = pc.new_pitcher or current_pitcher
                self.current_pitcher = current_pitcher
                if self.pitcher_split_mode:
                    self._start_pitcher_virtual(current_pitcher)
                continue
            if self._is_tiebreak_runner_setup_line(str(line or "")):
                self._run_tiebreak_setup(seq, line, current_pitcher)
                continue
            if self._is_administrative_line(line):
                continue
            self._run_one(seq, line, current_pitcher)
        self.result.total_actual_scores = len(self.actual_state.scored)
        self.result.total_virtual_scores = len(self.virtual_state.scored)
        self.result.actual_outs = self.actual_state.outs_count
        self.result.virtual_outs = self.virtual_state.outs_count
        return self.result

    def _extract_initial_pitcher(self, lines: list[str], fallback: str = "P") -> tuple[str, list[str]]:
        pitcher = str(fallback or "P").strip() or "P"
        play_lines: list[str] = []
        for line in lines:
            text = str(line or "").strip()
            if text.startswith("先発は"):
                name = text.replace("先発は", "", 1).strip()
                if name:
                    pitcher = name
                continue
            if text.startswith("マウンド"):
                name = text.replace("マウンド", "", 1).strip()
                if name:
                    pitcher = name
                continue
            play_lines.append(line)
        return pitcher, play_lines

    def _run_one(self, seq: int, line: str, pitcher: str) -> None:
        actual_before_text = self.actual_state.base_text()
        virtual_before_text = self.virtual_state.base_text()
        actual_outs_before = self.actual_state.outs_count
        virtual_outs_before = self.virtual_state.outs_count
        actual_before = self._base_state(self.actual_state)
        actual_before_bases = deepcopy(self.actual_state.bases)
        virtual_before_bases = deepcopy(self.virtual_state.bases)

        play = self.parser.parse_line(line, seq=seq, pitcher=pitcher)
        play.outs_before = self.actual_state.outs_count
        play.batter = self._guess_batter(line)

        generated = self.generator.generate(play)
        actual_moves = self.actual_completer.complete(play, generated, actual_before)
        actual_moves = self._align_actual_to_final_state(play, actual_moves, actual_before)

        if self.pitcher_split_mode:
            self._run_one_pitcher_split(
                seq=seq,
                line=line,
                pitcher=pitcher,
                play=play,
                generated=generated,
                actual_moves=actual_moves,
                actual_before_text=actual_before_text,
                virtual_before_text=virtual_before_text,
                actual_outs_before=actual_outs_before,
                virtual_outs_before=virtual_outs_before,
                actual_before_bases=actual_before_bases,
            )
            return

        virtual_moves = self._build_virtual_moves(
            play=play,
            generated=generated,
            actual_moves=actual_moves,
            actual_before_bases=actual_before_bases,
            virtual_before_bases=virtual_before_bases,
        )

        actual_scored_before = len(self.actual_state.scored)
        virtual_scored_before = len(self.virtual_state.scored)
        self.actual_atomic.apply(self.actual_state, actual_moves, batter_name=play.batter, pitcher=pitcher)
        self.virtual_atomic.apply(self.virtual_state, virtual_moves, batter_name=play.batter, pitcher=pitcher)

        if self._is_batter_out_play(line, actual_moves):
            self.actual_state.outs_count += 1
        if self._is_batter_out_play(line, virtual_moves):
            self.virtual_state.outs_count += 1

        actual_scored_ids = [
            str(getattr(runner, "id", ""))
            for runner in self.actual_state.scored[actual_scored_before:]
        ]
        virtual_scored_ids = [
            str(getattr(runner, "id", ""))
            for runner in self.virtual_state.scored[virtual_scored_before:]
        ]
        self._remove_runner_ids_from_bases(self.virtual_state, set(actual_scored_ids) | set(virtual_scored_ids))
        actual_scored_facts = [
            self._scored_runner_fact(runner)
            for runner in self.actual_state.scored[actual_scored_before:]
        ]
        virtual_scored_facts = [
            self._scored_runner_fact(runner)
            for runner in self.virtual_state.scored[virtual_scored_before:]
        ]
        warnings = self._filter_benign_scored_runner_warnings(
            list(self.actual_atomic.warnings) + list(self.virtual_atomic.warnings),
            set(actual_scored_ids) | set(virtual_scored_ids),
        )
        if warnings:
            self.result.warnings.extend(f"Seq{seq}: {w}" for w in warnings)

        self.result.plays.append(
            NeoPlaySnapshot(
                seq=seq,
                raw_text=line,
                actual_before=actual_before_text,
                actual_after=self.actual_state.base_text(),
                virtual_before=virtual_before_text,
                virtual_after=self.virtual_state.base_text(),
                actual_outs_before=actual_outs_before,
                actual_outs_after=self.actual_state.outs_count,
                virtual_outs_before=virtual_outs_before,
                virtual_outs_after=self.virtual_state.outs_count,
                actual_moves=actual_moves,
                virtual_moves=virtual_moves,
                scored_runner_ids=actual_scored_ids,
                actual_scored_runner_ids=actual_scored_ids,
                virtual_scored_runner_ids=virtual_scored_ids,
                actual_scored_runner_facts=actual_scored_facts,
                virtual_scored_runner_facts=virtual_scored_facts,
                warnings=warnings,
            )
        )
        if self._is_inning_end_line(line):
            self.actual_state.bases = {1: None, 2: None, 3: None}
            self.virtual_state.bases = {1: None, 2: None, 3: None}

    def _run_one_pitcher_split(
        self,
        seq: int,
        line: str,
        pitcher: str,
        play,
        generated: list[Move],
        actual_moves: list[Move],
        actual_before_text: str,
        virtual_before_text: str,
        actual_outs_before: int,
        virtual_outs_before: int,
        actual_before_bases: dict[int, Runner | None],
    ) -> None:
        self._ensure_pitcher_virtual(pitcher)
        current_state = self.pitcher_virtual_states[pitcher]
        current_atomic = self.pitcher_virtual_atomics[pitcher]
        virtual_before_text = current_state.base_text()
        virtual_outs_before = current_state.outs_count

        actual_scored_before = len(self.actual_state.scored)
        self.actual_atomic.apply(self.actual_state, actual_moves, batter_name=play.batter, pitcher=pitcher)
        if self._is_batter_out_play(line, actual_moves):
            self.actual_state.outs_count += 1

        actual_scored_ids = [
            str(getattr(runner, "id", ""))
            for runner in self.actual_state.scored[actual_scored_before:]
        ]
        actual_scored_facts = [
            self._scored_runner_fact(runner)
            for runner in self.actual_state.scored[actual_scored_before:]
        ]

        pitcher_before_by_name: dict[str, int] = {}
        pitcher_after_by_name: dict[str, int] = {}
        pitcher_scored_by_name: dict[str, set[str]] = {}
        current_virtual_moves: list[Move] = []
        current_virtual_scored_ids: list[str] = []
        current_warnings: list[str] = []

        for name in list(self.pitcher_virtual_states):
            state = self.pitcher_virtual_states[name]
            atomic = self.pitcher_virtual_atomics[name]
            pitcher_before_by_name[name] = state.outs_count
            scored_before = len(state.scored)
            if state.outs_count >= 3:
                moves: list[Move] = []
            else:
                moves = self._build_virtual_moves(
                    play=play,
                    generated=generated,
                    actual_moves=actual_moves,
                    actual_before_bases=actual_before_bases,
                    virtual_before_bases=deepcopy(state.bases),
                )
                atomic.apply(state, moves, batter_name=play.batter, pitcher=pitcher)
                if self._is_batter_out_play(line, moves):
                    state.outs_count += 1
                scored_ids = [
                    str(getattr(runner, "id", ""))
                    for runner in state.scored[scored_before:]
                ]
                self._remove_runner_ids_from_bases(state, set(actual_scored_ids) | set(scored_ids))
            pitcher_after_by_name[name] = state.outs_count
            pitcher_scored_by_name[name] = {
                str(getattr(runner, "id", ""))
                for runner in state.scored
                if str(getattr(runner, "id", ""))
            }
            if name == pitcher:
                current_virtual_moves = moves
                current_virtual_scored_ids = [
                    str(getattr(runner, "id", ""))
                    for runner in state.scored[scored_before:]
                ]
                current_warnings = list(atomic.warnings)

        self.virtual_state = current_state
        self.virtual_atomic = current_atomic

        facts_by_id = {str(fact.get("id", "")): fact for fact in actual_scored_facts}
        pitcher_before_by_runner: dict[str, int] = {}
        pitcher_after_by_runner: dict[str, int] = {}
        pitcher_scored_by_runner: dict[str, bool] = {}
        for runner_id in actual_scored_ids:
            fact = facts_by_id.get(runner_id, {})
            responsible = str(fact.get("responsible_pitcher", "") or "")
            pitcher_before_by_runner[runner_id] = pitcher_before_by_name.get(responsible, current_state.outs_count)
            pitcher_after_by_runner[runner_id] = pitcher_after_by_name.get(responsible, current_state.outs_count)
            pitcher_scored_by_runner[runner_id] = runner_id in pitcher_scored_by_name.get(responsible, set())

        warnings = self._filter_benign_scored_runner_warnings(
            current_warnings,
            set(actual_scored_ids) | set(current_virtual_scored_ids),
        )
        if warnings:
            self.result.warnings.extend(f"Seq{seq}: {w}" for w in warnings)

        self.result.plays.append(
            NeoPlaySnapshot(
                seq=seq,
                raw_text=line,
                actual_before=actual_before_text,
                actual_after=self.actual_state.base_text(),
                virtual_before=virtual_before_text,
                virtual_after=current_state.base_text(),
                actual_outs_before=actual_outs_before,
                actual_outs_after=self.actual_state.outs_count,
                virtual_outs_before=virtual_outs_before,
                virtual_outs_after=current_state.outs_count,
                actual_moves=actual_moves,
                virtual_moves=current_virtual_moves,
                scored_runner_ids=actual_scored_ids,
                actual_scored_runner_ids=actual_scored_ids,
                virtual_scored_runner_ids=current_virtual_scored_ids,
                actual_scored_runner_facts=actual_scored_facts,
                virtual_scored_runner_facts=[],
                pitcher_virtual_outs_before_by_runner_id=pitcher_before_by_runner,
                pitcher_virtual_outs_after_by_runner_id=pitcher_after_by_runner,
                pitcher_virtual_scored_by_runner_id=pitcher_scored_by_runner,
                pitcher_virtuals_after={
                    name: self._simple_state_text(state)
                    for name, state in self.pitcher_virtual_states.items()
                },
                current_pitcher=pitcher,
                warnings=warnings,
            )
        )
        if self._is_inning_end_line(line):
            self.actual_state.bases = {1: None, 2: None, 3: None}
            for state in self.pitcher_virtual_states.values():
                state.bases = {1: None, 2: None, 3: None}

    def _run_tiebreak_setup(self, seq: int, line: str, pitcher: str) -> None:
        actual_before_text = self.actual_state.base_text()
        virtual_before_text = self.virtual_state.base_text()
        actual_outs_before = self.actual_state.outs_count
        virtual_outs_before = self.virtual_state.outs_count
        text = str(line or "")
        bases: list[int] = []
        if "一、二塁" in text or "満塁" in text:
            bases.extend([1, 2])
        elif "二塁" in text:
            bases.append(2)
        if "満塁" in text:
            bases.append(3)
        for base in bases:
            name = f"タイブレーク{self._base_label(base)}走者"
            self._place_tiebreak_runner(self.actual_state, self.actual_atomic, base, name, pitcher)
            self._place_tiebreak_runner(self.virtual_state, self.virtual_atomic, base, name, pitcher)
        self.result.plays.append(
            NeoPlaySnapshot(
                seq=seq,
                raw_text=line,
                actual_before=actual_before_text,
                actual_after=self.actual_state.base_text(),
                virtual_before=virtual_before_text,
                virtual_after=self.virtual_state.base_text(),
                actual_outs_before=actual_outs_before,
                actual_outs_after=self.actual_state.outs_count,
                virtual_outs_before=virtual_outs_before,
                virtual_outs_after=self.virtual_state.outs_count,
                actual_moves=[],
                virtual_moves=[],
                scored_runner_ids=[],
                actual_scored_runner_ids=[],
                virtual_scored_runner_ids=[],
                actual_scored_runner_facts=[],
                virtual_scored_runner_facts=[],
                warnings=[],
            )
        )

    def _place_tiebreak_runner(
        self, state: RunnerState, atomic: AtomicRunner, base: int, name: str, pitcher: str
    ) -> None:
        atomic.runner_seq += 1
        runner = Runner(
            id=f"R{atomic.runner_seq:03d}",
            name=name,
            responsible_pitcher=pitcher,
            reached_by="タイブレーク開始走者",
            reached_cause_type="tiebreak",
            earned_eligible=False,
            current_base=base,
        )
        runner.history.append("タイブレーク開始走者")
        state.runner_registry.append(runner)
        state.bases[base] = runner

    def _ensure_pitcher_virtual(self, pitcher: str) -> None:
        pitcher = str(pitcher or "P")
        if pitcher in self.pitcher_virtual_states:
            self.virtual_state = self.pitcher_virtual_states[pitcher]
            self.virtual_atomic = self.pitcher_virtual_atomics[pitcher]
            return
        self._start_pitcher_virtual(pitcher)

    def _start_pitcher_virtual(self, pitcher: str) -> None:
        pitcher = str(pitcher or "P")
        state = RunnerState()
        state.copy_from(self.actual_state)
        atomic = AtomicRunner()
        atomic.runner_seq = self.actual_atomic.runner_seq
        self.pitcher_virtual_states[pitcher] = state
        self.pitcher_virtual_atomics[pitcher] = atomic
        self.virtual_state = state
        self.virtual_atomic = atomic

    def _base_label(self, base: int) -> str:
        return {1: "一塁", 2: "二塁", 3: "三塁"}.get(base, f"{base}塁")

    def _simple_state_text(self, state: RunnerState) -> str:
        outs = int(getattr(state, "outs_count", 0) or 0)
        if outs >= 3:
            return "3死"
        out_text = {0: "無死", 1: "1死", 2: "2死"}.get(outs, f"{outs}死")
        bases = []
        if state.bases.get(1) is not None:
            bases.append("一")
        if state.bases.get(2) is not None:
            bases.append("二")
        if state.bases.get(3) is not None:
            bases.append("三")
        if not bases:
            return out_text
        return f"{out_text}{'、'.join(bases)}塁"

    def _scored_runner_fact(self, runner: Runner) -> dict[str, object]:
        return {
            "id": str(getattr(runner, "id", "") or ""),
            "name": str(getattr(runner, "name", "") or ""),
            "responsible_pitcher": str(getattr(runner, "responsible_pitcher", "") or ""),
            "reached_cause_type": str(getattr(runner, "reached_cause_type", "") or ""),
            "reached_by": str(getattr(runner, "reached_by", "") or ""),
            "earned_eligible": bool(getattr(runner, "earned_eligible", True)),
            "score_cause_type": str(getattr(runner, "score_cause_type", "") or ""),
            "score_reason": str(getattr(runner, "score_reason", "") or ""),
        }

    def _build_virtual_moves(
        self,
        play,
        generated: list[Move],
        actual_moves: list[Move],
        actual_before_bases: dict[int, Runner | None],
        virtual_before_bases: dict[int, Runner | None],
    ) -> list[Move]:
        moves: list[Move] = []
        used_sources: set[str] = set()

        by_source: dict[str, Move] = {}
        for mv in actual_moves:
            source = str(getattr(mv, "source", ""))
            if source in by_source:
                continue
            if self.classifier.is_normal_advance(mv):
                by_source[source] = mv

        force_award_moves = self._virtual_force_award_moves(play, actual_moves, virtual_before_bases)
        for mv in force_award_moves:
            source = str(getattr(mv, "source", ""))
            moves.append(mv)
            used_sources.add(source)
        if force_award_moves:
            for mv in actual_moves:
                if str(getattr(mv, "cause_type", "")) in {"walk", "hbp"}:
                    used_sources.add(str(getattr(mv, "source", "")))

        for mv in self._virtual_missing_runner_out_moves(actual_moves, virtual_before_bases, used_sources):
            source = str(getattr(mv, "source", ""))
            moves.append(mv)
            used_sources.add(source)

        for base in (3, 2, 1):
            if str(base) in used_sources:
                continue
            runner = virtual_before_bases.get(base)
            actual_runner = actual_before_bases.get(base)
            if runner is None or actual_runner is None:
                continue
            mv = by_source.get(str(base))
            if mv is None:
                continue
            partial = self._partial_normal_move_for_composite(play, mv, virtual_before_bases, actual_moves)
            if partial is not None:
                moves.append(partial)
                used_sources.add(str(base))
                continue
            if self._is_blocked_virtual_steal(mv, virtual_before_bases, used_sources):
                used_sources.add(str(base))
                continue
            vacate = self._virtual_vacate_occupied_target_move(play, mv, virtual_before_bases, used_sources, actual_moves)
            if vacate is not None:
                moves.append(vacate)
                used_sources.add(str(getattr(vacate, "source", "")))
            moves.append(self._clone_move(mv, reason_suffix=" / Neo same-base Actual"))
            used_sources.add(str(base))

        for mv in self._virtual_partial_normal_moves(play, actual_moves, virtual_before_bases):
            source = str(getattr(mv, "source", ""))
            if source in used_sources:
                continue
            moves.append(mv)
            used_sources.add(source)

        batter_mv = by_source.get("B")
        if batter_mv is not None and "B" not in used_sources:
            moves.append(self._virtual_batter_move_from_actual(play, batter_mv, actual_moves, virtual_before_bases))
            used_sources.add("B")

        for mv in generated:
            source = str(getattr(mv, "source", ""))
            if source in used_sources:
                continue
            if source in {"1", "2", "3"} and virtual_before_bases.get(int(source)) is None:
                continue
            if not self.classifier.is_normal_advance(mv):
                continue
            moves.append(self._clone_move(mv, reason_suffix=" / Neo fallback rule"))
            used_sources.add(source)

        if getattr(play, "is_hit", False):
            hit_bases = self._hit_bases_from_moves_or_text(generated, str(getattr(play, "raw_text", "") or ""))
            final_set = set(getattr(play.final_base_state, "as_set", lambda: set())())
            for base in (3, 2, 1):
                source = str(base)
                if source in used_sources:
                    continue
                if virtual_before_bases.get(base) is None:
                    continue
                if self._should_hold_hit_fallback_runner(
                    base=base,
                    final_set=final_set,
                    hit_bases=hit_bases,
                    actual_moves=actual_moves,
                    actual_before_bases=actual_before_bases,
                    virtual_before_bases=virtual_before_bases,
                ):
                    continue
                target_base = base + hit_bases
                target = "H" if target_base >= 4 else str(target_base)
                moves.append(Move(source, target, f"Neo hit fallback runner advance +{hit_bases}", "hit", True, True, explicit=False))
                used_sources.add(source)

        if self._is_batter_error_reach(play, actual_moves):
            moves = [mv for mv in moves if str(getattr(mv, "source", "")) != "B"]
            moves.append(Move("B", "OUT", "Neo batter error reach converted to out", "out", False, True, explicit=False))

        return self._dedupe_by_source(moves)

    def _virtual_missing_runner_out_moves(
        self,
        actual_moves: list[Move],
        virtual_before_bases: dict[int, Runner | None],
        used_sources: set[str],
    ) -> list[Move]:
        if not any(
            str(getattr(mv, "source", "")) == "B"
            and str(getattr(mv, "target", "")) in {"2", "3"}
            for mv in actual_moves
        ):
            return []
        moves: list[Move] = []
        for actual_mv in actual_moves:
            source = str(getattr(actual_mv, "source", ""))
            if source not in {"1", "2", "3"} or str(getattr(actual_mv, "target", "")) != "OUT":
                continue
            source_base = int(source)
            if virtual_before_bases.get(source_base) is not None:
                continue
            candidates = [
                base
                for base in range(source_base - 1, 0, -1)
                if str(base) not in used_sources and virtual_before_bases.get(base) is not None
            ]
            if not candidates:
                continue
            virtual_source = str(candidates[0])
            moves.append(
                Move(
                    virtual_source,
                    "OUT",
                    "Neo missing actual out runner mapped to lead virtual runner",
                    "out",
                    False,
                    True,
                    explicit=False,
                )
            )
        return moves

    def _virtual_force_award_moves(
        self, play, actual_moves: list[Move], virtual_before_bases: dict[int, Runner | None]
    ) -> list[Move]:
        batter_award = next(
            (
                mv for mv in actual_moves
                if str(getattr(mv, "source", "")) == "B"
                and str(getattr(mv, "target", "")) == "1"
                and str(getattr(mv, "cause_type", "")) in {"walk", "hbp", "fielder_choice"}
            ),
            None,
        )
        if batter_award is None:
            return []
        moves: list[Move] = []
        cause = str(getattr(batter_award, "cause_type", "unknown") or "unknown")
        actual_normal_by_source = {
            str(getattr(mv, "source", "")): mv
            for mv in actual_moves
            if str(getattr(mv, "source", "")) in {"1", "2", "3"}
            and self.classifier.is_normal_advance(mv)
            and str(getattr(mv, "target", "")) not in {"", "OUT"}
        }
        if cause == "fielder_choice":
            if (
                virtual_before_bases.get(1) is not None
                and virtual_before_bases.get(2) is None
                and "1" not in actual_normal_by_source
            ):
                moves.append(Move("1", "2", "Neo fielder-choice force from occupied first", cause, True, True, explicit=False))
                moves.append(self._clone_move(batter_award, reason_suffix=" / Neo fielder-choice batter"))
                return moves
            return []

        def force_or_actual(source: str, target: str) -> Move:
            actual_mv = actual_normal_by_source.get(source)
            if actual_mv is not None and str(getattr(actual_mv, "target", "")) != target:
                return self._clone_move(actual_mv, reason_suffix=" / Neo actual runner advance before force award")
            return Move(source, target, "Neo force award from virtual bases", cause, True, True, explicit=False)

        if virtual_before_bases.get(1) is not None:
            if virtual_before_bases.get(2) is not None and virtual_before_bases.get(3) is not None:
                moves.append(force_or_actual("3", "H"))
            if virtual_before_bases.get(2) is not None:
                moves.append(force_or_actual("2", "3"))
            moves.append(force_or_actual("1", "2"))
        moves.append(self._clone_move(batter_award, reason_suffix=" / Neo force award batter"))
        return moves

    def _virtual_partial_normal_moves(
        self, play, actual_moves: list[Move], virtual_before_bases: dict[int, Runner | None]
    ) -> list[Move]:
        text = str(getattr(play, "raw_text", "") or "")
        moves: list[Move] = []
        force_sources: set[str] = set()
        for mv in actual_moves:
            forced = self._partial_force_move_before_error(mv, virtual_before_bases, actual_moves)
            if forced is None:
                continue
            source = str(getattr(forced, "source", ""))
            if source in force_sources:
                continue
            moves.append(forced)
            force_sources.add(source)
        steal_patterns = [
            ("1", "2", "一塁走者", "二塁"),
            ("2", "3", "二塁走者", "三塁"),
            ("3", "H", "三塁走者", "本塁"),
        ]
        for source, target, runner_word, target_word in steal_patterns:
            if source in force_sources:
                continue
            base = int(source)
            if virtual_before_bases.get(base) is None:
                continue
            if not any(str(getattr(mv, "source", "")) == source and self.classifier.is_virtual_excluded(mv) for mv in actual_moves):
                continue
            if runner_word in text and "盗塁" in text and (target_word in text or target == "H"):
                if self._is_blocked_virtual_steal(
                    Move(source, target, "Neo partial normal advance before error: steal", "steal", True, True, explicit=False),
                    virtual_before_bases,
                ):
                    continue
                moves.append(Move(source, target, "Neo partial normal advance before error: steal", "steal", True, True, explicit=False))
        return moves

    def _partial_normal_move_for_composite(
        self, play, mv: Move, virtual_before_bases: dict[int, Runner | None], actual_moves: list[Move]
    ) -> Move | None:
        text = str(getattr(play, "raw_text", "") or "")
        source = str(getattr(mv, "source", ""))
        target = str(getattr(mv, "target", ""))
        if (
            self.classifier.is_virtual_excluded(mv)
            and source == "3"
            and target == "H"
            and "ゴロ" in text
            and "三塁走者が生還" in text
        ):
            return Move("3", "H", "Neo third runner scores on groundout before error", "out", True, True, explicit=False)
        if self.classifier.is_virtual_excluded(mv):
            hit_move = self._partial_hit_move_before_error(play, mv, virtual_before_bases, actual_moves)
            if hit_move is not None:
                return hit_move
            forced = self._partial_force_move_before_error(mv, virtual_before_bases, actual_moves)
            if forced is not None:
                return forced
        if source not in {"1", "2"} or target not in {"3", "H"}:
            return None
        if "盗塁" not in text:
            return None
        if not any(word in text for word in ["捕逸", "失策", "悪送球", "後逸", "落球", "ファンブル"]):
            return None
        normal_target = "2" if source == "1" else "3"
        candidate = Move(source, normal_target, "Neo partial normal advance before error/pb: steal", "steal", True, True, explicit=False)
        if self._is_blocked_virtual_steal(candidate, virtual_before_bases):
            return None
        return candidate

    def _partial_hit_move_before_error(
        self,
        play,
        mv: Move,
        virtual_before_bases: dict[int, Runner | None],
        actual_moves: list[Move],
    ) -> Move | None:
        source = str(getattr(mv, "source", ""))
        target = str(getattr(mv, "target", ""))
        if source != "1" or target != "H" or not getattr(play, "is_hit", False):
            return None
        hit_bases = self._hit_bases_from_text(str(getattr(play, "raw_text", "") or ""))
        if hit_bases < 2:
            return None
        target_base = int(source) + hit_bases
        if target_base > 3:
            return None
        if virtual_before_bases.get(int(source)) is None:
            return None
        if virtual_before_bases.get(target_base) is not None and not self._base_vacated_by_move(str(target_base), actual_moves):
            return None
        return Move(
            source,
            str(target_base),
            "Neo hit advance before error",
            "hit",
            True,
            True,
            explicit=False,
        )

    def _base_vacated_by_move(self, source: str, moves: list[Move]) -> bool:
        return any(
            str(getattr(mv, "source", "")) == source
            and str(getattr(mv, "target", "")) in {"H", "OUT", "1", "2", "3"}
            and str(getattr(mv, "target", "")) != source
            for mv in moves
        )

    def _partial_force_move_before_error(
        self, mv: Move, virtual_before_bases: dict[int, Runner | None], actual_moves: list[Move]
    ) -> Move | None:
        source = str(getattr(mv, "source", ""))
        target = str(getattr(mv, "target", ""))
        if source not in {"1", "2"} or target not in {"3", "H"}:
            return None
        batter_reaches = any(
            str(getattr(actual_mv, "source", "")) == "B"
            and str(getattr(actual_mv, "target", "")) in {"1", "2", "3"}
            and not self.classifier.is_virtual_excluded(actual_mv)
            for actual_mv in actual_moves
        )
        if not batter_reaches:
            return None
        source_base = int(source)
        if virtual_before_bases.get(source_base) is None:
            return None
        if source == "2" and virtual_before_bases.get(1) is None:
            return None
        normal_target = str(source_base + 1)
        return Move(
            source,
            normal_target,
            "Neo partial normal force advance before error",
            "inferred",
            False,
            True,
            explicit=False,
        )

    def _is_blocked_virtual_steal(
        self, mv: Move, virtual_before_bases: dict[int, Runner | None], vacated_sources: set[str] | None = None
    ) -> bool:
        if str(getattr(mv, "cause_type", "")) != "steal":
            return False
        target = str(getattr(mv, "target", ""))
        if target not in {"1", "2", "3"}:
            return False
        if target in set(vacated_sources or set()):
            return False
        return virtual_before_bases.get(int(target)) is not None

    def _virtual_vacate_occupied_target_move(
        self,
        play,
        mv: Move,
        virtual_before_bases: dict[int, Runner | None],
        used_sources: set[str],
        actual_moves: list[Move] | None = None,
    ) -> Move | None:
        source = str(getattr(mv, "source", ""))
        target = str(getattr(mv, "target", ""))
        cause = str(getattr(mv, "cause_type", "") or "")
        if source not in {"1", "2"} or target not in {"2", "3"}:
            return None
        if target in used_sources:
            return None
        target_base = int(target)
        next_base = target_base + 1
        is_left_on_base_fill = self._is_left_on_base_target_fill(play, target_base, next_base)
        is_batter_out_advance = self._is_batter_out_occupied_target_advance(
            source,
            target,
            play,
            actual_moves or [],
        )
        if cause != "wild_pitch" and not is_left_on_base_fill and not is_batter_out_advance:
            return None
        if next_base > 3:
            return None
        if virtual_before_bases.get(target_base) is None or virtual_before_bases.get(next_base) is not None:
            return None
        final_set = set(getattr(play.final_base_state, "as_set", lambda: set())())
        if cause == "wild_pitch" and next_base not in final_set:
            return None
        if is_left_on_base_fill and not ({target_base, next_base} <= final_set):
            return None
        return Move(
            target,
            str(next_base),
            "Neo occupied target runner advances to match left-on-base final state"
            if is_left_on_base_fill
            else "Neo occupied target runner advances on batter-out advance"
            if is_batter_out_advance
            else "Neo occupied target runner advances on wild pitch",
            cause if cause and not is_batter_out_advance else "inferred",
            True,
            True,
            explicit=False,
        )

    def _is_batter_out_occupied_target_advance(
        self,
        source: str,
        target: str,
        play,
        actual_moves: list[Move],
    ) -> bool:
        text = str(getattr(play, "raw_text", "") or "")
        if source != "1" or target != "2":
            return False
        if not any(
            str(getattr(mv, "source", "")) == "B"
            and str(getattr(mv, "target", "")) == "OUT"
            for mv in actual_moves
        ):
            return False
        if "一塁走者が二塁" not in text:
            return False
        return "打者が封殺" in text or "打者アウト" in text or "スクイズ" in text

    def _is_left_on_base_target_fill(self, play, target_base: int, next_base: int) -> bool:
        text = str(getattr(play, "raw_text", "") or "")
        if not self._is_inning_end_line(text) or "残塁" not in text:
            return False
        final_set = set(getattr(play.final_base_state, "as_set", lambda: set())())
        return {target_base, next_base} <= final_set

    def _virtual_batter_move_from_actual(
        self,
        play,
        mv: Move,
        actual_moves: list[Move],
        virtual_before_bases: dict[int, Runner | None],
    ) -> Move:
        if (
            str(getattr(mv, "source", "")) == "B"
            and str(getattr(mv, "target", "")) == "1"
            and str(getattr(mv, "cause_type", "")) in {"out", "force_out"}
            and not self._virtual_has_runner_out_context(actual_moves, virtual_before_bases)
        ):
            return Move("B", "OUT", "Neo batter reaches on runner out converted to batter out", "out", False, True, explicit=False)
        if (
            str(getattr(mv, "source", "")) == "B"
            and str(getattr(mv, "target", "")) == "1"
            and self._actual_third_runner_out_without_virtual_runner(actual_moves, virtual_before_bases)
        ):
            return Move("B", "OUT", "Neo batter reaches on missing virtual third-runner out", "out", False, True, explicit=False)
        if str(getattr(mv, "cause_type", "")) == "hit" and self._has_error_extra_advance(str(getattr(mv, "reason", ""))):
            hit_bases = self._hit_bases_from_text(str(getattr(play, "raw_text", "") or ""))
            target = "H" if hit_bases >= 4 else str(hit_bases)
            return Move("B", target, "Neo batter hit base before error", "hit", True, True, explicit=False)
        if (
            str(getattr(mv, "source", "")) == "B"
            and str(getattr(mv, "target", "")) in {"2", "3"}
            and str(getattr(mv, "cause_type", "")) == "out"
            and self._has_error_extra_advance(str(getattr(mv, "reason", "")))
        ):
            return Move("B", "1", "Neo batter reaches before error advance", "out", False, True, explicit=False)
        return self._clone_move(mv, reason_suffix=" / Neo same-base Actual")

    def _actual_third_runner_out_without_virtual_runner(
        self, actual_moves: list[Move], virtual_before_bases: dict[int, Runner | None]
    ) -> bool:
        if virtual_before_bases.get(3) is not None:
            return False
        return any(
            str(getattr(mv, "source", "")) == "3"
            and str(getattr(mv, "target", "")) == "OUT"
            for mv in actual_moves
        )

    def _should_hold_hit_fallback_runner(
        self,
        base: int,
        final_set: set[int],
        hit_bases: int,
        actual_moves: list[Move],
        actual_before_bases: dict[int, Runner | None],
        virtual_before_bases: dict[int, Runner | None],
    ) -> bool:
        if base not in final_set:
            return False
        source = str(base)
        if any(str(getattr(mv, "source", "")) == source for mv in actual_moves):
            return False
        actual_runner = actual_before_bases.get(base)
        virtual_runner = virtual_before_bases.get(base)
        if actual_runner is None or virtual_runner is None:
            return False
        return str(getattr(actual_runner, "id", "")) == str(getattr(virtual_runner, "id", ""))

    def _virtual_has_runner_out_context(self, actual_moves: list[Move], virtual_before_bases: dict[int, Runner | None]) -> bool:
        for mv in actual_moves:
            source = str(getattr(mv, "source", ""))
            if source in {"1", "2", "3"} and str(getattr(mv, "target", "")) == "OUT":
                if virtual_before_bases.get(int(source)) is not None:
                    return True
        return False

    def _align_actual_to_final_state(self, play, moves: list[Move], before: BaseState) -> list[Move]:
        """Best-effort final-state alignment for Actual."""
        final_set = set(getattr(play.final_base_state, "as_set", lambda: set())())
        text = str(getattr(play, "raw_text", "") or "")
        if self._is_game_end_line(text):
            return moves
        if not self._has_final_base_occupancy(text):
            filtered = [
                mv for mv in moves
                if str(getattr(mv, "target", "")) not in {"1", "2", "3"}
            ]
            if self._batter_alignment_candidate(text) and not any(
                str(getattr(mv, "source", "")) == "B" for mv in filtered
            ):
                target = self._default_batter_target(text, moves)
                filtered.append(
                    Move("B", target, "Neo Actual no-final-state batter alignment", "inferred", False, True, explicit=False)
                )
            return filtered
        if not final_set:
            if self._is_inning_end_line(str(getattr(play, "raw_text", "") or "")) and "残塁" in str(getattr(play, "raw_text", "") or ""):
                return moves
            return [
                mv for mv in moves
                if str(getattr(mv, "target", "")) not in {"1", "2", "3"}
            ]
        before_set = before.as_set()
        moves = self._retarget_runner_moves_to_final_state(moves, before_set, final_set, int(getattr(play, "runs_scored", 0) or 0))
        occupied_by_runners = {
            int(str(mv.target))
            for mv in moves
            if str(getattr(mv, "source", "")) in {"1", "2", "3"}
            and str(getattr(mv, "target", "")) in {"1", "2", "3"}
        }
        batter_targets = [
            int(str(mv.target))
            for mv in moves
            if str(getattr(mv, "source", "")) == "B"
            and str(getattr(mv, "target", "")) in {"1", "2", "3"}
        ]
        stationary_occupied = self._stationary_final_bases(before_set, moves, final_set, set(batter_targets))
        missing = sorted(final_set - occupied_by_runners - set(batter_targets) - stationary_occupied)
        if batter_targets and missing:
            retargeted = self._retarget_batter_to_missing_final_base(moves, final_set, missing)
            if retargeted is not None:
                return retargeted
        if batter_targets and missing:
            moves = self._add_missing_runner_final_base_moves(moves, before, missing)
            occupied_by_runners = {
                int(str(mv.target))
                for mv in moves
                if str(getattr(mv, "source", "")) in {"1", "2", "3"}
                and str(getattr(mv, "target", "")) in {"1", "2", "3"}
            }
            missing = sorted(final_set - occupied_by_runners - set(batter_targets) - stationary_occupied)
        if batter_targets or not missing:
            return moves
        if self._batter_alignment_candidate(text) and not any(
            str(getattr(mv, "source", "")) == "B" for mv in moves
        ):
            target = str(min(missing))
            return moves + [Move("B", target, "Neo Actual final-state batter alignment", "inferred", False, True, explicit=False)]
        return moves

    def _retarget_batter_to_missing_final_base(
        self,
        moves: list[Move],
        final_set: set[int],
        missing: list[int],
    ) -> list[Move] | None:
        batter_indexes = [
            idx
            for idx, mv in enumerate(moves)
            if str(getattr(mv, "source", "")) == "B"
            and str(getattr(mv, "target", "")) in {"1", "2", "3"}
        ]
        if len(batter_indexes) != 1:
            return None
        idx = batter_indexes[0]
        old = moves[idx]
        if str(getattr(old, "cause_type", "")) not in {"field_error", "passed_ball", "interference"}:
            return None
        current_target = int(str(getattr(moves[idx], "target", "0")))
        if current_target in final_set:
            return None
        target = next((base for base in missing if base >= current_target), None)
        if target is None:
            return None
        adjusted = list(moves)
        adjusted[idx] = Move(
            "B",
            str(target),
            "Neo Actual final-state batter retarget",
            str(getattr(old, "cause_type", "") or "inferred"),
            bool(getattr(old, "pitcher_charge", False)),
            bool(getattr(old, "virtual_allow", True)),
            explicit=False,
        )
        return adjusted

    def _batter_alignment_candidate(self, text: str) -> bool:
        raw = str(text or "")
        has_batter_subject = bool(re.match(r"^\s*[0-9０-９]+番", raw)) or "打者が" in raw
        if not has_batter_subject:
            return False
        return self._batter_may_occupy_final_base(raw)

    def _batter_may_occupy_final_base(self, text: str) -> bool:
        raw = str(text or "")
        return any(
            word in raw
            for word in [
                "出塁",
                "安打",
                "適時打",
                "内野安打",
                "二塁打",
                "三塁打",
                "本塁打",
                "四球",
                "死球",
                "失策により出塁",
                "悪送球により出塁",
                "落球により出塁",
                "後逸により出塁",
                "ファンブルにより出塁",
            ]
        )

    def _default_batter_target(self, text: str, moves: list[Move]) -> str:
        raw = str(text or "")
        if "打者が" in raw and ("三塁へ" in raw or "三塁に" in raw):
            return "3"
        if "打者が" in raw and ("二塁へ" in raw or "二塁に" in raw):
            return "2"
        hit_bases = self._hit_bases_from_moves_or_text(moves, raw)
        if hit_bases >= 3:
            return "3"
        if hit_bases == 2:
            return "2"
        return "1"

    def _retarget_runner_moves_to_final_state(
        self, moves: list[Move], before_set: set[int], final_set: set[int], runs_scored: int
    ) -> list[Move]:
        adjusted = list(moves)
        adjusted = self._fix_stationary_runner_collisions(adjusted, before_set, final_set)
        adjusted = self._fix_extra_scoring_runner_moves(adjusted, before_set, final_set, runs_scored)
        return adjusted

    def _fix_stationary_runner_collisions(self, moves: list[Move], before_set: set[int], final_set: set[int]) -> list[Move]:
        moved_sources = {
            int(str(getattr(mv, "source", "")))
            for mv in moves
            if str(getattr(mv, "source", "")) in {"1", "2", "3"}
        }
        stationary = before_set - moved_sources
        if not stationary:
            return moves
        result: list[Move] = []
        for idx, mv in enumerate(moves):
            source = str(getattr(mv, "source", ""))
            target = str(getattr(mv, "target", ""))
            if source not in {"1", "2", "3"} or target not in {"1", "2", "3"}:
                result.append(mv)
                continue
            source_base = int(source)
            target_base = int(target)
            if target_base not in stationary:
                result.append(mv)
                continue
            used_targets = self._used_final_targets(moves, exclude_index=idx) | stationary
            candidate = self._choose_missing_target(final_set, used_targets, source_base)
            if candidate is None:
                result.append(mv)
            elif candidate == source_base:
                continue
            else:
                result.append(Move(source, str(candidate), "Neo Actual final-state runner retarget", "inferred", False, True, explicit=False))
        return result

    def _fix_extra_scoring_runner_moves(
        self, moves: list[Move], before_set: set[int], final_set: set[int], runs_scored: int
    ) -> list[Move]:
        scoring_indexes = [
            idx
            for idx, mv in enumerate(moves)
            if str(getattr(mv, "source", "")) in {"1", "2", "3"}
            and str(getattr(mv, "target", "")) == "H"
        ]
        extra_count = len(scoring_indexes) - max(0, runs_scored)
        if extra_count <= 0:
            return moves
        keep = set(
            sorted(
                scoring_indexes,
                key=lambda idx: int(str(getattr(moves[idx], "source", "0"))),
                reverse=True,
            )[: max(0, runs_scored)]
        )
        result: list[Move] = []
        stationary = before_set - {
            int(str(getattr(mv, "source", "")))
            for mv in moves
            if str(getattr(mv, "source", "")) in {"1", "2", "3"}
        }
        used_targets = self._used_final_targets(moves, exclude_indexes=set(scoring_indexes) - keep) | stationary
        for idx, mv in enumerate(moves):
            if idx not in scoring_indexes or idx in keep:
                result.append(mv)
                continue
            source_base = int(str(getattr(mv, "source", "0")))
            candidate = self._choose_missing_target(final_set, used_targets, source_base)
            if candidate is None:
                continue
            used_targets.add(candidate)
            if candidate == source_base:
                continue
            result.append(Move(str(source_base), str(candidate), "Neo Actual final-state scoring retarget", "inferred", False, True, explicit=False))
        return result

    def _used_final_targets(
        self, moves: list[Move], exclude_index: int | None = None, exclude_indexes: set[int] | None = None
    ) -> set[int]:
        excluded = set(exclude_indexes or set())
        if exclude_index is not None:
            excluded.add(exclude_index)
        return {
            int(str(getattr(mv, "target", "")))
            for idx, mv in enumerate(moves)
            if idx not in excluded and str(getattr(mv, "target", "")) in {"1", "2", "3"}
        }

    def _choose_missing_target(self, final_set: set[int], used_targets: set[int], source_base: int) -> int | None:
        candidates = sorted(base for base in final_set - used_targets if base >= source_base)
        if candidates:
            return candidates[0]
        candidates = sorted(final_set - used_targets)
        return candidates[0] if candidates else None

    def _stationary_final_bases(
        self, before_set: set[int], moves: list[Move], final_set: set[int], batter_targets: set[int]
    ) -> set[int]:
        moved_sources = {
            int(str(getattr(mv, "source", "")))
            for mv in moves
            if str(getattr(mv, "source", "")) in {"1", "2", "3"}
        }
        occupied_targets = {
            int(str(getattr(mv, "target", "")))
            for mv in moves
            if str(getattr(mv, "target", "")) in {"1", "2", "3"}
        }
        return {
            base
            for base in before_set - moved_sources
            if base in final_set and base not in occupied_targets and base not in batter_targets
        }

    def _add_missing_runner_final_base_moves(self, moves: list[Move], before: BaseState, missing: list[int]) -> list[Move]:
        used_sources = {
            str(getattr(mv, "source", ""))
            for mv in moves
            if str(getattr(mv, "source", "")) in {"1", "2", "3"}
        }
        additions: list[Move] = []
        for source in sorted(before.as_set(), reverse=True):
            source_text = str(source)
            if source_text in used_sources:
                continue
            target = next((base for base in missing if base > source), None)
            if target is None:
                continue
            additions.append(
                Move(source_text, str(target), "Neo Actual final-state runner alignment", "inferred", False, True, explicit=False)
            )
            used_sources.add(source_text)
            missing.remove(target)
            if not missing:
                break
        return moves + additions

    def _has_final_base_occupancy(self, text: str) -> bool:
        tail = str(text or "")
        markers = ["無死", "１死", "２死", "３死"]
        cut = -1
        for marker in markers:
            pos = tail.rfind(marker)
            if pos > cut:
                cut = pos
        if cut >= 0:
            tail = tail[cut:]
        if "チェンジ" in tail:
            return "残塁" in tail
        return any(
            word in tail
            for word in ["一塁", "二塁", "三塁", "一、二塁", "一、三塁", "二、三塁", "満塁"]
        )

    def _is_batter_error_reach(self, play, actual_moves: list[Move]) -> bool:
        if getattr(play, "is_hit", False):
            return False
        for mv in actual_moves:
            if str(getattr(mv, "source", "")) == "B" and str(getattr(mv, "target", "")) in {"1", "2", "3", "H"}:
                if self.classifier.is_virtual_excluded(mv):
                    return True
        return False

    def _base_state(self, state: RunnerState) -> BaseState:
        return BaseState(
            first="1" if state.bases.get(1) is not None else None,
            second="2" if state.bases.get(2) is not None else None,
            third="3" if state.bases.get(3) is not None else None,
        )

    def _remove_runner_ids_from_bases(self, state: RunnerState, runner_ids: set[str]) -> None:
        if not runner_ids:
            return
        for base, runner in list(state.bases.items()):
            if runner is not None and str(getattr(runner, "id", "")) in runner_ids:
                state.bases[base] = None

    def _filter_benign_scored_runner_warnings(self, warnings: list[str], scored_runner_ids: set[str]) -> list[str]:
        if not warnings or not scored_runner_ids:
            return warnings
        filtered: list[str] = []
        for warning in warnings:
            text = str(warning or "")
            ids = re.findall(r"R\d{3}", text)
            existing_id = ids[0] if ids else ""
            if existing_id and existing_id in scored_runner_ids and ("既存走者あり" in text or "譌｢蟄倩ｵｰ閠" in text):
                continue
            filtered.append(warning)
        return filtered

    def _clone_move(self, mv: Move, reason_suffix: str = "") -> Move:
        return Move(
            str(getattr(mv, "source", "")),
            str(getattr(mv, "target", "")),
            f"{getattr(mv, 'reason', '')}{reason_suffix}",
            str(getattr(mv, "cause_type", "unknown") or "unknown"),
            bool(getattr(mv, "pitcher_charge", False)),
            bool(getattr(mv, "virtual_allow", True)),
            bool(getattr(mv, "explicit", True)),
        )

    def _dedupe_by_source(self, moves: list[Move]) -> list[Move]:
        result: list[Move] = []
        seen: set[str] = set()
        for mv in moves:
            source = str(getattr(mv, "source", ""))
            if source in seen:
                continue
            seen.add(source)
            result.append(mv)
        return result

    def _hit_bases_from_moves_or_text(self, moves: list[Move], text: str) -> int:
        text_bases = self._hit_bases_from_text(text)
        if text_bases > 0:
            return text_bases
        for mv in moves:
            if str(getattr(mv, "source", "")) == "B":
                target = str(getattr(mv, "target", ""))
                if target == "H":
                    return 4
                if target in {"1", "2", "3"}:
                    return int(target)
        return 1

    def _hit_bases_from_text(self, text: str) -> int:
        raw = str(text or "")
        if "本塁打" in raw or "ホームラン" in raw or "ランニングホームラン" in raw:
            return 4
        if any(k in raw for k in ["左二適時打", "中二適時打", "右二適時打", "左中間二適時打", "右中間二適時打"]):
            return 2
        if "三塁打" in raw:
            return 3
        if "二塁打" in raw:
            return 2
        if any(word in raw for word in ["単打", "適時打", "内野安打", "バントヒット", "安打"]):
            return 1
        return 0

    def _has_error_extra_advance(self, text: str) -> bool:
        raw = str(text or "")
        return any(word in raw for word in ["失策", "悪送球", "後逸", "落球", "ファンブル"])

    def _default_hit_bases(self, text: str) -> int:
        hit_bases = self._hit_bases_from_text(text)
        if hit_bases > 0:
            return hit_bases
        return 1

    def _guess_batter(self, line: str) -> str:
        text = str(line or "")
        m = re.match(r"^\s*\d+番(?P<name>\S+)", text)
        if m:
            return m.group("name")
        return "打者"

    def _is_batter_out_play(self, line: str, moves: list[Move]) -> bool:
        if any(str(getattr(mv, "target", "")) == "OUT" for mv in moves):
            return False
        if any(str(getattr(mv, "source", "")) == "B" and str(getattr(mv, "target", "")) in {"1", "2", "3", "H"} for mv in moves):
            return False
        text = str(line or "")
        non_batter_words = ["暴投", "捕逸", "盗塁成功", "盗塁死", "走塁死", "牽制死", "ボーク"]
        if any(word in text for word in non_batter_words):
            return False
        if any(word in text for word in ["安打", "適時打", "二塁打", "三塁打", "本塁打", "ホームラン", "バントヒット"]):
            return False
        if any(word in text for word in ["犠打", "犠飛", "送りバント成功", "スクイズバント成功", "スクイズ成功"]):
            return True
        if "スリーバンド失敗" in text:
            return True
        out_words = ["三振", "空振り三振", "見逃し三振", "飛", "直", "ゴロ", "併殺"]
        if self._is_inning_end_line(line) and not any(word in text for word in ["四球", "死球", "失策", "出塁"]):
            return True
        return any(word in text for word in out_words)

    def _is_inning_end_line(self, line: str) -> bool:
        text = str(line or "")
        return ("チェンジ" in text and "チェンジアップ" not in text) or "試合終了" in text

    def _is_game_end_line(self, line: str) -> bool:
        text = str(line or "")
        return any(word in text for word in ["試合終了", "サヨナラ", "コールド"])

    def _is_administrative_line(self, line: str) -> bool:
        text = str(line or "").strip()
        return (
            not text
            or text.startswith("#")
            or text.startswith("マウンド ")
            or "守備位置変更" in text
            or "守備交代" in text
            or "代打" in text
            or "代走" in text
            or "投手交代" in text
            or "先発は" in text
            or ("タイブレーク" in text and not self._is_tiebreak_runner_setup_line(text))
        )

    def _is_tiebreak_runner_setup_line(self, text: str) -> bool:
        return "タイブレーク" in text and ("一、二塁" in text or "二塁" in text or "満塁" in text)
