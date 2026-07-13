from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class EventRule:
    label: str
    matcher: Callable[[str], bool]


def has_any(*words: str) -> Callable[[str], bool]:
    return lambda text: any(w in text for w in words)


def has_all(*words: str) -> Callable[[str], bool]:
    return lambda text: all(w in text for w in words)


def _retouch_out(text: str) -> bool:
    return "リタッチ" in text or "タッチアップ戻れず" in text or ("戻れず" in text and "アウト" in text)


def _steal(text: str) -> bool:
    return "盗塁" in text and not any(w in text for w in ["失敗", "盗塁死", "アウト"])


def _caught_stealing(text: str) -> bool:
    return "盗塁" in text and any(w in text for w in ["失敗", "盗塁死", "アウト"])


def _double_steal(text: str) -> bool:
    return "重盗" in text and not any(w in text for w in ["失敗", "盗塁死", "アウト"])


def _double_caught_stealing(text: str) -> bool:
    return "重盗" in text and any(w in text for w in ["失敗", "盗塁死", "アウト"])


def _pickoff_out(text: str) -> bool:
    return ("けん制" in text or "牽制" in text) and ("アウト" in text or "刺" in text)


def _pickoff(text: str) -> bool:
    return ("けん制" in text or "牽制" in text) and not _pickoff_out(text)


def _dropped_third_strike(text: str) -> bool:
    return (
        any(k in text for k in ["振逃", "振り逃げ", "振り逃"])
        or ("三振" in text and "出塁" in text and any(k in text for k in ["捕逸", "暴投", "ワイルドピッチ", "パスボール"]))
    )


def _single(text: str) -> bool:
    return any(k in text for k in ["安打", "適時打", "内野安打", "バントヒット"])


def _single_label(text: str) -> str:
    if "左" in text:
        return "左前安打"
    if "中" in text:
        return "中前安打"
    if "右" in text:
        return "右前安打"
    return "安打"


EVENT_RULES: tuple[EventRule, ...] = (
    EventRule("投手交代", lambda t: "投手交代" in t or ("ピッチャー" in t and "交代" in t)),
    EventRule("守備妨害", has_any("守備妨害", "守備を妨害")),
    EventRule("打撃妨害", has_any("打撃妨害", "打撃を妨害")),
    EventRule("走塁妨害", has_any("走塁妨害", "走塁を妨害")),
    EventRule("リタッチアウト", _retouch_out),
    EventRule("走塁死", has_any("走塁死")),
    EventRule("重盗死", _double_caught_stealing),
    EventRule("重盗", _double_steal),
    EventRule("盗塁死", _caught_stealing),
    EventRule("盗塁", _steal),
    EventRule("牽制死", _pickoff_out),
    EventRule("牽制", _pickoff),
    EventRule("ボーク", has_any("ボーク")),
    EventRule("敬遠", has_any("敬遠")),
    EventRule("四球", has_any("四球")),
    EventRule("死球", has_any("死球")),
    EventRule("振り逃げ", _dropped_third_strike),
    EventRule("三振", has_any("三振")),
    EventRule("本塁打", has_any("本塁打", "ホームラン")),
    EventRule("三塁打", has_any("三塁打")),
    EventRule("二塁打", has_any("二塁打")),
    EventRule("__SINGLE__", _single),
    EventRule("犠飛", has_any("犠飛", "犠牲フライ")),
    EventRule("スクイズ", has_any("スクイズ")),
    EventRule("犠打", has_any("犠打", "送りバント", "スリーバンド")),
    EventRule("失策", has_any("失策", "悪送球", "後逸", "ファンブル", "落球")),
    EventRule("野選", has_any("野手選択", "野選", "フィルダースチョイス")),
    EventRule("捕逸", has_any("捕逸")),
    EventRule("暴投", has_any("暴投")),
    EventRule("ゴロ", has_any("ゴロ")),
    EventRule("直", has_any("直")),
    EventRule("飛球", has_any("飛", "フライ")),
)


def lookup_event_label(line: str) -> str:
    text = str(line or "")
    if not text:
        return ""
    for rule in EVENT_RULES:
        if rule.matcher(text):
            if rule.label == "__SINGLE__":
                return _single_label(text)
            return rule.label
    return text[:16]
