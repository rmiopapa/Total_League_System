from __future__ import annotations

from src.move.models import Move, BaseState
from src.parser.play import Play


class MoveCompleter:
    """
    Phoenix alpha3

    MoveGeneratorが作った明示Moveを、before_base_state と final_base_state を使って補完する。

    責務:
      - 不足Moveを補完する
      - Move順を整える
      - 同一sourceの重複を整理する

    禁止:
      - Runnerを動かさない
      - 自責点判定しない
    """

    ORDER = {"3": 0, "2": 1, "1": 2, "B": 3}

    def __init__(self, virtual_hit_advance_limit: bool = False):
        # False: Actual Runner 用。現実に得点した走者は得点として補完する。
        # True : Virtual Runner 用。単打=+1等のRC009 Virtual進塁ルールを適用する。
        self.virtual_hit_advance_limit = virtual_hit_advance_limit

    def complete(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        result = list(moves)

        if play.is_wild_pitch or play.is_passed_ball:
            result = self._complete_wild_pitch_or_passed_ball(play, result, before)
        elif getattr(play, "is_interference", False) or "打撃妨害" in (play.raw_text or ""):
            result = self._complete_interference_award(play, result, before)
        elif "野手選択" in (play.raw_text or "") or "野選" in (play.raw_text or ""):
            result = self._complete_fielders_choice(play, result, before)
        elif play.is_walk or play.is_hbp:
            result = self._complete_force_award(play, result, before)
        elif play.is_hit:
            result = self._complete_hit(play, result, before)
        else:
            result = self._complete_by_final_state(play, result, before)

        # RC076 Warning Zero:
        # TextLiveに「二塁走者が戻れずリタッチアウト」と出るが、
        # 実際のbefore状態に二塁走者がおらず、final_stateから見ると
        # 一塁走者が消えているケースがある。
        # このまま 2->OUT を適用すると「2塁に走者なし」警告となり、
        # さらに一塁走者が残って次打者出塁時に衝突する。
        # アウト増加とfinal_stateで「消えた既存走者」が一意に決まる場合だけ、
        # OUT moveのsourceを実在する走者の塁へ補正する。
        result = self._normalize_missing_out_source_by_final_state(play, result, before)

        # RC115 Warning cleanup:
        # TextLive can contain an inconsistent runner label on sac flies, e.g.
        # before = 1,3 but text says 「二塁走者が三塁へ、三塁走者が生還」
        # and final = 3.  The score move (3->H) is correct, but the advance
        # source 2 does not exist, causing an Actual warning and leaving the
        # real 1B runner on first.  When final_state identifies a single
        # existing runner that must have moved to the target base, rewrite the
        # missing-source advance to that real source.
        result = self._normalize_missing_advance_source_by_final_state(play, result, before)

        return self._dedupe_sort(result)



    def _normalize_missing_advance_source_by_final_state(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        """Fix a non-OUT advance whose source base is empty when final_state uniquely identifies the real source.

        This is intentionally conservative: it only rewrites ordinary base-to-base advances,
        never scoring moves, outs, batter moves, or cases with multiple possible runners.
        """
        if self.virtual_hit_advance_limit:
            return moves

        before_set = before.as_set()
        final_set = play.final_base_state.as_set()
        if not before_set or not final_set:
            return moves

        fixed = list(moves)
        for i, mv in enumerate(list(fixed)):
            src_s = str(getattr(mv, "source", ""))
            tgt_s = str(getattr(mv, "target", ""))
            if src_s not in {"1", "2", "3"} or tgt_s not in {"1", "2", "3"}:
                continue
            src = int(src_s)
            tgt = int(tgt_s)
            if src in before_set:
                continue
            if tgt not in final_set:
                continue

            # Remove runners that are already explicitly scored/out or otherwise moved by other moves.
            used_sources = {
                int(str(getattr(other, "source", "")))
                for j, other in enumerate(fixed)
                if j != i and str(getattr(other, "source", "")) in {"1", "2", "3"}
            }
            candidates = sorted([b for b in before_set if b not in used_sources and b < tgt])
            if len(candidates) != 1:
                continue
            real_src = str(candidates[0])
            fixed[i] = Move(real_src, tgt_s, f"{real_src}塁走者進塁補正", getattr(mv, "cause_type", "inferred"), getattr(mv, "pitcher_charge", False), getattr(mv, "virtual_allow", True), getattr(mv, "explicit", False))
        return fixed

    def _normalize_missing_out_source_by_final_state(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        """RC076: source塁に走者がいないOUTを、final_stateで消えた走者へ安全補正する。"""
        before_set = before.as_set()
        final_set = play.final_base_state.as_set()
        if not before_set:
            return moves
        try:
            outs_delta = int(getattr(play, "outs_after", 0) or 0) - int(getattr(play, "outs_before", 0) or 0)
        except Exception:
            outs_delta = 0
        if outs_delta <= 0:
            return moves

        fixed = list(moves)
        for i, mv in enumerate(list(fixed)):
            src = str(getattr(mv, "source", ""))
            tgt = str(getattr(mv, "target", ""))
            if tgt != "OUT" or src not in {"1", "2", "3"}:
                continue
            if int(src) in before_set:
                continue

            # 既に別Moveで処理されている走者は候補から除く。
            moved_sources = {
                int(str(getattr(other, "source", "")))
                for j, other in enumerate(fixed)
                if j != i and str(getattr(other, "source", "")) in {"1", "2", "3"}
            }
            candidates = sorted((before_set - final_set) - moved_sources)
            if len(candidates) != 1:
                continue
            real_src = str(candidates[0])
            fixed[i] = Move(real_src, "OUT", f"{real_src}塁走者走塁死補正", getattr(mv, "cause_type", "out"), getattr(mv, "pitcher_charge", False), getattr(mv, "virtual_allow", True), getattr(mv, "explicit", False))
        return fixed

    def _complete_wild_pitch_or_passed_ball(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        cause = "wild_pitch" if play.is_wild_pitch else "passed_ball"
        reason_word = "暴投" if play.is_wild_pitch else "捕逸"
        pitcher_charge = play.is_wild_pitch
        virtual_allow = play.is_wild_pitch

        # 従来はB->1を落としていたため、
        # 「四球、二塁走者が暴投で三塁へ、三塁走者が暴投で生還」
        # のような複合プレーで打者走者が消え、後続プレーの警告・得点カウント漏れにつながっていた。
        # RC023: 四死球を伴うWP/PBでは打者走者を保持する。
        # RC069: 捕逸/暴投による振り逃げ出塁も、Actualでは打者走者を保持する。
        # 従来はWP/PB系プレーの補完で一律 B move を捨てていたため、
        # 「捕手の捕逸により振り逃げ出塁、打者が出塁」がActualにも反映されず、
        # 後続の盗塁・進塁・得点で「走者なし」警告が発生していた。
        dropped_third_batter_moves = [
            m for m in moves
            if m.source == "B" and m.target in {"1", "2", "3"}
            and ("振り逃げ" in str(m.reason) or "振逃" in str(m.reason))
        ]
        if dropped_third_batter_moves:
            result = list(moves)
        else:
            result = [m for m in moves if m.source != "B"]

        if getattr(play, "is_walk", False):
            self._add_if_missing(result, "B", "1", "打者四球", "walk", True, True)
        elif getattr(play, "is_hbp", False):
            self._add_if_missing(result, "B", "1", "打者死球", "hbp", True, True)

        before_set = before.as_set()
        final_set = play.final_base_state.as_set()
        scored_sources = set()

        if play.runs_scored > 0:
            # RC096:
            # TextLive may summarize WP/PB like
            # 「一、二塁走者が投手の暴投で進む +1点 ... ２死二塁」.
            # In that text the scoring runner is not explicitly written as 生還.
            # If there is no runner on third, infer the scoring source from
            # before/final base states.  For 1,2 -> final 2 with +1, the 2B
            # runner scores and the 1B runner advances to 2B.
            inferred_scored = self._infer_wp_pb_scored_sources(before_set, final_set, play.runs_scored)
            for src in sorted(inferred_scored, reverse=True):
                runner_word = {1: "一塁走者", 2: "二塁走者", 3: "三塁走者"}.get(src, f"{src}塁走者")
                score_cause, score_reason_word = self._score_cause_for_runner_score(play, runner_word, cause, reason_word)
                self._add_or_replace(
                    result, str(src), "H", f"{runner_word}{score_reason_word}生還",
                    score_cause, score_cause == "wild_pitch", score_cause != "passed_ball"
                )
                scored_sources.add(src)

        before_remaining = before_set - scored_sources

        if play.runs_scored > 0:
            text = play.raw_text or ""
            rc152_only_third_scores = (
                play.runs_scored == 1
                and before_set == {1, 2, 3}
                and final_set == {1, 2}
                and "三塁走者" in text
                and "進む" in text
                and not any(k in text for k in ["一、二塁走者", "一、三塁走者", "二、三塁走者"])
            )
            if rc152_only_third_scores:
                # RC152:
                # 満塁から三塁走者のみが暴投で生還し、残り一・二塁。
                # 一塁走者まで二塁へ送ると既存二塁走者と衝突する。
                stationary = before_remaining & final_set
                moving_sources = sorted(before_remaining - stationary, reverse=True)
                open_targets = sorted(final_set - stationary, reverse=True)
            else:
                # With a scoring WP/PB, TextLive often summarizes all runner movement.
                # Do not freeze a runner merely because the same base appears in final_set;
                # after a higher runner scores, the lower runner may occupy that base.
                moving_sources = sorted(before_remaining, reverse=True)
                open_targets = sorted(final_set, reverse=True)
            used_targets = set()
            for src in moving_sources:
                candidates = [t for t in open_targets if t > src and t not in used_targets]
                if not candidates:
                    continue
                tgt = min(candidates, key=lambda t: (t - src, -t))
                used_targets.add(tgt)
                self._add_or_replace(result, str(src), str(tgt), f"{src}塁走者{reason_word}進塁", cause, pitcher_charge, virtual_allow)
        else:
            # 同じ塁に残る走者を先に確保し、残りだけを進塁させる。
            # RC156: 既に明示Moveがある場合は、そのsource/targetを補完候補から外す。
            # 例: 1・2塁で「一塁走者が二塁へ、二塁走者が捕逸で三塁へ」。
            # 2->3を尊重せず二塁走者をstationary扱いすると、1->3を誤補完する。
            occupied_targets = {int(m.target) for m in result if str(getattr(m, "target", "")) in {"1", "2", "3"}}
            moved_sources = {int(m.source) for m in result if str(getattr(m, "source", "")) in {"1", "2", "3"}}
            remaining_sources = before_remaining - moved_sources
            available_targets = final_set - occupied_targets
            stationary = remaining_sources & available_targets
            moving_sources = sorted(remaining_sources - stationary, reverse=True)
            open_targets = sorted(available_targets - stationary, reverse=True)
            used_targets = set()
            for src in moving_sources:
                candidates = [t for t in open_targets if t > src and t not in used_targets]
                if not candidates:
                    continue
                tgt = min(candidates, key=lambda t: (t - src, -t))
                used_targets.add(tgt)
                self._add_or_replace(result, str(src), str(tgt), f"{src}塁走者{reason_word}進塁", cause, pitcher_charge, virtual_allow)

        return result


    def _infer_wp_pb_scored_sources(self, before_set: set[int], final_set: set[int], runs_scored: int) -> set[int]:
        """Infer which existing runners scored on WP/PB from base-state delta.

        Prefer higher bases, but choose a set that allows the remaining runners to
        map to the final base state by advancing forward.
        """
        if runs_scored <= 0:
            return set()

        candidates = sorted(before_set, reverse=True)
        if runs_scored >= len(candidates):
            return set(candidates)

        from itertools import combinations

        # Try all combinations of scoring sources, preferring higher-base runners.
        combos = list(combinations(candidates, runs_scored))
        combos.sort(key=lambda c: tuple(-x for x in c))
        for combo in combos:
            scored = set(combo)
            remaining = sorted(before_set - scored, reverse=True)
            stationary = (before_set - scored) & final_set
            moving_sources = sorted(set(remaining) - stationary, reverse=True)
            open_targets = sorted(final_set - stationary, reverse=True)
            used = set()
            ok = True
            for src in moving_sources:
                possible = [t for t in open_targets if t > src and t not in used]
                if not possible:
                    ok = False
                    break
                tgt = min(possible, key=lambda t: (t - src, -t))
                used.add(tgt)
            if ok:
                return scored

        # Fallback: highest runners score.
        return set(candidates[:runs_scored])

    def _score_cause_for_runner_score(self, play: Play, runner_word: str, default_cause: str, default_reason_word: str) -> tuple[str, str]:
        """Return WP/PB score cause by runner segment, not by whole play.

        RC057: A single text can say
        「一塁走者が暴投で二塁へ、二塁走者が暴投で三塁へ、三塁走者が捕逸で生還」.
        In that case the scoring runner's cause is passed_ball even though the play also contains 暴投.
        """
        text = play.raw_text or ""
        if runner_word in text:
            idx = text.find(runner_word)
            tail = text[idx:]
            boundaries = []
            for other in ["一塁走者", "二塁走者", "三塁走者", "打者"]:
                if other == runner_word:
                    continue
                p = tail.find(other, len(runner_word))
                if p != -1:
                    boundaries.append(p)
            end = min(boundaries) if boundaries else len(tail)
            segment = tail[:end]
            if "生還" in segment and "捕逸" in segment:
                return "passed_ball", "捕逸"
            if "生還" in segment and "暴投" in segment:
                return "wild_pitch", "暴投"
        return default_cause, default_reason_word


    def _complete_interference_award(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        """
        RC015 Warning Zero補強

        「捕手の打撃妨害により出塁 無死一、二塁」のように、
        TextLive上で一塁走者の押し出し進塁が明示されないケースを補完する。

        Actualでは打者を一塁に置き、押し出される走者を進める。
        ただし投手責任外なので、Virtual側では virtual_allow=False として
        打者アウト換算・走者進塁除外の対象にする。
        """
        cause = "interference"
        reason_word = "打撃妨害"
        result = list(moves)
        before_set = before.as_set()

        if 1 in before_set and 2 in before_set and 3 in before_set:
            self._add_or_replace(result, "3", "H", f"三塁走者押し出し{reason_word}生還", cause, False, False)
            self._add_or_replace(result, "2", "3", f"二塁走者押し出し{reason_word}進塁", cause, False, False)
            self._add_or_replace(result, "1", "2", f"一塁走者押し出し{reason_word}進塁", cause, False, False)
        elif 1 in before_set and 2 in before_set:
            self._add_or_replace(result, "2", "3", f"二塁走者押し出し{reason_word}進塁", cause, False, False)
            self._add_or_replace(result, "1", "2", f"一塁走者押し出し{reason_word}進塁", cause, False, False)
        elif 1 in before_set:
            self._add_or_replace(result, "1", "2", f"一塁走者押し出し{reason_word}進塁", cause, False, False)

        self._add_if_missing(result, "B", "1", f"打者{reason_word}", cause, False, False)
        return result



    def _complete_fielders_choice(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        """
        RC019追加補正

        「三塁手の野手選択の間に出塁 +1点 １死一、三塁」のように、
        TextLive上で「三塁走者が生還」「二塁走者が三塁へ」が明示されない
        野選プレーを、得点・残塁状況からActual/Virtual双方で補完する。

        野選は失策ではないため、投手責任候補として扱う。
        """
        result = list(moves)
        before_set = before.as_set()
        final_set = play.final_base_state.as_set()

        scored_sources: set[int] = set()
        scored_needed = max(0, getattr(play, "runs_scored", 0) or 0)

        # RC090:
        # Virtualでは、直前の失策出塁プレーで三塁進塁を除外した結果、
        # 現実は満塁でもVirtualは一・二塁に留まることがある。
        # その直後の野選得点を「2塁走者野選得点補完」として繰り上げると、
        # 現実三塁走者の生還に引きずられてVirtual得点を作ってしまう。
        # 野選の得点補完は、Virtual上にも三塁走者が存在する場合だけ 3->H として認める。
        # 三塁走者がいない場合は得点補完を抑止し、塁詰まりの進塁だけを補完する。
        if (
            self.virtual_hit_advance_limit
            and self._is_sac_bunt_fielders_choice_batter_out_multi_score(play.raw_text or "")
            and {1, 2} <= before_set
            and scored_needed >= 2
        ):
            self._add_or_replace(result, "2", "H", "2塁走者野選得点補完（犠打野選・打者走塁死）", "fielder_choice", True, True)
            self._add_or_replace(result, "1", "H", "1塁走者野選得点補完（犠打野選・打者走塁死）", "fielder_choice", True, True)
            return result

        if self.virtual_hit_advance_limit and scored_needed > 0 and 3 not in before_set:
            if 2 in before_set and 3 in final_set and not any(m.source == "2" for m in result):
                self._add_or_replace(result, "2", "3", "二塁走者野選進塁補完（Virtual得点抑止）", "fielder_choice", True, True)
            if 1 in before_set and 2 in final_set and not any(m.source == "1" for m in result):
                self._add_or_replace(result, "1", "2", "一塁走者野選進塁補完（Virtual得点抑止）", "fielder_choice", True, True)
            if "出塁" in (play.raw_text or "") or 1 in final_set:
                self._add_if_missing(result, "B", "1", "打者野選出塁", "fielder_choice", True, True)
            return result

        # 得点は本塁に近い走者から補完する。
        # Virtualでは2塁・1塁からの野選得点は安易に補完しない。
        score_sources = [3] if self.virtual_hit_advance_limit else [3, 2, 1]
        for src in score_sources:
            if scored_needed <= 0:
                break
            if src in before_set and not any(m.source == str(src) for m in result):
                self._add_or_replace(result, str(src), "H", f"{src}塁走者野選得点補完", "fielder_choice", True, True)
                scored_sources.add(src)
                scored_needed -= 1

        # 打者出塁。野選は通常B->1。
        if "出塁" in (play.raw_text or "") or 1 in final_set:
            self._add_if_missing(result, "B", "1", "打者野選出塁", "fielder_choice", True, True)

        occupied_after = {int(m.target) for m in result if m.target in {"1", "2", "3"}}
        remaining = sorted(before_set - scored_sources, reverse=True)

        # 同じ塁に残れる走者を優先して固定する。
        for src in list(remaining):
            if src in final_set and src not in occupied_after and not any(m.source == str(src) for m in result):
                occupied_after.add(src)
                remaining.remove(src)

        # 残りの走者をfinal_stateに合わせて補完。
        for src in remaining:
            if any(m.source == str(src) for m in result):
                continue
            candidates = [b for b in sorted(final_set, reverse=True) if b > src and b not in occupied_after]
            if not candidates:
                continue
            tgt = candidates[0]
            occupied_after.add(tgt)
            self._add_or_replace(result, str(src), str(tgt), f"{src}塁走者野選進塁補完", "fielder_choice", True, True)

        return result

    def _is_sac_bunt_fielders_choice_batter_out_multi_score(self, text: str) -> bool:
        t = str(text or "")
        if not ("野手選択" in t or "野選" in t):
            return False
        if "記録上犠打" not in t:
            return False
        if "打者が走塁死" not in t:
            return False
        if not any(k in t for k in ["+2点", "+２点"]):
            return False
        if any(k in t for k in ["失策", "悪送球", "後逸", "ファンブル", "落球", "捕逸", "暴投"]):
            return False
        return True

    def _complete_force_award(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        cause = "walk" if play.is_walk else "hbp"
        reason_word = "四球" if play.is_walk else "死球"
        result = list(moves)

        before_set = before.as_set()

        def add_force_if_missing(src: str, tgt: str, reason: str) -> None:
            if not any(m.source == src for m in result):
                self._add_or_replace(result, src, tgt, reason, cause, True, True)

        if 1 in before_set and 2 in before_set and 3 in before_set:
            add_force_if_missing("3", "H", f"三塁走者押し出し{reason_word}生還")
            add_force_if_missing("2", "3", f"二塁走者押し出し{reason_word}進塁")
            add_force_if_missing("1", "2", f"一塁走者押し出し{reason_word}進塁")
        elif 1 in before_set and 2 in before_set:
            add_force_if_missing("2", "3", f"二塁走者押し出し{reason_word}進塁")
            add_force_if_missing("1", "2", f"一塁走者押し出し{reason_word}進塁")
        elif 1 in before_set:
            add_force_if_missing("1", "2", f"一塁走者押し出し{reason_word}進塁")

        # B->1はGeneratorが作るが、保険として追加
        self._add_if_missing(result, "B", "1", f"打者{reason_word}", cause, True, True)

        return result

    def _complete_hit(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        if self.virtual_hit_advance_limit:
            return self._complete_hit_virtual(play, moves, before)
        return self._complete_hit_actual(play, moves, before)

    def _complete_hit_actual(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        """Actual Runner用。RC008までの現実得点補完を維持する。"""
        result = list(moves)
        before_set = before.as_set()
        final_set = play.final_base_state.as_set()

        # Bがない場合は安打種別に応じて保険追加。
        # RC019: 本塁打は B->H として得点カウントする。
        if not any(m.source == "B" for m in result):
            hit_bases = self._hit_bases(play.raw_text)
            if hit_bases >= 4:
                self._add_or_replace(result, "B", "H", "打者本塁打", "hit", True, True)
            elif hit_bases == 3:
                self._add_or_replace(result, "B", "3", "打者三塁打", "hit", True, True)
            elif hit_bases == 2:
                self._add_or_replace(result, "B", "2", "打者二塁打", "hit", True, True)
            else:
                self._add_or_replace(result, "B", "1", "打者単打", "hit", True, True)

        # RC178: 二死一三塁から「内野安打、打者が封殺」。
        # 打者走者はアウトで、一塁走者は二塁へ進む。通常の単打補完で
        # 一塁走者を三塁へ送ると既存三塁走者と衝突する。
        if (
            "内野安打" in (play.raw_text or "")
            and "打者が封殺" in (play.raw_text or "")
            and 1 in before_set
            and 2 in final_set
            and not any(m.source == "1" for m in result)
        ):
            self._add_or_replace(result, "1", "2", "一塁走者二塁進塁補完（打者封殺）", "inferred", False, True)

        # 得点補完
        if play.runs_scored > 0:
            # 高い塁から生還させる
            scored_needed = play.runs_scored
            for src in ["3", "2", "1"]:
                if scored_needed <= 0:
                    break
                if int(src) in before_set and not any(m.source == src for m in result):
                    self._add_or_replace(result, src, "H", f"{src}塁走者適時打得点補完", "hit", True, True)
                    scored_needed -= 1

        # RC072 Warning Zero補強:
        # 満塁から単打・内野安打で1点入り、コールド等で試合終了した場合、
        # TextLiveに最終塁状況が出ず final_state が空になることがある。
        # このときだけ、打者B->1に押し上げられる既存一塁/二塁走者を補完する。
        # final_state が読めている通常ケースは従来ロジックに任せ、既存RCへの影響を避ける。
        if not final_set and ("試合終了" in (play.raw_text or "") or "コールド" in (play.raw_text or "")):
            self._complete_forced_chain_on_batter_to_first(result, before_set)

        # V3.1 Quality07:
        # 「二適時内野安打、二塁走者が二塁手の悪送球で生還 +2点 ２死一、三塁」型。
        # TextLiveの最終塁状況「一、三塁」が parser 側で一塁だけに縮退する場合、
        # B->1 と既存一塁走者が衝突し、ActualWarnings が残る。
        # raw_text が一三塁を明示し、before一塁走者が未処理なら 1->3 を補完する。
        if (
            1 in before_set
            and "一、三塁" in (play.raw_text or "")
            and any(m.source == "B" and m.target == "1" for m in result)
            and not any(m.source == "1" for m in result)
        ):
            self._add_or_replace(result, "1", "3", "一塁走者三塁進塁補完", "inferred", False, True)
            final_set = set(final_set) | {3}

        # Quality15 RC115 Warning cleanup 2:
        # 「二塁走者が悪送球で生還 +1点 ... １死一、二塁」のように、
        # 得点・失策語を含む行で final_state が一塁だけに縮退することがある。
        # B->1 と既存一塁走者が衝突し、次プレーで「2塁に走者なし」へ連鎖するため、
        # raw_text が一二塁を明示し、before一塁走者が未処理なら 1->2 を補完する。
        if (
            1 in before_set
            and "一、二塁" in (play.raw_text or "")
            and any(m.source == "B" and m.target == "1" for m in result)
            and not any(m.source == "1" for m in result)
        ):
            self._add_or_replace(result, "1", "2", "一塁走者二塁進塁補完", "inferred", False, True)
            final_set = set(final_set) | {2}

        if self._single_batter_to_second_from_final_state(play, before_set):
            self._add_or_replace(result, "B", "2", "打者走者二塁進塁補完（最終塁状況）", "inferred", True, True)

        # final_stateに合わせた進塁補完
        # 打者走者が到達する塁も占有済みとして扱う。
        # 例: 一二塁から二塁打 +1点、最終二塁の場合、二塁は打者走者の塁であり、
        # 一塁走者を同じ二塁へ補完すると重複警告になる。
        occupied_after_by_existing = {int(m.target) for m in result if m.target in {"1", "2", "3"}}
        moved_existing_sources = {
            int(m.source) for m in result
            if m.source in {"1", "2", "3"}
        }
        # RC141: 一三塁から内野安打で得点なし・最終満塁のように、上位走者が
        # 同じ塁に留まるケースでは、その塁を先に占有済みにして下位走者を二塁へ送る。
        if (
            (getattr(play, "runs_scored", 0) or 0) == 0
            and before_set == {1, 3}
            and final_set == {1, 2, 3}
            and any(m.source == "B" and m.target == "1" for m in result)
        ):
            occupied_after_by_existing.update(
                base for base in (before_set & final_set)
                if base not in moved_existing_sources
            )
        if (
            any(m.source in {"1", "2", "3"} and m.target == "OUT" for m in result)
            and any(m.source == "B" and m.target == "1" for m in result)
        ):
            occupied_after_by_existing.update(
                base for base in (before_set & final_set)
                if base not in moved_existing_sources
            )
        for src in ["2", "1"]:
            src_int = int(src)
            if src_int not in before_set:
                continue
            if any(m.source == src for m in result):
                continue

            # before走者がfinalに必要なら高い到達塁へ
            possible_targets = sorted([b for b in final_set if b not in occupied_after_by_existing and b > src_int], reverse=True)
            if possible_targets:
                tgt = possible_targets[0]
                occupied_after_by_existing.add(tgt)
                self._add_or_replace(result, src, str(tgt), f"{src}塁走者進塁補完", "inferred", False, True)

        batter_final_target = self._batter_extra_target_from_final_state(
            play,
            {int(m.target) for m in result if m.source in {"1", "2", "3"} and m.target in {"1", "2", "3"}},
            self._hit_bases(play.raw_text),
            before_set,
            actual_mode=True,
        )
        if batter_final_target is not None:
            self._add_or_replace(result, "B", str(batter_final_target), "打者走者進塁補完（最終塁状況）", "inferred", True, True)

        return result

    def _complete_forced_chain_on_batter_to_first(self, moves: list[Move], before_set: set[int]) -> None:
        """Actual側で、試合終了により最終塁状況が省略された安打の押し上げ進塁を補完する。"""
        if not any(m.source == "B" and m.target == "1" for m in moves):
            return

        first_forced = 1 in before_set and not any(m.source == "1" for m in moves)
        if first_forced:
            self._add_or_replace(moves, "1", "2", "一塁走者安打押し上げ進塁補完", "inferred", False, True)

        second_forced = 2 in before_set and first_forced and not any(m.source == "2" for m in moves)
        if second_forced:
            self._add_or_replace(moves, "2", "3", "二塁走者安打押し上げ進塁補完", "inferred", False, True)


    def _complete_hit_virtual(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        """Virtual Runner用。V3.1 Quality14 Virtual Runner Rule V2。

        優先順位:
          1. Virtual走者と同じ塁に現実走者がいる場合は、現実走者の進塁を採用する。
             ただし、失策・捕逸・暴投等の投手責任外追加進塁は採用しない。
          2. 同じ塁に現実走者がいないVirtual走者だけ、単打+1・二塁打+2・三塁打+3の原則を適用する。
        """
        before_set = before.as_set()
        hit_bases = self._hit_bases(play.raw_text)
        result: list[Move] = []

        # Virtualでも、同一プレー内の明示アウト（例: 二塁走者が本塁封殺）は尊重する。
        for m in moves:
            if m.target == "OUT" and m.source in {"1", "2", "3"}:
                self._add_or_replace(result, m.source, "OUT", m.reason, m.cause_type, m.pitcher_charge, m.virtual_allow)

        # RC178: 「内野安打、打者が封殺」は、Virtualでも打者アウトを復活させない。
        # 一三塁なら一塁走者だけ二塁へ進め、三塁走者はそのまま残す。
        if any(m.source == "B" and m.target == "OUT" for m in moves) and "内野安打" in (play.raw_text or ""):
            if 1 in before_set and 2 in play.final_base_state.as_set():
                self._add_or_replace(result, "1", "2", "一塁走者二塁進塁補完（打者封殺）", "inferred", False, True)
            self._add_or_replace(result, "B", "OUT", "打者封殺", "out", True, True)
            return self._dedupe_sort(result)

        actual_before_state = getattr(play, "actual_before_base_state", None)
        actual_before_set = actual_before_state.as_set() if actual_before_state is not None else set()
        actual_targets = self._infer_actual_hit_targets_for_virtual_rule(play, moves, actual_before_set, hit_bases)

        # Quality15 RC115:
        # Actual Shadow BaseState 由来の既存挙動を大きく変えず、
        # 「無死一二塁から純粋な単打で無死満塁」と明確に読める場合だけ、
        # V2の同塁現実走者同期を明示補完する。
        # これにより後続単打で本来の三塁走者が生還可能になる。
        raw_text_rc115 = str(getattr(play, "raw_text", "") or "")
        final_set_rc115 = set(play.final_base_state.as_set())
        if (
            hit_bases == 1
            and before_set == {1, 2}
            and final_set_rc115 == {1, 2, 3}
            and int(getattr(play, "runs_scored", 0) or 0) == 0
            and not any(k in raw_text_rc115 for k in ["失策", "悪送球", "捕逸", "暴投", "後逸", "落球", "ファンブル", "アウト", "封殺"])
        ):
            self._add_or_replace(result, "2", "3", "2塁走者Virtual満塁同期補完", "inferred", False, True)
            self._add_or_replace(result, "1", "2", "1塁走者Virtual満塁同期補完", "inferred", False, True)
            self._add_or_replace(result, "B", "1", "打者単打", "hit", True, True)
            return self._dedupe_sort(result)

        occupied_after: set[int] = set()
        # Quality15 / RC061:
        # 「単打で二塁走者生還、打者だけが失策で二塁へ」は、失策追加進塁を
        # 打者に限定し、二塁走者の得点は打球によるものとして同期する。
        if (
            hit_bases == 1
            and 2 in before_set
            and self._is_batter_only_error_after_single(str(getattr(play, "raw_text", "") or ""))
            and int(getattr(play, "runs_scored", 0) or 0) >= 1
        ):
            self._add_or_replace(result, "2", "H", "2塁走者Virtual打者失策除外・単打生還", "hit", True, True)

        for src_int in [3, 2, 1]:
            if src_int not in before_set:
                continue
            src = str(src_int)
            if any(m.source == src for m in result):
                continue

            # Quality15: 同じ塁に現実走者がいる場合に加え、走者IDが同じで
            # Actual側では別塁にいる場合も、そのActual塁の打球進塁を採用する。
            # 失策・捕逸・暴投等の追加進塁は actual_targets 作成時点で除外済み。
            runner_actual_base_by_virtual_source = getattr(play, "virtual_runner_actual_base_by_source", {}) or {}
            # 単打は既存GoldData保護のため「同塁現実走者」だけを採用する。
            # Actual別塁の走者ID同期は、現時点ではV2確認済みの
            # 「一塁Virtual走者が、現実では二塁打で生還した二者生還＋打者走塁死」型に限定する。
            raw_text_for_v2 = str(getattr(play, "raw_text", "") or "")
            diff_base_v2_allowed = (
                hit_bases == 2
                and "+2点" in raw_text_for_v2
            )
            actual_ref_base = runner_actual_base_by_virtual_source.get(src_int, src_int) if diff_base_v2_allowed else src_int
            if actual_ref_base in actual_before_set and actual_ref_base in actual_targets:
                tgt = actual_targets[actual_ref_base]
                if tgt == "H":
                    self._add_or_replace(result, src, "H", f"{src_int}塁走者Virtual現実走者ID進塁採用", "hit", True, True)
                    continue
                if tgt in {"1", "2", "3"}:
                    tgt_i = int(tgt)
                    if (
                        src_int == 1
                        and hit_bases == 1
                        and tgt_i == 3
                        and self._is_single_second_scores_first_runner_error_to_third(raw_text_for_v2)
                    ):
                        tgt_i = 2
                        tgt = "2"
                    # Actual側の到達塁をVirtual現在塁から見ても前進になる場合だけ採用。
                    # 後退・同塁不可ならPhoenix原則へフォールバックする。
                    if tgt_i > src_int and tgt_i not in occupied_after:
                        occupied_after.add(tgt_i)
                        self._add_or_replace(result, src, tgt, f"{src_int}塁走者Virtual現実走者ID進塁採用", "inferred", False, True)
                        continue
                    if tgt_i == src_int and src_int not in occupied_after:
                        occupied_after.add(src_int)
                        continue
                # 現実進塁を採用できない場合は、下の原則へフォールバック。

            # 現実同塁走者がいない、または現実進塁を安全に採用できない場合は原則適用。
            if self._can_score_by_hit(src_int, hit_bases):
                self._add_or_replace(result, src, "H", f"{src_int}塁走者Virtual適時打得点(+{hit_bases})", "hit", True, True)
            else:
                tgt = min(3, src_int + hit_bases)
                if tgt > src_int and tgt not in occupied_after:
                    occupied_after.add(tgt)
                    self._add_or_replace(result, src, str(tgt), f"{src_int}塁走者Virtual進塁補完(+{hit_bases})", "inferred", False, True)
                elif src_int not in occupied_after:
                    occupied_after.add(src_int)

        # 打者走者。安打後失策で現実に余分に進んでいても、Virtualでは安打本来の到達塁まで。
        batter_target = "1"
        batter_reason = "打者単打"
        if hit_bases == 2:
            batter_target = "2"
            batter_reason = "打者二塁打"
        elif hit_bases == 3:
            batter_target = "3"
            batter_reason = "打者三塁打"
        elif hit_bases >= 4:
            batter_target = "H"
            batter_reason = "打者本塁打"
        elif self._single_batter_to_second_from_final_state(play, before_set):
            batter_target = "2"
            batter_reason = "打者走者二塁進塁補完（最終塁状況）"

        batter_final_target = self._batter_extra_target_from_final_state(play, occupied_after, hit_bases, before_set)
        if batter_final_target is not None:
            batter_target = str(batter_final_target)
            batter_reason = "打者走者進塁補完（最終塁状況）"

        if batter_target == "H" or int(batter_target) not in occupied_after:
            self._add_or_replace(result, "B", batter_target, batter_reason, "hit", True, True)

        return self._dedupe_sort(result)

    def _batter_extra_target_from_final_state(
        self,
        play: Play,
        occupied_after: set[int],
        hit_bases: int,
        before_set: set[int],
        actual_mode: bool = False,
    ) -> int | None:
        """失策等のない通常安打で、最終塁表示から打者走者の追加進塁を補完する。"""
        text = str(getattr(play, "raw_text", "") or "")
        if not getattr(play, "is_hit", False):
            return None
        if hit_bases >= 4:
            return None
        if any(k in text for k in ["失策", "悪送球", "捕逸", "暴投", "後逸", "落球", "ファンブル", "アウト", "封殺", "走塁死", "盗塁死"]):
            return None
        natural_target = max(1, min(3, int(hit_bases or 1)))
        final_set = set(play.final_base_state.as_set())
        if actual_mode:
            allowed_pattern = (
                int(getattr(play, "runs_scored", 0) or 0) == 0
                and (
                    (hit_bases == 2 and not before_set and final_set == {3})
                    or (hit_bases == 1 and before_set == {2} and final_set == {2, 3})
                    or (hit_bases == 1 and before_set == {1} and final_set == {2, 3} and "中安打" in text)
                )
            )
        else:
            allowed_pattern = (
                (hit_bases == 2 and not before_set and final_set == {3} and int(getattr(play, "runs_scored", 0) or 0) == 0)
                or (
                    hit_bases == 1
                    and int(getattr(play, "runs_scored", 0) or 0) == 1
                    and final_set == {2, 3}
                    and "適時打" in text
                    and "二、三塁" in text
                )
            )
        if not allowed_pattern:
            return None
        candidates = sorted(
            [base for base in final_set if base > natural_target and base not in occupied_after],
            reverse=True,
        )
        if not candidates:
            return None
        return candidates[0]

    def _single_batter_to_second_from_final_state(self, play: Play, before_set: set[int]) -> bool:
        """単打後の最終表示だけが二三塁を示す場合、打者走者の二塁到達を補完する。"""
        text = str(getattr(play, "raw_text", "") or "")
        final_set = set(play.final_base_state.as_set())
        try:
            outs_delta = int(getattr(play, "outs_after", 0) or 0) - int(getattr(play, "outs_before", 0) or 0)
        except Exception:
            outs_delta = 0
        return (
            self._hit_bases(text) == 1
            and before_set == {2}
            and final_set == {2, 3}
            and int(getattr(play, "runs_scored", 0) or 0) == 0
            and outs_delta == 0
            and "二、三塁" in text
            and not any(k in text for k in ["失策", "悪送球", "捕逸", "暴投", "後逸", "落球", "ファンブル", "アウト", "封殺", "走塁死"])
        )

    def _infer_actual_hit_targets_for_virtual_rule(self, play: Play, moves: list[Move], actual_before_set: set[int], hit_bases: int) -> dict[int, str]:
        """Quality14: 現実同塁優先用に、現実走者の同一プレー到達先を推定する。

        MoveGeneratorが明示した走者移動を優先し、不足分はActual側の補完と同じく
        高位走者から得点、残りはfinal_stateへ割り当てる。失策・捕逸・暴投などの
        追加進塁はVirtualでは採用対象外。
        """
        targets: dict[int, str] = {}
        blocked_causes = {"field_error", "passed_ball", "wild_pitch", "interference"}
        blocked_words = ["失策", "悪送球", "捕逸", "暴投", "後逸", "落球", "ファンブル"]

        def safe_move(m: Move) -> bool:
            if str(getattr(m, "cause_type", "")) in blocked_causes:
                return False
            reason = str(getattr(m, "reason", "") or "")
            return not any(w in reason for w in blocked_words)

        for m in moves:
            src = str(getattr(m, "source", ""))
            tgt = str(getattr(m, "target", ""))
            if src in {"1", "2", "3"} and tgt in {"1", "2", "3", "H", "OUT"} and int(src) in actual_before_set and safe_move(m):
                # OUTはすでに上位で明示アウトとして処理するため、ここではH/塁のみを採用対象にする。
                if tgt != "OUT":
                    targets[int(src)] = tgt

        scored_already = sum(1 for t in targets.values() if t == "H")
        scored_needed = max(0, int(getattr(play, "runs_scored", 0) or 0) - scored_already)

        raw_for_error_guard = str(getattr(play, "raw_text", "") or "")
        if self._is_single_upper_runner_scores_first_runner_and_batter_error_advance(raw_for_error_guard):
            score_src = 3 if 3 in actual_before_set else 2 if 2 in actual_before_set else None
            if score_src is not None:
                targets[score_src] = "H"
            return targets

        # Quality15 / RC032:
        # 安打＋悪送球・失策の複合プレーでは、得点数だけから現実走者の生還を
        # Virtualへ同期しない。同期するのは明示Moveのうちsafe_moveを通った打球進塁だけ。
        # ただしRC061の「得点は単打、失策は打者走者の追加進塁だけ」は例外として許可。
        suppress_error_final_state_assignment = (
            any(w in raw_for_error_guard for w in blocked_words)
            and not self._is_batter_only_error_after_single(raw_for_error_guard)
            and not self._is_single_second_scores_first_runner_error_to_third(raw_for_error_guard)
        )
        if suppress_error_final_state_assignment:
            scored_needed = 0

        for src in [3, 2, 1]:
            if scored_needed <= 0:
                break
            if src in actual_before_set and src not in targets:
                targets[src] = "H"
                scored_needed -= 1

        final_set = set(play.final_base_state.as_set())
        occupied = {int(t) for t in targets.values() if t in {"1", "2", "3"}}

        # 打者走者の安打本来到達塁はfinal_state上の占有候補から外す。
        batter_target = None
        if hit_bases == 1:
            batter_target = 1
        elif hit_bases == 2:
            batter_target = 2
        elif hit_bases == 3:
            batter_target = 3
        if batter_target in final_set:
            occupied.add(batter_target)

        # RC216:
        # 「単打、打者が失策で二塁へ、一塁走者が失策で三塁へ」は、
        # Virtualでは打者の失策追加進塁を除外して一塁に置くため、
        # 既存一塁走者も単打分の二塁止まりへ戻す。
        if self._is_single_with_batter_error_to_second_and_first_runner_error_to_third(raw_for_error_guard):
            return targets
        if suppress_error_final_state_assignment:
            return targets

        for src in [3, 2, 1]:
            if src not in actual_before_set or src in targets:
                continue
            candidates = [b for b in sorted(final_set, reverse=True) if b > src and b not in occupied]
            if candidates:
                tgt = candidates[0]
                occupied.add(tgt)
                targets[src] = str(tgt)
            elif src in final_set and src not in occupied:
                occupied.add(src)
                targets[src] = str(src)

        return targets

    def _is_single_with_batter_error_to_second_and_first_runner_error_to_third(self, text: str) -> bool:
        t = str(text or "")
        if not any(k in t for k in ["安打", "適時打", "内野安打", "バントヒット"]):
            return False
        if any(k in t for k in ["二塁打", "三塁打", "本塁打", "ホームラン"]):
            return False
        if "一塁走者" not in t or "三塁へ" not in t:
            return False
        if not any(k in t for k in ["一塁走者が失策の間に三塁へ", "一塁走者が悪送球で三塁へ", "一塁走者が後逸で三塁へ", "一塁走者がファンブルで三塁へ"]):
            return False
        if "打者が" not in t:
            return False
        batter_part = t.split("打者が", 1)[1]
        for other in ["一塁走者", "二塁走者", "三塁走者"]:
            pos = batter_part.find(other)
            if pos != -1:
                batter_part = batter_part[:pos]
                break
        return "二塁へ" in batter_part and any(k in batter_part for k in ["失策", "悪送球", "後逸", "ファンブル", "落球"])



    def _should_apply_virtual_single_actual_pattern(self, play: Play, before_set: set[int], hit_bases: int, moves: list[Move] | None = None) -> bool:
        """V2系限定の単打・現実走塁反映特例。

        単打=+1の原則は維持する。
        ただし、失策・悪送球・後逸・ファンブル等が絡まない純粋な単打で、
        現実の二塁走者が生還していると読める場合だけ、Virtual二塁走者も生還させる。
        一塁走者についても、現実で三塁へ到達している場合だけ三進を許容する。
        """
        text = play.raw_text or ""
        if hit_bases != 1:
            return False
        if 2 not in before_set:
            return False
        if getattr(play, "runs_scored", 0) <= 0:
            return False
        if not any(k in text for k in ["安打", "適時打", "内野安打", "バントヒット"]):
            return False
        if any(k in text for k in ["捕逸", "暴投", "悪送球", "後逸", "ファンブル", "落球"]):
            return False
        if "失策" in text and not self._is_batter_only_error_after_single(text):
            return False
        return self._actual_second_runner_scores_on_hit(play, before_set, moves)

    def _is_batter_only_error_after_single(self, text: str) -> bool:
        """RC061系: 安打で走者が生還し、失策等の影響が打者走者の追加進塁だけの場合。

        例: 「右適時打、打者が捕手の失策で二塁へ」。
        例: 「左適時二塁打、打者が左翼手の悪送球で三塁へ」。
        この失策等は得点走者には影響しないため、現実走塁特例を抑止しない。
        """
        t = text or ""
        error_words = ["失策", "悪送球", "後逸", "ファンブル", "落球"]
        if not any(k in t for k in error_words):
            return False
        if "打者が" not in t:
            return False
        if not any(k in t for k in ["適時打", "安打", "内野安打", "バントヒット", "二塁打", "三塁打", "本塁打", "ホームラン"]):
            return False
        # 得点走者側の失策進塁・生還が明示される場合は対象外。
        # 「打者が右翼手の後逸で生還」は、打者走者だけの追加進塁として扱う。
        for segment in t.replace("。", "、").split("、"):
            if "走者が" in segment and any(k in segment for k in error_words):
                return False
        return True

    def _actual_second_runner_scores_on_hit(self, play: Play, before_set: set[int], moves: list[Move] | None = None) -> bool:
        """現実の二塁走者がその単打で生還したかを、得点数と塁状況から推定する。

        RC071: Actualの三塁走者だけが単打で生還している場合、Virtual二塁走者を
        現実走塁特例で本塁へ送らない。Actual Moveに3->Hがあり2->Hが無い場合は、
        二塁走者生還とは扱わない。
        """
        if moves is not None:
            has_third_score = any(m.source == "3" and m.target == "H" for m in moves)
            has_second_score = any(m.source == "2" and m.target == "H" for m in moves)
            if has_third_score and not has_second_score:
                return False
        runs = getattr(play, "runs_scored", 0) or 0
        return runs > (1 if 3 in before_set else 0)

    def _is_single_second_scores_first_runner_error_to_third(self, text: str) -> bool:
        """単打で二塁走者が生還し、失策等は一塁走者の三進だけに付くケース。"""
        t = str(text or "")
        if not any(k in t for k in ["適時打", "安打", "内野安打", "バントヒット"]):
            return False
        if any(k in t for k in ["二塁打", "三塁打", "本塁打", "ホームラン"]):
            return False
        if "一塁走者" not in t or "三塁へ" not in t:
            return False
        if not any(k in t for k in [
            "一塁走者が中堅手のファンブルで三塁へ",
            "一塁走者がファンブルで三塁へ",
            "一塁走者が悪送球で三塁へ",
            "一塁走者が後逸で三塁へ",
            "一塁走者が失策で三塁へ",
            "一塁走者が失策の間に三塁へ",
        ]):
            return False
        if any(k in t for k in [
            "二塁走者が失策",
            "二塁走者が悪送球",
            "二塁走者が後逸",
            "二塁走者がファンブル",
            "二塁走者が落球",
            "二塁走者が失策の間に生還",
            "二塁走者が悪送球で生還",
            "二塁走者がファンブルで生還",
        ]):
            return False
        return True

    def _is_single_upper_runner_scores_first_runner_and_batter_error_advance(self, text: str) -> bool:
        """単打で上位走者だけが打球生還し、一塁走者・打者は失策追加進塁のケース。"""
        t = str(text or "")
        if not any(k in t for k in ["適時打", "安打", "内野安打", "バントヒット"]):
            return False
        if any(k in t for k in ["二塁打", "三塁打", "本塁打", "ホームラン"]):
            return False
        if not any(k in t for k in ["+2点", "+２点"]):
            return False
        if "一塁走者" not in t or "生還" not in t:
            return False
        if "打者が" not in t or "三塁へ" not in t:
            return False

        error_words = ["失策", "悪送球", "後逸", "ファンブル", "落球"]
        first_part = t.split("一塁走者", 1)[1]
        first_part = first_part.split("二塁走者", 1)[0].split("三塁走者", 1)[0].split("打者が", 1)[0]
        batter_part = t.split("打者が", 1)[1]
        batter_part = batter_part.split("一塁走者", 1)[0].split("二塁走者", 1)[0].split("三塁走者", 1)[0]
        return (
            "生還" in first_part
            and any(k in first_part for k in error_words)
            and "三塁へ" in batter_part
            and any(k in batter_part for k in error_words)
        )

    def _actual_first_runner_target_on_single(self, play: Play, before_set: set[int]) -> int:
        """単打特例時の一塁走者到達塁。

        現実で一塁走者が三塁へ到達していると読める場合だけ三進。
        それ以外はPhoenix原則どおり二進。
        """
        text = play.raw_text or ""
        final_set = play.final_base_state.as_set()
        if 1 in before_set and 3 in final_set and self._actual_second_runner_scores_on_hit(play, before_set):
            return 3
        if "一塁走者が三塁" in text or "一塁走者が三塁へ" in text:
            return 3
        return 2

    def _should_apply_virtual_double_actual_pattern(self, play: Play, before_set: set[int], hit_bases: int, moves: list[Move] | None = None) -> bool:
        """RC092: 二塁打で現実一塁走者が生還した場合のVirtual特例。

        二塁打=+2の原則ではVirtual一塁走者は三塁止まり。
        ただし、現実側が一・二塁で、一塁走者も二塁打で生還していると明確に読める場合は、
        単打の現実走塁特例と同様にVirtual一塁走者の生還を認める。
        失策・悪送球・後逸等が絡む場合は従来どおり除外する。
        """
        text = play.raw_text or ""
        if hit_bases != 2:
            return False
        if 1 not in before_set:
            return False
        if getattr(play, "runs_scored", 0) <= 0:
            return False
        if not any(k in text for k in ["二塁打", "適時二塁打"]):
            return False
        if any(k in text for k in ["捕逸", "暴投", "悪送球", "後逸", "ファンブル", "落球", "失策"]):
            return False
        return self._actual_first_runner_scores_on_double(play, before_set, moves)

    def _actual_first_runner_scores_on_double(self, play: Play, before_set: set[int], moves: list[Move] | None = None) -> bool:
        """現実の一塁走者が二塁打で生還したかをMove優先で判定する。"""
        if moves is not None and any(m.source == "1" and m.target == "H" for m in moves):
            return True
        runs = getattr(play, "runs_scored", 0) or 0
        # 三塁・二塁走者は二塁打原則で生還可能。その人数を超える得点があれば、
        # 一塁走者も生還したと推定する。
        # ただし+1点二塁打で、Actualだけ三塁/二塁まで進んでいた走者が生還したケース
        # （RC020/RC036/RC067）は、この特例対象外。
        naturally_scoring = (1 if 3 in before_set else 0) + (1 if 2 in before_set else 0)
        return runs >= 2 and runs > naturally_scoring

    def _hit_bases(self, text: str) -> int:
        text = text or ""
        if "本塁打" in text or "ホームラン" in text:
            return 4
        if "三塁打" in text:
            return 3
        if "二塁打" in text:
            return 2
        # RC094: 「中二適時打」等は、このフィードでは適時二塁打の省略表記として扱う。
        # 一方、「中二安打」「右二安打」は最終塁状況が一塁で出る既存ケースがあるため対象外。
        if any(k in text for k in ["左二適時打", "中二適時打", "右二適時打", "左中間二適時打", "右中間二適時打"]):
            return 2
        return 1

    def _can_score_by_hit(self, source_base: int, hit_bases: int) -> bool:
        if hit_bases >= 4:
            return True
        return source_base + hit_bases >= 4

    def _complete_by_final_state(self, play: Play, moves: list[Move], before: BaseState) -> list[Move]:
        result = list(moves)
        text = play.raw_text or ""
        before_set = before.as_set()
        final_set = play.final_base_state.as_set()

        # RC022 Warning Zero補強:
        # 一・二塁で「一塁走者が盗塁成功 １死二塁」のように、
        # 先行走者のアウトが省略される表記がある。
        # final_stateとアウト増加から、二塁走者OUT＋一塁走者二塁を補完する。
        if "一塁走者が盗塁成功" in text and 1 in before_set and 2 in before_set:
            if final_set == {2} and getattr(play, "outs_after", 0) > getattr(play, "outs_before", 0):
                self._add_or_replace(result, "2", "OUT", "二塁走者盗塁時アウト補完", "out", False, True)
                self._add_or_replace(result, "1", "2", "一塁走者盗塁成功", "steal", False, True)
                return result

        # RC049 Warning Zero補強:
        # Virtual側で三塁にも走者が残っている状態から、
        # 「一塁走者が二塁へ、二塁走者が三塁へ １死二、三塁」のような
        # 通常ゴロ進塁を処理すると、三塁走者の行き先が省略されているため
        # 2->3 が既存三塁走者と衝突する。得点はなく、アウトが増えているので、
        # 省略された三塁走者は本塁封殺/アウト相当として退避させる。
        if (
            {1, 2, 3} <= before_set
            and "一塁走者が二塁へ" in text
            and "二塁走者が三塁へ" in text
            and "生還" not in text
            and getattr(play, "runs_scored", 0) == 0
            and getattr(play, "outs_after", 0) > getattr(play, "outs_before", 0)
            and {2, 3} <= final_set
        ):
            self._add_or_replace(result, "3", "OUT", "三塁走者本塁封殺補完", "out", False, True)
            return result

        return result

    def _add_or_replace(self, moves: list[Move], src: str, tgt: str, reason: str, cause: str, pitcher_charge: bool, virtual_allow: bool):
        for mv in moves:
            if mv.source == src:
                mv.target = tgt
                mv.reason = reason
                mv.cause_type = cause
                mv.pitcher_charge = pitcher_charge
                mv.virtual_allow = virtual_allow
                mv.explicit = False
                return
        moves.append(Move(src, tgt, reason, cause, pitcher_charge, virtual_allow, explicit=False))

    def _add_if_missing(self, moves: list[Move], src: str, tgt: str, reason: str, cause: str, pitcher_charge: bool, virtual_allow: bool):
        if not any(mv.source == src for mv in moves):
            moves.append(Move(src, tgt, reason, cause, pitcher_charge, virtual_allow, explicit=False))

    def _dedupe_sort(self, moves: list[Move]) -> list[Move]:
        by_src: dict[str, Move] = {}
        for mv in moves:
            by_src[mv.source] = mv
        return sorted(by_src.values(), key=lambda mv: self.ORDER.get(mv.source, 99))
