from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.pitcher.pitcher_state import PitcherState


@dataclass
class PitcherChangeLog:
    seq: int
    old_pitcher: str
    new_pitcher: str
    raw_text: str


@dataclass
class PitcherRuntimeRow:
    seq: int
    event: str
    current_pitcher: str
    pitcher_virtual: str
    virtual_outs: int
    responsible_runner_count: int
    inherited_runner_count: int
    all_pitcher_virtuals: str = ""
    note: str = ""


@dataclass
class PitcherManager:
    """Phoenix V3.0 Sprint01 Foundation.

    既存の責任投手管理を維持しつつ、投手別PitcherStateを保持する。

    Sprint01の重要方針:
      - EarnedRunJudgeには接続しない
      - 判定結果はV2.6と同一
      - PitcherStateはDebug/Runtime可視化のために同期するだけ
    """

    current_pitcher: str = "P"
    changes: list[PitcherChangeLog] = field(default_factory=list)
    pitchers: dict[str, PitcherState] = field(default_factory=dict)
    runtime_rows: list[PitcherRuntimeRow] = field(default_factory=list)

    def set_initial(self, pitcher: str):
        if pitcher:
            self.current_pitcher = pitcher
        self.ensure_pitcher(self.current_pitcher)

    def ensure_pitcher(self, pitcher: str) -> PitcherState:
        key = pitcher or self.current_pitcher or "P"
        if key not in self.pitchers:
            self.pitchers[key] = PitcherState(pitcher_id=key, name=key)
        return self.pitchers[key]

    def _is_placeholder_pitcher(self, pitcher: str) -> bool:
        return str(pitcher or "").strip() in {"", "P"}

    def _rename_pitcher_key(self, old_key: str, new_key: str) -> None:
        """初期プレースホルダー P を、最初の投手交代で判明した実投手名へ置換する。

        試合開始時点では先発投手名がまだ分からないことがあるため、
        Runner/Virtual は暫定的に P で進む。最初の投手交代で
        「旧投手名」が判明したら、P の PitcherState を実名キーへ移す。
        これによりDebugTraceで先発投手が交代前から実名表示される。
        """
        old_key = str(old_key or "").strip()
        new_key = str(new_key or "").strip()
        if not old_key or not new_key or old_key == new_key:
            return
        if old_key not in self.pitchers:
            return
        state = self.pitchers.pop(old_key)
        state.pitcher_id = new_key
        state.name = new_key
        state.history.append(f"Pitcher placeholder renamed: {old_key} -> {new_key}")
        if new_key in self.pitchers:
            # 念のため既存実名Stateがあれば、現在状態を優先して統合する。
            existing = self.pitchers[new_key]
            existing.virtual_bases = state.virtual_bases
            existing.virtual_outs = state.virtual_outs
            existing.responsible_runners.update(state.responsible_runners)
            existing.inherited_runners.update(state.inherited_runners)
            existing.history.extend(state.history)
        else:
            self.pitchers[new_key] = state

        # 既存Runtime行の P 表示も実名に寄せる。
        for row in self.runtime_rows:
            if row.current_pitcher == old_key:
                row.current_pitcher = new_key
            row.all_pitcher_virtuals = row.all_pitcher_virtuals.replace(f"*{old_key}=", f"*{new_key}=").replace(f"{old_key}=", f"{new_key}=")

    def get_current_state(self) -> PitcherState:
        return self.ensure_pitcher(self.current_pitcher)

    def change(
        self,
        seq: int,
        new_pitcher: str,
        old_pitcher: str = "",
        raw_text: str = "",
        team_virtual_state: Any | None = None,
        actual_state: Any | None = None,
    ):
        old_pitcher = str(old_pitcher or "").strip()
        new_pitcher = str(new_pitcher or "").strip()

        # Sprint03 fix:
        # 先発投手は初期状態では P として動くが、最初の投手交代で
        # raw text の旧投手名が判明する。ここで P を実名へリネームし、
        # 交代前のPitcherVirtual列も実名表示にする。
        if old_pitcher and not self._is_placeholder_pitcher(old_pitcher) and self._is_placeholder_pitcher(self.current_pitcher):
            self._rename_pitcher_key(self.current_pitcher, old_pitcher)
            self.current_pitcher = old_pitcher

        old = old_pitcher or self.current_pitcher
        old_state = self.ensure_pitcher(old)
        self.current_pitcher = new_pitcher or self.current_pitcher
        new_state = self.ensure_pitcher(self.current_pitcher)

        # Sprint02: 投手交代時点のTeam Virtualを新投手の初期PitcherVirtualへコピーする。
        # old_stateが直前同期済みなら同値だが、明示的にTeamVirtualを入口にすることで
        # Sprint03以降の9.16(e)接続点を固定する。
        entry_state = actual_state if actual_state is not None else team_virtual_state
        if entry_state is not None:
            new_state.copy_virtual_from_runner_state(entry_state)
            source = "Actual" if actual_state is not None else "TeamVirtual"
            new_state.history.append(f"Virtual copied from {source} at seq {seq}")
        else:
            new_state.copy_virtual_from_pitcher(old_state)

        self.changes.append(PitcherChangeLog(seq=seq, old_pitcher=old, new_pitcher=self.current_pitcher, raw_text=raw_text))
        self.runtime_rows.append(PitcherRuntimeRow(
            seq=seq,
            event="投手交代",
            current_pitcher=self.current_pitcher,
            pitcher_virtual=new_state.virtual_text(),
            virtual_outs=new_state.virtual_outs,
            responsible_runner_count=len(new_state.responsible_runners),
            inherited_runner_count=len(new_state.inherited_runners),
            all_pitcher_virtuals=self.all_pitcher_virtuals_text(),
            note="責任投手更新 / PitcherVirtual初期化",
        ))

    def assign_to_new_runner(self) -> str:
        return self.current_pitcher

    def sync_current_virtual(self, state: Any, seq: int = 0, event: str = "", note: str = "") -> None:
        ps = self.get_current_state()
        ps.copy_virtual_from_runner_state(state)
        self.runtime_rows.append(PitcherRuntimeRow(
            seq=seq,
            event=event,
            current_pitcher=self.current_pitcher,
            pitcher_virtual=ps.virtual_text(),
            virtual_outs=ps.virtual_outs,
            responsible_runner_count=len(ps.responsible_runners),
            inherited_runner_count=len(ps.inherited_runners),
            all_pitcher_virtuals=self.all_pitcher_virtuals_text(),
            note=note,
        ))

    def all_pitcher_virtuals_text(self) -> str:
        """投手別PitcherVirtualを一覧表示する。例: P1=1死二塁 | P2=無死一塁"""
        parts = []
        for pitcher_id in sorted(self.pitchers.keys()):
            st = self.pitchers[pitcher_id]
            marker = "*" if pitcher_id == self.current_pitcher else ""
            parts.append(f"{marker}{pitcher_id}={st.virtual_text()}")
        return " | ".join(parts)

    def export_runtime_rows(self) -> list[str]:
        rows = []
        for r in self.runtime_rows:
            rows.append(
                f"{r.seq},{r.event},{r.current_pitcher},{r.pitcher_virtual},{r.virtual_outs},"
                f"{r.responsible_runner_count},{r.inherited_runner_count},{r.all_pitcher_virtuals},{r.note}"
            )
        return rows
