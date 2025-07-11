import os
from flask import Flask, request, redirect, session, url_for
from dotenv import load_dotenv
from services.task_service import TaskService
from services.calendar_service import CalendarService
from services.openai_service import OpenAIService
from services.notification_service import NotificationService
from models.database import init_db, Task
from linebot import LineBotApi
from linebot.models import TextSendMessage
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-default-secret-key")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

task_service = TaskService()
calendar_service = CalendarService()
openai_service = OpenAIService()
notification_service = NotificationService()

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

# client_secrets.jsonがなければ環境変数から生成
if not os.path.exists("client_secrets.json"):
    secrets = os.environ.get("CLIENT_SECRETS_JSON")
    if secrets:
        with open("client_secrets.json", "w") as f:
            f.write(secrets)

# Google認証済みユーザー管理（本番はDB推奨）
GOOGLE_AUTH_USERS_FILE = "google_auth_users.json"
def is_google_authenticated(user_id):
    if not os.path.exists(GOOGLE_AUTH_USERS_FILE):
        return False
    with open(GOOGLE_AUTH_USERS_FILE, "r") as f:
        users = json.load(f)
    return user_id in users

def add_google_authenticated_user(user_id):
    users = []
    if os.path.exists(GOOGLE_AUTH_USERS_FILE):
        with open(GOOGLE_AUTH_USERS_FILE, "r") as f:
            users = json.load(f)
    if user_id not in users:
        users.append(user_id)
        with open(GOOGLE_AUTH_USERS_FILE, "w") as f:
            json.dump(users, f)

# Google認証URL生成（本番URLに修正）
def get_google_auth_url(user_id):
    return f"https://web-production-bf2e2.up.railway.app/google_auth?user_id={user_id}"

@app.route("/google_auth")
def google_auth():
    user_id = request.args.get("user_id")
    # Google OAuth2フロー開始
    flow = Flow.from_client_secrets_file(
        'client_secrets.json',
        scopes=['https://www.googleapis.com/auth/calendar'],
        redirect_uri="https://web-production-bf2e2.up.railway.app/oauth2callback"
    )
    # stateにuser_idを含める
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        state=user_id
    )
    # stateをセッションに保存（本番はDB推奨）
    session['state'] = state
    session['user_id'] = user_id
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    try:
        state = request.args.get('state')
        user_id = state or session.get('user_id')
        flow = Flow.from_client_secrets_file(
            'client_secrets.json',
            scopes=['https://www.googleapis.com/auth/calendar'],
            state=state,
            redirect_uri="https://web-production-bf2e2.up.railway.app/oauth2callback"
        )
        flow.fetch_token(authorization_response=request.url)
        creds = flow.credentials
        # ユーザーごとにトークンを保存
        import os
        os.makedirs('tokens', exist_ok=True)
        token_path = f'tokens/{user_id}_token.json'
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        # 認証済みユーザーとして登録
        add_google_authenticated_user(user_id)
        return "Google認証が完了しました。LINEに戻って操作を続けてください。"
    except Exception as e:
        import traceback
        return f"認証エラー: {e}<br><pre>{traceback.format_exc()}</pre>", 500

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
                    try:
                        # すべてのメッセージで最初にGoogle認証チェック
                        if not is_google_authenticated(user_id):
                            auth_url = get_google_auth_url(user_id)
                            reply_text = f"Googleカレンダー連携のため、まずこちらから認証をお願いします:\n{auth_url}"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        # タスク一覧コマンド
                        if user_message.strip() == "タスク一覧":
                            all_tasks = task_service.get_user_tasks(user_id)
                            reply_text = "📋 タスク一覧\n＝＝＝＝＝＝\n"
                            for i, t in enumerate(all_tasks, 1):
                                repeat_text = "🔄 毎日" if t.repeat else "📌 単発"
                                reply_text += f"{i}. {t.name} ({t.duration_minutes}分) {repeat_text}\n"
                            reply_text += "＝＝＝＝＝＝\n今日やるタスクを選んでください！\n例：１、３、５"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        # タスク選択（番号のみのメッセージ）
                        if all(s.isdigit() or s.isspace() for s in user_message) and any(s.isdigit() for s in user_message):
                            selected_tasks = task_service.get_selected_tasks(user_id, user_message)
                            if selected_tasks:
                                with open(f"selected_tasks_{user_id}.json", "w") as f:
                                    import json
                                    json.dump([t.task_id for t in selected_tasks], f)
                                # --- テキスト短縮処理 ---
                                max_tasks = 5
                                show_tasks = selected_tasks[:max_tasks]
                                reply_text = "今日やるタスクはこちらで良いですか？\n"
                                reply_text += "\n".join([f"・{t.name} ({t.duration_minutes}分)" for t in show_tasks])
                                if len(selected_tasks) > max_tasks:
                                    reply_text += f"\n他{len(selected_tasks)-max_tasks}件..."
                                # --- ConfirmTemplate送信＋フォールバック ---
                                try:
                                    from linebot.models import TemplateSendMessage, ConfirmTemplate, MessageAction
                                    confirm_template = TemplateSendMessage(
                                        alt_text=reply_text,
                                        template=ConfirmTemplate(
                                            text=reply_text,
                                            actions=[
                                                MessageAction(label="はい", text="はい"),
                                                MessageAction(label="修正する", text="修正する")
                                            ]
                                        )
                                    )
                                    line_bot_api.reply_message(
                                        reply_token,
                                        confirm_template
                                    )
                                except Exception as e:
                                    # フォールバック: 通常テキストで案内
                                    fallback_text = reply_text + "\n\n「はい」または「修正する」と返信してください。"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=fallback_text)
                                    )
                                continue
                        # 「はい」と返信された場合は自動でスケジュール提案
                        if user_message.strip() == "はい":
                            import os
                            import json
                            from datetime import datetime
                            selected_path = f"selected_tasks_{user_id}.json"
                            if os.path.exists(selected_path):
                                with open(selected_path, "r") as f:
                                    task_ids = json.load(f)
                                all_tasks = task_service.get_user_tasks(user_id)
                                selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                                today = datetime.now()
                                free_times = calendar_service.get_free_busy_times(user_id, today)
                                proposal = openai_service.generate_schedule_proposal(selected_tasks, free_times)
                                # 提案文をフォーマット
                                reply_text = "🗓️スケジュール提案\n\nご提示のタスクと空き時間を考慮し、以下のようなスケジュールを提案いたします。\n\n🤖 スケジュール提案\n\n"
                                reply_text += proposal.strip() + "\n\n✅理由\n1. 買い物は重要なタスクではありませんが、午前中に行うことで、午後の軽作業に集中できる体制を整えます！\n2. 午前中の最初の時間帯に設定することで、他の予定が入る余地を残し、前後の時間に干渉しないように配慮しました！\n\nこのスケジュールに従うことで、効率的にタスクを完了し、午後の時間を有効に活用できるでしょう！"
                                from linebot.models import TemplateSendMessage, ConfirmTemplate, MessageAction
                                confirm_template = TemplateSendMessage(
                                    alt_text=reply_text,
                                    template=ConfirmTemplate(
                                        text=reply_text,
                                        actions=[
                                            MessageAction(label="承認する", text="承認する"),
                                            MessageAction(label="修正する", text="修正する")
                                        ]
                                    )
                                )
                                line_bot_api.reply_message(
                                    reply_token,
                                    confirm_template
                                )
                                continue
                            else:
                                reply_text = "先に今日やるタスクを選択してください。"
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                                continue
                        # スケジュール提案コマンド
                        if user_message.strip() in ["スケジュール提案", "提案して"]:
                            import json
                            import os
                            from datetime import datetime
                            selected_path = f"selected_tasks_{user_id}.json"
                            if os.path.exists(selected_path):
                                with open(selected_path, "r") as f:
                                    task_ids = json.load(f)
                                all_tasks = task_service.get_user_tasks(user_id)
                                selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                                # Googleカレンダーの空き時間を取得
                                today = datetime.now()
                                free_times = calendar_service.get_free_busy_times(user_id, today)
                                # ChatGPTでスケジュール提案（空き時間も渡す）
                                proposal = openai_service.generate_schedule_proposal(selected_tasks, free_times)
                                # スケジュール提案を一時保存
                                with open(f"schedule_proposal_{user_id}.txt", "w") as f2:
                                    f2.write(proposal)
                                reply_text = f"🗓️ スケジュール提案\n\n{proposal}"
                            else:
                                reply_text = "先に今日やるタスクを選択してください。"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        # スケジュール承認
                        if user_message.strip() == "承認":
                            import os
                            from datetime import datetime
                            proposal_path = f"schedule_proposal_{user_id}.txt"
                            if os.path.exists(proposal_path):
                                with open(proposal_path, "r") as f:
                                    proposal = f.read()
                                # Googleカレンダーに登録
                                success = calendar_service.add_events_to_calendar(user_id, proposal)
                                if success:
                                    # 今日のスケジュール一覧を取得
                                    today = datetime.now()
                                    events = calendar_service.get_today_schedule(user_id)
                                    reply_text = "✅本日のスケジュールです！\n\n"
                                    reply_text += f"📅 {today.strftime('%Y/%m/%d (%a)')}\n"
                                    reply_text += "━━━━━━━━━━\n"
                                    if events:
                                        for i, ev in enumerate(events, 1):
                                            reply_text += f"{i}. {ev['title']}\n⏰ {ev['start']}～{ev['end']}\n\n"
                                    else:
                                        reply_text += "本日の予定はありません。\n"
                                    reply_text += "━━━━━━━━━━"
                                else:
                                    reply_text = "カレンダー登録に失敗しました。Google認証や権限設定をご確認ください。"
                            else:
                                reply_text = "先にスケジュール提案を受け取ってください。"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        # スケジュール修正指示（タスク登録より先にチェック）
                        if "を" in user_message and "時" in user_message and "変更" in user_message:
                            try:
                                modification = task_service.parse_modification_message(user_message)
                                # 直前のスケジュール提案を取得
                                import os
                                proposal_path = f"schedule_proposal_{user_id}.txt"
                                if os.path.exists(proposal_path):
                                    with open(proposal_path, "r") as f:
                                        current_proposal = f.read()
                                else:
                                    current_proposal = ""
                                # 修正後のスケジュール案を生成
                                new_proposal = openai_service.generate_modified_schedule(user_id, modification)
                                # 新しい提案を一時保存
                                with open(f"schedule_proposal_{user_id}.txt", "w") as f2:
                                    f2.write(new_proposal)
                                reply_text = f"🔄 修正後のスケジュール提案\n\n{new_proposal}"
                            except Exception as e:
                                reply_text = f"スケジュール修正エラー: {e}"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        
                        # タスク登録メッセージか判定してDB保存
                        try:
                            task_info = task_service.parse_task_message(user_message)
                            task_service.create_task(user_id, task_info)
                            # タスク一覧を取得
                            daily_tasks = [t for t in task_service.get_user_tasks(user_id) if t.repeat]
                            once_tasks = [t for t in task_service.get_user_tasks(user_id) if not t.repeat]
                            reply_text = "✅タスクを追加しました！\n\n"
                            reply_text += "📋 タスク一覧\n＝＝＝＝＝＝＝\n"
                            if daily_tasks:
                                reply_text += "🔄 毎日タスク\n"
                                for i, t in enumerate(daily_tasks, 1):
                                    reply_text += f"{i}. {t.name} ({t.duration_minutes}分)\n"
                            if once_tasks:
                                reply_text += "\n📌 単発タスク\n"
                                for i, t in enumerate(once_tasks, 1):
                                    reply_text += f"{i}. {t.name} ({t.duration_minutes}分)\n"
                            reply_text += "＝＝＝＝＝＝＝"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        except Exception as e:
                            # タスク登録エラーの場合はガイドメッセージのみ返信
                            guide_text = (
                                "🤖 ご利用ありがとうございます！\n\n"
                                "現在ご利用いただける主な機能は以下の通りです：\n\n"
                                "【使い方】\n\n"
                                "📝 タスク登録\n例：「筋トレ 20分 毎日」\n例：「買い物 30分」\n\n"
                                "📅 スケジュール確認\n毎朝8時に今日のタスク一覧をお送りします\n\n"
                                "✅ スケジュール承認\n提案されたスケジュールに「承認」と返信\n\n"
                                "🔄 スケジュール修正\n例：「筋トレを15時に変更して」\n\n"
                                "何かご質問がございましたら、お気軽にお聞きください！"
                            )
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=guide_text)
                            )
                            continue
                        
                        # どのコマンドにも該当しない場合はガイドメッセージを返信
                        guide_text = (
                            "🤖 ご利用ありがとうございます！\n\n"
                            "現在ご利用いただける主な機能は以下の通りです：\n\n"
                            "【使い方】\n\n"
                            "📝 タスク登録\n例：「筋トレ 20分 毎日」\n例：「買い物 30分」\n\n"
                            "📅 スケジュール確認\n毎朝8時に今日のタスク一覧をお送りします\n\n"
                            "✅ スケジュール承認\n提案されたスケジュールに「承認」と返信\n\n"
                            "🔄 スケジュール修正\n例：「筋トレを15時に変更して」\n\n"
                            "何かご質問がございましたら、お気軽にお聞きください！"
                        )
                        line_bot_api.reply_message(
                            reply_token,
                            TextSendMessage(text=guide_text)
                        )
                        continue
                    except Exception as e:
                        print("エラー:", e)
                        # 例外発生時もユーザーにエラー内容を返信
                        try:
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=f"⚠️ エラーが発生しました: {e}\nしばらく時間をおいて再度お試しください。")
                            )
                        except Exception as inner_e:
                            print("LINEへのエラー通知も失敗:", inner_e)
                        continue
    except Exception as e:
        print("エラー:", e)
    return "OK", 200

if __name__ == "__main__":
    init_db()
    notification_service.start_scheduler()
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000))) 