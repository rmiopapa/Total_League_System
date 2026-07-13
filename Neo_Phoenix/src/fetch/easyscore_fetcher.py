from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import urllib.request
import urllib.parse
from html import unescape

from src.fetch.easyscore_html_parser import EasyScoreHtmlParser


@dataclass
class FetchResult:
    url: str
    game_id: str
    title: str
    text: str
    saved_path: str
    html_saved_path: str = ""


class EasyScoreTextFetcher:
    """
    Phoenix V2.4

    EasyScore / OmyuTech のテキスト速報ページを取得し、Phoenix入力用txtへ変換する。

    まずは urllib 標準ライブラリのみで実装。
    """

    def fetch_urls_file(self, urls_file: str | Path, out_dir: str | Path, limit: int = 3) -> list[FetchResult]:
        urls_file = Path(urls_file)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        urls = self._read_urls(urls_file)[:limit]
        results: list[FetchResult] = []

        for idx, url in enumerate(urls, 1):
            result = self.fetch_one(url, out_dir=out_dir, index=idx)
            results.append(result)

        return results

    def fetch_one(self, url: str, out_dir: str | Path, index: int = 1) -> FetchResult:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        normalized_url = self._normalize_textlive_url(url)
        html = self._download(normalized_url)
        parser = EasyScoreHtmlParser()
        text = parser.parse(html)

        game_id = self._extract_game_id(normalized_url)
        title = parser.guess_game_title(text, fallback=self._guess_title(text, game_id, index))

        # ファイル名は安全に
        safe_title = self._safe_filename(title)
        if not safe_title:
            safe_title = f"Game{index}_{game_id or 'unknown'}"

        path = out_dir / f"{index:02d}_{safe_title}.txt"
        path.write_text(text, encoding="utf-8")

        # V2.4: HTMLも自動保存する。
        # 正解データ保存時に sample.html としてコピーできるようにする。
        html_dir = Path("html_cache")
        html_dir.mkdir(parents=True, exist_ok=True)
        html_path = html_dir / f"{index:02d}_{safe_title}.html"
        html_path.write_text(html, encoding="utf-8")

        return FetchResult(
            url=normalized_url,
            game_id=game_id,
            title=title,
            text=text,
            saved_path=str(path),
            html_saved_path=str(html_path),
        )

    def _read_urls(self, urls_file: Path) -> list[str]:
        if not urls_file.exists():
            raise FileNotFoundError(f"URLファイルが見つかりません: {urls_file}")

        urls = []
        for line in urls_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
        return urls

    def _normalize_textlive_url(self, url: str) -> str:
        # ボックススコアURL等が入力された場合も、gameIdからテキスト速報URLへ寄せる。
        game_id = self._extract_game_id(url)
        if game_id and "CupHomePageTextLive" not in url:
            return f"https://baseball.omyutech.com/CupHomePageTextLive.action?gameId={game_id}"
        return url

    def _download(self, url: str) -> str:
        url = self._normalize_textlive_url(url)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PhoenixEasyScoreJudge/2.2",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as res:
            raw = res.read()

        # OmyuTechはUTF-8想定。失敗時はcp932にもフォールバック。
        for enc in ("utf-8", "cp932", "shift_jis"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                pass
        return raw.decode("utf-8", errors="replace")

    def _html_to_text(self, html: str) -> str:
        # script/style除去
        html = re.sub(r"(?is)<script.*?>.*?</script>", "\n", html)
        html = re.sub(r"(?is)<style.*?>.*?</style>", "\n", html)

        # 改行化
        html = re.sub(r"(?i)<br\s*/?>", "\n", html)
        html = re.sub(r"(?i)</p\s*>", "\n", html)
        html = re.sub(r"(?i)</div\s*>", "\n", html)
        html = re.sub(r"(?i)</li\s*>", "\n", html)
        html = re.sub(r"(?i)</tr\s*>", "\n", html)

        # タグ除去
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = unescape(text)

        # 空白整理
        text = text.replace("\xa0", " ")
        lines = []
        for line in text.splitlines():
            line = re.sub(r"[ \t]+", " ", line).strip()
            if line:
                lines.append(line)

        # Phoenixが使う打席本文の抽出を優先。ひとまず全テキスト保存。
        return "\n".join(lines) + "\n"

    def _extract_game_id(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if "gameId" in qs and qs["gameId"]:
            return qs["gameId"][0]
        m = re.search(r"gameId=(\d+)", url)
        return m.group(1) if m else ""

    def _guess_title(self, text: str, game_id: str, index: int) -> str:
        # 対戦カードらしい行を推定
        candidates = []
        for line in text.splitlines()[:120]:
            if "大学" in line and ("対" in line or "vs" in line.lower() or "-" in line or "－" in line):
                candidates.append(line)
            elif "第" in line and "試合" in line:
                candidates.append(line)

        if candidates:
            title = candidates[0]
            title = re.sub(r"\s+", "", title)
            return title[:40]

        return f"Game{index}_{game_id}" if game_id else f"Game{index}"

    def _safe_filename(self, name: str) -> str:
        bad = r'<>:"/\|?*'
        for ch in bad:
            name = name.replace(ch, "_")
        name = name.strip().strip(".")
        return name[:80]
