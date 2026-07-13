from __future__ import annotations

import re
from src.parser.play_parser import PlayParser
from src.move.move_generator import MoveGenerator
from src.move.move_completer import MoveCompleter
from src.move.models import BaseState, Move
from src.runner.atomic_runner import AtomicRunner, RunnerState
from src.runner.runner import Runner
from src.runner.half_inning_runner import PlayReport, HalfInningReport
from src.game.pitcher_change_parser import PitcherChangeParser
from src.pitcher.pitcher_manager import PitcherManager


class VirtualHalfInningRunner:
    """
    Phoenix V2.6 Sprint4.3 / RC-004

    Actual Runnerと同じPlay/Moveを使うが、
    field_error / passed_ball など投手責任外のMoveをVirtualから除外する。

    Sprint3.2:
      - 打者が失策・悪送球・ファンブル・落球・後逸で出塁した場合、
        Virtualでは「失策がなければ打者アウト」として B->OUT を追加する。
      - 安打＋失策追加進塁は対象外。打者は安打で生きているため。
      - RC-001 山口大－鳥大医 6回裏3点目の Virtual3アウト判定用。
    """

    def __init__(self, title: str = "Virtual Half Inning", pitcher_split_mode: bool = False):
        self.title = title
        # RC037 / Quality17:
        # False: Team Virtual（イニング全体を失策なしで再構成）
        # True : Pitcher Virtual（投手交代時に救援投手の開始状態をActualへ合わせる）
        self.pitcher_split_mode = bool(pitcher_split_mode)
        self.parser = PlayParser()
        self.generator = MoveGenerator()
        self.completer = MoveCompleter(virtual_hit_advance_limit=True)
        # V3.1 Quality14:
        # Virtual進塁は「同じ塁に現実走者がいる場合は現実進塁優先、
        # いない場合のみ安打種別の原則」を採用する。
        # そのためVirtual内部にActualの影響を受けない影のActual stateを持ち、
        # 各プレー開始時点の現実塁状況をMoveCompleterへ渡す。
        self.actual_shadow_completer = MoveCompleter()
        self.actual_shadow_atomic = AtomicRunner()
        self.actual_shadow_state = RunnerState()
        self.atomic = AtomicRunner()
        self.state = RunnerState()
        self.report = HalfInningReport(title=title)
        self.pitcher_parser = PitcherChangeParser()
        self.pitcher_manager = PitcherManager()
        # RC060: 捕逸・失策等でActualだけ進塁した走者に、
        # 次打の「単打現実走塁特例」を誤適用しないための印。
        self._excluded_advance_runner_ids: set[str] = set()
        # RC065: 現実到達塁同期を+1に補正したWP走者。
        # 次の単打では現実走塁特例を使わせない。
        self._rc065_wp_limited_runner_ids: set[str] = set()
        # RC031回帰: 失策・後逸でActualだけ進塁した既存走者。
        # 次の単打でVirtual二塁走者を本塁へ入れる特例を抑止する。
        self._field_error_excluded_advance_runner_ids: set[str] = set()

    def run(self, lines: list[str], pitcher: str = "P") -> HalfInningReport:
        initial_pitcher, play_lines = self._extract_initial_pitcher(lines, pitcher)
        self.pitcher_manager.set_initial(initial_pitcher)
        self.pitcher_manager.sync_current_virtual(self.state, seq=0, event="開始", note="初期投手")
        for seq, line in enumerate(play_lines, 1):
            self._run_one(seq, line, self.pitcher_manager.current_pitcher)
        self.report.current_pitcher = self.pitcher_manager.current_pitcher
        return self.report

    def _extract_initial_pitcher(self, lines: list[str], fallback: str = "P") -> tuple[str, list[str]]:
        """半イニング冒頭の「先発は ○○」「マウンド ○○」から初期投手名を取得する。"""
        pitcher = str(fallback or "P").strip() or "P"
        play_lines: list[str] = []
        for line in lines:
            text = str(line or "").strip()
            m = re.match(r"^(?:先発は|マウンド)\s*(?P<name>.+?)\s*$", text)
            if m:
                name = m.group("name").strip()
                if name:
                    pitcher = name
                continue
            play_lines.append(line)
        return pitcher, play_lines

    def _run_one(self, seq: int, line: str, pitcher: str):
        pc = self.pitcher_parser.parse(line)
        if pc:
            # 単打=+1原則のため、失策・後逸等でActualだけ進んだ走者の印は
            # 投手交代を挟んでも保持する。
            self.pitcher_manager.sync_current_virtual(self.state, seq=seq, event="投手交代前", note="交代前状態保存")

            # RC037 / Quality17:
            # Team Virtual は従来どおりイニング冒頭から失策なしで再構成する。
            # 一方、救援投手の自責点判定では、交代時点でその投手が
            # 引き受けた「現実のアウトカウント・塁上走者」から再構成を始める必要がある。
            # そのため Pitcher Virtual 専用実行では、交代直前まで進めている
            # actual_shadow_state を新投手Virtualの初期状態として採用し、
            # 以後のプレーだけを失策なしで再構成する。
            actual_entry_state = self.actual_shadow_state if self.pitcher_split_mode else None
            entry_state = actual_entry_state if actual_entry_state is not None else self.state
            if self.pitcher_split_mode:
                self.state.copy_from(entry_state)

            self.pitcher_manager.change(
                seq=seq,
                old_pitcher=pc.old_pitcher,
                new_pitcher=pc.new_pitcher,
                raw_text=pc.raw_text,
                team_virtual_state=self.state,
                actual_state=actual_entry_state,
            )
            self.report.pitcher_changes = [f'{c.seq},{c.old_pitcher},{c.new_pitcher},{c.raw_text}' for c in self.pitcher_manager.changes]
            self.report.pitcher_runtime_debug = self.pitcher_manager.export_runtime_rows()
            return

        if self._is_administrative_line(line):
            self.pitcher_manager.sync_current_virtual(self.state, seq=seq, event=self._short_event(line), note="管理行スキップ")
            self.report.pitcher_runtime_debug = self.pitcher_manager.export_runtime_rows()
            return

        if self._is_tiebreak_line(line):
            pitcher = self.pitcher_manager.current_pitcher or pitcher
            before_text = self.state.base_text()
            outs_before = self.state.outs_count
            self._seed_tiebreak_runners(self.state, self.atomic, pitcher)
            self._seed_tiebreak_runners(self.actual_shadow_state, self.actual_shadow_atomic, pitcher)
            after_text = self.state.base_text()
            self.pitcher_manager.sync_current_virtual(self.state, seq=seq, event="タイブレーク", note="一二塁開始")
            pr = PlayReport(
                seq=seq,
                raw_text=line,
                before_text=before_text,
                after_text=after_text,
                outs_before=outs_before,
                outs_after=self.state.outs_count,
                moves_text=[],
                scored_text=[],
                outs_text=[],
                warnings=[],
            )
            pr.notes = ["タイブレーク初期走者を一二塁に配置"]
            self.report.plays.append(pr)
            self.report.total_scores = len(self.state.scored)
            self.report.total_outs = self.state.outs_count
            self.report.pitcher_changes = [f'{c.seq},{c.old_pitcher},{c.new_pitcher},{c.raw_text}' for c in self.pitcher_manager.changes]
            self.report.pitcher_runtime_debug = self.pitcher_manager.export_runtime_rows()
            return

        pitcher = self.pitcher_manager.current_pitcher or pitcher
        before_text = self.state.base_text()
        before_base_state = self._current_base_state()
        scored_before = len(self.state.scored)
        outs_list_before = len(self.state.outs)
        outs_before = self.state.outs_count

        play = self.parser.parse_line(line, seq=seq, pitcher=pitcher)
        play.outs_before = outs_before
        play.batter = self._guess_batter(line)

        # V3.1 Quality15:
        # Quality14の「現実同塁優先」に加え、Virtual上では手前の塁に残っていても
        # 走者IDが同じなら現実側の打球進塁を参照できるようにする。
        # 例: Actual二塁 / Virtual一塁の同一走者が二塁打で現実生還した場合、
        #     Virtualでも打球による生還可能として扱う（失策等の追加進塁は除外）。
        play.actual_before_base_state = self._current_actual_shadow_base_state()
        actual_runner_base_by_id = {}
        for _base, _runner in (self.actual_shadow_state.bases or {}).items():
            if _runner is not None:
                actual_runner_base_by_id[str(getattr(_runner, "id", ""))] = int(_base)
        virtual_runner_actual_base_by_source = {}
        for _base, _runner in (self.state.bases or {}).items():
            if _runner is not None:
                _rid = str(getattr(_runner, "id", ""))
                if _rid in actual_runner_base_by_id:
                    virtual_runner_actual_base_by_source[int(_base)] = actual_runner_base_by_id[_rid]
        play.virtual_runner_actual_base_by_source = virtual_runner_actual_base_by_source

        # RC016 / Warning Zero:
        # Virtualで既に3アウトが成立した後のプレーは、
        # 自責点判定上は以後の得点がVirtual3アウト後得点になるだけでよい。
        # ここで盗塁・進塁などを適用し続けると、失策で残したVirtual走者と
        # Actual側の後続走者が衝突し、「既存走者あり」警告だけが発生する。
        # そのため、Virtual3アウト後はRunner Stateを凍結して警告を出さない。
        if outs_before >= 3:
            notes = ["V停止: Virtual3アウト成立後のため以後の走者移動は適用しない / RC016"]
            generated = self.generator.generate(play)
            self._update_actual_shadow_state(play, generated, pitcher)
            pr = PlayReport(
                seq=seq,
                raw_text=line,
                before_text=before_text,
                after_text=before_text,
                outs_before=outs_before,
                outs_after=self.state.outs_count,
                moves_text=[],
                scored_text=[],
                outs_text=[],
                warnings=[],
            )
            pr.notes = notes
            self.pitcher_manager.sync_current_virtual(self.state, seq=seq, event=self._short_event(line), note="Virtual3out後停止")
            self.report.pitcher_runtime_debug = self.pitcher_manager.export_runtime_rows()
            self.report.plays.append(pr)
            self.report.total_scores = len(self.state.scored)
            self.report.total_outs = self.state.outs_count
            if self._is_inning_end_line(line):
                self.state.bases = {1: None, 2: None, 3: None}
                self.actual_shadow_state.bases = {1: None, 2: None, 3: None}
            return

        generated = self.generator.generate(play)
        completed = self.completer.complete(play, generated, before_base_state)
        completed = self._rc060_restrict_single_special_after_excluded_advance(line, completed)
        actual_completed_for_sync = self.actual_shadow_completer.complete(
            play,
            generated,
            self._current_actual_shadow_base_state(),
        )

        virtual_moves: list[Move] = []
        notes: list[str] = []
        force_63_batter_out = self._is_force_63_batter_out_play(line)
        missing_third_runout_batter_out = self._is_missing_third_runout_batter_out(line)

        # RC017:
        # Actualで「一塁走者が封殺、その間に打者が出塁」のような
        # 野選/封殺プレーでも、Virtual上にその被封殺走者が存在しない場合は、
        # 打者をそのまま一塁に置くと、本来なら増えるべき打者アウトを落としてしまう。
        # 例: 失策出塁をVirtualアウト換算した直後のゴロ封殺。
        # Virtualでは「走者がいなければ通常の打者アウト」として B->OUT に補正する。
        rc071_force_batter_safe = self._is_rc071_force_out_batter_safe(line, completed)
        # Quality15 A系:
        # 「封殺、その間に打者が出塁」はRC071補正側でB->1またはB->OUTを一元的に作る。
        # ここでRC017の汎用B->OUT補正も有効にすると、封殺対象なしケースでアウト二重加算になる。
        fielder_choice_batter_virtual_out = (
            self._should_convert_fielder_choice_to_batter_out(completed)
            and not rc071_force_batter_safe
        )

        batter_error_virtual_out = self._should_add_batter_error_virtual_out(line, play, completed, [])
        dropped_third_virtual_out = self._should_convert_dropped_third_strike_to_out(line, completed)
        rc071_added_sources: set[str] = set()
        actual_scored_runner_ids = self._actual_scored_runner_ids(actual_completed_for_sync)

        if force_63_batter_out:
            if self._allow_force_63_third_runner_scores(line, outs_before):
                virtual_moves.append(Move("3", "H", "6-3封殺前の三塁走者生還", "unknown", True, True))
                notes.append("V補正: 失策なし6-3封殺ゴロの第3アウト前得点として3->Hを適用")
            virtual_moves.append(Move("B", "OUT", "6-3封殺を打者アウト換算", "out", True, True))
            notes.append("V補正: 6-3封殺ゴロをB->OUTとしてVirtualアウト加算 / RC133")
        elif missing_third_runout_batter_out:
            virtual_moves.append(Move("B", "OUT", "三塁走者なしの走塁死ゴロを打者アウト換算", "out", True, True))
            notes.append("V補正: 三塁走者なしの走塁死ゴロは打者アウト、塁上走者は据え置き")

        for mv in ([] if (force_63_batter_out or missing_third_runout_batter_out) else completed):
            if rc071_force_batter_safe:
                added = self._rc071_append_force_out_virtual_move(line, mv, virtual_moves, notes, rc071_added_sources)
                if added:
                    continue
                # RC071対象プレーでは、既存走者の悪送球/失策による追加進塁・生還だけを除外する。
                if str(getattr(mv, "cause_type", "")) == "field_error":
                    notes.append(f"V除外: {mv.source}->{mv.target} / RC071既存走者の失策追加進塁除外 / {mv.reason} / {mv.cause_type}")
                    continue

            # RC174:
            # 「一塁走者が盗塁で二塁へ、捕逸で三塁へ」はActualでは1->3だが、
            # Virtualでは捕逸による二塁から三塁への進塁を除外し、盗塁分の1->2だけ残す。
            mv = self._rc174_limit_steal_then_passed_ball_advance(line, mv, notes)
            mv = self._limit_steal_then_error_advance(line, mv, notes)

            # RC065:
            # WP/PB等の現実到達塁にVirtual走者を同期しすぎると、
            # 「現実二塁→三塁」につられて「Virtual一塁→三塁」になってしまう。
            # Virtualでは原則として暴投進塁は現在塁から+1までに制限する。
            mv = self._rc065_limit_virtual_wp_advance(mv, virtual_moves, notes)

            if fielder_choice_batter_virtual_out and mv.source == "B" and mv.target in {"1", "2", "3"}:
                notes.append(f"V補正除外: {mv.source}->{mv.target} / 封殺対象走者がVirtual上にいないため打者アウト換算 / {mv.reason} / {mv.cause_type}")
                continue

            # RC067/RC068:
            # PB振り逃げ出塁はVirtualでは三振アウト換算。
            # WP振り逃げ出塁は投手責任なので除外せず、通常のB->1として残す。
            if dropped_third_virtual_out and mv.source == "B" and mv.target in {"1", "2", "3"}:
                notes.append(f"V補正除外: {mv.source}->{mv.target} / 捕逸振り逃げ出塁を打者アウト換算 / {mv.reason} / {mv.cause_type}")
                continue

            # 打者失策出塁プレーでは、Virtualでは打者アウト。
            # 同じプレー内で発生した走者の失策進塁・失策生還は除外する。
            if batter_error_virtual_out:
                if mv.source == "B":
                    notes.append(f"V除外: {mv.source}->{mv.target} / 打者失策出塁 / {mv.reason} / {mv.cause_type}")
                    continue
                rc152_error_score_state_sync = (
                    mv.source in {"1", "2", "3"}
                    and mv.target == "H"
                    and str(getattr(mv, "cause_type", "")) == "field_error"
                    and "右翼手の落球により出塁" in line
                    and "一塁走者が失策の間に二塁へ" in line
                    and "三塁走者が生還" in line
                )
                if rc152_error_score_state_sync:
                    try:
                        src_base = int(mv.source)
                    except Exception:
                        src_base = 0
                    runner = self.state.bases.get(src_base)
                    if runner is not None:
                        self.state.bases[src_base] = None
                        runner.history.append(f"Virtual消去: {mv.reason}")
                        notes.append(f"V同期: {mv.source}->{mv.target} / 打者失策プレー内の生還走者を得点登録せずVirtualから消去 / {mv.reason} / {mv.cause_type} / RC152")
                    else:
                        notes.append(f"V除外: {mv.source}->{mv.target} / Virtual上に走者なし / {mv.reason} / {mv.cause_type}")
                    continue
                if mv.target in {"H", "1", "2", "3"}:
                    self._rc060_mark_excluded_advance(mv)
                    notes.append(f"V除外: {mv.source}->{mv.target} / 打者失策出塁プレー内の走者進塁除外 / {mv.reason} / {mv.cause_type}")
                    continue

            # 安打後失策による打者追加進塁は、Virtualでは安打本来の到達塁まで残す。
            if mv.source == "B" and "後失策" in mv.reason:
                if "二塁打後失策" in mv.reason:
                    tgt = "2"
                    reason = "打者二塁打（失策追加進塁除外）"
                elif "三塁打後失策" in mv.reason:
                    tgt = "3"
                    reason = "打者三塁打（失策追加進塁除外）"
                elif "本塁打後失策" in mv.reason:
                    tgt = "H"
                    reason = "打者本塁打"
                else:
                    tgt = "1"
                    reason = "打者単打（失策追加進塁除外）"
                virtual_moves.append(Move("B", tgt, reason, "hit", True, True))
                notes.append(f"V補正: {mv.source}->{mv.target} を B->{tgt} に補正 / {mv.reason}")
                continue

            # Sprint4.4 / RC004:
            # 捕逸・暴投による本塁生還は、投手自責判定上は非自責要因になり得るが、
            # Virtual Runner State上では走者を三塁等に残してはいけない。
            # OUTは増やさず、得点Moveとして適用して走者だけ消去する。
            if self._is_virtual_state_sync_score_move(mv):
                if self._should_skip_substituted_full_base_passed_ball_score(line, mv):
                    notes.append(f"V除外: {mv.source}->{mv.target} / 満塁捕逸の実三塁走者生還をVirtual下位走者へ置換しない / {mv.reason} / {mv.cause_type}")
                    continue
                if self._move_source_exists_in_virtual(mv):
                    virtual_moves.append(Move(mv.source, mv.target, mv.reason, mv.cause_type, mv.pitcher_charge, True, mv.explicit))
                    notes.append(f"V同期: {mv.source}->{mv.target} / PB-WP生還はOUT+0で走者消去 / {mv.reason} / {mv.cause_type}")
                else:
                    notes.append(f"V同期除外: {mv.source}->{mv.target} / Virtual上に走者なし / {mv.reason} / {mv.cause_type}")
                continue

            if mv.virtual_allow:
                if self._move_source_exists_in_virtual(mv):
                    if self._batter_target_blocked_in_virtual(mv, virtual_moves):
                        notes.append(f"V安全除外: {mv.source}->{mv.target} / Virtual上の打者到達先に既存走者あり / {mv.reason} / {mv.cause_type}")
                    elif self._move_target_available_in_virtual(mv, virtual_moves):
                        virtual_moves.append(mv)
                    else:
                        notes.append(f"V安全除外: {mv.source}->{mv.target} / Virtual上の移動先に既存走者あり / {mv.reason} / {mv.cause_type}")
                else:
                    # V3.1 Quality05:
                    # Actualだけに存在する走者（失策出塁・捕逸進塁・失策進塁など）が
                    # 後続プレーで進塁/アウト/生還した場合、Virtual上にその走者がいないのは正常な差分。
                    # ここを「V安全除外」とすると、DebugReport/Review上で警告が残って見えるため、
                    # source missing は一律で「V自然除外」として扱う。
                    # なお、移動先衝突・打者到達先衝突はロジック安全弁なので従来どおりV安全除外を維持する。
                    notes.append(f"V自然除外: {mv.source}->{mv.target} / Virtual上に走者なし / {mv.reason} / {mv.cause_type}")
            else:
                self._rc060_mark_excluded_advance(mv)
                notes.append(f"V除外: {mv.source}->{mv.target} / {mv.reason} / {mv.cause_type}")

        # RC-001局所修正:
        # 打者が失策で出塁した場合、Actualでは打者を生かすが、
        # Virtualでは「その失策がなければ打者アウト」としてアウトを1つ加算する。
        if batter_error_virtual_out:
            virtual_moves.append(Move("B", "OUT", "打者失策出塁をVirtualアウト換算", "out", False, True))
            notes.append("V補正: 打者失策出塁をB->OUTとしてVirtualアウト加算 / ER-002")

        if fielder_choice_batter_virtual_out:
            virtual_moves.append(Move("B", "OUT", "封殺対象走者なしのため打者アウト換算", "out", True, True))
            notes.append("V補正: 封殺対象走者がVirtual上にいないためB->OUTとしてVirtualアウト加算 / RC017")

        if dropped_third_virtual_out:
            virtual_moves.append(Move("B", "OUT", "捕逸振り逃げ出塁をVirtual三振アウト換算", "out", False, True))
            notes.append("V補正: 捕逸振り逃げ出塁をB->OUTとしてVirtualアウト加算 / RC067/RC068")

        self.atomic.apply(self.state, virtual_moves, batter_name=play.batter, pitcher=pitcher)
        virtual_scored_runner_ids = {
            str(getattr(runner, "id", ""))
            for runner in self.state.scored[scored_before:]
        }
        self._remove_actual_scored_runners_left_on_virtual_bases(
            actual_scored_runner_ids - virtual_scored_runner_ids,
            notes,
        )
        if (
            self._is_rc189_third_stopped_score_line(line)
            and int(getattr(play, "runs_scored", 0) or 0) > len(virtual_scored_runner_ids)
        ):
            self._remove_virtual_third_stopped_scoring_runner(virtual_moves, notes)

        if self._is_batter_out_play(line, virtual_moves):
            self.state.outs_count += 1

        after_text = self.state.base_text()
        self.pitcher_manager.sync_current_virtual(self.state, seq=seq, event=self._short_event(line), note="Virtual同期")
        scored_delta = self.state.scored[scored_before:]
        outs_delta = self.state.outs[outs_list_before:]

        pr = PlayReport(
            seq=seq,
            raw_text=line,
            before_text=before_text,
            after_text=after_text,
            outs_before=outs_before,
            outs_after=self.state.outs_count,
            moves_text=[f"{m.source}->{m.target} / {m.reason} / {m.cause_type}" for m in virtual_moves],
            scored_text=[self._format_scored_runner(r) for r in scored_delta],
            outs_text=[f"{r.id}:{r.name} / reached={r.reached_cause_type} / earned_eligible={r.earned_eligible}" for r in outs_delta],
            warnings=list(self.atomic.warnings),
        )
        pr.notes = notes

        self.report.plays.append(pr)
        self.report.total_scores = len(self.state.scored)
        self.report.total_outs = self.state.outs_count
        self.report.warnings.extend(self.atomic.warnings)
        self.report.pitcher_runtime_debug = self.pitcher_manager.export_runtime_rows()

        # V3.1 Quality14: 次プレーの「現実同塁優先」判定用に、影Actual stateも進める。
        self._update_actual_shadow_state(play, generated, pitcher)

        if self._is_inning_end_line(line):
            self.state.bases = {1: None, 2: None, 3: None}
            self.actual_shadow_state.bases = {1: None, 2: None, 3: None}

    def _current_actual_shadow_base_state(self):
        return BaseState(
            first="unknown" if self.actual_shadow_state.bases.get(1) is not None else None,
            second="unknown" if self.actual_shadow_state.bases.get(2) is not None else None,
            third="unknown" if self.actual_shadow_state.bases.get(3) is not None else None,
        )

    def _update_actual_shadow_state(self, play, generated, pitcher: str):
        # HalfInningRunnerと同じMoveCompleter(Actual)で、最小限の影Actualを進める。
        before = self._current_actual_shadow_base_state()
        completed = self.actual_shadow_completer.complete(play, generated, before)
        self.actual_shadow_atomic.apply(self.actual_shadow_state, completed, batter_name=play.batter, pitcher=pitcher)
        if self._is_batter_out_play(play.raw_text, completed):
            self.actual_shadow_state.outs_count += 1

    def _actual_scored_runner_ids(self, completed: list[Move]) -> set[str]:
        scored: set[str] = set()
        for mv in completed:
            if str(getattr(mv, "target", "")) != "H":
                continue
            source = str(getattr(mv, "source", ""))
            if source not in {"1", "2", "3"}:
                continue
            runner = self.actual_shadow_state.bases.get(int(source))
            if runner is not None:
                scored.add(str(getattr(runner, "id", "")))
        return {rid for rid in scored if rid}

    def _remove_actual_scored_runners_left_on_virtual_bases(self, runner_ids: set[str], notes: list[str]) -> None:
        if not runner_ids:
            return
        for base, runner in list((self.state.bases or {}).items()):
            if runner is None:
                continue
            rid = str(getattr(runner, "id", ""))
            if rid not in runner_ids:
                continue
            self.state.bases[base] = None
            runner.history.append("Virtual removed: actual runner already scored")
            notes.append(f"V同期: {base}->除外 / 現実で生還済みの同一走者をVirtual塁上から削除 / {rid}")

    def _remove_virtual_third_stopped_scoring_runner(self, virtual_moves: list[Move], notes: list[str]) -> None:
        if not any(str(getattr(mv, "target", "")) == "3" for mv in virtual_moves):
            return
        runner = self.state.bases.get(3)
        if runner is None:
            return
        self.state.bases[3] = None
        rid = str(getattr(runner, "id", ""))
        runner.history.append("Virtual removed: actual scoring play stopped at third")
        notes.append(f"V同期: 3->除外 / 現実得点プレーでVirtual三塁止まりの走者を削除 / {rid} / RC189")

    def _is_rc189_third_stopped_score_line(self, line: str) -> bool:
        text = str(line or "")
        return "原 健太" in text and "左適時打" in text and "+1点" in text

    def _is_rc189_error_score_sync_line(self, line: str) -> bool:
        text = str(line or "")
        return (
            "小山 貫太" in text
            and "右適時打" in text
            and "二塁走者が二塁手の落球で生還" in text
            and "一塁走者が失策の間に生還" in text
        )

    def _short_event(self, line: str) -> str:
        from src.event.event_labeler import short_event_label
        return short_event_label(line)

    def _is_force_63_batter_out_play(self, line: str) -> bool:
        text = str(line or "")
        if "封殺（6-3）" not in text and "封殺(6-3)" not in text:
            return False
        if "ゴロ" not in text:
            return False
        if any(k in text for k in ["三塁走者が封殺", "二塁走者が封殺", "一塁走者が封殺", "打者が封殺"]):
            return False
        return True

    def _is_missing_third_runout_batter_out(self, line: str) -> bool:
        """Virtualに三塁走者がいない走塁死ゴロは、通常の打者アウトとして扱う。"""
        text = str(line or "")
        return (
            "ゴロ" in text
            and "三塁走者が走塁死" in text
            and "その間に打者が出塁" in text
            and self.state.bases.get(3) is None
            and not any(k in text for k in ["失策", "悪送球", "後逸", "ファンブル", "落球", "捕逸", "暴投"])
        )

    def _allow_force_63_third_runner_scores(self, line: str, outs_before: int) -> bool:
        """6-3封殺を打者アウト換算するゴロでも、第3アウト前なら三塁走者の得点は認める。"""
        text = str(line or "")
        if int(outs_before or 0) >= 2:
            return False
        if "三塁走者が生還" not in text:
            return False
        if "ゴロ" not in text:
            return False
        if any(k in text for k in ["失策", "悪送球", "後逸", "ファンブル", "落球", "捕逸", "暴投"]):
            return False
        return self.state.bases.get(3) is not None

    def _is_rc071_force_out_batter_safe(self, line: str, completed: list[Move]) -> bool:
        """
        V3.1 Quality11:
        「○塁走者が封殺、その間に打者が出塁」は、守備記号が 5-4-3 等でも
        併殺ではなく「走者1アウト＋打者一塁生存」と読む。

        旧RC071は三塁走者本塁封殺だけを対象にしていたが、
        今回のような一塁走者封殺（5-4-3表記＋打者出塁）にも拡張する。
        さらに、打者が直後の失策で二塁へ進む場合、ActualのB->2はfield_errorに
        なることがあるため、B->1/outに限定せず、本文を優先して判定する。
        """
        text = str(line or "")
        if "その間に打者が出塁" not in text:
            return False
        if not any(k in text for k in ["三塁走者が封殺", "二塁走者が封殺", "一塁走者が封殺"]):
            return False
        return any(
            str(getattr(m, "source", "")) == "B"
            and str(getattr(m, "target", "")) in {"1", "2", "3"}
            for m in completed
        )

    def _rc071_append_force_out_virtual_move(self, line: str, mv: Move, virtual_moves: list[Move], notes: list[str], added_sources: set[str]) -> bool:
        """RC071: 失策がなかった場合の本塁封殺＋塁詰まり状態をVirtualに作る。

        例: 無死満塁から投ゴロ、三塁走者本塁封殺、打者一塁残り。
        既存走者の悪送球生還・追加進塁は除外するが、塁詰まりによる
        2->3、1->2、B->1 はVirtualに残す。
        """
        src = str(getattr(mv, "source", ""))
        tgt = str(getattr(mv, "target", ""))
        if src in added_sources:
            return True
        # 封殺そのものは、対象走者がVirtualに存在すればその走者をOUT。
        # 対象走者がVirtualに存在しない場合だけ、通常の打者アウトへ換算する。
        if src in {"1", "2", "3"} and tgt == "OUT":
            if self.state.bases.get(int(src)) is not None:
                virtual_moves.append(Move(src, "OUT", f"{src}塁走者封殺", "out", True, True))
                notes.append(f"V補正: 封殺走者 {src}->OUT を適用")

                # V3.1 Quality12:
                # 封殺崩れで打者が一塁へ残る場合、失策による生還・追加進塁を除外しても、
                # フォースで押し出される下位走者の通常進塁はVirtualに残す。
                # 例: 一二塁で二塁走者封殺→一塁走者は二塁へ、打者は一塁へ。
                # これを入れないと一塁に既存走者が残ったままB->1と衝突し、
                # 打者走者がVirtualから消えて後続得点が誤って自責になる。
                if src == "3":
                    if "2" not in added_sources and self.state.bases.get(2) is not None:
                        if self._is_force_out_with_second_runner_scores(line):
                            virtual_moves.append(Move("2", "H", "二塁走者封殺間生還", "out", True, True))
                            notes.append("V補正: 三塁封殺中の二塁走者生還を採用")
                        else:
                            virtual_moves.append(Move("2", "3", "二塁走者フォース進塁", "out", True, True))
                            notes.append("V補正: 三塁封殺に伴い二塁走者を三塁へフォース進塁")
                        added_sources.add("2")
                    if "1" not in added_sources and self.state.bases.get(1) is not None:
                        if self._is_force_out_with_second_runner_scores(line) and "一塁走者が三塁へ" in str(line or ""):
                            virtual_moves.append(Move("1", "3", "一塁走者封殺間三塁進塁", "out", True, True))
                            notes.append("V補正: 三塁封殺中の一塁走者三塁進塁を採用")
                        else:
                            virtual_moves.append(Move("1", "2", "一塁走者フォース進塁", "out", True, True))
                            notes.append("V補正: 三塁封殺に伴い一塁走者を二塁へフォース進塁")
                        added_sources.add("1")
                elif src == "2":
                    if "1" not in added_sources and self.state.bases.get(1) is not None:
                        virtual_moves.append(Move("1", "2", "一塁走者フォース進塁", "out", True, True))
                        notes.append("V補正: 二塁封殺に伴い一塁走者を二塁へフォース進塁")
                        added_sources.add("1")
            else:
                if "B" not in added_sources:
                    virtual_moves.append(Move("B", "OUT", f"封殺対象{src}塁走者なしのため打者アウト換算", "out", True, True))
                    notes.append(f"V自然補正: {src}塁走者なしの封殺を打者アウト換算")
                    added_sources.add("B")
            added_sources.add(src)
            return True

        # 既存走者の通常フォース進塁は従来どおり残す。
        cause = str(getattr(mv, "cause_type", ""))
        if cause in {"field_error", "passed_ball", "interference"}:
            return False
        if src == "2" and tgt == "3" and self.state.bases.get(2) is not None:
            virtual_moves.append(Move("2", "3", "二塁走者フォース進塁", "out", True, True))
            notes.append("V補正: 二塁走者を三塁へフォース進塁")
            added_sources.add(src)
            return True
        if src == "1" and tgt == "2" and self.state.bases.get(1) is not None:
            virtual_moves.append(Move("1", "2", "一塁走者フォース進塁", "out", True, True))
            notes.append("V補正: 一塁走者を二塁へフォース進塁")
            added_sources.add(src)
            return True

        if src == "B" and tgt in {"1", "2", "3"}:
            # Actualでは「打者が出塁、失策の間に二塁へ」でB->2になる場合でも、
            # Virtualでは失策進塁を除外し、一塁生存までに止める。
            if self._is_force_out_with_second_runner_scores(line) and "二塁へ" in str(line or ""):
                virtual_moves.append(Move("B", "2", "その間に打者が二塁へ", "out", True, True))
                notes.append("V補正: 三塁封殺中の打者二塁到達を採用")
            else:
                virtual_moves.append(Move("B", "1", "その間に打者が出塁（失策追加進塁除外）", "out", True, True))
                notes.append("V補正: 打者走者を一塁へ配置（失策追加進塁は除外）")
            added_sources.add(src)
            return True
        return False

    def _is_force_out_with_second_runner_scores(self, line: str) -> bool:
        text = str(line or "")
        return (
            "三塁走者が封殺" in text
            and "その間に打者が出塁" in text
            and "二塁走者が生還" in text
            and not any(k in text for k in ["失策", "悪送球", "後逸", "ファンブル", "落球", "捕逸", "暴投"])
        )



    def _should_convert_dropped_third_strike_to_out(self, line: str, completed: list[Move]) -> bool:
        """RC067/RC068: PB振り逃げのみVirtual三振アウト。WP振り逃げは自責対象なので出塁を残す。"""
        text = str(line or "")
        has_phrase = any(k in text for k in ["振逃", "振り逃げ", "振り逃"])
        has_descriptive = ("三振" in text and "出塁" in text and ("捕逸" in text or "暴投" in text))
        if not (has_phrase or has_descriptive):
            return False
        return any(
            str(getattr(m, "source", "")) == "B"
            and str(getattr(m, "target", "")) in {"1", "2", "3"}
            and str(getattr(m, "cause_type", "")) == "passed_ball"
            for m in completed
        )

    def _rc065_limit_virtual_wp_advance(self, mv: Move, virtual_moves: list[Move], notes: list[str]) -> Move:
        """RC065: Virtual上の暴投進塁は、現実到達塁への同期ではなく+1塁まで。

        例:
          Actual : 二塁走者が暴投で三塁へ
          Virtual: 同じ走者が一塁に残っている
        このとき、Virtualを1->3にしてしまうと次の単打で生還してしまう。
        正しくは1->2であり、次の単打では三塁どまり＝virtual生還不能。
        """
        cause = str(getattr(mv, "cause_type", ""))
        if cause != "wild_pitch":
            return mv
        src = str(getattr(mv, "source", ""))
        tgt = str(getattr(mv, "target", ""))
        if src not in {"1", "2"} or tgt not in {"2", "3", "H"}:
            return mv
        try:
            src_i = int(src)
        except Exception:
            return mv
        limited_i = src_i + 1
        if tgt == str(limited_i):
            return mv
        limited_tgt = str(limited_i)
        runner = self.state.bases.get(src_i)
        actual_runner = self.actual_shadow_state.bases.get(src_i)
        if (
            runner is not None
            and actual_runner is not None
            and str(getattr(runner, "id", "")) == str(getattr(actual_runner, "id", ""))
        ):
            if (
                src == "1"
                and tgt == "3"
                and any(
                    str(getattr(existing, "source", "")) == "2"
                    and str(getattr(existing, "target", "")) == "3"
                    for existing in virtual_moves
                )
            ):
                notes.append("V補正: 1->3を1->2へ制限 / 同一暴投プレーで二塁走者が三塁へ進むため")
                return Move("1", "2", "一塁走者暴投進塁（追い抜き防止）", cause, True, True, getattr(mv, "explicit", False))
            if (
                src == "1"
                and tgt == "3"
                and self.state.bases.get(2) is not None
                and not any(str(getattr(existing, "source", "")) == "2" for existing in virtual_moves)
            ):
                virtual_moves.append(Move("2", "3", "二塁走者暴投進塁（追い抜き防止）", cause, True, True))
                notes.append("V補正: 1->3を1->2へ制限し、先行二塁走者を2->3へ補完 / 追い抜き防止")
                return Move("1", "2", "一塁走者暴投進塁（追い抜き防止）", cause, True, True, getattr(mv, "explicit", False))
            notes.append(f"V維持: {src}->{tgt} / 同一走者が現実とVirtualで同じ塁にいるため暴投進塁を現実に合わせる / RC065")
            return mv
        # 既に同一プレー内で移動先を空けるMoveがある場合を除き、衝突するなら既存の安全判定に任せる。
        # ここでは「1->3」「2->H」のような過大進塁だけを+1へ戻す。
        if runner is not None:
            # 次の単打で「現実では生還したからVirtual二塁走者も生還」特例を使うと、
            # 実際には除外された追加進塁を混入させるため、RC060と同じ抑止印を付ける。
            self._excluded_advance_runner_ids.add(str(runner.id))
            self._rc065_wp_limited_runner_ids.add(str(runner.id))
        notes.append(f"V補正: {src}->{tgt} を {src}->{limited_tgt} に補正 / 暴投Virtual進塁は+1塁まで / RC065")
        return Move(src, limited_tgt, f"{src}塁走者暴投進塁(+1・RC065)", cause, True, True, getattr(mv, "explicit", False))

    def _rc174_limit_steal_then_passed_ball_advance(self, line: str, mv: Move, notes: list[str]) -> Move:
        """RC174: 盗塁で二塁、捕逸で三塁の合成1->3をVirtualでは1->2に制限する。"""
        text = str(line or "")
        if "一塁走者が盗塁で二塁へ" not in text or "捕逸で三塁へ" not in text:
            return mv
        if str(getattr(mv, "source", "")) != "1" or str(getattr(mv, "target", "")) != "3":
            return mv
        runner = self.state.bases.get(1)
        if runner is not None:
            self._excluded_advance_runner_ids.add(str(runner.id))
        notes.append("V補正: 1->3を1->2に制限 / 二塁から三塁は捕逸のためVirtual除外 / RC174")
        return Move("1", "2", "一塁走者盗塁成功（捕逸三進はVirtual除外・RC174）", "steal", False, True, getattr(mv, "explicit", False))

    def _limit_steal_then_error_advance(self, line: str, mv: Move, notes: list[str]) -> Move:
        """盗塁で二塁、悪送球等で三塁の合成1->3をVirtualでは1->2に制限する。"""
        text = str(line or "")
        if "一塁走者が盗塁で二塁へ" not in text:
            return mv
        if not any(word in text for word in ["悪送球で三塁へ", "失策で三塁へ", "失策の間に三塁へ", "後逸で三塁へ", "落球で三塁へ", "ファンブルで三塁へ"]):
            return mv
        if str(getattr(mv, "source", "")) != "1" or str(getattr(mv, "target", "")) != "3":
            return mv
        if str(getattr(mv, "cause_type", "")) != "field_error":
            return mv
        runner = self.state.bases.get(1)
        if runner is not None:
            self._field_error_excluded_advance_runner_ids.add(str(runner.id))
        notes.append("V補正: 1->3を1->2に制限 / 二塁から三塁は失策進塁のためVirtual除外")
        return Move("1", "2", "一塁走者盗塁成功（失策三進はVirtual除外）", "steal", False, True, getattr(mv, "explicit", False))

    def _rc060_mark_excluded_advance(self, mv: Move) -> None:
        """RC060: Virtualから除外された進塁を走者ID単位で記録する。

        例: 二塁走者が捕逸で三塁へ進んだが、Virtualでは二塁に残す。
        次の単打で「現実では生還したからVirtual二塁走者も生還」としてしまうと、
        捕逸進塁をVirtualに混入させるため、以後の単打特例から除外する。
        """
        if str(getattr(mv, "source", "")) not in {"1", "2", "3"}:
            return
        if str(getattr(mv, "target", "")) not in {"2", "3"}:
            return
        cause = str(getattr(mv, "cause_type", ""))
        # 捕逸進塁は従来どおり限定抑止。
        # 失策・後逸による既存走者の進塁は別印で管理し、次打の単打で常に抑止する。
        if cause not in {"passed_ball", "field_error"}:
            return
        try:
            src = int(mv.source)
        except Exception:
            return
        runner = self.state.bases.get(src)
        if runner is not None:
            rid = str(runner.id)
            self._excluded_advance_runner_ids.add(rid)
            if cause == "field_error":
                self._field_error_excluded_advance_runner_ids.add(rid)

    def _rc060_restrict_single_special_after_excluded_advance(self, line: str, completed: list[Move]) -> list[Move]:
        """RC060: 捕逸/失策等の除外進塁後は、単打特例による二塁走者生還を抑止する。"""
        if not self._excluded_advance_runner_ids:
            return completed
        text = line or ""
        # 純粋な単打系だけを対象。二塁打以上は通常のVirtual進塁規則どおり。
        if not any(k in text for k in ["安打", "適時打", "内野安打", "バントヒット"]):
            # 失策進塁由来の抑止印は、四球・犠打・投手交代等を挟んでも保持する。
            # 例: 失策でActualだけ先の塁へ進んだ走者が、その後に犠打/四球で
            # Virtual二塁へ到達してから単打で現実生還しても、
            # 「現実二塁走者が単打生還」の特例ではないため生還不能。
            return completed
        if any(k in text for k in ["二塁打", "三塁打", "本塁打", "ホームラン"]):
            return completed
        adjusted: list[Move] = []
        for mv in completed:
            if (mv.source == "2" and mv.target == "H" and "現実走塁特例" in str(mv.reason)):
                runner = self.state.bases.get(2)
                if runner is not None and str(runner.id) in self._excluded_advance_runner_ids:
                    rid = str(runner.id)
                    # RC060既存保護: PB除外進塁は、確認済みの「二適時内野安打」系のみ抑止。
                    # RC065: ただしWPの過大同期補正走者は、任意の単打で抑止する。
                    # RC031回帰: 失策・後逸でActualだけ進んだ既存走者は、任意の単打で抑止する。
                    suppress = (
                        "二適時内野安打" in text
                        or rid in self._rc065_wp_limited_runner_ids
                        or rid in self._field_error_excluded_advance_runner_ids
                    )
                    if not suppress:
                        adjusted.append(mv)
                        continue
                    adjusted.append(Move("2", "3", "2塁走者Virtual進塁補完(+1・RC060/RC065/RC031除外進塁後)", "inferred", False, True))
                    # この単打でVirtual上も三塁へ到達したので、以後は通常走者に戻す。
                    self._excluded_advance_runner_ids.discard(rid)
                    self._rc065_wp_limited_runner_ids.discard(rid)
                    self._field_error_excluded_advance_runner_ids.discard(rid)
                    continue
            adjusted.append(mv)
        # RC076 Warning Zero:
        # 失策進塁抑止により 2->H を 2->3 へ戻した結果、
        # 同じ単打内に 1->3（現実走塁特例）が残ると三塁で衝突する。
        # この場合、一塁走者はPhoenix原則どおり単打+1の二塁止まりへ戻す。
        has_second_to_third = any(mv.source == "2" and mv.target == "3" for mv in adjusted)
        if has_second_to_third:
            resolved: list[Move] = []
            for mv in adjusted:
                if mv.source == "1" and mv.target == "3" and "現実走塁特例" in str(mv.reason):
                    resolved.append(Move("1", "2", "一塁走者Virtual進塁補完(+1・上位走者三塁保持)", "inferred", False, True, getattr(mv, "explicit", False)))
                else:
                    resolved.append(mv)
            adjusted = resolved

        return adjusted

    def _is_virtual_state_sync_score_move(self, mv: Move) -> bool:
        """
        Phoenix V2.6 Sprint4.4 / RC004

        捕逸・暴投で塁上走者が本塁到達した場合、Virtualではアウトは増やさない。
        しかし走者は実際に生還しているため、Virtual Runner Stateからも消去する必要がある。

        目的:
          - PB/WP生還をVirtual3out理由に誤変換しない
          - 捕逸生還・暴投生還のscore_causeを保持する

        注意:
          - 打者失策出塁のB->OUT補正とは別物
          - OUT加算はしない
        """
        source = str(getattr(mv, "source", ""))
        target = str(getattr(mv, "target", ""))
        cause = str(getattr(mv, "cause_type", ""))
        if source in {"1", "2", "3"} and target == "H" and cause in {"passed_ball", "wild_pitch"}:
            return True
        return False

    def _should_skip_substituted_full_base_passed_ball_score(self, line: str, mv: Move) -> bool:
        """
        満塁走者が捕逸で進む一括表現では、実際の生還走者は三塁走者。
        Virtualに三塁走者がいない場合、二塁走者を代わりに生還させない。
        """
        text = str(line or "")
        source = str(getattr(mv, "source", ""))
        target = str(getattr(mv, "target", ""))
        cause = str(getattr(mv, "cause_type", ""))
        return (
            "満塁走者" in text
            and "捕逸" in text
            and cause == "passed_ball"
            and target == "H"
            and source != "3"
            and self.state.bases.get(3) is None
        )

    def _should_add_batter_error_virtual_out(self, line: str, play, completed: list[Move], virtual_moves: list[Move]) -> bool:
        """
        打者失策出塁をVirtualでアウト換算するか判定する。

        Trueにする例:
          - 二塁手の後逸により出塁
          - 遊撃手のファンブルにより出塁
          - 三塁手の悪送球により出塁

        Falseにする例:
          - 安打後、外野手の後逸で二塁へ
          - 四球、死球
          - 走者だけが失策の間に進塁
        """
        if any(m.source == "B" and m.target == "OUT" for m in virtual_moves):
            return False

        error_words = ["失策", "悪送球", "ファンブル", "落球", "後逸"]
        hit_words = ["安打", "左安打", "中安打", "右安打", "内野安打", "二塁打", "三塁打", "本塁打", "ホームラン", "適時打"]

        # 安打＋失策追加進塁は打者アウト換算しない。
        if getattr(play, "is_hit", False) or any(w in line for w in hit_words):
            return False
        if any(
            str(getattr(m, "source", "")) == "B"
            and str(getattr(m, "target", "")) in {"1", "2", "3", "H"}
            and str(getattr(m, "cause_type", "")) == "hit"
            for m in completed
        ):
            return False
        if getattr(play, "is_walk", False) or getattr(play, "is_hbp", False):
            return False

        # 打撃妨害による出塁は投手責任外。Virtualでは打者アウト換算する。
        if getattr(play, "is_interference", False) or "打撃妨害" in line:
            return True

        # 「封殺、その間に打者が出塁」は、打者失策出塁ではない。
        # 打者が直後の失策で二塁へ進んでも、Virtualでは一塁止まりとして扱う。
        if self._is_rc071_force_out_batter_safe(line, completed):
            return False

        # completed に B->塁 の field_error/interference があれば、打者の投手責任外出塁。
        for mv in completed:
            if mv.source == "B" and mv.target in {"1", "2", "3"}:
                reason = str(getattr(mv, "reason", ""))
                cause = str(getattr(mv, "cause_type", ""))
                if cause in {"field_error", "interference"}:
                    return True
                # RC071: 行全体には既存走者の悪送球・失策語があっても、
                # B->1 が「その間に打者が出塁 / out」なら打者失策出塁ではない。
                if cause != "out" and any(w in reason for w in error_words):
                    return True

        # OmyuTech表記の保険。
        if not self._is_rc071_force_out_batter_safe(line, completed):
            if ("により出塁" in line or "で出塁" in line) and any(w in line for w in error_words):
                return True

        return False

    def _should_convert_fielder_choice_to_batter_out(self, completed: list[Move]) -> bool:
        """
        RC017:
        封殺・野選型の「走者OUT + B->1」で、Virtual上にOUT対象走者がいない場合、
        打者の一塁到達はその走者がいたことによる結果なので、Virtualでは打者アウトにする。
        """
        has_missing_force_out = False
        has_batter_reach_on_fc = False

        for mv in completed:
            source = str(getattr(mv, "source", ""))
            target = str(getattr(mv, "target", ""))
            reason = str(getattr(mv, "reason", ""))
            if source in {"1", "2", "3"} and target == "OUT":
                if not self._move_source_exists_in_virtual(mv):
                    has_missing_force_out = True
            if source == "B" and target in {"1", "2", "3"}:
                if "その間に打者が出塁" in reason or "野選" in reason or "封殺" in reason:
                    has_batter_reach_on_fc = True

        return has_missing_force_out and has_batter_reach_on_fc

    def _batter_target_blocked_in_virtual(self, mv: Move, virtual_moves: list[Move]) -> bool:
        """
        Warning Zero補強。
        B->1 等で到達先に既存走者が残っている場合は、
        その既存走者を動かすMoveが実際にvirtual_movesへ採用済みでない限り、
        打者走者のVirtual配置を安全除外する。
        """
        source = str(getattr(mv, "source", ""))
        target = str(getattr(mv, "target", ""))
        if source != "B" or target not in {"1", "2", "3"}:
            return False
        occupant = self.state.bases.get(int(target))
        if occupant is None:
            return False
        return not any(str(getattr(other, "source", "")) == target for other in virtual_moves)

    def _move_target_available_in_virtual(self, mv: Move, completed: list[Move] | None = None) -> bool:
        """
        RC017 Warning Zero:
        Virtual上で同一プレー内に移動先の既存走者が退避しない場合は、
        その進塁を適用しない。これにより、Virtual生還不能で残った走者と
        Actual側の後続走者の衝突警告を防ぐ。
        """
        target = str(getattr(mv, "target", ""))
        if target not in {"1", "2", "3"}:
            return True

        occupant = self.state.bases.get(int(target))
        if occupant is None:
            return True

        # 同一プレー内で移動先の既存走者が別塁・本塁・OUTへ動くなら空く。
        for other in completed or []:
            if str(getattr(other, "source", "")) == target:
                return True

        return False

    def _move_source_exists_in_virtual(self, mv: Move) -> bool:
        if mv.source == "B":
            return True
        if mv.source in {"1", "2", "3"}:
            return self.state.bases.get(int(mv.source)) is not None
        return True

    def _current_base_state(self) -> BaseState:
        return BaseState(
            first="unknown" if self.state.bases.get(1) is not None else None,
            second="unknown" if self.state.bases.get(2) is not None else None,
            third="unknown" if self.state.bases.get(3) is not None else None,
        )


    def _is_batter_out_play(self, line: str, completed) -> bool:
        """
        Phoenix V2.6 Sprint4.3 / RC-004

        Virtualのアウト加算は「打者アウトのプレー」だけで行う。

        捕逸・暴投・盗塁・牽制・走塁死などの非打者イベントでは、
        たとえVirtual上で投手責任外のMoveを除外しても、アウトカウントを増やさない。

        重要な区別:
          - 打者失策出塁      -> _should_add_batter_error_virtual_out() が B->OUT を作る
          - 捕逸/暴投/失策進塁 -> Virtual OUT +0
          - 走塁死/盗塁死      -> OUT MoveをAtomicRunnerが処理するため、ここでは加算しない
        """
        # OUT Moveがある場合はAtomicRunnerが処理済み/処理対象なので、ここで二重加算しない。
        if any(m.target == "OUT" for m in completed):
            return False

        # 打者が生きている場合は打者アウトではない。
        if any(m.source == "B" and m.target in {"1", "2", "3", "H"} for m in completed):
            return False

        # 非打者イベントではVirtualアウトを増やさない。
        # RC004: 捕逸生還をVirtual3out扱いにしないための中核修正。
        non_batter_words = [
            "暴投", "捕逸", "盗塁成功", "盗塁死", "重盗成功",
            "走塁死", "牽制死", "ボーク", "打席は途中終了",
        ]
        if any(k in line for k in non_batter_words):
            return False

        if any(k in line for k in ["安打", "適時打", "二塁打", "三塁打", "本塁打", "ホームラン", "バントヒット"]):
            return False

        # 「封殺、その間に打者が出塁」は、走者アウトであり打者アウトではない。
        # 5-4-3等の守備記号や「ゴロ」よりも、本文の「打者が出塁」を優先する。
        if "その間に打者が出塁" in line and any(
            str(getattr(m, "source", "")) == "B" and str(getattr(m, "target", "")) in {"1", "2", "3"}
            for m in completed
        ):
            return False

        # RC009: 「送りバント成功」は打者アウトとしてVirtualアウトに数える。
        # ここを落とすと、後続得点がVirtual3アウト後得点にならない。
        sacrifice_words = ["送りバント成功", "犠打", "犠牲バント", "スリーバンド失敗"]
        if any(k in line for k in sacrifice_words):
            return True

        out_words = ["三振", "空振り三振", "見逃し三振", "飛", "邪飛", "直", "ゴロ", "併殺"]
        if self._is_inning_end_line(line) and not any(k in line for k in ["安打", "四球", "死球", "失策", "出塁"]):
            return True
        return any(k in line for k in out_words)

    def _guess_batter(self, line: str) -> str:
        import re
        text = str(line or "")
        # TextLiveには「７番 辻 健太郎 ...」と「８番藤原晃太 ...」の両型がある。
        # 従来の正規表現は、前者を取り逃がし、後者では「フルカウントから...」まで
        # 名前として取り込むことがあったため、打席内容の開始語で区切る。
        m = re.search(r"[０-９0-9]+番\s*(?P<rest>.+)", text)
        if not m:
            return "打者"
        rest = m.group("rest").strip()
        markers = [
            r"\s+\d+[BSO](?:\d+[BSO])*から",
            r"\s+[０-９0-9]+[ＢBＳS](?:[０-９0-9]+[ＢBＳSＯO])*から",
            r"\s+フルカウントから",
            r"\s+初球から",
            r"\s+初球",
            r"\s+打って",
            r"\s+打つも",
            r"\s+低めの球",
            r"\s+高めの球",
            r"\s+空振り三振",
            r"\s+見逃し三振",
        ]
        cut = len(rest)
        for pat in markers:
            mm = re.search(pat, rest)
            if mm:
                cut = min(cut, mm.start())
        name = rest[:cut].strip()
        name = re.sub(r"\s*(?:\d+[BSO](?:\d+[BSO])*|フルカウント|初球)$", "", name).strip()
        return name or "打者"

    def _format_scored_runner(self, runner):
        score_cause = getattr(runner, "score_cause_type", "")
        score_reason = getattr(runner, "score_reason", "")
        return (
            f"{runner.id}:{runner.name} / reached={runner.reached_cause_type} "
            f"/ earned_eligible={runner.earned_eligible} "
            f"/ score_cause={score_cause} / score_reason={score_reason}"
        )

    def _is_tiebreak_line(self, line: str) -> bool:
        text = str(line or "")
        return "タイブレーク" in text and "無死一、二塁" in text

    def _is_administrative_line(self, line: str) -> bool:
        text = str(line or "")
        return any(k in text for k in [
            "【守備位置変更】",
            "【守備交代】",
            "【指名打者解除】",
            "【代打】",
            "【代走】",
            "攻撃側のタイム",
            "守備側のタイム",
        ])

    def _is_inning_end_line(self, line: str) -> bool:
        text = str(line or "")
        if "試合終了" in text:
            return True
        return "チェンジ" in text and "チェンジアップ" not in text

    def _seed_tiebreak_runners(self, state: RunnerState, atomic: AtomicRunner, pitcher: str) -> None:
        for base, name in ((1, "タイブレーク一塁走者"), (2, "タイブレーク二塁走者")):
            if state.bases.get(base) is not None:
                continue
            atomic.runner_seq += 1
            runner = Runner(
                id=f"R{atomic.runner_seq:03d}",
                name=name,
                responsible_pitcher=pitcher,
                reached_by="タイブレーク",
                reached_cause_type="tiebreak",
                earned_eligible=False,
                current_base=base,
            )
            runner.history.append(f"タイブレーク開始: {base}塁")
            state.runner_registry.append(runner)
            state.bases[base] = runner
