from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from html import unescape
import re


@dataclass
class DomPlay:
    inning: str
    no: str
    text: str


@dataclass
class DomParseResult:
    title: str = ""
    cup: str = ""
    date: str = ""
    stadium: str = ""
    visitor: str = ""
    home: str = ""
    score: str = ""
    lines: list[str] = field(default_factory=list)
    plays: list[DomPlay] = field(default_factory=list)


class _TextLiveHTMLParser(HTMLParser):
    """
    EasyScore / OmyuTech テキスト速報HTML専用の軽量DOM抽出器。
    標準ライブラリだけで動作する。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_textlive_ul = False
        self.ul_depth = 0

        self.in_li = False
        self.li_depth = 0
        self.li_class = ""
        self.li_text_parts: list[str] = []

        self.in_title_tag = False
        self.page_title_parts: list[str] = []

        self.hidden_inputs: dict[str, str] = {}
        self.current_attrs = {}

        self.items: list[tuple[str, str]] = []  # (kind, text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.current_attrs = attrs

        if tag.lower() == "title":
            self.in_title_tag = True

        if tag.lower() == "input":
            input_id = attrs.get("id") or attrs.get("name")
            value = attrs.get("value")
            if input_id and value is not None:
                self.hidden_inputs[input_id] = value

        if tag.lower() == "ul" and attrs.get("id") == "ul_textlive":
            self.in_textlive_ul = True
            self.ul_depth = 1
            return

        if self.in_textlive_ul:
            if tag.lower() == "ul":
                self.ul_depth += 1
            if tag.lower() == "li":
                self.in_li = True
                self.li_depth = 1
                self.li_class = attrs.get("class", "")
                self.li_text_parts = []
            elif self.in_li:
                self.li_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title_tag = False

        if self.in_textlive_ul:
            if self.in_li:
                if tag.lower() == "li":
                    text = self._clean("".join(self.li_text_parts))
                    kind = "inning" if "inn_head" in self.li_class else "play" if "ab_result_txt" in self.li_class else "other"
                    if text:
                        self.items.append((kind, text))
                    self.in_li = False
                    self.li_depth = 0
                    self.li_class = ""
                    self.li_text_parts = []
                else:
                    self.li_depth = max(0, self.li_depth - 1)

            if tag.lower() == "ul":
                self.ul_depth -= 1
                if self.ul_depth <= 0:
                    self.in_textlive_ul = False

    def handle_data(self, data):
        if self.in_title_tag:
            self.page_title_parts.append(data)

        if self.in_textlive_ul and self.in_li:
            self.li_text_parts.append(data)

    def _clean(self, text: str) -> str:
        text = unescape(text)
        text = text.replace("\xa0", " ").replace("　", " ")
        text = re.sub(r"[ \t\r\n]+", " ", text).strip()
        return text


class EasyScoreDomParser:
    INNING_TITLE_RE = re.compile(r"([0-9０-９]+回[表裏])")
    LEADING_NO_RE = re.compile(r"^[0-9０-９]+\s*")
    PITCH_COUNT_RE = re.compile(r"\s*[^、。\s]+(?:\s[^、。\s]+)?\(\d+球/\d+球\)\s*$")

    def parse(self, html: str) -> DomParseResult:
        hp = _TextLiveHTMLParser()
        hp.feed(html)

        result = DomParseResult()
        result.title = self._guess_title(hp)
        result.cup = self._guess_cup(hp)
        result.score = self._guess_score(hp)

        current_inning = ""
        for kind, raw in hp.items:
            text = self._normalize(raw)

            if kind == "inning":
                inn = self._extract_inning(text)
                if inn:
                    current_inning = inn
                    result.lines.append(inn)
                continue

            if kind == "play":
                play = self._clean_play_text(text)
                if not play:
                    continue
                # 先発・マウンドだけの行も投手情報として残す
                result.lines.append(play)
                result.plays.append(DomPlay(
                    inning=current_inning,
                    no=self._extract_no(text),
                    text=play,
                ))

        # 重複・空行除去
        final_lines = []
        prev = None
        for line in result.lines:
            line = self._normalize(line)
            if not line or line == prev:
                continue
            final_lines.append(line)
            prev = line
        result.lines = final_lines
        return result

    def to_text(self, html: str) -> str:
        result = self.parse(html)
        header = []
        if result.title:
            header.append(result.title)
        if result.score:
            header.append(result.score)
        return "\n".join(header + result.lines).strip() + "\n"

    def _guess_title(self, hp: _TextLiveHTMLParser) -> str:
        # titleタグが最も安定
        title = self._normalize("".join(hp.page_title_parts))
        title = title.replace(" : 一球速報.com | OmyuTech", "")
        title = title.replace("｜一球速報.com｜OmyuTech", "")
        title = title.replace("テキスト速報-", " ")
        title = re.sub(r"\s+", " ", title).strip()
        # 「広大医 vs 広島大 ...」だけに短縮
        m = re.search(r"(.+?\s+vs\s+.+?)(?:\s|$)", title)
        if m:
            return self._compact_title(m.group(1))
        # hidden snsDescから推定
        sns = hp.hidden_inputs.get("fbSnsDesc") or hp.hidden_inputs.get("snsDesc") or ""
        m = re.search(r"([^\n]+)\s+(\d+)-(\d+)\s+([^\n]+)", sns)
        if m:
            return self._compact_title(f"{m.group(1)} vs {m.group(4)}")
        return self._compact_title(title[:60])

    def _guess_cup(self, hp: _TextLiveHTMLParser) -> str:
        title = self._normalize("".join(hp.page_title_parts))
        m = re.search(r"テキスト速報-(.+?)(?: :| \|)", title)
        return m.group(1).strip() if m else ""

    def _guess_score(self, hp: _TextLiveHTMLParser) -> str:
        sns = hp.hidden_inputs.get("fbSnsDesc") or hp.hidden_inputs.get("snsDesc") or ""
        lines = [self._normalize(x) for x in sns.splitlines() if self._normalize(x)]
        for line in lines:
            if re.search(r"\d+\s*-\s*\d+", line):
                return line
        return ""

    def _compact_title(self, text: str) -> str:
        text = self._normalize(text)
        text = text.replace(" vs ", "－").replace("vs", "－")
        text = re.sub(r"\s+", "", text)
        text = re.sub(r"テキスト速報.*$", "", text)
        return text[:40]

    def _normalize(self, text: str) -> str:
        text = unescape(text or "")
        text = text.replace("\xa0", " ").replace("　", " ")
        text = re.sub(r"[ \t\r\n]+", " ", text).strip()
        return text

    def _extract_inning(self, text: str) -> str:
        m = self.INNING_TITLE_RE.search(text)
        return m.group(1) if m else ""

    def _extract_no(self, text: str) -> str:
        m = re.match(r"^([0-9０-９]+)", text.strip())
        return m.group(1) if m else ""

    def _clean_play_text(self, text: str) -> str:
        text = self._normalize(text)
        text = self.LEADING_NO_RE.sub("", text).strip()

        # 行末の投手球数表示はPhoenix解析には不要なので削る
        # 例: 宮田 大雅(22球/22球)
        text = re.sub(r"\s*[\u3040-\u30ff\u3400-\u9fffA-Za-z]+\s*[\u3040-\u30ff\u3400-\u9fffA-Za-z]*\(\d+球/\d+球\)\s*$", "", text).strip()

        # 「先発は」「マウンド」は投手情報として残す
        if text in {"先発は", "マウンド"}:
            return ""
        return text
