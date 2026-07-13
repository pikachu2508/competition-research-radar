from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import os
import shutil
import sqlite3
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
OUTPUT = ROOT / "output"
LOGS = ROOT / "logs"
DB_PATH = DATA / "radar.sqlite3"
CN_TZ = ZoneInfo("Asia/Shanghai")


def now_cn() -> datetime:
    return datetime.now(CN_TZ)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CompetitionResearchRadar/1.0",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
    "Referer": "https://navi.cnki.net/",
}


def load_json(name: str):
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    decoded = html.unescape(value)
    if "<" not in decoded and ">" not in decoded:
        return re.sub(r"\s+", " ", decoded).strip()
    soup = BeautifulSoup(decoded, "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(node: ET.Element, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for child in list(node):
        if local_name(child.tag) in wanted:
            if local_name(child.tag) == "link" and child.attrib.get("href"):
                return child.attrib["href"]
            return "".join(child.itertext()).strip()
    return ""


def parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value[:30]
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M")


def canonical_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))
    except ValueError:
        return value.strip()


def fetch_feed(feed: dict, timeout: int) -> list[dict]:
    response = requests.get(feed["url"], headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    content = response.content.lstrip()
    if b"<rss" not in content[:600].lower() and b"<feed" not in content[:600].lower() and b"<rdf" not in content[:600].lower():
        raise ValueError("返回内容不是 RSS/Atom")
    root = ET.fromstring(response.content)
    nodes = [n for n in root.iter() if local_name(n.tag) in {"item", "entry"}]
    items = []
    for node in nodes:
        title = clean_text(child_text(node, "title"))
        link = canonical_url(child_text(node, "link"))
        summary = clean_text(child_text(node, "description", "summary", "content"))
        author = clean_text(child_text(node, "author", "creator"))
        published_raw = child_text(node, "pubdate", "published", "updated", "date")
        stable_id = child_text(node, "guid", "id") or link or f"{title}|{published_raw}"
        if not title:
            continue
        items.append({
            "feed_id": feed["id"], "source": feed["name"], "source_group": feed["group"],
            "kind": feed["kind"], "title": title, "link": link, "summary": summary,
            "author": author, "published": parse_date(published_raw),
            "stable_id": stable_id, "source_weight": int(feed.get("weight", 0)),
        })
    return items


def classify(item: dict, keyword_config: dict) -> dict:
    text = f'{item["title"]} {item["summary"]}'.lower()
    score = item["source_weight"]
    matches = []
    categories = []
    uses = []
    for category in keyword_config["categories"]:
        cat_score = 0
        for phrase in category["strong"]:
            if phrase.lower() in text:
                cat_score += 6
                matches.append(phrase)
        for phrase in category["medium"]:
            if phrase.lower() in text:
                cat_score += 3
                matches.append(phrase)
        if cat_score:
            score += min(cat_score, 12)
            categories.append(category["name"])
            uses.append(category["use"])
    for phrase in keyword_config.get("exclude", []):
        if phrase.lower() in text:
            score -= 8
    groups = keyword_config.get("logic_groups", {})
    hit = {name: [p for p in phrases if p.lower() in text] for name, phrases in groups.items()}
    direct = bool(hit.get("direct"))
    paired = bool(hit.get("measurement")) and bool(hit.get("temperature") or hit.get("quality"))
    teaching_technical = bool(hit.get("teaching")) and bool(hit.get("measurement") or hit.get("temperature") or hit.get("quality"))
    if direct:
        score = max(score, 12)
    elif paired:
        score = max(score, 10)
    elif teaching_technical:
        score = max(score, 7)
    else:
        score = min(score, 7)
    for values in hit.values():
        matches.extend(values)
    thresholds = keyword_config["levels"]
    level = "strong" if score >= thresholds["strong"] else "relevant" if score >= thresholds["relevant"] else "general"
    relation = "；".join(dict.fromkeys(uses)) if uses else "暂未发现与当前课题的直接联系"
    return {**item, "score": score, "level": level, "categories": "、".join(categories) or "待观察", "matches": "、".join(dict.fromkeys(matches)), "relation": relation}


def connect_db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS entries (
      fingerprint TEXT PRIMARY KEY, feed_id TEXT, source TEXT, source_group TEXT, kind TEXT,
      title TEXT, link TEXT, summary TEXT, author TEXT, published TEXT, first_seen TEXT,
      score INTEGER, level TEXT, categories TEXT, matches TEXT, relation TEXT,
      notified INTEGER DEFAULT 0, baseline INTEGER DEFAULT 0, digest_sent INTEGER DEFAULT 0,
      author_affiliations TEXT DEFAULT '', cnki_online_date TEXT DEFAULT '', doi TEXT DEFAULT '',
      detail_keywords TEXT DEFAULT '', funding TEXT DEFAULT '', metadata_source TEXT DEFAULT '',
      metadata_fetched_at TEXT DEFAULT '', metadata_status TEXT DEFAULT 'pending'
    );
    CREATE TABLE IF NOT EXISTS runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ran_at TEXT, fetched INTEGER, added INTEGER,
      strong INTEGER, failures TEXT
    );
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(entries)").fetchall()}
    migrations = {
        "digest_sent": "INTEGER DEFAULT 0", "author_affiliations": "TEXT DEFAULT ''",
        "cnki_online_date": "TEXT DEFAULT ''", "doi": "TEXT DEFAULT ''",
        "detail_keywords": "TEXT DEFAULT ''", "funding": "TEXT DEFAULT ''",
        "metadata_source": "TEXT DEFAULT ''", "metadata_fetched_at": "TEXT DEFAULT ''",
        "metadata_status": "TEXT DEFAULT 'pending'",
    }
    for column, definition in migrations.items():
        if column not in columns:
            db.execute(f"ALTER TABLE entries ADD COLUMN {column} {definition}")
    db.commit()
    return db


def fingerprint(item: dict) -> str:
    normalized_title = re.sub(r"\W+", "", item["title"].casefold(), flags=re.UNICODE)
    normalized_author = re.sub(r"\s+", "", item.get("author", "").casefold())
    value = f'{item["feed_id"]}|{normalized_title}|{normalized_author}'
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def save_entries(db: sqlite3.Connection, items: list[dict], baselined: set[str]) -> list[dict]:
    now = now_cn().strftime("%Y-%m-%d %H:%M:%S")
    added = []
    for item in items:
        fp = fingerprint(item)
        exists = db.execute("SELECT 1 FROM entries WHERE fingerprint=?", (fp,)).fetchone()
        if exists:
            db.execute("""UPDATE entries SET source=?,source_group=?,kind=?,title=?,link=?,summary=?,author=?,published=?,
                       score=?,level=?,categories=?,matches=?,relation=? WHERE fingerprint=?""",
                       (item["source"],item["source_group"],item["kind"],item["title"],item["link"],item["summary"],
                        item["author"],item["published"],item["score"],item["level"],item["categories"],item["matches"],item["relation"],fp))
            continue
        db.execute("""INSERT INTO entries
          (fingerprint,feed_id,source,source_group,kind,title,link,summary,author,published,first_seen,score,level,categories,matches,relation,baseline)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (fp,item["feed_id"],item["source"],item["source_group"],item["kind"],item["title"],item["link"],
           item["summary"],item["author"],item["published"],now,item["score"],item["level"],item["categories"],item["matches"],item["relation"],
           0 if f'feed:{item["feed_id"]}' in baselined else 1))
        added.append({**item, "fingerprint": fp, "first_seen": now})
    db.commit()
    return added


def apply_metadata_cache(db: sqlite3.Connection) -> int:
    path = CONFIG / "cnki_metadata.json"
    if not path.exists():
        return 0
    updated = 0
    for meta in json.loads(path.read_text(encoding="utf-8")):
        cursor = db.execute("""UPDATE entries SET
          author=COALESCE(NULLIF(?,''),author), author_affiliations=COALESCE(NULLIF(?,''),author_affiliations),
          cnki_online_date=COALESCE(NULLIF(?,''),cnki_online_date), doi=COALESCE(NULLIF(?,''),doi),
          detail_keywords=COALESCE(NULLIF(?,''),detail_keywords), funding=COALESCE(NULLIF(?,''),funding),
          metadata_source=?, metadata_fetched_at=?, metadata_status='complete'
          WHERE feed_id=? AND title=?""",
          (meta.get("author",""),meta.get("author_affiliations",""),meta.get("cnki_online_date",""),meta.get("doi",""),
           meta.get("detail_keywords",""),meta.get("funding",""),meta.get("metadata_source","CNKI详情页"),
           meta.get("metadata_fetched_at",now_cn().strftime("%Y-%m-%d")),meta["feed_id"],meta["title"]))
        updated += cursor.rowcount
    db.commit()
    return updated


def run_lark(args: list[str], message: str, timeout: int = 40) -> subprocess.CompletedProcess:
    if "\ufffd" in message:
        raise ValueError("消息含有乱码替换字符，已拒绝发送")
    wrapper = shutil.which("lark-cli.cmd") or shutil.which("lark-cli")
    node = shutil.which("node")
    if not wrapper or not node:
        raise FileNotFoundError("未找到飞书发送工具")
    entry = Path(wrapper).resolve().parent / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
    if not entry.exists():
        raise FileNotFoundError("未找到飞书发送程序入口")
    env = os.environ.copy()
    env.update({"PYTHONUTF8":"1", "PYTHONIOENCODING":"utf-8", "LARKSUITE_CLI_NO_UPDATE_NOTIFIER":"1", "LARKSUITE_CLI_NO_SKILLS_NOTIFIER":"1"})
    return subprocess.run([node, str(entry), *args], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env)


def send_feishu(items: list[dict], settings: dict, db: sqlite3.Connection) -> tuple[bool, str]:
    if not items or not settings.get("chat_id"):
        return True, "没有需要提醒的新内容"
    selected = items[: int(settings.get("max_notifications_per_run", 5))]
    lines = [f"竞赛研究雷达｜发现 {len(items)} 条强相关更新", ""]
    for i, item in enumerate(selected, 1):
        lines.extend([f"{i}. {item['title']}", f"来源：{item['source']}｜方向：{item['categories']}",
                      f"价值：{item['relation']}", item["link"], ""])
    if len(items) > len(selected):
        lines.append(f"另有 {len(items)-len(selected)} 条，请在本地雷达页面查看。")
    key = hashlib.sha256("|".join(i["fingerprint"] for i in selected).encode()).hexdigest()[:32]
    message = "\n".join(lines)
    cmd = ["im", "+messages-send", "--as", "bot", "--chat-id", settings["chat_id"],
           "--text", message, "--idempotency-key", f"radar-{key}"]
    try:
        result = run_lark(cmd, message, 30)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, f"飞书发送失败：{exc}"
    if result.returncode != 0:
        return False, f"飞书发送失败：{clean_text(result.stderr)[:240]}"
    db.executemany("UPDATE entries SET notified=1 WHERE fingerprint=?", [(i["fingerprint"],) for i in selected])
    db.commit()
    return True, f"飞书已发送 {len(selected)} 条"


def render_dashboard(db: sqlite3.Connection, feeds: list[dict], failures: list[str]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = [dict(r) for r in db.execute("SELECT * FROM entries ORDER BY first_seen DESC, score DESC, published DESC").fetchall()]
    stats = {
        "total": len(rows), "strong": sum(r["level"] == "strong" for r in rows),
        "relevant": sum(r["level"] == "relevant" for r in rows),
        "sources": len({r["feed_id"] for r in rows}),
    }
    last_run = db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "xml"]))
    output = env.get_template("dashboard.html.j2").render(
        entries=rows, stats=stats, feeds=feeds, failures=failures,
        updated=now_cn().strftime("%Y-%m-%d %H:%M"), last_run=dict(last_run) if last_run else None)
    path = OUTPUT / "index.html"
    path.write_text(output, encoding="utf-8")
    return path


def run(open_page: bool, notify: bool) -> int:
    DATA.mkdir(parents=True, exist_ok=True); OUTPUT.mkdir(parents=True, exist_ok=True); LOGS.mkdir(parents=True, exist_ok=True)
    feeds, keywords, settings = load_json("feeds.json"), load_json("keywords.json"), load_json("settings.json")
    db = connect_db()
    initialized = db.execute("SELECT value FROM meta WHERE key='initialized'").fetchone()
    baselined = {r[0] for r in db.execute("SELECT key FROM meta WHERE key LIKE 'feed:%'").fetchall()}
    all_items, failures, successful = [], [], []
    for feed in feeds:
        try:
            all_items.extend(classify(item, keywords) for item in fetch_feed(feed, int(settings["request_timeout_seconds"])))
            successful.append(feed["id"])
        except Exception as exc:
            failures.append(f"{feed['name']}：{exc}")
    added = save_entries(db, all_items, baselined)
    apply_metadata_cache(db)
    strong_new = sorted((i for i in added if i["level"] == "strong" and f'feed:{i["feed_id"]}' in baselined), key=lambda x: x["score"], reverse=True)
    notification = "本轮不发送即时提醒"
    if initialized and notify:
        _, notification = send_feishu(strong_new, settings, db)
    if not initialized:
        notification = "首次运行只建立资料基线，不发送历史论文"
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('initialized',?)", (now_cn().isoformat(),))
    for feed_id in successful:
        db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (f"feed:{feed_id}", now_cn().isoformat()))
    db.execute("INSERT INTO runs(ran_at,fetched,added,strong,failures) VALUES(?,?,?,?,?)",
               (now_cn().strftime("%Y-%m-%d %H:%M:%S"), len(all_items), len(added), len(strong_new), json.dumps(failures, ensure_ascii=False)))
    db.commit()
    path = render_dashboard(db, feeds, failures)
    log = f"抓取 {len(all_items)} 条，新增 {len(added)} 条，强相关新增 {len(strong_new)} 条。{notification}。失败 {len(failures)} 个。"
    (LOGS / "latest.log").write_text(f"{now_cn().isoformat()}\n{log}\n" + "\n".join(failures), encoding="utf-8")
    print(log)
    print(f"页面：{path}")
    if open_page:
        webbrowser.open(path.as_uri())
    return 0 if len(failures) < len(feeds) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="竞赛研究雷达")
    parser.add_argument("--open", action="store_true", help="完成后打开本地页面")
    parser.add_argument("--notify", action="store_true", help="将新发现的强相关内容发送到飞书")
    args = parser.parse_args()
    sys.exit(run(args.open, args.notify))
