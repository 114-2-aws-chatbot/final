'''Lambda_function.py'''

import base64
import json
import os

import boto3
import requests
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

# ── 環境變數 ──────────────────────────────────────────────────────
DISCORD_PUBLIC_KEY = os.environ["DISCORD_PUBLIC_KEY"]
DISCORD_APP_ID = os.environ["DISCORD_APP_ID"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1")

# ── AWS 用戶端（放在 handler 外，利用 Lambda 暖啟動快取連線）────────
bedrock = boto3.client(
    "bedrock-runtime",
    region_name=os.environ.get("AWS_BEDROCK_REGION", "us-east-1"),
)
lambda_client = boto3.client("lambda")


# ═════════════════════════════════════════════════════════════════
# 工具函式
# ═════════════════════════════════════════════════════════════════


def verify_discord_signature(signature: str, timestamp: str, body: str) -> bool:
    """驗證 Discord 送來的 Ed25519 數位簽名，防止偽造請求"""
    try:
        VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY)).verify(
            f"{timestamp}{body}".encode(),
            bytes.fromhex(signature),
        )
        return True
    except BadSignatureError:
        return False


def call_bedrock(question):
    # 初始化 Bedrock 用戶端
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
   
    try:
        # 使用 AWS 最新的 converse API
        response = bedrock.converse(
            modelId='amazon.nova-lite-v1:0',
            messages=[
                {
                    "role": "user",
                    "content": [{"text": question}]
                }
            ],
            inferenceConfig={
                "maxTokens": 512,
                "temperature": 0.7,
                "topP": 0.9
            }
        )
       
        # 精準抓出 Nova 回傳的文字內容
        answer = response['output']['message']['content'][0]['text']
        return answer
       
    except Exception as e:
        print(f"Bedrock 呼叫失敗: {e}")
        return "抱歉，AI 腦袋暫時當機了，請聯絡管理員！"



def patch_interaction(interaction_token: str, content: str) -> None:
    """
    透過 Discord Interaction Webhook 補發 AI 回覆。
    必須在 Token 發出後 15 分鐘內呼叫，否則 Token 過期。
    """
    url = (
        f"https://discord.com/api/v10/webhooks/"
        f"{DISCORD_APP_ID}/{interaction_token}/messages/@original"
    )
    resp = requests.patch(
        url,
        json={"content": content},
        headers={
            "Authorization": f"Bot {DISCORD_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    resp.raise_for_status()


def json_response(body: dict, status: int = 200) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


# ═════════════════════════════════════════════════════════════════
# Lambda 主入口
# ═════════════════════════════════════════════════════════════════


def lambda_handler(event: dict, context) -> dict:
    """
    進入點：依 event 結構決定走哪條路。

    API Gateway 傳進來的 event 一定有 'headers'。
    Lambda 自呼叫時的 payload 只有自訂欄位（有 'interaction_token'，沒有 'headers'）。
    """
    if "interaction_token" in event and "headers" not in event:
        # Path B：非同步 AI 工作者
        return _ai_worker(event)

    if "headers" in event:
        # Path A：Discord Webhook 請求
        return _discord_handler(event, context)

    return {"statusCode": 400, "body": "Bad Request"}


# ═════════════════════════════════════════════════════════════════
# Path A — Discord Webhook 請求處理
# ═════════════════════════════════════════════════════════════════


def _discord_handler(event: dict, context) -> dict:
    """
    1. 驗證 Discord Ed25519 簽名（必須在 3 秒內完成並回覆）
    2. PING → PONG（Discord 設定 Webhook 時的存活確認）
    3. Slash Command → 觸發 AI 工作者 + 回 Type 5
    """
    # 取出簽名相關 Header（統一轉小寫，相容不同 API Gateway 設定）
    headers = {k.lower(): v for k, v in event["headers"].items()}
    signature = headers.get("x-signature-ed25519", "")
    timestamp = headers.get("x-signature-timestamp", "")

    # API Gateway Binary Media Type 設定時 body 可能是 Base64
    body_raw = event.get("body", "")
    if event.get("isBase64Encoded"):
        body_raw = base64.b64decode(body_raw).decode("utf-8")

    # ① 簽名驗證（Discord 規定：失敗一律回 401，否則 Discord 會停止推送）
    if not verify_discord_signature(signature, timestamp, body_raw):
        return {"statusCode": 401, "body": "Invalid request signature"}

    body = json.loads(body_raw)
    interaction_type = body.get("type")

    # ② PING（type 1）→ PONG（type 1）
    if interaction_type == 1:
        return json_response({"type": 1})

    # ③ Application Command（Slash Command, type 2）
    if interaction_type == 2:
        return _handle_slash_command(body, context)

    return {"statusCode": 400, "body": f"Unsupported interaction type: {interaction_type}"}


def _handle_slash_command(body: dict, context) -> dict:
    """
    處理 /ask 指令：
      步驟 1 — 非同步喚起 Lambda 自身（AI 工作者路徑）
      步驟 2 — 立即回 Type 5（Deferred），Discord 顯示「正在思考...」
               → 繞過 Discord 3 秒超時限制
    """
    data = body.get("data", {})
    options = data.get("options", [])
    question = options[0].get("value", "").strip() if options else ""

    if not question:
        # 沒有輸入問題，直接用 Type 4（即時回覆）給錯誤提示
        return json_response({
            "type": 4,
            "data": {"content": "❌ 請輸入問題！用法：`/ask <你的問題>`"},
        })

    interaction_token = body["token"]

    # 非同步喚起自身（InvocationType='Event' = fire-and-forget，不等待結果）
    try:
        lambda_client.invoke(
            FunctionName=context.invoked_function_arn,
            InvocationType="Event",
            Payload=json.dumps({
                "interaction_token": interaction_token,
                "question": question,
            }),
        )
    except Exception as e:
        # 若自呼叫失敗（IAM 權限缺少等），立即用 Type 4 告知使用者
        print(f"[Lambda Invoke Error] {e}")
        return json_response({
            "type": 4,
            "data": {"content": f"❌ 系統忙碌中，請稍後再試。\n`{e}`"},
        })

    # Type 5：DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
    # Discord 收到後顯示「正在思考...」，等待 Webhook 補發正式回覆
    return json_response({"type": 5})


# ═════════════════════════════════════════════════════════════════
# Path B — AI 工作者（非同步自呼叫）
# ═════════════════════════════════════════════════════════════════


def _ai_worker(event: dict) -> dict:
    """
    由 Lambda 自呼叫觸發（不經過 API Gateway）。
    呼叫 Bedrock 取得答案後，透過 Discord Webhook 補發回覆。
    Lambda timeout 建議設為 60 秒以上。
    """
    token = event["interaction_token"]
    question = event["question"]

    try:
        answer = call_bedrock(question)
        content = f"**問題：** {question}\n\n**AI 回覆：**\n{answer}"
        print(f"[Bedrock OK] question={question[:60]}")
    except Exception as e:
        content = f"❌ Bedrock 發生錯誤：`{e}`"
        print(f"[Bedrock Error] {e}")

    try:
        patch_interaction(token, content)
        print("[Follow-up sent]")
    except Exception as e:
        # Webhook 失敗記 log，但不 raise（Lambda 不需重試這個 job）
        print(f"[Webhook Error] {e}")

    return {"statusCode": 200}
