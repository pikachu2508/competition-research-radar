from __future__ import annotations

import json
import os
import re
import requests


def _plain(markdown: str) -> str:
    text = re.sub(r"\[([^]]+)\]\((https?://[^)]+)\)", r"\1：\2", markdown)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    return text.replace("**", "").replace("  \n", "\n").strip()


def send_cloud_message(markdown: str, idempotency_key: str) -> str:
    app_id = os.environ.get("LARK_APP_ID", "")
    app_secret = os.environ.get("LARK_APP_SECRET", "")
    chat_id = os.environ.get("LARK_CHAT_ID", "")
    if not all((app_id, app_secret, chat_id)):
        raise RuntimeError("云端飞书配置不完整")
    token_response = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret}, timeout=25)
    token_response.raise_for_status()
    token_data = token_response.json()
    if token_data.get("code") != 0:
        raise RuntimeError(f"飞书身份验证失败：{token_data.get('msg', 'unknown')}")
    content = _plain(markdown)
    if "\ufffd" in content:
        raise ValueError("消息含乱码替换字符，已拒绝发送")
    response = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers={"Authorization": f"Bearer {token_data['tenant_access_token']}"},
        json={"receive_id": chat_id, "msg_type": "text",
              "content": json.dumps({"text": content}, ensure_ascii=False),
              "uuid": idempotency_key[:50]}, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书发送失败：{data.get('msg', 'unknown')}")
    return data.get("data", {}).get("message_id", "")
