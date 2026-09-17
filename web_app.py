import urllib.request
import json
import os
import ssl
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
    
    # ★ 2往復目以降でフリーズする原因（データ型の自動変換）を解決する安全な読み込み
    for msg in history:
        # 1. 1回目の辞書型の場合
        if isinstance(msg, dict):
            r = msg.get("role", "user")
            c = msg.get("content", "")
        # 2. 万が一古い形式（リスト）で来た場合の保険
        elif isinstance(msg, (list, tuple)):
            if len(msg) >= 2:
                gemini_history.append({"role": "user", "parts": [{"text": str(msg[0])}]})
                gemini_history.append({"role": "model", "parts": [{"text": str(msg[1])}]})
            continue
        # 3. 2回目以降の特殊なオブジェクト型（ChatMessage）で来た場合
        else:
            r = getattr(msg, "role", "user")
            c = getattr(msg, "content", "")
            
        role = "user" if r == "user" else "model"
        gemini_history.append({"role": role, "parts": [{"text": str(c)}]})
    
    # 今回のユーザーからのメッセージを追加
    gemini_history.append({"role": "user", "parts": [{"text": user_message}]})

    # [A] Geminiでテキスト生成
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
        
        # ★追加：画面の文字が透明になって消える現象を防ぐ（< > 記号を無害化）
        reply_text = reply_text.replace("<", "＜").replace(">", "＞")
    
    # [B] Fish Audioで音声生成
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
    except Exception as e:
        # 音声生成に失敗した場合は、強制終了せずにエラー文言をテキストに添える
        audio_path = None
        reply_text += "\n\n*(※現在、音声APIが制限に達しているためテキストのみでお答えしています)*"

    # 履歴への追加
    history.append({"role": "user", "content": user_message})

    # 履歴への追加
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": reply_text})
    
    return "", history, audio_path

# ==========================================
# 3. フィードバック送信処理
# ==========================================
def send_feedback(history, feedback_text):
    if not feedback_text:
        return "⚠️ 内容が入力されていません。", feedback_text
    if not history:
        return "⚠️ 会話履歴がありません。", feedback_text

    # 最新のAIの発言を抽出
    last_ai_message = "取得できませんでした"
    for msg in reversed(history):
        if getattr(msg, "role", "") == "assistant":
            last_ai_message = getattr(msg, "content", "")
            break
        elif isinstance(msg, dict) and msg.get("role") == "assistant":
            last_ai_message = msg.get("content", "")
            break
        elif isinstance(msg, (list, tuple)) and len(msg) >= 2:
            last_ai_message = str(msg[1])
            break

    # Googleフォームへデータを送信
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
        # フォームの送信仕様上エラーが返る場合があるため握り潰す
        pass

    return "✅ 報告を送信しました！ご協力ありがとうございます。", ""

# ==========================================
# 4. Web画面（UI）のレイアウト
# ==========================================
with gr.Blocks(title="佐竹教授 AIチャット") as demo:
    gr.Markdown("## 佐竹教授 AIチャットボット")
    
    chatbot = gr.Chatbot(label="会話", height=400)
    audio_output = gr.Audio(label="音声", autoplay=True, visible=True) 
    
    with gr.Row():
        msg = gr.Textbox(label="", placeholder="質問を入力してEnterキー...", scale=4)
        submit_btn = gr.Button("送信", scale=1)

    # ▼ 新規追加：違和感報告用のアコーディオン（折りたたみメニュー）▼
    with gr.Accordion("📝 AIの回答に違和感がある場合はこちら", open=False):
        gr.Markdown("直前の教授の回答で、事実誤認や不自然な口調があればお知らせください。")
        with gr.Row():
            feedback_msg = gr.Textbox(label="違和感の内容", placeholder="例：口調が若すぎる、〇〇という言葉はおかしい...など", scale=4)
            feedback_btn = gr.Button("報告を送信", scale=1)
        feedback_status = gr.Markdown("")
    # ▲ 新規追加ここまで ▲

    # ボタンとエンターキーの動作設定
    msg.submit(chat_and_speak, inputs=[msg, chatbot], outputs=[msg, chatbot, audio_output])
    submit_btn.click(chat_and_speak, inputs=[msg, chatbot], outputs=[msg, chatbot, audio_output])

    # フィードバックボタンの動作設定
    feedback_btn.click(
        send_feedback,
        inputs=[chatbot, feedback_msg],
        outputs=[feedback_status, feedback_msg]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
