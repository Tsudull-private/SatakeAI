import urllib.request
import json
import os
import ssl
import base64       # ←追加（ファイル暗号化用）
import mimetypes    # ←追加（ファイル種類判定用）
import gradio as gr

# ==========================================
# 1. APIキーの設定（★再度キーを入力してください）
# ==========================================
# os.getenv() を使って、Hugging Face の Secrets からキーを自動取得します
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip().replace('"', '')
FISH_AUDIO_API_KEY = os.getenv("FISH_AUDIO_API_KEY", "").strip().replace('"', '')
FISH_VOICE_ID = os.getenv("FISH_VOICE_ID", "").strip().replace('"', '')

# ==========================================
# 2. 初期設定
# ==========================================
gemini_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
fish_tts_url = "https://api.fish.audio/v1/tts"

file_path = "knowledge.txt"
if not os.path.exists(file_path):
    print(f"エラー: '{file_path}' が見つかりません。")
    exit()

# ==========================================
# ▼ 新規追加：Googleフォーム設定（ご自身のIDに書き換えてください） ▼
# ==========================================
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSeBw6WLsydkt64uYe69c6MJEUECH276jzBZWRbvijuaY4QFuQ/formResponse"
ENTRY_AI_TEXT = "entry.2062956169" # 「AIの回答」のID
ENTRY_FEEDBACK = "entry.1325197948" # 「違和感の内容」のID
# ==========================================

with open(file_path, "r", encoding="utf-8") as file:
    knowledge_text = file.read()

# ==========================================
# 2. チャットと音声生成の裏側処理
# ==========================================
def chat_and_speak(user_message, history):
    gemini_history = []
    
    # [A] 過去の履歴をGemini用に変換
    for pair in history:
        if not pair or len(pair) < 2:
            continue
        user_c, bot_c = pair[0], pair[1]
        
        # 過去のテキストのみをGeminiに引き継ぐ
        if isinstance(user_c, str) and user_c.strip():
            gemini_history.append({"role": "user", "parts": [{"text": user_c}]})
        if isinstance(bot_c, str) and bot_c.strip():
            gemini_history.append({"role": "model", "parts": [{"text": bot_c}]})
    
    user_text = user_message.get("text", "")
    raw_files = user_message.get("files", [])
    
    files = []
    for f in raw_files:
        if isinstance(f, str):
            files.append(f)
        elif isinstance(f, dict) and "path" in f:
            files.append(f["path"])
        elif hasattr(f, "path"):
            files.append(f.path)

    # ★ 今回の修正ポイント：ファイルだけ送られた場合は自動でテキストを補う
    if files and not user_text.strip():
        user_text = "添付ファイルを確認してください。"

    # [B] 今回のメッセージとファイルを準備
    current_parts = []
        
    # 1. まず添付ファイルをすべて追加する
    for filepath in files:
        if not os.path.exists(filepath):
            continue
            
        try:
            mime_type, _ = mimetypes.guess_type(filepath)
            if not mime_type:
                mime_type = "application/octet-stream"
                
            with open(filepath, "rb") as f:
                b64_data = base64.b64encode(f.read()).decode('utf-8')
                
            # ファイルごとに独立した part として追加
            current_parts.append({
                "inlineData": {
                    "mimeType": mime_type,
                    "data": b64_data
                }
            })
        except Exception:
            continue

    # 2. 最後にテキストを追加する（Geminiは「画像→テキスト」の順序を推奨しているため）
    if user_text:
        current_parts.append({"text": user_text})
        
    if not current_parts:
        return {"text": "", "files": []}, history, None

    gemini_history.append({"role": "user", "parts": current_parts})

    # [C] Geminiへ送信
    gemini_data = {
        "system_instruction": {"parts": [{"text": knowledge_text}]},
        "contents": gemini_history,
        "generationConfig": {"maxOutputTokens": 2048}
    }
    
    req_body = json.dumps(gemini_data).encode('utf-8')
    gemini_req = urllib.request.Request(gemini_url, data=req_body, method='POST')
    gemini_req.add_header('Content-Type', 'application/json')
    gemini_req.add_header('x-goog-api-key', GEMINI_API_KEY)
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(gemini_req, context=ctx) as response:
        result = json.loads(response.read().decode('utf-8'))
        reply_text = result['candidates'][0]['content']['parts'][0]['text']
        reply_text = reply_text.replace("<", "＜").replace(">", "＞")

    # [D] Fish Audioで音声生成
    audio_path = "voice_reply.wav"
    try:
        fish_data = {
            "text": reply_text,
            "reference_id": FISH_VOICE_ID,
            "format": "wav"
        }
        fish_req_body = json.dumps(fish_data).encode('utf-8')
        fish_req = urllib.request.Request(fish_tts_url, data=fish_req_body, method='POST')
        fish_req.add_header('Authorization', f'Bearer {FISH_AUDIO_API_KEY}')
        fish_req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(fish_req, context=ctx) as f_response:
            with open(audio_path, "wb") as f:
                f.write(f_response.read())
    except Exception:
        audio_path = None
        reply_text += "\n\n*(※現在、音声APIが一時的に制限に達しているためテキストのみでお答えしています)*"

    # [E] 画面の履歴（history）への反映
    for filepath in files:
        if os.path.exists(filepath):
            history.append([(filepath,), None])
            
    # テキストを必ず履歴に追加（自動補完された「添付ファイルを〜」も表示される）
    history.append([user_text, reply_text])
    
    return {"text": "", "files": []}, history, audio_path

# ==========================================
# 3. フィードバック送信処理
# ==========================================
def send_feedback(history, feedback_text):
    if not feedback_text:
        return "⚠️ 内容が入力されていません。", feedback_text
    if not history:
        return "⚠️ 会話履歴がありません。", feedback_text

    last_ai_message = "取得できませんでした"
    for pair in reversed(history):
        if len(pair) >= 2 and isinstance(pair[1], str) and pair[1].strip():
            last_ai_message = pair[1]
            break

    data = {
        ENTRY_AI_TEXT: last_ai_message,
        ENTRY_FEEDBACK: feedback_text
    }
    data_encoded = urllib.parse.urlencode(data).encode('utf-8')
    req = urllib.request.Request(GOOGLE_FORM_URL, data=data_encoded, method='POST')

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx) as response:
            pass
    except Exception:
        pass

    return "✅ 報告を送信しました！ご協力ありがとうございます。", ""

# ==========================================
# 4. Web画面（UI）のレイアウト
# ==========================================
with gr.Blocks(title="佐竹教授 AIチャット") as demo:
    gr.Markdown("## 佐竹教授 AIチャットボット")
    
    chatbot = gr.Chatbot(label="会話", height=400)
    audio_output = gr.Audio(label="音声", autoplay=True, visible=True) 
    
    msg = gr.MultimodalTextbox(label="", placeholder="質問やファイルを添付して送信...", interactive=True)

    with gr.Accordion("📝 AIの回答に違和感がある場合はこちら", open=False):
        gr.Markdown("直前の教授の回答で、事実誤認や不自然な口調があればお知らせください。")
        with gr.Row():
            feedback_msg = gr.Textbox(label="違和感の内容", placeholder="例：口調が若すぎる、〇〇という言葉はおかしい...など", scale=4)
            feedback_btn = gr.Button("報告を送信", scale=1)
        feedback_status = gr.Markdown("")

    msg.submit(chat_and_speak, inputs=[msg, chatbot], outputs=[msg, chatbot, audio_output])
    
    feedback_btn.click(
        send_feedback,
        inputs=[chatbot, feedback_msg],
        outputs=[feedback_status, feedback_msg]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
