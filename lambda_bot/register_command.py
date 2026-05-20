'''resister_command.py'''

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.environ.get("DISCORD_APP_ID", "")
TOKEN = os.environ.get("DISCORD_TOKEN", "")

if not APP_ID or not TOKEN:
    print("❌ 請先設定 DISCORD_APP_ID 和 DISCORD_TOKEN 環境變數")
    sys.exit(1)

url = f"https://discord.com/api/v10/applications/{APP_ID}/commands"

command = {
    "name": "ask",
    "description": "向 AWS Bedrock AI 提問",
    "options": [
        {
            "name": "question",
            "description": "輸入你的問題",
            "type": 3,       # 3 = STRING
            "required": True,
        }
    ],
}

resp = requests.post(
    url,
    json=command,
    headers={"Authorization": f"Bot {TOKEN}"},
)

if resp.status_code in (200, 201):
    data = resp.json()
    print(f"✅ 指令註冊成功！指令 ID：{data['id']}")
    print("   全域指令最多 1 小時後才會出現在 Discord，測試用可改為 Guild 指令（速度較快）。")
else:
    print(f"❌ 失敗（{resp.status_code}）：{resp.text}")
