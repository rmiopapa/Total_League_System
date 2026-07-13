from __future__ import annotations

from src.move.models import Move
from src.parser.play import Play


class MoveGenerator:
    """
    Phoenix V2.6 Sprint3.7 ScoreEventDetector

    TextLiveに明示されたMoveだけを生成する。
    不足Moveの補完はMoveCompleterに任せる。

    V2.5.3:
      - 「本塁狙うもアウト」を走者OUTとして認識
      - 「この間で三塁へ」を進塁として認識
      - 「二塁手の落球で二塁へ」等、失策の間の進塁表記ゆれに対応
      - 安打後の悪送球・後逸による打者追加進塁に対応
    """

    def generate(self, play: Play) -> list[Move]:
        text = play.raw_text or ""
        moves: list[Move] = []

        # 走者生還
        # Sprint3.8:
        # 同じプレーに失策が含まれていても、得点走者自身が失策で
        # 生還した場合だけ score_cause=field_error とする。
        if "三塁走者が生還" in text:
            cause = self._score_cause_for_score_move(play, text, "三塁走者")
            moves.append(Move("3", "H", "三塁走者が生還", cause, self._pitcher_charge_for_cause(cause), self._virtual_allow_for_cause(cause)))
        if "二塁走者が生還" in text:
            cause = self._score_cause_for_score_move(play, text, "二塁走者")
            moves.append(Move("2", "H", "二塁走者が生還", cause, self._pitcher_charge_for_cause(cause), self._virtual_allow_for_cause(cause)))
        if "一塁走者が生還" in text:
            cause = self._score_cause_for_score_move(play, text, "一塁走者")
            moves.append(Move("1", "H", "一塁走者が生還", cause, self._pitcher_charge_for_cause(cause), self._virtual_allow_for_cause(cause)))

        # 守備側悪送球・失策により生還した表現
        # Sprint3.8: 「一塁走者が悪送球で二塁へ、三塁走者が生還」等を
        # 一塁走者の生還と誤認しないよう、走者ごとの文節で判定する。
        if self._runner_scores_on_error(text, "三塁走者"):
            self._add_or_replace_move(moves, Move("3", "H", "三塁走者悪送球生還", "field_error", False, False))
        if self._runner_scores_on_error(text, "二塁走者"):
            self._add_or_replace_move(moves, Move("2", "H", "二塁走者悪送球生還", "field_error", False, False))
        if self._runner_scores_on_error(text, "一塁走者"):
            self._add_or_replace_move(moves, Move("1", "H", "一塁走者悪送球生還", "field_error", False, False))

        # 明示進塁・表記ゆれ対応
        if self._runner_advances_to(text, "一塁走者", "二塁"):
            moves.append(Move("1", "2", "一塁走者が二塁へ", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        if self._runner_advances_to(text, "一塁走者", "三塁"):
            moves.append(Move("1", "3", "一塁走者が三塁へ", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        if self._runner_advances_to(text, "二塁走者", "三塁"):
            moves.append(Move("2", "3", "二塁走者が三塁へ", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))

        if "三塁走者が失策の間に生還" in text:
            moves.append(Move("3", "H", "三塁走者失策生還", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        if "二塁走者が失策の間に生還" in text:
            moves.append(Move("2", "H", "二塁走者失策生還", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        if "一塁走者が失策の間に生還" in text:
            moves.append(Move("1", "H", "一塁走者失策生還", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))

        # 封殺
        if "三塁走者が封殺" in text:
            moves.append(Move("3", "OUT", "三塁走者封殺", "out", False, True))
        if "二塁走者が封殺" in text:
            moves.append(Move("2", "OUT", "二塁走者封殺", "out", False, True))
        if "一塁走者が封殺" in text:
            moves.append(Move("1", "OUT", "一塁走者封殺", "out", False, True))

        # 本塁狙うもアウト、アウト表記、牽制死
        if "三塁走者" in text and ("本塁狙うもアウト" in text or "本塁を狙うもアウト" in text or "アウト" in text and "三塁走者が" in text):
            moves.append(Move("3", "OUT", "三塁走者アウト", "out", False, True))
        if "二塁走者" in text and ("本塁狙うもアウト" in text or "本塁を狙うもアウト" in text or "アウト" in text and "二塁走者が" in text):
            moves.append(Move("2", "OUT", "二塁走者アウト", "out", False, True))
        if "一塁走者" in text and ("三塁狙うもアウト" in text or "三塁を狙うもアウト" in text or "アウト" in text and "一塁走者が" in text):
            moves.append(Move("1", "OUT", "一塁走者アウト", "out", False, True))

        if "三塁走者が牽制死" in text:
            moves.append(Move("3", "OUT", "三塁走者牽制死", "out", False, True))
        if "二塁走者が牽制死" in text:
            moves.append(Move("2", "OUT", "二塁走者牽制死", "out", False, True))
        if "一塁走者が牽制死" in text:
            moves.append(Move("1", "OUT", "一塁走者牽制死", "out", False, True))

        # 走塁死・盗塁死・飛び出し死・リタッチアウト
        if "三塁走者が走塁死" in text or "三塁走者が盗塁死" in text or "三塁走者が飛び出し" in text or "三塁走者が戻れずリタッチアウト" in text:
            moves.append(Move("3", "OUT", "三塁走者走塁死", "out", False, True))
        if "二塁走者が走塁死" in text or "二塁走者が盗塁死" in text or "二塁走者が飛び出し" in text or "二塁走者が戻れずリタッチアウト" in text:
            moves.append(Move("2", "OUT", "二塁走者走塁死", "out", False, True))
        if "一塁走者が走塁死" in text or "一塁走者が盗塁死" in text or "一塁走者が飛び出し" in text or "一塁走者が戻れずリタッチアウト" in text:
            moves.append(Move("1", "OUT", "一塁走者走塁死", "out", False, True))

        # 安打後に外野手後逸・悪送球等で打者が追加進塁・生還するケース
        # RC-003: 「中適時三塁打、打者が左翼手の悪送球で生還 +2点」
        # Actualでは打者得点、Virtualでは安打本来の到達塁（三塁打なら三塁）に補正する。
        # RC024: 一塁走者の「後逸で三塁へ」を、打者の三塁進塁と誤認しないよう、
        # 「打者が」以降の文節だけで判定する。
        batter_seg = text[text.find("打者が"):] if "打者が" in text else ""
        if batter_seg:
            cut = len(batter_seg)
            for other in ["一塁走者", "二塁走者", "三塁走者"]:
                p = batter_seg.find(other, len("打者"))
                if p != -1:
                    cut = min(cut, p)
            batter_seg = batter_seg[:cut]
        if play.is_hit and batter_seg and ("後逸で生還" in batter_seg or "悪送球で生還" in batter_seg or "失策で生還" in batter_seg or "失策の間に生還" in batter_seg
                                           or "落球で生還" in batter_seg or "ファンブルで生還" in batter_seg):
            base_label = self._hit_label(text)
            moves.append(Move("B", "H", f"打者{base_label}後失策生還", "field_error", False, False))
        elif play.is_hit and batter_seg and ("後逸で二塁へ" in batter_seg or "悪送球で二塁へ" in batter_seg or "失策で二塁へ" in batter_seg or "失策の間に二塁へ" in batter_seg
                                               or "ファンブルで二塁へ" in batter_seg or "落球で二塁へ" in batter_seg):
            base_label = self._hit_label(text)
            moves.append(Move("B", "2", f"打者{base_label}後失策二塁", "hit", True, True))
        elif play.is_hit and batter_seg and ("後逸で三塁へ" in batter_seg or "悪送球で三塁へ" in batter_seg or "失策で三塁へ" in batter_seg or "失策の間に三塁へ" in batter_seg
                                             or "ファンブルで三塁へ" in batter_seg or "落球で三塁へ" in batter_seg):
            base_label = self._hit_label(text)
            moves.append(Move("B", "3", f"打者{base_label}後失策三塁", "hit", True, True))

        # 打者走者
        dropped_third_cause = self._dropped_third_strike_safe_cause(text)
        if dropped_third_cause:
            # RC023 / RC067 / RC068 Warning Zero補強:
            # 振り逃げ出塁はActualでは打者を一塁に置く。
            # ただし、原因が捕逸(PB)なら投手責任外、暴投(WP)なら投手責任。
            # そのため、PBはVirtualでB->OUT換算、WPはVirtualでもB->1を許可する。
            # 「振逃」「振り逃げ」「三振、捕逸/暴投により出塁」の表記ゆれを吸収する。
            if dropped_third_cause == "wild_pitch":
                moves.append(Move("B", "1", "打者振り逃げ（暴投）", "wild_pitch", True, True))
            else:
                moves.append(Move("B", "1", "打者振り逃げ（捕逸）", "passed_ball", False, False))
        elif self._is_batter_out_after_temporary_safe(text):
            # RC172: 「打者が出塁、封殺」は通常の「その間に打者が出塁」
            # ではなく、最終的に打者走者がアウトになった表記。
            moves.append(Move("B", "OUT", "打者出塁後封殺", "out", True, True))
        elif self._is_batter_safe_on_force_out_without_error(text):
            # RC071 / V3.1 Quality12:
            # 「○塁走者が封殺、その間に打者が出塁」は、文中に
            # 悪送球・失策語があっても打者の「失策出塁」ではない。
            # ただし「その間に打者が出塁、失策の間に二塁へ」のように
            # 打者自身の追加進塁が続く場合、Actualでは到達塁まで置くが、
            # reached_cause は field_error ではなく force/out 系として保持する。
            # これにより後続の暴投等で生還した場合、理由が「失策出塁」ではなく
            # Virtual側の生還可否（Virtual生還不能）で判定される。
            tgt = self._batter_safe_force_out_actual_target(text)
            reason = "その間に打者が出塁" if tgt == "1" else f"その間に打者が出塁（失策追加進塁で{tgt}塁）"
            moves.append(Move("B", tgt, reason, "out", True, True))
        elif getattr(play, "is_interference", False) or "打撃妨害" in text:
            # RC015 Warning Zero補強:
            # 捕手の打撃妨害により出塁した打者をActualでは一塁に置く。
            # 投手責任外なのでVirtual側では打者アウト換算の対象にする。
            moves.append(Move("B", "1", "打者打撃妨害", "interference", False, False))
        elif "打者が封殺" in text:
            # RC077:
            # 「二塁手の悪送球により出塁、打者が封殺（4-3）、その間に一塁走者が二塁へ」
            # のように、文頭に「出塁」「悪送球」があっても、最終的に打者本人が封殺
            # されている場合は打者を一塁に残してはいけない。
            # ここをB->1にすると後続四球で架空の満塁となり、0点の回に押し出し得点を
            # 誤カウントする。
            moves.append(Move("B", "OUT", "打者封殺", "out", True, True))
        elif "打者が走塁死" in text:
            # RC217:
            # 野選・出塁後に打者本人が走塁死した表記。出塁原因に関係なく
            # 打者走者を塁上に残さない。
            moves.append(Move("B", "OUT", "打者走塁死", "out", True, True))
        elif play.is_walk:
            moves.append(Move("B", "1", "打者四球", "walk", True, True))
        elif play.is_hbp:
            moves.append(Move("B", "1", "打者死球", "hbp", True, True))
        elif play.is_error and "打者が出塁、走塁死" in text:
            # RC138: 出塁後に打者本人が走塁死した表記。失策出塁の汎用分岐で
            # B->1に残すと、次打者の出塁時に一塁重複警告が発生する。
            moves.append(Move("B", "OUT", "打者走塁死", "out", True, True))
        elif play.is_error and "出塁" in text and not play.is_hit:
            # Phoenix V2.6 Sprint3.6 / RC-002
            # 例: 「投手の悪送球により出塁、打者が二塁へ ２死二塁」
            # Actualでは打者走者の到達塁まで反映する。
            # Virtualでは virtual_half_inning_runner 側でB->OUTに変換される。
            # RC009補強: 「打者が失策の間に二塁へ」も二塁到達として扱う。
            # RC055補強: 「後逸により出塁、打者が生還」は打者走者の得点として扱う。
            if ("打者が失策の間に生還" in text or "打者が生還" in text
                    or "打者が出塁、失策の間に生還" in text):
                moves.append(Move("B", "H", "打者失策出塁生還", "field_error", False, False))
            elif ("打者が失策の間に三塁へ" in text or "打者が三塁へ" in text
                    or "打者が出塁、失策の間に三塁へ" in text
                    or "打者が出塁、三塁へ" in text
                    or (batter_seg and "三塁へ" in batter_seg and any(k in batter_seg for k in ["悪送球", "失策", "後逸", "落球", "ファンブル"]))):
                # RC060:
                # 「遊撃手のファンブルにより出塁、打者が失策の間に二塁へ、左翼手の悪送球で三塁へ」
                # のように、二塁到達後の追加進塁で主語「打者が」が省略される表記を拾う。
                # 旧仕様では先に「打者が失策の間に二塁へ」に一致し、Actualが二塁止まりとなって、
                # 次プレーの「三塁走者が生還」で警告・得点漏れが発生していた。
                moves.append(Move("B", "3", "打者失策出塁三塁", "field_error", False, False))
            elif ("打者が失策の間に二塁へ" in text or "打者が二塁へ" in text
                    or "打者が出塁、失策の間に二塁へ" in text):
                moves.append(Move("B", "2", "打者失策出塁二塁", "field_error", False, False))
            else:
                moves.append(Move("B", "1", "打者失策出塁", "field_error", False, False))
        elif "その間に打者が二塁へ" in text or "その間に打者が出塁、二塁へ" in text:
            moves.append(Move("B", "2", "その間に打者が二塁へ", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        elif "その間に打者が三塁へ" in text:
            moves.append(Move("B", "3", "その間に打者が三塁へ", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        # RC036 Warning Zero:
        # 「打者が出塁、失策の間に二塁へ」のように、直前の「打者が出塁」を
        # 主語として後続の「失策の間に二塁へ」が省略表記される場合がある。
        # これをB->1で止めると、次プレーの「二塁走者が走塁死」と整合せず
        # 2塁走者なし／1塁既存走者あり警告が出るため、B->2として扱う。
        elif ("打者が出塁、失策の間に三塁へ" in text
              or "打者が出塁、悪送球で三塁へ" in text
              or "打者が出塁、後逸で三塁へ" in text
              or "打者が出塁、捕逸で三塁へ" in text):
            moves.append(Move("B", "3", "打者出塁後三塁", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        elif ("打者が出塁、失策の間に二塁へ" in text
              or "打者が出塁、悪送球で二塁へ" in text
              or "打者が出塁、後逸で二塁へ" in text
              or "打者が出塁、捕逸で二塁へ" in text):
            moves.append(Move("B", "2", "打者出塁後二塁", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        elif "その間に打者が出塁" in text or "打者が出塁" in text:
            moves.append(Move("B", "1", "その間に打者が出塁", self._cause(play), self._pitcher_charge(play), self._virtual_allow(play)))
        elif play.is_hit and not any(m.source == "B" for m in moves):
            bases = self._hit_bases(text)
            # RC019: 本塁打は「4塁到達」ではなく「得点」として扱う。
            # 旧仕様の B->4 は AtomicRunner では得点扱いにならず、
            # 本塁打の打者走者がScoreJudgmentsに出ない原因だった。
            if bases >= 4:
                moves.append(Move("B", "H", "打者本塁打", "hit", True, True))
            else:
                moves.append(Move("B", str(bases), f"打者{bases}塁打" if bases > 1 else "打者単打", "hit", True, True))

        # 盗塁
        # RC145: 四球で押し出された一塁走者が、続けて三塁へ盗塁する表記。
        # Moveは同一走者を1本に正規化するため、状態整合上は1->3に集約する。
        if "一塁走者が盗塁で三塁へ" in text:
            moves.append(Move("1", "3", "一塁走者四球進塁後三塁盗塁", "steal", False, True))
        elif "一塁走者が盗塁成功" in text or "一塁走者が盗塁で二塁へ" in text:
            moves.append(Move("1", "2", "一塁走者盗塁成功", "steal", False, True))
        if "二塁走者が盗塁成功" in text:
            moves.append(Move("2", "3", "二塁走者盗塁成功", "steal", False, True))

        # RC049 Warning/ScoreCount補強:
        # 「一、三塁走者ともにスタートを切って重盗成功 +1点」は、
        # 二塁走者の重盗ではなく三塁走者の本盗＋一塁走者の二盗。
        # 従来の generic 重盗処理(2->3, 1->2)では、Actualで「2塁に走者なし」警告が出て、
        # 三塁走者の得点カウントも落ちていた。
        if "一、三塁走者ともにスタートを切って" in text and "重盗成功" in text:
            moves.append(Move("3", "H", "三塁走者重盗生還", "steal", False, True))
            moves.append(Move("1", "2", "一塁走者重盗成功", "steal", False, True))
        elif "二、三塁走者ともにスタートを切って" in text and "重盗成功" in text and "+1点" in text:
            moves.append(Move("3", "H", "三塁走者重盗生還", "steal", False, True))
            moves.append(Move("2", "3", "二塁走者重盗成功", "steal", False, True))
        elif "一、二塁走者ともにスタートを切って" in text and "重盗成功" in text and "+1点" in text:
            moves.append(Move("2", "H", "二塁走者重盗生還", "steal", False, True))
            moves.append(Move("1", "3", "一塁走者重盗三塁到達", "steal", False, True))
        elif "重盗成功" in text or "一、二塁走者ともにスタートを切って" in text:
            moves.append(Move("2", "3", "二塁走者重盗成功", "steal", False, True))
            moves.append(Move("1", "2", "一塁走者重盗成功", "steal", False, True))

        moves = self._phoenix_normalize_explicit_runner_advances(moves, text, play)
        return self._sort(moves)


    def _is_batter_safe_on_force_out_without_error(self, text: str) -> bool:
        """RC071: 封殺の間に打者が一塁へ残る出塁を、後続失策語から分離する。

        満塁等で「三塁走者が封殺（1-2）、その間に打者が出塁」とある場合、
        打者走者の出塁は失策ではない。後続の「一塁走者が失策の間に…」や
        「二塁走者が捕手の悪送球で…」に引っ張られて field_error にしない。

        ただし「その間に打者が出塁、失策の間に二塁/三塁へ」のように
        打者自身の追加進塁が明示される場合は、既存の到達塁補完ロジックへ委ねる。
        """
        text = str(text or "")
        if "その間に打者が出塁" not in text:
            return False
        if not any(k in text for k in ["三塁走者が封殺", "二塁走者が封殺", "一塁走者が封殺"]):
            return False
        return True

    def _is_batter_out_after_temporary_safe(self, text: str) -> bool:
        """TextLiveの「打者が出塁、封殺」を打者走者アウトとして扱う。"""
        return "打者が出塁、封殺" in str(text or "")

    def _batter_safe_force_out_actual_target(self, text: str) -> str:
        """封殺崩れで出塁した打者走者のActual到達塁を返す。

        「その間に打者が出塁、失策の間に二塁へ」は、出塁原因は
        失策ではなく封殺崩れ。ただしActual上は二塁へ置く必要がある。
        後続の「一塁走者が失策の間に…」等を誤読しないよう、
        打者文節だけを見る。
        """
        text = str(text or "")
        idx = text.find("その間に打者が出塁")
        if idx < 0:
            return "1"
        tail = text[idx:]
        cut = len(tail)
        for other in ["一塁走者", "二塁走者", "三塁走者"]:
            pos = tail.find(other, len("その間に打者が出塁"))
            if pos != -1:
                cut = min(cut, pos)
        batter_tail = tail[:cut]
        if any(k in batter_tail for k in ["生還", "本塁へ"]):
            return "H"
        if "三塁へ" in batter_tail:
            return "3"
        if "二塁へ" in batter_tail:
            return "2"
        return "1"

    def _is_dropped_third_strike_safe(self, text: str) -> bool:
        """RC067互換: 振り逃げ出塁を検出する。"""
        return self._dropped_third_strike_safe_cause(text) is not None

    def _dropped_third_strike_safe_cause(self, text: str) -> str | None:
        """RC067/RC068: 振り逃げ出塁の原因をPB/WPで分離する。

        PB(捕逸)による振り逃げは投手責任外なのでVirtualでは三振アウト換算。
        WP(暴投)による振り逃げは投手責任なのでVirtualでも出塁を残す。
        原因語が省略された「振逃」系は、従来互換として捕逸扱いにする。
        """
        text = str(text or "")
        if any(k in text for k in ["振逃チェンジ", "振り逃げチェンジ", "振り逃チェンジ"]):
            return None
        has_phrase = any(k in text for k in ["振逃", "振り逃げ", "振り逃"])
        has_descriptive = ("三振" in text and "出塁" in text and ("捕逸" in text or "暴投" in text))
        if not (has_phrase or has_descriptive):
            return None

        # 打者出塁に関係する文節を優先して原因を読む。
        batter_seg = text
        for key in ["打者", "振逃", "振り逃げ", "振り逃", "三振"]:
            if key in text:
                batter_seg = text[text.find(key):]
                break
        # 後続走者文節にある別原因へ引っ張られないよう粗く切る。
        for other in ["一塁走者", "二塁走者", "三塁走者"]:
            pos = batter_seg.find(other)
            if pos != -1:
                batter_seg = batter_seg[:pos]

        if "暴投" in batter_seg or ("暴投" in text and "捕逸" not in batter_seg):
            return "wild_pitch"
        if "捕逸" in batter_seg or "捕逸" in text:
            return "passed_ball"
        return "passed_ball"

    def _runner_advances_to(self, text: str, runner_word: str, base_word: str) -> bool:
        """
        Phoenix V2.6 Sprint4.7 / RC006

        走者ごとの明示進塁を、文全体ではなく「その走者の文節」だけで判定する。

        旧仕様では、
          一塁走者が失策の間に二塁へ、二塁走者が失策の間に三塁へ
        のような文で、
          runner_word=一塁走者 / base_word=三塁
        でも、文全体に「三塁へ」があるため True になり、
        1->3 を誤生成していた。

        正しくは、
          一塁走者の文節には「二塁へ」だけ
          二塁走者の文節には「三塁へ」だけ
        を認識する。
        """
        if runner_word not in text:
            return False

        # 「盗塁成功」は下の盗塁処理に任せる。
        if "盗塁成功" in text:
            return False

        idx = text.find(runner_word)
        tail = text[idx:]

        # RC015:
        # 「一塁走者が二塁へ、三塁へ」のように、同一走者の連続進塁が
        # 読点で続く場合がある。読点で区切ると 1->2 で止まり、次プレーの
        # 「三塁走者が生還」を取りこぼすため、境界は次の走者文節までにする。
        boundaries = []
        for other in ["一塁走者", "二塁走者", "三塁走者", "打者"]:
            if other == runner_word:
                continue
            p = tail.find(other, len(runner_word))
            if p != -1:
                boundaries.append(p)

        end = min(boundaries) if boundaries else len(tail)
        segment = tail[:end]
        return f"{base_word}へ" in segment


    def _phoenix_normalize_explicit_runner_advances(self, moves: list[Move], text: str, play: Play) -> list[Move]:
        """
        Phoenix V2.6 Sprint4.6 / RC-006 Warning Zero

        明示された走者進塁を、文章内の「走者ごとの到達塁」で固定する。

        目的:
          - 「一塁走者が失策の間に二塁へ、二塁走者が失策の間に三塁へ」
            のような文で、一塁走者を 1->3 と誤認しない。
          - 満塁・一二塁など複数走者同時進塁時の
            「3塁に既存走者あり」警告を防止する。

        方針:
          - runner_word と target_word を近接範囲で判定する。
          - sourceごとに最終Moveを1つだけ持つ。
          - 自責点判定・Virtual判定には触れない。
        """
        fixed = list(moves)

        def remove_source(src: str) -> None:
            fixed[:] = [mv for mv in fixed if str(getattr(mv, "source", "")) != src]

        def add(src: str, tgt: str, reason: str, cause: str = "unknown", pitcher_charge: bool = False, virtual_allow: bool = True) -> None:
            fixed.append(Move(src, tgt, reason, cause, pitcher_charge, virtual_allow))

        def phrase_exists(runner_word: str, target_word: str) -> bool:
            """
            「一塁走者が失策の間に二塁へ」のように、
            runner_word と target_word の間に修飾語が入る表記を拾う。
            ただし文全体の別走者の target_word に引っ張られないよう、
            runner_word 以降の短い範囲だけを見る。
            """
            idx = text.find(runner_word)
            if idx < 0:
                return False
            # RC015:
            # 「一塁走者が二塁へ、三塁へ」のような同一走者の連続進塁を拾うため、
            # 読点や空白では切らず、次の走者文節または打者文節までを見る。
            tail = text[idx:]
            cut = len(tail)
            for other in ["一塁走者", "二塁走者", "三塁走者", "打者"]:
                if other == runner_word:
                    continue
                p = tail.find(other, len(runner_word))
                if p != -1:
                    cut = min(cut, p)
            segment = tail[:cut]
            return target_word in segment

        cause = "field_error" if "失策" in text or "悪送球" in text or "後逸" in text or "落球" in text or "ファンブル" in text else "unknown"
        pitcher_charge = False if cause == "field_error" else False
        virtual_allow = False if cause == "field_error" else True

        grouped_wp_pb = (
            any(k in text for k in ["一、二塁走者", "一・二塁走者"])
            and "進む" in text
            and ("暴投" in text or "捕逸" in text)
        )
        if grouped_wp_pb:
            grouped_cause = "wild_pitch" if "暴投" in text else "passed_ball"
            grouped_reason = "暴投" if grouped_cause == "wild_pitch" else "捕逸"
            remove_source("2")
            remove_source("1")
            add("2", "3", f"二塁走者{grouped_reason}進塁", grouped_cause, grouped_cause == "wild_pitch", grouped_cause == "wild_pitch")
            add("1", "2", f"一塁走者{grouped_reason}進塁", grouped_cause, grouped_cause == "wild_pitch", grouped_cause == "wild_pitch")
            return fixed

        # 失策・悪送球等で生還した走者は、途中の「二塁へ」「三塁へ」で上書きしない。
        # RC003: 「一塁走者が盗塁で二塁へ、捕手の悪送球で生還」は 1->H が正しい。
        scored_by_error = {
            "1": self._runner_scores_on_error(text, "一塁走者"),
            "2": self._runner_scores_on_error(text, "二塁走者"),
            "3": self._runner_scores_on_error(text, "三塁走者"),
        }
        runner_out = {
            "1": phrase_exists("一塁走者", "アウト"),
            "2": phrase_exists("二塁走者", "アウト"),
            "3": phrase_exists("三塁走者", "アウト"),
        }

        if runner_out["1"]:
            remove_source("1")
            add("1", "OUT", "一塁走者アウト", "out", False, True)
        elif scored_by_error["1"]:
            remove_source("1")
            add("1", "H", "一塁走者悪送球生還", "field_error", False, False)
        # 「一塁走者が二塁へ、三塁へ、生還」のように、中間進塁と生還が
        # 同一文節に連続する場合は最終到達点の本塁を優先する。
        elif phrase_exists("一塁走者", "生還"):
            remove_source("1")
            score_cause = self._score_cause_for_score_move(play, text, "一塁走者")
            add("1", "H", "一塁走者が生還", score_cause, self._pitcher_charge_for_cause(score_cause), self._virtual_allow_for_cause(score_cause))
        # RC015: 「一塁走者が二塁へ、三塁へ」は最終到達塁の三塁を優先する。
        elif phrase_exists("一塁走者", "三塁へ"):
            remove_source("1")
            add("1", "3", "一塁走者が三塁へ", cause, pitcher_charge, virtual_allow)
        elif phrase_exists("一塁走者", "二塁へ"):
            remove_source("1")
            add("1", "2", "一塁走者が二塁へ", cause, pitcher_charge, virtual_allow)

        if runner_out["2"]:
            remove_source("2")
            add("2", "OUT", "二塁走者アウト", "out", False, True)
        elif scored_by_error["2"]:
            remove_source("2")
            add("2", "H", "二塁走者悪送球生還", "field_error", False, False)
        # RC034:
        # 「二塁走者が三塁へ、生還」のように、同一文節内に中間進塁と生還が
        # 連続して出る場合は、最終到達点である本塁を優先する。
        # 旧順序では「三塁へ」を先に拾って 2->3 で固定され、+2点のうち
        # 二塁走者の生還が得点カウントから漏れていた。
        elif phrase_exists("二塁走者", "生還"):
            remove_source("2")
            score_cause = self._score_cause_for_score_move(play, text, "二塁走者")
            add("2", "H", "二塁走者が生還", score_cause, self._pitcher_charge_for_cause(score_cause), self._virtual_allow_for_cause(score_cause))
        elif phrase_exists("二塁走者", "三塁へ"):
            remove_source("2")
            add("2", "3", "二塁走者が三塁へ", cause, pitcher_charge, virtual_allow)

        if runner_out["3"]:
            remove_source("3")
            add("3", "OUT", "三塁走者アウト", "out", False, True)
        elif scored_by_error["3"]:
            remove_source("3")
            add("3", "H", "三塁走者悪送球生還", "field_error", False, False)
        elif phrase_exists("三塁走者", "生還"):
            remove_source("3")
            score_cause = self._score_cause_for_score_move(play, text, "三塁走者")
            add("3", "H", "三塁走者が生還", score_cause, self._pitcher_charge_for_cause(score_cause), self._virtual_allow_for_cause(score_cause))

        return fixed


    def _runner_scores_on_error(self, text: str, runner_word: str) -> bool:
        """
        Phoenix V2.6 Sprint4.8.1 / RC003-006

        走者が失策・悪送球・後逸等を契機に生還したかを、
        「その走者の文節」だけで判定する。

        例:
          一塁走者が盗塁で二塁へ、捕手の悪送球で生還
        は、一塁走者の生還として 1->H を生成する。
        """
        if runner_word not in text:
            return False
        idx = text.find(runner_word)
        tail = text[idx:]

        # 次の別走者の開始までは同一走者の説明として扱う。
        boundaries = []
        for other in ["一塁走者", "二塁走者", "三塁走者", "打者"]:
            if other == runner_word:
                continue
            p = tail.find(other, len(runner_word))
            if p != -1:
                boundaries.append(p)
        end = min(boundaries) if boundaries else len(tail)
        segment = tail[:end]

        error_words = ["失策", "悪送球", "後逸", "落球", "ファンブル"]
        return "生還" in segment and any(w in segment for w in error_words)

    def _add_or_replace_move(self, moves: list[Move], new_move: Move) -> None:
        """同一sourceのMoveを差し替える。ただし得点Move(H)は優先する。"""
        for i, mv in enumerate(moves):
            if mv.source == new_move.source:
                if new_move.target == "H" or mv.target != "H":
                    moves[i] = new_move
                return
        moves.append(new_move)

    def _score_cause_for_score_move(self, play: Play, text: str, runner_word: str) -> str:
        # RC057:
        # 同一プレー内に暴投と捕逸が混在する場合、Play全体の is_wild_pitch が
        # 優先されると「三塁走者が捕逸で生還」を暴投生還として誤判定する。
        # 得点原因は走者文節単位で判定する。
        segment = self._runner_segment(text, runner_word)
        if "生還" in segment and "盗塁" in segment:
            return "steal"
        if "生還" in segment and "捕逸" in segment:
            return "passed_ball"
        if "生還" in segment and "暴投" in segment:
            return "wild_pitch"

        # RC039:
        # 「中犠飛、二塁走者が中堅手の悪送球で三塁へ、三塁走者が生還」
        # のように、同一プレー内に悪送球が含まれていても、悪送球の影響を
        # 受けたのが二塁走者の追加進塁だけで、三塁走者の生還自体は犠飛に
        # よる場合がある。
        # Play全体の is_error だけで三塁走者の score_cause を field_error にすると、
        # 犠飛得点を非自責・Virtual除外に誤判定するため、走者文節単位で見る。
        if self._runner_scores_on_error(text, runner_word):
            return "field_error"

        # 犠飛得点の基本処理。
        # ただし同一文内に失策語がある場合は、RC002等の既存GoldData保護のため
        # 原則としてfield_error扱いを維持する。
        # 例外はRC039型：
        #   中犠飛、二塁走者が中堅手の悪送球で三塁へ、三塁走者が生還
        # この場合、悪送球の影響は二塁走者の三進だけで、三塁走者の生還は犠飛。
        if ("犠飛" in text or "犠牲フライ" in text) and "生還" in self._runner_segment(text, runner_word):
            has_error_word = any(w in text for w in ["失策", "悪送球", "後逸", "落球", "ファンブル"])
            rc039_style = (
                runner_word == "三塁走者"
                and "二塁走者" in text
                and "二塁走者" in text[:text.find("三塁走者")]
                and "三塁へ" in text[text.find("二塁走者"):text.find("三塁走者")]
                and any(w in text[text.find("二塁走者"):text.find("三塁走者")] for w in ["失策", "悪送球", "後逸", "落球", "ファンブル"])
            )
            if (not has_error_word) or rc039_style:
                return "hit"
            return "field_error"
        return self._cause(play)

    def _runner_segment(self, text: str, runner_word: str) -> str:
        if runner_word not in text:
            return ""
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
        return tail[:end]

    def _pitcher_charge_for_cause(self, cause: str) -> bool:
        return cause in {"hit", "walk", "hbp", "wild_pitch", "steal"}

    def _virtual_allow_for_cause(self, cause: str) -> bool:
        return cause not in {"field_error", "passed_ball"}

    def _hit_bases(self, text: str) -> int:
        text = text or ""
        if "本塁打" in text or "ホームラン" in text:
            return 4
        if "三塁打" in text:
            return 3
        if "二塁打" in text:
            return 2
        # RC094:
        # OmyuTech/TextLive sometimes abbreviates a timely double as
        # 「中二適時打」「右二適時打」「左二適時打」 rather than 「適時二塁打」.
        # Do not treat 「中二安打」「右二安打」 as a double: those lines commonly end
        # with final base state 一塁 and mean a single to the middle/right side in this feed.
        if any(k in text for k in ["左二適時打", "中二適時打", "右二適時打", "左中間二適時打", "右中間二適時打"]):
            return 2
        return 1

    def _hit_label(self, text: str) -> str:
        bases = self._hit_bases(text)
        return {1: "単打", 2: "二塁打", 3: "三塁打", 4: "本塁打"}.get(bases, "安打")

    def _cause(self, play: Play) -> str:
        if play.is_wild_pitch:
            return "wild_pitch"
        if play.is_passed_ball:
            return "passed_ball"
        if play.is_error:
            return "field_error"
        if play.is_hit:
            return "hit"
        return "unknown"

    def _pitcher_charge(self, play: Play) -> bool:
        return self._cause(play) in {"hit", "walk", "hbp", "wild_pitch"}

    def _virtual_allow(self, play: Play) -> bool:
        return self._cause(play) not in {"field_error", "passed_ball"}

    def _sort(self, moves: list[Move]) -> list[Move]:
        # 同一sourceは原則後勝ち。
        # ただし、同一走者に「中間進塁」と「生還」が同時に出た場合は、
        # 得点イベントを取りこぼさないため H を最優先する。
        order = {"3": 0, "2": 1, "1": 2, "B": 3}
        target_priority = {"H": 0, "OUT": 1, "3": 2, "2": 3, "1": 4}
        by_src: dict[str, Move] = {}
        for mv in moves:
            prev = by_src.get(mv.source)
            if prev is None:
                by_src[mv.source] = mv
                continue
            if target_priority.get(str(mv.target), 99) <= target_priority.get(str(prev.target), 99):
                by_src[mv.source] = mv
        return sorted(by_src.values(), key=lambda mv: order.get(mv.source, 99))
