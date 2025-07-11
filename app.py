import os
from flask import Flask, request
from dotenv import load_dotenv
from services.task_service import TaskService
from services.calendar_service import CalendarService
from services.openai_service import OpenAIService
from services.notification_service import NotificationService
from models.database import init_db, Task
from linebot import LineBotApi
from linebot.models import TextSendMessage

load_dotenv()
app = Flask(__name__)

task_service = TaskService()
calendar_service = CalendarService()
openai_service = OpenAIService()
notification_service = NotificationService()

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

@app.route("/callback", methods=['POST'])
def callback():
    try:
        data = request.get_json(force=True, silent=True)
        print("受信:", data)
        if data is not None:
            events = data.get("events", [])
            for event in events:
                if event.get("type") == "message" and "replyToken" in event:
                    reply_token = event["replyToken"]
                    user_message = event["message"]["text"]
                    user_id = event["source"].get("userId", "")
                    # タスク登録メッセージか判定してDB保存
                    try:
                        task_info = task_service.parse_task_message(user_message)
                        task_service.create_task(user_id, task_info)
                        reply_text = f"タスク「{task_info['name']}」({task_info['duration_minutes']}分, {'毎日' if task_info['repeat'] else '単発'})を登録しました。"
                    except Exception as e:
                        reply_text = f"タスク登録エラー: {e}"
                    line_bot_api.reply_message(
                        reply_token,
                        TextSendMessage(text=reply_text)
                    )
    except Exception as e:
        print("エラー:", e)
    return "OK", 200

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000))) 