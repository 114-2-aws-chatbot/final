import boto3
import json
import os
from dotenv import load_dotenv

load_dotenv()

# 初始化 Bedrock 用戶端
bedrock = boto3.client(service_name='bedrock-runtime', region_name='us-east-1')

# 設定 Claude 3 Haiku 的輸入格式
model_id = "amazon.titan-text-lite-v1"

# native_request = {
#     "anthropic_version": "bedrock-2023-05-31",
#     "max_tokens": 512,
#     "messages": [
#         {
#             "role": "user",
#             "content": "如果你看到這句話，請回覆：『連線成功！』"
#         }
#     ],
# }

native_request = {
    "inputText": "如果你看到這句話，請回覆：『連線成功！』",
    "textGenerationConfig": {
        "maxTokenCount": 512,
        "temperature": 0.5
    }
}

try:
    # 轉換為 JSON 字串
    request = json.dumps(native_request)

    # 呼叫模型
    response = bedrock.invoke_model(modelId=model_id, body=request)

    # 解析回傳結果
    # ⚠️ 注意：Titan 的回應格式和 Claude 不同！
    # Titan 格式：{ "results": [{ "outputText": "..." }] }
    # Claude 格式：{ "content": [{ "text": "..." }] }  ← 原本寫錯了
    model_response = json.loads(response["body"].read())
    response_text = model_response["results"][0]["outputText"]
    print(response_text)

except Exception as e:
    print(f"出現錯誤：{e}")