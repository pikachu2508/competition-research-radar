from __future__ import annotations

import hashlib
import subprocess
import sys
from datetime import datetime, timedelta

from radar import ROOT, connect_db, load_json, run_lark


def main(notify: bool = True) -> int:
    db = connect_db()
    since = (datetime.now().astimezone() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    items = [dict(r) for r in db.execute(
        "SELECT * FROM entries WHERE baseline=0 AND first_seen>=? AND level IN ('strong','relevant') ORDER BY score DESC, first_seen DESC",
        (since,)).fetchall()]
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"{datetime.now():%y-%m-%d}-每周精选.md"
    lines = [f"# {datetime.now():%Y-%m-%d} 竞赛研究雷达每周精选", "", f"本周共发现 {len(items)} 条值得关注的新内容。", ""]
    for index, item in enumerate(items[:20], 1):
        lines.extend([f"## {index}. {item['title']}", "", f"- 来源：{item['source']}", f"- 方向：{item['categories']}",
                      f"- 与竞赛的关系：{item['relation']}", f"- 相关度：{item['score']}", f"- 原文：{item['link']}", ""])
    if not items:
        lines.append("本周没有达到提醒门槛的新内容。")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"每周精选已生成：{path}")
    if not notify or not items:
        return 0
    settings = load_json("settings.json")
    selected = items[:8]
    message = [f"竞赛研究雷达｜本周精选 {len(items)} 条", ""]
    for index, item in enumerate(selected, 1):
        message.extend([f"{index}. {item['title']}", f"{item['source']}｜{item['categories']}", item['link'], ""])
    if len(items) > len(selected):
        message.append(f"另有 {len(items)-len(selected)} 条已收入本地每周报告。")
    key = hashlib.sha256(f"weekly-{datetime.now():%G-%V}".encode()).hexdigest()[:32]
    message_text = "\n".join(message)
    cmd = ["im", "+messages-send", "--as", "bot", "--chat-id", settings["chat_id"],
           "--text", "\n".join(message), "--idempotency-key", f"radar-weekly-{key}"]
    result = run_lark(cmd, message_text, 30)
    if result.returncode:
        print("飞书周报发送失败，本地报告仍已保存。", file=sys.stderr)
        return 1
    print("飞书周报发送成功。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
