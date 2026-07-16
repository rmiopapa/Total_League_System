# -*- coding: utf-8 -*-
"""
LeagueSuite for WordPress - LeaguePost v4.0 Tile UI & Schedule Edition
リーグ戦速報記事作成専用・WordPress自動入力版。

- WordPressへのログイン入力は自動化しません。
- Seleniumでログイン済みブラウザを開き、Gutenberg内部APIへタイトルと本文HTMLを直接入力します。
- 公開操作は手動確認を前提にします。
"""

import csv
import html
import json
import logging
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import ctypes
import os
import sys
import time
import webbrowser
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter import font as tkfont

APP_NAME = "LeaguePost"
APP_TITLE = "LeagueSuite for WordPress - LeaguePost"
APP_VERSION = "4.1.74 CustomTkinter Sidebar Edition"

POST_TYPE_RESULT = "試合速報"
POST_TYPE_STANDINGS = "順位＆星取表"
POST_TYPE_AWARDS = "個人賞"
POST_TYPE_SCHEDULE = "日程"
POST_TYPE_REVIEW = "寸評追加"
POST_TYPES = [POST_TYPE_RESULT, POST_TYPE_STANDINGS, POST_TYPE_AWARDS, POST_TYPE_SCHEDULE, POST_TYPE_REVIEW]
DEFAULT_ELEAGUE_URL = "https://safe.omyutech.com/league/57"
DEFAULT_WP_POST_LIST_URL = "https://chugoku.junko.or.jp/wp-admin/edit.php"


def normalize_post_type(value: str) -> str:
    if value == "リーグ戦速報":
        return POST_TYPE_RESULT
    return value if value in POST_TYPES else POST_TYPE_RESULT


def normalize_division_key(value: str) -> str:
    if "2" in value or "２" in value:
        return "2"
    return "1"

def normalize_division_key(value: str) -> str:
    if "入替" in value or "入れ替え" in value or "蜈･譖ｿ" in value:
        return "3"
    if "2" in value or "２" in value or "・帝" in value:
        return "2"
    return "1"


if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

def bundled_app_dir(folder_name: str) -> Path:
    candidates = [
        BASE_DIR / folder_name,
        BASE_DIR.parent / folder_name,
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


UNIVERSITY_ROSTER_APP_DIR = bundled_app_dir("大学名簿統合システム")
NEO_PHOENIX_APP_DIR = bundled_app_dir("Neo_Phoenix")
APP_DATA_DIR = BASE_DIR / "LeaguePost_data"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR = APP_DATA_DIR / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
LEGACY_CONFIG_FILE = LOCAL_APPDATA / APP_NAME / "leaguepost_config.json"
BASE_LEGACY_CONFIG_FILE = BASE_DIR / "leaguepost_config.json"
CONFIG_FILE = APP_DATA_DIR / "leaguepost_config.json"
LOG_DIR = APP_DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "LeaguePost.log"
SELENIUM_PROFILE_DIR = APP_DATA_DIR / "selenium_chrome_profile"


def app_path(value):
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def app_path_text(value) -> str:
    path = Path(value)
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except Exception:
        return str(path)


def app_path_exists(value) -> bool:
    path = app_path(value)
    return bool(path and path.exists())


def stored_app_path_text(value) -> str:
    path = app_path(value)
    return app_path_text(path) if path else ""

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)


@dataclass
class ResultPostItem:
    index: int
    total: int
    title_text: str
    body_html: str
    categories_list: list
    publish_datetime_value: datetime
    meta_label: str = ""

    @property
    def title(self) -> str:
        return self.title_text

    @property
    def publish_datetime(self) -> datetime:
        return self.publish_datetime_value

    @property
    def pub_year(self) -> str:
        return self.publish_datetime.strftime("%Y")

    @property
    def pub_month(self) -> str:
        return str(int(self.publish_datetime.strftime("%m")))

    @property
    def pub_day(self) -> str:
        return str(int(self.publish_datetime.strftime("%d")))

    @property
    def pub_hour(self) -> str:
        return self.publish_datetime.strftime("%H")

    @property
    def pub_minute(self) -> str:
        return self.publish_datetime.strftime("%M")

    @property
    def categories(self):
        return self.categories_list


@dataclass
class PostItem:
    index: int
    total: int
    game_date: datetime
    league_name: str
    cup_id: str
    tournament_id: str

    @property
    def day_label(self) -> str:
        if self.index == 1:
            return "初日"
        if self.index == self.total:
            return "最終日"
        return f"{self.index}日目"

    @property
    def title(self) -> str:
        return f"{self.league_name}　{self.day_label}"

    @property
    def yyyymmdd(self) -> str:
        return self.game_date.strftime("%Y%m%d")

    @property
    def publish_datetime(self) -> datetime:
        return self.game_date - timedelta(days=1) + timedelta(hours=17)

    @property
    def pub_year(self) -> str:
        return self.publish_datetime.strftime("%Y")

    @property
    def pub_month(self) -> str:
        return str(int(self.publish_datetime.strftime("%m")))

    @property
    def pub_day(self) -> str:
        return str(int(self.publish_datetime.strftime("%d")))

    @property
    def pub_hour(self) -> str:
        return self.publish_datetime.strftime("%H")

    @property
    def pub_minute(self) -> str:
        return self.publish_datetime.strftime("%M")

    @property
    def categories(self):
        return guess_categories(self.league_name)


def normalize_tournament_id(value: str) -> str:
    v = value.strip()
    if not v:
        return v
    if v.startswith("57-"):
        return v
    return "57-" + v


def reiwa_year_text(year_text: str) -> str:
    try:
        y = int(year_text)
        r = y - 2018
        if r == 1:
            return "令和元年度"
        return f"令和{r}年度"
    except Exception:
        return f"{year_text}年度"


def western_year_text(year_text: str) -> str:
    try:
        return f"{int(year_text)}年度"
    except Exception:
        return f"{year_text}年度"


def season_label(season: str) -> str:
    return "春季リーグ戦" if season == "春季" else "秋季リーグ戦"


def season_code(season: str) -> str:
    return "haru" if season == "春季" else "aki"


def division_code(division: str) -> str:
    if division == "１部":
        return "01"
    if division == "２部":
        return "02"
    return "03"


def make_league_name(year_text: str, season: str, division: str) -> str:
    if division == "入替戦":
        return f"{reiwa_year_text(year_text)}　{season_label(season)}　入替戦"
    return f"{reiwa_year_text(year_text)}　{season_label(season)}　{division}"


def make_base_league_name(year_text: str, season: str) -> str:
    return f"{reiwa_year_text(year_text)}　{season_label(season)}"


def division_label_from_key(key: str) -> str:
    if key == "2":
        return "２部"
    if key == "3":
        return "入替戦"
    return "１部"



def division_key_from_label(label: str) -> str:
    text = str(label or "").replace(" ", "").replace("\u3000", "")
    text = text.replace("\uff11", "1").replace("\uff12", "2")
    if "\u5165\u66ff" in text or "\u5165\u308c\u66ff\u3048" in text:
        return "3"
    if "2\u90e8" in text:
        return "2"
    return "1"

def league_name_with_division(base_name: str, division_key: str) -> str:
    base = (base_name or "").strip()
    label = division_label_from_key(division_key)
    base_without_division = strip_league_division_suffix(base)
    if base_without_division != base:
        base = base_without_division
    if not base:
        return label
    return f"{base}　{label}".strip()


def eleague_division_label_from_key(key: str) -> str:
    if key == "2":
        return "2部"
    if key == "3":
        return "入替戦"
    return "1部"


def eleague_title_base(title_text: str, year_text: str, season: str) -> str:
    title = strip_result_title_suffix(title_text or "")
    if not title:
        title = make_base_league_name(year_text, season)
    western_prefix = f"{western_year_text(year_text)}中国地区大学準硬式野球連盟"
    reiwa_prefix = reiwa_year_text(year_text)
    if reiwa_prefix in title:
        return title.replace(reiwa_prefix, western_prefix, 1).strip()
    year_prefix = western_year_text(year_text)
    if year_prefix in title:
        return title.replace(year_prefix, western_prefix, 1).strip()
    return f"{western_prefix}　{title}".strip()


def eleague_name_with_division(base_name: str, division_key: str) -> str:
    base = strip_league_division_suffix(base_name)
    label = eleague_division_label_from_key(division_key)
    if not base:
        return label
    return f"{base}　{label}".strip()


def strip_league_division_suffix(value: str) -> str:
    text = (value or "").strip()
    return re.sub(r"[ 　]*[（(]?\s*(１部|1部|２部|2部|入替戦|入れ替え戦)\s*[）)]?\s*$", "", text).strip()


def strip_result_title_suffix(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[ 　]*(初日|最終日|[0-9０-９]+日目)\s*$", "", text).strip()
    return strip_league_division_suffix(text)


def make_tournament_id(year_text: str, season: str, division: str) -> str:
    return f"{year_text}{season_code(season)}{division_code(division)}"


def extract_cup_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    for pattern in (r"/cup/(\d+)", r"[?&]cupId=(\d+)", r"^(\d+)$"):
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return text


def parse_dates_with_default_year(text: str, default_year: int):
    dates = []
    for raw in text.replace("，", ",").replace("\n", ",").split(","):
        s = raw.strip()
        if not s:
            continue

        parsed = None
        for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d", "%Y%m%d"):
            try:
                parsed = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass

        if parsed is None:
            for fmt in ("%m/%d", "%m-%d", "%m.%d"):
                try:
                    tmp = datetime.strptime(s, fmt)
                    parsed = datetime(default_year, tmp.month, tmp.day)
                    break
                except ValueError:
                    pass

        if parsed is None:
            raise ValueError(f"日付形式が不正です: {s}")

        dates.append(parsed)

    return sorted(set(dates))


def guess_categories(name: str):
    t = name.replace(" ", "").replace("　", "")
    cats = []

    if "春季" in t:
        cats.append("春季リーグ戦")
    if "秋季" in t:
        cats.append("秋季リーグ戦")
    if "新人" in t:
        cats.append("新人戦")
    if "入替" in t or "入れ替え" in t:
        cats.append("入替戦")
    if "1部" in t or "１部" in t:
        cats.append("１部")
    if "2部" in t or "２部" in t:
        cats.append("２部")
    if "3部" in t or "３部" in t:
        cats.append("３部")

    return cats


def wordpress_category_targets(item, post_type=None):
    title = getattr(item, "title", "") or ""
    league = getattr(item, "league_name", "") or title
    source = f"{league} {title} {getattr(item, 'meta_label', '')}"
    compact = source.replace(" ", "").replace("　", "")
    post_type = post_type or getattr(item, "meta_label", "") or ""

    targets = ["開催大会"]
    if post_type == POST_TYPE_SCHEDULE or "日程" in title:
        targets += ["大会・日程／要綱", "大会・日程/要綱", "日程／要綱", "日程/要綱"]
        return targets

    season = "秋" if "秋" in compact else "春"
    is_relegation = "入替" in compact or "入れ替え" in compact
    if is_relegation:
        divisions = ["入れ替え戦", "入替戦"]
    elif "2部" in compact or "２部" in compact or "二部" in compact:
        divisions = ["二部", "２部", "2部"]
    else:
        divisions = ["一部", "１部", "1部"]

    if is_relegation:
        season_names = [f"{season}季リーグ", f"{season}季リーグ戦", f"{season}リーグ戦"]
        separators = ["", " ", "-", "‐", "－"]
    else:
        season_names = [f"{season}リーグ戦", f"{season}季リーグ戦"]
        separators = ["", " "]

    for season_name in season_names:
        for division in divisions:
            for sep in separators:
                targets.append(f"{season_name}{sep}{division}")
    return targets


def wordpress_publish_payload(item, post_type=None):
    if not hasattr(item, "game_date"):
        return None
    dt = item.publish_datetime
    return {
        "year": dt.strftime("%Y"),
        "month": dt.strftime("%m"),
        "day": dt.strftime("%d"),
        "hour": dt.strftime("%H"),
        "minute": dt.strftime("%M"),
        "iso": dt.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def focus_chrome_window(driver):
    try:
        driver.execute_cdp_cmd("Page.bringToFront", {})
    except Exception:
        pass
    try:
        driver.switch_to.window(driver.current_window_handle)
        driver.maximize_window()
        driver.execute_script("window.focus();")
    except Exception:
        pass

    if os.name != "nt":
        return
    try:
        title = (driver.title or "").strip()
    except Exception:
        title = ""
    if not title:
        return

    try:
        user32 = ctypes.windll.user32
        hwnd_target = ctypes.c_void_p()
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                window_title = buff.value or ""
                if title in window_title and "Chrome" in window_title:
                    hwnd_target.value = hwnd
                    return False
            except Exception:
                return True
            return True

        user32.EnumWindows(enum_proc(callback), 0)
        if hwnd_target.value:
            user32.ShowWindow(hwnd_target.value, 9)
            user32.SetForegroundWindow(hwnd_target.value)
    except Exception:
        pass


def post_body_html(item) -> str:
    if hasattr(item, "body_html"):
        return item.body_html
    return build_body_html(item)


def post_tournament_id(item) -> str:
    return normalize_tournament_id(getattr(item, "tournament_id", ""))


def build_result_style() -> str:
    return """
<style>
.leaguepost-result{font-family:'Meiryo UI','Yu Gothic',sans-serif;line-height:1.8;color:#222;}
.leaguepost-result h2{color:#2f5d34;font-size:30px;border-left:8px solid #2f5d34;padding-left:12px;margin:0 0 18px;}
.leaguepost-result h3{color:#1f4e79;font-size:22px;border-bottom:2px solid #d7e3f0;padding-bottom:4px;margin:24px 0 10px;}
.leaguepost-table{border-collapse:collapse;width:100%;max-width:760px;font-size:17px;margin:10px 0 14px;}
.leaguepost-table th{background:#eef5ee;color:#234b28;border:1px solid #c8d8c8;padding:8px;text-align:left;}
.leaguepost-table td{border:1px solid #d6d6d6;padding:8px;vertical-align:top;}
.leaguepost-note{background:#fff8e1;border-left:6px solid #e0a800;padding:10px 12px;margin:14px 0;font-size:15px;}
.leaguepost-award{border-left:6px solid #2f5d34;background:#f7faf7;padding:10px 14px;margin:10px 0;display:grid;grid-template-columns:190px 1fr;column-gap:18px;align-items:start;}
.leaguepost-award-title{font-weight:bold;color:#2f5d34;}
.leaguepost-award-body{white-space:normal;}
.leaguepost-award-line{display:block;}
.leaguepost-rank{font-weight:bold;text-align:center;width:70px;}
.leaguepost-avg-rank{width:70px;text-align:right;font-weight:bold;}
.leaguepost-avg-name{min-width:210px;}
.leaguepost-avg-value{width:90px;text-align:left;font-family:Consolas,'Meiryo UI',monospace;}
</style>"""


def _clean_lines(text: str):
    return [ln.strip().replace("１", "1") if False else ln.strip() for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]


def parse_standings_from_line_text(text: str):
    import re
    rows = []
    notes = []
    started = False
    for line in _clean_lines(text):
        line_norm = line.replace("　", " ")
        m = re.match(r"^\s*([0-9０-９]+)\s*位\s+(.+?)\s+(.+?)\s+勝ち点\s*([0-9０-９]+)\s*$", line_norm)
        if m:
            started = True
            rank = m.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789")) + "位"
            rows.append((rank, m.group(2).strip(), m.group(3).strip(), m.group(4).translate(str.maketrans("０１２３４５６７８９", "0123456789"))))
            continue
        if started:
            if any(key in line for key in ["最高殊勲", "敢闘賞", "最優秀", "最多勝", "首位打者", "盗塁王", "打点王", "ベストナイン", "打率十傑"]):
                break
            if line.startswith("順位") or line.startswith("大会"):
                continue
            notes.append(line)
    return rows, notes


def build_standings_body_html(league_name: str, tournament_id: str, line_text: str) -> str:
    rows, notes = parse_standings_from_line_text(line_text)
    if not rows:
        raise ValueError("順位行を読み取れませんでした。例：1位　山口大学　5勝　勝ち点15")
    table_rows = []
    for rank, team, record, point in rows:
        table_rows.append(
            f"<tr><td class='leaguepost-rank'>{html.escape(rank)}</td><td>{html.escape(team)}</td><td>{html.escape(record)}</td><td>{html.escape(point)}</td></tr>"
        )
    note_html = ""
    if notes:
        note_html = "<div class='leaguepost-note'>" + "<br>".join(html.escape(n) for n in notes) + "</div>"
    tid = normalize_tournament_id(tournament_id)
    return f"""<div class="leaguepost-result">
{build_result_style()}
<h3>順位</h3>
<table class="leaguepost-table">
<thead><tr><th>順位</th><th>大学名</th><th>成績</th><th>勝ち点</th></tr></thead>
<tbody>
{''.join(table_rows)}
</tbody>
</table>
{note_html}
</div>

<!--more-->

<script src="https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>

<div>
<script class="omyu" src="https://baseball.omyutech.com/ns/omyu_standing.js?ver=1.0" charset="utf-8"></script>
<br>
<script class="omyu">omyu.renderContent("57", "{html.escape(tid.replace('57-',''))}");</script>
</div>
"""


def build_awards_body_html(league_name: str, tournament_id: str, line_text: str) -> str:
    import re
    lines = _clean_lines(line_text)
    award_keys = ["最高殊勲選手", "敢闘賞", "最優秀防御率", "最多勝", "首位打者", "盗塁王", "打点王"]

    def is_section_head(x: str) -> bool:
        return any(x.startswith(k) for k in award_keys + ["ベストナイン", "打率十傑", "順位"])

    def split_players(text: str):
        parts = []
        for p in re.split(r"[、,，]\s*", text):
            p = p.strip(" 　")
            if p:
                parts.append(p)
        return parts

    def render_award(title: str, vals):
        vals = [v.strip(" 　") for v in vals if v.strip(" 　")]
        # 受賞者が1人の賞は1行表示。例：最優秀防御率 0.53 梶原弘貴（岡）
        single_line_titles = {"最高殊勲選手", "敢闘賞", "最優秀防御率", "首位打者", "打点王"}
        if title in single_line_titles:
            body = "　".join(vals)
            body_html = f"<span class='leaguepost-award-line'>{html.escape(body)}</span>" if body else ""
            return f"<div class='leaguepost-award'><div class='leaguepost-award-title'>{html.escape(title)}</div><div class='leaguepost-award-body'>{body_html}</div></div>"

        # 受賞者が複数の場合は、賞名・数値の右側で選手名の頭をそろえる。
        body_lines = []
        if vals:
            first = vals[0]
            body_lines.append(first)
            for v in vals[1:]:
                body_lines.extend(split_players(v) if ("、" in v or "," in v or "，" in v) else [v])
        body_html = "".join(f"<span class='leaguepost-award-line'>{html.escape(v)}</span>" for v in body_lines)
        return f"<div class='leaguepost-award'><div class='leaguepost-award-title'>{html.escape(title)}</div><div class='leaguepost-award-body'>{body_html}</div></div>"

    pre_more_blocks = []
    post_more_blocks = []
    i = 0
    more_inserted = False
    while i < len(lines):
        line = lines[i]
        matched = next((k for k in award_keys if line.startswith(k)), None)
        if matched:
            rest = line[len(matched):].strip(" 　")
            vals = []
            if rest:
                vals.append(rest)
            j = i + 1
            while j < len(lines) and not is_section_head(lines[j]):
                vals.append(lines[j])
                j += 1
            block = render_award(matched, vals)
            if more_inserted:
                post_more_blocks.append(block)
            else:
                pre_more_blocks.append(block)
                if matched == "敢闘賞":
                    more_inserted = True
            i = j
            continue
        i += 1

    if not more_inserted:
        more_inserted = True

    def collect_after(header):
        out=[]
        if header not in lines:
            return out
        idx=lines.index(header)+1
        while idx < len(lines):
            if lines[idx] != header and is_section_head(lines[idx]):
                break
            out.append(lines[idx]); idx+=1
        return out

    best = collect_after("ベストナイン")
    best_html = ""
    if best:
        trs=[]
        for b in best:
            pos=b[:1]
            name=b[1:].strip(" 　")
            trs.append(f"<tr><td class='leaguepost-rank'>{html.escape(pos)}</td><td>{html.escape(name)}</td></tr>")
        best_html = "<h3>ベストナイン</h3><table class='leaguepost-table'><tbody>"+"".join(trs)+"</tbody></table>"

    top = collect_after("打率十傑")
    top_html = ""
    if top:
        trs=[]
        for t in top:
            t_norm = t.replace("．", ".").strip()
            m = re.match(r"^([0-9０-９]+)\.\s*(.+?)\s+([0-9０-９]+\.[0-9０-９]+)\s*$", t_norm)
            if m:
                rank = m.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789")) + "."
                name = m.group(2).strip()
                avg = m.group(3).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
            else:
                m2 = re.match(r"^(.+?)\s+([0-9０-９]+\.[0-9０-９]+)\s*$", t_norm)
                rank = ""
                name = m2.group(1).strip() if m2 else t_norm
                avg = m2.group(2).translate(str.maketrans("０１２３４５６７８９", "0123456789")) if m2 else ""
            trs.append(f"<tr><td class='leaguepost-avg-rank'>{html.escape(rank)}</td><td class='leaguepost-avg-name'>{html.escape(name)}</td><td class='leaguepost-avg-value'>{html.escape(avg)}</td></tr>")
        top_html = "<h3>打率十傑</h3><table class='leaguepost-table'><tbody>"+"".join(trs)+"</tbody></table>"

    tid = normalize_tournament_id(tournament_id)
    return f"""<div class="leaguepost-result">
{build_result_style()}
<h3>個人賞</h3>
{''.join(pre_more_blocks)}
</div>

<!--more-->

<div class="leaguepost-result">
{''.join(post_more_blocks)}
{best_html}
{top_html}
</div>

<script src="https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>

<div>
<script class="omyu" src="https://baseball.omyutech.com/ns/omyu_playerranking.js?ver=1.0" charset="utf-8"></script>
<br>
<script class="omyu">omyu.renderContent("57", "{html.escape(tid.replace('57-',''))}");</script>
</div>
"""


def build_body_html(item: PostItem) -> str:
    tid = normalize_tournament_id(item.tournament_id)
    return f"""<p>速報・詳細は<a href="https://baseball.omyutech.com/CupHomePageMain.action?cupId={item.cup_id}&amp;date={item.yyyymmdd}">一球速報サイト</a>をご覧ください</p>

<!--more-->

<script src="https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>

<div>
<script class="omyu" src="https://baseball.omyutech.com/ns/omyu_inningscore.js?ver=1.3" charset="utf-8"></script>
<br>
<script class="omyu">omyu.renderInningScoreContent("{tid}","","{item.yyyymmdd}");</script>
</div>
"""


def fetch_url_text(url: str, timeout=25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 LeaguePost",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def strip_html_text(value: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", value or "")
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\u3000]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def split_japanese_review_sentences(text: str) -> list:
    compact = re.sub(r"[ \t\u3000]+", " ", text or "")
    compact = re.sub(r"\s*\n\s*", "\n", compact)
    parts = re.split(r"(?<=[。．.!！？?])|\n+", compact)
    return [part.strip() for part in parts if part and part.strip()]


def extract_review_pitching_context(game: dict, live_text: str) -> dict:
    teams = [str(game.get("team1") or "").strip(), str(game.get("team2") or "").strip()]
    teams = [team for team in teams if team]

    def other_team(team_name: str) -> str:
        key = normalize_team_match_key(team_name)
        for team in teams:
            if normalize_team_match_key(team) != key:
                return team
        return ""

    def clean_player_name(value: str) -> str:
        text = re.sub(r"\([^)]*\)|（[^）]*）", "", str(value or ""))
        text = re.sub(r"[\r\n\t]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or text in {"先発は", "マウンド", "投手", "試合開始", "試合終了"}:
            return ""
        if re.match(r"^\d+$", text) or re.search(r"[死一二三塁残無球目]", text) and len(text) > 12:
            return ""
        if any(mark in text for mark in ("攻撃", "広告", "ログイン", "ランキング", "勝敗表", "テキスト速報")):
            return ""
        return text

    lines = [line.strip() for line in re.split(r"[\r\n]+", live_text or "") if line.strip()]
    pitchers_by_team = {team: [] for team in teams}
    confirmed_pitchers = []
    current_batting_team = ""
    current_fielding_team = ""
    top_team = ""
    bottom_team = ""

    def add_pitcher(team: str, name: str, evidence: str, role: str = "投手"):
        team = str(team or "").strip()
        name = clean_player_name(name)
        if not team or not name:
            return
        opponent = other_team(team)
        rows = pitchers_by_team.setdefault(team, [])
        if not any(row.get("name") == name for row in rows):
            rows.append({"name": name, "team": team, "opponent": opponent, "role": role, "evidence": evidence[:300]})
        if not any(row.get("name") == name and row.get("team") == team for row in confirmed_pitchers):
            confirmed_pitchers.append({
                "name": name,
                "team": team,
                "opponent": opponent,
                "role": role,
                "do_not_assign_to": opponent,
                "evidence": evidence[:300],
            })

    for idx, line in enumerate(lines):
        inning_match = re.search(r"\d+回([表裏])\s+(.+?)の攻撃", line)
        if inning_match:
            half = inning_match.group(1)
            current_batting_team = inning_match.group(2).strip()
            current_fielding_team = other_team(current_batting_team)
            if half == "表" and not top_team:
                top_team = current_batting_team
                bottom_team = current_fielding_team
            elif half == "裏" and not bottom_team:
                bottom_team = current_batting_team
                top_team = current_fielding_team
            continue
        if line == "先発は" or line == "マウンド":
            for offset in range(1, 5):
                if idx + offset < len(lines):
                    name = clean_player_name(lines[idx + offset])
                    if name:
                        role = "先発投手" if line == "先発は" else "投手"
                        add_pitcher(current_fielding_team, name, f"{line}: {name}", role)
                        break
        if "【投手交代】" in line:
            before = re.sub(r"^.*?】", "", line)
            before = re.sub(r"→.*$", "", before)
            before_name = clean_player_name(before)
            if before_name:
                add_pitcher(current_fielding_team, before_name, line, "交代前投手")
            for offset in range(1, 5):
                if idx + offset < len(lines):
                    name = clean_player_name(lines[idx + offset])
                    if name:
                        add_pitcher(current_fielding_team, name, f"{line} -> {name}", "救援投手")
                        break

    pitcher_keywords = (
        "投手", "先発", "救援", "継投", "完投", "登板", "降板", "マウンド",
        "勝利投手", "敗戦投手", "バッテリー", "捕手", "被安打", "奪三振",
        "失点", "自責", "投げ", "抑え", "締め"
    )
    batting_noise = ("適時打", "安打", "二塁打", "三塁打", "本塁打", "犠飛", "盗塁")
    sentences = split_japanese_review_sentences(live_text)
    pitcher_sentences = []
    for sentence in sentences:
        if any(keyword in sentence for keyword in pitcher_keywords):
            pitcher_sentences.append(sentence[:500])

    evidence_by_team = []
    for team in teams:
        team_key = normalize_team_match_key(team)
        evidence = [
            f"{row.get('name', '')}: {row.get('evidence', '')}"
            for row in pitchers_by_team.get(team, [])
            if row.get("name")
        ]
        for sentence in pitcher_sentences:
            sentence_key = normalize_team_match_key(sentence)
            if team_key and team_key in sentence_key:
                evidence.append(sentence)
        evidence_by_team.append({
            "team": team,
            "pitchers": pitchers_by_team.get(team, []),
            "pitcher_evidence": evidence[:12],
        })

    possible_pitcher_lines = []
    for sentence in pitcher_sentences:
        if any(noise in sentence for noise in batting_noise) and not any(keyword in sentence for keyword in ("投手", "先発", "継投", "完投", "登板", "降板", "マウンド", "勝利投手", "敗戦投手")):
            continue
        possible_pitcher_lines.append(sentence)

    return {
        "teams_from_schedule": teams,
        "team1_from_schedule": teams[0] if len(teams) > 0 else "",
        "team2_from_schedule": teams[1] if len(teams) > 1 else "",
        "top_team": top_team,
        "bottom_team": bottom_team,
        "confirmed_pitchers": confirmed_pitchers,
        "confirmed_pitchers_text": "\n".join(
            f"{row['name']} = {row['team']}（{row['role']}、相手: {row['opponent']}、{row['opponent']}所属ではない）"
            for row in confirmed_pitchers
        ),
        "rule": (
            "confirmed_pitchersを最優先する。"
            "confirmed_pitchersのnameは必ずteam所属として扱い、do_not_assign_toのチーム所属にしてはいけない。"
            "投手の所属は pitcher_evidence_by_team を最優先する。"
            "各teamのpitcher_evidenceに含まれる投手名・先発名・救援名は、そのteam所属として扱う。"
            "投手名が取れている場合は寸評で積極的に使用する。"
            "pitcher_related_sentencesにしか出ない投手名は、所属を断定せず文脈に注意して使用する。"
        ),
        "usage_instruction": (
            "投手名を省略しすぎない。pitcher_evidence_by_teamに根拠がある投手名は、"
            "「○○大の先発・△△」「○○大は△△が好投」のようにチーム名付きで書いてよい。"
            "根拠がない場合だけ、投手陣・先発投手・救援陣などの安全な表現にする。"
        ),
        "pitcher_evidence_by_team": evidence_by_team,
        "pitcher_evidence_text": "\n".join(
            f"{row['team']}: " + " / ".join(row["pitcher_evidence"])
            for row in evidence_by_team
            if row.get("pitcher_evidence")
        ),
        "pitcher_related_sentences": possible_pitcher_lines[:25],
    }


def compress_live_text_for_review(game: dict, live_text: str, pitching_context: dict = None, max_chars: int = 3500) -> str:
    lines = [line.strip() for line in re.split(r"[\r\n]+", live_text or "") if line.strip()]
    if not lines:
        return ""
    keep = set()

    # Header/scoreboard area usually contains date, ballpark, final score, and inning totals.
    for idx in range(min(len(lines), 40)):
        keep.add(idx)

    important_patterns = [
        r"\d+回[表裏].+?の攻撃",
        r"試合開始",
        r"試合終了",
        r"先発は",
        r"マウンド",
        r"【投手交代】",
        r"投手交代",
        r"\+\d+点",
        r"先制",
        r"同点",
        r"逆転",
        r"勝ち越し",
        r"適時",
        r"犠飛",
        r"本塁打",
        r"暴投",
        r"失策",
        r"悪送球",
        r"後逸",
        r"四球",
        r"死球",
        r"満塁",
        r"決勝",
        r"最終回",
        r"ゲームセット",
        r"勝利投手",
        r"敗戦投手",
    ]
    important_re = re.compile("|".join(f"(?:{p})" for p in important_patterns))
    score_re = re.compile(r"\+\d+点|適時|犠飛|本塁打|先制|同点|逆転|勝ち越し|決勝|押し出し|暴投|失策|悪送球|後逸")
    pitcher_re = re.compile(r"先発|マウンド|投手交代|【投手交代】|登板|降板|完投|継投|勝利投手|敗戦投手")

    for idx, line in enumerate(lines):
        if important_re.search(line):
            before = 2
            after = 3
            if pitcher_re.search(line):
                before = 2
                after = 3
            if score_re.search(line):
                before = 4
                after = 5
            for pos in range(max(0, idx - before), min(len(lines), idx + after + 1)):
                keep.add(pos)

    # Preserve the ending because the final score, last rally, and winning/losing pitcher
    # often appear near the bottom of the rendered text.
    for idx in range(max(0, len(lines) - 35), len(lines)):
        keep.add(idx)

    selected = []
    last_idx = -2
    for idx in sorted(keep):
        if idx >= len(lines):
            continue
        if selected and idx > last_idx + 1:
            selected.append("...")
        selected.append(lines[idx])
        last_idx = idx

    context_lines = []
    if pitching_context:
        confirmed_text = str(pitching_context.get("confirmed_pitchers_text") or "").strip()
        if confirmed_text:
            context_lines.extend(["", "【確定投手】", confirmed_text])
        pitcher_evidence = str(pitching_context.get("pitcher_evidence_text") or "").strip()
        if pitcher_evidence:
            context_lines.extend(["", "【投手根拠】", pitcher_evidence])

    guide_lines = [
        "【寸評材料メモ】",
        f"対戦: {game.get('team1', '')}-{game.get('team2', '')}",
        f"日付: {game.get('date', '')} / 開始: {game.get('time', '')}",
        "以下は一球速報全文ではなく、得点場面・投手起用・終盤場面を中心に抽出した要点です。",
    ]

    compressed = "\n".join(guide_lines + [""] + selected + context_lines)
    if len(compressed) <= max_chars:
        return compressed

    # Prefer preserving the scoreboard/first scoring memo and confirmed pitcher context.
    context_text = "\n".join(context_lines)
    reserved = min(len(context_text), int(max_chars * 0.30))
    body_limit = max_chars - reserved - 12
    body = "\n".join(guide_lines + [""] + selected)
    if len(body) > body_limit:
        head = body[: int(body_limit * 0.70)]
        tail = body[-int(body_limit * 0.30):]
        body = head.rstrip() + "\n...\n" + tail.lstrip()
    if context_text:
        return (body.rstrip() + "\n\n" + context_text[-reserved:].lstrip()).strip()
    return body[:max_chars].strip()


def omyu_day_url(cup_id: str, yyyymmdd: str) -> str:
    return f"https://baseball.omyutech.com/CupHomePageMain.action?cupId={urllib.parse.quote(str(cup_id))}&date={yyyymmdd}"


def omyu_text_live_url(game_id: str) -> str:
    return f"https://baseball.omyutech.com/CupHomePageTextLive.action?gameId={urllib.parse.quote(str(game_id))}"


def parse_omyu_game_ids(day_html: str) -> list:
    ids = []
    seen = set()
    text = day_html or ""

    def add_candidate(game_id: str, context: str, source: str):
        game_id = str(game_id or "").strip()
        if not game_id or game_id in seen:
            return
        ids.append({"game_id": game_id, "context": strip_html_text(context or ""), "source": source})
        seen.add(game_id)

    score_parts = re.split(r'(?=<div[^>]+class=\\?["\'][^"\']*\bscoreBox\b)', text, flags=re.IGNORECASE)
    for part in score_parts:
        if "data-id" not in part and "gameId" not in part and "CupHomePageSeiseki" not in part:
            continue
        block = re.split(r'(?=<div[^>]+class=\\?["\'][^"\']*\bscoreBox\b)', part, maxsplit=1, flags=re.IGNORECASE)[0]
        data_match = re.search(r"data-id=\\?[\"'](\d{8,})\\?[\"']", block, flags=re.IGNORECASE)
        if data_match:
            add_candidate(data_match.group(1), block, "live")
            continue
        score_match = re.search(
            r"CupHomePage(?:Seiseki|TextLive)\.action\?[^\"'<>]*?gameId=(\d+)",
            block,
            flags=re.IGNORECASE,
        )
        if score_match:
            add_candidate(score_match.group(1), block, "score")

    patterns = [
        ("score", r"CupHomePageSeiseki\.action\?[^\"'<>]*?gameId=(\d+)"),
        ("live", r"CupHomePageTextLive\.action\?[^\"'<>]*?gameId=(\d+)"),
        ("live", r"data-id=\\?[\"'](\d{8,})\\?[\"']"),
        ("live", r"[\"']id[\"']\\?\s*:\\?\s*\\?[\"'](\d{8,})\\?[\"']"),
        ("live", r"data-id&quot;[^0-9]{0,30}(\d{8,})"),
        ("generic", r"gameId[=:/](\d+)"),
        ("generic", r"gameId%3D(\d+)"),
        ("generic", r"gameId[\"']?\s*[:=]\s*[\"']?(\d+)"),
        ("generic", r"openCupHomePageGame\w*\([^)]*?[\"'](\d{8,})[\"']"),
        ("generic", r"openCupHomePageGame\w*\([^)]*?(\d{8,})"),
        ("generic", r"/Game/[a-z]/(\d{8,})"),
        ("generic", r"gameId&quot;[^0-9]{0,30}(\d{8,})"),
    ]
    for source, pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            game_id = match.group(1)
            if game_id in seen:
                continue
            context_width = 2600 if source == "score" else 1600
            start = max(0, match.start() - context_width)
            end = min(len(text), match.end() + context_width)
            add_candidate(game_id, text[start:end], source)
    return ids


def match_omyu_game_ids(games: list, day_html: str) -> list:
    candidates = parse_omyu_game_ids(day_html)
    unused = list(candidates)
    matched = []
    for game in games:
        team1_key = normalize_team_match_key(game.get("team1", ""))
        team2_key = normalize_team_match_key(game.get("team2", ""))
        hit = None
        for cand in unused:
            context_key = normalize_team_match_key(cand.get("context", ""))
            if team1_key and team2_key and team1_key in context_key and team2_key in context_key:
                hit = cand
                break
        if hit is not None:
            unused.remove(hit)
        item = dict(game)
        item["game_id"] = hit.get("game_id", "") if hit else ""
        item["game_context"] = hit.get("context", "") if hit else ""
        matched.append(item)
    score_candidates = [cand for cand in candidates if cand.get("source") in ("score", "live")]
    if matched and len(score_candidates) == len(matched):
        for item, cand in zip(matched, score_candidates):
            if not item.get("game_id"):
                item["game_id"] = cand.get("game_id", "")
                item["game_context"] = cand.get("context", "")
    return matched


def team_name_match_keys(name: str) -> list:
    values = [str(name or "").strip()]
    alias = TEAM_NAME_ALIASES.get(str(name or "").strip(), "")
    if alias:
        values.append(alias)
    keys = []
    for value in values:
        key = normalize_team_match_key(value)
        if key and key not in keys:
            keys.append(key)
    return keys


def live_text_matches_game(game: dict, live_text: str) -> bool:
    text_key = normalize_team_match_key(live_text or "")
    if not text_key:
        return False
    for team in (game.get("team1", ""), game.get("team2", "")):
        keys = team_name_match_keys(team)
        if keys and not any(key in text_key for key in keys):
            return False
    return True


def find_verified_omyu_live_text(game: dict, html_sources: list) -> tuple:
    candidates = []
    seen = set()
    for source in html_sources:
        for cand in parse_omyu_game_ids(source or ""):
            game_id = cand.get("game_id", "")
            if game_id and game_id not in seen:
                candidates.append(cand)
                seen.add(game_id)
    for cand in candidates:
        game_id = cand.get("game_id", "")
        try:
            live_html = fetch_url_text(omyu_text_live_url(game_id))
            live_text = strip_html_text(live_html)
        except Exception:
            logging.error(traceback.format_exc())
            continue
        if live_text_matches_game(game, live_text):
            return game_id, live_text
    return "", ""


def build_team_code_lookup(master_rows: list) -> dict:
    if not master_rows:
        return {}
    header = [str(x or "").strip() for x in master_rows[0]]
    code_index = None
    for idx, name in enumerate(header):
        if "チームコード" in name or "コード" == name:
            code_index = idx
            break
    if code_index is None:
        code_index = max(0, len(header) - 1)
    lookup = {}
    for row in master_rows[1:]:
        if not row or code_index >= len(row):
            continue
        code = str(row[code_index] or "").strip()
        if not code:
            continue
        for value in row[:2]:
            key = normalize_team_match_key(str(value or ""))
            if key:
                lookup[key] = code
    return lookup


def team_code_for_game(game: dict, lookup: dict) -> str:
    for team in (game.get("team1", ""), game.get("team2", "")):
        values = [team, TEAM_NAME_ALIASES.get(team, "")]
        for value in values:
            key = normalize_team_match_key(value)
            if key and key in lookup:
                return lookup[key]
    return ""


def normalize_review_date_label(value: str) -> str:
    text = (value or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y/%m/%d")
        except ValueError:
            pass
    return text


def split_manual_review_answers(text: str, max_count: int = 3) -> list:
    text = str(text or "").strip()
    if not text:
        return []
    text = re.sub(r"```(?:html|text|markdown)?", "", text, flags=re.IGNORECASE).replace("```", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    marker_split = re.split(r"(?:\*\*)?\s*【寸評】\s*(?:\*\*)?", text)
    chunks = [chunk.strip() for chunk in marker_split if chunk.strip()]
    if len(chunks) <= 1:
        chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n+", text) if chunk.strip()]
    reviews = []
    for chunk in chunks:
        chunk = re.sub(r"^\s*(?:第[一二三１２３1-3]試合|[1-3][\.．、:]|[-・])\s*", "", chunk)
        chunk = re.sub(r"^\s*(?:\*\*)?【寸評】(?:\*\*)?\s*", "", chunk)
        chunk = re.sub(r"^\s*#{1,4}\s*.*?\n", "", chunk)
        chunk = re.sub(r"\n{2,}", "\n", chunk).strip()
        if chunk:
            reviews.append(chunk)
        if len(reviews) >= max_count:
            break
    return reviews


def build_review_body_html(item, games: list) -> str:
    tid = normalize_tournament_id(getattr(item, "tournament_id", ""))
    cup_id = getattr(item, "cup_id", "")
    yyyymmdd = getattr(item, "yyyymmdd", "")
    parts = [
        f'<p>速報・詳細は<a href="{html.escape(omyu_day_url(cup_id, yyyymmdd))}">一球速報サイト</a>をご覧ください</p>',
        "",
        "<!--more-->",
        "",
        '<script src="https://ajax.googleapis.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>',
    ]
    for game in games:
        team_code = game.get("team_code", "")
        review = game.get("review", "") or "（寸評を入力してください。）"
        parts.extend([
            "",
            "<div>",
            '<script class="omyu" src="https://baseball.omyutech.com/ns/omyu_inningscore.js?ver=1.3" charset="utf-8"></script>',
            "<br>",
            f'<script class="omyu">omyu.renderInningScoreContent("{html.escape(tid)}","{html.escape(team_code)}","{html.escape(yyyymmdd)}");</script>',
            "<p><strong>【寸評】</strong></p>",
            f"<p>{html.escape(review).replace(chr(10), '<br>')}</p>",
            "</div>",
        ])
    parts.extend([
        "",
        '<p style="text-align:right;"><small>※寸評は生成AIを活用して作成し、内容を確認のうえ掲載しています。</small></p>',
    ])
    return "\n".join(parts).strip() + "\n"


def build_schedule_body_html(league_name: str, cup_id: str, tournament_id: str, dates) -> str:
    if not cup_id:
        raise ValueError("日程ページには cupId が必要です。")
    if not dates:
        raise ValueError("日程ページ用の試合日一覧を入力してください。")

    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    rows = []
    for d in dates:
        date_label = f"{d.month}/{d.day}（{weekdays[d.weekday()]}）"
        yyyymmdd = d.strftime("%Y%m%d")
        url = f"https://baseball.omyutech.com/CupHomePageMain.action?cupId={html.escape(cup_id)}&amp;date={yyyymmdd}"
        rows.append(
            "<tr>"
            f"<td class='leaguepost-rank'>{html.escape(date_label)}</td>"
            f"<td><a href='{url}'>一球速報サイトで確認</a></td>"
            "</tr>"
        )

    tid = normalize_tournament_id(tournament_id)
    return f"""<div class="leaguepost-result">
{build_result_style()}
<h3>日程</h3>
<table class="leaguepost-table">
<thead><tr><th>日付</th><th>試合情報</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
<div class="leaguepost-note">速報・詳細は各日付の一球速報サイトをご覧ください。大会コード：{html.escape(tid)}</div>
</div>
"""


def make_schedule_title(year_text: str, season: str) -> str:
    return f"{reiwa_year_text(year_text)}　{season_label(season)}　日程"


def format_jp_date(d: datetime) -> str:
    return f"{d.month}月{d.day}日"


def parse_schedule_date_cell(value: str, default_year: int):
    import re
    s = (value or "").strip()
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    m = re.search(r"([0-9]{1,2})\s*月\s*([0-9]{1,2})\s*日", s)
    if m:
        return datetime(default_year, int(m.group(1)), int(m.group(2)))
    m = re.search(r"\b([0-9]{1,2})[/-]([0-9]{1,2})\b", s)
    if m:
        return datetime(default_year, int(m.group(1)), int(m.group(2)))
    return None


def schedule_section_title(value: str):
    compact = (value or "").replace(" ", "").replace("　", "")
    if compact.startswith(("1部", "１部")):
        return "１部"
    if compact.startswith(("2部", "２部")):
        return "２部"
    return None


def split_excel_schedule_sections(excel_text: str):
    sections = []
    current_title = ""
    current_rows = []
    for raw in (excel_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw.strip():
            continue
        cells = [c.strip() for c in raw.split("\t")]
        title = schedule_section_title("".join(cells).strip())
        if title:
            if current_rows:
                sections.append((current_title, current_rows))
            current_title = title
            current_rows = []
            continue
        current_rows.append(cells)
    if current_rows:
        sections.append((current_title, current_rows))
    return sections


def parse_playoff_schedule_date(cells, default_year: int):
    text = " ".join(c.strip() for c in cells if c.strip())
    if "入替" not in text and "入れ替え" not in text:
        return None
    main_text = text.split("予備日", 1)[0]
    return parse_schedule_date_cell(main_text, default_year)


def looks_like_schedule_venue(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    compact = compact_schedule_label(text)
    if any(word in compact for word in ("日程", "会場", "開始時刻", "対戦チーム", "本部", "係")):
        return False
    if any(word in compact for word in ("入替", "入れ替え", "予備日", "清瀬杯", "リーグ戦")):
        return False
    return bool(re.search(r"(球場|野球場|グラウンド|スタジアム|公園|市営|県営|倉敷|玉島|マスカット|森)", compact))


def collect_playoff_schedule_venues(excel_text: str) -> list:
    venues = []
    for _title, rows in split_excel_schedule_sections(excel_text):
        for row in rows:
            row_text = " ".join(c.strip() for c in row if c.strip())
            if "入替" not in row_text and "入れ替え" not in row_text:
                continue
            for cell in row:
                venue = (cell or "").strip()
                if looks_like_schedule_venue(venue) and venue not in venues:
                    venues.append(venue)
    return venues


def collect_all_schedule_venues(excel_text: str, default_year: int) -> list:
    venues = []
    for _title, rows in split_excel_schedule_sections(excel_text):
        records, _notes = collect_schedule_records_and_notes(rows, default_year)
        for rec in records:
            venue = (rec.get("venue") or "").strip()
            if venue and venue not in venues:
                venues.append(venue)
    for venue in collect_playoff_schedule_venues(excel_text):
        if venue not in venues:
            venues.append(venue)
    return venues


def collect_schedule_dates_by_division(excel_text: str, default_year: int):
    result = {"1": [], "2": [], "3": []}
    current_key = "1"
    seen = {"1": set(), "2": set(), "3": set()}
    for title, rows in split_excel_schedule_sections(excel_text):
        if title == "２部":
            current_key = "2"
        elif title == "１部":
            current_key = "1"
        for cells in rows:
            playoff_date = parse_playoff_schedule_date(cells, default_year)
            if playoff_date and playoff_date.date() not in seen["3"]:
                result["3"].append(playoff_date)
                seen["3"].add(playoff_date.date())
        try:
            records, _notes = collect_schedule_records_and_notes(rows, default_year)
        except NameError:
            records = []
        if records:
            for rec in records:
                date = rec.get("date_sort")
                if date and date.date() not in seen[current_key]:
                    result[current_key].append(date)
                    seen[current_key].add(date.date())
            continue
        for cells in rows:
            playoff_date = parse_playoff_schedule_date(cells, default_year)
            if playoff_date and playoff_date.date() not in seen["3"]:
                result["3"].append(playoff_date)
                seen["3"].add(playoff_date.date())
                continue
            if is_schedule_note_row(cells):
                break
            date = parse_schedule_date_cell(cells[0] if cells else "", default_year)
            if date and date.date() not in seen[current_key]:
                result[current_key].append(date)
                seen[current_key].add(date.date())
    return result


def dates_to_text(dates) -> str:
    return "\n".join(f"{d.month}/{d.day}" for d in dates)


def excel_col_to_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return max(0, value - 1)


def excel_serial_to_date_text(value: str):
    try:
        serial = float(value)
    except Exception:
        return value
    if 0 <= serial < 1:
        minutes = int(round(serial * 24 * 60))
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    if serial < 1:
        return value
    d = datetime(1899, 12, 30) + timedelta(days=int(serial))
    return f"{d.month}月{d.day}日"


def load_xlsx_schedule_text(path: str) -> str:
    xlsx_path = Path(path)
    if not xlsx_path.exists():
        raise ValueError("日程表Excelファイルが見つかりません。")
    if xlsx_path.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError("日程表Excelファイルは .xlsx または .xlsm を選択してください。")

    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }

    def text_of(node):
        parts = []
        for t in node.findall("main:t", ns):
            parts.append(t.text or "")
        for run in node.findall("main:r", ns):
            t = run.find("main:t", ns)
            if t is not None:
                parts.append(t.text or "")
        if parts:
            return "".join(parts)
        inline = node.find("main:is", ns)
        if inline is not None:
            return text_of(inline)
        return ""

    with zipfile.ZipFile(xlsx_path) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            shared = [text_of(si) for si in root.findall("main:si", ns)]

        date_style_ids = set()
        if "xl/styles.xml" in zf.namelist():
            styles = ET.fromstring(zf.read("xl/styles.xml"))
            custom_date_numfmts = set()
            for numfmt in styles.findall(".//main:numFmt", ns):
                code = (numfmt.attrib.get("formatCode") or "").lower()
                if any(token in code for token in ("yy", "mm", "dd", "m/d", "m月", "d日")):
                    custom_date_numfmts.add(numfmt.attrib.get("numFmtId"))
            builtin_date_ids = {str(i) for i in list(range(14, 23)) + [45, 46, 47]}
            cell_xfs = styles.find("main:cellXfs", ns)
            if cell_xfs is not None:
                for idx, xf in enumerate(cell_xfs.findall("main:xf", ns)):
                    numfmt_id = xf.attrib.get("numFmtId")
                    if numfmt_id in builtin_date_ids or numfmt_id in custom_date_numfmts:
                        date_style_ids.add(str(idx))

        sheet_titles = {}
        rel_targets = {}
        sheet_paths_order = []
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        for rel in rels.findall("pkgrel:Relationship", ns):
            target = rel.attrib.get("Target", "")
            if target.startswith("/"):
                target = target.lstrip("/")
            else:
                target = "xl/" + target
            rel_targets[rel.attrib.get("Id")] = target.replace("\\", "/")
        for sheet in workbook.findall(".//main:sheet", ns):
            rel_id = sheet.attrib.get(f"{{{ns['rel']}}}id")
            target = rel_targets.get(rel_id)
            if target:
                name = sheet.attrib.get("name", "")
                sheet_titles[target] = name
                sheet_paths_order.append((name, target))

        schedule_lines = []
        available = [(name, path) for name, path in sheet_paths_order if path in zf.namelist()]
        preferred = [(name, path) for name, path in available if "修正後" in name]
        if not preferred:
            preferred = [(name, path) for name, path in available if "日程" in name]
        if not preferred:
            preferred = available
        for sheet_name, sheet_path in preferred:
            sheet_root = ET.fromstring(zf.read(sheet_path))
            rows = []
            for row in sheet_root.findall(".//main:sheetData/main:row", ns):
                values = []
                for c in row.findall("main:c", ns):
                    col = excel_col_to_index(c.attrib.get("r", "A1"))
                    while len(values) < col:
                        values.append("")
                    cell_type = c.attrib.get("t")
                    style_id = c.attrib.get("s")
                    v = c.find("main:v", ns)
                    if cell_type == "s" and v is not None:
                        idx = int(v.text or "0")
                        value = shared[idx] if idx < len(shared) else ""
                    elif cell_type == "inlineStr":
                        value = text_of(c)
                    elif v is not None:
                        raw_value = v.text or ""
                        value = excel_serial_to_date_text(raw_value) if style_id in date_style_ids else raw_value
                        if isinstance(value, str) and value.endswith(".0"):
                            value = value[:-2]
                    else:
                        value = ""
                    values.append(str(value).strip())
                while values and not values[-1]:
                    values.pop()
                if values and any(values):
                    rows.append(values)
            if not rows:
                continue
            title = schedule_section_title(sheet_name or sheet_titles.get(sheet_path, ""))
            if title:
                schedule_lines.append(title)
            schedule_lines.extend("\t".join(row) for row in rows)
        if not schedule_lines:
            raise ValueError("日程表Excelファイルから表を読み取れませんでした。")
        return "\n".join(schedule_lines)


def build_schedule_excel_table_html(excel_text: str) -> str:
    sections = split_excel_schedule_sections(excel_text)
    if not sections:
        raise ValueError("日程表Excelファイルから表を読み取れませんでした。")

    html_parts = []
    for title, rows in sections:
        max_cols = max((len(r) for r in rows), default=0)
        if title:
            html_parts.append(f"<h3>{html.escape(title)}</h3>")
        html_parts.append('<div class="leaguepost-schedule-wrap"><table class="leaguepost-table leaguepost-schedule-table">')
        for row_index, row in enumerate(rows):
            tag = "th" if row_index == 0 else "td"
            html_parts.append("<tr>")
            for col_index in range(max_cols):
                cell = row[col_index] if col_index < len(row) else ""
                cell_html = html.escape(cell).replace("\n", "<br>")
                html_parts.append(f"<{tag}>{cell_html}</{tag}>")
            html_parts.append("</tr>")
        html_parts.append("</table></div>")
    return "\n".join(html_parts)


def schedule_cell(row, index: int) -> str:
    return row[index].strip() if index < len(row) else ""


def compact_schedule_label(value: str) -> str:
    return (value or "").replace(" ", "").replace("　", "").strip()


def schedule_label_startswith(value: str, label: str) -> bool:
    return compact_schedule_label(value).startswith(compact_schedule_label(label))


KNOWN_SCHEDULE_VENUES = [
    "倉敷市営球場",
    "倉敷玉島の森野球場",
    "玉島の森野球場",
    "真庭やまびこスタジアム",
]


def cleanup_schedule_venue(value: str) -> str:
    text = (value or "").strip()
    for venue in KNOWN_SCHEDULE_VENUES:
        if text.startswith(venue):
            return venue
    return text


TEAM_ABBREVIATION_CANDIDATES = [
    "鳥取大", "鳥大医", "島根大", "吉国大", "吉備国", "岡山大", "岡大医",
    "川医大", "広修大", "広国大", "広島大", "広大医", "海保大", "下市大", "山口大",
]


def cleanup_schedule_team_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    text = re.split(r"[ァ-ヶｦ-ﾟ]", text, maxsplit=1)[0].strip()
    for team in sorted(TEAM_ABBREVIATION_CANDIDATES, key=len, reverse=True):
        if text.startswith(team):
            return team
    return text


def is_schedule_table_header(row) -> bool:
    return schedule_label_startswith(schedule_cell(row, 0), "日程") and schedule_label_startswith(schedule_cell(row, 1), "会場")


def is_schedule_note_row(row) -> bool:
    filled = [c for c in row if c.strip()]
    if not filled:
        return False
    text = compact_schedule_label(filled[0])
    return text.startswith(("左・・・", "係・・・", "理事会", "予備日", "入れ替え戦", "清瀬杯"))


def schedule_header_groups(header_row, sub_header_row):
    head_col = None
    for i, value in enumerate(header_row):
        if schedule_label_startswith(value, "本部"):
            head_col = i
            break

    groups = []
    for i, value in enumerate(sub_header_row):
        if not schedule_label_startswith(value, "対戦チーム"):
            continue
        role_col = None
        for j in range(i + 1, min(i + 4, len(sub_header_row))):
            if schedule_label_startswith(schedule_cell(sub_header_row, j), "係"):
                role_col = j
                break
        if role_col is None:
            continue
        venue = cleanup_schedule_venue(schedule_cell(header_row, i))
        if not venue:
            for j in range(i, -1, -1):
                venue = cleanup_schedule_venue(schedule_cell(header_row, j))
                if venue:
                    break
        groups.append({
            "venue": venue,
            "team_col": i,
            "role_col": role_col,
            "head_col": head_col,
            "records": [],
        })
    return groups


def collect_schedule_venue_blocks(rows):
    blocks = []
    active_groups = []
    current_date = ""
    skip_row_index = None
    for row_index, row in enumerate(rows):
        if row_index == skip_row_index:
            continue
        if is_schedule_note_row(row):
            break
        if is_schedule_table_header(row) and row_index + 1 < len(rows):
            active_groups = schedule_header_groups(row, rows[row_index + 1])
            blocks.extend(active_groups)
            current_date = ""
            skip_row_index = row_index + 1
            continue
        if not active_groups:
            continue
        date_value = schedule_cell(row, 0)
        if date_value:
            current_date = date_value
        time_value = normalize_schedule_time_text(schedule_cell(row, 1))
        for group in active_groups:
            team = schedule_cell(row, group["team_col"])
            role = schedule_cell(row, group["role_col"])
            if not team and not role:
                continue
            head = schedule_cell(row, group["head_col"]) if group["head_col"] is not None else ""
            group["records"].append({
                "date": current_date,
                "time": time_value,
                "team": team,
                "role": role,
                "head": head,
            })
    return [block for block in blocks if block["records"]]


def parse_schedule_time_sort(value: str):
    try:
        numeric = float(str(value or "").strip())
        if 0 <= numeric < 1:
            return int(round(numeric * 24 * 60))
    except Exception:
        pass
    m = re.search(r"([0-9]{1,2})\s*[:：]\s*([0-9]{1,2})", value or "")
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"([0-9]{1,2})(?:\.0)?$", value or "")
    if m:
        return int(m.group(1)) * 60
    return 9999


def normalize_schedule_time_text(value: str) -> str:
    text = (value or "").strip()
    try:
        numeric = float(text)
        if 0 <= numeric < 1:
            minutes = int(round(numeric * 24 * 60))
            return f"{minutes // 60:02d}:{minutes % 60:02d}"
    except Exception:
        pass
    return text


def collect_schedule_records_and_notes(rows, default_year: int):
    records = []
    notes = []
    active_groups = []
    current_date = ""
    skip_row_index = None
    in_notes = False
    order = 0
    for row_index, row in enumerate(rows):
        if row_index == skip_row_index:
            continue
        filled = [c.strip() for c in row if c.strip()]
        if in_notes:
            if filled:
                notes.append("　".join(filled))
            continue
        if is_schedule_note_row(row):
            in_notes = True
            if filled:
                notes.append("　".join(filled))
            continue
        if is_schedule_table_header(row) and row_index + 1 < len(rows):
            active_groups = schedule_header_groups(row, rows[row_index + 1])
            current_date = ""
            skip_row_index = row_index + 1
            continue
        if not active_groups:
            continue
        date_value = schedule_cell(row, 0)
        if date_value:
            current_date = date_value
        time_value = normalize_schedule_time_text(schedule_cell(row, 1))
        for group in active_groups:
            team = schedule_cell(row, group["team_col"])
            role = schedule_cell(row, group["role_col"])
            if not team and not role:
                continue
            head = schedule_cell(row, group["head_col"]) if group["head_col"] is not None else ""
            date_sort = parse_schedule_date_cell(current_date, default_year) or datetime(default_year, 12, 31)
            records.append({
                "date": current_date,
                "date_sort": date_sort,
                "time": time_value,
                "time_sort": parse_schedule_time_sort(time_value),
                "team": team,
                "role": role,
                "head": head,
                "venue": group["venue"],
                "order": order,
            })
            order += 1
    records.sort(key=lambda r: (r["date_sort"], r["time_sort"], r["order"]))
    return records, notes


def split_schedule_team_pair(value: str):
    text = (value or "").strip()
    if not text:
        return None
    parts = re.split(r"\s*[-－‐–—ー―×]\s*", text, maxsplit=1)
    if len(parts) != 2:
        return None
    left, right = cleanup_schedule_team_name(parts[0]), cleanup_schedule_team_name(parts[1])
    if not left or not right:
        return None
    return left, right


ELEAGUE_SCHEDULE_TEAM_ALIASES = {
    "吉国大": "吉備国",
}


def normalize_eleague_schedule_team_name(value: str) -> str:
    team = (value or "").strip()
    return ELEAGUE_SCHEDULE_TEAM_ALIASES.get(team, team)


def collect_eleague_schedule_games(excel_text: str, default_year: int, division_key: str):
    games = []
    seen = set()
    for title, rows in split_excel_schedule_sections(excel_text):
        section_key = normalize_division_key(title or "")
        if section_key != division_key:
            continue
        records, _notes = collect_schedule_records_and_notes(rows, default_year)
        for rec in records:
            pair = split_schedule_team_pair(rec.get("team", ""))
            if not pair:
                continue
            date_sort = rec.get("date_sort")
            if not date_sort:
                continue
            time_text = (rec.get("time") or "").strip()
            venue = (rec.get("venue") or "").strip()
            key = (date_sort.strftime("%Y-%m-%d"), time_text, pair[0], pair[1], venue)
            if key in seen:
                continue
            seen.add(key)
            games.append({
                "date": date_sort.strftime("%Y/%m/%d"),
                "date_iso": date_sort.strftime("%Y-%m-%d"),
                "time": time_text,
                "team1": pair[0],
                "team2": pair[1],
                "venue": venue,
            })
    return games


def xlsx_col_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def xlsx_read_first_sheet_rows(path: str) -> list:
    xlsx_path = Path(path)
    if not xlsx_path.exists():
        raise ValueError(f"Excelファイルが見つかりません: {xlsx_path}")
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def text_of(node):
        parts = []
        for t in node.findall("main:t", ns):
            parts.append(t.text or "")
        for run in node.findall("main:r", ns):
            t = run.find("main:t", ns)
            if t is not None:
                parts.append(t.text or "")
        if parts:
            return "".join(parts)
        inline = node.find("main:is", ns)
        if inline is not None:
            return text_of(inline)
        return ""

    with zipfile.ZipFile(xlsx_path) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            shared = [text_of(si) for si in root.findall("main:si", ns)]
        sheet_name = "xl/worksheets/sheet1.xml"
        root = ET.fromstring(zf.read(sheet_name))
        rows = []
        for row in root.findall(".//main:sheetData/main:row", ns):
            values = []
            for cell in row.findall("main:c", ns):
                col = excel_col_to_index(cell.attrib.get("r", "A1"))
                while len(values) < col:
                    values.append("")
                cell_type = cell.attrib.get("t")
                v = cell.find("main:v", ns)
                if cell_type == "s" and v is not None:
                    idx = int(v.text or "0")
                    value = shared[idx] if idx < len(shared) else ""
                elif cell_type == "inlineStr":
                    value = text_of(cell)
                elif v is not None:
                    value = v.text or ""
                else:
                    value = ""
                values.append(str(value).strip())
            while values and not values[-1]:
                values.pop()
            if values:
                rows.append(values)
        return rows


def xlsx_shared_string_cell(ref: str, index: int) -> str:
    return f'<c r="{ref}" t="s"><v>{index}</v></c>'


def build_shared_strings_xml(strings: list) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(strings)}" uniqueCount="{len(strings)}">',
    ]
    for value in strings:
        text = html.escape(str(value or ""), quote=False)
        parts.append(f"<si><t>{text}</t></si>")
    parts.append("</sst>")
    return "".join(parts)


def build_simple_xlsx_sheet_xml(rows: list, string_index: dict) -> str:
    row_count = max(1, len(rows))
    col_count = max(1, max((len(row) for row in rows), default=1))
    dimension = f"A1:{xlsx_col_name(col_count - 1)}{row_count}"
    parts = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
        f'<dimension ref="{dimension}"/>',
        "<sheetData>",
    ]
    for row_index, row in enumerate(rows, start=1):
        parts.append(f'<row r="{row_index}">')
        for col_index in range(col_count):
            value = row[col_index] if col_index < len(row) else ""
            ref = f"{xlsx_col_name(col_index)}{row_index}"
            parts.append(xlsx_shared_string_cell(ref, string_index[str(value or "")]))
        parts.append("</row>")
    parts.extend(["</sheetData>", "</worksheet>"])
    return "".join(parts)


def write_xlsx_rows_from_template(template_path: str, output_path: str, rows: list):
    template = Path(template_path)
    output = Path(output_path)
    if not template.exists():
        raise ValueError(f"テンプレートExcelが見つかりません: {template}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_output = output.with_suffix(output.suffix + ".tmp")
    strings = []
    string_index = {}
    for row in rows:
        for value in row:
            value = str(value or "")
            if value not in string_index:
                string_index[value] = len(strings)
                strings.append(value)
    if "" not in string_index:
        string_index[""] = len(strings)
        strings.append("")
    sheet_xml = build_simple_xlsx_sheet_xml(rows, string_index).encode("utf-8")
    shared_xml = build_shared_strings_xml(strings).encode("utf-8")
    with zipfile.ZipFile(template, "r") as zin:
        with zipfile.ZipFile(temp_output, "w", zipfile.ZIP_DEFLATED) as zout:
            wrote_shared = False
            for item in zin.infolist():
                if item.filename == "xl/worksheets/sheet1.xml":
                    data = sheet_xml
                elif item.filename == "xl/sharedStrings.xml":
                    data = shared_xml
                    wrote_shared = True
                else:
                    data = zin.read(item.filename)
                zout.writestr(item, data)
            if not wrote_shared:
                zout.writestr("xl/sharedStrings.xml", shared_xml)
    temp_output.replace(output)


def normalize_team_match_key(value: str) -> str:
    return re.sub(r"[\s　・･\-.－‐–—ー―（）()]", "", value or "").lower()


TEAM_NAME_ALIASES = {
    "吉国大": "吉備国際大学",
    "吉備国": "吉備国際大学",
}


def collect_eleague_team_names(excel_text: str, default_year: int, division_key: str) -> list:
    teams = []
    for game in collect_eleague_schedule_games(excel_text, default_year, division_key):
        for team in (game.get("team1", ""), game.get("team2", "")):
            team = (team or "").strip()
            if team and team not in teams:
                teams.append(team)
    return teams


def build_team_import_rows(master_rows: list, team_names: list) -> tuple:
    if not master_rows:
        raise ValueError("league_team_list.xlsxにチーム名簿がありません。")
    header = master_rows[0]
    data_rows = master_rows[1:]
    row_by_key = {}
    for row in data_rows:
        for value in row[:2]:
            key = normalize_team_match_key(value)
            if key:
                row_by_key[key] = row
    selected = [header]
    missing = []
    used = set()
    for team in team_names:
        lookup_values = [team, TEAM_NAME_ALIASES.get(team, "")]
        row = None
        for value in lookup_values:
            key = normalize_team_match_key(value)
            if key and key in row_by_key:
                row = row_by_key[key]
                break
        if row is None:
            missing.append(team)
            continue
        row_key = normalize_team_match_key(row[0] if row else "")
        if row_key not in used:
            selected.append(row)
            used.add(row_key)
    return selected, missing


def append_schedule_block_html(html_parts, block):
    venue = html.escape(block["venue"] or "")
    html_parts.append('<tr class="leaguepost-schedule-head leaguepost-schedule-head-main">')
    html_parts.append('<th rowspan="2">日程</th><th>会場</th>')
    html_parts.append(f'<th colspan="3">{venue}</th><th rowspan="2">本部</th>')
    html_parts.append("</tr>")
    html_parts.append('<tr class="leaguepost-schedule-head leaguepost-schedule-head-sub">')
    html_parts.append('<th>開始時刻</th><th colspan="2">対戦チーム</th><th>係</th>')
    html_parts.append("</tr>")

    by_date = []
    for rec in block["records"]:
        if by_date and by_date[-1][0] == rec["date"]:
            by_date[-1][1].append(rec)
        else:
            by_date.append((rec["date"], [rec]))

    for date_value, records in by_date:
        head = next((r["head"] for r in records if r["head"]), "")
        rowspan = len(records)
        for index, rec in enumerate(records):
            html_parts.append("<tr>")
            if index == 0:
                html_parts.append(f'<td rowspan="{rowspan}">{html.escape(date_value)}</td>')
            html_parts.append(f'<td>{html.escape(rec["time"])}</td>')
            html_parts.append(f'<td colspan="2">{html.escape(rec["team"])}</td>')
            html_parts.append(f'<td>{html.escape(rec["role"])}</td>')
            if index == 0:
                html_parts.append(f'<td rowspan="{rowspan}">{html.escape(head)}</td>')
            html_parts.append("</tr>")


def append_schedule_header_html(html_parts, venue):
    venue = html.escape(venue or "")
    html_parts.append('<tr class="leaguepost-schedule-head leaguepost-schedule-head-main">')
    html_parts.append('<th rowspan="2">日程</th><th>会場</th>')
    html_parts.append(f'<th colspan="3">{venue}</th><th rowspan="2">本部</th>')
    html_parts.append("</tr>")
    html_parts.append('<tr class="leaguepost-schedule-head leaguepost-schedule-head-sub">')
    html_parts.append('<th>開始時刻</th><th colspan="2">対戦チーム</th><th>係</th>')
    html_parts.append("</tr>")


def append_schedule_records_html(html_parts, records):
    index = 0
    current_venue = None
    while index < len(records):
        rec = records[index]
        if rec["venue"] != current_venue:
            append_schedule_header_html(html_parts, rec["venue"])
            current_venue = rec["venue"]
        end = index + 1
        while end < len(records) and records[end]["venue"] == rec["venue"] and records[end]["date"] == rec["date"]:
            end += 1
        group = records[index:end]
        head = next((r["head"] for r in group if r["head"]), "")
        rowspan = len(group)
        for offset, item in enumerate(group):
            html_parts.append("<tr>")
            if offset == 0:
                html_parts.append(f'<td rowspan="{rowspan}">{html.escape(item["date"])}</td>')
            html_parts.append(f'<td>{html.escape(item["time"])}</td>')
            html_parts.append(f'<td colspan="2">{html.escape(item["team"])}</td>')
            html_parts.append(f'<td>{html.escape(item["role"])}</td>')
            if offset == 0:
                html_parts.append(f'<td rowspan="{rowspan}">{html.escape(head)}</td>')
            html_parts.append("</tr>")
        index = end


def build_schedule_notes_html(notes):
    clean_notes = []
    seen = set()
    for note in notes:
        note = note.strip()
        if note and note not in seen:
            clean_notes.append(note)
            seen.add(note)
    if not clean_notes:
        return ""
    parts = ['<div class="leaguepost-schedule-notes">']
    parts.extend(f"<p>{html.escape(note)}</p>" for note in clean_notes)
    parts.append("</div>")
    return "\n".join(parts)


def build_schedule_excel_table_html_v2(excel_text: str, default_year=None) -> str:
    sections = split_excel_schedule_sections(excel_text)
    if not sections:
        raise ValueError("日程表Excelファイルから表を読み取れませんでした。")

    html_parts = []
    all_notes = []
    default_year = default_year or datetime.now().year
    for title, rows in sections:
        for row in rows:
            for cell in row:
                date = parse_schedule_date_cell(cell, default_year)
                if date:
                    default_year = date.year
                    break
            else:
                continue
            break
    for title, rows in sections:
        records, notes = collect_schedule_records_and_notes(rows, default_year)
        all_notes.extend(notes)
        if not records:
            continue
        if title:
            html_parts.append(f"<h3>{html.escape(title)}</h3>")
        html_parts.append('<div class="leaguepost-schedule-wrap"><table class="leaguepost-table leaguepost-schedule-table">')
        append_schedule_records_html(html_parts, records)
        html_parts.append("</table></div>")
    if not html_parts:
        return build_schedule_excel_table_html(excel_text)
    notes_html = build_schedule_notes_html(all_notes)
    if notes_html:
        html_parts.append(notes_html)
    return "\n".join(html_parts)


def build_schedule_page_body_html(year_text: str, season: str, excel_text: str, download_url: str) -> str:
    default_year = int(year_text)
    dates_by_division = collect_schedule_dates_by_division(excel_text, default_year)
    first_1 = dates_by_division["1"][0] if dates_by_division["1"] else None
    first_2 = dates_by_division["2"][0] if dates_by_division["2"] else None
    if first_1 and first_2:
        intro = f"１部は{format_jp_date(first_1)}、２部は{format_jp_date(first_2)}開幕です。"
    elif first_1:
        intro = f"１部は{format_jp_date(first_1)}開幕です。"
    elif first_2:
        intro = f"２部は{format_jp_date(first_2)}開幕です。"
    else:
        intro = "日程は以下の通りです。"

    download_html = ""
    if download_url.strip():
        url = html.escape(download_url.strip(), quote=True)
        download_html = f'<p><a href="{url}">日程表をダウンロード</a></p>'

    return f"""<div class="leaguepost-result">
{build_result_style()}
<style>
.leaguepost-schedule-wrap{{margin:12px 0 22px;}}
.leaguepost-schedule-table{{width:100%;table-layout:fixed;font-size:15px;}}
.leaguepost-schedule-table th,.leaguepost-schedule-table td{{text-align:center;vertical-align:middle;word-break:keep-all;overflow-wrap:anywhere;}}
.leaguepost-schedule-head-main th{{background:#d9ead3;color:#173a1a;font-weight:bold;}}
.leaguepost-schedule-head-sub th{{background:#d9ead3;color:#173a1a;font-weight:bold;}}
.leaguepost-schedule-table td:empty{{background:#fafafa;}}
.leaguepost-schedule-notes{{margin:4px 0 22px;font-size:14px;line-height:1.7;}}
.leaguepost-schedule-notes p{{margin:2px 0;}}
</style>
<p>{html.escape(intro)}</p>
</div>

<!--more-->

<div class="leaguepost-result">
{build_schedule_excel_table_html_v2(excel_text, default_year)}
{download_html}
</div>
"""


def build_txt(items):
    lines = []
    for it in items:
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"タイトル：{it.title}",
            f"試合日：{getattr(it, 'game_date', datetime.now()).strftime('%Y/%m/%d')}",
            f"予約入力：年={it.pub_year} 月={it.pub_month} 日={it.pub_day} 時={it.pub_hour} 分={it.pub_minute}",
            f"カテゴリー候補：{'、'.join(it.categories)}",
            f"大会コード：{post_tournament_id(it)}",
            "",
            "本文HTML：",
            post_body_html(it),
            "",
        ]
    return "\n".join(lines)


def build_single_preview_html(item):
    body = post_body_html(item).replace("<!--more-->", '<div class="more">続きを読む</div>')
    return "\n".join([
        "<!doctype html>",
        '<html lang="ja">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{html.escape(item.title)}</title>",
        "<style>",
        build_result_style(),
        'body{font-family:"Meiryo UI",sans-serif;font-size:18px;line-height:1.8;margin:20px;background:#fff;color:#111;}',
        'article{max-width:920px;margin:0 auto;}',
        '.more{text-align:center;color:#666;border-top:2px dashed #aaa;border-bottom:2px dashed #aaa;padding:8px;margin:18px 0;}',
        "</style>",
        "</head>",
        "<body>",
        "<article>",
        f"<h1>{html.escape(item.title)}</h1>",
        body,
        "</article>",
        "</body>",
        "</html>",
    ])


def build_preview_html(items):
    parts = [
        "<!doctype html>",
        '<html lang="ja">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>LeaguePost 投稿原稿一覧</title>",
        "<style>",
        'body{font-family:"Meiryo UI",sans-serif;font-size:16px;line-height:1.7;margin:24px;}',
        "article{border:2px solid #999;border-radius:12px;padding:18px;margin-bottom:24px;}",
        "pre{white-space:pre-wrap;background:#f5f5f5;padding:14px;border-radius:8px;}",
        ".more{text-align:center;color:#666;border-top:2px dashed #aaa;border-bottom:2px dashed #aaa;padding:8px;margin:16px 0;}",
        "</style>",
        "</head>",
        "<body>",
        "<h1>LeaguePost 投稿原稿一覧</h1>",
    ]
    for it in items:
        body = post_body_html(it)
        parts += [
            "<article>",
            f"<h2>{html.escape(it.title)}</h2>",
            f"<p><b>予約入力：</b>年={it.pub_year} 月={it.pub_month} 日={it.pub_day} 時={it.pub_hour} 分={it.pub_minute}</p>",
            f"<p><b>カテゴリー候補：</b>{html.escape('、'.join(it.categories))}</p>",
            f"<p><b>大会コード：</b>{html.escape(post_tournament_id(it))}</p>",
            "<p>速報・詳細は一球速報サイトをご覧ください</p>",
            '<div class="more">続きを読む</div>',
            "<h3>WordPress貼り付け用HTML</h3>",
            f"<pre>{html.escape(body)}</pre>",
            "</article>",
        ]

    parts += ["</body>", "</html>"]
    return "\n".join(parts)



def build_wp_custom_html_block(body_html: str) -> str:
    """Gutenberg に貼り付けやすいカスタムHTMLブロック形式へ整形します。"""
    body_html = body_html.strip()
    return f"<!-- wp:html -->\n{body_html}\n<!-- /wp:html -->"




def build_wp_full_paste_text(title: str, body_html: str) -> str:
    """
    WordPress Gutenberg のタイトル欄に1回貼り付けるための形式。
    1行目をタイトル、空行後を本文ブロックとして解釈させる。
    """
    title = (title or "").strip()
    body_block = build_wp_custom_html_block(body_html)
    return f"{title}\n\n{body_block}"




def build_extension_payload(item: PostItem) -> str:
    """Chrome拡張機能に渡すためのJSON文字列を作ります。"""
    payload = {
        "type": "LEAGUEPOST_WP_PAYLOAD_V1",
        "title": item.title,
        "content": build_wp_custom_html_block(post_body_html(item)),
        "raw_body_html": post_body_html(item),
        "categories": item.categories,
        "publish": {
            "year": item.pub_year,
            "month": item.pub_month,
            "day": item.pub_day,
            "hour": item.pub_hour,
            "minute": item.pub_minute,
        },
        "meta": {
            "game_date": getattr(item, "game_date", datetime.now()).strftime("%Y/%m/%d"),
            "cup_id": getattr(item, "cup_id", ""),
            "tournament_id": post_tournament_id(item),
        },
    }
    return "LEAGUEPOST_WP_PAYLOAD_V1\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def safe_import_pyautogui():
    try:
        import pyautogui  # type: ignore
        return pyautogui
    except Exception:
        return None



def safe_import_selenium():
    try:
        from selenium import webdriver  # type: ignore
        from selenium.webdriver.chrome.options import Options as ChromeOptions  # type: ignore
        from selenium.webdriver.chrome.service import Service as ChromeService  # type: ignore
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
        return webdriver, ChromeOptions, ChromeService, WebDriverWait
    except Exception:
        return None


def safe_import_webdriver_manager():
    try:
        from webdriver_manager.chrome import ChromeDriverManager  # type: ignore
        return ChromeDriverManager
    except Exception:
        return None


def safe_import_tkinterweb():
    try:
        from tkinterweb import HtmlFrame  # type: ignore
        return HtmlFrame
    except Exception:
        return None


def build_wp_block_for_selenium(body_html: str) -> str:
    return build_wp_custom_html_block(body_html)

def load_config():
    for path in (CONFIG_FILE, BASE_LEGACY_CONFIG_FILE, LEGACY_CONFIG_FILE):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logging.exception("Failed to load config: %s", path)
                return {}
    return {}


def save_config(data):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class VerticalScrolledFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window_id, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def scroll_to_widget(self, widget, margin=8):
        try:
            self.update_idletasks()
            self.canvas.update_idletasks()
            widget.update_idletasks()
            scrollregion = self.canvas.bbox("all")
            if not scrollregion:
                return
            total_height = max(1, scrollregion[3] - scrollregion[1])
            target_y = max(0, widget.winfo_y() - margin)
            self.canvas.yview_moveto(target_y / total_height)
        except Exception:
            pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("980x740")
        self.minsize(820, 600)
        try:
            self.state("zoomed")
        except Exception:
            pass

        self.config_data = load_config()
        self.base_font_size = int(self.config_data.get("font_size", 18))
        self.items = []
        self.current_index = 0
        self.posted_flags = []
        self.wp_driver = None
        self._last_autofilled_dates_text = ""
        self._last_auto_tournament_id = ""

        self._setup_fonts()
        self._build_ui()
        self._load_defaults()
        self.after(100, self.maximize_window)
        self.after(600, self.maximize_window)

    def maximize_window(self):
        try:
            self.state("zoomed")
        except Exception:
            pass

    def _setup_fonts(self):
        self.font_normal = tkfont.Font(family="Meiryo UI", size=self.base_font_size)
        self.font_bold = tkfont.Font(family="Meiryo UI", size=self.base_font_size, weight="bold")
        self.font_title = tkfont.Font(family="Meiryo UI", size=self.base_font_size + 6, weight="bold")
        self.option_add("*Font", self.font_normal)

    def _build_ui(self):
        style = ttk.Style()
        style.configure("TLabel", font=self.font_bold)
        style.configure("TButton", font=self.font_bold, padding=6)
        style.configure("TEntry", font=self.font_normal)
        style.configure("TCombobox", font=self.font_normal)
        style.configure("Tile.TButton", font=self.font_title, padding=(14, 14))
        style.configure("TileSelected.TButton", font=self.font_title, padding=(14, 14), relief="sunken")

        scrolled = VerticalScrolledFrame(self)
        self.scrolled = scrolled
        scrolled.pack(fill="both", expand=True)
        root = scrolled.inner
        root.columnconfigure(1, weight=1)
        self.post_type_var = tk.StringVar(value=POST_TYPE_RESULT)
        self.tile_buttons = {}

        r = 0
        ttk.Label(root, text="LeagueSuite for WordPress", font=self.font_title).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=(12, 2))
        r += 1
        ttk.Label(root, text=f"LeaguePost v{APP_VERSION}").grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))

        r += 1
        menu = ttk.LabelFrame(root, text="メニュー")
        menu.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        for i, post_type in enumerate(POST_TYPES):
            menu.columnconfigure(i, weight=1)
            btn = ttk.Button(
                menu,
                text=post_type,
                command=lambda value=post_type: self.select_post_type(value),
                style="Tile.TButton",
            )
            btn.grid(row=0, column=i, sticky="ew", padx=5, pady=8)
            self.tile_buttons[post_type] = btn
        self.update_post_type_tiles()

        r += 1
        top = ttk.Frame(root)
        top.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        ttk.Button(top, text="大会名・大会IDを生成", command=self.auto_fill_tournament).pack(side="left", padx=3)
        ttk.Button(top, text="原稿生成", command=self.generate).pack(side="left", padx=3)
        ttk.Button(top, text="設定保存", command=self.save_settings).pack(side="left", padx=3)

        r += 1
        ttk.Label(root, text="文字サイズ").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.font_size_var = tk.StringVar(value=str(self.base_font_size))
        ttk.Combobox(root, textvariable=self.font_size_var, values=["12", "14", "16", "18", "20", "24"], width=8, state="readonly").grid(row=r, column=1, sticky="w", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="作成年度").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        now_year = datetime.now().year
        self.year_var = tk.StringVar(value=str(now_year))
        ttk.Combobox(root, textvariable=self.year_var, values=[str(y) for y in range(now_year - 1, now_year + 4)], width=12).grid(row=r, column=1, sticky="w", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="季節").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.season_var = tk.StringVar(value="春季")
        ttk.Combobox(root, textvariable=self.season_var, values=["春季", "秋季"], width=12, state="readonly").grid(row=r, column=1, sticky="w", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="区分").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.division_var = tk.StringVar(value="１部")
        ttk.Combobox(root, textvariable=self.division_var, values=["１部", "２部", "入替戦"], width=12, state="readonly").grid(row=r, column=1, sticky="w", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="投稿種別").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.post_type_combo = ttk.Combobox(root, textvariable=self.post_type_var, values=POST_TYPES, width=18, state="readonly")
        self.post_type_combo.grid(row=r, column=1, sticky="w", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="大会選択/直接入力").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.league_var = tk.StringVar()
        self.league_combo = ttk.Combobox(root, textvariable=self.league_var, values=[], width=52)
        self.league_combo.grid(row=r, column=1, sticky="ew", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="cupId\n※保存しません").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.cup_id_var = tk.StringVar()
        ttk.Entry(root, textvariable=self.cup_id_var).grid(row=r, column=1, sticky="ew", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="大会ID選択/直接入力\n例：2026haru01").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.tournament_id_var = tk.StringVar()
        self.tournament_combo = ttk.Combobox(root, textvariable=self.tournament_id_var, values=[], width=32)
        self.tournament_combo.grid(row=r, column=1, sticky="w", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="WordPress新規投稿URL\n例：https://example.com/wp-admin/post-new.php").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.wp_new_post_url_var = tk.StringVar()
        ttk.Entry(root, textvariable=self.wp_new_post_url_var).grid(row=r, column=1, sticky="ew", padx=12, pady=4)

        r += 1
        self.normalized_id_var = tk.StringVar()
        ttk.Label(root, text="実際に使用する大会コード").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        ttk.Entry(root, textvariable=self.normalized_id_var, state="readonly", width=32).grid(row=r, column=1, sticky="w", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="試合日一覧\n1行に1日\n例：4/12 も可").grid(row=r, column=0, sticky="nw", padx=12, pady=4)
        self.dates_text = tk.Text(root, height=6, font=self.font_normal, undo=True)
        self.dates_text.grid(row=r, column=1, sticky="ew", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="公式記録員LINE本文\n※順位・個人賞用").grid(row=r, column=0, sticky="nw", padx=12, pady=4)
        self.result_text = tk.Text(root, height=14, font=self.font_normal, wrap="word", undo=True)
        self.result_text.grid(row=r, column=1, sticky="ew", padx=12, pady=4)

        r += 1
        ttk.Label(root, text="日程表Excelファイル\n※日程ページ用").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        schedule_file_frame = ttk.Frame(root)
        schedule_file_frame.grid(row=r, column=1, sticky="ew", padx=12, pady=4)
        schedule_file_frame.columnconfigure(0, weight=1)
        self.schedule_excel_file_var = tk.StringVar()
        ttk.Entry(schedule_file_frame, textvariable=self.schedule_excel_file_var, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(schedule_file_frame, text="Excelファイルを選択", command=self.select_schedule_excel_file).grid(row=0, column=1, sticky="e")

        r += 1
        ttk.Label(root, text="日程表ダウンロードリンク\n※任意").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.schedule_download_url_var = tk.StringVar()
        ttk.Entry(root, textvariable=self.schedule_download_url_var).grid(row=r, column=1, sticky="ew", padx=12, pady=4)

        r += 1
        ttk.Separator(root).grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=10)

        r += 1
        self.counter_label = ttk.Label(root, text="記事未生成", font=self.font_title)
        self.counter_label.grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4)

        r += 1
        self.progress_label = ttk.Label(root, text="")
        self.progress_label.grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=2)

        r += 1
        copy = ttk.LabelFrame(root, text="コピー・WordPress貼り付け支援")
        copy.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=6)
        self.title_copy_button = ttk.Button(copy, text="タイトルをコピー", command=self.copy_title)
        self.body_copy_button = ttk.Button(copy, text="本文HTMLをコピー", command=self.copy_body)
        self.wp_block_copy_button = ttk.Button(copy, text="本文HTMLブロックをコピー", command=self.copy_wp_custom_html_block)
        self.open_wp_button = ttk.Button(copy, text="通常Chromeで新規投稿を開く", command=self.open_wordpress_new_post)
        self.extension_copy_button = ttk.Button(copy, text="拡張機能用データをコピー", command=self.copy_extension_payload)
        self.prev_button = ttk.Button(copy, text="◀ 前", command=self.prev_item)
        self.next_button = ttk.Button(copy, text="次 ▶", command=self.next_item)
        self.mark_posted_button = ttk.Button(copy, text="投稿済みにして次へ", command=self.mark_posted)
        self.open_wp_button.pack(side="left", padx=4, pady=6)
        self.extension_copy_button.pack(side="left", padx=4, pady=6)
        self.title_copy_button.pack(side="left", padx=4, pady=6)
        self.wp_block_copy_button.pack(side="left", padx=4, pady=6)
        self.prev_button.pack(side="left", padx=4, pady=6)
        self.next_button.pack(side="left", padx=4, pady=6)
        self.mark_posted_button.pack(side="left", padx=4, pady=6)

        r += 1
        ttk.Label(root, text="タイトル").grid(row=r, column=0, sticky="w", padx=12, pady=4)
        self.title_var = tk.StringVar()
        ttk.Entry(root, textvariable=self.title_var).grid(row=r, column=1, sticky="ew", padx=12, pady=4)

        r += 1
        guide = ttk.LabelFrame(root, text="予約日時入力ガイド（WordPressで選択・入力）")
        guide.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=6)
        self.pub_year_var = tk.StringVar()
        self.month_var = tk.StringVar()
        self.day_var = tk.StringVar()
        self.hour_var = tk.StringVar()
        self.minute_var = tk.StringVar()
        for i, (label, var) in enumerate([("年", self.pub_year_var), ("月", self.month_var), ("日", self.day_var), ("時", self.hour_var), ("分", self.minute_var)]):
            ttk.Label(guide, text=label).grid(row=0, column=i * 2, padx=4, pady=6)
            ttk.Entry(guide, textvariable=var, width=8, justify="center").grid(row=0, column=i * 2 + 1, padx=4, pady=6)

        r += 1
        cat = ttk.LabelFrame(root, text="カテゴリー候補（WordPressでチェック）")
        cat.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=6)
        self.categories_var = tk.StringVar()
        ttk.Entry(cat, textvariable=self.categories_var).pack(fill="x", padx=8, pady=8)

        r += 1
        ttk.Label(root, text="本文HTML（HTML/コード表示に貼り付け）").grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4)

        r += 1
        self.body_text = tk.Text(root, height=14, font=self.font_normal, wrap="word")
        self.body_text.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=4)

        r += 1
        export = ttk.LabelFrame(root, text="出力")
        export.grid(row=r, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        ttk.Button(export, text="TXT出力", command=self.export_txt).pack(side="left", padx=4, pady=6)
        ttk.Button(export, text="CSV出力", command=self.export_csv).pack(side="left", padx=4, pady=6)
        ttk.Button(export, text="HTML出力", command=self.export_html).pack(side="left", padx=4, pady=6)

        r += 1
        note = (
            "※『ログイン画面を開く』でWordPressログイン画面を表示し、必ず手入力でログインしてください。ログイン後、新規投稿画面に移動してから『WPへ自動入力』を押します。\n"
            "※『WPへ自動入力』はログイン画面のID/パスワード入力は行わず、ログイン済み投稿画面にタイトルと本文HTMLブロックを直接入力します。\n"
            "※公開ボタンは自動で押しません。内容確認後、下書き保存・予約・公開は手動で行ってください。\n"
            "※大会IDは 2026haru01 のように入力すれば、本文では 57-2026haru01 として使います。\n"
            "※本文HTMLには <!--more--> を含みます。"
        )
        ttk.Label(root, text=note).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=12)

        for var in (self.year_var, self.season_var, self.division_var, self.tournament_id_var):
            var.trace_add("write", self._on_tournament_fields_changed)
        self.post_type_var.trace_add("write", self._on_post_type_changed)

    def select_post_type(self, post_type: str):
        self.post_type_var.set(post_type)

    def _on_post_type_changed(self, *args):
        self.update_post_type_tiles()
        self.apply_remembered_schedule_dates()

    def select_schedule_excel_file(self):
        file = filedialog.askopenfilename(
            title="日程表Excelファイルを選択",
            filetypes=[
                ("Excel files", "*.xlsx *.xlsm"),
                ("All files", "*.*"),
            ],
        )
        if not file:
            return
        self.schedule_excel_file_var.set(app_path_text(file))
        try:
            excel_text = load_xlsx_schedule_text(file)
            self.remember_schedule_dates_from_excel(excel_text)
            messagebox.showinfo(APP_NAME, "日程表Excelファイルを読み込みました。")
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def update_post_type_tiles(self):
        current = self.post_type_var.get()
        for post_type, button in getattr(self, "tile_buttons", {}).items():
            button.configure(style="TileSelected.TButton" if post_type == current else "Tile.TButton")

    def _load_defaults(self):
        self.font_size_var.set(str(self.base_font_size))
        self.year_var.set(self.config_data.get("year", str(datetime.now().year)))
        self.season_var.set(self.config_data.get("season", "春季"))
        self.division_var.set(self.config_data.get("division", "１部"))
        self.league_var.set(self.config_data.get("league_name", ""))
        initial_auto_id = make_tournament_id(self.year_var.get().strip(), self.season_var.get(), self.division_var.get())
        self.tournament_id_var.set(initial_auto_id)
        self._last_auto_tournament_id = initial_auto_id
        self.wp_new_post_url_var.set(self.config_data.get("wp_new_post_url", "https://chugoku.junko.or.jp/wp-admin/post-new.php"))
        self.dates_text.insert("1.0", self.config_data.get("dates", "4/5\n4/12\n4/19\n5/3"))
        if hasattr(self, "result_text"):
            self.result_text.insert("1.0", self.config_data.get("result_text", ""))
        if hasattr(self, "schedule_excel_file_var"):
            self.schedule_excel_file_var.set(self.config_data.get("schedule_excel_file", ""))
        if hasattr(self, "schedule_download_url_var"):
            self.schedule_download_url_var.set(self.config_data.get("schedule_download_url", ""))
        if hasattr(self, "post_type_var"):
            self.post_type_var.set(normalize_post_type(self.config_data.get("post_type", POST_TYPE_RESULT)))
        self.refresh_candidates()
        if not self.league_var.get().strip() or not self.tournament_id_var.get().strip():
            self.auto_fill_tournament(show_message=False)
        self.update_normalized_id()

    def safe_action(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, f"エラーが発生しました。\n\n{e}\n\nログ: {LOG_FILE}")
            return None

    def refresh_candidates(self):
        year = self.year_var.get().strip()
        names = []
        ids = []
        for season in ["春季", "秋季"]:
            for division in ["１部", "２部", "入替戦"]:
                names.append(make_league_name(year, season, division))
                ids.append(make_tournament_id(year, season, division))
        self.league_combo["values"] = names
        self.tournament_combo["values"] = ids

    def _on_tournament_fields_changed(self, *args):
        self.refresh_candidates()
        self.update_normalized_id()
        self.apply_remembered_schedule_dates()

    def remembered_schedule_dates_text(self):
        key = normalize_division_key(self.division_var.get())
        return self.config_data.get(f"schedule_dates_{key}", "").strip()

    def apply_remembered_schedule_dates(self, force=False):
        if not force and normalize_post_type(self.post_type_var.get()) != POST_TYPE_RESULT:
            return
        remembered = self.remembered_schedule_dates_text()
        if not remembered:
            return
        current = self.dates_text.get("1.0", "end").strip()
        if not force and current and current != self._last_autofilled_dates_text:
            return
        self.dates_text.delete("1.0", "end")
        self.dates_text.insert("1.0", remembered)
        self._last_autofilled_dates_text = remembered

    def remember_schedule_dates_from_excel(self, excel_text: str):
        default_year = int(self.year_var.get().strip())
        dates_by_division = collect_schedule_dates_by_division(excel_text, default_year)
        if dates_by_division["1"]:
            self.config_data["schedule_dates_1"] = dates_to_text(dates_by_division["1"])
        if dates_by_division["2"]:
            self.config_data["schedule_dates_2"] = dates_to_text(dates_by_division["2"])
        if dates_by_division["3"]:
            self.config_data["schedule_dates_3"] = dates_to_text(dates_by_division["3"])
        return dates_by_division

    def auto_fill_tournament(self, show_message=True):
        year = self.year_var.get().strip()
        season = self.season_var.get()
        division = self.division_var.get()
        self.league_var.set(make_league_name(year, season, division))
        new_tournament_id = make_tournament_id(year, season, division)
        current_tournament_id = self.tournament_id_var.get().strip()
        if not current_tournament_id or current_tournament_id == self._last_auto_tournament_id:
            self.tournament_id_var.set(new_tournament_id)
            self._last_auto_tournament_id = new_tournament_id
        self.update_normalized_id()
        if show_message:
            messagebox.showinfo(APP_NAME, "大会名と大会IDを生成しました。")

    def update_normalized_id(self):
        self.normalized_id_var.set(normalize_tournament_id(self.tournament_id_var.get()))

    def get_items(self):
        league = self.league_var.get().strip()
        cup = self.cup_id_var.get().strip()
        tournament_id = self.tournament_id_var.get().strip()

        if not league:
            raise ValueError("大会名を入力してください。")
        if not cup:
            raise ValueError("cupIdを入力してください。")
        if not tournament_id:
            raise ValueError("大会IDを入力してください。")

        default_year = int(self.year_var.get().strip())
        dates = parse_dates_with_default_year(self.dates_text.get("1.0", "end"), default_year)
        if not dates:
            raise ValueError("試合日を入力してください。")

        return [PostItem(i + 1, len(dates), d, league, cup, tournament_id) for i, d in enumerate(dates)]

    def save_settings(self):
        data = {
            "font_size": self.font_size_var.get(),
            "year": self.year_var.get().strip(),
            "season": self.season_var.get(),
            "division": self.division_var.get(),
            "league_name": self.league_var.get().strip(),
            "wp_new_post_url": self.wp_new_post_url_var.get().strip(),
            "dates": self.dates_text.get("1.0", "end").strip(),
            "post_type": self.post_type_var.get(),
            "result_text": self.result_text.get("1.0", "end").strip(),
            "schedule_excel_file": stored_app_path_text(self.schedule_excel_file_var.get()),
            "schedule_title": self.schedule_title_var.get().strip(),
            "schedule_download_url": self.schedule_download_url_var.get().strip(),
            "roster_mode": self.roster_mode_var.get() if hasattr(self, "roster_mode_var") else self.config_data.get("roster_mode", "all"),
            "roster_input_folder": stored_app_path_text(self.roster_input_folder_var.get()) if hasattr(self, "roster_input_folder_var") else self.config_data.get("roster_input_folder", ""),
            "roster_single_file": stored_app_path_text(self.roster_single_file_var.get()) if hasattr(self, "roster_single_file_var") else self.config_data.get("roster_single_file", ""),
            "roster_output_file": stored_app_path_text(self.roster_output_file_var.get()) if hasattr(self, "roster_output_file_var") else self.config_data.get("roster_output_file", ""),
            "roster_overwrite": bool(self.roster_overwrite_var.get()) if hasattr(self, "roster_overwrite_var") else bool(self.config_data.get("roster_overwrite", True)),
            "schedule_dates_1": self.config_data.get("schedule_dates_1", ""),
            "schedule_dates_2": self.config_data.get("schedule_dates_2", ""),
            "schedule_dates_3": self.config_data.get("schedule_dates_3", ""),
        }
        self.config_data.update(data)
        save_config(self.config_data)
        messagebox.showinfo(APP_NAME, "設定を保存しました。\ncupIdは保存していません。")

    def generate(self):
        try:
            self.update_normalized_id()
            post_type = normalize_post_type(self.post_type_var.get())
            self.post_type_var.set(post_type)
            if self.division_var.get() == "２部" and post_type not in (POST_TYPE_STANDINGS, POST_TYPE_SCHEDULE):
                raise ValueError("２部は『順位＆星取表』と『日程』のみ対応です。メニューを選び直してください。")
            if post_type == POST_TYPE_RESULT:
                self.items = self.get_items()
            else:
                league = self.league_var.get().strip()
                tournament_id = self.tournament_id_var.get().strip()
                if not league:
                    raise ValueError("大会名を入力してください。")
                if not tournament_id:
                    raise ValueError("大会IDを入力してください。")
                line_text = self.result_text.get("1.0", "end").strip()
                if post_type != POST_TYPE_SCHEDULE and not line_text:
                    raise ValueError("公式記録員LINE本文を貼り付けてください。")
                now_pub = datetime.now()
                if post_type == POST_TYPE_STANDINGS:
                    body = build_standings_body_html(league, tournament_id, line_text)
                    title = f"{league}　順位＆星取表"
                elif post_type == POST_TYPE_AWARDS:
                    body = build_awards_body_html(league, tournament_id, line_text)
                    title = f"{league}　個人賞"
                elif post_type == POST_TYPE_SCHEDULE:
                    excel_file = self.schedule_excel_file_var.get().strip()
                    if not excel_file:
                        raise ValueError("日程表Excelファイルを選択してください。")
                    excel_path = app_path(excel_file)
                    if not excel_path or not excel_path.exists():
                        raise ValueError("日程表Excelファイルが見つかりません。")
                    excel_text = load_xlsx_schedule_text(str(excel_path))
                    self.remember_schedule_dates_from_excel(excel_text)
                    self.apply_remembered_schedule_dates(force=True)
                    self.config_data["schedule_excel_file"] = stored_app_path_text(excel_file)
                    self.config_data["schedule_download_url"] = self.schedule_download_url_var.get().strip()
                    save_config(self.config_data)
                    body = build_schedule_page_body_html(
                        self.year_var.get().strip(),
                        self.season_var.get(),
                        excel_text,
                        self.schedule_download_url_var.get().strip(),
                    )
                    title = make_schedule_title(self.year_var.get().strip(), self.season_var.get())
                else:
                    raise ValueError(f"未対応の投稿種別です: {post_type}")
                self.items = [ResultPostItem(1, 1, title, body, guess_categories(league), now_pub, post_type)]
            self.posted_flags = [False] * len(self.items)
            self.current_index = 0
            self.show_current()
            self.scroll_to_article_area()
            logging.info("Generated %s posts", len(self.items))
            messagebox.showinfo(APP_NAME, f"{len(self.items)}件の記事原稿を生成しました。")
            self.after(50, self.scroll_to_article_area)
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def current_item(self):
        return self.items[self.current_index] if self.items else None

    def show_current(self):
        it = self.current_item()
        if not it:
            return

        posted = "投稿済" if self.posted_flags and self.posted_flags[self.current_index] else "未投稿"
        self.counter_label.config(text=f"現在の記事　【{self.current_index + 1} / {len(self.items)}】　{posted}")

        done = sum(1 for x in self.posted_flags if x)
        self.progress_label.config(text=f"進捗：{done} / {len(self.items)} 件投稿済")

        self.title_var.set(it.title)
        self.pub_year_var.set(it.pub_year)
        self.month_var.set(it.pub_month)
        self.day_var.set(it.pub_day)
        self.hour_var.set(it.pub_hour)
        self.minute_var.set(it.pub_minute)
        self.categories_var.set("、".join(it.categories))

        self.body_text.delete("1.0", "end")
        self.body_text.insert("end", post_body_html(it))

        self.title_copy_button.config(text="① タイトルをコピー")
        self.body_copy_button.config(text="② 本文HTMLをコピー")
        self.wp_block_copy_button.config(text="② 本文HTMLブロックをコピー")
        self.extension_copy_button.config(text="拡張機能用データをコピー")

    def scroll_to_article_area(self):
        if hasattr(self, "scrolled") and hasattr(self, "counter_label"):
            self.scrolled.scroll_to_widget(self.counter_label, margin=12)

    def prev_item(self):
        if not self.items:
            self.generate()
            return
        self.current_index = max(0, self.current_index - 1)
        self.show_current()

    def next_item(self):
        if not self.items:
            self.generate()
            return
        self.current_index = min(len(self.items) - 1, self.current_index + 1)
        self.show_current()

    def mark_posted(self):
        if not self.items:
            self.generate()
            return

        self.posted_flags[self.current_index] = True
        if self.current_index < len(self.items) - 1:
            self.current_index += 1
            self.show_current()
        else:
            self.show_current()
            messagebox.showinfo(APP_NAME, "全記事の確認が終了しました。\nお疲れ様でした。")

    def set_clipboard_text(self, value: str) -> bool:
        """Tk標準を優先し、失敗時はWindows標準のSet-Clipboardへフォールバック。"""
        value = value or ""
        try:
            self.clipboard_clear()
            self.clipboard_append(value)
            self.update_idletasks()
            try:
                copied = self.clipboard_get()
                if copied == value:
                    return True
            except Exception:
                # clipboard_get が環境によって失敗しても、append自体は成功している場合がある
                return True
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Set-Clipboard"],
                input=value,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception:
            return False

    def copy_to_clipboard(self, value, label):
        ok = self.set_clipboard_text(value)
        if ok:
            messagebox.showinfo(APP_NAME, f"{label}をコピーしました。")
        else:
            messagebox.showerror(APP_NAME, f"{label}のコピーに失敗しました。\n個別のタイトルコピー／本文コピーも試してください。")

    def copy_title(self):
        it = self.current_item()
        if it:
            self.copy_to_clipboard(it.title, "タイトル")
            self.title_copy_button.config(text="✔ タイトルコピー済")

    def copy_body(self):
        it = self.current_item()
        if it:
            self.copy_to_clipboard(post_body_html(it), "本文HTML")
            self.body_copy_button.config(text="✔ 本文HTMLコピー済")

    def copy_wp_custom_html_block(self):
        it = self.current_item()
        if it:
            value = build_wp_custom_html_block(post_body_html(it))
            self.copy_to_clipboard(value, "本文HTMLブロック")
            self.wp_block_copy_button.config(text="✔ 本文HTMLブロックコピー済")

    def copy_extension_payload(self):
        it = self.current_item()
        if it:
            value = build_extension_payload(it)
            self.copy_to_clipboard(value, "Chrome拡張機能用データ")
            self.extension_copy_button.config(text="✔ 拡張機能用データコピー済")

    def open_wordpress_new_post(self):
        url = self.wp_new_post_url_var.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "WordPress新規投稿URLを入力してください。")
            return
        webbrowser.open(url)

    def _wp_login_url(self, new_post_url: str) -> str:
        """新規投稿URLからログイン画面URLを作る。
        post-new.php へ直接アクセスせず、ログイン画面から手入力ログインしてもらうため。
        """
        from urllib.parse import urlparse, quote
        parsed = urlparse(new_post_url)
        if not parsed.scheme or not parsed.netloc:
            return new_post_url
        base = f"{parsed.scheme}://{parsed.netloc}"
        redirect = quote(new_post_url, safe="")
        return f"{base}/wp-login.php?redirect_to={redirect}&reauth=1"

    def _get_wp_driver(self):
        selenium_pack = safe_import_selenium()
        if selenium_pack is None:
            raise RuntimeError(
                "Selenium がインストールされていません。\n\n"
                "コマンドプロンプトで次を実行してください。\n"
                "pip install selenium"
            )

        webdriver, ChromeOptions, ChromeService, WebDriverWait = selenium_pack

        if self.wp_driver is not None:
            try:
                handles = list(self.wp_driver.window_handles)
                if handles:
                    try:
                        current = self.wp_driver.current_window_handle
                    except Exception:
                        current = None
                    if current not in handles:
                        self.wp_driver.switch_to.window(handles[-1])
                    _ = self.wp_driver.current_url
                    return self.wp_driver, WebDriverWait
            except Exception:
                self.wp_driver = None

        SELENIUM_PROFILE_DIR.mkdir(exist_ok=True)
        profile = str(SELENIUM_PROFILE_DIR)

        last_error = None

        def chrome_options():
            options = ChromeOptions()
            options.add_argument(f"--user-data-dir={profile}")
            options.add_argument("--profile-directory=Default")
            options.add_argument("--start-maximized")
            options.add_argument("--remote-debugging-port=9222")
            options.add_experimental_option("detach", True)
            return options

        # 1) Selenium Manager をまず使用（Chrome専用）
        try:
            self.wp_driver = webdriver.Chrome(options=chrome_options())
            return self.wp_driver, WebDriverWait
        except Exception as e:
            last_error = e

        try:
            attach_options = ChromeOptions()
            attach_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
            self.wp_driver = webdriver.Chrome(options=attach_options)
            return self.wp_driver, WebDriverWait
        except Exception as e:
            last_error = f"{last_error} / attach existing Chrome: {e}"

        # 2) EXE環境で Selenium Manager が同梱されない場合に備え、webdriver-manager で取得
        manager_pack = safe_import_webdriver_manager()
        if manager_pack is not None:
            ChromeDriverManager = manager_pack
            try:
                service = ChromeService(ChromeDriverManager().install())
                self.wp_driver = webdriver.Chrome(service=service, options=chrome_options())
                return self.wp_driver, WebDriverWait
            except Exception as e:
                last_error = f"{last_error} / ChromeDriverManager: {e}"

        raise RuntimeError(
            "Chrome のSelenium起動に失敗しました。\n\n"
            "この版は Chrome 専用です。Edge は起動しません。\n"
            "まず Google Chrome がインストールされているか確認してください。\n"
            "次に Builder.py でEXEを作り直してください。\n\n"
            "それでも失敗する場合は、職場ネットワーク等で ChromeDriver の取得がブロックされている可能性があります。\n"
            "その場合は Chrome を最新版へ更新してください。\n\n"
            f"詳細: {last_error}"
        )

    def open_wp_selenium_browser(self):
        """WordPressログイン画面を開く。
        ロックアウト回避のため、新規投稿URLへ直接アクセスせず、
        ユーザーが手入力でログインできる画面を先に表示する。
        """
        try:
            url = self.wp_new_post_url_var.get().strip()
            if not url:
                raise ValueError("WordPress新規投稿URLを入力してください。")
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError("URLは http:// または https:// から入力してください。")

            login_url = self._wp_login_url(url)
            driver, _ = self._get_wp_driver()
            driver.get(login_url)
            messagebox.showinfo(
                APP_NAME,
                "WordPressログイン画面を開きました。\n\n"
                "ブラウザでID・パスワードを手入力してログインしてください。\n"
                "ログイン後、新規投稿画面が表示されたら、\n"
                "アプリに戻って『WPへ自動入力』を押してください。\n\n"
                "※このボタンはログイン操作を自動化しません。"
            )
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def auto_input_wordpress(self):
        try:
            it = self.current_item()
            if it is None:
                self.generate()
                it = self.current_item()
                if it is None:
                    return

            url = self.wp_new_post_url_var.get().strip()
            if not url:
                raise ValueError("WordPress新規投稿URLを入力してください。")
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError("URLは http:// または https:// から入力してください。")

            driver, WebDriverWait = self._get_wp_driver()

            # ロックアウト回避のため、ここでは無条件に新規投稿URLへ飛ばない。
            # まず現在開いているページが投稿編集画面かを確認する。
            try:
                has_wp_now = driver.execute_script("return !!(window.wp && wp.data && wp.data.dispatch && wp.data.select);")
            except Exception:
                has_wp_now = False

            if not has_wp_now:
                if not messagebox.askyesno(
                    APP_NAME,
                    "現在のブラウザがWordPress投稿編集画面ではありません。\n\n"
                    "手入力ログインが完了している場合のみ、新規投稿画面へ移動します。\n"
                    "移動してよろしいですか？"
                ):
                    return
                driver.get(url)

            title = it.title
            content = build_wp_block_for_selenium(post_body_html(it))

            wait = WebDriverWait(driver, 60)
            try:
                wait.until(lambda d: d.execute_script(
                    "return !!(window.wp && wp.data && wp.data.dispatch && wp.data.select);"
                ))
            except Exception:
                raise RuntimeError(
                    "WordPress投稿編集画面を確認できませんでした。\n\n"
                    "ログイン画面が表示されている場合は、開いたブラウザで手動ログインしてから、\n"
                    "もう一度『WPへ自動入力』を押してください。"
                )

            script = r"""
const title = arguments[0];
const content = arguments[1];
let result = {ok:false, message:""};
try {
  if (!(window.wp && wp.data && wp.data.dispatch)) {
    result.message = "wp.data が見つかりません";
    return result;
  }

  const editorDispatch = wp.data.dispatch('core/editor');
  if (!editorDispatch || !editorDispatch.editPost) {
    result.message = "core/editor.editPost が見つかりません";
    return result;
  }

  editorDispatch.editPost({ title: title });

  // Gutenbergのブロックとして本文を反映。失敗時はeditPost(content)へフォールバック。
  let blockOk = false;
  try {
    if (wp.blocks && wp.blocks.parse && wp.data.dispatch('core/block-editor')) {
      const blocks = wp.blocks.parse(content);
      wp.data.dispatch('core/block-editor').resetBlocks(blocks);
      blockOk = true;
    }
  } catch (e) {
    blockOk = false;
  }

  if (!blockOk) {
    editorDispatch.editPost({ content: content });
  }

  // 念のため、タイトルDOMが存在する場合も同期。
  try {
    const selectors = [
      'textarea.editor-post-title__input',
      'input.editor-post-title__input',
      'h1[contenteditable="true"]',
      '[aria-label="タイトルを追加"]',
      '[aria-label="Add title"]'
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) {
        if ('value' in el) {
          el.value = title;
          el.dispatchEvent(new Event('input', {bubbles:true}));
          el.dispatchEvent(new Event('change', {bubbles:true}));
        } else {
          el.textContent = title;
          el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:title}));
        }
        break;
      }
    }
  } catch (e) {}

  result.ok = true;
  result.message = blockOk ? "block-editor" : "editPost-content";
  return result;
} catch (e) {
  result.message = String(e && e.message ? e.message : e);
  return result;
}
"""
            result = driver.execute_script(script, title, content)
            if not result or not result.get("ok"):
                raise RuntimeError("WordPressへの自動入力に失敗しました。\n" + str(result))

            messagebox.showinfo(
                APP_NAME,
                "WordPressへ自動入力しました。\n\n"
                "タイトルと本文HTMLブロックが入っているか確認してください。\n"
                "公開・予約・下書き保存は手動で行ってください。"
            )
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def paste_to_wordpress_editor(self):
        self.auto_input_wordpress()

    def get_export_items(self):
        post_type = normalize_post_type(self.post_type_var.get())
        if post_type == POST_TYPE_RESULT:
            return self.items if self.items else self.get_items()
        if not self.items:
            self.generate()
        return self.items

    def export_txt(self):
        try:
            items = self.get_export_items()
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return

        file = filedialog.asksaveasfilename(
            title="TXT出力",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt")],
            initialfile="LeaguePost_posts.txt",
        )
        if file:
            Path(file).write_text(build_txt(items), encoding="utf-8")
            messagebox.showinfo(APP_NAME, "TXTを出力しました。")

    def export_html(self):
        try:
            items = self.get_export_items()
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return

        file = filedialog.asksaveasfilename(
            title="HTML出力",
            defaultextension=".html",
            filetypes=[("HTML", "*.html")],
            initialfile="LeaguePost_preview.html",
        )
        if file:
            Path(file).write_text(build_preview_html(items), encoding="utf-8")
            messagebox.showinfo(APP_NAME, "HTMLを出力しました。")

    def export_csv(self):
        try:
            items = self.get_export_items()
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return

        file = filedialog.asksaveasfilename(
            title="CSV出力",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="LeaguePost_posts.csv",
        )
        if not file:
            return

        with open(file, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "タイトル",
                "試合日",
                "予約年",
                "予約月",
                "予約日",
                "予約時",
                "予約分",
                "カテゴリー候補",
                "大会コード",
                "本文HTML",
            ])
            for it in items:
                writer.writerow([
                    it.title,
                    getattr(it, "game_date", datetime.now()).strftime("%Y/%m/%d"),
                    it.pub_year,
                    it.pub_month,
                    it.pub_day,
                    it.pub_hour,
                    it.pub_minute,
                    "、".join(it.categories),
                    post_tournament_id(it),
                    post_body_html(it),
                ])

        messagebox.showinfo(APP_NAME, "CSVを出力しました。")


class CustomTkApp:
    """CustomTkinter sidebar UI. Core generation logic stays shared with the legacy Tk UI."""

    def __init__(self, ctk_module):
        self.ctk = ctk_module
        ctk_module.set_appearance_mode("light")
        ctk_module.set_default_color_theme("blue")
        self.root = ctk_module.CTk()
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        try:
            self.root.state("zoomed")
        except Exception:
            pass

        self.config_data = load_config()
        self.items = []
        self.wp_driver = None
        self.posted_flags = []
        self.current_index = 0
        self.current_page = "日程"
        self.sidebar_open = True
        self._last_autofilled_dates_text = ""
        self._last_auto_tournament_id = ""
        self.ui_font_size = int(self.config_data.get("ui_font_size", self.config_data.get("font_size", 18)))

        self.vars = {}
        self._build_shell()
        self._build_pages()
        self._load_defaults()
        self.root.after(100, self.maximize_window)
        self.root.after(600, self.maximize_window)
        self.show_page("設定")

    def mainloop(self):
        self.root.mainloop()

    def maximize_window(self):
        try:
            self.root.state("zoomed")
        except Exception:
            pass

    def _var(self, name, value=""):
        var = tk.StringVar(value=value)
        self.vars[name] = var
        return var

    def font(self, delta=0, weight="normal"):
        return ("Meiryo UI", self.ui_font_size + delta, weight)

    def _button(self, parent, **kwargs):
        kwargs.setdefault("font", self.font(0, "bold"))
        kwargs["height"] = max(int(kwargs.get("height", 36)), self.ui_font_size + 22)
        return self.ctk.CTkButton(parent, **kwargs)

    def _entry(self, parent, **kwargs):
        kwargs.setdefault("font", self.font())
        kwargs["height"] = max(int(kwargs.get("height", 34)), self.ui_font_size + 18)
        return self.ctk.CTkEntry(parent, **kwargs)

    def _option_menu(self, parent, **kwargs):
        kwargs.setdefault("font", self.font())
        kwargs.setdefault("dropdown_font", self.font())
        kwargs["height"] = max(int(kwargs.get("height", 34)), self.ui_font_size + 18)
        return self.ctk.CTkOptionMenu(parent, **kwargs)

    def _combo_box(self, parent, **kwargs):
        kwargs.setdefault("font", self.font())
        kwargs.setdefault("dropdown_font", self.font())
        kwargs["height"] = max(int(kwargs.get("height", 34)), self.ui_font_size + 18)
        return self.ctk.CTkComboBox(parent, **kwargs)

    def _build_shell(self):
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.sidebar = self.ctk.CTkFrame(self.root, width=210, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.main = self.ctk.CTkFrame(self.root, fg_color="#f7f8fa", corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        top = self.ctk.CTkFrame(self.main, fg_color="#ffffff", corner_radius=0, height=58)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        self._button(top, text="三", width=44, command=self.toggle_sidebar).grid(row=0, column=0, padx=12, pady=10)
        self.page_title = self.ctk.CTkLabel(top, text="", font=self.font(6, "bold"))
        self.page_title.grid(row=0, column=1, sticky="w", padx=6)

        self.content = self.ctk.CTkFrame(self.main, fg_color="#f7f8fa", corner_radius=0)
        self.content.grid(row=1, column=0, sticky="nsew", padx=18, pady=18)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.brand = self.ctk.CTkLabel(
            self.sidebar,
            text="League POST\n中国地区大学準硬式野球連盟",
            font=self.font(1, "bold"),
            justify="left",
        )
        self.brand.pack(anchor="w", padx=16, pady=(18, 14))
        self.nav_buttons = {}
        for page in ["日程", "E-League", "選手名簿", "試合速報", "寸評追加", "順位表", "個人賞", "自責点判定", "設定"]:
            btn = self._button(
                self.sidebar,
                text=page,
                anchor="w",
                height=42,
                command=lambda p=page: self.show_page(p),
            )
            btn.pack(fill="x", padx=12, pady=4)
            self.nav_buttons[page] = btn

    def _make_page(self, name):
        page = self.ctk.CTkScrollableFrame(self.content, fg_color="#f7f8fa")
        page.grid_columnconfigure(0, weight=1)
        self.pages[name] = page
        return page

    def _field(self, parent, row, label, widget, help_text=""):
        self.ctk.CTkLabel(parent, text=label, font=self.font(0, "bold"), anchor="w").grid(row=row, column=0, sticky="nw", padx=(0, 18), pady=9)
        widget.grid(row=row, column=1, sticky="ew", pady=7)
        if help_text:
            self.ctk.CTkLabel(parent, text=help_text, text_color="#666", font=self.font(-1), anchor="w").grid(row=row, column=2, sticky="w", padx=10)

    def _section(self, parent, title):
        frame = self.ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=12)
        frame.grid_columnconfigure(1, weight=1)
        self.ctk.CTkLabel(frame, text=title, font=self.font(4, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=18, pady=(16, 8))
        return frame

    def _build_pages(self):
        self.pages = {}
        self._build_settings_page()
        self._build_schedule_page()
        self._build_eleague_page()
        self._build_player_roster_page()
        self._build_result_page()
        self._build_review_page()
        self._build_standings_page()
        self._build_awards_page()
        self._build_earned_run_page()

    def _build_settings_page(self):
        page = self._make_page("設定")
        card = self._section(page, "設定")
        card.grid(row=0, column=0, sticky="ew")
        self.wp_new_post_url_var = self._var("wp_new_post_url")
        self.media_new_url_var = self._var("media_new_url")
        self.media_base_url_var = self._var("media_base_url")
        self.eleague_url_var = self._var("eleague_url")
        self.eleague_cup_id_1_var = self._var("eleague_cup_id_1")
        self.eleague_cup_id_2_var = self._var("eleague_cup_id_2")
        self.eleague_cup_id_3_var = self._var("eleague_cup_id_3")
        self.dify_api_url_var = self._var("dify_api_url")
        self.dify_api_key_var = self._var("dify_api_key")
        self.dify_prompt_var = self._var("dify_prompt")
        self.font_size_var = self._var("font_size", str(self.ui_font_size))
        self._field(card, 1, "WordPress新規投稿URL", self._entry(card, textvariable=self.wp_new_post_url_var))
        self._field(card, 2, "ファイル新規投稿URL", self._entry(card, textvariable=self.media_new_url_var))
        self._field(card, 3, "ダウンロードフォルダ", self._entry(card, textvariable=self.media_base_url_var), "例: https://.../wp-content/uploads")
        self._field(card, 4, "E-League URL", self._entry(card, textvariable=self.eleague_url_var), "初期値: https://safe.omyutech.com/league/57")
        self._field(
            card,
            5,
            "文字サイズ",
            self._option_menu(card, variable=self.font_size_var, values=["14", "16", "18", "20", "22", "24"]),
            "保存後、次回起動時に反映",
        )
        self._field(card, 6, "Dify API URL", self._entry(card, textvariable=self.dify_api_url_var), "例: https://api.dify.ai/v1")
        self._field(card, 7, "Dify API Key", self._entry(card, textvariable=self.dify_api_key_var, show="*"), "未設定の場合は寸評欄に仮文を入れます")
        self._field(card, 8, "寸評生成プロンプト", self._entry(card, textvariable=self.dify_prompt_var), "空欄なら標準プロンプトを使用")
        self._button(card, text="設定を保存", command=self.save_settings).grid(row=9, column=1, sticky="w", pady=18)

    def _build_schedule_page(self):
        page = self._make_page("日程")
        card = self._section(page, "日程 編集画面")
        card.grid(row=0, column=0, sticky="ew")
        self.year_var = self._var("year", str(datetime.now().year))
        self.season_var = self._var("season", "春季")
        self.schedule_excel_file_var = self._var("schedule_excel_file")
        self.schedule_title_var = self._var("schedule_title")
        self.schedule_download_url_var = self._var("schedule_download_url")
        self._field(card, 1, "作成年度", self._entry(card, textvariable=self.year_var, width=160))
        self._field(card, 2, "季節", self._option_menu(card, variable=self.season_var, values=["春季", "秋季"], command=self.on_season_changed))
        self._field(card, 3, "大会タイトル", self._entry(card, textvariable=self.schedule_title_var))
        file_row = self.ctk.CTkFrame(card, fg_color="transparent")
        file_row.grid_columnconfigure(0, weight=1)
        self._entry(file_row, textvariable=self.schedule_excel_file_var, state="readonly").grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._button(file_row, text="Excelファイルを選択", command=self.select_schedule_excel_file).grid(row=0, column=1)
        self._field(card, 4, "日程表Excelファイル", file_row)
        self._field(card, 5, "ダウンロードリンク", self._entry(card, textvariable=self.schedule_download_url_var))
        actions = self._action_row(card)
        actions.grid(row=6, column=1, sticky="w", pady=18)
        self._button(actions, text="原稿作成", command=lambda: self.generate_post(POST_TYPE_SCHEDULE)).pack(side="left", padx=4)
        self._button(actions, text="メディアへアップロード", width=230, command=self.upload_schedule_excel_media).pack(side="left", padx=4)
        self.ctk.CTkLabel(card, text="\u30a8\u30af\u30bb\u30eb\u30d5\u30a1\u30a4\u30eb\u540d\u306f\u82f1\u6570\u5b57\u3068\u3057\u3066\u304f\u3060\u3055\u3044\u3002", text_color="#666", font=self.font(-1), anchor="w").grid(row=7, column=1, sticky="w", pady=(0, 18))

    def _build_eleague_page(self):
        page = self._make_page("E-League")
        card = self._section(page, "E-League 編集画面")
        card.grid(row=0, column=0, sticky="ew")
        self.eleague_title_var = self._var("eleague_title")
        self._field(
            card,
            1,
            "大会タイトル",
            self._entry(card, textvariable=self.eleague_title_var),
        )

        actions = self._action_row(card)
        actions.grid(row=2, column=1, sticky="w", pady=(18, 8))
        self._button(actions, text="E-league\u30ed\u30b0\u30a4\u30f3", width=170, command=self.open_eleague_chrome).pack(side="left", padx=4)
        self._button(actions, text="\u5927\u4f1a\u4f5c\u6210", width=150, command=self.run_eleague_tournament_create_workflow).pack(side="left", padx=4)
        self._button(actions, text="\u30eb\u30fc\u30eb\u8a2d\u5b9a", width=150, command=self.run_eleague_tournament_edit_workflow).pack(side="left", padx=4)
        self._button(actions, text="\u5927\u4f1aID\u53d6\u5f97", width=160, command=self.fetch_eleague_tournament_ids).pack(side="left", padx=4)
        self._button(actions, text="\u30c1\u30fc\u30e0\u767b\u9332", width=160, command=self.run_eleague_team_setup_workflow).pack(side="left", padx=4)
        self._button(actions, text="\u65e5\u7a0b\u7de8\u96c6", width=160, command=self.run_eleague_schedule_edit_workflow).pack(side="left", padx=4)
        self.ctk.CTkLabel(
            card,
            text="\u5fc5\u305a\u6700\u521d\u306bE-league\u306b\u624b\u52d5\u3067\u30ed\u30b0\u30a4\u30f3\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
            font=self.font(-1, "bold"),
            text_color="#a15c00",
        ).grid(row=3, column=1, sticky="w", padx=4, pady=(0, 4))
        self.ctk.CTkLabel(
            card,
            text="E-league\u3078\u306e\u767b\u9332\u306fChrome\u3092\u9589\u3058\u305a\u306b\u4e00\u6c17\u306b\u5b9f\u884c\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
            font=self.font(-1, "bold"),
            text_color="#a15c00",
        ).grid(row=4, column=1, sticky="w", padx=4, pady=(0, 18))

    def _build_player_roster_page(self):
        page = self._make_page("選手名簿")
        card = self._section(page, "選手名簿 編集画面")
        card.grid(row=0, column=0, sticky="ew")

        self.roster_mode_var = tk.StringVar(value=self.config_data.get("roster_mode", "all"))
        self.roster_input_folder_var = tk.StringVar(value=self.config_data.get("roster_input_folder", ""))
        self.roster_single_file_var = tk.StringVar(value=self.config_data.get("roster_single_file", ""))
        self.roster_output_file_var = tk.StringVar(value=self.config_data.get("roster_output_file", ""))
        self.roster_overwrite_var = tk.BooleanVar(value=bool(self.config_data.get("roster_overwrite", True)))

        mode_row = self.ctk.CTkFrame(card, fg_color="transparent")
        self.ctk.CTkLabel(mode_row, text="処理モード", font=self.font(0, "bold")).pack(side="left", padx=(0, 12))
        self.ctk.CTkRadioButton(mode_row, text="全大学更新", variable=self.roster_mode_var, value="all", font=self.font(), command=self.persist_settings).pack(side="left", padx=8)
        self.ctk.CTkRadioButton(mode_row, text="1大学のみ更新", variable=self.roster_mode_var, value="single", font=self.font(), command=self.persist_settings).pack(side="left", padx=8)
        self._field(card, 1, "処理モード", mode_row)

        input_row = self.ctk.CTkFrame(card, fg_color="transparent")
        input_row.grid_columnconfigure(0, weight=1)
        self._entry(input_row, textvariable=self.roster_input_folder_var).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._button(input_row, text="参照", width=110, command=self.select_roster_input_folder).grid(row=0, column=1)
        self._field(card, 2, "入力フォルダ", input_row)

        single_row = self.ctk.CTkFrame(card, fg_color="transparent")
        single_row.grid_columnconfigure(0, weight=1)
        self._entry(single_row, textvariable=self.roster_single_file_var).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._button(single_row, text="参照", width=110, command=self.select_roster_single_file).grid(row=0, column=1)
        self._field(card, 3, "1大学更新ファイル", single_row)

        output_row = self.ctk.CTkFrame(card, fg_color="transparent")
        output_row.grid_columnconfigure(0, weight=1)
        self._entry(output_row, textvariable=self.roster_output_file_var).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._button(output_row, text="参照", width=110, command=self.select_roster_output_file).grid(row=0, column=1)
        self._field(card, 4, "出力ファイル", output_row)

        option_row = self.ctk.CTkFrame(card, fg_color="transparent")
        self.ctk.CTkCheckBox(option_row, text="既存大学シートを上書きする", variable=self.roster_overwrite_var, font=self.font(), command=self.persist_settings).pack(anchor="w")
        self._field(card, 5, "オプション", option_row)

        actions = self._action_row(card)
        actions.grid(row=6, column=1, sticky="w", pady=18)
        self._button(actions, text="名簿統合を実行", width=220, command=self.run_player_roster_merge).pack(side="left", padx=4)
        self._button(actions, text="フォルダを開く", width=180, command=lambda: self.open_external_folder(UNIVERSITY_ROSTER_APP_DIR)).pack(side="left", padx=4)
        self._button(actions, text="E-leagueへ登録（１部・２部）", width=280, command=self.register_roster_eleague_teams).pack(side="left", padx=4)

        log_card = self._section(page, "処理ログ")
        log_card.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        self.roster_log = self.ctk.CTkTextbox(log_card, height=260, font=("Consolas", max(12, self.ui_font_size - 2)))
        self.roster_log.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=18, pady=(8, 18))
        log_card.grid_columnconfigure(0, weight=1)

    def _build_result_page(self):
        page = self._make_page("試合速報")
        card = self._section(page, "試合速報 編集画面")
        card.grid(row=0, column=0, sticky="ew")
        self.division_var = self._var("division", "１部")
        self.league_var = self._var("league_name")
        self.cup_id_var = self._var("cup_id")
        self.tournament_id_var = self._var("tournament_id")
        self._field(card, 1, "大会タイトル", self._entry(card, textvariable=self.league_var))
        self._field(card, 2, "日程", self._textbox(card, "dates_text", height=150), "日程ページから1部・2部・入替戦を自動反映")
        actions = self._action_row(card)
        actions.grid(row=3, column=1, sticky="w", pady=18)
        self._button(actions, text="原稿作成", command=lambda: self.generate_post(POST_TYPE_RESULT)).pack(side="left", padx=4)

    def _build_review_page(self):
        page = self._make_page("寸評追加")
        card = self._section(page, "寸評追加 編集画面")
        card.grid(row=0, column=0, sticky="ew")
        self.review_division_var = self._var("review_division", "１部")
        self.review_cup_id_var = self._var("review_cup_id")
        self.review_date_var = self._var("review_date")
        self.review_title_var = self._var("review_title")
        self.review_game_id_vars = [
            self._var("review_game_id_1"),
            self._var("review_game_id_2"),
            self._var("review_game_id_3"),
        ]
        self._field(
            card,
            1,
            "区分",
            self._option_menu(
                card,
                variable=self.review_division_var,
                values=["１部", "２部", "入替戦"],
                command=self.on_review_division_changed,
            ),
        )
        self._field(card, 2, "CupID", self._entry(card, textvariable=self.review_cup_id_var), "手入力可")
        self.review_date_menu = self._option_menu(card, variable=self.review_date_var, values=[""], command=self.on_review_date_changed)
        self._field(card, 3, "日付", self.review_date_menu, "日程画面で読み込んだ日程から選択")
        self._field(card, 4, "第１試合GameID", self._entry(card, textvariable=self.review_game_id_vars[0]), "取得失敗時は手入力可")
        self._field(card, 5, "第２試合GameID", self._entry(card, textvariable=self.review_game_id_vars[1]), "取得失敗時は手入力可")
        self._field(card, 6, "第３試合GameID", self._entry(card, textvariable=self.review_game_id_vars[2]), "取得失敗時は手入力可")
        self._field(card, 7, "タイトル", self._entry(card, textvariable=self.review_title_var), "同名の既存投稿を検索し、本文を全文置換")
        self._field(card, 8, "ChatGPT回答貼付", self._textbox(card, "review_chatgpt_text", height=170), "空欄・不足はDifyで自動作成")
        actions = self._action_row(card)
        actions.grid(row=9, column=1, sticky="w", pady=(18, 4))
        self._button(actions, text="GameID取得", width=180, command=self.fetch_review_game_ids).pack(side="left", padx=4)
        self._button(actions, text="ChatGPT用プロンプトコピー", width=280, command=self.copy_review_chatgpt_prompt).pack(side="left", padx=4)
        actions2 = self._action_row(card)
        actions2.grid(row=10, column=1, sticky="w", pady=(4, 18))
        self._button(actions2, text="ChatGPTを開く", width=200, command=lambda: webbrowser.open("https://chatgpt.com/")).pack(side="left", padx=4)
        self._button(actions2, text="原稿作成", width=180, command=lambda: self.generate_post(POST_TYPE_REVIEW)).pack(side="left", padx=4)

    def _build_standings_page(self):
        page = self._make_page("順位表")
        card = self._section(page, "順位表 編集画面")
        card.grid(row=0, column=0, sticky="ew")
        self.standings_division_var = self._var("standings_division", "１部")
        self._field(card, 1, "区分", self._option_menu(card, variable=self.standings_division_var, values=["１部", "２部"], command=self.on_standings_division_changed))
        self._field(card, 2, "投稿タイトル", self._entry(card, textvariable=self.league_var))
        self._field(card, 3, "記録員LINE本文", self._textbox(card, "standings_text", height=220))
        actions = self._action_row(card)
        actions.grid(row=4, column=1, sticky="w", pady=18)
        self._button(actions, text="原稿作成", command=lambda: self.generate_post(POST_TYPE_STANDINGS)).pack(side="left", padx=4)

    def _build_awards_page(self):
        page = self._make_page("個人賞")
        card = self._section(page, "個人賞 編集画面")
        card.grid(row=0, column=0, sticky="ew")
        self.awards_division_var = self._var("awards_division", "１部")
        self._field(card, 1, "区分", self._option_menu(card, variable=self.awards_division_var, values=["１部", "２部"], command=self.on_awards_division_changed))
        self._field(card, 2, "投稿タイトル", self._entry(card, textvariable=self.league_var))
        self._field(card, 3, "記録員LINE本文", self._textbox(card, "awards_text", height=260))
        actions = self._action_row(card)
        actions.grid(row=4, column=1, sticky="w", pady=18)
        self._button(actions, text="原稿作成", command=lambda: self.generate_post(POST_TYPE_AWARDS)).pack(side="left", padx=4)

    def _build_earned_run_page(self):
        page = self._make_page("自責点判定")
        card = self._section(page, "自責点判定 編集画面")
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(1, weight=1)

        self.neo_url_vars = []
        for i in range(3):
            var = tk.StringVar()
            self.neo_url_vars.append(var)
            self._field(card, i + 1, f"第{i + 1}試合URL", self._entry(card, textvariable=var))

        actions = self._action_row(card)
        actions.grid(row=4, column=1, sticky="w", pady=(18, 6))
        self._button(actions, text="解析する", width=170, command=self.run_neo_embedded_analysis).pack(side="left", padx=4)
        self._button(actions, text="GoldData保存", width=170, command=self.save_neo_selected).pack(side="left", padx=4)
        self._button(actions, text="保存済み正解データ検証", width=230, command=self.run_neo_saved_regression).pack(side="left", padx=4)
        self._button(actions, text="DebugReport表示", width=190, command=self.open_neo_debug_report).pack(side="left", padx=4)

        self.neo_status_var = tk.StringVar(value="URLを入力して解析してください。")
        self.ctk.CTkLabel(card, textvariable=self.neo_status_var, font=self.font(-1), anchor="w").grid(row=5, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 14))

        check_card = self._section(page, "保存対象試合")
        check_card.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        self.neo_check_items_frame = self.ctk.CTkFrame(check_card, fg_color="transparent")
        self.neo_check_items_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(8, 18))
        self.neo_save_vars = {}

        result_card = self._section(page, "判定結果")
        result_card.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        columns = ("game", "location", "judgment", "reason", "runner")
        style = ttk.Style()
        style.configure("Neo.Treeview", font=self.font(-1), rowheight=max(26, self.ui_font_size + 8))
        style.configure("Neo.Treeview.Heading", font=self.font(-1, "bold"))
        self.neo_tree = ttk.Treeview(result_card, columns=columns, show="headings", height=14, style="Neo.Treeview")
        headings = {"game": "試合", "location": "場所", "judgment": "判定", "reason": "理由", "runner": "走者"}
        widths = {"game": 230, "location": 130, "judgment": 120, "reason": 300, "runner": 460}
        for col in columns:
            self.neo_tree.heading(col, text=headings[col])
            self.neo_tree.column(col, width=widths[col], anchor="center" if col != "runner" else "w")
        yscroll = ttk.Scrollbar(result_card, orient="vertical", command=self.neo_tree.yview)
        xscroll = ttk.Scrollbar(result_card, orient="horizontal", command=self.neo_tree.xview)
        self.neo_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.neo_tree.grid(row=1, column=0, sticky="nsew", padx=(18, 0), pady=(8, 18))
        yscroll.grid(row=1, column=1, sticky="ns", pady=(8, 18))
        xscroll.grid(row=2, column=0, sticky="ew", padx=(18, 0), pady=(0, 18))
        result_card.grid_columnconfigure(0, weight=1)
        result_card.grid_rowconfigure(1, weight=1)

        memo_card = self._section(page, "保存メモ")
        memo_card.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        self.neo_memo = self.ctk.CTkTextbox(memo_card, height=90, font=self.font(-1))
        self.neo_memo.grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(8, 18))
        self.neo_day = None

    def _textbox(self, parent, name, height=160):
        box = self.ctk.CTkTextbox(parent, height=height, font=self.font(-1))
        self.vars[name] = box
        return box

    def _action_row(self, parent):
        return self.ctk.CTkFrame(parent, fg_color="transparent")

    def _roster_log(self, message):
        widget = getattr(self, "roster_log", None)
        if widget is not None:
            widget.insert("end", str(message) + "\n")
            widget.see("end")
            self.root.update_idletasks()

    def _load_roster_modules(self):
        app_dir = Path(UNIVERSITY_ROSTER_APP_DIR)
        if not app_dir.exists():
            raise FileNotFoundError(f"大学名簿統合システムのフォルダが見つかりません: {app_dir}")
        app_dir_text = str(app_dir)
        if app_dir_text not in sys.path:
            sys.path.insert(0, app_dir_text)
        from app.config import TEMPLATE_FILE_NAME, DEFAULT_OUTPUT_FILE  # type: ignore
        from app.excel_reader import ExcelReader  # type: ignore
        from app.header_detector import HeaderDetector  # type: ignore
        from app.data_extractor import DataExtractor  # type: ignore
        from app.exporter import ExcelExporter  # type: ignore
        return TEMPLATE_FILE_NAME, DEFAULT_OUTPUT_FILE, ExcelReader, HeaderDetector, DataExtractor, ExcelExporter

    def select_roster_input_folder(self):
        folder = filedialog.askdirectory(title="入力フォルダを選択")
        if not folder:
            return
        self.roster_input_folder_var.set(app_path_text(folder))
        if not self.roster_output_file_var.get().strip():
            try:
                _template, default_output, *_ = self._load_roster_modules()
            except Exception:
                default_output = "統合名簿.xlsx"
            self.roster_output_file_var.set(app_path_text(Path(folder) / default_output))
        self.persist_settings()
        self.scan_roster_input_folder()

    def select_roster_single_file(self):
        initial_dir = str(app_path(self.roster_input_folder_var.get())) if self.roster_input_folder_var.get().strip() else None
        file_path = filedialog.askopenfilename(
            title="1大学更新ファイルを選択",
            initialdir=initial_dir,
            filetypes=[("Excelファイル", "*.xlsx")],
        )
        if not file_path:
            return
        self.roster_single_file_var.set(app_path_text(file_path))
        if not self.roster_input_folder_var.get().strip():
            self.roster_input_folder_var.set(app_path_text(Path(file_path).parent))
        self.persist_settings()

    def select_roster_output_file(self):
        initial_dir = str(app_path(self.roster_input_folder_var.get())) if self.roster_input_folder_var.get().strip() else None
        file_path = filedialog.asksaveasfilename(
            title="出力ファイルを指定",
            initialdir=initial_dir,
            defaultextension=".xlsx",
            filetypes=[("Excelファイル", "*.xlsx")],
            initialfile="統合名簿.xlsx",
        )
        if file_path:
            self.roster_output_file_var.set(app_path_text(file_path))
            self.persist_settings()

    def scan_roster_input_folder(self):
        widget = getattr(self, "roster_log", None)
        if widget is not None:
            widget.delete("1.0", "end")
        folder_text = self.roster_input_folder_var.get().strip()
        if not folder_text:
            return
        try:
            folder = app_path(folder_text)
            template_name, _default_output, *_ = self._load_roster_modules()
            files = self._roster_excel_files(folder, template_name)
            self._roster_log(f"入力フォルダ: {folder_text}")
            self._roster_log(f"テンプレート: {folder / template_name}")
            self._roster_log(f"Excelファイル検出数: {len(files)} 件")
            for file_path in files:
                self._roster_log(f" - {file_path.name}")
        except Exception as exc:
            self._roster_log(f"確認エラー: {exc}")

    def _roster_excel_files(self, folder, template_name):
        return sorted([
            path for path in Path(folder).glob("*.xlsx")
            if not path.name.startswith("~$") and path.name != template_name
        ])

    def run_player_roster_merge(self):
        try:
            input_folder = self.roster_input_folder_var.get().strip()
            output_file = self.roster_output_file_var.get().strip()
            mode = self.roster_mode_var.get()
            self.persist_settings()
            if not input_folder:
                raise ValueError("入力フォルダを選択してください。")
            if not output_file:
                raise ValueError("出力ファイルを指定してください。")
            folder = app_path(input_folder)
            if not folder.exists():
                raise FileNotFoundError(f"入力フォルダが見つかりません: {folder}")

            template_name, _default_output, ExcelReader, HeaderDetector, DataExtractor, ExcelExporter = self._load_roster_modules()
            template_file = folder / template_name
            if mode == "single":
                single_file = self.roster_single_file_var.get().strip()
                if not single_file:
                    raise ValueError("1大学更新ファイルを選択してください。")
                files = [app_path(single_file)]
            else:
                files = self._roster_excel_files(folder, template_name)
            if not files:
                raise ValueError("処理対象のExcelファイルが見つかりません。")

            self.roster_log.delete("1.0", "end")
            self._roster_log("名簿統合を開始します。")
            self._roster_log(f"処理モード: {'1大学のみ更新' if mode == 'single' else '全大学更新'}")
            self._roster_log(f"出力ファイル: {output_file}")
            self._roster_log(f"テンプレート: {template_file}")

            university_records = {}
            for file_path in files:
                if not file_path.exists():
                    self._roster_log(f"スキップ: {file_path} が見つかりません。")
                    continue
                try:
                    reader = ExcelReader(file_path)
                    summary = reader.read_summary()
                    detector = HeaderDetector(summary["rows"])
                    header_info = detector.detect()
                    if header_info.get("header_row") is None:
                        self._roster_log(f"警告: {file_path.name} は見出し行を判定できないためスキップしました。")
                        continue
                    all_rows = reader.read_all_rows()
                    extractor = DataExtractor(all_rows, header_info)
                    records = extractor.extract()
                    university_name = summary["university_name"]
                    university_records[university_name] = records
                    self._roster_log(f"{file_path.name}: {university_name} / {len(records)} 件")
                except Exception as exc:
                    self._roster_log(f"エラー: {file_path.name} - {exc}")

            if not university_records:
                raise ValueError("出力できるデータがありませんでした。")

            exporter = ExcelExporter(
                output_file=str(app_path(output_file)),
                overwrite=self.roster_overwrite_var.get(),
                template_file=template_file if template_file.exists() else None,
            )
            exporter.save(university_records)
            self._roster_log("")
            self._roster_log("Excel出力が完了しました。")
            self._roster_log(f"保存先: {output_file}")
            messagebox.showinfo(APP_NAME, f"選手名簿の統合が完了しました。\n\n{output_file}")
        except Exception as exc:
            logging.error(traceback.format_exc())
            self._roster_log(f"エラー: {exc}")
            messagebox.showerror(APP_NAME, str(exc))

    def open_eleague_chrome(self):
        try:
            self.persist_settings()
            url = self.eleague_url_var.get().strip() or DEFAULT_ELEAGUE_URL
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError("E-League URL\u306f http:// \u307e\u305f\u306f https:// \u304b\u3089\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002")
            try:
                driver, WebDriverWait = self._get_wp_driver()
                driver.get(url)
                WebDriverWait(driver, 60).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )
                focus_chrome_window(driver)
            except Exception:
                logging.warning(traceback.format_exc())
                webbrowser.open(url)
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))
    def _run_eleague_combined_workflow(self, confirm_message, steps, complete_message, progress_title="E-League \u81ea\u52d5\u51e6\u7406", allow_chrome_focus=False, show_progress=True):
        if not messagebox.askyesno(APP_NAME, confirm_message):
            return
        original_askyesno = messagebox.askyesno
        original_showinfo = messagebox.showinfo
        original_showwarning = messagebox.showwarning
        original_showerror = messagebox.showerror
        original_focus_chrome = globals().get("focus_chrome_window")
        original_suppress_progress = getattr(self, "_eleague_suppress_progress", False)
        warnings = []

        def yes_to_step_prompts(*args, **kwargs):
            return True

        def collect_info(*args, **kwargs):
            return None

        def collect_warning(title, message=None, *args, **kwargs):
            warnings.append(str(message if message is not None else title))
            return None

        def raise_error(title, message=None, *args, **kwargs):
            raise RuntimeError(str(message if message is not None else title))

        def keep_app_foreground(*args, **kwargs):
            try:
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
            return None

        step_entries = []
        for item in steps:
            if isinstance(item, tuple):
                step_entries.append(item)
            else:
                step_entries.append((getattr(item, "__name__", "\u51e6\u7406"), item))

        try:
            messagebox.askyesno = yes_to_step_prompts
            messagebox.showinfo = collect_info
            messagebox.showwarning = collect_warning
            messagebox.showerror = raise_error
            self._eleague_suppress_progress = not show_progress
            if original_focus_chrome is not None and not allow_chrome_focus:
                globals()["focus_chrome_window"] = keep_app_foreground
            if show_progress:
                self._show_progress_dialog(
                    progress_title,
                    "Chrome\u3092\u6e96\u5099\u3057\u3066\u3044\u307e\u3059\u3002\n\u3057\u3070\u3089\u304f\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002",
                )
            for index, (label, step) in enumerate(step_entries, start=1):
                if show_progress:
                    self._show_progress_dialog(
                        progress_title,
                        f"{label}\u3092\u5b9f\u884c\u3057\u3066\u3044\u307e\u3059\u3002({index}/{len(step_entries)})\nChrome\u753b\u9762\u306f\u81ea\u52d5\u64cd\u4f5c\u4e2d\u3067\u3059\u3002\u5b8c\u4e86\u307e\u3067\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002",
                    )
                step()
        except Exception as exc:
            logging.error(traceback.format_exc())
            original_showerror(APP_NAME, str(exc))
            return
        finally:
            messagebox.askyesno = original_askyesno
            messagebox.showinfo = original_showinfo
            messagebox.showwarning = original_showwarning
            messagebox.showerror = original_showerror
            if original_focus_chrome is not None:
                globals()["focus_chrome_window"] = original_focus_chrome
            self._eleague_suppress_progress = original_suppress_progress
            self._close_progress_dialog()
            try:
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
        if warnings:
            original_showwarning(APP_NAME, complete_message + "\n\n" + "\n".join(warnings[:8]))
        else:
            original_showinfo(APP_NAME, complete_message)

    def run_eleague_tournament_create_workflow(self):
        self._run_eleague_combined_workflow(
            "E-League\u3067\u5927\u4f1a\u4f5c\u6210\u3092\u5b9f\u884c\u3057\u307e\u3059\u3002\n\n\u30ed\u30b0\u30a4\u30f3\u753b\u9762\u304c\u8868\u793a\u3055\u308c\u305f\u5834\u5408\u306f\u51e6\u7406\u3092\u505c\u6b62\u3057\u307e\u3059\u3002\u5148\u306bChrome\u3067E-League\u3078\u30ed\u30b0\u30a4\u30f3\u3057\u3066\u304b\u3089\u518d\u5b9f\u884c\u3057\u3066\u304f\u3060\u3055\u3044\u3002\n\n\u7d9a\u884c\u3057\u307e\u3059\u304b\uff1f",
            [("\u5927\u4f1a\u4f5c\u6210", self.open_eleague_tournament_create)],
            "E-League\u306e\u5927\u4f1a\u4f5c\u6210\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002",
            "E-League \u5927\u4f1a\u4f5c\u6210",
        )

    def run_eleague_tournament_edit_workflow(self):
        self._run_eleague_combined_workflow(
            "E-League\u306e\u30eb\u30fc\u30eb\u8a2d\u5b9a\u3092\u4e00\u62ec\u5b9f\u884c\u3057\u307e\u3059\u3002\n\n\u5927\u4f1a\u7de8\u96c6 \u2192 \u30eb\u30fc\u30eb\u8a2d\u5b9a \u2192 \u7403\u5834\u8ffd\u52a0 \u2192 \u5927\u4f1aID\u8a2d\u5b9a \u306e\u9806\u306b\u5b9f\u884c\u3057\u307e\u3059\u3002\nChrome\u753b\u9762\u3092\u524d\u9762\u306b\u51fa\u3057\u3001\u753b\u9762\u8868\u793a\u306b\u5408\u308f\u305b\u3066\u51e6\u7406\u3057\u307e\u3059\u3002\n\n\u7d9a\u884c\u3057\u307e\u3059\u304b\uff1f",
            [("\u5927\u4f1a\u7de8\u96c6", self.edit_eleague_tournaments), ("\u30eb\u30fc\u30eb\u8a2d\u5b9a", self.setup_eleague_rules_stadiums_outputs)],
            "E-League\u306e\u30eb\u30fc\u30eb\u8a2d\u5b9a\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002",
            "E-League \u30eb\u30fc\u30eb\u8a2d\u5b9a",
            allow_chrome_focus=True,
            show_progress=False,
        )

    def run_eleague_team_setup_workflow(self):
        self._run_eleague_combined_workflow(
            "E-League\u306e\u30c1\u30fc\u30e0\u767b\u9332\u3092\u4e00\u62ec\u5b9f\u884c\u3057\u307e\u3059\u3002\n\n\u30c1\u30fc\u30e0\u767b\u9332 \u2192 \u30b0\u30eb\u30fc\u30d7\u8a2d\u5b9a \u2192 \u7d44\u307f\u5408\u308f\u305b\u767b\u9332 \u306e\u9806\u306b\u5b9f\u884c\u3057\u307e\u3059\u3002\nChrome\u753b\u9762\u3092\u524d\u9762\u306b\u51fa\u3057\u3001\u51e6\u7406\u306e\u9032\u307f\u65b9\u3092\u78ba\u8a8d\u3067\u304d\u308b\u3088\u3046\u306b\u3057\u307e\u3059\u3002\n\n\u7d9a\u884c\u3057\u307e\u3059\u304b\uff1f",
            [("\u30c1\u30fc\u30e0\u767b\u9332", self.import_eleague_teams), ("\u30b0\u30eb\u30fc\u30d7\u8a2d\u5b9a\u30fb\u7d44\u307f\u5408\u308f\u305b\u767b\u9332", self.setup_eleague_groups)],
            "E-League\u306e\u30c1\u30fc\u30e0\u767b\u9332\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002",
            "E-League \u30c1\u30fc\u30e0\u767b\u9332",
            allow_chrome_focus=True,
            show_progress=False,
        )

    def run_eleague_schedule_edit_workflow(self):
        self._run_eleague_combined_workflow(
            "E-League\u306e\u65e5\u7a0b\u7de8\u96c6\u3092\u4e00\u62ec\u5b9f\u884c\u3057\u307e\u3059\u3002\n\n\u5bfe\u6226\u30ab\u30fc\u30c9\u65e5\u7a0b\u30fb\u7403\u5834\u767b\u9332 \u2192 \u7403\u5834\u5225\u5165\u529b\u8005\u306e\u8a2d\u5b9a \u306e\u9806\u306b\u5b9f\u884c\u3057\u307e\u3059\u3002\nChrome\u753b\u9762\u3092\u524d\u9762\u306b\u51fa\u3057\u3001\u51e6\u7406\u306e\u9032\u307f\u65b9\u3092\u78ba\u8a8d\u3067\u304d\u308b\u3088\u3046\u306b\u3057\u307e\u3059\u3002\n\n\u7d9a\u884c\u3057\u307e\u3059\u304b\uff1f",
            [("\u5bfe\u6226\u30ab\u30fc\u30c9\u65e5\u7a0b\u30fb\u7403\u5834\u767b\u9332", self.register_eleague_schedule), ("\u7403\u5834\u5225\u5165\u529b\u8005\u306e\u8a2d\u5b9a", self.setup_eleague_recorders)],
            "E-League\u306e\u65e5\u7a0b\u7de8\u96c6\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002",
            "E-League \u65e5\u7a0b\u7de8\u96c6",
            allow_chrome_focus=True,
            show_progress=False,
        )


    def _roster_eleague_import_payloads(self):
        output_file = self.roster_output_file_var.get().strip()
        if not output_file:
            raise ValueError("選手名簿の出力ファイルを指定してください。")
        file_path = app_path(output_file).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"出力ファイルが見つかりません: {file_path}")
        cup_ids = {
            "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
        }
        missing = [division_label_from_key(key) for key, cup_id in cup_ids.items() if not cup_id]
        if missing:
            raise ValueError("設定画面でCupIDを入力してください: " + "、".join(missing))
        return [
            {
                "division_key": key,
                "division": division_label_from_key(key),
                "cup_id": cup_ids[key],
                "file_path": str(file_path),
                "url": f"https://safe.omyutech.com/cup/{cup_ids[key]}/team/import",
            }
            for key in ("1", "2")
        ]

    def _upload_roster_file_to_eleague_import(self, driver, WebDriverWait, payload):
        from selenium.webdriver.common.by import By  # type: ignore
        from selenium.common.exceptions import StaleElementReferenceException, WebDriverException  # type: ignore

        last_error = None
        file_name = Path(payload["file_path"]).name
        for attempt in range(1, 4):
            try:
                WebDriverWait(driver, 60).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )
                file_input = WebDriverWait(driver, 60).until(
                    lambda d: d.find_element(By.CSS_SELECTOR, 'input[type="file"]')
                )
                driver.execute_script(
                    """
arguments[0].removeAttribute('hidden');
arguments[0].removeAttribute('disabled');
arguments[0].style.display = 'block';
arguments[0].style.visibility = 'visible';
arguments[0].style.opacity = 1;
arguments[0].style.height = '1px';
arguments[0].style.width = '1px';
""",
                    file_input,
                )
                file_input.send_keys(payload["file_path"])
                return {"ok": True, "fileName": file_name, "attempt": attempt}
            except (StaleElementReferenceException, WebDriverException) as exc:
                last_error = exc
                time.sleep(1.0)
        raise RuntimeError(f"Failed to set file: {file_name}\n{last_error}")

    def register_roster_eleague_teams(self):
        try:
            payloads = self._roster_eleague_import_payloads()
            self.persist_settings()
            summary = "\n".join(f"{p['division']}: CupID {p['cup_id']} / {p['file_path']}" for p in payloads)
            if not messagebox.askyesno(
                APP_NAME,
                "E-League\u306e\u51fa\u529b\u753b\u9762\u304b\u3089\u5927\u4f1aID\u3092\u53d6\u5f97\u3057\u307e\u3059\u3002\n\n"
                "\u5927\u4f1aID\u3092\u624b\u5165\u529b\u3057\u305f\u5f8c\u306e\u78ba\u8a8d\u306b\u3082\u4f7f\u3048\u307e\u3059\u3002\n\n\u7d9a\u884c\u3057\u307e\u3059\u304b\uff1f",
            ):
                return
            use_progress = True
            self._show_progress_dialog("E-league \u9078\u624b\u540d\u7c3f\u767b\u9332", "Chrome\u3092\u6e96\u5099\u3057\u3066\u3044\u307e\u3059\u3002\n\u3057\u3070\u3089\u304f\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002")
            driver, WebDriverWait = self._get_wp_driver()
            tab_handles = {}
            try:
                for index, payload in enumerate(payloads, start=1):
                    self._update_progress_dialog(
                        f"{payload['division']}\u306e\u30a4\u30f3\u30dd\u30fc\u30c8\u753b\u9762\u3092\u958b\u3044\u3066\u3044\u307e\u3059\u3002({index}/{len(payloads)})\n"
                        f"CupID: {payload['cup_id']}"
                    )
                    if index == 1:
                        driver.get(payload["url"])
                        tab_handles[payload["division_key"]] = driver.current_window_handle
                    else:
                        before_handles = set(driver.window_handles)
                        driver.execute_script("window.open('about:blank', '_blank');")
                        WebDriverWait(driver, 15).until(lambda d: len(set(d.window_handles) - before_handles) >= 1)
                        new_handles = list(set(driver.window_handles) - before_handles)
                        driver.switch_to.window(new_handles[-1])
                        tab_handles[payload["division_key"]] = driver.current_window_handle
                        driver.get(payload["url"])
                    WebDriverWait(driver, 60).until(
                        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                    )
                    time.sleep(0.5)

                for index, payload in enumerate(payloads, start=1):
                    self._update_progress_dialog(
                        f"{payload['division']}\u3078\u51fa\u529b\u30d5\u30a1\u30a4\u30eb\u3092\u30bb\u30c3\u30c8\u3057\u3066\u3044\u307e\u3059\u3002({index}/{len(payloads)})\n"
                        "\u30a4\u30f3\u30dd\u30fc\u30c8\u78ba\u5b9a\u306f\u753b\u9762\u78ba\u8a8d\u5f8c\u306b\u624b\u52d5\u3067\u884c\u3063\u3066\u304f\u3060\u3055\u3044\u3002"
                    )
                    driver.switch_to.window(tab_handles[payload["division_key"]])
                    self._upload_roster_file_to_eleague_import(driver, WebDriverWait, payload)
                    time.sleep(0.6)
            finally:
                if use_progress:
                    self._close_progress_dialog()
            if tab_handles.get("2"):
                try:
                    driver.switch_to.window(tab_handles["2"])
                except Exception:
                    pass
            focus_chrome_window(driver)
            messagebox.showinfo(
                APP_NAME,
                "E-league\u306e\u9078\u624b\u540d\u7c3f\u30a4\u30f3\u30dd\u30fc\u30c8\u753b\u9762\u3092\u958b\u304d\u307e\u3057\u305f\u3002\n"
                "\uff11\u90e8\u30fb\uff12\u90e8\u306e\u5404\u30bf\u30d6\u3067\u5185\u5bb9\u3092\u78ba\u8a8d\u3057\u3001\u624b\u52d5\u3067\u30a4\u30f3\u30dd\u30fc\u30c8\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
            )
        except Exception as exc:
            self._close_progress_dialog()
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(exc))

    def _load_neo_modules(self):
        app_dir = Path(NEO_PHOENIX_APP_DIR)
        if not app_dir.exists():
            raise FileNotFoundError(f"NeoPhoenixのフォルダが見つかりません: {app_dir}")
        app_dir_text = str(app_dir)
        if app_dir_text not in sys.path:
            sys.path.insert(0, app_dir_text)
        from src.config import GOLDDATA_EXCLUDED_CASES, NEO_JUDGMENT_EXCLUDED_CASES  # type: ignore
        from src.debug.debug_reporter import DebugReporter  # type: ignore
        from src.event.score_event_builder import ScoreEventBuilder  # type: ignore
        from src.fetch.easyscore_fetcher import EasyScoreTextFetcher  # type: ignore
        from src.game.day_runner import DayAnalysis  # type: ignore
        from src.neo.game_runner import NeoDayRunner  # type: ignore
        from src.regression.correct_case_saver import CorrectCaseSaver  # type: ignore
        from src.report.day_xlsx_reporter import DayXlsxReporter  # type: ignore
        from src.tools import neo_judgment_gate, neo_pitcher_gate  # type: ignore
        from src.version import VERSION  # type: ignore
        return {
            "excluded": GOLDDATA_EXCLUDED_CASES | NEO_JUDGMENT_EXCLUDED_CASES,
            "DebugReporter": DebugReporter,
            "ScoreEventBuilder": ScoreEventBuilder,
            "EasyScoreTextFetcher": EasyScoreTextFetcher,
            "DayAnalysis": DayAnalysis,
            "NeoDayRunner": NeoDayRunner,
            "CorrectCaseSaver": CorrectCaseSaver,
            "DayXlsxReporter": DayXlsxReporter,
            "neo_judgment_gate": neo_judgment_gate,
            "neo_pitcher_gate": neo_pitcher_gate,
            "VERSION": VERSION,
        }

    def _with_neo_cwd(self, callback):
        old_cwd = Path.cwd()
        os.chdir(str(NEO_PHOENIX_APP_DIR))
        try:
            return callback()
        finally:
            os.chdir(str(old_cwd))

    def _neo_paths(self):
        base = Path(NEO_PHOENIX_APP_DIR)
        return {
            "games": base / "games",
            "html_cache": base / "html_cache",
            "reports": base / "reports",
            "urls": base / "urls" / "_review_window_urls.txt",
            "regression_cases": base / "regression_cases",
        }

    def _clear_neo_tree(self):
        tree = getattr(self, "neo_tree", None)
        if tree is not None:
            for item in tree.get_children():
                tree.delete(item)

    def _clear_neo_checks(self):
        frame = getattr(self, "neo_check_items_frame", None)
        if frame is not None:
            for child in frame.winfo_children():
                child.destroy()
        self.neo_save_vars = {}

    def _clear_neo_work_dirs(self):
        paths = self._neo_paths()
        paths["games"].mkdir(exist_ok=True)
        for path in paths["games"].glob("*.txt"):
            path.unlink()
        paths["html_cache"].mkdir(exist_ok=True)
        for path in paths["html_cache"].glob("*.html"):
            path.unlink()

    def run_neo_embedded_analysis(self):
        try:
            urls = [var.get().strip() for var in self.neo_url_vars if var.get().strip()]
            if not urls:
                raise ValueError("少なくとも1試合分のURLを入力してください。")
            modules = self._load_neo_modules()
            paths = self._neo_paths()
            self.neo_status_var.set("HTML取得とNeo解析を実行中...")
            self.root.update_idletasks()

            def work():
                self._clear_neo_work_dirs()
                paths["urls"].parent.mkdir(exist_ok=True)
                paths["urls"].write_text("\n".join(urls[:3]) + "\n", encoding="utf-8")
                modules["EasyScoreTextFetcher"]().fetch_urls_file(Path("urls") / "_review_window_urls.txt", Path("games"), limit=3)
                day = modules["NeoDayRunner"]().run_folder(Path("games"), pitcher="P", limit=3)
                Path("reports").mkdir(exist_ok=True)
                modules["DayXlsxReporter"]().write(day, Path("reports") / "daily_check.xlsx")
                modules["DebugReporter"]().write(day, Path("reports") / "debug_report.xlsx")
                return day

            self.neo_day = self._with_neo_cwd(work)
            self._populate_neo_results(modules)
            self.neo_status_var.set(
                f"解析完了: {self.neo_day.total_games}試合 / 得点 {self.neo_day.total_scores} / 確認対象 {self.neo_day.total_work_items} / DebugReport作成済み"
            )
        except Exception as exc:
            logging.error(traceback.format_exc())
            self.neo_status_var.set("解析エラーが発生しました。")
            messagebox.showerror(APP_NAME, str(exc))

    def _populate_neo_results(self, modules=None):
        if modules is None:
            modules = self._load_neo_modules()
        self._clear_neo_tree()
        self._clear_neo_checks()
        if not self.neo_day:
            return
        builder = modules["ScoreEventBuilder"]()
        for game in self.neo_day.games:
            var = tk.BooleanVar(value=False)
            self.neo_save_vars[game.game_no] = var
            self.ctk.CTkCheckBox(
                self.neo_check_items_frame,
                text=f"第{game.game_no}試合 {game.game_name}",
                variable=var,
                font=self.font(-1),
            ).pack(side="left", padx=(0, 18), pady=4)

            team_events = builder.build_for_game(game, judgment_source="team")
            pitcher_events = builder.build_for_game(game, judgment_source="pitcher")
            if not pitcher_events:
                self.neo_tree.insert("", "end", values=(game.game_name, "得点なし", "", "", ""))
            for ev in pitcher_events:
                self.neo_tree.insert("", "end", values=(game.game_name, ev.location, builder.label(ev.judgment), ev.reason, ev.runner))
            self._append_neo_team_pitcher_comparison(builder, game, team_events, pitcher_events)
            for half in game.analysis.halves:
                for item in half.review_result.items:
                    if item.level in {"WARN", "ERROR"}:
                        loc = half.title if item.location.startswith(("Actual #", "Virtual #")) else item.location
                        self.neo_tree.insert("", "end", values=(game.game_name, loc, item.level, item.message, ""))

    def _append_neo_team_pitcher_comparison(self, builder, game, team_events, pitcher_events):
        team_earned = sum(1 for ev in team_events if ev.judgment == "自責点")
        by_pitcher = {}
        for ev in pitcher_events:
            pitcher = ev.charged_pitcher or "(責任投手不明)"
            by_pitcher.setdefault(pitcher, {"runs": 0, "earned": 0})
            by_pitcher[pitcher]["runs"] += 1
            if ev.judgment == "自責点":
                by_pitcher[pitcher]["earned"] += 1
        pitcher_earned = sum(row["earned"] for row in by_pitcher.values())
        status = "PASS" if (len(team_events), team_earned) == (len(pitcher_events), pitcher_earned) else "DIFF"
        self.neo_tree.insert("", "end", values=(game.game_name, "Team/Pitcher比較", status, f"Team ER {team_earned} / Pitcher ER {pitcher_earned}", ""))
        for pitcher, row in sorted(by_pitcher.items()):
            self.neo_tree.insert("", "end", values=(game.game_name, "投手別", pitcher, f"失点 {row['runs']} / 自責 {row['earned']}", ""))

    def save_neo_selected(self):
        try:
            if not self.neo_day:
                raise ValueError("先に解析してください。")
            selected = [no for no, var in self.neo_save_vars.items() if var.get()]
            if not selected:
                raise ValueError("保存する試合にチェックを入れてください。")
            modules = self._load_neo_modules()
            memo = self.neo_memo.get("1.0", "end").strip()

            def work():
                saved = modules["CorrectCaseSaver"]().save_day(
                    self.neo_day,
                    Path("games"),
                    Path("reports") / "daily_check.xlsx",
                    memo=memo,
                    html_cache_dir=Path("html_cache"),
                    selected_game_nos=selected,
                )
                return saved

            saved = self._with_neo_cwd(work)
            messagebox.showinfo(APP_NAME, "GoldDataとして保存しました。\n\n" + "\n".join(str(path) for path in saved))
            self.neo_status_var.set(f"GoldData保存完了: {len(saved)}試合")
        except Exception as exc:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(exc))

    def run_neo_saved_regression(self):
        try:
            self.neo_status_var.set("Neo Gate \u691c\u8a3c\u4e2d...")
            self.root.update_idletasks()
            modules = self._load_neo_modules()

            def work():
                team = modules["neo_judgment_gate"].run(Path("regression_cases"), limit_cases=20, limit_diffs=5)
                pitcher = modules["neo_pitcher_gate"].run(Path("regression_cases"), limit_cases=20)
                return team, pitcher

            team, pitcher = self._with_neo_cwd(work)
            passed = team.get("different", 0) == 0 and pitcher.get("failed", 0) == 0
            self._clear_neo_tree()
            excluded = sorted(modules["excluded"])
            self.neo_tree.insert("", "end", values=("Neo saved GoldData gate", "Summary", "PASS" if passed else "FAIL", f"Excluded: {', '.join(excluded) if excluded else '-'}", f"Version {modules['VERSION']}"))
            self.neo_tree.insert("", "end", values=("Neo Team", "regression_cases", "PASS" if team.get("different", 0) == 0 else "FAIL", f"{team.get('matched', 0)}/{team.get('total', 0)}", f"missing={team.get('missing', 0)} extra={team.get('extra', 0)}"))
            self.neo_tree.insert("", "end", values=("Neo Pitcher", "regression_cases", "PASS" if pitcher.get("failed", 0) == 0 else "FAIL", f"{pitcher.get('passed', 0)}/{pitcher.get('total', 0)}", ""))
            for sample in team.get("samples", []):
                self.neo_tree.insert("", "end", values=("Neo Team", sample.get("case", ""), "FAIL", str(sample), ""))
            for sample in pitcher.get("samples", []):
                self.neo_tree.insert("", "end", values=("Neo Pitcher", sample.get("case", ""), "FAIL", str(sample.get("team_diff") or sample.get("pitcher_diff") or ""), ""))
            self.neo_status_var.set(f"Neo Gate {'PASS' if passed else 'FAIL'}")
        except Exception as exc:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(exc))

    def _selected_neo_day(self):
        modules = self._load_neo_modules()
        day = modules["DayAnalysis"]()
        selected = {no for no, var in self.neo_save_vars.items() if var.get()}
        if self.neo_day:
            day.games = [game for game in self.neo_day.games if game.game_no in selected]
        return day

    def create_neo_debug_report(self):
        try:
            if not self.neo_day:
                raise ValueError("先に解析してください。")
            selected = [no for no, var in self.neo_save_vars.items() if var.get()]
            if not selected:
                raise ValueError("DebugReportを作成する試合にチェックを入れてください。")
            modules = self._load_neo_modules()

            def work():
                Path("reports").mkdir(exist_ok=True)
                return modules["DebugReporter"]().write(self._selected_neo_day(), Path("reports") / "debug_report.xlsx")

            out = self._with_neo_cwd(work)
            self.neo_status_var.set(f"DebugReport作成完了: {out}")
            messagebox.showinfo(APP_NAME, f"DebugReportを作成しました。\n\n{out}")
        except Exception as exc:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(exc))

    def open_neo_debug_report(self):
        path = Path(NEO_PHOENIX_APP_DIR) / "reports" / "debug_report.xlsx"
        if not path.exists():
            messagebox.showwarning(APP_NAME, "reports/debug_report.xlsx がまだありません。")
            return
        try:
            os.startfile(str(path))
        except Exception as exc:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(exc))

    def _launch_external_app(self, app_name, app_dir, exe_candidates, script_candidates=None):
        app_dir = Path(app_dir)
        script_candidates = script_candidates or []
        for exe_name in exe_candidates:
            exe_path = app_dir / exe_name
            if exe_path.exists():
                try:
                    subprocess.Popen([str(exe_path)], cwd=str(app_dir), close_fds=True)
                    messagebox.showinfo(APP_NAME, f"{app_name}を起動しました。")
                    return
                except Exception as exc:
                    logging.error(traceback.format_exc())
                    messagebox.showerror(APP_NAME, f"{app_name}の起動に失敗しました。\n\n{exc}")
                    return
        for script_name in script_candidates:
            script_path = app_dir / script_name
            if script_path.exists():
                try:
                    subprocess.Popen([sys.executable, str(script_path)], cwd=str(app_dir), close_fds=True)
                    messagebox.showinfo(APP_NAME, f"{app_name}を起動しました。")
                    return
                except Exception as exc:
                    logging.error(traceback.format_exc())
                    messagebox.showerror(APP_NAME, f"{app_name}の起動に失敗しました。\n\n{exc}")
                    return
        messagebox.showerror(APP_NAME, f"{app_name}の実体が見つかりません。\n\n{app_dir}")

    def open_external_folder(self, folder):
        folder = Path(folder)
        if not folder.exists():
            messagebox.showerror(APP_NAME, f"フォルダが見つかりません。\n\n{folder}")
            return
        try:
            os.startfile(str(folder))
        except Exception as exc:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(exc))

    def open_player_roster_system(self):
        self._launch_external_app(
            "大学名簿統合システム",
            UNIVERSITY_ROSTER_APP_DIR,
            ["dist/大学名簿統合システム.exe", "大学名簿統合システム.exe"],
            ["main.py"],
        )

    def open_neo_phoenix(self):
        self._launch_external_app(
            "NeoPhoenix",
            NEO_PHOENIX_APP_DIR,
            ["dist/NeoPhoenix_Developer.exe", "NeoPhoenix_Developer.exe", "dist/NeoPhoenix.exe", "NeoPhoenix.exe"],
            ["neo_ctk_review_window.py"],
        )

    def _show_progress_dialog(self, title, message):
        self._close_progress_dialog()
        dialog = self.ctk.CTkToplevel(self.root)
        dialog.title(title)
        dialog.geometry("560x210")
        dialog.transient(self.root)
        dialog.attributes("-topmost", True)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        self.ctk.CTkLabel(dialog, text=title, font=self.font(4, "bold")).grid(row=0, column=0, sticky="w", padx=22, pady=(22, 8))
        label = self.ctk.CTkLabel(dialog, text=message, font=self.font(), anchor="w", justify="left", wraplength=500)
        label.grid(row=1, column=0, sticky="ew", padx=22, pady=(8, 4))
        self.ctk.CTkProgressBar(dialog, mode="indeterminate").grid(row=2, column=0, sticky="ew", padx=22, pady=(18, 8))
        progress = dialog.grid_slaves(row=2, column=0)[0]
        progress.start()
        self._progress_dialog = dialog
        self._progress_label = label
        dialog.lift()
        dialog.focus_force()
        self.root.update_idletasks()
        self.root.update()

    def _update_progress_dialog(self, message):
        label = getattr(self, "_progress_label", None)
        dialog = getattr(self, "_progress_dialog", None)
        if label is not None and dialog is not None:
            label.configure(text=message)
            try:
                dialog.attributes("-topmost", True)
                dialog.lift()
            except Exception:
                pass
            self.root.update_idletasks()
            self.root.update()

    def _close_progress_dialog(self):
        dialog = getattr(self, "_progress_dialog", None)
        if dialog is not None:
            try:
                dialog.grab_release()
            except Exception:
                pass
            try:
                dialog.destroy()
            except Exception:
                pass
        self._progress_dialog = None
        self._progress_label = None

    def _load_defaults(self):
        self.font_size_var.set(str(self.ui_font_size))
        self.wp_new_post_url_var.set(self.config_data.get("wp_new_post_url", "https://chugoku.junko.or.jp/wp-admin/post-new.php"))
        self.media_new_url_var.set(self.config_data.get("media_new_url", "https://chugoku.junko.or.jp/wp-admin/media-new.php"))
        self.media_base_url_var.set(self.config_data.get("media_base_url", "https://chugoku.junko.or.jp/wp-content/uploads"))
        self.eleague_url_var.set(self.config_data.get("eleague_url", DEFAULT_ELEAGUE_URL))
        self.dify_api_url_var.set(self.config_data.get("dify_api_url", ""))
        self.dify_api_key_var.set(self.config_data.get("dify_api_key", ""))
        self.dify_prompt_var.set(self.config_data.get("dify_prompt", ""))
        legacy_cup = extract_cup_id(self.config_data.get("eleague_url", "")) or extract_cup_id(self.config_data.get("cup_id", ""))
        self.eleague_cup_id_1_var.set(self.config_data.get("eleague_cup_id_1", legacy_cup))
        self.eleague_cup_id_2_var.set(self.config_data.get("eleague_cup_id_2", ""))
        self.eleague_cup_id_3_var.set(self.config_data.get("eleague_cup_id_3", ""))
        self.year_var.set(self.config_data.get("year", str(datetime.now().year)))
        self.season_var.set(self.config_data.get("season", "春季"))
        self.division_var.set(self.config_data.get("division", "１部"))
        self.review_division_var.set(self.config_data.get("review_division", "１部"))
        self.review_cup_id_var.set(self.config_data.get("review_cup_id", ""))
        self.review_date_var.set(self.config_data.get("review_date", ""))
        self.review_title_var.set(self.config_data.get("review_title", ""))
        for idx, var in enumerate(getattr(self, "review_game_id_vars", []), start=1):
            var.set(self.config_data.get(f"review_game_id_{idx}", ""))
        self._set_text("review_chatgpt_text", self.config_data.get("review_chatgpt_text", ""))
        self.standings_division_var.set(self.config_data.get("standings_division", self.config_data.get("division", "１部")))
        self.awards_division_var.set(self.config_data.get("awards_division", "１部"))
        saved_league = self.config_data.get("league_name", "")
        self.league_var.set(strip_league_division_suffix(saved_league) or make_base_league_name(self.year_var.get().strip(), self.season_var.get()))
        self.eleague_title_var.set(self.config_data.get("eleague_title", self.league_var.get()))
        initial_auto_id = make_tournament_id(self.year_var.get().strip(), self.season_var.get(), self.division_var.get())
        self.tournament_id_var.set(initial_auto_id)
        self._last_auto_tournament_id = initial_auto_id
        self.schedule_excel_file_var.set(self.config_data.get("schedule_excel_file", ""))
        self.schedule_title_var.set(self.config_data.get("schedule_title", ""))
        self.schedule_download_url_var.set(self.config_data.get("schedule_download_url", ""))
        self._set_text("dates_text", self.config_data.get("dates", ""))
        self._set_text("standings_text", self.config_data.get("standings_text", self.config_data.get("result_text", "")))
        self._set_text("awards_text", self.config_data.get("awards_text", ""))
        if hasattr(self, "roster_mode_var"):
            self.roster_mode_var.set(self.config_data.get("roster_mode", "all"))
            self.roster_input_folder_var.set(self.config_data.get("roster_input_folder", ""))
            self.roster_single_file_var.set(self.config_data.get("roster_single_file", ""))
            self.roster_output_file_var.set(self.config_data.get("roster_output_file", ""))
            self.roster_overwrite_var.set(bool(self.config_data.get("roster_overwrite", True)))
        self.update_schedule_title()
        self.auto_fill_tournament(show_message=False)
        self.apply_remembered_schedule_dates()
        self.update_review_cup_id()
        self.update_review_date_options()
        self.update_review_title()

    def _get_text(self, name):
        widget = self.vars[name]
        return widget.get("1.0", "end").strip()

    def _set_text(self, name, value):
        widget = self.vars.get(name)
        if widget is not None:
            widget.delete("1.0", "end")
            widget.insert("1.0", value or "")

    def toggle_sidebar(self):
        self.sidebar_open = not self.sidebar_open
        if self.sidebar_open:
            self.sidebar.grid(row=0, column=0, sticky="nsew")
        else:
            self.sidebar.grid_remove()

    def show_page(self, name):
        self.current_page = name
        for page in self.pages.values():
            page.grid_remove()
        self.pages[name].grid(row=0, column=0, sticky="nsew")
        self.page_title.configure(text=f"{name}\u3000\u7de8\u96c6\u753b\u9762")
        for page_name, btn in self.nav_buttons.items():
            btn.configure(fg_color=("#1f6aa5" if page_name == name else "#3b8ed0"))
        if name == "\u8a66\u5408\u901f\u5831":
            self.set_auto_text_var(
                self.league_var,
                make_base_league_name(self.year_var.get().strip(), self.season_var.get()),
                "_last_auto_league_title",
            )
            self.apply_remembered_schedule_dates()
        elif name == "寸評追加":
            self.update_review_cup_id()
            self.update_review_date_options()
            self.update_review_title()
        elif name == "\u9806\u4f4d\u8868":
            self.on_standings_division_changed(self.standings_division_var.get())
        elif name == "\u500b\u4eba\u8cde":
            self.on_awards_division_changed(self.awards_division_var.get())
            self.sync_awards_text_from_standings()
        elif name == "E-League":
            self.set_auto_text_var(
                self.eleague_title_var,
                make_base_league_name(self.year_var.get().strip(), self.season_var.get()),
                "_last_auto_eleague_title",
            )

    def set_auto_text_var(self, var, auto_value, attr_name):
        current = var.get().strip()
        previous = getattr(self, attr_name, "")
        if not current or current == previous:
            var.set(auto_value)
        setattr(self, attr_name, auto_value)

    def update_schedule_title(self):
        self.set_auto_text_var(
            self.schedule_title_var,
            make_schedule_title(self.year_var.get().strip(), self.season_var.get()),
            "_last_auto_schedule_title",
        )
        if hasattr(self, "eleague_title_var"):
            self.set_auto_text_var(
                self.eleague_title_var,
                make_base_league_name(self.year_var.get().strip(), self.season_var.get()),
                "_last_auto_eleague_title",
            )

    def on_season_changed(self, value=None):
        self.update_schedule_title()
        base = make_base_league_name(self.year_var.get().strip(), self.season_var.get())
        if self.current_page == "\u9806\u4f4d\u8868":
            self.on_standings_division_changed(self.standings_division_var.get())
        elif self.current_page == "\u500b\u4eba\u8cde":
            self.on_awards_division_changed(self.awards_division_var.get())
        else:
            self.set_auto_text_var(self.league_var, base, "_last_auto_league_title")
            self.ensure_tournament_id()

    def auto_fill_tournament(self, show_message=True):
        year = self.year_var.get().strip()
        season = self.season_var.get()
        auto_title = make_base_league_name(year, season)
        self.league_var.set(auto_title)
        self._last_auto_league_title = auto_title
        self.ensure_tournament_id()
        if show_message:
            messagebox.showinfo(APP_NAME, "\u5927\u4f1a\u540d\u3068\u5927\u4f1aID\u3092\u751f\u6210\u3057\u307e\u3057\u305f\u3002")

    def ensure_tournament_id(self):
        year = self.year_var.get().strip()
        season = self.season_var.get()
        division = self.division_var.get()
        new_tournament_id = make_tournament_id(year, season, division)
        current_tournament_id = self.tournament_id_var.get().strip()
        if not current_tournament_id or current_tournament_id == self._last_auto_tournament_id:
            self.tournament_id_var.set(new_tournament_id)
            self._last_auto_tournament_id = new_tournament_id

    def prepare_tournament_for_generation(self):
        if not self.league_var.get().strip():
            self.auto_fill_tournament(show_message=False)
        else:
            self.ensure_tournament_id()

    def sync_awards_text_from_standings(self):
        if self._get_text("awards_text"):
            return
        standings_text = self._get_text("standings_text")
        if standings_text:
            self._set_text("awards_text", standings_text)

    def set_editing_division(self, division):
        self.division_var.set(division)
        year = self.year_var.get().strip()
        season = self.season_var.get()
        auto_base = make_base_league_name(year, season)
        auto_division_title = make_league_name(year, season, division)
        current = self.league_var.get().strip()
        previous = getattr(self, "_last_auto_league_title", "")
        if not current or current in (auto_base, previous):
            self.league_var.set(auto_division_title)
        self._last_auto_league_title = auto_division_title
        self.ensure_tournament_id()

    def on_standings_division_changed(self, value=None):
        self.set_editing_division(value or self.standings_division_var.get())

    def on_awards_division_changed(self, value=None):
        self.set_editing_division(value or self.awards_division_var.get())

    def on_review_division_changed(self, value=None):
        self.update_review_cup_id()
        self.update_review_date_options()
        self.update_review_title()
        self.persist_settings()

    def on_review_date_changed(self, value=None):
        self.update_review_title()
        self.persist_settings()

    def on_division_changed(self):
        self.auto_fill_tournament(show_message=False)
        self.apply_remembered_schedule_dates()

    def review_division_key(self):
        return division_key_from_label(self.review_division_var.get())

    def default_review_cup_id(self, key=None):
        key = key or self.review_division_key()
        return {
            "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
            "3": extract_cup_id(self.eleague_cup_id_3_var.get()),
        }.get(key, "")

    def update_review_cup_id(self):
        if not hasattr(self, "review_cup_id_var"):
            return
        auto_cup_id = self.default_review_cup_id()
        current = extract_cup_id(self.review_cup_id_var.get())
        previous = getattr(self, "_last_auto_review_cup_id", "")
        if auto_cup_id and (not current or current == previous):
            self.review_cup_id_var.set(auto_cup_id)
        self._last_auto_review_cup_id = auto_cup_id

    def review_dates_for_key(self, key):
        text = self.config_data.get(f"schedule_dates_{key}", "").strip()
        if not text:
            return []
        try:
            return parse_dates_with_default_year(text, int(self.year_var.get().strip()))
        except Exception:
            return []

    def update_review_date_options(self):
        if not hasattr(self, "review_date_menu"):
            return
        key = self.review_division_key()
        dates = self.review_dates_for_key(key)
        values = [d.strftime("%Y/%m/%d") for d in dates] or [""]
        current = normalize_review_date_label(self.review_date_var.get())
        if current not in values:
            current = values[0]
            self.review_date_var.set(current)
        try:
            self.review_date_menu.configure(values=values)
        except Exception:
            pass

    def update_review_title(self):
        if not hasattr(self, "review_title_var"):
            return
        key = self.review_division_key()
        selected = normalize_review_date_label(self.review_date_var.get())
        dates = self.review_dates_for_key(key)
        date_labels = [d.strftime("%Y/%m/%d") for d in dates]
        if selected and selected in date_labels:
            index = date_labels.index(selected) + 1
            total = len(date_labels)
            if index == 1:
                day_label = "初日"
            elif index == total:
                day_label = "最終日"
            else:
                day_label = f"{index}日目"
        else:
            day_label = "初日"
        base = make_base_league_name(self.year_var.get().strip(), self.season_var.get())
        league = league_name_with_division(base, key)
        auto_title = f"{league}　{day_label}"
        current = self.review_title_var.get().strip()
        previous = getattr(self, "_last_auto_review_title", "")
        if not current or current == previous:
            self.review_title_var.set(auto_title)
        self._last_auto_review_title = auto_title

    def remembered_schedule_dates_text(self):
        parts = []
        for key in ("1", "2", "3"):
            text = self.config_data.get(f"schedule_dates_{key}", "").strip()
            if text:
                parts.append(f"[{division_label_from_key(key)}]\n{text}")
        return "\n\n".join(parts)

    def apply_remembered_schedule_dates(self, force=False):
        remembered = self.remembered_schedule_dates_text()
        if not remembered:
            return
        current = self._get_text("dates_text")
        if not force and current and current != self._last_autofilled_dates_text:
            return
        self._set_text("dates_text", remembered)
        self._last_autofilled_dates_text = remembered

    def remember_schedule_dates_from_excel(self, excel_text):
        dates_by_division = collect_schedule_dates_by_division(excel_text, int(self.year_var.get().strip()))
        if dates_by_division["1"]:
            self.config_data["schedule_dates_1"] = dates_to_text(dates_by_division["1"])
        if dates_by_division["2"]:
            self.config_data["schedule_dates_2"] = dates_to_text(dates_by_division["2"])
        if dates_by_division["3"]:
            self.config_data["schedule_dates_3"] = dates_to_text(dates_by_division["3"])
        return dates_by_division

    def select_schedule_excel_file(self):
        file = filedialog.askopenfilename(
            title="日程表Excelファイルを選択",
            filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")],
        )
        if not file:
            return
        self.schedule_excel_file_var.set(app_path_text(file))
        try:
            excel_text = load_xlsx_schedule_text(file)
            self.remember_schedule_dates_from_excel(excel_text)
            self.update_review_date_options()
            self.update_review_title()
            self.schedule_download_url_var.set(self.default_download_url(file))
            messagebox.showinfo(APP_NAME, "日程表Excelファイルを読み込みました。")
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def default_download_url(self, file, pub_dt=None):
        base = self.media_base_url_var.get().strip().rstrip("/")
        if not base:
            return ""
        pub_dt = pub_dt or datetime.now()
        path = Path(file)
        download_name = f"{path.stem}-{path.name}"
        return f"{base}/{pub_dt.year}/{pub_dt.strftime('%m')}/{download_name}"

    def _eleague_create_url(self, year):
        eleague_url = (self.eleague_url_var.get().strip() or DEFAULT_ELEAGUE_URL).rstrip("/")
        if not (eleague_url.startswith("http://") or eleague_url.startswith("https://")):
            raise ValueError("E-League URLは http:// または https:// から入力してください。")
        return re.sub(r"/new/\d{4}/?$", "", eleague_url).rstrip("/") + f"/new/{year}"

    def _eleague_league_url(self):
        eleague_url = (self.eleague_url_var.get().strip() or DEFAULT_ELEAGUE_URL).rstrip("/")
        if not (eleague_url.startswith("http://") or eleague_url.startswith("https://")):
            raise ValueError("E-League URLは http:// または https:// から入力してください。")
        eleague_url = re.sub(r"/new/\d{4}/?$", "", eleague_url).rstrip("/")
        eleague_url = re.sub(r"/cup/\d+.*$", "", eleague_url).rstrip("/")
        return eleague_url or DEFAULT_ELEAGUE_URL

    def _eleague_create_dates_by_division(self, year):
        excel_file = self.schedule_excel_file_var.get().strip()
        excel_path = app_path(excel_file)
        if excel_path and excel_path.exists():
            return collect_schedule_dates_by_division(load_xlsx_schedule_text(str(excel_path)), int(year))

        dates_by_division = {"1": [], "2": [], "3": []}
        for key in dates_by_division:
            saved = self.config_data.get(f"schedule_dates_{key}", "").strip()
            if saved:
                dates_by_division[key] = parse_dates_with_default_year(saved, int(year))
        return dates_by_division

    def _eleague_create_payloads(self):
        year = self.year_var.get().strip()
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError("日程画面の作成年度は西暦4桁で入力してください。")
        dates_by_division = self._eleague_create_dates_by_division(year)
        season = self.season_var.get()
        title_base = eleague_title_base(self.eleague_title_var.get().strip(), year, season)
        payloads = []
        missing = []
        for key in ("1", "2", "3"):
            dates = dates_by_division.get(key) or []
            label = division_label_from_key(key)
            if not dates:
                missing.append(label)
                continue
            start = min(dates)
            end = max(dates)
            payloads.append({
                "division_key": key,
                "division": label,
                "year": year,
                "season": season,
                "season_type": season_label(season),
                "name": eleague_name_with_division(title_base, key),
                "start": start.strftime("%Y/%m/%d"),
                "end": end.strftime("%Y/%m/%d"),
                "start_iso": start.strftime("%Y-%m-%d"),
                "end_iso": end.strftime("%Y-%m-%d"),
            })
        if missing:
            raise ValueError(
                "日程編集画面で次の区分の日程を取得してください: " + "、".join(missing)
            )
        return payloads

    def _eleague_team_count_by_division(self, year):
        excel_file = self.schedule_excel_file_var.get().strip()
        excel_path = app_path(excel_file)
        if not excel_path or not excel_path.exists():
            return {}
        excel_text = load_xlsx_schedule_text(str(excel_path))
        counts = {}
        for key in ("1", "2", "3"):
            teams = []
            for game in collect_eleague_schedule_games(excel_text, int(year), key):
                for team in (game.get("team1", ""), game.get("team2", "")):
                    team = (team or "").strip()
                    if team and team not in teams:
                        teams.append(team)
            if teams:
                counts[key] = len(teams)
        return counts

    def _eleague_venues_by_division(self, year):
        excel_file = self.schedule_excel_file_var.get().strip()
        excel_path = app_path(excel_file)
        if not excel_path or not excel_path.exists():
            return {}
        excel_text = load_xlsx_schedule_text(str(excel_path))
        venues_by_division = {}
        all_venues = collect_all_schedule_venues(excel_text, int(year))
        for key in ("1", "2", "3"):
            venues = []
            for game in collect_eleague_schedule_games(excel_text, int(year), key):
                venue = (game.get("venue") or "").strip()
                if venue and venue not in venues:
                    venues.append(venue)
            if key == "3":
                for venue in collect_playoff_schedule_venues(excel_text):
                    if venue and venue not in venues:
                        venues.append(venue)
                if not venues:
                    venues = list(all_venues)
            if venues:
                venues_by_division[key] = venues
        return venues_by_division

    def _eleague_tournament_id_for_key(self, key, default_value=""):
        saved = (self.config_data.get(f"eleague_tournament_id_{key}", "") or "").strip()
        if saved:
            return saved
        if default_value:
            return default_value
        year = self.year_var.get().strip()
        season = self.season_var.get()
        return make_tournament_id(year, season, division_label_from_key(key))

    def _set_eleague_tournament_id_for_key(self, key, value):
        value = (value or "").strip()
        if not value:
            return
        self.config_data[f"eleague_tournament_id_{key}"] = value
        self.persist_settings()

    def _eleague_edit_payloads(self):
        year = self.year_var.get().strip()
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError("日程画面の作成年度は西暦4桁で入力してください。")
        team_counts = self._eleague_team_count_by_division(year)
        cup_ids = {
            "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
            "3": extract_cup_id(self.eleague_cup_id_3_var.get()),
        }
        defaults = {"1": 6, "2": 6, "3": 4}
        payloads = []
        missing = []
        for key in ("1", "2", "3"):
            label = division_label_from_key(key)
            cup_id = cup_ids.get(key, "")
            if not cup_id:
                missing.append(label)
                continue
            payloads.append({
                "division_key": key,
                "division": label,
                "cup_id": cup_id,
                "game_method": "1" if key == "3" else "0",
                "game_method_label": "トーナメント" if key == "3" else "リーグ",
                "teams_num": str(defaults[key] if key == "3" else (team_counts.get(key) or defaults[key])),
                "inputters": ["入力用#1中国地区", "入力用#2中国地区"],
            })
        if missing:
            raise ValueError("次の区分のCupIDを取得してください: " + "、".join(missing))
        return payloads

    def _eleague_stage3_payloads(self):
        year = self.year_var.get().strip()
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError("日程画面の作成年度は西暦4桁で入力してください。")
        cup_ids = {
            "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
            "3": extract_cup_id(self.eleague_cup_id_3_var.get()),
        }
        venues_by_division = self._eleague_venues_by_division(year)
        payloads = []
        missing_cups = []
        missing_venues = []
        for key in ("1", "2", "3"):
            label = division_label_from_key(key)
            cup_id = cup_ids.get(key, "")
            if not cup_id:
                missing_cups.append(label)
                continue
            venues = venues_by_division.get(key, [])
            if not venues:
                missing_venues.append(label)
            base_id = make_tournament_id(year, self.season_var.get(), label)
            payloads.append({
                "division_key": key,
                "division": label,
                "cup_id": cup_id,
                "venues": venues,
                "tournament_id": self._eleague_tournament_id_for_key(key, base_id),
                "tournament_id_base": base_id,
            })
        if missing_cups:
            raise ValueError("次の区分のCupIDを取得してください: " + "、".join(missing_cups))
        if missing_venues:
            raise ValueError("日程表Excelから次の区分の球場を取得できません: " + "、".join(missing_venues))
        return payloads

    def _eleague_stage5_payloads(self):
        year = self.year_var.get().strip()
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError("日程画面の作成年度は西暦4桁で入力してください。")
        excel_file = self.schedule_excel_file_var.get().strip()
        excel_path = app_path(excel_file)
        if not excel_path or not excel_path.exists():
            raise ValueError("日程編集画面で日程表Excelファイルを選択してください。")
        excel_text = load_xlsx_schedule_text(str(excel_path))
        cup_ids = {
            "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
        }
        payloads = []
        missing_cups = []
        missing_teams = []
        for key in ("1", "2"):
            label = division_label_from_key(key)
            cup_id = cup_ids.get(key, "")
            if not cup_id:
                missing_cups.append(label)
                continue
            team_names = collect_eleague_team_names(excel_text, int(year), key)
            if not team_names:
                missing_teams.append(label)
                continue
            payloads.append({
                "division_key": key,
                "division": label,
                "cup_id": cup_id,
                "team_names": team_names,
                "teams_num": str(len(team_names)),
            })
        if missing_cups:
            raise ValueError("次の区分のCupIDを取得してください: " + "、".join(missing_cups))
        if missing_teams:
            raise ValueError("日程表Excelから次の区分のチーム名を取得できません: " + "、".join(missing_teams))
        return payloads

    def _eleague_stage6_payloads(self):
        year = self.year_var.get().strip()
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError("日程画面の作成年度は西暦4桁で入力してください。")
        cup_ids = {
            "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
        }
        venues_by_division = self._eleague_venues_by_division(year)
        inputters = {
            "1": "入力用#1中国地区",
            "2": "入力用#2中国地区",
        }
        payloads = []
        missing_cups = []
        missing_venues = []
        for key in ("1", "2"):
            label = division_label_from_key(key)
            cup_id = cup_ids.get(key, "")
            if not cup_id:
                missing_cups.append(label)
                continue
            venues = venues_by_division.get(key, [])
            if not venues:
                missing_venues.append(label)
                continue
            payloads.append({
                "division_key": key,
                "division": label,
                "cup_id": cup_id,
                "venues": venues,
                "inputter": inputters[key],
            })
        if missing_cups:
            raise ValueError("次の区分のCupIDを取得してください: " + "、".join(missing_cups))
        if missing_venues:
            raise ValueError("日程表Excelから次の区分の球場を取得できません: " + "、".join(missing_venues))
        return payloads

    def _eleague_autofill_create_form(self, driver, payload):
        return driver.execute_async_script(
            r'''
const payload = arguments[0];
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", filled:[], clicked:false};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function norm(value) {
  return String(value || "").replace(/[\s　\u200b\u200c\ufeff:：]/g, "").toLowerCase();
}
function textOf(el) { return (el.innerText || el.textContent || "").trim(); }
function setValue(el, value) {
  value = String(value || "");
  el.scrollIntoView({block:"center", inline:"center"});
  el.focus();
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, "value")
    || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")
    || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
  if (el._valueTracker) el._valueTracker.setValue(el.value);
  if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:value}));
  el.dispatchEvent(new Event("change", {bubbles:true}));
  el.blur();
}
function labelTextFor(field) {
  const id = field.id;
  let texts = [];
  if (id) texts.push(...[...document.querySelectorAll(`label[for="${CSS.escape(id)}"]`)].map(textOf));
  let node = field;
  for (let depth = 0; node && depth < 5; depth++, node = node.parentElement) {
    texts.push(textOf(node));
  }
  return texts.join(" ");
}
function findInput(labels, index=0) {
  const wanted = labels.map(norm);
  const fields = [...document.querySelectorAll("input, textarea")].filter(visible);
  const hits = fields.filter(field => {
    const hay = norm([
      field.name,
      field.id,
      field.placeholder,
      field.getAttribute("aria-label"),
      labelTextFor(field),
    ].join(" "));
    return wanted.some(label => hay.includes(label));
  });
  return hits[index] || null;
}
function setByLabel(labels, value, note, index=0) {
  const field = findInput(labels, index);
  if (!field) return false;
  const actual = field.type === "date" && /^\d{4}\/\d{2}\/\d{2}$/.test(value)
    ? value.replaceAll("/", "-")
    : value;
  setValue(field, actual);
  result.filled.push(note);
  return true;
}
function setBySelector(selector, value, note) {
  const field = document.querySelector(selector);
  if (!visible(field)) return false;
  setValue(field, value);
  result.filled.push(note);
  return true;
}
function describeField(field) {
  return norm([
    field.type,
    field.name,
    field.id,
    field.placeholder,
    field.getAttribute("aria-label"),
    labelTextFor(field),
  ].join(" "));
}
function setTournamentNameFallback() {
  const fields = [...document.querySelectorAll("input, textarea")].filter(visible).filter(field => {
    if (field.disabled || field.readOnly) return false;
    if (["hidden", "date", "checkbox", "radio", "button", "submit"].includes(field.type)) return false;
    const hay = describeField(field);
    if (hay.includes("年度") || hay.includes("year") || hay.includes("開始") || hay.includes("終了")) return false;
    if (hay.includes("開催期間") || hay.includes("期間") || hay.includes("start") || hay.includes("end")) return false;
    if (String(field.value || "").trim() === String(payload.year || "").trim()) return false;
    return true;
  });
  const emptyField = fields.find(field => !String(field.value || "").trim());
  const field = emptyField || fields[0];
  if (!field) return false;
  setValue(field, payload.name);
  result.filled.push("大会名");
  return true;
}
function setNativeSelect(selector, values, note) {
  const select = document.querySelector(selector);
  if (!visible(select) || select.tagName !== "SELECT") return false;
  const valueNorms = values.map(norm);
  const option = [...select.options].find(opt => valueNorms.some(v => norm(opt.textContent).includes(v) || norm(opt.value).includes(v)));
  if (!option) return false;
  select.value = option.value;
  select.dispatchEvent(new Event("input", {bubbles:true}));
  select.dispatchEvent(new Event("change", {bubbles:true}));
  result.filled.push(note);
  return true;
}
function clickButtonText(values, note) {
  const valueNorms = values.map(norm);
  const buttons = [...document.querySelectorAll("button, [role='button']")].filter(visible);
  const button = buttons.find(btn => {
    const text = norm(textOf(btn));
    return valueNorms.some(v => text.includes(v) || v.includes(text));
  });
  if (!button) return false;
  button.scrollIntoView({block:"center", inline:"center"});
  button.click();
  result.filled.push(note);
  return true;
}
async function chooseByLabel(labels, values, note) {
  const wanted = labels.map(norm);
  const valueNorms = values.map(norm);
  const controls = [...document.querySelectorAll('[role="button"], [aria-haspopup="listbox"], .MuiSelect-select, select')]
    .filter(visible);
  let control = controls.find(el => {
    const hay = norm([el.id, el.getAttribute("aria-label"), textOf(el), labelTextFor(el)].join(" "));
    return wanted.some(label => hay.includes(label));
  });
  if (!control) return false;
  if (control.tagName === "SELECT") {
    const option = [...control.options].find(opt => valueNorms.some(v => norm(opt.textContent).includes(v) || norm(opt.value).includes(v)));
    if (!option) return false;
    control.value = option.value;
    control.dispatchEvent(new Event("change", {bubbles:true}));
    result.filled.push(note);
    return true;
  }
  control.scrollIntoView({block:"center", inline:"center"});
  control.click();
  await sleep(350);
  const options = [...document.querySelectorAll('li[role="option"], [role="option"], li.MuiMenuItem-root')]
    .filter(visible);
  const option = options.find(opt => {
    const text = norm(textOf(opt));
    return valueNorms.some(v => text.includes(v) || v.includes(text));
  });
  if (!option) return false;
  option.click();
  result.filled.push(note);
  await sleep(200);
  return true;
}
function clickRegister() {
  const buttons = [...document.querySelectorAll('button, [role="button"]')].filter(visible);
  const btn = buttons.find(el => /登録/.test(textOf(el)) && /[+＋]/.test(textOf(el)))
    || buttons.find(el => /^登録$|登録する|保存/.test(textOf(el)));
  if (!btn) return false;
  btn.scrollIntoView({block:"center", inline:"center"});
  btn.click();
  result.clicked = true;
  return true;
}
async function waitForCreateFields() {
  for (let i = 0; i < 50; i++) {
    if (visible(document.querySelector('input[name="cupName"]'))
        || visible(document.querySelector('input[name="beginDate"]'))
        || visible(document.querySelector('input[name="endDate"]'))) {
      return true;
    }
    await sleep(200);
  }
  return false;
}
function fieldDebugText() {
  const fields = [...document.querySelectorAll("input, textarea, select")].filter(visible).slice(0, 12);
  if (!fields.length) return "候補入力欄なし";
  return fields.map(field => {
    const bits = [
      field.tagName.toLowerCase(),
      field.type ? "type=" + field.type : "",
      field.name ? "name=" + field.name : "",
      field.id ? "id=" + field.id : "",
      field.value ? "value=" + String(field.value).slice(0, 20) : "",
    ].filter(Boolean);
    return bits.join(" ");
  }).join(" / ");
}
(async () => {
  try {
    await waitForCreateFields();
    setBySelector('input[name="cupName"]', payload.name, "大会名")
      || setByLabel(["大会名", "大会名称", "名称", "大会タイトル", "タイトル", "リーグ名", "name", "title", "tournament", "cup"], payload.name, "大会名")
      || setTournamentNameFallback();
    const periodFields = [...document.querySelectorAll("input, textarea")].filter(visible).filter(field => {
      const hay = norm([field.name, field.id, field.placeholder, field.getAttribute("aria-label"), labelTextFor(field)].join(" "));
      return hay.includes("開催期間") || hay.includes("期間") || hay.includes("開始") || hay.includes("終了")
        || hay.includes("start") || hay.includes("end") || field.type === "date";
    });
    if (setBySelector('input[name="beginDate"]', payload.start, "開始日")
        && setBySelector('input[name="endDate"]', payload.end, "終了日")) {
      result.filled.push("開催期間");
    } else if (periodFields.length >= 2) {
      setValue(periodFields[0], periodFields[0].type === "date" ? payload.start_iso : payload.start);
      setValue(periodFields[1], periodFields[1].type === "date" ? payload.end_iso : payload.end);
      result.filled.push("開催期間");
    } else {
      setByLabel(["開始", "start"], payload.start, "開始日");
      setByLabel(["終了", "end"], payload.end, "終了日");
    }
    clickButtonText([payload.season_type, payload.season], "大会種別")
      || await chooseByLabel(["大会種別", "設定パターン"], [payload.season_type, payload.season], "大会種別");
    setNativeSelect('select[name="cupAttr"]', ["準硬式", "3"], "種別")
      || await chooseByLabel(["種別", "競技種別"], ["準硬式"], "種別");
    if (!result.filled.some(x => x === "大会名")) throw new Error("大会名入力欄を検出できません: " + fieldDebugText());
    if (!result.filled.some(x => x === "開催期間" || x === "開始日")) throw new Error("開催期間入力欄を検出できません: " + fieldDebugText());
    if (!clickRegister()) throw new Error("登録ボタンを検出できません");
    result.ok = true;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
            payload,
        )

    def _eleague_open_tournament_from_league(self, driver, tournament_name):
        return driver.execute_async_script(
            r'''
const target = arguments[0];
const done = arguments[arguments.length - 1];
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) {
  return (el && (el.innerText || el.textContent) || "").trim();
}
function norm(value) {
  return String(value || "").replace(/[\s　\u200b\u200c\ufeff:：()（）]/g, "").toLowerCase();
}
const targetNorm = norm(target);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function currentRows() {
  return [...document.querySelectorAll("tbody tr, tr, .MuiTableRow-root")].filter(visible);
}
(async () => {
  for (let i = 0; i < 75; i++) {
    const rows = currentRows();
    const row = rows.find(tr => norm(textOf(tr)).includes(targetNorm));
    if (row) {
      const editButton = row.querySelector(".btn-edit")
        || [...row.querySelectorAll("button, [role='button']")].find(btn => visible(btn));
      if (!editButton) {
        done({ok:false, message:"大会行の編集ボタンを検出できません: " + textOf(row).replace(/\s+/g, " ").slice(0, 160)});
        return;
      }
      editButton.scrollIntoView({block:"center", inline:"center"});
      editButton.click();
      done({ok:true});
      return;
    }
    await sleep(200);
  }
  const rows = currentRows();
  const samples = rows.slice(0, 10).map(tr => textOf(tr).replace(/\s+/g, " ").slice(0, 140));
  done({ok:false, message:"大会行を検出できません: " + samples.join(" / ")});
})();
''',
            tournament_name,
        )

    def _eleague_fetch_cup_ids_from_league(self, driver, WebDriverWait, payloads):
        league_url = self._eleague_league_url()

        def wait_ready(timeout=60):
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
            )

        cup_ids = {}
        failures = []
        for payload in payloads:
            driver.get(league_url)
            wait_ready()
            WebDriverWait(driver, 30).until(
                lambda d: d.execute_script("return !!document.body && (document.body.innerText || document.body.textContent || '').length > 0")
            )
            result = self._eleague_open_tournament_from_league(driver, payload["name"])
            if not result or not result.get("ok"):
                failures.append(f"{payload['division']}: {(result or {}).get('message', result)}")
                continue
            try:
                WebDriverWait(driver, 20).until(lambda d: extract_cup_id(d.current_url))
                cup_id = extract_cup_id(driver.current_url)
            except Exception:
                cup_id = extract_cup_id(driver.current_url)
            if cup_id:
                cup_ids[payload["division_key"]] = cup_id
            else:
                failures.append(f"{payload['division']}: CupIDをURLから取得できません ({driver.current_url})")

        if cup_ids.get("1"):
            self.eleague_cup_id_1_var.set(cup_ids["1"])
        if cup_ids.get("2"):
            self.eleague_cup_id_2_var.set(cup_ids["2"])
        if cup_ids.get("3"):
            self.eleague_cup_id_3_var.set(cup_ids["3"])
        if cup_ids:
            self.persist_settings()
        return cup_ids, failures

    def fetch_eleague_cup_ids(self):
        try:
            payloads = self._eleague_create_payloads()
            self.persist_settings()
            driver, WebDriverWait = self._get_wp_driver()
            cup_ids, failures = self._eleague_fetch_cup_ids_from_league(driver, WebDriverWait, payloads)
            focus_chrome_window(driver)
            lines = []
            labels = {"1": "１部", "2": "２部", "3": "入替戦"}
            for key in ("1", "2", "3"):
                if cup_ids.get(key):
                    lines.append(f"{labels[key]}: {cup_ids[key]}")
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    "CupID取得を実行しました。\n\n"
                    f"取得:\n{chr(10).join(lines) if lines else 'なし'}\n\n"
                    "失敗:\n" + "\n".join(failures),
                )
            else:
                messagebox.showinfo(APP_NAME, "CupID取得が完了しました。\n" + "\n".join(lines))
        except Exception as e:
            self._close_progress_dialog()
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def _eleague_autofill_edit_form(self, driver, payload):
        return driver.execute_async_script(
            r'''
const payload = arguments[0];
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", filled:[], clicked:false};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function norm(value) {
  return String(value || "").replace(/[\s　\u200b\u200c\ufeff:：()（）]/g, "").toLowerCase();
}
function setNativeValue(el, value) {
  value = String(value || "");
  el.scrollIntoView({block:"center", inline:"center"});
  el.focus();
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, "value")
    || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")
    || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
    || Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  if (el._valueTracker) el._valueTracker.setValue(el.value);
  if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:value}));
  el.dispatchEvent(new Event("change", {bubbles:true}));
  el.blur();
}
async function waitForEditFields() {
  for (let i = 0; i < 60; i++) {
    if (visible(document.querySelector('select[name="gameMethod"]'))
        && visible(document.querySelector('input[name="teamsNum"]'))) return true;
    await sleep(200);
  }
  return false;
}
function setSelectByValueOrText(selector, values, note) {
  const select = document.querySelector(selector);
  if (!visible(select) || select.tagName !== "SELECT") return false;
  const valueNorms = values.map(norm);
  const option = [...select.options].find(opt => valueNorms.some(v => norm(opt.value) === v || norm(opt.textContent).includes(v)));
  if (!option) return false;
  setNativeValue(select, option.value);
  result.filled.push(note);
  return true;
}
function setInput(selector, value, note) {
  const input = document.querySelector(selector);
  if (!visible(input)) return false;
  setNativeValue(input, value);
  result.filled.push(note);
  return true;
}
function clickRadio(name, value, note) {
  const input = [...document.querySelectorAll(`input[name="${name}"]`)].find(el => String(el.value) === String(value));
  if (!input) return false;
  const label = input.closest("label");
  (label || input).scrollIntoView({block:"center", inline:"center"});
  (label || input).click();
  result.filled.push(note);
  return true;
}
function setCheckbox(name, checked, note) {
  const input = document.querySelector(`input[name="${name}"]`);
  if (!input) return false;
  if (!!input.checked !== !!checked) {
    const label = input.closest("label");
    (label || input).scrollIntoView({block:"center", inline:"center"});
    (label || input).click();
  }
  result.filled.push(note);
  return true;
}
async function selectInputter(label) {
  const wanted = norm(label);
  const input = [...document.querySelectorAll('input[id^="react-select-"]')].find(visible);
  if (!input) return false;
  input.scrollIntoView({block:"center", inline:"center"});
  input.focus();
  input.click();
  setNativeValue(input, label);
  await sleep(500);
  let options = [...document.querySelectorAll('[role="option"], .select__option, [id*="-option-"]')].filter(visible);
  let option = options.find(opt => norm(textOf(opt)).includes(wanted));
  if (!option) {
    setNativeValue(input, "");
    input.click();
    await sleep(300);
    options = [...document.querySelectorAll('[role="option"], .select__option, [id*="-option-"]')].filter(visible);
    option = options.find(opt => norm(textOf(opt)).includes(wanted));
  }
  if (!option) return false;
  option.click();
  await sleep(250);
  return true;
}
function clickRegister() {
  const buttons = [...document.querySelectorAll('button, [role="button"]')].filter(visible);
  const btn = buttons.find(el => /^登録$|登録する|保存/.test(textOf(el)));
  if (!btn) return false;
  btn.scrollIntoView({block:"center", inline:"center"});
  btn.click();
  result.clicked = true;
  return true;
}
function debugFields() {
  return [...document.querySelectorAll("input, select")].filter(visible).slice(0, 16).map(el => {
    return [el.tagName.toLowerCase(), el.name ? "name=" + el.name : "", el.type ? "type=" + el.type : "", el.value ? "value=" + el.value : ""].filter(Boolean).join(" ");
  }).join(" / ");
}
(async () => {
  try {
    await waitForEditFields();
    if (!setSelectByValueOrText('select[name="gameMethod"]', [payload.game_method, payload.game_method_label], "試合方式")) {
      throw new Error("試合方式を設定できません: " + debugFields());
    }
    if (!clickRadio("usedType", "2", "運用方式")) {
      throw new Error("運用方式を設定できません: " + debugFields());
    }
    if (!setCheckbox("ikkyuInput", true, "一球入力モード")) {
      throw new Error("一球入力モードを設定できません: " + debugFields());
    }
    if (!setInput('input[name="teamsNum"]', payload.teams_num, "参加チーム数")) {
      throw new Error("参加チーム数を設定できません: " + debugFields());
    }
    for (const inputter of (payload.inputters || [])) {
      const ok = await selectInputter(inputter);
      if (ok) result.filled.push("入力者:" + inputter);
    }
    if (!clickRegister()) throw new Error("登録ボタンを検出できません");
    result.ok = true;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
            payload,
        )

    def edit_eleague_tournaments(self):
        try:
            payloads = self._eleague_edit_payloads()
            self.persist_settings()
            summary = "\n".join(
                f"{p['division']}: CupID {p['cup_id']} / 試合方式 {p['game_method_label']} / チーム数 {p['teams_num']}"
                for p in payloads
            )
            if not messagebox.askyesno(
                APP_NAME,
                "E-Leagueの大会編集を自動設定します。\n\n"
                f"{summary}\n\n続行しますか？",
            ):
                return
            driver, WebDriverWait = self._get_wp_driver()
            focus_chrome_window(driver)

            def wait_ready(timeout=60):
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )

            successes = []
            failures = []
            for payload in payloads:
                driver.get(f"https://safe.omyutech.com/cup/{payload['cup_id']}")
                focus_chrome_window(driver)
                wait_ready()
                WebDriverWait(driver, 30).until(
                    lambda d: d.execute_script("return !!document.body && (document.body.innerText || document.body.textContent || '').length > 0")
                )
                result = self._eleague_autofill_edit_form(driver, payload)
                if result and result.get("ok"):
                    successes.append(payload["division"])
                    time.sleep(1.2)
                else:
                    failures.append(f"{payload['division']}: {(result or {}).get('message', result)}")
            focus_chrome_window(driver)
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    "E-League大会編集を実行しました。\n\n"
                    f"成功: {', '.join(successes) if successes else 'なし'}\n"
                    "失敗:\n" + "\n".join(failures),
                )
            else:
                messagebox.showinfo(APP_NAME, "E-League大会編集が完了しました。\n" + "、".join(successes))
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def _eleague_set_rule_pattern(self, driver, payload):
        return driver.execute_async_script(
            r'''
const done = arguments[arguments.length - 1];
const result = {ok:false, message:""};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function norm(value) { return String(value || "").replace(/[\s　\u200b\u200c\ufeff:：]/g, "").toLowerCase(); }
function setValue(el, value) {
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, "value")
    || Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")
    || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:String(value)}));
  el.dispatchEvent(new Event("change", {bubbles:true}));
}
function clickRegister() {
  const buttons = [...document.querySelectorAll("button, [role='button']")].filter(visible);
  const button = buttons.find(btn => /^登録$|登録する|保存/.test(textOf(btn)));
  if (!button) return false;
  button.scrollIntoView({block:"center", inline:"center"});
  button.click();
  return true;
}
(async () => {
  try {
    for (let i = 0; i < 50; i++) {
      if (visible(document.querySelector('select[name="pattern"]'))) break;
      await sleep(200);
    }
    const select = document.querySelector('select[name="pattern"]');
    if (!visible(select)) throw new Error("設定パターン欄を検出できません");
    const option = [...select.options].find(opt => norm(opt.textContent).includes(norm("中国地区準硬式")) || String(opt.value) === "1689");
    if (!option) throw new Error("中国地区準硬式の選択肢を検出できません");
    setValue(select, option.value);
    await sleep(200);
    if (!clickRegister()) throw new Error("登録ボタンを検出できません");
    result.ok = true;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
        )

    def _eleague_add_stadiums(self, driver, payload):
        return driver.execute_async_script(
            r'''
const payload = arguments[0];
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", added:[], missing:[]};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function norm(value) { return String(value || "").replace(/[\s　\u200b\u200c\ufeff:：()（）]/g, "").toLowerCase(); }
function setValue(el, value) {
  value = String(value || "");
  el.focus();
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, "value")
    || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  if (el._valueTracker) el._valueTracker.setValue(el.value);
  if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:value}));
  el.dispatchEvent(new Event("change", {bubbles:true}));
}
function candidates(venue) {
  const values = [
    venue,
    String(venue || "").replace(/野球場$/, ""),
    String(venue || "").replace(/球場$/, ""),
  ];
  if (/倉敷|市営/.test(venue)) values.push("倉敷市営球場", "倉 市営", "倉　市営", "倉敷");
  if (/玉島|森/.test(venue)) values.push("玉島の森野球場", "玉 玉島", "玉　玉島", "玉島");
  return values.filter((v, i) => v && values.indexOf(v) === i);
}
function visibleReactSelectInput() {
  return [...document.querySelectorAll('input[id^="react-select-"]')].find(visible);
}
async function waitForVisibleReactSelectInput(timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const input = visibleReactSelectInput();
    if (input) return input;
    await sleep(300);
  }
  return null;
}
async function waitForButton(pattern, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const buttons = [...document.querySelectorAll("button, [role='button'], a")].filter(visible);
    const button = buttons.find(btn => pattern.test(textOf(btn)));
    if (button) return button;
    await sleep(300);
  }
  return null;
}
async function openAddForm() {
  if (await waitForVisibleReactSelectInput(1500)) return true;
  const button = await waitForButton(/球場追加/, 60000);
  if (!button) {
    result.message = "球場追加ボタンを検出できません";
    return false;
  }
  button.scrollIntoView({block:"center", inline:"center"});
  for (let attempt = 0; attempt < 3; attempt++) {
    button.click();
    if (await waitForVisibleReactSelectInput(20000)) return true;
    await sleep(700);
  }
  result.message = "球場追加フォームを検出できません";
  return false;
}
async function selectVenue(venue) {
  const input = await waitForVisibleReactSelectInput(30000);
  if (!input) return false;
  input.scrollIntoView({block:"center", inline:"center"});
  for (const candidate of candidates(venue)) {
    input.click();
    setValue(input, candidate);
    await sleep(650);
    const options = [...document.querySelectorAll('[role="option"], .select__option, [id*="-option-"]')].filter(visible);
    const option = options.find(opt => {
      const text = norm(textOf(opt));
      return text && (text.includes(norm(candidate)) || norm(candidate).includes(text) || text.includes(norm(venue)));
    });
    if (option) {
      option.click();
      await sleep(250);
      result.added.push(venue);
      return true;
    }
  }
  result.missing.push(venue);
  return false;
}
function clickAdd() {
  const buttons = [...document.querySelectorAll("button, [role='button']")].filter(visible);
  const button = buttons.find(btn => /^追加$|追加する/.test(textOf(btn)) && !btn.disabled && !btn.className.includes("disabled"));
  if (!button) return false;
  button.scrollIntoView({block:"center", inline:"center"});
  button.click();
  return true;
}
(async () => {
  try {
    if (!await openAddForm()) throw new Error(result.message || "球場追加フォームを検出できません");
    for (const venue of (payload.venues || [])) {
      await selectVenue(venue);
    }
    if (!result.added.length) throw new Error("球場を選択できません: " + result.missing.join(" / "));
    if (!clickAdd()) throw new Error("追加ボタンを検出できません");
    result.ok = true;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
            payload,
        )

    def _eleague_set_output_code(self, driver, payload):
        return driver.execute_async_script(
            r'''
const payload = arguments[0];
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", tournament_id:""};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function setValue(el, value) {
  value = String(value || "");
  el.scrollIntoView({block:"center", inline:"center"});
  el.focus();
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, "value")
    || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  if (el._valueTracker) el._valueTracker.setValue(el.value);
  if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:value}));
  el.dispatchEvent(new Event("change", {bubbles:true}));
}

function messageText() {
  return String(document.body ? (document.body.innerText || document.body.textContent || "") : "");
}
function clickSetting() {
  const buttons = [...document.querySelectorAll("button, [role='button']")].filter(visible);
  const button = buttons.find(btn => /^\u8a2d\u5b9a$|\u767b\u9332|\u4fdd\u5b58/.test(textOf(btn)) && !btn.disabled);
  if (!button) return false;
  button.scrollIntoView({block:"center", inline:"center"});
  button.click();
  return true;
}
function candidateIds(base) {
  base = String(base || "").replace(/[^0-9A-Za-z]/g, "");
  const ids = [base];
  for (let i = 2; i <= 20; i++) ids.push(`${base}_${i}`);
  return ids;
}
function cupCodeInput() {
  const inputs = [...document.querySelectorAll('input, textarea')].filter(visible);
  return inputs.find(el => el.name === "cupCode")
    || inputs.find(el => /cup[_-]?code/i.test(el.name || ""))
    || inputs.find(el => /\u5927\u4f1a\u30b3\u30fc\u30c9/.test((el.placeholder || "") + " " + textOf(el.closest("label") || el.parentElement)));
}
function candidateTabElements() {
  const exact = "\u30a6\u30a7\u30d6\u30b5\u30a4\u30c8\u306b\u57cb\u3081\u8fbc\u3080";
  return [...document.querySelectorAll("button[role='tab'], [role='tab'], button, a")]
    .filter(el => textOf(el) === exact || textOf(el).includes(exact))
    .map(el => el.closest("button, a, [role='button'], [role='tab']") || el);
}
function scrollTabAreas() {
  for (const el of document.querySelectorAll(".output-tab .MuiTabs-scroller, .MuiTabs-scroller, .MuiTabs-flexContainer, [role='tablist']")) {
    try { el.scrollLeft = el.scrollWidth; } catch (e) {}
  }
  try { window.scrollTo(0, 0); } catch (e) {}
}
async function clickEmbedTab() {
  for (let i = 0; i < 120; i++) {
    if (visible(cupCodeInput())) return true;
    scrollTabAreas();
    const tabs = candidateTabElements();
    const tab = tabs.find(el => visible(el)) || tabs[0];
    if (tab) {
      tab.scrollIntoView({block:"center", inline:"center"});
      tab.click();
      await sleep(900);
      if (visible(cupCodeInput())) return true;
    }
    await sleep(500);
  }
  return visible(cupCodeInput());
}
(async () => {
  try {
    if (!await clickEmbedTab()) throw new Error("\u30a6\u30a7\u30d6\u30b5\u30a4\u30c8\u306b\u57cb\u3081\u8fbc\u3080\u30bf\u30d6\u3092\u691c\u51fa\u3067\u304d\u307e\u305b\u3093");
    for (let i = 0; i < 120; i++) {
      if (visible(cupCodeInput())) break;
      await sleep(500);
    }
    const input = cupCodeInput();
    if (!visible(input)) throw new Error("大会コード欄を検出できません");
    const base = String(payload.tournament_id || payload.tournament_id_base || "").replace(/[^0-9A-Za-z]/g, "");
    if (!base) throw new Error("大会コードが空です");
    for (const code of candidateIds(base)) {
      const before = messageText();
      setValue(input, code);
      await sleep(150);
      if (!clickSetting()) throw new Error("設定ボタンを検出できません");
      await sleep(900);
      const after = messageText();
      if (!/大会コードが存在|既に存在|存在しています|使用されています/.test(after) || after === before) {
        result.ok = true;
        result.tournament_id = code;
        done(result);
        return;
      }
    }
    throw new Error("利用可能な大会コードを設定できません");
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
            payload,
        )

    def _eleague_read_output_code(self, driver):
        return driver.execute_async_script(
            r"""
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", tournament_id:""};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function cupCodeInput() {
  return document.querySelector('input[name="cupCode"], input[name="cup_code"], input[placeholder*="\u5927\u4f1a\u30b3\u30fc\u30c9"]');
}
function candidateTabElements() {
  const exact = "\u30a6\u30a7\u30d6\u30b5\u30a4\u30c8\u306b\u57cb\u3081\u8fbc\u3080";
  return [...document.querySelectorAll("button[role='tab'], [role='tab'], button, a")]
    .filter(el => textOf(el) === exact || textOf(el).includes(exact))
    .map(el => el.closest("button, a, [role='button'], [role='tab']") || el);
}
function scrollTabAreas() {
  for (const el of document.querySelectorAll(".output-tab .MuiTabs-scroller, .MuiTabs-scroller, .MuiTabs-flexContainer, [role='tablist']")) {
    try { el.scrollLeft = el.scrollWidth; } catch (e) {}
  }
  try { window.scrollTo(0, 0); } catch (e) {}
}
async function clickEmbedTab() {
  for (let i = 0; i < 120; i++) {
    if (visible(cupCodeInput())) return true;
    scrollTabAreas();
    const tabs = candidateTabElements();
    const tab = tabs.find(el => visible(el)) || tabs[0];
    if (tab) {
      tab.scrollIntoView({block:"center", inline:"center"});
      tab.click();
      await sleep(900);
      if (visible(cupCodeInput())) return true;
    }
    await sleep(500);
  }
  return visible(cupCodeInput());
}
(async () => {
  try {
    if (!await clickEmbedTab()) throw new Error("\u30a6\u30a7\u30d6\u30b5\u30a4\u30c8\u306b\u57cb\u3081\u8fbc\u3080\u30bf\u30d6\u3092\u691c\u51fa\u3067\u304d\u307e\u305b\u3093");
    const input = cupCodeInput();
    if (!visible(input)) throw new Error("\u5927\u4f1a\u30b3\u30fc\u30c9\u6b04\u3092\u691c\u51fa\u3067\u304d\u307e\u305b\u3093");
    const value = String(input.value || input.getAttribute("value") || "").trim();
    if (!value) throw new Error("\u5927\u4f1a\u30b3\u30fc\u30c9\u6b04\u304c\u7a7a\u3067\u3059\u3002E-League\u753b\u9762\u3067\u624b\u5165\u529b\u5f8c\u3001\u518d\u5ea6\u53d6\u5f97\u3057\u3066\u304f\u3060\u3055\u3044\u3002");
    result.ok = true;
    result.tournament_id = value;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
"""
        )

    def fetch_eleague_tournament_ids(self):
        try:
            payloads = self._eleague_stage3_payloads()
            if not messagebox.askyesno(
                APP_NAME,
                "E-League\u306e\u51fa\u529b\u753b\u9762\u304b\u3089\u5927\u4f1aID\u3092\u53d6\u5f97\u3057\u307e\u3059\u3002\n\n"
                "\u5927\u4f1aID\u3092\u624b\u5165\u529b\u3057\u305f\u5f8c\u306e\u78ba\u8a8d\u306b\u3082\u4f7f\u3048\u307e\u3059\u3002\n\n\u7d9a\u884c\u3057\u307e\u3059\u304b\uff1f",
            ):
                return
            driver, WebDriverWait = self._get_wp_driver()

            def wait_ready(timeout=60):
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )

            successes = []
            failures = []
            for payload in payloads:
                label = payload["division"]
                cup_id = payload["cup_id"]
                driver.get(f"https://safe.omyutech.com/cup/{cup_id}/output")
                focus_chrome_window(driver)
                wait_ready()
                time.sleep(1.0)
                result = self._eleague_read_output_code(driver)
                if result and result.get("ok"):
                    tournament_id = result.get("tournament_id", "").strip()
                    self._set_eleague_tournament_id_for_key(payload["division_key"], tournament_id)
                    successes.append(f"{label}: {tournament_id}")
                    if payload["division_key"] == division_key_from_label(self.division_var.get()):
                        self.tournament_id_var.set(tournament_id)
                    time.sleep(0.6)
                else:
                    failures.append(f"{label}: {(result or {}).get('message', result)}")
            if successes:
                self.persist_settings()
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    "\u5927\u4f1aID\u53d6\u5f97\u3092\u5b9f\u884c\u3057\u307e\u3057\u305f\u3002\n\n"
                    f"\u6210\u529f:\n{chr(10).join(successes) if successes else '\u306a\u3057'}\n\n"
                    "\u5931\u6557:\n" + "\n".join(failures),
                )
            else:
                messagebox.showinfo(APP_NAME, "\u5927\u4f1aID\u53d6\u5f97\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002\n" + "\n".join(successes))
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def setup_eleague_rules_stadiums_outputs(self):
        try:
            payloads = self._eleague_stage3_payloads()
            self.persist_settings()
            summary = "\n".join(
                f"{p['division']}: CupID {p['cup_id']} / 球場 {len(p['venues'])}件 / 大会コード {p['tournament_id']}"
                for p in payloads
            )
            if not messagebox.askyesno(
                APP_NAME,
                "E-League第三段階を自動設定します。\n\n"
                "ルール設定、球場追加、埋め込み大会コード設定を実行します。\n\n"
                f"{summary}\n\n続行しますか？",
            ):
                return
            driver, WebDriverWait = self._get_wp_driver()
            focus_chrome_window(driver)

            def wait_ready(timeout=60):
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )

            def wait_page_text(pattern, timeout=60):
                regex = re.compile(pattern)
                WebDriverWait(driver, timeout).until(
                    lambda d: bool(regex.search(d.execute_script(
                        "return document.body ? (document.body.innerText || document.body.textContent || '') : '';"
                    ) or ""))
                )

            try:
                driver.set_script_timeout(90)
            except Exception:
                pass

            successes = []
            failures = []
            for payload in payloads:
                label = payload["division"]
                cup_id = payload["cup_id"]

                driver.get(f"https://safe.omyutech.com/cup/{cup_id}/info/leaguerule")
                focus_chrome_window(driver)
                wait_ready()
                wait_page_text(r"設定パターン|登録|リーグ規定|ルール", 60)
                rule_result = self._eleague_set_rule_pattern(driver, payload)
                if not rule_result or not rule_result.get("ok"):
                    failures.append(f"{label} ルール設定: {(rule_result or {}).get('message', rule_result)}")
                    continue
                time.sleep(1.5)

                driver.get(f"https://safe.omyutech.com/cup/{cup_id}/info/stadium")
                focus_chrome_window(driver)
                wait_ready()
                wait_page_text(r"球場追加|球場リスト|球場", 60)
                stadium_result = self._eleague_add_stadiums(driver, payload)
                if not stadium_result or not stadium_result.get("ok"):
                    failures.append(f"{label} 球場追加: {(stadium_result or {}).get('message', stadium_result)}")
                    continue
                time.sleep(1.5)

                driver.get(f"https://safe.omyutech.com/cup/{cup_id}/output")
                focus_chrome_window(driver)
                wait_ready()
                wait_page_text(r"ウェブサイトに埋め込む|大会コード|設定", 60)
                output_result = self._eleague_set_output_code(driver, payload)
                if output_result and output_result.get("ok"):
                    tournament_id = output_result.get("tournament_id") or payload["tournament_id"]
                    self._set_eleague_tournament_id_for_key(payload["division_key"], tournament_id)
                    successes.append(f"{label}: {tournament_id}")
                    time.sleep(0.8)
                else:
                    failures.append(f"{label} 大会コード設定: {(output_result or {}).get('message', output_result)}")
            focus_chrome_window(driver)
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    "E-League第三段階を実行しました。\n\n"
                    f"成功:\n{chr(10).join(successes) if successes else 'なし'}\n\n"
                    "失敗:\n" + "\n".join(failures),
                )
            else:
                messagebox.showinfo(APP_NAME, "E-League第三段階が完了しました。\n" + "\n".join(successes))
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def _team_list_template_path(self):
        candidates = [
            BASE_DIR / "league_team_list.xlsx",
            Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "league_team_list.xlsx",
            Path(__file__).resolve().parent / "league_team_list.xlsx",
        ]
        for path in candidates:
            if path.exists():
                return path
        return candidates[0]

    def _create_eleague_team_import_files(self):
        year = self.year_var.get().strip()
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError("日程画面の作成年度は西暦4桁で入力してください。")
        excel_file = self.schedule_excel_file_var.get().strip()
        excel_path = app_path(excel_file)
        if not excel_path or not excel_path.exists():
            raise ValueError("日程表Excelファイルを選択してください。")

        schedule_text = load_xlsx_schedule_text(str(excel_path))
        template_path = self._team_list_template_path()
        master_rows = xlsx_read_first_sheet_rows(str(template_path))
        result = {}
        for key, filename in (("1", "league_team_01.xlsx"), ("2", "league_team_02.xlsx")):
            team_names = collect_eleague_team_names(schedule_text, int(year), key)
            if not team_names:
                raise ValueError(f"日程表Excelから{division_label_from_key(key)}のチームを取得できません。")
            rows, missing = build_team_import_rows(master_rows, team_names)
            if missing:
                raise ValueError(
                    f"{division_label_from_key(key)}のチームをleague_team_list.xlsxで照合できません: "
                    + "、".join(missing)
                )
            output_path = BASE_DIR / filename
            write_xlsx_rows_from_template(str(template_path), str(output_path), rows)
            result[key] = {
                "file_path": str(output_path),
                "team_names": team_names,
                "upload_team_names": [row[0] for row in rows[1:] if row],
                "row_count": max(0, len(rows) - 1),
            }
        return result

    def _eleague_team_import_payloads(self):
        cup_ids = {
            "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
        }
        missing_cups = [division_label_from_key(key) for key, cup_id in cup_ids.items() if not cup_id]
        if missing_cups:
            raise ValueError("次の区分のCupIDを取得してください: " + "、".join(missing_cups))
        files = self._create_eleague_team_import_files()
        payloads = []
        for key in ("1", "2"):
            payloads.append({
                "division_key": key,
                "division": division_label_from_key(key),
                "cup_id": cup_ids[key],
                "file_path": files[key]["file_path"],
                "team_names": files[key]["team_names"],
                "upload_team_names": files[key]["upload_team_names"],
                "row_count": files[key]["row_count"],
            })
        return payloads

    def _eleague_import_team_file(self, driver, WebDriverWait, payload):
        from selenium.webdriver.common.by import By  # type: ignore

        file_path = Path(payload["file_path"]).resolve()
        if not file_path.exists():
            return {"ok": False, "message": f"インポートファイルが見つかりません: {file_path}"}
        driver.execute_async_script(
            r"""
const done = arguments[arguments.length - 1];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function text() { return document.body ? (document.body.innerText || document.body.textContent || "") : ""; }
(async () => {
  let stableSince = 0;
  let last = "";
  const started = Date.now();
  while (Date.now() - started < 30000) {
    const nowText = text();
    const hasImportUi = nowText.length > 50;
    const hasFile = !!document.querySelector('input[type="file"]');
    if (hasImportUi && hasFile) {
      if (nowText === last) {
        stableSince += 250;
        if (stableSince >= 2000) { done(true); return; }
      } else {
        stableSince = 0;
        last = nowText;
      }
    }
    await sleep(250);
  }
  done(false);
})();
"""
        )
        time.sleep(0.8)
        file_input = WebDriverWait(driver, 60).until(
            lambda d: d.find_element(By.CSS_SELECTOR, 'input[type="file"][accept*=".xls"]')
        )
        driver.execute_script(
            """
arguments[0].removeAttribute('hidden');
arguments[0].style.display = 'block';
arguments[0].style.visibility = 'visible';
arguments[0].style.opacity = 1;
arguments[0].style.height = '1px';
arguments[0].style.width = '1px';
""",
            file_input,
        )
        file_input.send_keys(str(file_path))
        return driver.execute_async_script(
            r'''
const payload = arguments[0] || {};
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", shownTeams:0, expectedTeams:0};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function norm(value) { return String(value || "").normalize("NFKC").replace(/[\s　\u200b\u200c\ufeff]/g, ""); }
function pageText() { return norm(document.body ? (document.body.innerText || document.body.textContent || "") : ""); }
function expectedTeams() {
  const names = [...(payload.upload_team_names || []), ...(payload.team_names || [])]
    .map(norm)
    .filter(Boolean);
  return [...new Set(names)];
}
function shownTeamCount(names) {
  const body = pageText();
  return names.filter(name => body.includes(name)).length;
}
async function waitForTeamRows(timeoutMs) {
  const names = expectedTeams();
  result.expectedTeams = names.length;
  if (!names.length) return true;
  const required = Math.max(1, Math.min(names.length, Math.ceil((payload.row_count || names.length) * 0.8)));
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    result.shownTeams = shownTeamCount(names);
    if (result.shownTeams >= required) return true;
    await sleep(250);
  }
  return false;
}
function shouldSkip(el) {
  if (!el) return true;
  const label = norm(textOf(el));
  if (/選手一括|野球ねっと|テンプレート|連盟チーム入りEXCEL/.test(label)) return true;
  if (el.getAttribute("aria-disabled") === "true") return true;
  return false;
}
function canClick(el) {
  if (!el || shouldSkip(el)) return false;
  if (!el.disabled) return true;
  const cls = String(el.className || "");
  return !/\bMui-disabled\b|\bdisabled\b/.test(cls);
}
function buttonByExactText(pattern) {
  const buttons = [...document.querySelectorAll("button, [role='button']")].filter(visible);
  return {
    button: buttons.find(btn => canClick(btn) && pattern.test(norm(textOf(btn)))),
    visibleText: buttons.map(textOf).filter(Boolean).join(" / ")
  };
}
(async () => {
  try {
    let lastButtons = "";
    let clickedRead = false;
    for (let i = 0; i < 200; i++) {
      const readResult = buttonByExactText(/^読込み$|^読み込み$/);
      lastButtons = readResult.visibleText || lastButtons;
      if (!clickedRead && readResult.button) {
        clickedRead = true;
        readResult.button.scrollIntoView({block:"center", inline:"center"});
        readResult.button.click();
        await sleep(500);
      }
      const importResult = buttonByExactText(/^(?:\+|\uFF0B)?(?:\u30a4\u30f3\u30dd\u30fc\u30c8|\u8ffd\u52a0|\u65b0\u898f\u8ffd\u52a0|\u767b\u9332)$/);
      lastButtons = importResult.visibleText || lastButtons;
      if (importResult.button) {
        if (!await waitForTeamRows(15000)) {
          throw new Error("チーム一覧の表示完了を確認できません（表示 " + result.shownTeams + "/" + result.expectedTeams + "）。表示ボタン: " + lastButtons);
        }
        importResult.button.scrollIntoView({block:"center", inline:"center"});
        importResult.button.click();
        await sleep(1200);
        result.ok = true;
        done(result);
        return;
      }
      await sleep(300);
    }
    throw new Error("インポートボタンを検出できません。表示ボタン: " + lastButtons);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
            payload,
        )

    def import_eleague_teams(self):
        try:
            payloads = self._eleague_team_import_payloads()
            self.persist_settings()
            summary = "\n".join(
                f"{p['division']}: {p['row_count']}\u30c1\u30fc\u30e0 / {p['file_path']}"
                for p in payloads
            )
            if not messagebox.askyesno(
                APP_NAME,
                "E-League\u3078\u30c1\u30fc\u30e0\u3092\u30a4\u30f3\u30dd\u30fc\u30c8\u3057\u307e\u3059\u3002\n\n"
                f"{summary}\n\n"
                "\u5bfe\u8c61\u306f\uff11\u90e8\u30fb\uff12\u90e8\u306e\u307f\u3067\u3059\u3002\u7d9a\u884c\u3057\u307e\u3059\u304b\uff1f",
            ):
                return
            use_progress = not getattr(self, "_eleague_suppress_progress", False)
            if use_progress:
                self._show_progress_dialog(
                    "E-League \u30c1\u30fc\u30e0\u767b\u9332",
                    "Chrome\u3092\u6e96\u5099\u3057\u3066\u3044\u307e\u3059\u3002\n\u3057\u3070\u3089\u304f\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002",
                )
            driver, WebDriverWait = self._get_wp_driver()
            focus_chrome_window(driver)

            def wait_ready(timeout=60):
                if use_progress:
                    self._update_progress_dialog("\u30da\u30fc\u30b8\u306e\u8aad\u307f\u8fbc\u307f\u5b8c\u4e86\u3092\u5f85\u3063\u3066\u3044\u307e\u3059\u3002\n\u3057\u3070\u3089\u304f\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002")
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )

            def wait_page_text(pattern, timeout=60):
                if use_progress:
                    self._update_progress_dialog("E-League\u753b\u9762\u306e\u8868\u793a\u5b8c\u4e86\u3092\u5f85\u3063\u3066\u3044\u307e\u3059\u3002\n\u30cd\u30c3\u30c8\u30ef\u30fc\u30af\u72b6\u6cc1\u306b\u3088\u308a\u6642\u9593\u304c\u304b\u304b\u308b\u5834\u5408\u304c\u3042\u308a\u307e\u3059\u3002")
                regex = re.compile(pattern)
                WebDriverWait(driver, timeout).until(
                    lambda d: bool(regex.search(d.execute_script(
                        "return document.body ? (document.body.innerText || document.body.textContent || '') : '';"
                    ) or ""))
                )

            try:
                driver.set_script_timeout(90)
            except Exception:
                pass

            successes = []
            failures = []
            try:
                for index, payload in enumerate(payloads, start=1):
                    label = payload["division"]
                    cup_id = payload["cup_id"]
                    if use_progress:
                        self._update_progress_dialog(
                            f"{label}\u306e\u30c1\u30fc\u30e0\u767b\u9332\u3092\u958b\u59cb\u3057\u3066\u3044\u307e\u3059\u3002({index}/{len(payloads)})\n"
                            f"{payload['row_count']}\u30c1\u30fc\u30e0\u306eExcel\u3092E-League\u3078\u9001\u4fe1\u3057\u307e\u3059\u3002"
                        )
                    result = None
                    for attempt in range(1, 4):
                        try:
                            driver.get(f"https://safe.omyutech.com/cup/{cup_id}/team/add")
                            focus_chrome_window(driver)
                            wait_ready()
                            wait_page_text("\u30c1\u30fc\u30e0\u3092\u30a4\u30f3\u30dd\u30fc\u30c8|Excel\u30d5\u30a1\u30a4\u30eb|\u51fa\u5834\u30c1\u30fc\u30e0\u8ffd\u52a0|\u30a4\u30f3\u30dd\u30fc\u30c8", 60)
                            if use_progress:
                                self._update_progress_dialog(
                                    f"{label}\u306eExcel\u30d5\u30a1\u30a4\u30eb\u3092\u30a2\u30c3\u30d7\u30ed\u30fc\u30c9\u3057\u3066\u3044\u307e\u3059\u3002({index}/{len(payloads)})\n"
                                    f"\u30c1\u30fc\u30e0\u4e00\u89a7\u304c\u8868\u793a\u3055\u308c\u308b\u307e\u3067\u5f85\u3061\u307e\u3059\u3002\uff08\u8a66\u884c {attempt}/3\uff09"
                                )
                            result = self._eleague_import_team_file(driver, WebDriverWait, payload)
                            if result and result.get("ok"):
                                break
                        except Exception as exc:
                            result = {"ok": False, "message": str(exc)}
                        if attempt < 3:
                            time.sleep(1.2)
                    if result and result.get("ok"):
                        successes.append(f"{label}: {payload['row_count']}\u30c1\u30fc\u30e0")
                        if use_progress:
                            self._update_progress_dialog(
                                f"{label}\u306e\u30c1\u30fc\u30e0\u767b\u9332\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002({index}/{len(payloads)})\n"
                                "\u6b21\u306e\u51e6\u7406\u3078\u9032\u307f\u307e\u3059\u3002"
                            )
                        time.sleep(1.5)
                    else:
                        failures.append(f"{label}: {(result or {}).get('message', result)}")
            finally:
                if use_progress:
                    self._close_progress_dialog()
            try:
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    "E-League\u30c1\u30fc\u30e0\u767b\u9332\u3092\u5b9f\u884c\u3057\u307e\u3057\u305f\u3002\n\n"
                    f"\u6210\u529f:\n{chr(10).join(successes) if successes else '\u306a\u3057'}\n\n"
                    "\u5931\u6557:\n" + "\n".join(failures),
                )
            else:
                messagebox.showinfo(APP_NAME, "E-League\u30c1\u30fc\u30e0\u767b\u9332\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002\n" + "\n".join(successes))
        except Exception as e:
            self._close_progress_dialog()
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def _eleague_set_group_settings(self, driver, payload):
        return driver.execute_async_script(
            r'''
const payload = arguments[0];
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", checkedAll:0};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function norm(value) { return String(value || "").replace(/[\s　\u200b\u200c\ufeff:：]/g, "").toLowerCase(); }
function setValue(el, value) {
  value = String(value || "");
  el.scrollIntoView({block:"center", inline:"center"});
  el.focus();
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, "value")
    || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  if (el._valueTracker) el._valueTracker.setValue(el.value);
  if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:value}));
  el.dispatchEvent(new Event("change", {bubbles:true}));
  el.blur();
}
function labelText(input) {
  const labels = [];
  if (input.labels) labels.push(...[...input.labels].map(l => textOf(l)));
  let p = input.parentElement;
  for (let i = 0; p && i < 4; i++, p = p.parentElement) {
    const text = textOf(p).replace(/\s+/g, " ");
    if (text) labels.push(text);
  }
  return labels.join(" ");
}
function clickCheckbox(input) {
  if (!input.checked) {
    input.scrollIntoView({block:"center", inline:"center"});
    input.click();
    input.dispatchEvent(new Event("change", {bubbles:true}));
  }
}
async function waitFor(predicate, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const value = predicate();
    if (value) return value;
    await sleep(300);
  }
  return null;
}
function clickRegister() {
  const buttons = [...document.querySelectorAll("button, [role='button']")].filter(visible);
  const button = buttons.find(btn => /^登録$|登録する|保存/.test(textOf(btn)) && !btn.disabled);
  if (!button) return false;
  button.scrollIntoView({block:"center", inline:"center"});
  button.click();
  return true;
}
(async () => {
  try {
    await waitFor(() => [...document.querySelectorAll('input[name="teamsNum"]')].filter(visible).length >= 1, 60000);
    const groupNames = [...document.querySelectorAll('input[name="groupName"]')].filter(visible);
    const teamNums = [...document.querySelectorAll('input[name="teamsNum"]')].filter(visible);
    if (!teamNums.length) throw new Error("参加チーム数欄を検出できません");
    let targetNum = teamNums[teamNums.length - 1];
    const groupIndex = groupNames.findIndex(input => norm(input.value || "").includes("a") || norm(input.value || "").includes("グループ1"));
    if (groupIndex >= 0 && teamNums[groupIndex]) targetNum = teamNums[groupIndex];
    setValue(targetNum, payload.teams_num);
    await sleep(250);

    const teamSetting = [...document.querySelectorAll('input[type="checkbox"], input[name="teamSetting"]')]
      .filter(visible)
      .find(input => input.name === "teamSetting" || /参加チーム設定/.test(labelText(input)));
    if (!teamSetting) throw new Error("参加チーム設定チェックボックスを検出できません");
    clickCheckbox(teamSetting);
    await sleep(800);

    const allTeamsRadio = [...document.querySelectorAll('input[type="radio"][name="teamRangeType"]')]
      .find(input => String(input.value) === "1" || /\u3059\u3079\u3066\u306e\u30c1\u30fc\u30e0|\u5168\u3066\u306e\u30c1\u30fc\u30e0/.test(labelText(input)));
    if (allTeamsRadio && !allTeamsRadio.checked) {
      allTeamsRadio.scrollIntoView({block:"center", inline:"center"});
      allTeamsRadio.click();
      allTeamsRadio.dispatchEvent(new Event("change", {bubbles:true}));
      result.checkedAll += 1;
      await sleep(400);
    }

    const clickAllText = [...document.querySelectorAll("label, button, [role='button'], span, div")]
      .filter(visible)
      .find(el => /^(\u3059\u3079\u3066\u3092\u9078\u629e|\u5168\u3066\u3092\u9078\u629e)$/.test(textOf(el)));
    if (clickAllText) {
      const target = clickAllText.closest("label, button, [role='button']") || clickAllText;
      target.scrollIntoView({block:"center", inline:"center"});
      target.click();
      result.checkedAll += 1;
      await sleep(400);
    } else {
      const checkboxes = [...document.querySelectorAll('input[type="checkbox"]')].filter(visible);
      const allSelect = checkboxes.find(input => input !== teamSetting && /\u3059\u3079\u3066|\u5168\u3066|\u5168\u9078\u629e|selectall/i.test(labelText(input)));
      if (allSelect) {
        clickCheckbox(allSelect);
        result.checkedAll += 1;
      } else {
        for (const input of checkboxes) {
          if (input === teamSetting) continue;
          if (!input.checked) {
            clickCheckbox(input);
            result.checkedAll += 1;
          }
        }
      }
    }
    await sleep(300);
    if (!clickRegister()) throw new Error("登録ボタンを検出できません");
    result.ok = true;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
            payload,
        )

    def _eleague_assign_tournament_teams(self, driver, payload):
        return driver.execute_async_script(
            r'''
const payload = arguments[0];
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", assigned:[]};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function norm(value) { return String(value || "").replace(/[\s　\u200b\u200c\ufeff.．。、:：]/g, "").toLowerCase(); }
async function waitFor(predicate, timeoutMs, message) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const value = predicate();
    if (value) return value;
    await sleep(300);
  }
  throw new Error(message || "timeout");
}
async function waitStable(snapshot, timeoutMs, stableMs, message) {
  const started = Date.now();
  let last = "";
  let stable = 0;
  while (Date.now() - started < timeoutMs) {
    const now = snapshot();
    if (now && now === last) {
      stable += 250;
      if (stable >= stableMs) return now;
    } else {
      last = now;
      stable = 0;
    }
    await sleep(250);
  }
  throw new Error(message || "stable timeout");
}
function teamButtons() {
  return [...document.querySelectorAll("button, [role='button']")]
    .filter(visible)
    .map(btn => ({btn, text:textOf(btn)}))
    .filter(item => /^\d+\s*[.．]/.test(item.text));
}
function findTeamButton(index, expectedName) {
  const numbered = teamButtons();
  const byNumber = numbered.find(item => new RegExp("^\\s*" + index + "\\s*[.．]").test(item.text));
  if (byNumber) return byNumber;
  const expected = norm(expectedName || "");
  if (expected) {
    const byName = numbered.find(item => norm(item.text).includes(expected));
    if (byName) return byName;
  }
  return null;
}
function targetButtons() {
  const table = [...document.querySelectorAll("table")].find(visible);
  if (!table) return [];
  const rows = [...table.rows];
  const targets = [];
  for (let i = 1; i < rows.length; i++) {
    const cell = rows[i].cells && rows[i].cells[0];
    if (!cell) continue;
    const button = [...cell.querySelectorAll("button, [role='button']")].find(visible);
    targets.push(button || cell);
  }
  return targets.filter(Boolean);
}
function mouseClick(el) {
  el.scrollIntoView({block:"center", inline:"center"});
  try { el.click(); } catch (e) {
    try { el.dispatchEvent(new MouseEvent("click", {bubbles:true, cancelable:true, view:window})); } catch (_e) {}
  }
}
function pageSnapshot() {
  return [teamButtons().map(x => x.text).join("|"), targetButtons().length, document.body ? document.body.innerText.length : 0].join("#");
}
(async () => {
  try {
    const teams = payload.team_names || [];
    const count = Number(payload.teams_num || teams.length || 0);
    if (!count) throw new Error("team count is empty");
    await waitFor(() => teamButtons().length >= count, 60000, "left team buttons were not rendered");
    await waitFor(() => targetButtons().length >= count, 60000, "table targets were not rendered");
    await waitStable(pageSnapshot, 60000, 2000, "tournament page was not stable");
    for (let i = 0; i < count; i++) {
      await waitStable(pageSnapshot, 30000, 1000, "tournament page changed too long");
      const targets = targetButtons();
      const target = targets[i];
      if (!target) throw new Error("table target not found: " + (i + 1));
      mouseClick(target);
      await sleep(700);
      const team = findTeamButton(i + 1, teams[i]);
      if (!team) throw new Error("left team button not found: " + (i + 1));
      mouseClick(team.btn);
      result.assigned.push(team.text);
      await sleep(1200);
    }
    result.ok = true;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
            payload,
        )
    def _eleague_click_top_tab(self, driver, tab_label, expected_pattern=None, timeout=60):
        result = driver.execute_async_script(
            r"""
const label = arguments[0];
const expected = arguments[1] || "";
const timeoutMs = Number(arguments[2] || 60000);
const done = arguments[arguments.length - 1];
const result = {ok:false, message:""};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim().replace(/\s+/g, " "); }
function pageText() { return document.body ? (document.body.innerText || document.body.textContent || "") : ""; }
function scrollTabAreas() {
  for (const el of document.querySelectorAll(".MuiTabs-scroller, .MuiTabs-flexContainer, [role='tablist']")) {
    try { el.scrollLeft = 0; } catch (e) {}
  }
  try { window.scrollTo(0, 0); } catch (e) {}
}
function findTab() {
  const tabs = [...document.querySelectorAll("button[role='tab'], [role='tab'], button")].filter(visible);
  return tabs.find(el => textOf(el) === label) || tabs.find(el => textOf(el).includes(label));
}
(async () => {
  try {
    const started = Date.now();
    let lastTabs = "";
    while (Date.now() - started < timeoutMs) {
      scrollTabAreas();
      const tabs = [...document.querySelectorAll("button[role='tab'], [role='tab'], button")].filter(visible);
      lastTabs = tabs.map(textOf).filter(Boolean).join(" / ") || lastTabs;
      const tab = findTab();
      if (tab) {
        tab.scrollIntoView({block:"center", inline:"center"});
        tab.click();
        await sleep(1000);
        if (!expected || new RegExp(expected).test(pageText())) {
          result.ok = true;
          done(result);
          return;
        }
      }
      await sleep(500);
    }
    result.message = "top tab not found: " + label + " / visible tabs: " + lastTabs;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
""",
            tab_label,
            expected_pattern or "",
            timeout * 1000,
        )
        if not result or not result.get("ok"):
            raise RuntimeError((result or {}).get("message", result))
        return result

    def setup_eleague_groups(self):
        try:
            payloads = self._eleague_stage5_payloads()
            self.persist_settings()
            summary = "\n".join(
                f"{p['division']}: CupID {p['cup_id']} / {p['teams_num']}\u30c1\u30fc\u30e0"
                for p in payloads
            )
            if not messagebox.askyesno(
                APP_NAME,
                "E-League\u306e\u30c1\u30fc\u30e0\u8a2d\u5b9a\u3092\u81ea\u52d5\u5b9f\u884c\u3057\u307e\u3059\u3002\n\n"
                "\u30b0\u30eb\u30fc\u30d7\u8a2d\u5b9a\u3068\u7d44\u5408\u308f\u305b\u8868\u3078\u306e\u30c1\u30fc\u30e0\u5272\u308a\u5f53\u3066\u3092\u5b9f\u884c\u3057\u307e\u3059\u3002\n\n"
                f"{summary}\n\n\u5bfe\u8c61\u306f\uFF11\u90E8\u30fb\uFF12\u90E8\u306e\u307f\u3067\u3059\u3002\u7d9a\u884c\u3057\u307e\u3059\u304b\uff1f",
            ):
                return
            use_progress = not getattr(self, "_eleague_suppress_progress", False)
            if use_progress:
                self._show_progress_dialog(
                    "E-League \u30c1\u30fc\u30e0\u8a2d\u5b9a",
                    "Chrome\u3092\u6e96\u5099\u3057\u3066\u3044\u307e\u3059\u3002\n\u3057\u3070\u3089\u304f\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002",
                )
            driver, WebDriverWait = self._get_wp_driver()

            def wait_ready(timeout=60):
                if use_progress:
                    self._update_progress_dialog("\u30da\u30fc\u30b8\u306e\u8aad\u307f\u8fbc\u307f\u5b8c\u4e86\u3092\u5f85\u3063\u3066\u3044\u307e\u3059\u3002\n\u3057\u3070\u3089\u304f\u304a\u5f85\u3061\u304f\u3060\u3055\u3044\u3002")
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )

            def wait_page_text(pattern, timeout=60):
                if use_progress:
                    self._update_progress_dialog("E-League\u753b\u9762\u306e\u8868\u793a\u5b8c\u4e86\u3092\u5f85\u3063\u3066\u3044\u307e\u3059\u3002\n\u30cd\u30c3\u30c8\u30ef\u30fc\u30af\u72b6\u6cc1\u306b\u3088\u308a\u6642\u9593\u304c\u304b\u304b\u308b\u5834\u5408\u304c\u3042\u308a\u307e\u3059\u3002")
                regex = re.compile(pattern)
                WebDriverWait(driver, timeout).until(
                    lambda d: bool(regex.search(d.execute_script(
                        "return document.body ? (document.body.innerText || document.body.textContent || '') : '';"
                    ) or ""))
                )

            try:
                driver.set_script_timeout(120)
            except Exception:
                pass

            successes = []
            failures = []
            try:
                for index, payload in enumerate(payloads, start=1):
                    label = payload["division"]
                    cup_id = payload["cup_id"]
                    if use_progress:
                        self._update_progress_dialog(
                            f"{label}\u306e\u30b0\u30eb\u30fc\u30d7\u8a2d\u5b9a\u3092\u958b\u59cb\u3057\u3066\u3044\u307e\u3059\u3002({index}/{len(payloads)})\n"
                            f"{payload['teams_num']}\u30c1\u30fc\u30e0\u3092\u8a2d\u5b9a\u3057\u307e\u3059\u3002"
                        )
                    driver.get(f"https://safe.omyutech.com/cup/{cup_id}/tournamentset")
                    focus_chrome_window(driver)
                    wait_ready()
                    wait_page_text(r"\u30b0\u30eb\u30fc\u30d7\u8a2d\u5b9a|\u53c2\u52a0\u30c1\u30fc\u30e0\u6570|\u53c2\u52a0\u30c1\u30fc\u30e0\u8a2d\u5b9a|\u767b\u9332", 90)
                    group_result = self._eleague_set_group_settings(driver, payload)
                    if not group_result or not group_result.get("ok"):
                        failures.append(f"{label} \u30b0\u30eb\u30fc\u30d7\u8a2d\u5b9a: {(group_result or {}).get('message', group_result)}")
                        continue
                    time.sleep(1.5)

                    if use_progress:
                        self._update_progress_dialog(
                            f"{label}\u306e\u7d44\u5408\u308f\u305b\u8868\u3078\u30c1\u30fc\u30e0\u3092\u5272\u308a\u5f53\u3066\u3066\u3044\u307e\u3059\u3002({index}/{len(payloads)})\n"
                            "\u5de6\u306e\u30c1\u30fc\u30e0\u30ea\u30b9\u30c8\u30921\u756a\u304b\u3089\u9806\u306bTable\u3078\u8a2d\u5b9a\u3057\u307e\u3059\u3002"
                        )
                    driver.get(f"https://safe.omyutech.com/cup/{cup_id}/tournament")
                    focus_chrome_window(driver)
                    wait_ready()
                    wait_page_text(r"\u7d44\u5408\u308f\u305b|\u30c1\u30fc\u30e0\u5217\u306e\u8a2d\u5b9a\u5148|\u30c1\u30fc\u30e0\u30ea\u30b9\u30c8|\u30c1\u30fc\u30e0", 90)
                    assign_result = self._eleague_assign_tournament_teams(driver, payload)
                    if assign_result and assign_result.get("ok"):
                        successes.append(f"{label}: {len(assign_result.get('assigned') or [])}\u30c1\u30fc\u30e0")
                        time.sleep(1.2)
                    else:
                        failures.append(f"{label} \u7d44\u5408\u308f\u305b\u8a2d\u5b9a: {(assign_result or {}).get('message', assign_result)}")
            finally:
                if use_progress:
                    self._close_progress_dialog()
            try:
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    "E-League\u30c1\u30fc\u30e0\u8a2d\u5b9a\u3092\u5b9f\u884c\u3057\u307e\u3057\u305f\u3002\n\n"
                    f"\u6210\u529f:\n{chr(10).join(successes) if successes else '\u306a\u3057'}\n\n"
                    "\u5931\u6557:\n" + "\n".join(failures),
                )
            else:
                messagebox.showinfo(APP_NAME, "E-League\u30c1\u30fc\u30e0\u8a2d\u5b9a\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002\n" + "\n".join(successes))
        except Exception as e:
            self._close_progress_dialog()
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def _eleague_bulk_assign_recorders(self, driver, payload):
        return driver.execute_async_script(
            r'''
const payload = arguments[0];
const done = arguments[arguments.length - 1];
const result = {ok:false, message:"", selected:0, clicked:false};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function norm(value) { return String(value || "").replace(/[\s　\u200b\u200c\ufeff:：()（）#＃]/g, "").toLowerCase(); }
function setValue(el, value) {
  value = String(value || "");
  el.focus();
  const proto = Object.getPrototypeOf(el);
  const desc = Object.getOwnPropertyDescriptor(proto, "value")
    || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  if (el._valueTracker) el._valueTracker.setValue(el.value);
  if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  el.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertText", data:value}));
  el.dispatchEvent(new Event("change", {bubbles:true}));
}
async function waitFor(predicate, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const value = predicate();
    if (value) return value;
    await sleep(300);
  }
  return null;
}
function findButton(pattern) {
  return [...document.querySelectorAll("button, [role='button'], a")]
    .filter(visible)
    .find(btn => pattern.test(textOf(btn)) && !btn.disabled);
}
async function ensureSettingsOpen() {
  if (/球場別入力者の一括反映/.test(document.body.innerText || "") && findButton(/^一括反映$/)) return true;
  const button = findButton(/設定を開く/);
  if (!button) return false;
  button.scrollIntoView({block:"center", inline:"center"});
  button.click();
  await sleep(600);
  return !!await waitFor(() => /球場別入力者の一括反映/.test(document.body.innerText || "") && findButton(/^一括反映$/), 30000);
}
function bulkContainer() {
  const button = findButton(/^一括反映$/);
  if (!button) return null;
  let node = button.parentElement;
  for (let i = 0; node && i < 8; i++, node = node.parentElement) {
    const text = textOf(node);
    if (/球場別入力者の一括反映/.test(text) && /一括反映/.test(text)) return node;
  }
  return button.parentElement;
}
function bulkInputs() {
  const container = bulkContainer();
  if (!container) return [];
  return [...container.querySelectorAll('input[id^="react-select-"]')]
    .filter(visible)
    .filter(input => {
      let p = input.parentElement;
      for (let i = 0; p && i < 5; i++, p = p.parentElement) {
        if (/select__control/.test(String(p.className || ""))) {
          const text = textOf(p);
          return !/球場別入力者の一括反映/.test(text);
        }
      }
      return false;
    });
}
function controlForInput(input) {
  let p = input.parentElement;
  for (let i = 0; p && i < 6; i++, p = p.parentElement) {
    if (/select__control/.test(String(p.className || ""))) return p;
  }
  return input;
}
function optionMatches(option, label) {
  const text = norm(textOf(option));
  const target = norm(label);
  return text && (text.includes(target) || target.includes(text));
}
async function selectReact(input, label) {
  const control = controlForInput(input);
  control.scrollIntoView({block:"center", inline:"center"});
  control.click();
  await sleep(250);
  input = control.querySelector('input[id^="react-select-"]') || input;
  setValue(input, label);
  await sleep(800);
  let options = [...document.querySelectorAll('[role="option"], .select__option, [id*="-option-"]')].filter(visible);
  let option = options.find(opt => optionMatches(opt, label));
  if (!option) {
    const shortLabel = String(label || "").replace(/中国地区.*/, "中国地区");
    setValue(input, shortLabel);
    await sleep(800);
    options = [...document.querySelectorAll('[role="option"], .select__option, [id*="-option-"]')].filter(visible);
    option = options.find(opt => optionMatches(opt, label) || optionMatches(opt, shortLabel));
  }
  if (!option) return false;
  option.scrollIntoView({block:"center", inline:"center"});
  option.click();
  await sleep(350);
  return true;
}
function installDialogAutoAccept() {
  window.confirm = () => true;
  window.alert = () => {};
}
(async () => {
  try {
    if (!await ensureSettingsOpen()) throw new Error("設定を開くボタン、または球場別入力者の一括反映画面を検出できません");
    await waitFor(() => bulkInputs().length > 0, 30000);
    const inputs = bulkInputs();
    const expected = (payload.venues || []).length || inputs.length;
    if (!inputs.length) throw new Error("球場別入力者の選択欄を検出できません");
    for (const input of inputs.slice(0, expected)) {
      if (await selectReact(input, payload.inputter)) result.selected += 1;
    }
    if (!result.selected) throw new Error("入力者を選択できません: " + payload.inputter);
    installDialogAutoAccept();
    const button = findButton(/^一括反映$/);
    if (!button) throw new Error("一括反映ボタンを検出できません");
    button.scrollIntoView({block:"center", inline:"center"});
    button.click();
    result.clicked = true;
    await sleep(1200);
    result.ok = true;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
            payload,
        )

    def _accept_eleague_alerts(self, driver, WebDriverWait, timeout=8):
        accepted = 0
        end_time = time.time() + timeout
        while time.time() < end_time and accepted < 3:
            try:
                alert = WebDriverWait(driver, 1).until(lambda d: d.switch_to.alert)
                alert.accept()
                accepted += 1
                time.sleep(0.5)
            except Exception:
                break
        try:
            driver.set_script_timeout(max(10, timeout + 2))
        except Exception:
            pass
        try:
            result = driver.execute_async_script(
                r'''
const timeoutMs = arguments[0];
const done = arguments[arguments.length - 1];
const result = {clicked:[], message:""};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function visible(el) {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el && (el.innerText || el.textContent) || "").trim(); }
function visibleDialogs() {
  return [...document.querySelectorAll('[role="dialog"], .MuiDialog-paper, .MuiDialog-root, .swal2-container, .modal')]
    .filter(visible)
    .filter(el => textOf(el));
}
function findDialogButton(labels) {
  const dialogs = visibleDialogs();
  const buttons = [...document.querySelectorAll("button, [role='button'], a")].filter(visible);
  for (const dialog of dialogs) {
    for (const label of labels) {
      const found = buttons.find(btn => dialog.contains(btn) && textOf(btn) === label && !btn.disabled);
      if (found) return {button: found, label};
    }
  }
  return null;
}
(async () => {
  try {
    const started = Date.now();
    const sequence = [
      ["はい", "OK", "ＯＫ"],
      ["OK", "ＯＫ"],
    ];
    for (const labels of sequence) {
      let clickedThisStep = false;
      while (Date.now() - started < timeoutMs) {
        const target = findDialogButton(labels);
        if (target) {
          target.button.scrollIntoView({block:"center", inline:"center"});
          target.button.click();
          result.clicked.push(target.label);
          clickedThisStep = true;
          await sleep(700);
          break;
        }
        await sleep(250);
      }
      if (!clickedThisStep && labels.includes("はい")) {
        continue;
      }
    }
    const end = Date.now() + 2500;
    while (Date.now() < end) {
      const target = findDialogButton(["OK", "ＯＫ", "はい"]);
      if (!target) break;
      target.button.scrollIntoView({block:"center", inline:"center"});
      target.button.click();
      result.clicked.push(target.label);
      await sleep(700);
    }
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();
''',
                timeout * 1000,
            )
            accepted += len((result or {}).get("clicked") or [])
        except Exception:
            pass
        return accepted

    def setup_eleague_recorders(self):
        try:
            payloads = self._eleague_stage6_payloads()
            self.persist_settings()
            summary = "\n".join(
                f"{p['division']}: CupID {p['cup_id']} / {len(p['venues'])}球場 / {p['inputter']}"
                for p in payloads
            )
            if not messagebox.askyesno(
                APP_NAME,
                "E-League第六段階を自動設定します。\n\n"
                "球場別入力者の一括反映で記録員を設定します。\n\n"
                f"{summary}\n\n対象は１部・２部のみです。続行しますか？",
            ):
                return
            use_progress = True
            self._show_progress_dialog(
                "E-League 記録員設定",
                "Chromeを準備しています。\nしばらくお待ちください。",
            )
            driver, WebDriverWait = self._get_wp_driver()

            def wait_ready(timeout=60):
                self._update_progress_dialog("ページの読み込み完了を待っています。\nしばらくお待ちください。")
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )

            def wait_page_text(pattern, timeout=60):
                self._update_progress_dialog("E-League画面の表示完了を待っています。\nネットワーク状況により時間がかかる場合があります。")
                regex = re.compile(pattern)
                WebDriverWait(driver, timeout).until(
                    lambda d: bool(regex.search(d.execute_script(
                        "return document.body ? (document.body.innerText || document.body.textContent || '') : '';"
                    ) or ""))
                )

            try:
                driver.set_script_timeout(120)
            except Exception:
                pass

            successes = []
            failures = []
            try:
                for index, payload in enumerate(payloads, start=1):
                    label = payload["division"]
                    cup_id = payload["cup_id"]
                    self._update_progress_dialog(
                        f"{label}の記録員設定を開始しています。({index}/{len(payloads)})\n"
                        f"{len(payload['venues'])}球場へ {payload['inputter']} を一括反映します。"
                    )
                    driver.get(f"https://safe.omyutech.com/cup/{cup_id}/assign")
                    wait_ready()
                    wait_page_text(r"設定を開く|球場別入力者の一括反映|一括反映|入力者", 60)
                    result = self._eleague_bulk_assign_recorders(driver, payload)
                    self._accept_eleague_alerts(driver, WebDriverWait, 8)
                    if result and result.get("ok"):
                        successes.append(f"{label}: {result.get('selected', 0)}球場")
                        time.sleep(1.5)
                    else:
                        failures.append(f"{label}: {(result or {}).get('message', result)}")
            finally:
                if use_progress:
                    self._close_progress_dialog()
            try:
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    "E-League第六段階を実行しました。\n\n"
                    f"成功:\n{chr(10).join(successes) if successes else 'なし'}\n\n"
                    "失敗:\n" + "\n".join(failures),
                )
            else:
                messagebox.showinfo(APP_NAME, "E-League第六段階が完了しました。\n" + "\n".join(successes))
        except Exception as e:
            self._close_progress_dialog()
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def open_eleague_tournament_create(self):
        try:
            year = self.year_var.get().strip()
            if not re.fullmatch(r"\d{4}", year):
                raise ValueError("日程画面の作成年度は西暦4桁で入力してください。")

            create_url = self._eleague_create_url(year)
            payloads = self._eleague_create_payloads()

            self.persist_settings()

            summary = "\n".join(
                f"{p['division']}: {p['name']} / {p['start']} - {p['end']}"
                for p in payloads
            )
            if not messagebox.askyesno(
                APP_NAME,
                "E-Leagueで大会を自動作成します。\n\n"
                f"{summary}\n\n"
                "ログイン画面が表示された場合は、開いたChromeで手動ログインしてください。\n"
                "ID・パスワードは自動入力しません。続行しますか？",
            ):
                return

            driver, WebDriverWait = self._get_wp_driver()

            def wait_ready(timeout=60):
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )

            failures = []
            successes = []
            created_payloads = []
            for payload in payloads:
                driver.get(create_url)
                wait_ready()
                WebDriverWait(driver, 30).until(
                    lambda d: d.execute_script("return !!document.body && (document.body.innerText || document.body.textContent || '').length > 0")
                )
                body_text = driver.execute_script("return document.body ? (document.body.innerText || document.body.textContent || '') : ''")
                if "ログイン" in body_text and "大会名" not in body_text:
                    raise RuntimeError(
                        "E-League\u306e\u30ed\u30b0\u30a4\u30f3\u753b\u9762\u304c\u8868\u793a\u3055\u308c\u305f\u305f\u3081\u3001\u5927\u4f1a\u4f5c\u6210\u3092\u505c\u6b62\u3057\u307e\u3057\u305f\u3002\n\n"
                        "\u5148\u306bChrome\u3067E-League\u3078\u30ed\u30b0\u30a4\u30f3\u3057\u3066\u304b\u3089\u3001\u3082\u3046\u4e00\u5ea6\u5927\u4f1a\u4f5c\u6210\u3092\u5b9f\u884c\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
                    )
                result = self._eleague_autofill_create_form(driver, payload)
                if result and result.get("ok"):
                    successes.append(payload["division"])
                    created_payloads.append(payload)
                    time.sleep(1.2)
                else:
                    failures.append(f"{payload['division']}: {(result or {}).get('message', result)}")
            cup_ids = {}
            cup_id_failures = []
            if created_payloads:
                try:
                    cup_ids, cup_id_failures = self._eleague_fetch_cup_ids_from_league(driver, WebDriverWait, created_payloads)
                except Exception as e:
                    cup_id_failures = [str(e)]
            focus_chrome_window(driver)
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    "E-League大会作成を実行しました。\n\n"
                    f"成功: {', '.join(successes) if successes else 'なし'}\n"
                    "失敗:\n" + "\n".join(failures)
                    + (("\n\nCupID取得失敗:\n" + "\n".join(cup_id_failures)) if cup_id_failures else ""),
                )
            else:
                cup_id_lines = []
                labels = {"1": "１部", "2": "２部", "3": "入替戦"}
                for key in ("1", "2", "3"):
                    if cup_ids.get(key):
                        cup_id_lines.append(f"{labels[key]}: {cup_ids[key]}")
                message = "E-League大会作成が完了しました。\n" + "、".join(successes)
                if cup_id_lines:
                    message += "\n\nCupID:\n" + "\n".join(cup_id_lines)
                if cup_id_failures:
                    message += "\n\nCupID取得失敗:\n" + "\n".join(cup_id_failures)
                messagebox.showinfo(APP_NAME, message)
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def _get_wp_driver(self):
        selenium_pack = safe_import_selenium()
        if selenium_pack is None:
            raise RuntimeError(
                "Selenium がインストールされていません。\n\n"
                "コマンドプロンプトで次を実行してください。\n"
                "pip install selenium"
            )

        webdriver, ChromeOptions, ChromeService, WebDriverWait = selenium_pack

        if self.wp_driver is not None:
            try:
                handles = list(self.wp_driver.window_handles)
                if handles:
                    try:
                        current = self.wp_driver.current_window_handle
                    except Exception:
                        current = None
                    if current not in handles:
                        self.wp_driver.switch_to.window(handles[-1])
                    _ = self.wp_driver.current_url
                    return self.wp_driver, WebDriverWait
            except Exception:
                self.wp_driver = None

        SELENIUM_PROFILE_DIR.mkdir(exist_ok=True)
        profile = str(SELENIUM_PROFILE_DIR)
        last_error = None

        def chrome_options():
            options = ChromeOptions()
            options.add_argument(f"--user-data-dir={profile}")
            options.add_argument("--profile-directory=Default")
            options.add_argument("--start-maximized")
            options.add_argument("--remote-debugging-port=9222")
            options.add_experimental_option("detach", True)
            return options

        try:
            self.wp_driver = webdriver.Chrome(options=chrome_options())
            return self.wp_driver, WebDriverWait
        except Exception as e:
            last_error = e

        try:
            attach_options = ChromeOptions()
            attach_options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
            self.wp_driver = webdriver.Chrome(options=attach_options)
            return self.wp_driver, WebDriverWait
        except Exception as e:
            last_error = f"{last_error} / attach existing Chrome: {e}"

        manager_pack = safe_import_webdriver_manager()
        if manager_pack is not None:
            ChromeDriverManager = manager_pack
            try:
                service = ChromeService(ChromeDriverManager().install())
                self.wp_driver = webdriver.Chrome(service=service, options=chrome_options())
                return self.wp_driver, WebDriverWait
            except Exception as e:
                last_error = f"{last_error} / ChromeDriverManager: {e}"

        raise RuntimeError(
            "Chrome のSelenium起動に失敗しました。\n\n"
            "Google Chrome がインストールされているか確認してください。\n"
            "それでも失敗する場合は、Chrome を最新版へ更新してください。\n\n"
            f"詳細: {last_error}"
        )

    def upload_schedule_excel_media(self):
        try:
            excel_file = self.schedule_excel_file_var.get().strip()
            if not excel_file:
                raise ValueError("日程表Excelファイルを選択してください。")
            excel_path = app_path(excel_file)
            if not excel_path or not excel_path.exists():
                raise ValueError("日程表Excelファイルが見つかりません。")

            media_url = self.media_new_url_var.get().strip()
            if not media_url:
                raise ValueError("設定画面でファイル新規投稿URLを入力してください。")
            if not (media_url.startswith("http://") or media_url.startswith("https://")):
                raise ValueError("ファイル新規投稿URLは http:// または https:// から入力してください。")

            if not messagebox.askyesno(
                APP_NAME,
                "WordPressメディアライブラリーへ日程表Excelをアップロードします。\n\n"
                "ログイン画面が表示された場合は、開いたChromeで手動ログイン後に続行できます。\n"
                "ID・パスワードは自動入力しません。続行しますか？",
            ):
                return

            driver, WebDriverWait = self._get_wp_driver()
            driver.get(media_url)

            def is_login_page(d):
                try:
                    current = (d.current_url or "").lower()
                    has_login = d.execute_script(
                        "return !!document.querySelector('form#loginform,input#user_login,input[name=\"log\"]');"
                    )
                    return "wp-login.php" in current or bool(has_login)
                except Exception:
                    return False

            wait = WebDriverWait(driver, 30)

            def wait_ready(timeout=30):
                WebDriverWait(driver, timeout).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )

            try:
                wait_ready()
            except Exception:
                pass

            if is_login_page(driver):
                messagebox.showinfo(
                    APP_NAME,
                    "アップロード用ChromeでWordPressログイン画面が開きました。\n\n"
                    "このChromeで手動ログインしてください。\n"
                    "ログインしてメディア画面が表示されたら、このメッセージのOKを押すとアップロードを続行します。\n\n"
                    "一度ログインすれば、次回からは同じアップロード用Chromeにログイン状態が残ります。",
                )
                driver.get(media_url)
                try:
                    wait_ready(45)
                except Exception:
                    pass
                if is_login_page(driver):
                    raise RuntimeError(
                        "まだWordPressログイン画面のままです。\n\n"
                        "アップロード用Chromeでログインを完了してから、もう一度メディアアップロードを実行してください。"
                    )

            file_inputs = driver.find_elements("css selector", "input[type='file']")
            if not file_inputs:
                raise RuntimeError(
                    "アップロード用のファイル選択欄が見つかりませんでした。\n"
                    "メディアの新規追加画面が表示されているか確認してください。"
                )

            file_inputs[0].send_keys(str(excel_path.resolve()))
            file_name = excel_path.name
            WebDriverWait(driver, 90).until(
                lambda d: is_login_page(d)
                or file_name in (d.execute_script("return document.body ? document.body.innerText : '';") or "")
            )
            if is_login_page(driver):
                raise RuntimeError("アップロード中にログイン画面へ移動したため停止しました。")

            download_url = self.default_download_url(excel_file)
            self.schedule_download_url_var.set(download_url)
            self.persist_settings()
            messagebox.showinfo(
                APP_NAME,
                f"アップロード処理を実行しました。\n\nダウンロードリンクを更新しました。\n{download_url}",
            )
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def _eleague_norm(self, value):
        return re.sub(r"[\s\u3000\u200b\u200c\ufeff]+", "", str(value or "")).replace("－", "-").replace("‐", "-").replace("–", "-").replace("—", "-").replace("ー", "-").replace("―", "-").lower()

    def _eleague_tournament_url(self, url):
        url = (url or "").strip()
        match = re.search(r"^(https?://[^/]+/cup/\d+)", url)
        if match:
            return match.group(1).rstrip("/") + "/tournament"
        return url

    def _eleague_visible_dialog(self, driver):
        return driver.execute_script(
            r'''
const visible = el => {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
};
const textOf = el => (el.innerText || el.textContent || "").trim();
const nodes = [...document.querySelectorAll('[role="dialog"], .MuiDialog-root, .MuiModal-root, .MuiPopover-paper, .MuiPaper-root')]
  .filter(el => visible(el) && /試合設定|試合日|開始時刻|試合球場/.test(textOf(el)));
nodes.sort((a, b) => {
  const ar = a.getBoundingClientRect();
  const br = b.getBoundingClientRect();
  return (ar.width * ar.height) - (br.width * br.height);
});
return nodes[0] || null;
'''
        )

    def _eleague_finish_dialog_native(self, driver, game, WebDriverWait):
        from selenium.webdriver.common.action_chains import ActionChains  # type: ignore
        from selenium.webdriver.common.by import By  # type: ignore
        from selenium.webdriver.common.keys import Keys  # type: ignore
        from selenium.common.exceptions import NoAlertPresentException  # type: ignore

        wait = WebDriverWait(driver, 10)
        dlg = wait.until(lambda d: self._eleague_visible_dialog(d))

        venue = (game.get("venue") or "").strip()
        if venue:
            labels = [
                venue,
                venue.replace("球場", ""),
                venue.replace("野球場", ""),
                f"倉 {venue}",
                f"倉　{venue}",
                f"倉{venue}",
                f"玉 {venue}",
                f"玉　{venue}",
                f"玉{venue}",
            ]
            label_norms = [self._eleague_norm(x) for x in labels if x]

            venue_control = driver.execute_script(
                r'''
const root = arguments[0];
const visible = el => {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
};
const controls = [...root.querySelectorAll('#mui-component-select-stadium, [aria-haspopup="listbox"], .MuiSelect-select')]
  .filter(visible);
return controls.find(el => el.id === 'mui-component-select-stadium') || controls[controls.length - 1] || null;
''',
                dlg,
            )
            if venue_control is None:
                raise RuntimeError("球場ドロップダウンが見つかりません")

            driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", venue_control)
            def open_venue_menu():
                driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", venue_control)
                try:
                    venue_control.click()
                except Exception:
                    ActionChains(driver).move_to_element(venue_control).pause(0.1).click().perform()
                time.sleep(0.4)

            def visible_options(d):
                options = d.find_elements(By.CSS_SELECTOR, "li[role='option'], [role='option'], li.MuiMenuItem-root")
                return [o for o in options if o.is_displayed()]

            def option_match(d):
                for option in visible_options(d):
                    text = option.text or option.get_attribute("textContent") or ""
                    text_norm = self._eleague_norm(text)
                    if any(text_norm == label or text_norm.endswith(label) or label.endswith(text_norm) or label in text_norm for label in label_norms):
                        return option
                if "倉敷" in venue or "市営" in venue:
                    for option in visible_options(d):
                        if "倉敷市営球場" in (option.text or option.get_attribute("textContent") or ""):
                            return option
                if "玉島" in venue or "森" in venue:
                    for option in visible_options(d):
                        if "玉島の森野球場" in (option.text or option.get_attribute("textContent") or ""):
                            return option
                return False

            def selected_state():
                return driver.execute_script(
                    r'''
const root = arguments[0];
const expected = arguments[1];
const norm = value => String(value || "").replace(/[\s　\u200b\u200c\ufeff]/g, "").replace(/[－‐–—ー―]/g, "-").toLowerCase();
const control = root.querySelector('#mui-component-select-stadium, [aria-haspopup="listbox"], .MuiSelect-select');
const hidden = root.querySelector('input[name="stadium"], .MuiSelect-nativeInput');
const shown = control ? (control.innerText || control.textContent || "") : "";
const hiddenValue = hidden ? hidden.value : "";
return {ok: hidden ? !!hiddenValue : expected.some(x => norm(shown).includes(x)), shown, hiddenValue};
''',
                    dlg,
                    label_norms,
                )

            open_venue_menu()
            option = wait.until(option_match)
            option_text = option.text or option.get_attribute("textContent") or ""
            option_value = option.get_attribute("data-value") or option.get_attribute("value") or option_text
            options_now = visible_options(driver)
            option_texts = [o.text or o.get_attribute("textContent") or "" for o in options_now]
            target_index = -1
            for i, candidate in enumerate(options_now):
                if candidate.id == option.id:
                    target_index = i
                    break
            prefers_tamashima = "玉島" in venue or "森" in venue
            prefers_kurashiki = ("倉敷" in venue or "市営" in venue) and not prefers_tamashima
            preferred_index = -1
            for i, text in enumerate(option_texts):
                text_norm = self._eleague_norm(text)
                if not text_norm:
                    continue
                if prefers_tamashima and ("玉" in text or "玉島" in text or "森" in text):
                    preferred_index = i
                    break
                if prefers_kurashiki and ("倉" in text or "倉敷" in text or "市営" in text):
                    preferred_index = i
                    break
            if preferred_index >= 0:
                target_index = preferred_index
                option = options_now[target_index]
                option_text = option_texts[target_index]
            option_text_norm = self._eleague_norm(option_text)
            if target_index < 0 or not option_text_norm:
                for i, text in enumerate(option_texts):
                    text_norm = self._eleague_norm(text)
                    if not text_norm:
                        continue
                    if prefers_tamashima and not ("玉" in text or "玉島" in text or "森" in text):
                        continue
                    if prefers_kurashiki and not ("倉" in text or "倉敷" in text or "市営" in text):
                        continue
                    if any(text_norm == label or text_norm.endswith(label) or label.endswith(text_norm) or label in text_norm for label in label_norms):
                        target_index = i
                        option_text = text
                        option_text_norm = text_norm
                        break
            if target_index < 0:
                for i, text in enumerate(option_texts):
                    if self._eleague_norm(text):
                        target_index = i
                        option_text = text
                        break
            if target_index < 0:
                target_index = 0
            if 0 <= target_index < len(options_now):
                option = options_now[target_index]
                option_text = option_texts[target_index]
                option_value = option.get_attribute("data-value") or option.get_attribute("value") or option_text
            if not option_value:
                option_value = option_text
            venue_value_candidates = [option_value, option_text]
            is_tamashima = "玉島" in venue or "森" in venue or option_text.strip().startswith("玉")
            is_kurashiki = ("倉敷" in venue or "市営" in venue or option_text.strip().startswith("倉")) and not is_tamashima
            if is_tamashima:
                venue_value_candidates += ["玉", "玉島の森野球場", "玉 玉島の森野球場", "玉　玉島の森野球場"]
            if is_kurashiki:
                venue_value_candidates += ["倉", "倉敷市営球場", "倉 倉敷市営球場", "倉　倉敷市営球場"]
            venue_value_candidates = [x for i, x in enumerate(venue_value_candidates) if x and x not in venue_value_candidates[:i]]
            driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", option)
            try:
                option.click()
            except Exception:
                ActionChains(driver).move_to_element(option).pause(0.1).click().perform()
            time.sleep(0.4)

            selected_ok = selected_state()
            if not selected_ok or not selected_ok.get("ok"):
                open_venue_menu()
                keys = [Keys.HOME] + [Keys.ARROW_DOWN] * target_index + [Keys.ENTER]
                ActionChains(driver).pause(0.1).send_keys(*keys).perform()
                time.sleep(0.5)
                selected_ok = selected_state()

            if not selected_ok or not selected_ok.get("ok"):
                selected_ok = driver.execute_script(
                    r'''
const root = arguments[0];
const optionText = arguments[1];
const optionValues = arguments[2];
const expected = arguments[3];
const norm = value => String(value || "").replace(/[\s　\u200b\u200c\ufeff]/g, "").replace(/[－‐–—ー―]/g, "-").toLowerCase();
const control = root.querySelector('#mui-component-select-stadium, [aria-haspopup="listbox"], .MuiSelect-select');
const hidden = root.querySelector('input[name="stadium"], .MuiSelect-nativeInput');
function reactProps(el) {
  if (!el) return null;
  const key = Object.keys(el).find(k => k.startsWith('__reactProps$') || k.startsWith('__reactEventHandlers$'));
  return key ? el[key] : null;
}
function nativeSetValue(input, value) {
  if (!input) return;
  const proto = Object.getPrototypeOf(input);
  const desc = Object.getOwnPropertyDescriptor(proto, 'value') || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  if (input._valueTracker) input._valueTracker.setValue(input.value);
  if (desc && desc.set) desc.set.call(input, value); else input.value = value;
}
function callHandler(el, names, event) {
  for (let node = el; node && node !== document.body; node = node.parentElement) {
    const props = reactProps(node);
    if (!props) continue;
    for (const name of names) {
      if (typeof props[name] === 'function') {
        props[name](event);
        return true;
      }
    }
  }
  return false;
}
const event = {
  bubbles: true,
  cancelable: true,
  target: { name: 'stadium', value: '' },
  currentTarget: { name: 'stadium', value: '' },
  nativeEvent: new MouseEvent('click', {bubbles:true, cancelable:true, view:window}),
  preventDefault() {},
  stopPropagation() {},
  persist() {},
};
let usedValue = "";
for (const optionValue of optionValues) {
  usedValue = optionValue;
  event.target.value = optionValue;
  event.currentTarget.value = optionValue;
  nativeSetValue(hidden, optionValue);
  if (hidden) {
    hidden.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:String(optionValue)}));
    hidden.dispatchEvent(new Event('change', {bubbles:true}));
  }
  callHandler(hidden, ['onChange'], event);
  callHandler(control, ['onChange'], event);
  const hiddenValueTry = hidden ? hidden.value : "";
  if (hiddenValueTry) break;
}
const shown = control ? (control.innerText || control.textContent || "") : "";
const hiddenValue = hidden ? hidden.value : "";
return {ok: hidden ? !!hiddenValue : expected.some(x => norm(shown).includes(x)), shown, hiddenValue, optionValue: usedValue, optionText};
''',
                    dlg,
                    option_text,
                    venue_value_candidates,
                    label_norms,
                )

            if not selected_ok or not selected_ok.get("ok"):
                raise RuntimeError(
                    f"球場が選択されていません: {venue}（表示:{(selected_ok or {}).get('shown', '')} / 値:{(selected_ok or {}).get('hiddenValue', '')} / option:{(selected_ok or {}).get('optionValue', '')} / 候補:{' / '.join(option_texts)} / index:{target_index}）"
                )

        set_button = driver.execute_script(
            r'''
const root = arguments[0];
const visible = el => {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
};
return [...root.querySelectorAll('button, [role="button"]')]
  .filter(visible)
  .find(el => ((el.innerText || el.textContent || "").trim() === "設定")) || null;
''',
            dlg,
        )
        if set_button is None:
            raise RuntimeError("設定ボタンが見つかりません")
        driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", set_button)
        ActionChains(driver).move_to_element(set_button).pause(0.1).click().perform()
        time.sleep(0.5)
        try:
            alert = driver.switch_to.alert
            alert_text = alert.text
            alert.accept()
            if alert_text:
                raise RuntimeError(f"Alert: {alert_text}")
        except NoAlertPresentException:
            pass

    def _eleague_cancel_dialog_native(self, driver):
        try:
            dlg = self._eleague_visible_dialog(driver)
            if not dlg:
                return
            cancel_button = driver.execute_script(
                r'''
const root = arguments[0];
const visible = el => {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
};
return [...root.querySelectorAll('button, [role="button"]')]
  .filter(visible)
  .find(el => ((el.innerText || el.textContent || "").trim() === "キャンセル")) || null;
''',
                dlg,
            )
            if cancel_button is not None:
                cancel_button.click()
                time.sleep(0.2)
        except Exception:
            pass

    def register_eleague_schedule(self):
        try:
            excel_file = self.schedule_excel_file_var.get().strip()
            if not excel_file:
                raise ValueError("日程表Excelファイルを選択してください。")
            excel_path = app_path(excel_file)
            if not excel_path or not excel_path.exists():
                raise ValueError("日程表Excelファイルが見つかりません。")

            excel_text = load_xlsx_schedule_text(str(excel_path))
            default_year = int(self.year_var.get().strip())
            cup_ids = {
                "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
                "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
            }
            batches = []
            missing = []
            for key in ("1", "2"):
                games = collect_eleague_schedule_games(excel_text, default_year, key)
                if not games:
                    continue
                if not cup_ids[key]:
                    missing.append(division_label_from_key(key))
                    continue
                label = division_label_from_key(key)
                batches.append((label, f"https://safe.omyutech.com/cup/{cup_ids[key]}/tournament", games))
            if missing:
                raise ValueError("設定画面でCupIDを入力してください: " + "、".join(missing))
            if not batches:
                raise ValueError("E-leagueへ登録できる1部・2部の試合日程が見つかりませんでした。Excelを確認してください。")

            all_games = [(label, game) for label, _url, games in batches for game in games]
            sample = "\n".join(f"{label}: {g['date']} {g['time']} {g['team1']} - {g['team2']} / {g['venue']}" for label, g in all_games[:8])
            more = "" if len(all_games) <= 8 else f"\n...ほか {len(all_games) - 8} 試合"
            if not messagebox.askyesno(
                APP_NAME,
                f"E-leagueへ {len(all_games)} 試合を登録します。\n\n"
                "メール認証・ログインは自動化しません。開いたChromeでログイン済みの大会画面にしてください。\n"
                "既に登録済みの試合がある場合は重複に注意してください。\n\n"
                f"{sample}{more}\n\n続行しますか？",
            ):
                return

            driver, WebDriverWait = self._get_wp_driver()
            focus_chrome_window(driver)

            script = r'''const done = arguments[arguments.length - 1];
const game = arguments[0];
const result = {ok:false, message:""};
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function norm(value) {
  return String(value || "").replace(/[\s　\u200b\u200c\ufeff]/g, "").replace(/[－‐–—ー―]/g, "-").toLowerCase();
}
function teamAliasNorms(value) {
  const v = norm(value);
  const kibikoku = [norm("吉国大"), norm("吉備国")];
  if (kibikoku.includes(v)) return kibikoku;
  return [v];
}
function teamNameMatches(text, wanted) {
  const n = norm(text);
  return teamAliasNorms(wanted).some(w => !!n && !!w && (n === w || n.includes(w) || w.includes(n)));
}
function textHasTeam(text, wanted) {
  const n = norm(text);
  return teamAliasNorms(wanted).some(w => !!n && !!w && n.includes(w));
}
function visible(el) {
  const r = el.getBoundingClientRect();
  const s = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
}
function textOf(el) { return (el.innerText || el.textContent || "").trim(); }
function center(rect) { return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}; }
function visibleElements() { return [...document.querySelectorAll('body *')].filter(visible); }
function findTextElements(label) {
  const n = norm(label);
  return visibleElements().filter(el => norm(textOf(el)) === n);
}
function plusButtons() {
  return [...document.querySelectorAll('button')].filter(btn => {
    if (!visible(btn)) return false;
    const txt = textOf(btn);
    const aria = btn.getAttribute('aria-label') || '';
    const paths = [...btn.querySelectorAll('path')].map(p => p.getAttribute('d') || '').join(' ');
    const compactPaths = paths.replace(/\s/g, '');
    const cls = String(btn.className || '');
    const r = btn.getBoundingClientRect();
    const isPlusIcon = /M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2/.test(paths)
      || compactPaths.includes('M1913h-6v6h-2v-6H5v-2h6V5h2v6h6v2')
      || /jss361/.test(cls);
    const isDeleteIcon = /M19 6\.41L17\.59 5 12 10\.59/.test(paths) || /jss346/.test(cls);
    const looksLikeIconButton = !!btn.querySelector('svg') && !txt && r.width <= 90 && r.height <= 90;
    return !isDeleteIcon && (txt === '+' || /add|追加|登録|plus/i.test(aria) || isPlusIcon || !!btn.querySelector('svg[data-testid*="Add"]') || looksLikeIconButton);
  });
}
function headerCells(table) {
  const rows = [...table.querySelectorAll('tr')];
  return rows.length ? [...rows[0].children] : [];
}
async function clickAtIntersection(rowTeam, colTeam) {
  const wantedRow = norm(rowTeam);
  const wantedCol = norm(colTeam);
  const tables = [...document.querySelectorAll('table')];
  let sawRow = false;
  let sawCol = false;
  const rowSamples = [];
  const colSamples = [];
  function isMatch(text, wanted) {
    return teamNameMatches(text, wanted);
  }
  function cellSample(cell) {
    return textOf(cell).replace(/\s+/g, ' ').trim();
  }
  function findMatchedCells(table, wanted) {
    return [...table.querySelectorAll('th,td')].filter(cell => isMatch(textOf(cell), wanted));
  }
  function bestPlusFor(rowCell, colCell) {
    const rowRect = rowCell.getBoundingClientRect();
    const colRect = colCell.getBoundingClientRect();
    const targetX = colRect.left + colRect.width / 2;
    const targetY = rowRect.top + rowRect.height / 2;
    let best = null;
    let bestScore = Infinity;
    for (const btn of plusButtons()) {
      const r = btn.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const dx = Math.abs(cx - targetX);
      const dy = Math.abs(cy - targetY);
      const xLimit = Math.max(90, colRect.width * 0.55);
      const yLimit = Math.max(45, rowRect.height * 0.85);
      if (dx > xLimit || dy > yLimit) continue;
      const score = dx + dy * 1.8;
      if (score < bestScore) {
        bestScore = score;
        best = btn;
      }
    }
    return best;
  }
  for (const table of tables) {
    const allCells = [...table.querySelectorAll('th,td')];
    for (const cell of allCells.slice(0, 80)) {
      const sample = cellSample(cell);
      if (sample && rowSamples.length < 12 && !rowSamples.includes(sample)) rowSamples.push(sample);
      if (sample && colSamples.length < 12 && !colSamples.includes(sample)) colSamples.push(sample);
    }
    const rowCells = findMatchedCells(table, wantedRow);
    const colCells = findMatchedCells(table, wantedCol);
    if (rowCells.length) sawRow = true;
    if (colCells.length) sawCol = true;
    for (const rowCell of rowCells) {
      const rowRect0 = rowCell.getBoundingClientRect();
      for (const colCell of colCells) {
        if (rowCell === colCell) continue;
        const colRect0 = colCell.getBoundingClientRect();
        if (colRect0.top >= rowRect0.top) continue;
        if (colRect0.left <= rowRect0.left + 10) continue;
        colCell.scrollIntoView({block:'nearest', inline:'center'});
        await sleep(80);
        rowCell.scrollIntoView({block:'center', inline:'nearest'});
        await sleep(160);
        const btn = bestPlusFor(rowCell, colCell);
        if (!btn) continue;
        btn.scrollIntoView({block:'center', inline:'center'});
        await sleep(60);
        btn.click();
        return true;
      }
    }
    const rows = [...table.querySelectorAll('tr')];
    const heads = headerCells(table);
    const colIndex = heads.findIndex(cell => isMatch(textOf(cell), wantedCol));
    if (colIndex >= 0) sawCol = true;
    if (colIndex < 1) continue;
    for (const row of rows.slice(1)) {
      const cells = [...row.children];
      if (!cells.length) continue;
      if (!isMatch(textOf(cells[0]), wantedRow)) continue;
      sawRow = true;
      if (cells.length <= colIndex) continue;
      const targetCell = cells[colIndex];
      row.scrollIntoView({block:'center', inline:'nearest'});
      targetCell.scrollIntoView({block:'center', inline:'center'});
      await sleep(100);
      const btn = plusButtons().find(button => targetCell.contains(button));
      if (!btn) return false;
      btn.scrollIntoView({block:'center', inline:'center'});
      btn.click();
      return true;
    }
  }
  if (!sawRow) throw new Error(`行チームが見つかりません: ${rowTeam}（候補:${rowSamples.join(' / ')}）`);
  if (!sawCol) throw new Error(`列チームが見つかりません: ${colTeam}（候補:${colSamples.join(' / ')}）`);
  return false;
}
function dialog() {
  const candidates = [...document.querySelectorAll('[role="dialog"], .MuiDialog-root, .MuiModal-root, .MuiPopover-paper, .MuiPaper-root')]
    .filter(el => visible(el) && /試合設定|試合日|開始時刻|試合球場/.test(textOf(el)));
  candidates.sort((a, b) => {
    const ar = a.getBoundingClientRect();
    const br = b.getBoundingClientRect();
    return (ar.width * ar.height) - (br.width * br.height);
  });
  return candidates[0] || null;
}
function setInput(input, value) {
  value = String(value || "");
  input.focus();
  if (input.select) input.select();
  const proto = Object.getPrototypeOf(input);
  const desc = Object.getOwnPropertyDescriptor(proto, 'value') || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  if (input._valueTracker) input._valueTracker.setValue(input.value);
  if (desc && desc.set) desc.set.call(input, value); else input.value = value;
  input.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:value}));
  input.dispatchEvent(new Event('change', {bubbles:true}));
  input.dispatchEvent(new KeyboardEvent('keydown', {bubbles:true, key:'Enter'}));
  input.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true, key:'Enter'}));
  input.blur();
}
function normalizeTime(value) {
  const m = String(value || "").match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return String(value || "");
  return `${m[1].padStart(2, '0')}:${m[2]}`;
}
function setNativeValue(input, value) {
  const proto = Object.getPrototypeOf(input);
  const desc = Object.getOwnPropertyDescriptor(proto, 'value') || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  if (input._valueTracker) input._valueTracker.setValue(input.value);
  if (desc && desc.set) desc.set.call(input, value); else input.value = value;
  input.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:String(value || '')}));
  input.dispatchEvent(new Event('change', {bubbles:true}));
}
function clickByText(root, labels) {
  const labelNorms = labels.map(norm);
  const els = [...root.querySelectorAll('li, [role="option"], button, [role="button"], span, div')].filter(visible);
  const hit = els.find(el => labelNorms.includes(norm(textOf(el))))
    || els.find(el => labelNorms.some(label => norm(textOf(el)).includes(label) || label.includes(norm(textOf(el)))));
  if (hit) {
    const option = hit.closest('li, [role="option"]');
    (option || hit).click();
    return true;
  }
  return false;
}
function fireMouse(el, type) {
  const r = el.getBoundingClientRect();
  const x = r.left + r.width / 2;
  const y = r.top + r.height / 2;
  el.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y}));
}
function firePointer(el, type) {
  const r = el.getBoundingClientRect();
  const x = r.left + r.width / 2;
  const y = r.top + r.height / 2;
  const EventCtor = window.PointerEvent || window.MouseEvent;
  el.dispatchEvent(new EventCtor(type, {bubbles:true, cancelable:true, view:window, clientX:x, clientY:y, pointerId:1, pointerType:'mouse', isPrimary:true}));
}
function humanClick(el) {
  el.scrollIntoView({block:'center', inline:'center'});
  firePointer(el, 'pointerover');
  fireMouse(el, 'mouseover');
  firePointer(el, 'pointermove');
  fireMouse(el, 'mousemove');
  firePointer(el, 'pointerdown');
  fireMouse(el, 'mousedown');
  callReactHandler(el, ['onMouseDown', 'onPointerDown']);
  firePointer(el, 'pointerup');
  fireMouse(el, 'mouseup');
  callReactHandler(el, ['onMouseUp', 'onPointerUp']);
  fireMouse(el, 'click');
  callReactHandler(el, ['onClick']);
  el.click();
}
function reactProps(el) {
  if (!el) return null;
  const key = Object.keys(el).find(k => k.startsWith('__reactProps$') || k.startsWith('__reactEventHandlers$'));
  return key ? el[key] : null;
}
function callReactHandler(el, names) {
  const props = reactProps(el);
  if (!props) return false;
  const event = {
    bubbles: true,
    cancelable: true,
    currentTarget: el,
    target: el,
    nativeEvent: new MouseEvent('click', {bubbles:true, cancelable:true, view:window}),
    preventDefault() {},
    stopPropagation() {},
    persist() {},
  };
  for (const name of names) {
    if (typeof props[name] === 'function') {
      props[name](event);
      return true;
    }
  }
  return false;
}
function dialogTeams(dlg) {
  const texts = [...dlg.querySelectorAll('div, span, p')]
    .filter(visible)
    .map(textOf)
    .map(t => t.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
  const stopWords = new Set(['試合設定', '先攻', '後攻', '試合日', '開始時刻', '試合球場', 'キャンセル', '設定']);
  const teams = [];
  for (const t of texts) {
    if (stopWords.has(t)) continue;
    if (/^\d{4}\/\d{2}\/\d{2}$/.test(t) || /^\d{1,2}:\d{2}$/.test(t)) continue;
    if (t.length > 12) continue;
    if (!teams.includes(t)) teams.push(t);
  }
  return teams.slice(0, 2);
}
function dialogHasExpectedTeams(dlg) {
  const text = textOf(dlg);
  return textHasTeam(text, game.team1) && textHasTeam(text, game.team2);
}
function sameTeam(a, b) {
  const left = teamAliasNorms(a);
  const right = teamAliasNorms(b);
  return left.some(x => right.includes(x));
}
function samePair(a, b, x, y) {
  return (sameTeam(a, x) && sameTeam(b, y)) || (sameTeam(a, y) && sameTeam(b, x));
}
function cancelDialog(dlg) {
  clickByText(dlg, ['キャンセル']);
}
async function selectVenue(dlg, venue) {
  const labels = [
    venue,
    venue.replace(/球場$/, ''),
    venue.replace(/野球場$/, ''),
    `倉${venue}`,
    `倉 ${venue}`,
    `倉　${venue}`,
    `玉${venue}`,
    `玉 ${venue}`,
    `玉　${venue}`,
  ].filter(Boolean);
  const controls = [...dlg.querySelectorAll('#mui-component-select-stadium, [aria-haspopup="listbox"], .MuiSelect-select')]
    .filter(visible);
  const venueControl = controls.find(el => el.id === 'mui-component-select-stadium')
    || controls.find(el => /試合球場|球場|選択/.test(textOf(el)))
    || controls[controls.length - 1];
  if (!venueControl) throw new Error('球場ドロップダウンが見つかりません');
  humanClick(venueControl);
  await sleep(500);
  const labelNorms = labels.map(norm).filter(Boolean);
  const options = [...document.querySelectorAll('li, [role="option"]')].filter(visible);
  let option = options.find(el => {
    const t = norm(textOf(el));
    return labelNorms.some(label => t === label || t.includes(label) || label.includes(t));
  });
  if (!option && /倉敷|市営/.test(venue)) option = options.find(el => norm(textOf(el)).includes(norm('倉敷市営球場')));
  if (!option && /玉島|森/.test(venue)) option = options.find(el => norm(textOf(el)).includes(norm('玉島の森野球場')));
  if (!option) {
    const optionText = options.map(textOf).filter(Boolean).slice(0, 12).join(' / ');
    throw new Error(`球場候補が選択できません: ${venue}（候補: ${optionText}）`);
  }
  humanClick(option);
  await sleep(500);
  const selectedText = norm(textOf(venueControl));
  const hidden = dlg.querySelector('input[name="stadium"], .MuiSelect-nativeInput');
  const optionValue = option.getAttribute('data-value') || option.getAttribute('value') || "";
  if (hidden && optionValue && !norm(hidden.value)) setNativeValue(hidden, optionValue);
  const hiddenValue = hidden ? norm(hidden.value) : "";
  const selectedOk = labelNorms.some(label => selectedText.includes(label) || hiddenValue.includes(label)) || !!hiddenValue;
  if (!selectedOk) {
    const visibleValue = textOf(venueControl).replace(/\s+/g, ' ').trim();
    const hiddenRaw = hidden ? hidden.value : "";
    const optionText = options.map(textOf).filter(Boolean).slice(0, 12).join(' / ');
    throw new Error(`球場が選択されていません: ${venue}（表示:${visibleValue} / 値:${hiddenRaw} / 候補:${optionText}）`);
  }
}
async function fillDialog() {
  let dlg = null;
  for (let i = 0; i < 30; i++) {
    await sleep(150);
    dlg = dialog();
    if (dlg && /試合設定|試合日|開始時刻|試合球場/.test(textOf(dlg))) break;
  }
  if (!dlg) throw new Error('試合設定ダイアログが見つかりません');
  if (!dialogHasExpectedTeams(dlg)) {
    const teams = dialogTeams(dlg);
    cancelDialog(dlg);
    const actual = teams.length >= 2 ? `${teams[0]}-${teams[1]}` : textOf(dlg).replace(/\s+/g, ' ').slice(0, 80);
    throw new Error(`別カードの＋を検出しました: ${actual} / 予定 ${game.team1}-${game.team2}`);
  }
  const inputs = [...dlg.querySelectorAll('input')]
    .filter(input => visible(input) && !input.classList.contains('MuiSelect-nativeInput') && input.getAttribute('aria-hidden') !== 'true');
  if (inputs.length < 2) throw new Error(`日付・時刻入力欄が見つかりません: ${inputs.length}件`);
  const dateValue = String(game.date || "");
  const timeValue = normalizeTime(game.time);
  if (inputs.length >= 1) setInput(inputs[0], dateValue);
  await sleep(100);
  if (inputs.length >= 2) setInput(inputs[1], timeValue);
  await sleep(100);
  if (inputs[0].value !== dateValue) throw new Error(`日付入力が反映されていません: ${inputs[0].value} / 予定 ${dateValue}`);
  if (inputs[1].value !== timeValue) throw new Error(`時刻入力が反映されていません: ${inputs[1].value} / 予定 ${timeValue}`);
  await sleep(100);
}
(async () => {
  try {
    let clicked = await clickAtIntersection(game.team1, game.team2);
    if (!clicked) clicked = await clickAtIntersection(game.team2, game.team1);
    if (!clicked) throw new Error(`＋ボタンが見つかりません: ${game.team1} - ${game.team2}`);
    await fillDialog();
    result.ok = true;
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();'''
            failures = []
            success_count = 0
            total_count = sum(len(games) for _label, _url, games in batches)
            for label, eleague_url, games in batches:
                driver.get(eleague_url)
                focus_chrome_window(driver)
                WebDriverWait(driver, 60).until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
                WebDriverWait(driver, 30).until(
                    lambda d: d.execute_script("return !!document.querySelector('table') && /チーム/.test(document.body ? document.body.innerText : '');")
                )
                for index, game in enumerate(games, 1):
                    prefix = f"{label} {index}. {game['date']} {game['time']} {game['team1']}-{game['team2']}"
                    try:
                        result = driver.execute_async_script(script, game)
                    except Exception as e:
                        if "unexpected alert" in str(e).lower() or "alert text" in str(e).lower():
                            alert_text = ""
                            try:
                                alert = driver.switch_to.alert
                                alert_text = alert.text
                                alert.accept()
                            except Exception:
                                alert_text = str(e).splitlines()[0]
                            failures.append(f"{prefix} / Alert: {alert_text}")
                            time.sleep(0.4)
                            continue
                        raise
                    if not result or not result.get("ok"):
                        if isinstance(result, dict):
                            detail = result.get("message") or result.get("error") or repr(result)
                        else:
                            detail = repr(result)
                        failures.append(f"{prefix} / {detail}")
                        continue
                    try:
                        self._eleague_finish_dialog_native(driver, game, WebDriverWait)
                        success_count += 1
                    except Exception as e:
                        self._eleague_cancel_dialog_native(driver)
                        detail = str(e).splitlines()[0] if str(e).strip() else type(e).__name__
                        failures.append(f"{prefix} / {detail}")
                    time.sleep(0.4)

            focus_chrome_window(driver)
            if failures:
                messagebox.showwarning(
                    APP_NAME,
                    f"E-league登録を実行しました。\n成功 {success_count} 件 / 失敗 {len(failures)} 件\n\n"
                    + "\n".join(failures[:8])
                )
            else:
                messagebox.showinfo(APP_NAME, f"E-leagueへ {total_count} 試合を登録しました。\n内容を確認してください。")
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def save_settings(self):
        self.persist_settings()
        messagebox.showinfo(APP_NAME, "設定を保存しました。\n文字サイズは次回起動時に反映されます。")

    def on_close(self):
        try:
            self.persist_settings()
        except Exception:
            logging.error(traceback.format_exc())
        self.root.destroy()

    def persist_settings(self):
        data = {
            "year": self.year_var.get().strip(),
            "season": self.season_var.get(),
            "division": self.division_var.get(),
            "review_division": self.review_division_var.get(),
            "review_cup_id": extract_cup_id(self.review_cup_id_var.get()),
            "review_date": self.review_date_var.get().strip(),
            "review_title": self.review_title_var.get().strip(),
            "review_game_id_1": self.review_game_id_vars[0].get().strip() if hasattr(self, "review_game_id_vars") else "",
            "review_game_id_2": self.review_game_id_vars[1].get().strip() if hasattr(self, "review_game_id_vars") else "",
            "review_game_id_3": self.review_game_id_vars[2].get().strip() if hasattr(self, "review_game_id_vars") else "",
            "review_chatgpt_text": self._get_text("review_chatgpt_text") if "review_chatgpt_text" in self.vars else "",
            "standings_division": self.standings_division_var.get(),
            "awards_division": self.awards_division_var.get(),
            "league_name": self.league_var.get().strip(),
            "wp_new_post_url": self.wp_new_post_url_var.get().strip(),
            "media_new_url": self.media_new_url_var.get().strip(),
            "media_base_url": self.media_base_url_var.get().strip(),
            "eleague_url": self.eleague_url_var.get().strip() or DEFAULT_ELEAGUE_URL,
            "eleague_title": self.eleague_title_var.get().strip(),
            "eleague_cup_id_1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "eleague_cup_id_2": extract_cup_id(self.eleague_cup_id_2_var.get()),
            "eleague_cup_id_3": extract_cup_id(self.eleague_cup_id_3_var.get()),
            "dify_api_url": self.dify_api_url_var.get().strip(),
            "dify_api_key": self.dify_api_key_var.get().strip(),
            "dify_prompt": self.dify_prompt_var.get().strip(),
            "eleague_tournament_id_1": self.config_data.get("eleague_tournament_id_1", ""),
            "eleague_tournament_id_2": self.config_data.get("eleague_tournament_id_2", ""),
            "eleague_tournament_id_3": self.config_data.get("eleague_tournament_id_3", ""),
            "font_size": self.font_size_var.get(),
            "ui_font_size": self.font_size_var.get(),
            "dates": self._get_text("dates_text"),
            "standings_text": self._get_text("standings_text"),
            "awards_text": self._get_text("awards_text") or self._get_text("standings_text"),
            "schedule_excel_file": self.schedule_excel_file_var.get().strip(),
            "schedule_title": self.schedule_title_var.get().strip(),
            "schedule_download_url": self.schedule_download_url_var.get().strip(),
            "roster_mode": self.roster_mode_var.get() if hasattr(self, "roster_mode_var") else self.config_data.get("roster_mode", "all"),
            "roster_input_folder": self.roster_input_folder_var.get().strip() if hasattr(self, "roster_input_folder_var") else self.config_data.get("roster_input_folder", ""),
            "roster_single_file": self.roster_single_file_var.get().strip() if hasattr(self, "roster_single_file_var") else self.config_data.get("roster_single_file", ""),
            "roster_output_file": self.roster_output_file_var.get().strip() if hasattr(self, "roster_output_file_var") else self.config_data.get("roster_output_file", ""),
            "roster_overwrite": bool(self.roster_overwrite_var.get()) if hasattr(self, "roster_overwrite_var") else bool(self.config_data.get("roster_overwrite", True)),
            "schedule_dates_1": self.config_data.get("schedule_dates_1", ""),
            "schedule_dates_2": self.config_data.get("schedule_dates_2", ""),
            "schedule_dates_3": self.config_data.get("schedule_dates_3", ""),
        }
        self.config_data.update(data)
        save_config(self.config_data)

    def _review_cup_id_for_key(self, key):
        manual = extract_cup_id(self.review_cup_id_var.get()) if hasattr(self, "review_cup_id_var") else ""
        return manual or self.default_review_cup_id(key)

    def _review_tournament_id_for_key(self, key):
        division = division_label_from_key(key)
        return self._eleague_tournament_id_for_key(
            key,
            make_tournament_id(self.year_var.get().strip(), self.season_var.get(), division),
        )

    def fetch_omyu_rendered_html(self, url, expected_games=None):
        driver, WebDriverWait = self._get_wp_driver()
        wait = WebDriverWait(driver, 20)
        original_handle = None
        opened_handles = set()

        def collect_rendered_text():
            chunks = []
            for handle in list(driver.window_handles):
                if original_handle and handle == original_handle:
                    continue
                try:
                    driver.switch_to.window(handle)
                    current_url = ""
                    try:
                        current_url = driver.current_url
                    except Exception:
                        pass
                    clean_data = driver.execute_script(
                        r"""return JSON.stringify((function(){
                            function removeNoise(root) {
                                var selectors = [
                                    "script", "style", "iframe", "noscript", "svg", "canvas", "video",
                                    "ins", "amp-ad", "amp-iframe",
                                    "[id*='ad' i]", "[class*='ad' i]", "[id*='ads' i]", "[class*='ads' i]",
                                    "[id*='google' i]", "[class*='google' i]",
                                    "[id*='doubleclick' i]", "[class*='doubleclick' i]",
                                    "[id*='glia' i]", "[class*='glia' i]",
                                    "[id*='banner' i]", "[class*='banner' i]"
                                ];
                                selectors.forEach(function(sel){
                                    Array.from(root.querySelectorAll(sel)).forEach(function(e){ e.remove(); });
                                });
                            }
                            var clone = document.documentElement ? document.documentElement.cloneNode(true) : null;
                            if (clone) removeNoise(clone);
                            var bodyClone = clone ? clone.querySelector("body") : null;
                            var cleanText = bodyClone ? (bodyClone.innerText || bodyClone.textContent || "") : "";
                            var cleanHtml = clone ? (clone.outerHTML || "") : "";
                            var links = Array.from(document.querySelectorAll("a,button,[onclick],[href]")).map(function(e){
                                var outer = e.outerHTML || "";
                                return {
                                    tag: e.tagName,
                                    text: (e.innerText || e.textContent || "").trim(),
                                    href: e.href || e.getAttribute("href") || "",
                                    onclick: e.getAttribute("onclick") || "",
                                    dataset: Object.assign({}, e.dataset || {}),
                                    outerHTML: outer.slice(0, 1200)
                                };
                            }).filter(function(x){
                                var joined = [x.text, x.href, x.onclick, JSON.stringify(x.dataset), x.outerHTML].join(" ");
                                if (/doubleclick|googlesyndication|googleadservices|gliacloud|adservice|Advertisement/i.test(joined)) return false;
                                return /game|Game|試合|速報|CupHome|広|山口|鳥|岡山|下市|医|修/i.test(joined);
                            }).slice(0, 500);
                            return {
                                url: location.href,
                                title: document.title || "",
                                text: cleanText,
                                html: cleanHtml,
                                elements: links
                            };
                        })());"""
                    )
                    dom_data = driver.execute_script(
                        r"""return JSON.stringify({
                            url: location.href,
                            title: document.title || "",
                            text: document.body ? document.body.innerText : "",
                            elements: Array.from(document.querySelectorAll("a,button,[onclick],[href]")).map(function(e){
                                return {
                                    tag: e.tagName,
                                    text: (e.innerText || e.textContent || "").trim(),
                                    href: e.href || e.getAttribute("href") || "",
                                    onclick: e.getAttribute("onclick") || "",
                                    dataset: Object.assign({}, e.dataset || {}),
                                    outerHTML: (e.outerHTML || "").slice(0, 1200)
                                };
                            }).filter(function(x){
                                return /game|Game|試合|速報|CupHome|広|山口|鳥|岡山|下市|医|修/.test(
                                    [x.text, x.href, x.onclick, JSON.stringify(x.dataset), x.outerHTML].join(" ")
                                );
                            }).filter(function(x){
                                return !/doubleclick|googlesyndication|googleadservices|gliacloud|adservice|Advertisement/i.test(
                                    [x.text, x.href, x.onclick, JSON.stringify(x.dataset), x.outerHTML].join(" ")
                                );
                            }).slice(0, 500)
                        });"""
                    )
                    chunks.append(f"\n<!-- URL:{current_url} -->\n<!-- CLEAN_RENDERED -->\n{clean_data}\n<!-- RELATED_ELEMENTS -->\n{dom_data}")
                except Exception:
                    pass
            return "\n".join(chunks)

        try:
            try:
                original_handle = driver.current_window_handle
            except Exception:
                original_handle = None
            before_handles = set(driver.window_handles)
            driver.execute_script("window.open(arguments[0], '_blank');", url)
            wait.until(lambda d: len(set(d.window_handles) - before_handles) >= 1)
            new_handles = list(set(driver.window_handles) - before_handles)
            opened_handles.update(new_handles)
            target_handle = new_handles[-1] if new_handles else driver.window_handles[-1]
            driver.switch_to.window(target_handle)
            wait.until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
            for _ in range(12):
                opened_handles.update(set(driver.window_handles) - before_handles)
                combined = collect_rendered_text()
                if parse_omyu_game_ids(combined):
                    return combined
                time.sleep(0.8)
            combined = collect_rendered_text()
            try:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                debug_file = DEBUG_DIR / f"omyu_rendered_{stamp}.txt"
                debug_file.write_text(combined, encoding="utf-8")
                logging.info("Omyu rendered debug saved: %s", debug_file)
            except Exception:
                logging.error(traceback.format_exc())
            return combined
        finally:
            for handle in list(opened_handles):
                try:
                    if handle in driver.window_handles:
                        driver.switch_to.window(handle)
                        driver.close()
                except Exception:
                    pass
            try:
                handles = driver.window_handles
                if original_handle and original_handle in handles:
                    driver.switch_to.window(original_handle)
                elif handles:
                    driver.switch_to.window(handles[-1])
            except Exception:
                pass

    def generate_review_text(self, game, live_text, division_label="", tournament_name=""):
        api_url = self.dify_api_url_var.get().strip()
        api_key = self.dify_api_key_var.get().strip()
        if not api_url or not api_key:
            return "（Dify API設定後に寸評を自動生成できます。内容を確認して手入力してください。）"
        api_endpoint = api_url.rstrip("/")
        if not api_endpoint.endswith("/workflows/run"):
            api_endpoint = api_endpoint + "/workflows/run"
        prompt = self.dify_prompt_var.get().strip() or (
            "あなたは大学準硬式野球の記事担当です。"
            "一球速報テキストから、勝敗の流れ、投打のポイント、決定的場面を含む寸評を"
            "日本語で150〜230字程度、敬体ではなく新聞調で作成してください。"
            "投手の所属はconfirmed_pitchers_jsonを絶対優先してください。"
            "confirmed_pitchers_jsonのnameは必ずteam所属であり、do_not_assign_to所属として書いてはいけません。"
            "投手の所属はpitching_context_jsonを最優先してください。"
            "pitcher_evidence_by_teamに根拠がある投手名は、所属チームの投手として積極的に寸評へ入れてください。"
            "根拠がない投手名だけ、チーム名と結び付けず投手陣・先発投手・救援陣など安全な表現にしてください。"
        )
        game_date = str(game.get("date", "") or "").replace("/", "")
        pitching_context = game.get("pitching_context") or extract_review_pitching_context(game, live_text)
        compressed_live_text = compress_live_text_for_review(game, live_text, pitching_context)
        game_payload = {
            "game_no": game.get("game_no") or game.get("order") or 1,
            "team1": game.get("team1", ""),
            "team2": game.get("team2", ""),
            "score": game.get("score", ""),
            "game_id": game.get("game_id", ""),
            "date": game.get("date", ""),
            "time": game.get("time", ""),
            "pitching_context": pitching_context,
            "text_live": compressed_live_text,
            "text_live_compressed": True,
            "text_live_original_chars": len(live_text or ""),
            "text_live_compressed_chars": len(compressed_live_text or ""),
        }
        payload = {
            "inputs": {
                "division": division_label,
                "game_date": game_date,
                "tournament": tournament_name,
                "games_json": json.dumps([game_payload], ensure_ascii=False),
                "pitching_context_json": json.dumps(pitching_context, ensure_ascii=False),
                "confirmed_pitchers_json": json.dumps(pitching_context.get("confirmed_pitchers", []), ensure_ascii=False),
                "pitcher_usage_instruction": pitching_context.get("usage_instruction", ""),
                "prompt": prompt,
            },
            "response_mode": "blocking",
            "user": "leaguepost",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        def clean_review_value(value):
            text = str(value or "").strip()
            text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```\s*$", "", text)
            text = re.sub(r"^\s*(?:\*\*)?【寸評】(?:\*\*)?\s*", "", text)
            return text.strip()

        def review_from_value(value):
            if isinstance(value, dict):
                for key in ("review", "寸評", "text", "answer", "result", "resultString", "output"):
                    found = review_from_value(value.get(key))
                    if found:
                        return found
                return ""
            if isinstance(value, list):
                game_no = str(game.get("game_no") or game.get("order") or "").strip()
                title_key = normalize_team_match_key(f"{game.get('team1', '')}{game.get('team2', '')}")
                for item in value:
                    if isinstance(item, dict):
                        item_no = str(item.get("game_no") or item.get("order") or "").strip()
                        item_title = normalize_team_match_key(str(item.get("title") or item.get("game") or ""))
                        if (game_no and item_no == game_no) or (title_key and title_key in item_title):
                            found = review_from_value(item)
                            if found:
                                return found
                for item in value:
                    found = review_from_value(item)
                    if found:
                        return found
                return ""
            if isinstance(value, str):
                text = clean_review_value(value)
                if not text:
                    return ""
                try:
                    parsed = json.loads(text)
                    found = review_from_value(parsed)
                    if found:
                        return found
                except Exception:
                    pass
                return text
            return ""

        def extract_review_from_raw(raw):
            result = json.loads(raw)
            for key_path in (
                ("answer",),
                ("data", "outputs", "reviews_json"),
                ("data", "outputs", "resultString"),
                ("data", "outputs", "result"),
                ("data", "outputs", "output"),
                ("data", "outputs", "text"),
                ("data", "outputs", "answer"),
                ("outputs", "reviews_json"),
                ("outputs", "resultString"),
                ("outputs", "result"),
                ("outputs", "output"),
                ("outputs", "text"),
                ("outputs", "answer"),
            ):
                value = result
                for key in key_path:
                    if isinstance(value, dict):
                        value = value.get(key)
                    else:
                        value = None
                        break
                found = review_from_value(value)
                if found:
                    return found
            if isinstance(result, dict):
                outputs = result.get("data", {}).get("outputs") or result.get("outputs") or {}
                if isinstance(outputs, dict):
                    for value in outputs.values():
                        found = review_from_value(value)
                        if found:
                            return found
            return ""

        def summarize_dify_failure(raw):
            try:
                result = json.loads(raw)
            except Exception:
                return ""
            if not isinstance(result, dict):
                return ""
            data_obj = result.get("data")
            status = ""
            error_text = ""
            if isinstance(data_obj, dict):
                status = str(data_obj.get("status") or "")
                error_text = str(data_obj.get("error") or "")
            status = status or str(result.get("status") or "")
            error_text = error_text or str(result.get("error") or "")
            if not error_text and status.lower() != "failed":
                return ""
            if "RESOURCE_EXHAUSTED" in error_text or "Quota exceeded" in error_text or "429" in error_text:
                return "Dify内のGemini API利用上限に達しました。時間を置くか、Dify側のモデル/APIキー/プランを確認してください。"
            if "PluginInvokeError" in error_text:
                return "Difyワークフロー内のAIノードでエラーが発生しました。Difyの実行履歴で該当ノードを確認してください。"
            if error_text:
                compact = re.sub(r"\s+", " ", error_text).strip()
                return compact[:500]
            if status.lower() == "failed":
                return "Difyワークフローが失敗しました。Difyの実行履歴を確認してください。"
            return ""

        last_error = ""
        last_raw = ""
        for attempt in range(1, 4):
            req = urllib.request.Request(
                api_endpoint,
                data=data,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=150) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                last_raw = raw
                failure = summarize_dify_failure(raw)
                if failure:
                    last_error = failure
                    if "利用上限" in failure:
                        break
                    continue
                found = extract_review_from_raw(raw)
                if found:
                    return found
                last_error = "Dify応答から寸評本文を取得できませんでした"
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    detail = ""
                logging.error(traceback.format_exc())
                last_error = f"HTTP {exc.code}: {exc.reason}"
                if detail:
                    last_error += f" / {detail[:600]}"
                    last_raw = detail
            except Exception as exc:
                logging.error(traceback.format_exc())
                last_error = str(exc)
            if attempt < 3:
                time.sleep(2.0 * attempt)

        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            game_no = game.get("game_no") or game.get("order") or "x"
            debug_file = DEBUG_DIR / f"dify_review_{stamp}_game{game_no}.txt"
            debug_file.write_text(
                "ERROR:\n" + str(last_error) + "\n\nPAYLOAD:\n" +
                json.dumps(payload, ensure_ascii=False, indent=2) +
                "\n\nRAW:\n" + (last_raw or ""),
                encoding="utf-8",
            )
        except Exception:
            logging.error(traceback.format_exc())
        return f"（Dify寸評生成エラー: {last_error or '応答が安定しませんでした'}）"

    def review_manual_game_ids(self):
        values = []
        for var in getattr(self, "review_game_id_vars", []):
            values.append(re.sub(r"\D", "", var.get().strip()))
        while len(values) < 3:
            values.append("")
        return values[:3]

    def review_schedule_context(self):
        self.update_review_date_options()
        key = self.review_division_key()
        label = division_label_from_key(key)
        selected = normalize_review_date_label(self.review_date_var.get())
        if not selected:
            raise ValueError("寸評追加の日付を選択してください。日程画面でExcelを読み込むと候補が表示されます。")
        try:
            game_date = datetime.strptime(selected, "%Y/%m/%d")
        except ValueError:
            raise ValueError("寸評追加の日付形式が不正です。")

        cup_id = self._review_cup_id_for_key(key)
        if not cup_id:
            raise ValueError(f"設定画面で{label}のCupIDを入力してください。")

        excel_file = self.schedule_excel_file_var.get().strip()
        excel_path = app_path(excel_file)
        if not excel_path or not excel_path.exists():
            raise ValueError("日程編集画面で日程表Excelファイルを選択してください。")
        excel_text = load_xlsx_schedule_text(str(excel_path))
        all_games = collect_eleague_schedule_games(excel_text, int(self.year_var.get().strip()), key)
        games = [g for g in all_games if normalize_review_date_label(g.get("date", "")) == selected]
        if not games:
            raise ValueError(f"{label} {selected} の試合カードを日程表Excelから取得できませんでした。")

        return key, label, selected, game_date, cup_id, games, omyu_day_url(cup_id, game_date.strftime("%Y%m%d"))

    def match_review_game_ids_from_day(self, games, day_url):
        self._update_progress_dialog("一球速報ページからGameIDを探しています。\n取得できない場合は画面描画後の内容も確認します。")
        day_html = fetch_url_text(day_url)
        candidate_htmls = [day_html]
        matched_games = match_omyu_game_ids(games, day_html)
        found = sum(1 for game in matched_games if game.get("game_id"))
        if found < len(games):
            try:
                rendered_html = self.fetch_omyu_rendered_html(day_url, games)
                candidate_htmls.append(rendered_html)
                rendered_matches = match_omyu_game_ids(games, rendered_html)
                rendered_found = sum(1 for game in rendered_matches if game.get("game_id"))
                if rendered_found > found:
                    matched_games = rendered_matches
            except Exception:
                logging.error(traceback.format_exc())
        return matched_games, candidate_htmls

    def verify_review_game_id(self, game, game_id, candidate_htmls, day_url, all_games, manual=False):
        if not game_id:
            return "", ""
        live_html = fetch_url_text(omyu_text_live_url(game_id))
        live_text = strip_html_text(live_html)
        if live_text_matches_game(game, live_text):
            return game_id, live_text
        if manual:
            return "", (
                "手入力GameIDの一球速報本文が日程Excelの対戦カードと一致しませんでした。"
                f"予定: {game.get('team1', '')}-{game.get('team2', '')} / GameID: {game_id}"
            )
        verified_id, verified_text = find_verified_omyu_live_text(game, candidate_htmls)
        if not verified_id and len(candidate_htmls) == 1:
            try:
                rendered_html = self.fetch_omyu_rendered_html(day_url, all_games)
                candidate_htmls.append(rendered_html)
                verified_id, verified_text = find_verified_omyu_live_text(game, candidate_htmls)
            except Exception:
                logging.error(traceback.format_exc())
        if verified_id:
            return verified_id, verified_text
        return "", (
            "GameID候補の一球速報本文が日程Excelの対戦カードと一致しませんでした。"
            f"予定: {game.get('team1', '')}-{game.get('team2', '')}"
        )

    def fetch_review_game_ids(self):
        self._show_progress_dialog(
            "GameID取得中",
            "日程Excel、CupID、一球速報ページを照合しています。\n失敗した試合はGameID欄へ手入力してください。",
        )
        try:
            key, label, selected, game_date, cup_id, games, day_url = self.review_schedule_context()
            matched_games, candidate_htmls = self.match_review_game_ids_from_day(games, day_url)
            lines = []
            found = 0
            for idx, game in enumerate(matched_games[:3], start=1):
                gid = game.get("game_id", "")
                if gid:
                    self._update_progress_dialog(f"第{idx}試合のGameIDを確認しています。\nGameID: {gid}")
                    try:
                        gid, _ = self.verify_review_game_id(game, gid, candidate_htmls, day_url, games)
                    except Exception as exc:
                        logging.error(traceback.format_exc())
                        lines.append(f"第{idx}試合: 確認エラー {exc}")
                        continue
                if gid:
                    self.review_game_id_vars[idx - 1].set(gid)
                    found += 1
                    lines.append(f"第{idx}試合: {gid} ({game.get('team1', '')}-{game.get('team2', '')})")
                else:
                    lines.append(f"第{idx}試合: 取得できませんでした ({game.get('team1', '')}-{game.get('team2', '')})")
            self.persist_settings()
            self._close_progress_dialog()
            message = f"{label} {selected} のGameID取得結果: {found} / {min(3, len(matched_games))} 件\n\n" + "\n".join(lines)
            if found == min(3, len(matched_games)):
                messagebox.showinfo(APP_NAME, message)
            else:
                messagebox.showwarning(APP_NAME, message + "\n\n未取得分はGameID欄へ手入力してください。")
        except Exception as e:
            self._close_progress_dialog()
            messagebox.showerror(APP_NAME, str(e))

    def build_review_chatgpt_prompt(self):
        key, label, selected, game_date, cup_id, games, day_url = self.review_schedule_context()
        manual_ids = self.review_manual_game_ids()
        lines = [
            "あなたは大学準硬式野球の記事担当です。",
            "以下の一球速報テキストURLを確認し、各試合の寸評を日本語の新聞調で作成してください。",
            "各寸評は150〜230字程度を目安に、勝敗の流れ、得点場面、投手起用、決定的場面を入れてください。",
            "出力は試合順に、各試合ごとに「【寸評】」から始めてください。",
            "投手の所属チームを推測で逆にしないでください。分からない場合は投手名を無理に使わず、投手陣など安全な表現にしてください。",
            "",
            f"大会: {league_name_with_division(make_base_league_name(self.year_var.get().strip(), self.season_var.get()), key)}",
            f"区分: {label}",
            f"日付: {selected}",
            f"大会ページ: {day_url}",
            "",
            "試合一覧:",
        ]
        for idx, game in enumerate(games[:3], start=1):
            game_id = manual_ids[idx - 1] if idx - 1 < len(manual_ids) else ""
            url = omyu_text_live_url(game_id) if game_id else "GameID未取得"
            lines.append(f"第{idx}試合: {game.get('team1', '')}-{game.get('team2', '')} / 開始 {game.get('time', '')} / 一球速報: {url}")
        return "\n".join(lines)

    def copy_review_chatgpt_prompt(self):
        try:
            prompt = self.build_review_chatgpt_prompt()
            self.root.clipboard_clear()
            self.root.clipboard_append(prompt)
            self.persist_settings()
            messagebox.showinfo(APP_NAME, "ChatGPT用プロンプトをコピーしました。\nChatGPTに貼り付け、回答を「ChatGPT回答貼付」欄へ戻してください。")
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def get_review_item(self):
        key, label, selected, game_date, cup_id, games, day_url = self.review_schedule_context()
        manual_ids = self.review_manual_game_ids()
        manual_reviews = split_manual_review_answers(self._get_text("review_chatgpt_text") if "review_chatgpt_text" in self.vars else "")
        if len(manual_reviews) >= min(3, len(games)):
            matched_games = [dict(game) for game in games]
            candidate_htmls = []
        else:
            matched_games, candidate_htmls = self.match_review_game_ids_from_day(games, day_url)

        base = make_base_league_name(self.year_var.get().strip(), self.season_var.get())
        league = league_name_with_division(base, key)
        template_path = self._team_list_template_path()
        team_lookup = build_team_code_lookup(xlsx_read_first_sheet_rows(str(template_path)))
        missing_codes = []
        for game_no, game in enumerate(matched_games, start=1):
            game["game_no"] = game_no
            game["team_code"] = team_code_for_game(game, team_lookup)
            if not game["team_code"]:
                missing_codes.append(f"{game.get('team1', '')}-{game.get('team2', '')}")
            manual_game_id = manual_ids[game_no - 1] if game_no - 1 < len(manual_ids) else ""
            if manual_game_id:
                game["game_id"] = manual_game_id
            if game.get("game_id"):
                try:
                    verified_id, live_text = self.verify_review_game_id(
                        game,
                        game["game_id"],
                        candidate_htmls,
                        day_url,
                        games,
                        manual=bool(manual_game_id),
                    )
                    game["game_id"] = verified_id
                except Exception as exc:
                    logging.error(traceback.format_exc())
                    live_text = f"一球速報テキスト取得エラー: {exc}"
            else:
                live_text = "GameIDを取得できませんでした。"
            game["live_text"] = live_text
            game["pitching_context"] = extract_review_pitching_context(game, live_text)
            if game_no - 1 < len(manual_reviews) and manual_reviews[game_no - 1].strip():
                game["review"] = manual_reviews[game_no - 1].strip()
            elif not game.get("game_id"):
                game["review"] = (
                    "（一球速報のGameIDを取得できませんでした。CupID、日付、チーム名の対応を確認してください。"
                    f"使用CupID: {cup_id} / URL: {day_url}。"
                    f"調査用ファイルは {DEBUG_DIR} に保存されます。）"
                )
            elif not live_text or len(live_text.strip()) < 120:
                game["review"] = "（一球速報本文を十分に取得できませんでした。リンク先の一球速報テキストを確認してください。）"
            else:
                self._update_progress_dialog(
                    f"第{game_no}試合の寸評をDifyで生成しています。\n"
                    "応答が不安定な場合は自動で再試行します。"
                )
                if game_no > 1:
                    time.sleep(1.0)
                game["review"] = self.generate_review_text(game, live_text, label, league)

        if missing_codes:
            raise ValueError("league_team_list.xlsxでチームコードを照合できません: " + "、".join(missing_codes))

        tournament_id = self._review_tournament_id_for_key(key)
        dates = self.review_dates_for_key(key)
        date_labels = [d.strftime("%Y/%m/%d") for d in dates]
        idx = date_labels.index(selected) if selected in date_labels else 0
        item = PostItem(idx + 1, max(1, len(dates)), game_date, league, cup_id, tournament_id)
        title = self.review_title_var.get().strip() or item.title
        body = build_review_body_html(item, matched_games)
        return ResultPostItem(1, 1, title, body, guess_categories(league), datetime.now(), POST_TYPE_REVIEW)

    def get_result_items(self):
        league_base = strip_result_title_suffix(self.league_var.get().strip())
        if not league_base:
            raise ValueError("大会タイトルを入力してください。")
        year = self.year_var.get().strip()
        season = self.season_var.get()
        default_year = int(year)
        cup_ids = {
            "1": extract_cup_id(self.eleague_cup_id_1_var.get()),
            "2": extract_cup_id(self.eleague_cup_id_2_var.get()),
            "3": extract_cup_id(self.eleague_cup_id_3_var.get()),
        }
        items = []
        missing_cups = []
        for key in ("1", "2", "3"):
            date_text = self.config_data.get(f"schedule_dates_{key}", "").strip()
            if not date_text and key == "1":
                raw_dates = self._get_text("dates_text")
                if raw_dates and "[" not in raw_dates:
                    date_text = raw_dates
            if not date_text:
                continue
            dates = parse_dates_with_default_year(date_text, default_year)
            if not dates:
                continue
            if not cup_ids[key]:
                missing_cups.append(division_label_from_key(key))
                continue
            division = division_label_from_key(key)
            league = league_name_with_division(league_base, key)
            tournament_id = self._eleague_tournament_id_for_key(key, make_tournament_id(year, season, division))
            items.extend(PostItem(i + 1, len(dates), d, league, cup_ids[key], tournament_id) for i, d in enumerate(dates))
        if missing_cups:
            raise ValueError("設定画面でCupIDを入力してください: " + "、".join(missing_cups))
        if not items:
            raise ValueError("日程を入力してください。日程編集画面でExcelを読み込むと1部・2部・入替戦の日程を自動取得します。")
        return items

    def generate_post(self, post_type):
        try:
            now_pub = datetime.now()
            if post_type == POST_TYPE_RESULT:
                self.prepare_tournament_for_generation()
                self.items = self.get_result_items()
            elif post_type == POST_TYPE_REVIEW:
                self.persist_settings()
                self._show_progress_dialog(
                    "寸評作成中",
                    "GameID取得、一球速報本文取得、Dify寸評生成を実行しています。\n"
                    "完了までこのままお待ちください。",
                )
                try:
                    self.root.lift()
                    self.root.focus_force()
                except Exception:
                    pass
                try:
                    self.items = [self.get_review_item()]
                finally:
                    self._close_progress_dialog()
            elif post_type == POST_TYPE_SCHEDULE:
                excel_file = self.schedule_excel_file_var.get().strip()
                if not excel_file:
                    raise ValueError("日程表Excelファイルを選択してください。")
                excel_path = app_path(excel_file)
                if not excel_path or not excel_path.exists():
                    raise ValueError("日程表Excelファイルが見つかりません。")
                excel_text = load_xlsx_schedule_text(str(excel_path))
                self.remember_schedule_dates_from_excel(excel_text)
                self.apply_remembered_schedule_dates(force=True)
                self.update_review_date_options()
                self.update_review_title()
                download_url = self.default_download_url(str(excel_path), now_pub)
                self.schedule_download_url_var.set(download_url)
                body = build_schedule_page_body_html(self.year_var.get().strip(), self.season_var.get(), excel_text, download_url)
                title = self.schedule_title_var.get().strip() or make_schedule_title(self.year_var.get().strip(), self.season_var.get())
                self.items = [ResultPostItem(1, 1, title, body, guess_categories(title), now_pub, post_type)]
            elif post_type == POST_TYPE_STANDINGS:
                line_text = self._get_text("standings_text")
                if not line_text:
                    raise ValueError("記録員LINE本文を入力してください。")
                if not self._get_text("awards_text"):
                    self._set_text("awards_text", line_text)
                division = self.standings_division_var.get()
                self.division_var.set(division)
                self.prepare_tournament_for_generation()
                league = self.league_var.get().strip()
                body = build_standings_body_html(league, self.tournament_id_var.get().strip(), line_text)
                title = league if ("順位" in league or "星取" in league) else f"{league}　順位＆星取表"
                self.items = [ResultPostItem(1, 1, title, body, guess_categories(league), now_pub, post_type)]
            elif post_type == POST_TYPE_AWARDS:
                self.division_var.set(self.awards_division_var.get())
                self.prepare_tournament_for_generation()
                self.sync_awards_text_from_standings()
                line_text = self._get_text("awards_text")
                if not line_text:
                    raise ValueError("記録員LINE本文を入力してください。")
                league = self.league_var.get().strip()
                body = build_awards_body_html(league, self.tournament_id_var.get().strip(), line_text)
                title = league if "個人賞" in league else f"{league}　個人賞"
                self.items = [ResultPostItem(1, 1, title, body, guess_categories(league), now_pub, post_type)]
            else:
                raise ValueError(f"未対応の投稿種別です: {post_type}")
            self.posted_flags = [False] * len(self.items)
            self.current_index = 0
            self.persist_settings()
            self.show_preview_window()
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def current_item(self):
        return self.items[self.current_index] if self.items else None

    def show_preview_window(self):
        it = self.current_item()
        if not it:
            return
        win = self.ctk.CTkToplevel(self.root)
        win.title("プレビュー")
        win.geometry("1080x720")
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(2, weight=1)
        toolbar = self.ctk.CTkFrame(win)
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        self._button(toolbar, text="WPへ自動入力", width=170, command=self.auto_input_wordpress).pack(side="left", padx=4)
        self._button(toolbar, text="ブラウザでプレビュー", command=self.open_preview_in_browser).pack(side="left", padx=4)
        self._button(toolbar, text="前", command=lambda: self.preview_move(win, -1)).pack(side="left", padx=4)
        self._button(toolbar, text="次", command=lambda: self.preview_move(win, 1)).pack(side="left", padx=4)
        self._button(toolbar, text="投稿済みにして次", command=lambda: self.preview_mark_posted(win)).pack(side="left", padx=4)
        self.preview_title = self._entry(win, font=self.font(2, "bold"))
        self.preview_title.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        editable_post_types = {POST_TYPE_RESULT, POST_TYPE_REVIEW}
        use_html_preview = getattr(it, "meta_label", "") not in editable_post_types
        HtmlFrame = safe_import_tkinterweb() if use_html_preview else None
        self.preview_is_web = False
        self.preview_body = None
        if HtmlFrame is not None:
            try:
                self.preview_body = HtmlFrame(win, messages_enabled=False)
                self.preview_is_web = True
            except Exception:
                logging.error(traceback.format_exc())
                self.preview_body = None
        if self.preview_body is None:
            self.preview_body = self.ctk.CTkTextbox(win, font=("Consolas", max(12, self.ui_font_size - 2)))
        self.preview_body.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.preview_counter = self.ctk.CTkLabel(win, text="", font=self.font())
        self.preview_counter.grid(row=3, column=0, sticky="w", padx=12, pady=(0, 10))
        self.refresh_preview()
        try:
            win.transient(self.root)
            win.lift()
            win.focus_force()
            win.after(100, lambda: (win.lift(), win.focus_force()))
        except Exception:
            pass

    def refresh_preview(self):
        it = self.current_item()
        if not it:
            return
        self.preview_title.delete(0, "end")
        self.preview_title.insert(0, it.title)
        if getattr(self, "preview_is_web", False):
            self.preview_body.load_html(build_single_preview_html(it))
        else:
            self.preview_body.delete("1.0", "end")
            self.preview_body.insert("1.0", post_body_html(it))
        done = sum(1 for x in self.posted_flags if x)
        self.preview_counter.configure(text=f"{self.current_index + 1} / {len(self.items)}　投稿済み {done}件")

    def apply_preview_edits(self):
        it = self.current_item()
        if not it:
            return
        title = ""
        try:
            title = self.preview_title.get().strip()
        except Exception:
            title = ""
        if title and hasattr(it, "title_text"):
            it.title_text = title
        if not getattr(self, "preview_is_web", False) and hasattr(it, "body_html"):
            try:
                body = self.preview_body.get("1.0", "end").strip()
                if body:
                    it.body_html = body
            except Exception:
                pass

    def preview_move(self, win, delta):
        if not self.items:
            return
        self.apply_preview_edits()
        self.current_index = min(max(0, self.current_index + delta), len(self.items) - 1)
        self.refresh_preview()

    def preview_mark_posted(self, win):
        if not self.items:
            return
        self.apply_preview_edits()
        self.posted_flags[self.current_index] = True
        if self.current_index < len(self.items) - 1:
            self.current_index += 1
        self.refresh_preview()

    def set_clipboard_text(self, value):
        self.root.clipboard_clear()
        self.root.clipboard_append(value or "")
        self.root.update_idletasks()

    def copy_to_clipboard(self, value, label):
        self.set_clipboard_text(value)
        messagebox.showinfo(APP_NAME, f"{label}をコピーしました。")

    def copy_extension_payload(self):
        it = self.current_item()
        if it:
            self.apply_preview_edits()
            self.copy_to_clipboard(build_extension_payload(it), "拡張機能用データ")

    def copy_wp_custom_html_block(self):
        it = self.current_item()
        if it:
            self.apply_preview_edits()
            self.copy_to_clipboard(build_wp_custom_html_block(post_body_html(it)), "本文HTMLブロック")

    def open_preview_in_browser(self):
        try:
            it = self.current_item()
            if not it:
                raise ValueError("原稿が未生成です。")
            self.apply_preview_edits()
            preview_dir = APP_DATA_DIR / "previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_file = preview_dir / "leaguepost_preview.html"
            preview_file.write_text(build_single_preview_html(it), encoding="utf-8")
            webbrowser.open(preview_file.resolve().as_uri())
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def wordpress_post_list_url(self):
        configured = self.wp_new_post_url_var.get().strip()
        if configured.startswith("http://") or configured.startswith("https://"):
            parsed = urllib.parse.urlparse(configured)
            return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/wp-admin/edit.php", "", "", ""))
        return DEFAULT_WP_POST_LIST_URL

    def auto_update_review_wordpress(self, item):
        url = self.wordpress_post_list_url()
        driver, WebDriverWait = self._get_wp_driver()
        driver.get(url)
        wait = WebDriverWait(driver, 60)
        wait.until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
        title = item.title
        find_script = r'''
const title = arguments[0];
function stripTags(value) {
  const div = document.createElement('div');
  div.innerHTML = String(value || '');
  return (div.textContent || div.innerText || '').trim();
}
function norm(value) {
  return String(value || '')
    .replace(/[\s\u3000]/g, '')
    .replace(/[０-９]/g, ch => String.fromCharCode(ch.charCodeAt(0) - 0xFEE0))
    .replace(/[一]/g, '1')
    .replace(/[二]/g, '2')
    .replace(/[-‐－–—]/g, '')
    .toLowerCase();
}
function titleFromRow(row) {
  const titleEl = row.querySelector('.row-title, .title a, strong a, a[href*="post.php?post="][href*="action=edit"]');
  return titleEl ? stripTags(titleEl.innerHTML || titleEl.textContent || '') : '';
}
function editHrefFromRow(row) {
  const links = [...row.querySelectorAll('a[href*="post.php?post="][href*="action=edit"]')];
  const rowTitle = row.querySelector('.row-title, .title a, strong a');
  return (rowTitle && rowTitle.href) || (links[0] && links[0].href) || '';
}
function findTitleOnAdminList(wantedTitle) {
  const wanted = norm(wantedTitle);
  const rows = [...document.querySelectorAll('#the-list tr, table.wp-list-table tbody tr')];
  const scored = rows.map(row => {
    const rowTitle = titleFromRow(row);
    const rowNorm = norm(rowTitle);
    let score = 0;
    if (rowNorm === wanted) score = 100;
    else if (rowNorm.includes(wanted) || wanted.includes(rowNorm)) score = 80;
    else {
      const daylessWanted = wanted.replace(/初日|最終日|\d+日目/g, '');
      const daylessRow = rowNorm.replace(/初日|最終日|\d+日目/g, '');
      if (daylessWanted && daylessRow && daylessWanted === daylessRow) score = 60;
    }
    return {href: editHrefFromRow(row), title: rowTitle, score};
  }).filter(x => x.score > 0).sort((a, b) => b.score - a.score);
  return scored[0] || null;
}
return findTitleOnAdminList(title);'''
        parsed = urllib.parse.urlparse(url)
        base_edit_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/wp-admin/edit.php", "", "", ""))
        candidate_urls = [
            base_edit_url + "?" + urllib.parse.urlencode({"s": title, "post_status": "all"}),
        ]
        for page in range(1, 21):
            candidate_urls.append(base_edit_url + "?" + urllib.parse.urlencode({"paged": page, "post_status": "all"}))

        result = None
        visited = 0
        samples = []
        for candidate_url in candidate_urls:
            driver.get(candidate_url)
            wait.until(lambda d: d.execute_script("return document.readyState") in ("interactive", "complete"))
            time.sleep(0.4)
            visited += 1
            result = driver.execute_script(find_script, title)
            if result and result.get("href"):
                break
            try:
                page_samples = driver.execute_script(
                    "return [...document.querySelectorAll('.row-title, .title a, strong a')].slice(0,8).map(a => (a.innerText || a.textContent || '').trim()).filter(Boolean);"
                )
                for sample in page_samples or []:
                    if sample and sample not in samples:
                        samples.append(sample)
            except Exception:
                pass
        if not result or not result.get("href"):
            raise RuntimeError({
                "message": f"同タイトルの記事が見つかりません: {title}",
                "visited_pages": visited,
                "samples": samples[:8],
            })
        driver.get(result["href"])
        try:
            wait.until(lambda d: d.execute_script(
                "return !!(window.wp && wp.data && wp.data.dispatch && wp.data.select);"
            ))
        except Exception:
            raise RuntimeError(
                "WordPress投稿編集画面を確認できませんでした。\n\n"
                "ログイン画面が表示されている場合は、開いたブラウザで手動ログインしてから、\n"
                "もう一度『WPへ自動入力』を押してください。"
            )
        content = build_wp_block_for_selenium(post_body_html(item))
        update_script = r'''const done = arguments[arguments.length - 1];
const title = arguments[0];
const content = arguments[1];
const result = {ok:false, message:""};
(async () => {
  try {
    if (!(window.wp && wp.data && wp.data.dispatch)) {
      result.message = "wp.data が見つかりません";
      done(result);
      return;
    }
    const editorDispatch = wp.data.dispatch('core/editor');
    if (!editorDispatch || !editorDispatch.editPost) {
      result.message = "core/editor.editPost が見つかりません";
      done(result);
      return;
    }
    editorDispatch.editPost({ title: title });
    let blockOk = false;
    try {
      if (wp.blocks && wp.blocks.parse && wp.data.dispatch('core/block-editor')) {
        const blocks = wp.blocks.parse(content);
        wp.data.dispatch('core/block-editor').resetBlocks(blocks);
        blockOk = true;
      }
    } catch (e) {
      blockOk = false;
    }
    if (!blockOk) editorDispatch.editPost({ content: content });
    result.ok = true;
    result.message = blockOk ? "block-editor-reset" : "editPost-content";
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();'''
        update_result = driver.execute_async_script(update_script, title, content)
        if not update_result or not update_result.get("ok"):
            raise RuntimeError("WordPress記事更新入力に失敗しました。\n" + str(update_result))
        messagebox.showinfo(
            APP_NAME,
            "既存の試合速報記事を開き、本文を寸評入り原稿に置き換えました。\n\n"
            f"対象記事: {result.get('title') or title}\n"
            "内容を確認し、最後の更新ボタンは手動で押してください。",
        )
        focus_chrome_window(driver)

    def auto_input_wordpress(self):
        try:
            it = self.current_item()
            if it is None:
                raise ValueError("原稿が未生成です。")
            self.apply_preview_edits()
            if getattr(it, "meta_label", "") == POST_TYPE_REVIEW:
                self.auto_update_review_wordpress(it)
                return

            url = self.wp_new_post_url_var.get().strip()
            if not url:
                raise ValueError("WordPress新規投稿URLを入力してください。")
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValueError("URLは http:// または https:// から入力してください。")

            driver, WebDriverWait = self._get_wp_driver()
            try:
                before_handles = set(driver.window_handles)
                driver.execute_script("window.open(arguments[0], '_blank');", url)
                WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - before_handles) >= 1)
                new_handles = list(set(driver.window_handles) - before_handles)
                driver.switch_to.window(new_handles[-1] if new_handles else driver.window_handles[-1])
            except Exception:
                self.wp_driver = None
                driver, WebDriverWait = self._get_wp_driver()
                driver.get(url)

            wait = WebDriverWait(driver, 60)
            try:
                wait.until(lambda d: d.execute_script(
                    "return !!(window.wp && wp.data && wp.data.dispatch && wp.data.select);"
                ))
            except Exception:
                raise RuntimeError(
                    "WordPress投稿編集画面を確認できませんでした。\n\n"
                    "ログイン画面が表示されている場合は、開いたブラウザで手動ログインしてから、\n"
                    "もう一度『WPへ自動入力』を押してください。"
                )

            title = it.title
            content = build_wp_block_for_selenium(post_body_html(it))
            post_type = getattr(it, "meta_label", "") or ""
            category_targets = wordpress_category_targets(it, post_type)
            publish_payload = wordpress_publish_payload(it, post_type)

            script = r'''const done = arguments[arguments.length - 1];
const title = arguments[0];
const content = arguments[1];
const categoryTargets = arguments[2] || [];
const publishPayload = arguments[3] || null;
const result = {ok:false, message:"", categories:[], missingCategories:[]};

function normalizeName(value) {
  return String(value || "")
    .replace(/[\s\u3000]/g, "")
    .replace(/[／]/g, "/")
    .replace(/[１]/g, "1")
    .replace(/[２]/g, "2")
    .replace(/[一]/g, "1")
    .replace(/[二]/g, "2")
    .replace(/入れ替え/g, "入替")
    .replace(/[-‐－–—]/g, "")
    .toLowerCase();
}

async function fetchAllCategories() {
  const all = [];
  if (window.wp && wp.apiFetch) {
    for (let page = 1; page <= 10; page++) {
      const rows = await wp.apiFetch({path: `/wp/v2/categories?per_page=100&page=${page}&hide_empty=false&_fields=id,name,parent`});
      if (!rows || !rows.length) break;
      all.push(...rows);
      if (rows.length < 100) break;
    }
    return all;
  }

  const core = wp.data.select('core');
  let records = core.getEntityRecords('taxonomy', 'category', {per_page: 100, hide_empty: false});
  const start = Date.now();
  while (!records && Date.now() - start < 5000) {
    await new Promise(resolve => setTimeout(resolve, 150));
    records = core.getEntityRecords('taxonomy', 'category', {per_page: 100, hide_empty: false});
  }
  return records || [];
}

async function resolveCategoryIds(targets) {
  const ids = [];
  const missing = [];
  try {
    const records = await fetchAllCategories();
    const byId = new Map(records.map(cat => [cat.id, cat]));

    function categoryPath(cat) {
      const names = [];
      let current = cat;
      const seen = new Set();
      while (current && !seen.has(current.id)) {
        seen.add(current.id);
        names.unshift(current.name);
        current = current.parent ? byId.get(current.parent) : null;
      }
      return names.join("");
    }

    const normalizedRecords = records.map(cat => ({
      id: cat.id,
      name: cat.name,
      path: categoryPath(cat),
      normName: normalizeName(cat.name),
      normPath: normalizeName(categoryPath(cat))
    }));

    for (const target of targets) {
      const norm = normalizeName(target);
      const hit = normalizedRecords.find(cat => cat.normPath === norm) || normalizedRecords.find(cat => cat.normName === norm);
      if (hit) {
        if (!ids.includes(hit.id)) ids.push(hit.id);
        if (!result.categories.includes(hit.path || hit.name)) result.categories.push(hit.path || hit.name);
      } else {
        missing.push(target);
      }
    }
  } catch (e) {
    result.message += " categoryLookup:" + String(e && e.message ? e.message : e);
  }
  result.missingCategories = missing;
  return ids;
}

(async () => {
  try {
    if (!(window.wp && wp.data && wp.data.dispatch)) {
      result.message = "wp.data が見つかりません";
      done(result);
      return;
    }
    const editorDispatch = wp.data.dispatch('core/editor');
    if (!editorDispatch || !editorDispatch.editPost) {
      result.message = "core/editor.editPost が見つかりません";
      done(result);
      return;
    }

    editorDispatch.editPost({ title: title });

    let blockOk = false;
    try {
      if (wp.blocks && wp.blocks.parse && wp.data.dispatch('core/block-editor')) {
        const blocks = wp.blocks.parse(content);
        wp.data.dispatch('core/block-editor').resetBlocks(blocks);
        blockOk = true;
      }
    } catch (e) {
      blockOk = false;
    }
    if (!blockOk) {
      editorDispatch.editPost({ content: content });
    }

    const catIds = await resolveCategoryIds(categoryTargets);
    if (catIds.length) {
      editorDispatch.editPost({ categories: catIds });
    }

    if (publishPayload && publishPayload.iso) {
      editorDispatch.editPost({ date: publishPayload.iso, status: 'future' });
    }

    try {
      const selectors = [
        'textarea.editor-post-title__input',
        'input.editor-post-title__input',
        'h1[contenteditable="true"]',
        '[aria-label="タイトルを追加"]',
        '[aria-label="Add title"]'
      ];
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) {
          if ('value' in el) {
            el.value = title;
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
          } else {
            el.textContent = title;
            el.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText', data:title}));
          }
          break;
        }
      }
    } catch (e) {}

    result.ok = true;
    result.message = blockOk ? "block-editor" : "editPost-content";
    done(result);
  } catch (e) {
    result.message = String(e && e.message ? e.message : e);
    done(result);
  }
})();'''
            result = driver.execute_async_script(script, title, content, category_targets, publish_payload)
            if not result or not result.get("ok"):
                raise RuntimeError("WordPressへの自動入力に失敗しました。\n" + str(result))

            lines = [
                "WordPressへ自動入力しました。",
                "",
                "タイトル・本文HTML・カテゴリーを確認してください。",
            ]
            if publish_payload:
                lines.append(f"予約日時: {publish_payload['year']}/{publish_payload['month']}/{publish_payload['day']} {publish_payload['hour']}:{publish_payload['minute']}")
            else:
                lines.append("下書き作成向けです。予約日時は設定していません。")
            if result.get("categories"):
                lines.append("カテゴリー: " + "、".join(result.get("categories")))
            if result.get("missingCategories"):
                lines.append("未検出カテゴリー: " + "、".join(result.get("missingCategories")))
            lines.append("")
            lines.append("最後の保存・予約・投稿ボタンは手動で押してください。")
            messagebox.showinfo(APP_NAME, "\n".join(lines))
            focus_chrome_window(driver)
        except Exception as e:
            logging.error(traceback.format_exc())
            messagebox.showerror(APP_NAME, str(e))

    def open_wordpress_new_post(self):
        url = self.wp_new_post_url_var.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "WordPress新規投稿URLを入力してください。")
            return
        webbrowser.open(url)


def run_customtkinter_or_legacy():
    try:
        import customtkinter as ctk  # type: ignore
        CustomTkApp(ctk).mainloop()
    except ImportError:
        messagebox.showwarning(
            APP_NAME,
            "CustomTkinterがインストールされていないため、従来UIで起動します。\n\n"
            "v4.1のサイドバーUIを使うには customtkinter をインストールしてください。",
        )
        App().mainloop()


if __name__ == "__main__":
    logging.info("LeaguePost started")
    run_customtkinter_or_legacy()





















