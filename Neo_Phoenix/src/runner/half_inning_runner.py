from __future__ import annotations

from dataclasses import dataclass, field
import re
from src.parser.play_parser import PlayParser
from src.move.move_generator import MoveGenerator
from src.move.move_completer import MoveCompleter
from src.move.models import BaseState
from src.runner.atomic_runner import AtomicRunner, RunnerState
from src.runner.runner import Runner
from src.judge.earned_run_judge import EarnedRunJudge
from src.game.pitcher_change_parser import PitcherChangeParser
from src.pitcher.pitcher_manager import PitcherManager


@dataclass
class PlayReport:
    seq: int
    raw_text: str
    before_text: str
    after_text: str
    outs_before: int = 0
    outs_after: int = 0
    moves_text: list[str] = field(default_factory=list)
    scored_text: list[str] = field(default_factory=list)
    outs_text: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    runner_history: list[str] = field(default_factory=list)
    pitcher_changes: list[str] = field(default_factory=list)
    pitcher_runtime_debug: list[str] = field(default_factory=list)


@dataclass
class HalfInningReport:
    title: str
    plays: list[PlayReport] = field(default_factory=list)
    total_scores: int = 0
    total_outs: int = 0
    warnings: list[str] = field(default_factory=list)
    # V3.0 Sprint04: 次の同じ守備側半イニングへ投手名を引き継ぐため、
    # 半イニング終了時点の責任投手を保持する。
    current_pitcher: str = ""


class HalfInningRunner:
    """
    Phoenix alpha5.5

    複数プレーを連続処理するActual Runner。

    alpha5.5:
      - 打者アウトをouts_countへ反映
      - scored/outsをプレー単位deltaで表示
    """

    def __init__(self, title: str = "Half Inning"):
        self.title = title
        self.parser = PlayParser()
        self.generator = MoveGenerator()
        self.completer = MoveCompleter()
        self.atomic = AtomicRunner()
        self.state = RunnerState()
        self.report = HalfInningReport(title=title)
        self.judge = EarnedRunJudge()
        self.pitcher_parser = PitcherChangeParser()
        self.pitcher_manager = PitcherManager()

    def run(self, lines: list[str], pitcher: str = "P") -> HalfInningReport:
        initial_pitcher, play_lines = self._extract_initial_pitcher(lines, pitcher)
        self.pitcher_manager.set_initial(initial_pitcher)
        self.pitcher_manager.sync_current_virtual(self.state, seq=0, event="開始", note="初期投手")
        for seq, line in enumerate(play_lines, 1):
            self._run_one(seq, line, self.pitcher_manager.current_pitcher)
        self.report.current_pitcher = self.pitcher_manager.current_pitcher
        return self.report

    def _extract_initial_pitcher(self, lines: list[str], fallback: str = "P") -> tuple[str, list[str]]:
        """半イニング冒頭の「先発は ○○」「マウンド ○○」から初期投手名を取得する。

        TextLiveでは各半イニングの #1 付近に守備側投手が表示されるため、
        投手交代イベントを待たずに先発名をPitcherStateへ登録する。
        取得した行はプレーではないので解析対象から除外する。
        """
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
            self.pitcher_manager.sync_current_virtual(self.state, seq=seq, event="投手交代前", note="交代前状態保存")
            self.pitcher_manager.change(
                seq=seq,
                old_pitcher=pc.old_pitcher,
                new_pitcher=pc.new_pitcher,
                raw_text=pc.raw_text,
                actual_state=self.state,
            )
            self.report.pitcher_changes = [f'{c.seq},{c.old_pitcher},{c.new_pitcher},{c.raw_text}' for c in self.pitcher_manager.changes]
            self.report.pitcher_runtime_debug = self.pitcher_manager.export_runtime_rows()
            # 投手交代行はプレーとして処理せず、Runner責任投手の切替のみ行う
            return

        if self._is_administrative_line(line):
            self.pitcher_manager.sync_current_virtual(self.state, seq=seq, event=self._short_event(line), note="管理行スキップ")
            self.report.pitcher_runtime_debug = self.pitcher_manager.export_runtime_rows()
            return

        if self._is_tiebreak_line(line):
            pitcher = self.pitcher_manager.current_pitcher or pitcher
            before_text = self.state.base_text()
            outs_before = self.state.outs_count
            self._seed_tiebreak_runners(pitcher)
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
            self.report.runner_history = self._build_runner_history()
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

        generated = self.generator.generate(play)
        completed = self.completer.complete(play, generated, before_base_state)

        # V3.1 Quality02:
        # Actual得点は、TextLiveの当該プレー本文に現れた得点数を上限とする。
        # まれに補完ロジックが「いるはずの三塁走者」を作って3->Hを追加し、
        # 実際は2得点の回を3得点として数えることがある。
        # ここでプレー単位の得点Moveを正規化し、現実得点の過大カウントを防ぐ。
        completed = self._remove_undeclared_actual_score_moves(play, completed)
        completed = self._cap_actual_score_moves_to_declared_runs(play, completed)

        # RC031補強:
        # TextLive上は「+2点」なのに、明示される得点が「二塁走者が失策で生還」
        # だけになる表記がある。この場合、もう1点は通常、三塁走者が安打で
        # 生還した得点として先にカウントすべき。内部状態に三塁走者がいないと
        # 得点番号が1点ずれるため、安全弁として不明三塁走者を補完し、3->Hを
        # 追加する。既存のGoldData判定には触れず、得点カウント漏れだけを防ぐ。
        completed = self._ensure_missing_hit_score_runner(play, completed, pitcher)
        # V3.1 Quality03:
        # RC031等の得点不足補完を行った後も、本文の +N点 を上限として再度制限する。
        # これにより、同一プレー内で補完が過剰にH Moveを作っても現実得点数を超えない。
        completed = self._cap_actual_score_moves_to_declared_runs(play, completed)

        # V3.1 Quality08:
        # MoveCompleterだけに任せると、parserのfinal_state縮退や既存補完後の再制限により、
        # 「本文は２死一、三塁なのに、内部Actualは一塁既存走者を残したままB->1」
        # となるケースが残る。AtomicRunnerへ渡す直前に、現在のActual実走者状態と
        # TextLive本文の最終塁表示を突き合わせ、警告発生源そのものを補正する。
        completed = self._repair_actual_moves_before_apply(play, completed)

        self.atomic.apply(self.state, completed, batter_name=play.batter, pitcher=pitcher)

        # 打者アウト加算: Moveでアウトが出ていない通常アウトのみ
        if self._is_batter_out_play(line, completed):
            self.state.outs_count += 1

        after_text = self.state.base_text()
        self.pitcher_manager.sync_current_virtual(self.state, seq=seq, event=self._short_event(line), note="Actual同期")
        scored_delta = self.state.scored[scored_before:]
        outs_delta = self.state.outs[outs_list_before:]

        pr = PlayReport(
            seq=seq,
            raw_text=line,
            before_text=before_text,
            after_text=after_text,
            outs_before=outs_before,
            outs_after=self.state.outs_count,
            moves_text=[f"{m.source}->{m.target} / {m.reason} / {m.cause_type}" for m in completed],
            scored_text=[self._format_scored_runner(r) for r in scored_delta],
            outs_text=[f"{r.id}:{r.name} / reached={r.reached_cause_type} / earned_eligible={r.earned_eligible}" for r in outs_delta],
            warnings=list(self.atomic.warnings),
        )

        self.report.plays.append(pr)
        self.report.total_scores = len(self.state.scored)
        self.report.total_outs = self.state.outs_count
        self.report.warnings.extend(self.atomic.warnings)
        self.report.runner_history = self._build_runner_history()
        self.report.pitcher_changes = [f'{c.seq},{c.old_pitcher},{c.new_pitcher},{c.raw_text}' for c in self.pitcher_manager.changes]
        self.report.pitcher_runtime_debug = self.pitcher_manager.export_runtime_rows()

        if self._is_inning_end_line(line):
            self.state.bases = {1: None, 2: None, 3: None}




    def _repair_actual_moves_before_apply(self, play, completed):
        """V3.1 Quality08: AtomicRunner適用直前のActual Move整合補正。

        目的は表示置換ではなく、Warningsの発生源を消すこと。

        対象例:
          満塁から「二適時内野安打、二塁走者が二塁手の悪送球で生還 +2点 ２死一、三塁」

        TextLiveの本文上は、三塁走者と二塁走者が生還し、
        一塁走者が三塁、打者走者が一塁に残る。
        しかしfinal_state parserが「一、三塁」を一塁だけに縮退すると、
        1->3 が補完されず、B->1適用時に「1塁に既存走者あり」となる。
        その結果、次プレーの三塁走者走塁死も「3塁に走者なし」へ連鎖する。
        """
        text = str(getattr(play, "raw_text", "") or "")
        fixed = list(completed)

        def has_move(src: str) -> bool:
            return any(str(getattr(m, "source", "")) == src for m in fixed)

        def has_move_to(src: str, tgt: str) -> bool:
            return any(str(getattr(m, "source", "")) == src and str(getattr(m, "target", "")) == tgt for m in fixed)

        # 1) 本文に最終「一、三塁」があり、打者が一塁へ入るのに既存一塁走者が未処理なら、
        #    既存一塁走者を三塁へ送る。
        #    final_state parserの結果に依存せず、本文の最終塁表示を優先する。
        final_says_first_third = any(k in text for k in ["一、三塁", "一三塁", "1、3塁", "１、３塁"])
        if (
            final_says_first_third
            and self.state.bases.get(1) is not None
            # 三塁に走者がいる場合でも、同一プレーの 3->H/OUT 等で空くなら補正対象。
            and (self.state.bases.get(3) is None or has_move("3"))
            and has_move_to("B", "1")
            and not has_move("1")
        ):
            from src.move.models import Move
            fixed.append(Move("1", "3", "一塁走者三塁進塁補正（本文最終一、三塁）", "inferred", False, True, explicit=False))

        # Quality15 RC115 Warning cleanup 3:
        # 得点を含む単打で、本文の最終状態が「一、二塁」なのに parser/補完/cap の組合せで
        # 既存一塁走者の 1->2 が落ちることがある。
        # そのまま B->1 を適用すると「1塁に既存走者あり」が出て、次プレーの
        # 二塁走者アウトも「2塁に走者なし」へ連鎖する。
        # AtomicRunner適用直前に、現在の実走者状態と本文最終塁表示を優先して補正する。
        final_says_first_second = any(k in text for k in ["一、二塁", "一二塁", "1、2塁", "１、２塁"])
        if (
            final_says_first_second
            and self.state.bases.get(1) is not None
            and (self.state.bases.get(2) is None or has_move("2"))
            and has_move_to("B", "1")
            and not has_move("1")
        ):
            from src.move.models import Move
            fixed.append(Move("1", "2", "一塁走者二塁進塁補正（本文最終一、二塁）", "inferred", False, True, explicit=False))

        # Quality15 RC115 Warning cleanup 4:
        # 二三塁からの内野安打で、本文最終が「満塁」の場合は、塁上走者が
        # 動かず打者だけが一塁へ入ったケースがある。
        # 従来のfinal_state補完は「二塁走者を三塁へ」と推定していたため、
        # 既存三塁走者と衝突してActual警告が出ていた。
        # 現在三塁が埋まっており、最終満塁かつ得点なしなら、2->3補完を除外する。
        final_says_loaded = any(k in text for k in ["満塁", "一、二、三塁", "一二三塁", "1、2、3塁", "１、２、３塁"])
        if (
            final_says_loaded
            and int(getattr(play, "runs_scored", 0) or 0) == 0
            and self.state.bases.get(1) is None
            and self.state.bases.get(2) is not None
            and self.state.bases.get(3) is not None
            and has_move_to("B", "1")
        ):
            fixed = [
                m for m in fixed
                if not (
                    str(getattr(m, "source", "")) == "2"
                    and str(getattr(m, "target", "")) == "3"
                    and "進塁補完" in str(getattr(m, "reason", ""))
                )
            ]

        return fixed

    def _remove_undeclared_actual_score_moves(self, play, completed):
        """V3.1 Quality02: 得点表示のないプレーでH MoveをActual得点にしない。

        今回の品質改善対象は、現実は2得点止まりなのにPhoenixが
        補完Moveで「3点目」を作る過大カウント。
        まず安全側として、本文に「+N点」も「生還」もないプレーでは
        H Moveを採用しない。+N点がある既存RCの特殊補完は維持する。
        """
        text = str(getattr(play, "raw_text", "") or "")
        if self._declared_runs_in_text(text) > 0:
            return completed
        # 押し出し四死球・打撃妨害は、TextLiveが+1点を省略することがあるため維持。
        if getattr(play, "is_walk", False) or getattr(play, "is_hbp", False) or getattr(play, "is_interference", False):
            return completed
        if not any(str(getattr(m, "target", "")) == "H" for m in completed):
            return completed
        return [m for m in completed if str(getattr(m, "target", "")) != "H"]

    def _cap_actual_score_moves_to_declared_runs(self, play, completed):
        """Actual Runnerの得点Moveをプレー本文の得点数で上限管理する。

        原則として現実得点はTextLive本文の「+N点」または生還表記から確定する。
        MoveCompleter/補完処理が安全弁として3->H等を追加しても、本文上の
        得点数を超えるH Moveは採用しない。

        優先順位:
          1. 本文に明示された得点Move(explicit=True)
          2. 補完Move(explicit=False)

        これにより、実得点2点止まりの半イニングをPhoenixが3点に
        過大カウントする事故を防ぐ。
        """
        text = str(getattr(play, "raw_text", "") or "")
        declared = self._declared_runs_in_text(text)

        h_moves = [m for m in completed if str(getattr(m, "target", "")) == "H"]
        if not h_moves:
            return completed

        if declared <= 0:
            # 押し出し四死球・打撃妨害は、TextLiveが +1点 を省略することがあるため維持。
            if getattr(play, "is_walk", False) or getattr(play, "is_hbp", False) or getattr(play, "is_interference", False):
                return completed
            # 得点表示がないプレーではActual得点を発生させない。
            return [m for m in completed if str(getattr(m, "target", "")) != "H"]

        if len(h_moves) <= declared:
            return completed

        kept_h_ids = set()
        explicit = [m for m in h_moves if bool(getattr(m, "explicit", True))]
        inferred = [m for m in h_moves if not bool(getattr(m, "explicit", True))]
        for m in (explicit + inferred)[:declared]:
            kept_h_ids.add(id(m))

        fixed = []
        for m in completed:
            if str(getattr(m, "target", "")) != "H" or id(m) in kept_h_ids:
                fixed.append(m)
        return fixed

    def _declared_runs_in_text(self, text: str) -> int:
        """TextLive本文からプレー単位の現実得点数を読む。"""
        import re
        s = str(text or "")
        m = re.search(r"\+(\d+)点", s)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return 0

        # +N点がない場合は、生還表記の数を明示得点数として扱う。
        # 同じ走者語を二重に数えない。
        runners = ["三塁走者", "二塁走者", "一塁走者", "打者"]
        count = 0
        for r in runners:
            if r in s and "生還" in self._runner_segment(s, r):
                count += 1
        if count:
            return count

        # 押し出し等で「生還」が省略される表記への保険。
        if any(k in s for k in ["押し出し", "押出し"]) and any(k in s for k in ["四球", "死球", "打撃妨害"]):
            return 1
        return 0

    def _runner_segment(self, text: str, runner_word: str) -> str:
        s = str(text or "")
        start = s.find(runner_word)
        if start < 0:
            return ""
        end = len(s)
        for other in ["一塁走者", "二塁走者", "三塁走者", "打者"]:
            if other == runner_word:
                continue
            p = s.find(other, start + len(runner_word))
            if p != -1:
                end = min(end, p)
        return s[start:end]

    def _ensure_missing_hit_score_runner(self, play, completed, pitcher: str):
        """RC031: +N点の実得点数に対してH Moveが不足する場合の補完。

        対象は安打プレー限定。特に、
          右前適時打、二塁走者が右翼手のファンブルで生還、打者が二塁へ +2点
        のように、二塁走者の失策生還だけがMove化され、
        先行する三塁走者の通常生還が欠けるケースを補完する。
        """
        try:
            runs = int(getattr(play, "runs_scored", 0) or 0)
        except Exception:
            runs = 0
        if runs <= 0 or not getattr(play, "is_hit", False):
            return completed

        h_moves = [m for m in completed if str(getattr(m, "target", "")) == "H"]
        missing = runs - len(h_moves)
        if missing <= 0:
            return completed

        text = str(getattr(play, "raw_text", "") or "")
        # すでに三塁走者がいる場合は通常の補完に任せる。
        # ここでは「本来いるはずの三塁走者が内部状態にいない」ケースだけを扱う。
        if self.state.bases.get(3) is not None:
            return completed
        if not ("二塁走者" in text and "生還" in text and any(w in text for w in ["失策", "悪送球", "後逸", "ファンブル", "落球"])):
            return completed

        # 三塁の不明走者を作成。自責対象の通常進塁走者として扱う。
        # 実在打者走者のR連番をずらすとActual/Virtualの同一走者対応が崩れるため、
        # Ghost専用IDを使い atomic.runner_seq は進めない。
        ghost_id = f"G{getattr(play, 'seq', 0):03d}"
        runner = Runner(
            id=ghost_id,
            name=f"不明走者{ghost_id}",
            responsible_pitcher=pitcher,
            reached_by="得点不足補完",
            reached_cause_type="unknown",
            earned_eligible=True,
            current_base=3,
        )
        runner.history.append("3塁へ: 得点不足補完")
        self.state.runner_registry.append(runner)
        self.state.bases[3] = runner

        from src.move.models import Move
        fixed = list(completed)
        if not any(str(getattr(m, "source", "")) == "3" for m in fixed):
            fixed.append(Move("3", "H", "三塁走者適時打得点補完", "hit", True, True, explicit=False))
        return fixed

    def _current_base_state(self) -> BaseState:
        return BaseState(
            first="unknown" if self.state.bases.get(1) is not None else None,
            second="unknown" if self.state.bases.get(2) is not None else None,
            third="unknown" if self.state.bases.get(3) is not None else None,
        )

    def _is_batter_out_play(self, line: str, completed) -> bool:
        # 走者アウトがあるプレーでは、まずMoveのOUTを優先。
        if any(m.target == "OUT" for m in completed):
            return False

        # 出塁系は打者アウトではない
        if any(m.source == "B" and m.target in {"1", "2", "3"} for m in completed):
            return False

        sacrifice_words = ["送りバント成功", "犠打", "犠牲バント", "スリーバンド失敗"]
        if any(k in line for k in sacrifice_words):
            return True

        out_words = [
            "三振", "空振り三振", "見逃し三振",
            "飛", "邪飛", "直",
            "ゴロ", "併殺",
        ]

        if self._is_inning_end_line(line) and not any(k in line for k in ["安打", "四球", "死球", "失策", "出塁"]):
            return True

        return any(k in line for k in out_words)

    def _build_runner_history(self) -> list[str]:
        rows = []
        for r in self.state.runner_registry:
            status = "得点" if r.scored else "アウト" if r.out else "残塁"
            rows.append(
                f"{r.id},{r.name},{r.responsible_pitcher},{r.reached_cause_type},"
                f"{r.earned_eligible},{status},{r.current_base},{' > '.join(r.history)}"
            )
        return rows

    def _format_scored_runner(self, runner: Runner) -> str:
        result = self.judge.judge_scored_runner(runner)
        score_cause = getattr(runner, "score_cause_type", "")
        score_reason = getattr(runner, "score_reason", "")
        return (
            f"{runner.id}:{runner.name} / reached={runner.reached_cause_type} "
            f"/ earned_eligible={runner.earned_eligible} "
            f"/ score_cause={score_cause} / score_reason={score_reason} "
            f"/ {result.judgment} / {result.reason}"
        )

    def _short_event(self, line: str) -> str:
        from src.event.event_labeler import short_event_label
        return short_event_label(line)
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

    def _seed_tiebreak_runners(self, pitcher: str) -> None:
        for base, name in ((1, "タイブレーク一塁走者"), (2, "タイブレーク二塁走者")):
            if self.state.bases.get(base) is not None:
                continue
            self.atomic.runner_seq += 1
            runner = Runner(
                id=f"R{self.atomic.runner_seq:03d}",
                name=name,
                responsible_pitcher=pitcher,
                reached_by="タイブレーク",
                reached_cause_type="tiebreak",
                earned_eligible=False,
                current_base=base,
            )
            runner.history.append(f"タイブレーク開始: {base}塁")
            self.state.runner_registry.append(runner)
            self.state.bases[base] = runner
