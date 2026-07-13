from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime

from radar import ROOT, clean_text, connect_db, load_json, run_lark, now_cn
from feishu_api import send_cloud_message


def use_suggestions(categories: str) -> list[str]:
    suggestions = []
    if "电桥与电阻测量" in categories:
        suggestions.append("实验：检查现有电桥模型、桥臂选择或线性近似是否需要修正。")
    if "温度传感器与热电阻" in categories:
        suggestions.append("应用：判断能否补充测温场景、传感器对照或装置改进。")
    if "测量误差与不确定度" in categories:
        suggestions.append("论文/答辩：补充误差来源、不确定度分量和结果可信度依据。")
    if "大学物理实验改进" in categories or "实验教学与竞赛创新" in categories:
        suggestions.append("PPT：判断能否转化为“传统局限—改进方法—验证结果”的问题链。")
    return suggestions[:3] or ["建议：先阅读摘要和结论，再决定是否进入竞赛材料。"]


def main(force_test: bool = False) -> int:
    db = connect_db()
    today = now_cn().strftime("%Y-%m-%d")
    delivery_key = f"delivery:daily:{today}"
    if not force_test and db.execute("SELECT 1 FROM meta WHERE key=?", (delivery_key,)).fetchone():
        print("今日早报已经发送，不重复发送。")
        return 0
    items = [dict(r) for r in db.execute(
        "SELECT * FROM entries WHERE baseline=0 AND digest_sent=0 AND level IN ('strong','relevant') ORDER BY score DESC, first_seen DESC LIMIT 5"
    ).fetchall()]
    is_review = not items
    if is_review:
        items = [dict(r) for r in db.execute(
            "SELECT * FROM entries WHERE level='strong' ORDER BY score DESC, published DESC LIMIT 1").fetchall()]
    settings = load_json("settings.json")
    heading = "云端部署测试" if force_test else f"{now_cn():%m月%d日} 早间研究雷达"
    status = "今日暂无达到门槛的新论文，推荐回看 1 篇核心资料。" if is_review else f"今天筛出 **{len(items)} 条**值得关注的新内容。"
    lines = [f"# ☀️ 竞赛研究雷达｜{heading}", "", status, ""]
    for index, item in enumerate(items, 1):
        stars = "★★★★★ 强相关" if item["level"] == "strong" else "★★★ 值得关注"
        summary = clean_text(item["summary"])
        if len(summary) > 260:
            summary = summary[:260].rstrip() + "……"
        lines.extend([f"## {index}. {stars}", f"**《{item['title']}》**  ",
                      f"作者：{item['author'].rstrip(';') or '未提供'}  ",
                      f"单位：{item['author_affiliations'] or '知网详情待补充'}  ",
                      f"来源：{item['source']}｜期刊日期：{item['published'] or '未提供'}  ",
                      f"知网首次公开：{item['cnki_online_date'] or '详情待补充'}｜DOI：{item['doi'] or '未提供'}", "",
                      "**内容在讲什么**", summary or "信源未提供摘要，请打开原文查看。", "",
                      "**为什么值得关注**", item["relation"], "", "**可以立即用在哪里**"])
        lines.extend([f"- {tip}" for tip in use_suggestions(item["categories"])])
        if item["detail_keywords"]:
            lines.extend(["", f"**关键词**：{item['detail_keywords']}"])
        lines.extend(["", f"[打开原文]({item['link']})", ""])
    lines.append("**雷达原则：只负责发现和初筛，正式进入实验、PPT或论文前仍需阅读全文核对。**")
    key = hashlib.sha256((today+"|"+"|".join(i["fingerprint"] for i in items)).encode()).hexdigest()[:32]
    message = "\n".join(lines)
    try:
        if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("LARK_APP_SECRET"):
            message_id = send_cloud_message(message, f"radar-{today}-{key}")
        else:
            cmd = ["im", "+messages-send", "--as", "bot", "--chat-id", settings["chat_id"],
                   "--markdown", message, "--idempotency-key", f"radar-daily-{key}"]
            result = run_lark(cmd, message, 40)
            if result.returncode:
                raise RuntimeError(clean_text(result.stderr)[:240])
            message_id = "local"
    except Exception as exc:
        print(f"早间雷达发送失败：{exc}", file=sys.stderr)
        return 1
    if not is_review and not force_test:
        db.executemany("UPDATE entries SET digest_sent=1 WHERE fingerprint=?", [(item["fingerprint"],) for item in items])
    if not force_test:
        db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (delivery_key, message_id))
    db.commit()
    print(f"早间雷达已发送 {len(items)} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(force_test=os.environ.get("RADAR_FORCE_TEST") == "1"))
