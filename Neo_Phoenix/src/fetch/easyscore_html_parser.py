from __future__ import annotations

import re
from html import unescape

from src.fetch.easyscore_dom_parser import EasyScoreDomParser


class EasyScoreHtmlParser:
    """
    Phoenix V2.2 Sprint2

    OmyuTech / EasyScore のHTMLから、Phoenix解析に必要な本文を抽出する。
    目的は「ページ全体テキスト」ではなく「試合経過・打席イベント中心のテキスト」へ寄せること。
    """

    INNING_RE = re.compile(r"^[0-9０-９]+回[表裏]$")
    PLAY_HINT_RE = re.compile(
        r"(から|初球|球目|フルカウント|打って|打つも|空振り三振|見逃し三振|四球|死球|安打|本塁打|ホームラン|"
        r"二塁打|三塁打|犠打|犠飛|ゴロ|飛|ライナー|失策|落球|悪送球|暴投|捕逸|盗塁|封殺|併殺|"
        r"出塁|進む|\+1点|\+2点|\+3点|チェンジ)"
    )
    SCORE_RE = re.compile(r"\+[0-9０-９]+点")
    BASE_STATE_RE = re.compile(r"(無死|１死|２死|一塁|二塁|三塁|満塁|一、二塁|一、三塁|二、三塁|残塁)")
    NOISE_HINT_RE = re.compile(
        r"(ログイン|メニュー|トップ|大会情報|チーム情報|個人成績|試合一覧|速報|テキスト速報|"
        r"Copyright|JavaScript|SNS|共有|戻る|更新|検索|お問い合わせ|利用規約)"
    )

    def parse(self, html: str) -> str:
        # Sprint3: まずEasyScore専用DOM Parserで抽出する
        dom_text = EasyScoreDomParser().to_text(html)
        if dom_text.strip():
            return dom_text
        text = self._html_to_lines(html)
        return self.extract_game_text(text)

    def extract_game_text(self, raw_text_or_lines) -> str:
        if isinstance(raw_text_or_lines, str):
            lines = [self._normalize_line(x) for x in raw_text_or_lines.splitlines()]
        else:
            lines = [self._normalize_line(x) for x in raw_text_or_lines]

        lines = [x for x in lines if x]

        selected: list[str] = []
        current_inning = ""

        for line in lines:
            if self._is_noise(line):
                continue

            if self.INNING_RE.match(line):
                current_inning = line
                selected.append(line)
                continue

            if self._is_play_line(line):
                selected.append(line)
                continue

            # 試合名・対戦カード候補は先頭付近だけ残す
            if len(selected) < 5 and self._looks_like_game_title(line):
                selected.append(line)

        # 連続重複除去
        deduped: list[str] = []
        prev = None
        for line in selected:
            if line == prev:
                continue
            deduped.append(line)
            prev = line

        return "\n".join(deduped).strip() + "\n"

    def guess_game_title(self, parsed_text: str, fallback: str = "") -> str:
        for line in parsed_text.splitlines()[:30]:
            if self._looks_like_game_title(line) or "－" in line:
                return self._compact_title(line)
        return fallback

    def _html_to_lines(self, html: str) -> list[str]:
        html = re.sub(r"(?is)<script.*?>.*?</script>", "\n", html)
        html = re.sub(r"(?is)<style.*?>.*?</style>", "\n", html)

        # ブロック境界を改行に変換
        html = re.sub(r"(?i)<br\s*/?>", "\n", html)
        html = re.sub(r"(?i)</(p|div|li|tr|h1|h2|h3|td|th)\s*>", "\n", html)

        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = unescape(text)
        text = text.replace("\xa0", " ")

        return [self._normalize_line(x) for x in text.splitlines()]

    def _normalize_line(self, line: str) -> str:
        line = line.replace("　", " ")
        line = re.sub(r"[ \t]+", " ", line).strip()
        return line

    def _is_noise(self, line: str) -> bool:
        if not line:
            return True
        if len(line) <= 1:
            return True
        if self.NOISE_HINT_RE.search(line):
            # 「テキスト速報」だけのタイトル等は除くが、打席本文に含まれる場合は残す
            if not self.PLAY_HINT_RE.search(line):
                return True
        # URLやCSS断片
        if line.startswith("http") or "{" in line or "}" in line:
            return True
        return False

    def _is_play_line(self, line: str) -> bool:
        if self.SCORE_RE.search(line):
            return True
        if self.PLAY_HINT_RE.search(line) and (self.BASE_STATE_RE.search(line) or "点" in line):
            return True
        # 打順＋選手名＋イベントらしい行
        if re.match(r"^[0-9０-９]+番", line) and self.PLAY_HINT_RE.search(line):
            return True
        return False

    def _looks_like_game_title(self, line: str) -> bool:
        if len(line) > 80:
            return False
        if "vs" in line.lower() and ("大学" in line or "大" in line):
            return True
        if "－" in line and ("大学" in line or "大" in line):
            return True
        if "対" in line and ("大学" in line or "大" in line):
            return True
        return False

    def _compact_title(self, line: str) -> str:
        line = line.replace("テキスト速報", "")
        line = re.sub(r"[-－]?\d{4}年度.*$", "", line)
        line = re.sub(r"\s+", "", line)
        return line[:40]
