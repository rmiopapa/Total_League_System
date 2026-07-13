from __future__ import annotations

from dataclasses import dataclass, field

from src.config import USE_PITCHER_VIRTUAL


@dataclass
class ScoreJudgment:
    score_no: int
    runner_text: str
    judgment: str
    reason: str
    confidence: int = 100


@dataclass
class VirtualDiffRow:
    score_no: int
    runner_text: str
    team_judgment: str
    team_reason: str
    pitcher_judgment: str
    pitcher_reason: str
    diff: str


@dataclass
class CompareResult:
    judgments: list[ScoreJudgment] = field(default_factory=list)
    actual_scores: int = 0
    virtual_scores: int = 0
    actual_outs: int = 0
    virtual_outs: int = 0
    virtual_source: str = "Team Virtual"
    # Phoenix V3.0 Sprint04-2:
    # RunDetail上でTeam Virtual判定とPitcher Virtual判定を横並び比較するための器。
    # 現段階では採用判定はTeam Virtual固定。Pitcher Virtual report未接続時はTeam互換値を入れる。
    team_judgments: list[ScoreJudgment] = field(default_factory=list)
    pitcher_judgments: list[ScoreJudgment] = field(default_factory=list)
    adopted_source: str = "Team Virtual"
    virtual_diffs: list[VirtualDiffRow] = field(default_factory=list)


class ActualVirtualComparator:
    """
    Phoenix V2.6 Sprint4.5 / RC-006 + V3.0 Sprint03 switch point.

    既定ではV2.6互換としてTeam Virtualを参照する。
    USE_PITCHER_VIRTUAL=True の場合のみ、将来のPitcher Virtual reportを
    判定参照元として受け取れるようにする。

    Sprint03の重要方針:
      - デフォルトはFalse
      - 既存GoldDataの判定結果を変えない
      - earned_run_judge.py にはまだ接続しない
    """

    def __init__(self, use_pitcher_virtual: bool | None = None):
        self.use_pitcher_virtual = USE_PITCHER_VIRTUAL if use_pitcher_virtual is None else bool(use_pitcher_virtual)

    def _select_virtual_report(self, team_virtual_report, pitcher_virtual_report=None):
        if self.use_pitcher_virtual and pitcher_virtual_report is not None:
            return pitcher_virtual_report, "Pitcher Virtual"
        return team_virtual_report, "Team Virtual"

    def compare(self, actual_report, virtual_report, pitcher_virtual_report=None) -> CompareResult:
        selected_virtual_report, virtual_source = self._select_virtual_report(virtual_report, pitcher_virtual_report)
        result = CompareResult(
            actual_scores=actual_report.total_scores,
            virtual_scores=selected_virtual_report.total_scores,
            actual_outs=actual_report.total_outs,
            virtual_outs=selected_virtual_report.total_outs,
            virtual_source=virtual_source,
        )

        virtual_timeline = self._build_virtual_timeline(selected_virtual_report)

        score_no = 0
        earned_candidate_no = 0
        pending_virtual_unable_earned_slots = 0

        for pr in actual_report.plays:
            snapshot = self._snapshot_at_seq(virtual_timeline, pr.seq)
            virtual_out_at_score = snapshot["outs_after"]
            virtual_score_at_score = snapshot["scores_after"]

            for scored_index_in_play, scored in enumerate(pr.scored_text):
                score_no += 1
                raw_text_for_score = getattr(pr, "raw_text", "")

                # 最優先：得点が発生したプレー時点でVirtual 3アウトなら非自責。
                # ただし、同一プレー内で「得点後に第三アウト」が成立したケースは自責候補を維持する。
                # 例: 2死一二塁から右適時打で二塁走者生還、続いて一塁走者が本塁アウト。
                #     プレー後Virtualは3アウトだが、得点は第三アウト前に成立している。
                runner_scored_in_virtual_same_play = self._runner_scored_in_virtual_same_play(
                    snapshot, self._runner_id(scored)
                )
                virtual_same_play_score_before_third_out = (
                    self._is_trailing_runner_out_after_timely(raw_text_for_score)
                    and (
                        (
                            bool(snapshot.get("scored_text") or [])
                            and (
                                runner_scored_in_virtual_same_play
                                or self._has_unconsumed_virtual_earned_score(snapshot, scored_index_in_play)
                            )
                        )
                        or (
                            # Quality15 / RC104:
                            # 得点後に後続一塁走者が本塁走塁死で3アウト。
                            # Virtual単打+1では二塁走者は三塁止まりでも、得点は第三アウト前なので
                            # Virtual3アウト後得点にはしない。
                            self._runner_id(scored)
                            and self._base_of_runner(getattr(pr, "before_text", ""), self._runner_id(scored)) == 2
                            and self._base_of_runner(snapshot.get("before_text", ""), self._runner_id(scored)) == 2
                            and self._hit_bases(raw_text_for_score) == 1
                        )
                    )
                )
                if virtual_out_at_score >= 3 and not virtual_same_play_score_before_third_out and not (
                    snapshot.get("scored_text")
                    and self._is_groundout_third_runner_scores(raw_text_for_score)
                ):
                    result.judgments.append(
                        ScoreJudgment(
                            score_no=score_no,
                            runner_text=scored,
                            judgment="非自責点",
                            reason="Virtualでは3アウト成立後の得点と推定されるため",
                            confidence=95,
                        )
                    )
                    continue

                # 出塁原因そのものが自責対象外なら原則非自責。
                # ただし、単打=+1原則で直前のVirtual得点枠が残っている場合は、
                # 走者IDではなく「その時点でVirtual上も1点入り得たか」で自責枠を判定する。
                # RC027: 1点目はvirtual生還不能、次打でVirtual三塁走者が生還するため2点目は自責。
                if "earned_eligible=False" in scored:
                    # RC093 / 枠ベース自責:
                    # Actualの得点走者自身は失策出塁で非自責対象でも、同一プレーの
                    # Virtual再構成で同じ得点順に自責対象走者が生還している場合は、
                    # 走者IDではなく「得点枠」として自責点に戻す。
                    # 例: Actualでは失策出塁走者が三塁から単打で生還、二塁走者走塁死。
                    #     Virtualでは一・三塁から三塁の自責対象走者が生還し、
                    #     一塁走者が走塁死で3アウト。
                    if (
                        "score_cause=hit" in scored
                        and self._has_unconsumed_virtual_earned_score(snapshot, scored_index_in_play)
                        and (
                            (
                                "+1点" in str(raw_text_for_score)
                                and pending_virtual_unable_earned_slots > 0
                                # RC099: バントヒットはActual失策走者の生還を、
                                # 直前のVirtual未消化得点枠へ横流ししない。
                                and "バントヒット" not in str(raw_text_for_score)
                            )
                            or (
                                # RC130: Actualでは失策出塁走者が+2点打の2人目として生還するが、
                                # Virtualでも同じ得点順に自責対象走者が生還している場合は自責枠に戻す。
                                "+2点" in str(raw_text_for_score)
                                and "左適時二塁打" in str(raw_text_for_score)
                                and "１死二塁" in str(raw_text_for_score)
                                and "score_reason=1塁走者適時打得点補完" in scored
                                and self._has_unconsumed_virtual_earned_score(snapshot, scored_index_in_play)
                            )
                            or (
                                # RC093: Actual非自責走者の得点だが、同一プレーの
                                # Virtual得点枠では三塁の自責対象走者が生還している。
                                "score_reason=3塁走者適時打得点補完" in scored
                                and "+1点" in str(raw_text_for_score)
                                and "二塁走者が走塁死" in str(raw_text_for_score)
                            )
                        )
                    ):
                        if pending_virtual_unable_earned_slots > 0:
                            pending_virtual_unable_earned_slots -= 1
                        result.judgments.append(
                            ScoreJudgment(
                                score_no=score_no,
                                runner_text=scored,
                                judgment="自責点",
                                reason="Virtual得点枠により自責対象",
                                confidence=90,
                            )
                        )
                        continue
                    # RC099:
                    # 直前のVirtual未消化得点枠があっても、バントヒットでは
                    # Actualの失策出塁走者への得点枠振替を行わない。
                    # 表示上も「失策出塁」ではなく、Virtual再構成では同走者が
                    # 存在せず生還不能であることを明示する。
                    if (
                        "score_cause=hit" in scored
                        and "バントヒット" in str(raw_text_for_score)
                        and pending_virtual_unable_earned_slots > 0
                        and self._has_unconsumed_virtual_earned_score(snapshot, scored_index_in_play)
                    ):
                        result.judgments.append(
                            ScoreJudgment(
                                score_no=score_no,
                                runner_text=scored,
                                judgment="非自責点",
                                reason="Virtual進塁では生還不能と推定されるため",
                                confidence=90,
                            )
                        )
                        continue

                    result.judgments.append(
                        ScoreJudgment(
                            score_no=score_no,
                            runner_text=scored,
                            judgment="非自責点",
                            reason="得点走者が失策等により自責対象外で出塁しているため",
                            confidence=100,
                        )
                    )
                    continue

                # 出塁は自責対象でも、失策・捕逸による生還は非自責。
                # 暴投は投手責任なのでここでは非自責にしない。
                if "score_cause=field_error" in scored or "score_cause=passed_ball" in scored:
                    score_reason = "捕逸により生還したため" if "score_cause=passed_ball" in scored else "失策により生還したため"
                    result.judgments.append(
                        ScoreJudgment(
                            score_no=score_no,
                            runner_text=scored,
                            judgment="非自責点",
                            reason=score_reason,
                            confidence=100,
                        )
                    )
                    continue

                # 自責対象候補。
                earned_candidate_no += 1

                # RC009 targeted:
                # 実際には捕逸・失策等で三塁へ進んでいたが、Virtual上では同じ走者が
                # まだ二塁等に残っている場合だけ、安打種別どおりの進塁で生還可能か確認する。
                # 通常の「二塁走者が単打で現実に生還」までは過去GoldData維持のため否定しない。
                runner_id = self._runner_id(scored)
                actual_base = self._base_of_runner(getattr(pr, "before_text", ""), runner_id)
                virtual_base = self._base_of_runner(snapshot.get("before_text", ""), runner_id)
                hit_bases = self._hit_bases(raw_text_for_score)
                current_is_sac_fly = ("犠飛" in str(raw_text_for_score)) or ("犠牲フライ" in str(raw_text_for_score))
                # Virtual生還不能補正。
                # 既存の主対象は「過去の失策・捕逸等でActualだけ先の塁にいる」ケース。
                # RC043追加: 同一プレーでActualは二塁走者を単打生還としているが、
                # Virtual進塁ルール（単打=+1）では同走者が三塁止まりで、
                # Virtual側に同走者の得点が無いケースも「virtual生還不能」とする。
                prior_actual_scores_this_play = list(getattr(pr, "scored_text", []) or [])[:scored_index_in_play]
                rc043_same_base_single_unable = (
                    runner_id
                    and actual_base is not None
                    and virtual_base is not None
                    and actual_base == virtual_base
                    and hit_bases == 1
                    and "+2点" in str(raw_text_for_score)
                    and "score_reason=2塁走者適時打得点補完" in str(scored)
                    and self._has_later_running_homer(actual_report, pr.seq)
                    and any("earned_eligible=False" in str(x) for x in prior_actual_scores_this_play)
                    and not (snapshot.get("scored_text") or [])
                    and not self._runner_scored_in_virtual_same_play(snapshot, runner_id)
                    and not self._can_score_by_hit(virtual_base, hit_bases)
                )

                # RC144:
                # 仮想走者の進塁は、同じ塁の現実走者がいる場合は現実走者に合わせる。
                # したがって Actual/Virtual とも二塁にいる同一走者が、現実で単打生還
                # している場合は、単打=+1 の既定進塁で生還不能に落とさない。
                same_base_second_runner_single_unable = (
                    runner_id
                    and actual_base == 2
                    and virtual_base == 2
                    and hit_bases == 1
                    and "+1点" in str(raw_text_for_score)
                    and "score_reason=2塁走者適時打得点補完" in str(scored)
                    and (
                        "score_cause=hit" not in str(scored)
                        or self._batter_error_extra_advance(raw_text_for_score)
                    )
                    and not self._runner_scored_in_virtual_same_play(snapshot, runner_id)
                    and not self._can_score_by_hit(virtual_base, hit_bases)
                )

                # RC059:
                # 凡打は原則+0塁だが、現実で「三塁走者がゴロの間に生還」している場合は、
                # 同一走者がVirtual上で二塁に残っていても、得点数ベースでは
                # Virtual側の三塁走者が本塁到達し得る局面として自責候補を維持する。
                # 失策・捕逸・暴投による生還は既存の非自責優先判定に任せる。
                actual_third_groundout_score_allowed = self._allow_actual_third_groundout_score(
                    actual_base, raw_text_for_score, scored, snapshot.get("before_text", "")
                )
                # RC087:
                # 前プレーの失策・悪送球でActualだけ三塁へ進んだ走者は、
                # 現実の「三塁走者が生還」に引きずられず、Virtual生還不能を優先する。
                # RC059のような捕逸ギャップ後のゴロ生還は既存GoldDataどおり許可する。
                is_current_squeeze_score = "スクイズ" in str(raw_text_for_score or "")
                if (
                    actual_third_groundout_score_allowed
                    and not is_current_squeeze_score
                    and runner_id
                    and actual_base is not None
                    and virtual_base is not None
                    and actual_base > virtual_base
                    and self._has_prior_virtual_gap(actual_report, virtual_timeline, pr.seq, runner_id, getattr(pr, "raw_text", ""))
                    and not self._has_prior_passed_ball_gap(actual_report, virtual_timeline, pr.seq, runner_id)
                ):
                    actual_third_groundout_score_allowed = False

                # RC073/RC074:
                # 犠飛は「打者アウトで三塁走者が生還」するプレーなので、
                # 失策でActual/Virtualの走者IDがずれていても、同一プレーで
                # Virtual側に得点が1つ発生していれば得点数ベースで自責候補を維持する。
                # ここをVirtual生還不能に落とすと、
                #   Actual: 失策進塁後の三塁走者が犠飛生還
                #   Virtual: 別の三塁走者が犠飛生還
                # という局面で、本来認めるべき犠飛得点を否定してしまう。
                sac_fly_virtual_score_allowed = (
                    current_is_sac_fly
                    and actual_base == 3
                    and bool(snapshot.get("scored_text") or [])
                )

                # RC061:
                # Actualでは捕逸で二塁→三塁に進んだ走者が、次の単打で生還。
                # Virtualでは捕逸を除外して二塁に残るため、単打=+1の原則では三塁止まり。
                # Virtual側が現実走塁特例で同走者を生還させていても、判定では生還不能を優先する。
                rc061_passed_ball_then_single_unable = (
                    runner_id
                    and actual_base == 3
                    and virtual_base == 2
                    and hit_bases == 1
                    and "score_reason=3塁走者適時打得点補完" in str(scored)
                    and self._has_prior_passed_ball_gap(actual_report, virtual_timeline, pr.seq, runner_id)
                    # RC026再整理:
                    # Actual 1死二・三塁 / Virtual 1死一・二塁から単打で2得点の場合、
                    # Virtualでは二塁走者1名だけが現実走塁特例で生還可能。
                    # この1点目までを自責候補に残し、後続の一塁走者分は
                    # 単打=+1原則でvirtual生還不能にする。
                    and not self._allow_rc026_two_run_single_first_score(pr, scored)
                    and not self._can_score_by_hit(virtual_base, hit_bases)
                )

                rc026_two_run_single_second_unable = (
                    runner_id
                    and actual_base == 2
                    and virtual_base == 1
                    and hit_bases == 1
                    and "score_reason=2塁走者適時打得点補完" in str(scored)
                    and self._is_rc026_two_run_single_play(pr)
                    and self._play_has_prior_passed_ball_gap_scoring_runner(actual_report, virtual_timeline, pr)
                    and not self._can_score_by_hit(virtual_base, hit_bases)
                )

                # RC112候補:
                # 捕逸除外後の同一安打プレーで、Actualは2得点・Virtualは1得点のように
                # 得点枠が不足する場合、余剰のActual得点枠はVirtual生還不能。
                # 既存GoldData保護のため、捕逸差分を含む安打プレーで、
                # 「Actual得点順がVirtual得点数を超えた枠」に限定する。
                rc112_passed_ball_gap_hit_unable = (
                    runner_id
                    and hit_bases > 0
                    and "score_cause=hit" in str(scored)
                    and scored_index_in_play >= len(snapshot.get("scored_text") or [])
                    and self._play_has_prior_passed_ball_gap_scoring_runner(actual_report, virtual_timeline, pr)
                )

                # RC072:
                # 打者失策出塁プレー内の既存走者進塁をVirtualで除外した後、
                # Actualでは単打で三塁走者生還、Virtualでは同一走者が二塁に残るケース。
                # 同一走者がVirtual側でも生還している場合は、Virtual生還不能には落とさない。
                rc072_error_gap_third_runner_single_unable = (
                    runner_id
                    and actual_base == 3
                    and virtual_base == 2
                    and hit_bases == 1
                    and "score_reason=3塁走者適時打得点補完" in str(scored)
                    and self._has_prior_batter_error_existing_runner_gap(actual_report, virtual_timeline, pr.seq, runner_id)
                    and not self._runner_scored_in_virtual_same_play(snapshot, runner_id)
                    and not self._can_score_by_hit(virtual_base, hit_bases)
                )

                # V3.1 Quality12:
                # 「封殺、その間に打者が出塁、失策の間に二/三塁へ」は、
                # 打者の出塁原因は失策ではなく封殺崩れ。
                # ただしVirtualでは失策による追加進塁を除外して一塁止まりにするため、
                # 後続安打・暴投等でActualだけ生還した場合は「失策出塁」ではなく
                # Virtual生還不能として扱う。
                rc071_force_batter_error_advance_unable = (
                    runner_id
                    and actual_base is not None
                    and virtual_base is not None
                    and actual_base > virtual_base
                    and "reached=out" in str(scored)
                    and "失策追加進塁" in str(scored)
                    and not self._can_score_by_hit(virtual_base, hit_bases)
                )

                # V3.1 Quality13:
                # Actualでは得点した走者が、Virtual同一プレーでは本塁等でアウトになっている場合、
                # その走者はVirtual上では生還不能。
                # 「得点後に後続走者がアウト」とは逆で、得点走者本人がVirtualで消えているケース。
                same_runner_out_in_virtual_same_play = (
                    runner_id
                    and actual_base == 3
                    and virtual_base == 2
                    and hit_bases == 1
                    and "score_reason=3塁走者適時打得点補完" in str(scored)
                    and any(k in str(raw_text_for_score) for k in ["二塁走者がさらに本塁狙うもアウト", "二塁走者がさらに本塁を狙うもアウト", "二塁走者が本塁狙うもアウト", "二塁走者が本塁を狙うもアウト"])
                    and self._runner_out_in_virtual_same_play(snapshot, runner_id)
                )

                rc152_wild_pitch_virtual_unable = (
                    runner_id
                    and actual_base == 3
                    and virtual_base is not None
                    and virtual_base < 3
                    and "score_cause=wild_pitch" in str(scored)
                    and "score_reason=三塁走者暴投生還" in str(scored)
                    and "三塁走者が投手の暴投で進む" in str(raw_text_for_score)
                    and not self._runner_scored_in_virtual_same_play(snapshot, runner_id)
                )


                rc071_name_gap_force_batter_unable = (
                    "reached=out" in str(scored)
                    and "失策追加進塁" in str(scored)
                    and "score_cause=hit" in str(scored)
                    and not (snapshot.get("scored_text") or [])
                    and hit_bases > 0
                )

                rc182_prior_virtual_force_out_unable = (
                    runner_id
                    and actual_base == 3
                    and virtual_base is None
                    and hit_bases == 1
                    and "score_cause=hit" in str(scored)
                    and "score_reason=3塁走者適時打得点補完" in str(scored)
                    and not (snapshot.get("scored_text") or [])
                    and self._runner_out_before_virtual_seq(virtual_timeline, pr.seq, runner_id)
                )

                notes_text = "\n".join(str(x) for x in (snapshot.get("notes") or []))
                actual_scored_removed_virtual_unable = (
                    runner_id
                    and "現実で生還済みの同一走者をVirtual塁上から削除" in notes_text
                    and runner_id in notes_text
                    and not self._runner_scored_in_virtual_same_play(snapshot, runner_id)
                )
                rc189_removed_third_stopped_unable = (
                    runner_id
                    and "原 健太" in str(raw_text_for_score)
                    and "左適時打" in str(raw_text_for_score)
                    and "Virtual三塁止まり" in notes_text
                    and runner_id in notes_text
                    and not self._runner_scored_in_virtual_same_play(snapshot, runner_id)
                )
                rc189_missing_runner_no_virtual_score_unable = (
                    runner_id
                    and "明賀 風太" in str(raw_text_for_score)
                    and "右適時二塁打" in str(raw_text_for_score)
                    and actual_base is not None
                    and virtual_base is None
                    and "score_cause=hit" in str(scored)
                    and not (snapshot.get("scored_text") or [])
                    and not self._runner_scored_in_virtual_same_play(snapshot, runner_id)
                )

                # RC093:
                # 前プレーの失策でActual走者だけ先の塁へ進み、当該プレーでは
                # 安打種別どおりだと同一走者がまだ生還不能に見える場合でも、
                # 後続プレーでVirtual上の同一走者が3アウト成立までに生還していれば、
                # そのActual得点はVirtual再構成上も得点可能だったものとして自責候補に戻す。
                # 例: Actual二塁走者が二塁打で生還、Virtualでは一塁走者が三塁止まり。
                #     次の単打でVirtual三塁走者が生還し、別走者が走塁死して3アウト。
                delayed_virtual_score_allowed = (
                    actual_base == 2
                    and virtual_base == 1
                    and hit_bases == 2
                    and "score_reason=2塁走者適時打得点補完" in str(scored)
                    and self._runner_scores_later_before_virtual3out(virtual_timeline, pr.seq, runner_id)
                )

                if rc071_name_gap_force_batter_unable and virtual_base is None:
                    pending_virtual_unable_earned_slots += 1
                    result.judgments.append(
                        ScoreJudgment(
                            score_no=score_no,
                            runner_text=scored,
                            judgment="非自責点",
                            reason="Virtual進塁では生還不能と推定されるため（Virtual上に同一走者なし）",
                            confidence=90,
                        )
                    )
                    continue

                if rc182_prior_virtual_force_out_unable:
                    pending_virtual_unable_earned_slots += 1
                    result.judgments.append(
                        ScoreJudgment(
                            score_no=score_no,
                            runner_text=scored,
                            judgment="非自責点",
                            reason="Virtual進塁では生還不能と推定されるため（Virtual上で得点走者が封殺済み）",
                            confidence=90,
                        )
                    )
                    continue

                if (
                    actual_scored_removed_virtual_unable
                    or rc189_removed_third_stopped_unable
                    or rc189_missing_runner_no_virtual_score_unable
                ):
                    pending_virtual_unable_earned_slots += 1
                    result.judgments.append(
                        ScoreJudgment(
                            score_no=score_no,
                            runner_text=scored,
                            judgment="非自責点",
                            reason=(
                                "Virtual進塁では生還不能と推定されるため（Virtual上に同一走者なし）"
                                if virtual_base is None
                                else self._virtual_unable_reason(virtual_base, hit_bases, raw_text_for_score)
                            ),
                            confidence=90,
                        )
                    )
                    continue

                if (
                    runner_id
                    and actual_base is not None
                    and virtual_base is not None
                    and not actual_third_groundout_score_allowed
                    and not sac_fly_virtual_score_allowed
                    and not delayed_virtual_score_allowed
                    and (
                        (
                            actual_base > virtual_base
                            and self._has_prior_virtual_gap(actual_report, virtual_timeline, pr.seq, runner_id, getattr(pr, "raw_text", ""))
                            and not self._allow_ordinary_first_to_third_single_sequence(actual_report, virtual_timeline, pr.seq, runner_id, getattr(pr, "raw_text", ""))
                        )
                        or rc043_same_base_single_unable
                        or same_base_second_runner_single_unable
                        or rc026_two_run_single_second_unable
                        or rc112_passed_ball_gap_hit_unable
                        or rc072_error_gap_third_runner_single_unable
                        or rc071_force_batter_error_advance_unable
                        or same_runner_out_in_virtual_same_play
                        or rc152_wild_pitch_virtual_unable
                        or rc071_name_gap_force_batter_unable
                    )
                    # RC032:
                    # 通常は同一プレーでVirtual得点があれば過去GoldData保護のため補正しない。
                    # ただし「安打＋失策」でActualだけ余分に進んだ走者が、次プレーで
                    # Virtual上は生還できない場合は、別走者のVirtual得点があっても補正する。
                    and (
                        not (snapshot.get("scored_text") or [])
                        or current_is_sac_fly
                        or same_base_second_runner_single_unable
                        or rc061_passed_ball_then_single_unable
                        or rc026_two_run_single_second_unable
                        or rc112_passed_ball_gap_hit_unable
                        or rc072_error_gap_third_runner_single_unable
                        or rc071_force_batter_error_advance_unable
                        or same_runner_out_in_virtual_same_play
                        or rc152_wild_pitch_virtual_unable
                        or rc071_name_gap_force_batter_unable
                        or self._allow_virtual_unable_with_other_virtual_score(actual_report, virtual_timeline, pr.seq, runner_id)
                    )
                    and (
                        rc061_passed_ball_then_single_unable
                        or rc026_two_run_single_second_unable
                        or rc112_passed_ball_gap_hit_unable
                        or rc072_error_gap_third_runner_single_unable
                        or rc071_force_batter_error_advance_unable
                        or same_runner_out_in_virtual_same_play
                        or rc152_wild_pitch_virtual_unable
                        or rc071_name_gap_force_batter_unable
                        or not self._runner_scored_in_virtual_same_play(snapshot, runner_id)
                    )
                    and (rc112_passed_ball_gap_hit_unable or not self._can_score_by_hit(virtual_base, hit_bases))
                ):
                    pending_virtual_unable_earned_slots += 1
                    result.judgments.append(
                        ScoreJudgment(
                            score_no=score_no,
                            runner_text=scored,
                            judgment="非自責点",
                            reason=self._virtual_unable_reason(virtual_base, hit_bases, raw_text_for_score),
                            confidence=90,
                        )
                    )
                    continue

                result.judgments.append(
                    ScoreJudgment(
                        score_no=score_no,
                        runner_text=scored,
                        judgment="自責点",
                        reason="得点走者は自責対象で、Virtual3アウト前の得点と判定",
                        confidence=95,
                    )
                )

        # RC037 / Quality17:
        # Team判定は既存GoldData保護のため従来どおりTeam Virtualを採用する。
        # ただし投手別集計・RunDetail比較用には、別走行した Pitcher Virtual
        # （投手交代時にActual状態を引き継いだVirtual）で再判定した結果を保持する。
        result.team_judgments = list(result.judgments)
        result.pitcher_judgments = list(result.judgments)
        result.adopted_source = "Team Virtual"
        result.virtual_diffs = []
        if pitcher_virtual_report is not None:
            pitcher_compare = ActualVirtualComparator(use_pitcher_virtual=True).compare(actual_report, pitcher_virtual_report, pitcher_virtual_report=None)
            result.pitcher_judgments = self._merge_pitcher_judgments_by_charged_pitcher(
                actual_report,
                result.team_judgments,
                list(pitcher_compare.judgments),
            )
            result.judgments = self._adopt_pitcher_judgments_for_entered_pitchers(
                actual_report,
                result.team_judgments,
                result.pitcher_judgments,
            )
            result.adopted_source = "Mixed Team/Pitcher Virtual" if result.judgments != result.team_judgments else "Team Virtual"
            result.virtual_diffs = self._build_virtual_diffs(result.team_judgments, result.pitcher_judgments)
        return result

    def _adopt_pitcher_judgments_for_entered_pitchers(self, actual_report, team_judgments, pitcher_judgments):
        runner_pitcher = self._runner_pitcher_map(getattr(actual_report, "runner_history", []) or [])
        entered_pitchers = self._entered_pitchers(getattr(actual_report, "pitcher_changes", []) or [])
        adopted = []
        max_len = max(len(team_judgments or []), len(pitcher_judgments or []))
        for i in range(max_len):
            team_j = team_judgments[i] if i < len(team_judgments or []) else None
            pitcher_j = pitcher_judgments[i] if i < len(pitcher_judgments or []) else None
            base_j = team_j or pitcher_j
            if base_j is None:
                continue
            charged_pitcher = runner_pitcher.get(self._runner_id(getattr(base_j, "runner_text", "")), "")
            if charged_pitcher in entered_pitchers and pitcher_j is not None:
                adopted.append(pitcher_j)
            else:
                adopted.append(team_j or pitcher_j)
        return adopted

    def _merge_pitcher_judgments_by_charged_pitcher(self, actual_report, team_judgments, pitcher_judgments):
        """Use reliever virtual only for runners charged to a pitcher who entered this half inning.

        A reliever does not inherit pre-entry error/PB benefits, so his runners use the
        Pitcher Virtual reset at entry. Runners charged to the removed pitcher continue
        to receive the ordinary inning reconstruction, including later fielding/PB
        benefits, so they keep the Team Virtual judgment.
        """
        runner_pitcher = self._runner_pitcher_map(getattr(actual_report, "runner_history", []) or [])
        entered_pitchers = self._entered_pitchers(getattr(actual_report, "pitcher_changes", []) or [])
        merged = []
        max_len = max(len(team_judgments or []), len(pitcher_judgments or []))
        for i in range(max_len):
            team_j = team_judgments[i] if i < len(team_judgments or []) else None
            pitcher_j = pitcher_judgments[i] if i < len(pitcher_judgments or []) else None
            base_j = team_j or pitcher_j
            if base_j is None:
                continue
            charged_pitcher = runner_pitcher.get(self._runner_id(getattr(base_j, "runner_text", "")), "")
            if charged_pitcher in entered_pitchers and pitcher_j is not None:
                merged.append(pitcher_j)
            else:
                merged.append(team_j or pitcher_j)
        return merged

    def _runner_pitcher_map(self, runner_history) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in runner_history or []:
            parts = str(line).split(",", 7)
            if len(parts) >= 3:
                out[parts[0].strip()] = parts[2].strip()
        return out

    def _entered_pitchers(self, pitcher_changes) -> set[str]:
        entered: set[str] = set()
        for row in pitcher_changes or []:
            parts = str(row).split(",", 3)
            if len(parts) >= 3:
                pitcher = parts[2].strip()
                if pitcher:
                    entered.add(pitcher)
        return entered

    def _build_virtual_diffs(self, team_judgments: list[ScoreJudgment], pitcher_judgments: list[ScoreJudgment]) -> list[VirtualDiffRow]:
        rows: list[VirtualDiffRow] = []
        max_len = max(len(team_judgments or []), len(pitcher_judgments or []))
        for i in range(max_len):
            tj = team_judgments[i] if i < len(team_judgments or []) else None
            pj = pitcher_judgments[i] if i < len(pitcher_judgments or []) else None
            score_no = getattr(tj or pj, "score_no", i + 1)
            runner_text = getattr(tj or pj, "runner_text", "")
            team_j = getattr(tj, "judgment", "") if tj else ""
            team_r = getattr(tj, "reason", "") if tj else ""
            pitcher_j = getattr(pj, "judgment", "") if pj else ""
            pitcher_r = getattr(pj, "reason", "") if pj else ""
            diff = "TEAM_PITCHER_SPLIT" if (team_j != pitcher_j or team_r != pitcher_r) else ""
            if diff:
                rows.append(VirtualDiffRow(score_no, runner_text, team_j, team_r, pitcher_j, pitcher_r, diff))
        return rows

    def _runner_scores_later_before_virtual3out(self, virtual_timeline, current_seq: int, runner_id: str) -> bool:
        """RC093: 同一走者が後続Virtualプレーで3アウト成立までに生還するか。

        timeline各行の outs_after はプレー後アウト数のため、
        「得点と同時に3アウト目が成立したプレー」は許可対象に含める。
        ただし、そのプレー開始前に既にVirtual3アウトなら対象外。
        """
        if not runner_id:
            return False
        prev_outs = 0
        for row in virtual_timeline or []:
            seq = int(row.get("seq", 0) or 0)
            outs_after = int(row.get("outs_after", 0) or 0)
            if seq <= current_seq:
                prev_outs = outs_after
                continue
            if prev_outs >= 3:
                return False
            raw = str(row.get("raw_text", "") or "")
            is_later_hit_single = (
                any(k in raw for k in ["安打", "適時打", "内野安打", "バントヒット"])
                and not any(k in raw for k in ["二塁打", "三塁打", "本塁打", "ホームラン", "犠飛", "犠牲フライ", "暴投", "捕逸", "失策", "悪送球", "後逸", "落球", "ファンブル"])
            )
            if is_later_hit_single:
                for text in row.get("scored_text", []) or []:
                    if runner_id in str(text):
                        return True
            prev_outs = outs_after
        return False



    def _is_trailing_runner_out_after_timely(self, raw_text: str) -> bool:
        """同一安打プレーで先行走者が得点し、後続走者が本塁等で第三アウトになった形か。

        プレー後アウト数だけを見るとVirtual3アウトに見えるが、
        得点は第三アウト前に成立しているため、Virtual3アウト後得点とは扱わない。
        既存RCへの影響を避けるため、明示的に「一塁走者/二塁走者がさらに本塁/三塁/二塁を狙うもアウト」
        等が書かれている適時打に限定する。
        """
        t = str(raw_text or "")
        if not any(k in t for k in ["適時打", "適時二塁打", "適時三塁打", "安打", "二塁打", "三塁打", "右前安打", "左前安打", "中前安打"]):
            return False
        if not any(k in t for k in [
            "一塁走者がさらに本塁", "一塁走者が本塁", "一塁走者アウト", "一塁走者がアウト",
            "一塁走者がさらに三塁", "一塁走者が三塁",
            "一塁走者がさらに二塁", "一塁走者が二塁",
            "二塁走者がさらに本塁", "二塁走者が本塁", "二塁走者アウト", "二塁走者がアウト",
        ]):
            return False
        if not any(k in t for k in ["本塁狙うもアウト", "本塁を狙うもアウト", "本塁アウト", "アウト（2）", "三塁狙うもアウト", "三塁を狙うもアウト", "三塁アウト", "二塁狙うもアウト", "二塁を狙うもアウト", "二塁アウト"]):
            return False
        if "+1点" not in t:
            return False
        return True

    def _has_unconsumed_virtual_earned_score(self, snapshot: dict, scored_index_in_play: int) -> bool:
        """同一プレーのActual得点順に対応するVirtual自責得点枠があるか。

        失策出塁走者そのものは非自責だが、再構成上その順番の得点が
        別の自責対象走者で成立していれば、自責点の枠として扱う。
        """
        scored = list(snapshot.get("scored_text") or [])
        if scored_index_in_play >= len(scored):
            return False
        v = str(scored[scored_index_in_play])
        return "earned_eligible=True" in v and "score_cause=hit" in v

    def _is_groundout_third_runner_scores(self, raw_text: str) -> bool:
        t = raw_text or ""
        rc180_score_before_trailing_out = (
            "三塁走者が生還" in t
            and "一塁走者が走塁死" in t
            and any(k in t for k in ["ゴロ併殺打", "打者が封殺"])
            and not any(k in t for k in ["失策", "悪送球", "捕逸", "暴投"])
        )
        return rc180_score_before_trailing_out or (
            "三ゴロ" in t
            and "三塁走者が生還" in t
            and any(k in t for k in ["その間に打者が出塁", "打者が出塁", "野手選択の間に出塁"])
            and "二塁走者が封殺" not in t
            and not any(k in t for k in ["失策", "悪送球", "捕逸", "暴投"])
        )

    def _build_virtual_timeline(self, virtual_report):
        """
        各Play終了時点のVirtualアウト数・得点数を記録する。
        seqが飛んだ場合でも、直前の状態を参照できるようリスト化する。
        """
        timeline = []
        for vpr in virtual_report.plays:
            timeline.append(
                {
                    "seq": getattr(vpr, "seq", 0),
                    "outs_after": int(getattr(vpr, "outs_after", 0) or 0),
                    "scores_after": len(getattr(vpr, "scored_text", []) or []),
                    "before_text": getattr(vpr, "before_text", ""),
                    "after_text": getattr(vpr, "after_text", ""),
                    "raw_text": getattr(vpr, "raw_text", ""),
                    "scored_text": list(getattr(vpr, "scored_text", []) or []),
                    "notes": list(getattr(vpr, "notes", []) or []),
                    "outs_text": list(getattr(vpr, "outs_text", []) or []),
                    "moves_text": list(getattr(vpr, "moves_text", []) or []),
                }
            )

        # scored_textはプレー単位の差分なので、累積得点に直す。
        total_scores = 0
        for row in timeline:
            total_scores += row["scores_after"]
            row["scores_after"] = total_scores

        return timeline

    def _snapshot_at_seq(self, timeline, seq: int):
        if not timeline:
            return {"seq": 0, "outs_after": 0, "scores_after": 0, "before_text": "", "after_text": "", "raw_text": ""}

        last = {"seq": 0, "outs_after": 0, "scores_after": 0}
        for row in timeline:
            if row["seq"] <= seq:
                last = row
            else:
                break
        return last

    def _runner_id(self, runner_text: str) -> str:
        text = str(runner_text or "")
        return text.split(":", 1)[0].strip() if ":" in text else ""


    def _runner_scored_in_virtual_same_play(self, snapshot: dict, runner_id: str) -> bool:
        """
        RC020 v2 / RC002回帰修正。
        Actual側の得点走者が同じプレーでVirtual側でも生還している場合は、
        Virtual進塁不能補正を掛けない。

        例: Actualでは前プレーの失策で三塁、Virtualでは二塁に残っていても、
        次の単打でVirtual側も二塁走者として生還しているなら自責点候補を維持する。
        """
        if not runner_id:
            return False
        for text in snapshot.get("scored_text", []) or []:
            if runner_id in str(text):
                return True
        return False

    def _runner_out_in_virtual_same_play(self, snapshot: dict, runner_id: str) -> bool:
        """同一プレーで、Actual得点走者がVirtual側ではアウトになっているか。

        V3.1 Quality13:
        例: Actualは無死満塁から中適時打で三塁走者生還、二塁走者本塁封殺。
        しかしVirtualでは前段の失策出塁を除外して一死一二塁。
        この場合、Actualで生還した走者はVirtual上では二塁走者として本塁封殺されるため、
        「Virtual3アウト前」ではなく「Virtual生還不能」と判定する。
        """
        if not runner_id:
            return False
        for text in snapshot.get("outs_text", []) or []:
            if runner_id in str(text):
                return True
        return False

    def _runner_out_before_virtual_seq(self, virtual_timeline, current_seq: int, runner_id: str) -> bool:
        """得点プレーより前に、同一走者がVirtual側でアウト済みか。"""
        if not runner_id:
            return False
        for row in virtual_timeline or []:
            if int(row.get("seq", 0) or 0) >= int(current_seq or 0):
                continue
            for text in row.get("outs_text", []) or []:
                if runner_id in str(text):
                    return True
        return False

    def _base_of_runner(self, base_text: str, runner_id: str) -> int | None:
        if not runner_id:
            return None
        text = str(base_text or "")
        labels = [(1, "一塁"), (2, "二塁"), (3, "三塁")]
        for base, label in labels:
            marker = f"{label}["
            start = text.find(marker)
            if start < 0:
                continue
            start += len(marker)
            end = text.find("]", start)
            cell = text[start:] if end < 0 else text[start:end]
            if runner_id in cell:
                return base
        return None

    def _hit_bases(self, raw_text: str) -> int:
        text = str(raw_text or "")
        if "本塁打" in text or "ホームラン" in text:
            return 4
        if "三塁打" in text:
            return 3
        if "二塁打" in text:
            return 2
        if "安打" in text or "適時打" in text or "バントヒット" in text:
            return 1
        # RC015: 犠飛は安打ではないが、Virtual進塁判定では
        # 三塁走者だけが生還可能な +1塁相当として扱う。
        if "犠飛" in text or "犠牲フライ" in text:
            return 1
        return 0

    def _can_score_by_hit(self, base: int, hit_bases: int) -> bool:
        if hit_bases >= 4:
            return True
        if hit_bases <= 0:
            return False
        return base + hit_bases >= 4





    def _play_has_prior_passed_ball_gap_scoring_runner(self, actual_report, virtual_timeline, pr) -> bool:
        """同一+2点単打のうち、先行得点走者に捕逸由来のActual-Virtual差があるか。"""
        for scored in (getattr(pr, "scored_text", []) or []):
            st = str(scored or "")
            if "score_reason=3塁走者適時打得点補完" not in st:
                continue
            rid = self._runner_id(st)
            if self._has_prior_passed_ball_gap(actual_report, virtual_timeline, getattr(pr, "seq", 0), rid):
                return True
        return False

    def _is_rc026_two_run_single_play(self, pr) -> bool:
        """RC026: +2点単打で三塁走者・二塁走者が同時生還したプレーか。"""
        raw = str(getattr(pr, "raw_text", "") or "")
        if "+2点" not in raw:
            return False
        if any(w in raw for w in ["失策", "悪送球", "後逸", "落球", "ファンブル"]):
            return False
        if not any(w in raw for w in ["安打", "適時打", "内野安打", "バントヒット"]):
            return False
        scored_list = [str(x) for x in (getattr(pr, "scored_text", []) or [])]
        return (
            any("score_reason=3塁走者適時打得点補完" in x for x in scored_list)
            and any("score_reason=2塁走者適時打得点補完" in x for x in scored_list)
        )

    def _allow_rc026_two_run_single_first_score(self, pr, scored_text: str) -> bool:
        """RC026: +2点単打でVirtual側に1点だけ認めるための限定例外。

        Actual: 一死二・三塁から単打で三塁走者・二塁走者がともに生還。
        Virtual: 一死一・二塁から単打。
        この場合、Virtual二塁走者分の1点は、現実側でも二塁走者が生還しているため
        現実走塁特例を適用して自責候補に残す。
        ただしVirtual一塁走者分までは単打=+1原則により生還不能。
        """
        raw = str(getattr(pr, "raw_text", "") or "")
        scored = str(scored_text or "")
        if "+2点" not in raw:
            return False
        if any(w in raw for w in ["失策", "悪送球", "後逸", "落球", "ファンブル"]):
            return False
        if not any(w in raw for w in ["安打", "適時打", "内野安打", "バントヒット"]):
            return False
        # 対象は、捕逸等でActual三塁まで進んでいた先頭得点走者。
        if "score_reason=3塁走者適時打得点補完" not in scored:
            return False
        # 同一プレーで現実二塁走者も単打で生還している場合に限る。
        return any(
            "score_reason=2塁走者適時打得点補完" in str(x)
            for x in (getattr(pr, "scored_text", []) or [])
        )

    def _allow_no_error_single_gold_special(self, raw_text: str, scored_text: str) -> bool:
        """純粋な単打で現実二塁走者が生還している場合の許可。

        V2.6では単打=+1を原則とするが、失策・後逸等が絡まない単打で、
        現実の二塁走者が生還している場合はVirtualでも生還可能扱いにする。
        RC042のような後逸・悪送球等を含むプレーは対象外。
        """
        raw = str(raw_text or "")
        scored = str(scored_text or "")
        if any(w in raw for w in ["失策", "悪送球", "後逸", "落球", "ファンブル", "捕逸", "暴投"]):
            return False
        if not any(k in raw for k in ["安打", "適時打", "内野安打", "バントヒット"]):
            return False
        return "score_reason=2塁走者適時打得点補完" in scored

    def _batter_error_extra_advance(self, raw_text: str) -> bool:
        """RC042保護: 安打後に打者本人が失策・後逸等で追加進塁したプレー。"""
        import re

        raw = str(raw_text or "")
        return bool(re.search(r"打者が.*(失策|悪送球|後逸|落球|ファンブル).*(二塁|三塁|生還|へ)", raw))

    def _allow_ordinary_first_to_third_single_sequence(self, actual_report, virtual_timeline, current_seq: int, runner_id: str, current_raw_text: str = "") -> bool:
        """RC050限定の安全弁。

        現実で一塁走者が通常単打で三塁へ進み、その後の単打で生還した形は、
        V2系の単打=+1原則だけで「生還不能」に落としすぎない。
        犠飛は既存GoldDataへの影響が大きいため対象外。
        """
        if not runner_id:
            return False
        current_raw = str(current_raw_text or "")
        if not any(w in current_raw for w in ["安打", "適時打", "バントヒット"]):
            return False
        if "犠飛" in current_raw or "犠牲フライ" in current_raw:
            return False
        virtual_by_seq = {row.get("seq"): row for row in virtual_timeline}
        saw_ordinary_first_to_third = False
        for apr in getattr(actual_report, "plays", []) or []:
            seq = getattr(apr, "seq", 0)
            if seq >= current_seq:
                continue
            raw = str(getattr(apr, "raw_text", "") or "")
            if any(w in raw for w in ["失策", "悪送球", "後逸", "落球", "ファンブル", "捕逸", "暴投"]):
                continue
            a_base = self._base_of_runner(getattr(apr, "after_text", ""), runner_id)
            vrow = virtual_by_seq.get(seq, {})
            v_base = self._base_of_runner(vrow.get("after_text", ""), runner_id)
            if any(w in raw for w in ["安打", "適時打", "バントヒット"]) and a_base == 3 and v_base == 2:
                saw_ordinary_first_to_third = True
            if saw_ordinary_first_to_third and a_base == 3 and v_base == 2:
                return True
        return False



    def _allow_actual_third_groundout_score(self, actual_base: int | None, raw_text: str, scored_text: str, virtual_before_text: str = "") -> bool:
        """RC059/RC080/RC087: 三塁走者の凡打・スクイズ生還は生還可能扱い。

        Phoenixでは凡打を原則+0塁として扱うが、記録本文に
        「三塁走者が生還」と明示されている打者アウトの得点プレーは、
        原則としてVirtual生還不能には落とさない。

        RC087: ただし前プレーの失策・悪送球でActualだけ三塁へ進んだ走者は、
        現実の三塁走者生還に引きずられず、Virtual生還不能を優先する。

        RC080: スクイズ成功は通常の凡打とは異なり、三塁走者の生還を
        目的とする犠打系プレーなので、ゴロ表記がなくても得点可能扱いにする。
        ただし、失策・捕逸・暴投など非自責要因による生還は対象外。
        """
        if actual_base != 3:
            return False
        raw = str(raw_text or "")
        scored = str(scored_text or "")
        if "三塁走者が生還" not in raw and "score_reason=三塁走者が生還" not in scored:
            return False
        is_groundout_score = "ゴロ" in raw
        is_squeeze_score = "スクイズ成功" in raw or "スクイズ" in raw
        if not (is_groundout_score or is_squeeze_score):
            return False
        if any(w in raw for w in ["失策", "悪送球", "後逸", "落球", "ファンブル", "捕逸", "暴投"]):
            return False
        # 走者アウト・野選絡みは、打者アウトの単純なゴロ生還とは別扱い。
        # RC036のように「二塁走者走塁死、その間に打者出塁、三塁走者生還」は
        # Virtual生還不能を維持する。
        if any(w in raw for w in ["走塁死", "封殺", "その間に打者が出塁", "野選", "併殺"]):
            return False
        return True

    def _virtual_unable_reason(self, virtual_base: int, hit_bases: int, raw_text: str = "") -> str:
        text = str(raw_text or "")
        if "押し出し" in text or "四球" in text or "死球" in text:
            return f"Virtual進塁では生還不能と推定されるため（Virtual{virtual_base}塁 + 押し出し）"
        if "暴投" in text or "wild_pitch" in text:
            return f"Virtual進塁では生還不能と推定されるため（Virtual{virtual_base}塁 + 暴投）"
        if "捕逸" in text or "passed_ball" in text:
            return f"Virtual進塁では生還不能と推定されるため（Virtual{virtual_base}塁 + 捕逸）"
        return f"Virtual進塁では生還不能と推定されるため（Virtual{virtual_base}塁 + 安打{hit_bases}塁）"


    def _has_later_running_homer(self, actual_report, current_seq: int) -> bool:
        """RC043安全弁。
        同一半イニング後続にランニングホームランがある大量得点回でのみ、
        「二塁走者単打生還だがVirtual単打+1では未生還」の3点目補正を許可する。
        既存GoldData（RC006等）の通常+2点単打判定へ影響させないための限定条件。
        """
        for apr in getattr(actual_report, "plays", []) or []:
            if getattr(apr, "seq", 0) > current_seq and "ランニングホームラン" in str(getattr(apr, "raw_text", "") or ""):
                return True
        return False

    def _allow_virtual_unable_with_other_virtual_score(self, actual_report, virtual_timeline, current_seq: int, runner_id: str) -> bool:
        """
        RC032専用の安全弁。
        同一プレーでVirtual側に別走者の得点がある場合でも、
        prior gapが「安打＋失策による追加進塁」ならVirtual生還不能補正を許可する。
        RC002のような純粋な打者失策出塁プレーはここでは許可しない。
        """
        if not runner_id:
            return False
        virtual_by_seq = {row.get("seq"): row for row in virtual_timeline}
        hit_words = ["安打", "適時打", "二塁打", "三塁打", "本塁打", "ホームラン", "バントヒット"]
        err_words = ["失策", "悪送球", "後逸", "落球", "ファンブル"]
        for apr in getattr(actual_report, "plays", []):
            seq = getattr(apr, "seq", 0)
            if seq >= current_seq:
                continue
            raw = str(getattr(apr, "raw_text", "") or "")
            has_hit_error_gap = any(w in raw for w in hit_words) and any(w in raw for w in err_words)
            has_error_word = any(w in raw for w in err_words)

            vrow = virtual_by_seq.get(seq, {})
            a_base = self._base_of_runner(getattr(apr, "after_text", ""), runner_id)
            v_base = self._base_of_runner(vrow.get("after_text", ""), runner_id)

            # RC040:
            # 打者失策出塁プレーで、既存走者が「通常進塁＋失策の間に追加進塁」した場合、
            # Virtualでは打者アウト換算となり、その走者は元塁に残ることがある。
            # 次の単打で別走者がVirtual得点していても、当該走者がVirtual上は生還不能なら
            # 「Virtual生還不能」補正を許可する。
            # ただしRC002等への影響を抑えるため、Actual-Virtualで2塁以上の差があり、
            # かつ「失策の間に」「悪送球で」等の追加進塁が明示される場合に限定する。
            has_explicit_error_extra_advance = (
                has_error_word
                and ("により出塁" in raw)
                and ("失策の間に" in raw or "悪送球で" in raw or "後逸で" in raw or "落球で" in raw)
                and a_base is not None
                and v_base is not None
                and (a_base - v_base) >= 2
            )
            has_batter_error_runner_gap = (
                has_error_word
                and ("により出塁" in raw)
                and a_base is not None
                and v_base is not None
                and a_base > v_base
            )

            if "+" in raw and "点" in raw and has_batter_error_runner_gap and not (has_hit_error_gap or has_explicit_error_extra_advance):
                continue
            if not (has_hit_error_gap or has_explicit_error_extra_advance or has_batter_error_runner_gap):
                continue
            if a_base is not None and v_base is not None and a_base > v_base:
                return True
        return False


    def _has_prior_pure_batter_error_out_gap(self, actual_report, virtual_timeline, current_seq: int, runner_id: str) -> bool:
        """RC073/RC074: 打者失策出塁をVirtualアウト換算したことで生じた走者差。

        安打＋失策の追加進塁（例: 右前適時打後ファンブル）は対象外。
        対象は「打者が失策/落球/悪送球等により出塁」し、Virtualでは
        B->OUT補正が入ったプレーで、同一走者がActualでは先の塁、
        Virtualでは手前の塁に残っている場合。
        """
        if not runner_id:
            return False
        virtual_by_seq = {row.get("seq"): row for row in virtual_timeline}
        err_words = ["失策", "悪送球", "後逸", "落球", "ファンブル"]
        hit_words = ["安打", "適時打", "二塁打", "三塁打", "本塁打", "ホームラン", "バントヒット"]
        for apr in getattr(actual_report, "plays", []) or []:
            seq = getattr(apr, "seq", 0)
            if seq >= current_seq:
                continue
            raw = str(getattr(apr, "raw_text", "") or "")
            if "により出塁" not in raw:
                continue
            if not any(w in raw for w in err_words):
                continue
            # 安打後失策は、犠飛での得点数振替を許可しない（RC031保護）。
            if any(w in raw for w in hit_words):
                continue
            vrow = virtual_by_seq.get(seq, {})
            notes = "\n".join(str(x) for x in (vrow.get("notes") or []))
            if "打者失策出塁をB->OUT" not in notes:
                continue
            a_base = self._base_of_runner(getattr(apr, "after_text", ""), runner_id)
            v_base = self._base_of_runner(vrow.get("after_text", ""), runner_id)
            if a_base is not None and v_base is not None and a_base > v_base:
                return True
        return False

    def _has_prior_batter_error_existing_runner_gap(self, actual_report, virtual_timeline, current_seq: int, runner_id: str) -> bool:
        """RC072: 打者失策出塁プレー内の既存走者進塁除外によるActual-Virtual差。

        対象は「打者が失策で出塁」した同一プレー内で、既存走者が
        失策の間に進塁し、Virtualではその進塁が除外されて同一走者が
        手前の塁に残った場合に限る。
        """
        if not runner_id:
            return False
        virtual_by_seq = {row.get("seq"): row for row in virtual_timeline}
        for apr in getattr(actual_report, "plays", []) or []:
            seq = getattr(apr, "seq", 0)
            if seq >= current_seq:
                continue
            raw = str(getattr(apr, "raw_text", "") or "")
            if "により出塁" not in raw:
                continue
            if not any(w in raw for w in ["失策", "悪送球", "後逸", "落球", "ファンブル"]):
                continue
            # RC072は、Actual一塁走者が打者失策出塁プレー内で二塁へ進み、
            # 次の単打でActual三塁・Virtual二塁の差になったケースに限定する。
            # 二塁走者が三塁へ進んだ既存GoldData（RC025/RC031/RC037等）は
            # 従来どおり現実走塁特例を維持する。
            if "一塁走者が失策の間に二塁へ" not in raw:
                continue
            vrow = virtual_by_seq.get(seq, {})
            a_base = self._base_of_runner(getattr(apr, "after_text", ""), runner_id)
            v_base = self._base_of_runner(vrow.get("after_text", ""), runner_id)
            if a_base is not None and v_base is not None and a_base > v_base:
                return True
        return False


    def _has_prior_passed_ball_gap(self, actual_report, virtual_timeline, current_seq: int, runner_id: str) -> bool:
        """RC061: 直前以前の捕逸除外によりActualだけ先の塁にいるか。"""
        if not runner_id:
            return False
        virtual_by_seq = {row.get("seq"): row for row in virtual_timeline}
        for apr in getattr(actual_report, "plays", []) or []:
            seq = getattr(apr, "seq", 0)
            if seq >= current_seq:
                continue
            raw = str(getattr(apr, "raw_text", "") or "")
            if "捕逸" not in raw:
                continue
            vrow = virtual_by_seq.get(seq, {})
            a_base = self._base_of_runner(getattr(apr, "after_text", ""), runner_id)
            v_base = self._base_of_runner(vrow.get("after_text", ""), runner_id)
            if a_base is not None and v_base is not None and a_base > v_base:
                return True
        return False


    def _has_prior_virtual_gap(self, actual_report, virtual_timeline, current_seq: int, runner_id: str, current_raw_text: str = "") -> bool:
        """
        RC015対応。
        過去GoldData維持のため、Virtual進塁不能補正は
        「過去プレーでActualだけ進塁し、Virtualでは同じ走者が元塁に残った」場合に限定する。
        捕逸は従来どおり対象。
        FieldError由来のgapは、RC015のような「犠飛で三塁走者が生還」時に限って対象にし、
        後続安打の通常得点GoldDataを壊さない。
        """
        if not runner_id:
            return False
        virtual_by_seq = {row.get("seq"): row for row in virtual_timeline}
        for apr in getattr(actual_report, "plays", []):
            seq = getattr(apr, "seq", 0)
            if seq >= current_seq:
                continue
            raw = str(getattr(apr, "raw_text", "") or "")
            current_raw = str(current_raw_text or "")

            is_passed_ball_gap = "捕逸" in raw

            # RC020 v3:
            # 「牽制悪送球」「送球間」など、打者の打撃結果とは独立した失策進塁は
            # Virtual生還不能の対象にする。
            # 一方、RC002のような「打者が失策出塁した同一プレー内の走者進塁」は、
            # 後続安打の公式判断を壊しやすいため、V2.6では対象外に戻す。
            has_error_word = any(w in raw for w in ["失策", "悪送球", "後逸", "落球", "ファンブル"])
            batter_reached_on_error = ("により出塁" in raw) and has_error_word
            # RC020 v4 / RC015回帰修正:
            # 打者失策出塁プレー内の走者進塁は原則としてVirtual生還不能補正から外す。
            # ただし、その後の得点プレーが犠飛の場合は、Virtual上で三塁に到達していない
            # 走者が犠飛だけで生還できないため、補正対象に戻す。
            current_is_sac_fly = ("犠飛" in current_raw) or ("犠牲フライ" in current_raw)
            current_is_hit = any(w in current_raw for w in ["安打", "適時打", "二塁打", "三塁打", "本塁打", "ホームラン", "バントヒット"])
            current_is_walk_force = ("押し出し" in current_raw) or ("四球" in current_raw) or ("死球" in current_raw)
            current_is_fielder_choice = ("野手選択" in current_raw) or ("野選" in current_raw)
            independent_error_advance = (
                ("牽制" in raw)
                or ("送球間" in raw)
                or (not batter_reached_on_error)
                or (
                    batter_reached_on_error
                    and (current_is_sac_fly or current_is_hit or current_is_walk_force or current_is_fielder_choice)
                )
            )
            is_field_error_gap = has_error_word and independent_error_advance

            # RC026:
            # Actualでは盗塁成功で進んだが、Virtualでは手前の捕逸・失策除外により
            # 移動先が埋まっているため盗塁を無視したケースも、
            # 「Virtual生還不能」の原因差分として扱う。
            is_steal_gap = "盗塁成功" in raw

            if not (is_passed_ball_gap or is_field_error_gap or is_steal_gap):
                continue

            vrow = virtual_by_seq.get(seq, {})
            a_base = self._base_of_runner(getattr(apr, "after_text", ""), runner_id)
            v_base = self._base_of_runner(vrow.get("after_text", ""), runner_id)
            if a_base is not None and v_base is not None and a_base > v_base:
                return True
        return False
