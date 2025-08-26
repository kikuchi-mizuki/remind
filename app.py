import os
from flask import Flask, request, redirect, session, url_for
from dotenv import load_dotenv
from services.task_service import TaskService
from services.calendar_service import CalendarService
from services.openai_service import OpenAIService
from services.notification_service import NotificationService
from models.database import init_db, Task
from linebot.v3.messaging import (
    MessagingApi,
    Configuration,
    ApiClient,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    ImageMessage,
    FlexContainer,
    TemplateMessage,
    QuickReply,
    QuickReplyItem,
)
from linebot.v3.webhook import WebhookHandler
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from werkzeug.middleware.proxy_fix import ProxyFix
import re as regex
from datetime import datetime, timedelta
import pytz

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "your-default-secret-key")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# データベースを最初に初期化
init_db()
print(f"[app.py] データベース初期化完了: {datetime.now()}")

from models.database import db

print(f"[app.py] データベースインスタンス確認: {db.db_path if db else 'None'}")

task_service = TaskService(db)
calendar_service = CalendarService()
openai_service = OpenAIService()
notification_service = NotificationService()

# --- 修正 ---
# line_bot_api = MessagingApi(channel_access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
configuration = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
api_client = ApiClient(configuration)
line_bot_api = MessagingApi(api_client)

# スケジューラーを確実に開始（重複開始を防ぐ）
if not notification_service.is_running:
    try:
        notification_service.start_scheduler()
        print(f"[app.py] スケジューラー開始完了: {datetime.now()}")
    except Exception as e:
        print(f"[app.py] スケジューラー開始エラー: {e}")
        import traceback

        traceback.print_exc()
else:
    print(f"[app.py] スケジューラーは既に動作中: {datetime.now()}")

# client_secrets.jsonがなければ環境変数から生成
if not os.path.exists("client_secrets.json"):
    secrets = os.environ.get("CLIENT_SECRETS_JSON")
    if secrets:
        with open("client_secrets.json", "w") as f:
            f.write(secrets)


# Google認証済みユーザー管理（tokenファイルの存在と有効性で判定）
def is_google_authenticated(user_id):
    """tokenの存在と有効性をDBでチェック"""
    from models.database import db

    print(f"[is_google_authenticated] 開始: user_id={user_id}")
    print(f"[is_google_authenticated] DBファイルパス: {db.db_path}")
    token_json = db.get_token(user_id)
    print(
        f"[is_google_authenticated] DBから取得: token_json={token_json[:100] if token_json else 'None'}"
    )
    if not token_json:
        print(f"[is_google_authenticated] トークンが存在しません")
        return False
    try:
        from google.oauth2.credentials import Credentials
        import json

        print(f"[is_google_authenticated] JSONパース開始")
        creds = Credentials.from_authorized_user_info(
            json.loads(token_json),
            [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        print(
            f"[is_google_authenticated] Credentials作成成功: refresh_token={getattr(creds, 'refresh_token', None) is not None}"
        )
        if creds and creds.refresh_token:
            if creds.expired and creds.refresh_token:
                try:
                    from google.auth.transport.requests import Request

                    print(f"[is_google_authenticated] トークン更新開始")
                    creds.refresh(Request())
                    db.save_token(user_id, creds.to_json())
                    print(f"[is_google_authenticated] トークン更新成功")
                    return True
                except Exception as e:
                    print(f"[is_google_authenticated] Token refresh failed: {e}")
                    return False
            print(f"[is_google_authenticated] 認証成功（更新不要）")
            return True
        print(f"[is_google_authenticated] refresh_tokenが存在しません")
        return False
    except Exception as e:
        print(f"[is_google_authenticated] Token validation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def add_google_authenticated_user(user_id):
    """認証済みユーザーとして登録（tokenファイルが存在する場合のみ）"""
    # tokenファイルの存在確認のみ（実際の登録はoauth2callbackで行う）
    pass


# Google認証URL生成（本番URLに修正）
def get_google_auth_url(user_id):
    return f"https://web-production-bf2e2.up.railway.app/google_auth?user_id={user_id}"


@app.route("/google_auth")
def google_auth():
    user_id = request.args.get("user_id")
    # Google OAuth2フロー開始
    flow = Flow.from_client_secrets_file(
        "client_secrets.json",
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive",
        ],
        redirect_uri="https://web-production-bf2e2.up.railway.app/oauth2callback",
    )
    # stateにuser_idを含める
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # 確実にrefresh_tokenを取得するため
        state=user_id,
    )
    # stateをセッションに保存（本番はDB推奨）
    session["state"] = state
    session["user_id"] = user_id
    return redirect(auth_url)


@app.route("/oauth2callback")
def oauth2callback():
    try:
        print("[oauth2callback] start")
        state = request.args.get("state")
        print(f"[oauth2callback] state: {state}")
        user_id = state or session.get("user_id")
        print(f"[oauth2callback] user_id: {user_id}")
        flow = Flow.from_client_secrets_file(
            "client_secrets.json",
            scopes=[
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/drive",
            ],
            state=state,
            redirect_uri="https://web-production-bf2e2.up.railway.app/oauth2callback",
        )
        print("[oauth2callback] flow created")
        flow.fetch_token(authorization_response=request.url)
        print("[oauth2callback] token fetched")
        creds = flow.credentials
        print(f"[oauth2callback] creds: {creds}")
        print(
            f"[oauth2callback] creds.refresh_token: {getattr(creds, 'refresh_token', None)}"
        )
        print(f"[oauth2callback] user_id: {user_id}")
        # refresh_tokenの確認
        if not creds.refresh_token:
            print(
                "[oauth2callback] ERROR: refresh_token not found! 必ずGoogle認証時に『別のアカウントを選択』してください。"
            )
            return (
                "認証エラー: refresh_tokenが取得できませんでした。<br>ブラウザで『別のアカウントを使用』を選択して再度認証してください。",
                400,
            )

        # ユーザーごとにトークンを保存
        import os

        try:
            from models.database import db

            if not user_id:
                print(f"[oauth2callback] ERROR: user_id is None, token保存スキップ")
            else:
                token_json = creds.to_json()
                print(
                    f"[oauth2callback] save_token呼び出し: user_id={user_id}, token_json先頭100={token_json[:100]}"
                )
                print(f"[oauth2callback] DBファイルパス: {db.db_path}")
                db.save_token(str(user_id), token_json)
                print(f"[oauth2callback] token saved to DB for user: {user_id}")
        except Exception as e:
            print(f"[oauth2callback] token保存エラー: {e}")
            import traceback

            traceback.print_exc()

        # 認証済みユーザーとして登録
        add_google_authenticated_user(user_id)
        print("[oauth2callback] user registered")

        # 認証完了メッセージと使い方ガイドを送信
        try:
            print(f"[oauth2callback] 認証完了メッセージ送信開始: user_id={user_id}")

            # LINE API制限チェック用フラグ
            line_api_limited = False

            # 簡潔な認証完了メッセージを送信
            guide_text = """✅ Googleカレンダー連携完了！

🤖 基本的な使い方：
• 「タスク追加」→ タスク名・所要時間・期限を入力
• 「タスク一覧」→ 登録済みタスクを確認
• 「緊急タスク追加」→ 今日の空き時間に自動スケジュール
• 「未来タスク追加」→ 投資につながるタスクを登録
• 「タスク削除」→ 不要なタスクを削除

何かご質問があれば、いつでもお気軽にお声かけください！"""

            try:
                print(f"[oauth2callback] ガイドメッセージ送信試行: user_id={user_id}")
                line_bot_api.push_message(
                    PushMessageRequest(
                        to=str(user_id), messages=[TextMessage(text=guide_text)]
                    )
                )
                print("[oauth2callback] 認証完了ガイド送信成功")
            except Exception as e:
                print(f"[oauth2callback] ガイドメッセージ送信エラー: {e}")
                if "429" in str(e) or "monthly limit" in str(e):
                    print(f"[oauth2callback] LINE API制限エラー: {e}")
                    line_api_limited = True
                    # 制限エラーの場合は、認証完了のみを通知
                    try:
                        print(
                            f"[oauth2callback] 簡潔メッセージ送信試行: user_id={user_id}"
                        )
                        line_bot_api.push_message(
                            PushMessageRequest(
                                to=str(user_id),
                                messages=[
                                    TextMessage(
                                        text="✅ Googleカレンダー連携完了！\n\n「タスク追加」と送信してタスクを追加してください。"
                                    )
                                ],
                            )
                        )
                        print("[oauth2callback] 簡潔な認証完了メッセージ送信成功")
                    except Exception as e2:
                        print(f"[oauth2callback] 簡潔メッセージ送信も失敗: {e2}")
                        print(
                            "[oauth2callback] LINE API制限により、すべてのメッセージ送信が失敗しました"
                        )
                else:
                    print(f"[oauth2callback] その他の送信エラー: {e}")
                    import traceback

                    traceback.print_exc()

            # 操作メニューも送信（制限エラーの場合はスキップ）
            if not line_api_limited:
                try:
                    print(f"[oauth2callback] Flexメニュー送信試行: user_id={user_id}")
                    from linebot.v3.messaging import FlexMessage, FlexContainer

                    flex_message = get_simple_flex_menu(str(user_id))
                    flex_container = FlexContainer.from_dict(flex_message)
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=str(user_id),
                            messages=[
                                FlexMessage(
                                    alt_text="操作メニュー", contents=flex_container
                                )
                            ],
                        )
                    )
                    print("[oauth2callback] Flexメニュー送信成功")
                except Exception as e:
                    print(f"[oauth2callback] Flexメニュー送信エラー詳細: {e}")
                    if "429" in str(e) or "monthly limit" in str(e):
                        print(f"[oauth2callback] Flexメニュー送信制限エラー: {e}")
                        print("[oauth2callback] Flexメニュー送信をスキップしました")
                        line_api_limited = True
                    else:
                        print(f"[oauth2callback] Flexメニュー送信エラー: {e}")
                        import traceback

                        traceback.print_exc()

            print("[oauth2callback] 認証完了処理完了")
        except Exception as e:
            print(f"[oauth2callback] 認証完了処理エラー: {e}")
            import traceback

            traceback.print_exc()

        # pending_actionがあれば自動実行
        pending_path = f"pending_actions/pending_action_{user_id}.json"
        if user_id and os.path.exists(pending_path):
            import json

            with open(pending_path, "r") as f:
                pending_action = json.load(f)
            os.remove(pending_path)
            user_message = pending_action.get("user_message", "")
            reply_token = pending_action.get("reply_token", None)
            if user_message.strip() == "タスク一覧":
                all_tasks = task_service.get_user_tasks(str(user_id))
                reply_text = task_service.format_task_list(
                    all_tasks, show_select_guide=True
                )
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        replyToken=reply_token, messages=[TextMessage(text=reply_text)]
                    )
                )
            elif user_message.strip() == "はい":
                import os
                import json
                import re
                from datetime import datetime
                import pytz

                selected_path = f"selected_tasks_{user_id}.json"
                if os.path.exists(selected_path):
                    with open(selected_path, "r") as f:
                        task_ids = json.load(f)
                    all_tasks = task_service.get_user_tasks(str(user_id))
                    selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                    jst = pytz.timezone("Asia/Tokyo")
                    today = datetime.now(jst)
                    free_times = calendar_service.get_free_busy_times(
                        str(user_id), today
                    )
                    if not free_times and len(free_times) == 0:
                        # Google認証エラーの可能性
                        reply_text = (
                            "❌ Googleカレンダーへのアクセスに失敗しました。\n\n"
                        )
                        reply_text += "以下の手順で再認証をお願いします：\n"
                        reply_text += "1. 下記のリンクからGoogle認証を実行\n"
                        reply_text += "2. 認証時は必ずアカウント選択画面でアカウントを選び直してください\n"
                        reply_text += (
                            "3. 認証完了後、再度「はい」と送信してください\n\n"
                        )
                        auth_url = get_google_auth_url(user_id)
                        reply_text += f"🔗 {auth_url}"
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                replyToken=reply_token,
                                messages=[TextMessage(text=reply_text)],
                            )
                        )
                        return "OK", 200
                    proposal = openai_service.generate_schedule_proposal(
                        selected_tasks, free_times
                    )
                    with open(f"schedule_proposal_{user_id}.txt", "w") as f:
                        f.write(proposal)
                    # ここでproposalをそのまま送信
                    print("[LINE送信直前 proposal]", proposal)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            replyToken=reply_token,
                            messages=[TextMessage(text=proposal)],
                        )
                    )
                    return "OK", 200
                else:
                    reply_text = "先に今日やるタスクを選択してください。"
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            replyToken=reply_token,
                            messages=[TextMessage(text=reply_text)],
                        )
                    )
                    return "OK", 200
            else:
                # pending_actionがある場合は処理済みなので、追加のメニュー送信は不要
                pass
        # pending_actionがない場合は、最初に送信済みのメニューで十分
        return """
        <html>
        <head>
            <title>認証完了</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background-color: #f5f5f5; }
                .container { background: white; border-radius: 10px; padding: 40px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 500px; margin: 0 auto; }
                .success { color: #4CAF50; font-size: 28px; margin-bottom: 20px; font-weight: bold; }
                .message { color: #666; margin-bottom: 20px; line-height: 1.6; }
            </style>
        </head>
        <body>
            <div class="container">
            <div class="success">✅ 認証完了</div>
            <div class="message">
                    Googleカレンダーとの連携が完了しました！
                </div>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        import traceback

        print(f"[oauth2callback] error: {e}\n{traceback.format_exc()}")
        return f"認証エラー: {e}<br><pre>{traceback.format_exc()}</pre>", 500


@app.route("/callback", methods=["POST"])
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
                    print(f"[DEBUG] 受信user_message: '{user_message}'", flush=True)
                    user_id = event["source"].get("userId", "")

                    # ユーザーをデータベースに登録（初回メッセージ時）
                    from models.database import db

                    db.register_user(user_id)

                    # ここで認証未済なら認証案内のみ返す
                    if not is_google_authenticated(user_id):
                        auth_url = get_google_auth_url(user_id)
                        reply_text = f"Googleカレンダー連携のため、まずこちらから認証をお願いします:\n{auth_url}"
                        line_bot_api.reply_message(
                            ReplyMessageRequest(
                                replyToken=reply_token,
                                messages=[TextMessage(text=reply_text)],
                            )
                        )
                        continue
                    # --- ここから下は認証済みユーザーのみ ---

                    # 緊急タスク追加モードフラグを最優先で判定
                    import os
                    urgent_mode_file = f"urgent_task_mode_{user_id}.json"
                    if os.path.exists(urgent_mode_file):
                        print(f"[DEBUG] 緊急タスク追加モードフラグ検出: {urgent_mode_file}")
                        try:
                            task_info = task_service.parse_task_message(user_message)
                            task = task_service.create_task(user_id, task_info)
                            # 緊急タスクとして今日のスケジュールに追加
                            if is_google_authenticated(user_id):
                                try:
                                    from services.calendar_service import CalendarService
                                    from datetime import datetime, timedelta
                                    import pytz
                                    
                                    calendar_service = CalendarService()
                                    
                                    # 今日の日付を取得（JST）
                                    jst = pytz.timezone('Asia/Tokyo')
                                    today = datetime.now(jst).replace(hour=0, minute=0, second=0, microsecond=0)
                                    
                                    # 最適な開始時刻を提案（重複チェック付き）
                                    optimal_time = calendar_service.suggest_optimal_time(user_id, task.duration_minutes, "urgent")
                                    
                                    if optimal_time:
                                        # 重複チェック
                                        if calendar_service.check_time_conflict(user_id, optimal_time, task.duration_minutes):
                                            print(f"[DEBUG] 最適時刻で重複検出: {optimal_time.strftime('%H:%M')}")
                                            # 重複がある場合は別の時刻を探す
                                            from datetime import timedelta
                                            alternative_times = []
                                            for hour in range(8, 22):  # 8時から22時まで
                                                for minute in [0, 30]:  # 30分間隔
                                                    test_time = today.replace(hour=hour, minute=minute, second=0, microsecond=0)
                                                    if not calendar_service.check_time_conflict(user_id, test_time, task.duration_minutes):
                                                        alternative_times.append(test_time)
                                            
                                            if alternative_times:
                                                optimal_time = min(alternative_times, key=lambda x: x)
                                                print(f"[DEBUG] 代替時刻を選択: {optimal_time.strftime('%H:%M')}")
                                            else:
                                                optimal_time = None
                                                print("[DEBUG] 代替時刻が見つかりません")
                                    
                                    if optimal_time:
                                        # 最適な時刻にタスクを配置
                                        success = calendar_service.add_event_to_calendar(
                                            user_id, 
                                            task.name, 
                                            optimal_time, 
                                            task.duration_minutes,
                                            f"緊急タスク: {task.name}"
                                        )
                                        if success:
                                            reply_text = f"✅ 緊急タスクを追加し、今日のスケジュールに配置しました！\n\n📋 タスク: {task.name}\n⏰ 所要時間: {task.duration_minutes}分\n🕐 開始時刻: {optimal_time.strftime('%H:%M')}"
                                        else:
                                            reply_text = f"✅ 緊急タスクを追加しましたが、カレンダーへの配置に失敗しました。\n\n📋 タスク: {task.name}\n⏰ 所要時間: {task.duration_minutes}分"
                                    else:
                                        # 最適な時刻が見つからない場合は現在時刻から1時間後に配置（重複チェック付き）
                                        start_time = datetime.now(jst) + timedelta(hours=1)
                                        start_time = start_time.replace(minute=0, second=0, microsecond=0)
                                        
                                        # 重複チェック
                                        if calendar_service.check_time_conflict(user_id, start_time, task.duration_minutes):
                                            # 重複がある場合はさらに1時間後
                                            start_time += timedelta(hours=1)
                                        
                                        success = calendar_service.add_event_to_calendar(
                                            user_id, 
                                            task.name, 
                                            start_time, 
                                            task.duration_minutes,
                                            f"緊急タスク: {task.name}"
                                        )
                                        if success:
                                            reply_text = f"✅ 緊急タスクを追加し、今日のスケジュールに配置しました！\n\n📋 タスク: {task.name}\n⏰ 所要時間: {task.duration_minutes}分\n🕐 開始時刻: {start_time.strftime('%H:%M')}"
                                        else:
                                            reply_text = f"✅ 緊急タスクを追加しましたが、カレンダーへの配置に失敗しました。\n\n📋 タスク: {task.name}\n⏰ 所要時間: {task.duration_minutes}分"
                                except Exception as e:
                                    print(f"[DEBUG] カレンダー追加エラー: {e}")
                                    reply_text = f"✅ 緊急タスクを追加しましたが、カレンダーへの配置に失敗しました。\n\n📋 タスク: {task.name}\n⏰ 所要時間: {task.duration_minutes}分"
                            else:
                                reply_text = f"✅ 緊急タスクを追加しました！\n\n📋 タスク: {task.name}\n⏰ 所要時間: {task.duration_minutes}分"
                            
                            os.remove(urgent_mode_file)
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        except Exception as e:
                            print(f"[DEBUG] 緊急タスク追加エラー: {e}")
                            reply_text = f"⚠️ 緊急タスク追加中にエラーが発生しました: {e}"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue

                    # 未来タスク追加モードフラグを判定
                    future_mode_file = f"future_task_mode_{user_id}.json"
                    if os.path.exists(future_mode_file):
                        print(f"[DEBUG] 未来タスク追加モードフラグ検出: {future_mode_file}")
                        try:
                            task_info = task_service.parse_task_message(user_message)
                            task = task_service.create_future_task(user_id, task_info)
                            os.remove(future_mode_file)
                            
                            # 未来タスク一覧を取得して表示
                            future_tasks = task_service.get_user_future_tasks(user_id)
                            reply_text = task_service.format_future_task_list(future_tasks, show_select_guide=False)
                            reply_text += "\n\n✅ 未来タスクを追加しました！"
                            
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        except Exception as e:
                            print(f"[DEBUG] 未来タスク追加エラー: {e}")
                            reply_text = f"⚠️ 未来タスク追加中にエラーが発生しました: {e}"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue

                    # タスク追加モードフラグを判定
                    import os
                    add_flag = f"add_task_mode_{user_id}.flag"
                    if os.path.exists(add_flag):
                        print(f"[DEBUG] タスク追加モードフラグ検出: {add_flag}")
                        # キャンセルワード判定（全角・半角空白、改行、大小文字を吸収）
                        cancel_words = ["キャンセル", "やめる", "中止"]
                        normalized_message = user_message.strip().replace('　','').replace('\n','').lower()
                        print(f"[DEBUG] キャンセル判定: normalized_message='{normalized_message}'")
                        if normalized_message in [w.lower() for w in cancel_words]:
                            os.remove(add_flag)
                            reply_text = "タスク追加をキャンセルしました。"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        try:
                            task_info = task_service.parse_task_message(user_message)
                            task = task_service.create_task(user_id, task_info)
                            os.remove(add_flag)
                            all_tasks = task_service.get_user_tasks(user_id)
                            task_list_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                            reply_text = f"✅ タスクを追加しました！\n\n{task_list_text}\n\nタスクの追加や削除があれば、いつでもお気軽にお声かけください！"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        except Exception as e:
                            print(f"[DEBUG] タスク追加エラー: {e}")
                            reply_text = f"⚠️ タスク追加中にエラーが発生しました: {e}"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue

                    try:
                        # 削除モード判定を追加
                        import os
                        delete_mode_file = f"delete_mode_{user_id}.json"
                        if os.path.exists(delete_mode_file):
                            print(f"[DEBUG] 削除モード判定: {delete_mode_file} 存在")
                            # ユーザーの入力から削除対象タスクを抽出
                            # 例：「タスク 1、3」「未来タスク 2」「タスク 1、未来タスク 2」
                            import re
                            # AIで番号抽出
                            from services.openai_service import OpenAIService
                            openai_service = OpenAIService()
                            ai_result = openai_service.extract_task_numbers_from_message(user_message)
                            if ai_result and (ai_result.get("tasks") or ai_result.get("future_tasks")):
                                task_numbers = [str(n) for n in ai_result.get("tasks", [])]
                                future_task_numbers = [str(n) for n in ai_result.get("future_tasks", [])]
                                print(f"[DEBUG] AI抽出: 通常タスク番号: {task_numbers}, 未来タスク番号: {future_task_numbers}")
                            else:
                                # 全角数字→半角数字へ変換
                                def z2h(s):
                                    return s.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
                                normalized_message = z2h(user_message)
                                task_numbers = re.findall(r"タスク\s*(\d+)", normalized_message)
                                future_task_numbers = re.findall(r"未来タスク\s*(\d+)", normalized_message)
                                print(f"[DEBUG] fallback: 通常タスク番号: {task_numbers}, 未来タスク番号: {future_task_numbers}")
                            all_tasks = task_service.get_user_tasks(user_id)
                            future_tasks = task_service.get_user_future_tasks(user_id)
                            deleted = []
                            # 通常タスク削除
                            for num in task_numbers:
                                idx = int(num) - 1
                                if 0 <= idx < len(all_tasks):
                                    task = all_tasks[idx]
                                    task_service.delete_task(task.task_id)
                                    deleted.append(f"タスク {num}. {task.name}")
                            # 未来タスク削除
                            for num in future_task_numbers:
                                idx = int(num) - 1
                                if 0 <= idx < len(future_tasks):
                                    task = future_tasks[idx]
                                    task_service.delete_future_task(task.task_id)
                                    deleted.append(f"未来タスク {num}. {task.name}")
                            # 削除モードファイルを削除
                            os.remove(delete_mode_file)
                            print(f"[DEBUG] 削除モードファイル削除: {delete_mode_file}")
                            if deleted:
                                reply_text = "✅ タスクを削除しました！\n" + "\n".join(deleted)
                            else:
                                reply_text = "⚠️ 削除対象のタスクが見つかりませんでした。"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        # Google認証が必要な機能でのみ認証チェックを行う
                        # 基本的なタスク管理機能は認証なしでも利用可能

                        # タスク登録メッセージか判定してDB保存（コマンドでない場合のみ）
                        # コマンド一覧
                        commands = [
                            "タスク追加",
                            "緊急タスク追加",
                            "未来タスク追加",
                            "タスク削除",
                            "タスク一覧",
                            "未来タスク一覧",
                            "キャンセル",
                            "認証確認",
                            "DB確認",
                            "8時テスト",
                            "８時テスト",
                            "21時テスト",
                            "日曜18時テスト",
                            "はい",
                            "修正する",
                            "承認する",
                        ]

                        print(
                            f"[DEBUG] コマンド判定: user_message='{user_message.strip()}', in commands={user_message.strip() in commands}"
                        )
                        print(f"[DEBUG] コマンド一覧: {commands}")

                        # 自然言語でのタスク追加処理を先に実行
                        # コマンドでない場合、自然言語でのタスク追加として処理
                        if user_message.strip() not in commands:
                            print(f"[DEBUG] 自然言語タスク追加判定: '{user_message}' はコマンドではありません")
                            # 時間表現が含まれているかチェック（分、時間、半など）
                            time_patterns = ['分', '時間', '半', 'hour', 'min', 'minute']
                            has_time = any(pattern in user_message for pattern in time_patterns)
                            
                            if has_time:
                                print(f"[DEBUG] 時間表現検出: '{user_message}' をタスク追加として処理します")
                                try:
                                    task_info = task_service.parse_task_message(user_message)
                                    task = task_service.create_task(user_id, task_info)
                                    all_tasks = task_service.get_user_tasks(user_id)
                                    task_list_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                                    reply_text = f"✅ タスクを追加しました！\n\n{task_list_text}\n\nタスクの追加や削除があれば、いつでもお気軽にお声かけください！"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    continue
                                except Exception as e:
                                    print(f"[DEBUG] 自然言語タスク追加エラー: {e}")
                                    # エラーの場合は通常のFlexMessageメニューを表示
                                    pass

                        # タスク選択処理を先に実行（数字入力の場合）
                        import os

                        select_flag = f"task_select_mode_{user_id}.flag"
                        print(
                            f"[DEBUG] タスク選択フラグ確認: {select_flag}, exists={os.path.exists(select_flag)}"
                        )
                        if user_message.strip().isdigit() or (
                            "," in user_message or "、" in user_message
                        ):
                            if os.path.exists(select_flag):
                                print(f"[DEBUG] タスク選択フラグ検出: {select_flag}")
                                print(
                                    f"[DEBUG] タスク選択処理開始: user_message='{user_message}'"
                                )
                                try:
                                    # 全タスクを取得して、表示された番号と一致させる
                                    from datetime import datetime
                                    import pytz
                                    jst = pytz.timezone('Asia/Tokyo')
                                    today_str = datetime.now(jst).strftime('%Y-%m-%d')
                                    
                                    all_tasks = task_service.get_user_tasks(user_id)
                                    
                                    # 表示された番号と一致するように、全タスクから選択
                                    print(f"[DEBUG] 全タスク: {[f'{i+1}.{task.name}' for i, task in enumerate(all_tasks)]}")
                                    
                                    # 選択された数字を解析（全角カンマも対応）
                                    selected_numbers = [
                                        int(n.strip())
                                        for n in user_message.replace("、", ",").replace("，", ",").split(
                                            ","
                                        )
                                        if n.strip().isdigit()
                                    ]
                                    if not selected_numbers:
                                        reply_text = "⚠️ 有効な数字を入力してください。\n例: 1、2、3"
                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                        continue
                                    
                                    # デバッグ情報を追加
                                    print(f"[DEBUG] 選択された数字: {selected_numbers}")
                                    print(f"[DEBUG] 全タスク数: {len(all_tasks)}")
                                    print(f"[DEBUG] 全タスク一覧: {[(i+1, task.name) for i, task in enumerate(all_tasks)]}")
                                    
                                    selected_tasks = []
                                    for num in selected_numbers:
                                        idx = num - 1
                                        if 0 <= idx < len(all_tasks):
                                            selected_tasks.append(all_tasks[idx])
                                            print(
                                                f"[DEBUG] タスク選択: 番号={num}, インデックス={idx}, タスク名={all_tasks[idx].name}"
                                            )
                                        else:
                                            print(
                                                f"[DEBUG] タスク選択エラー: 番号={num}, インデックス={idx}, 最大インデックス={len(all_tasks)-1}"
                                            )
                                    if not selected_tasks:
                                        # より詳細なエラーメッセージを提供
                                        available_numbers = list(range(1, len(all_tasks) + 1))
                                        reply_text = (
                                            f"⚠️ 選択されたタスクが見つかりませんでした。\n\n"
                                            f"選択可能な番号: {', '.join(map(str, available_numbers))}\n"
                                            f"入力された番号: {', '.join(map(str, selected_numbers))}"
                                        )
                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                        continue
                                    
                                    # 選択されたタスクを即座に削除
                                    deleted_tasks = []
                                    for task in selected_tasks:
                                        try:
                                            task_service.delete_task(task.task_id)
                                            deleted_tasks.append(task.name)
                                            print(f"[DEBUG] タスク削除完了: {task.name}")
                                        except Exception as e:
                                            print(f"[DEBUG] タスク削除エラー: {task.name}, {e}")

                                    # 削除結果を報告
                                    if deleted_tasks:
                                        reply_text = f"✅ 選択されたタスクを削除しました！\n\n"
                                        for i, task_name in enumerate(deleted_tasks, 1):
                                            reply_text += f"{i}. {task_name}\n"
                                        reply_text += "\nお疲れさまでした！"
                                    else:
                                        reply_text = "⚠️ タスクの削除に失敗しました。"
                                    
                                    # タスク選択モードフラグを削除
                                    os.remove(select_flag)
                                    print(f"[DEBUG] タスク選択モードフラグ削除完了: {select_flag}")
                                    
                                    print(
                                        f"[DEBUG] タスク削除結果送信開始: {reply_text[:100]}..."
                                    )
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    print(f"[DEBUG] タスク選択確認メッセージ送信完了")
                                    continue
                                except Exception as e:
                                    print(f"[DEBUG] タスク選択処理エラー: {e}")
                                    reply_text = (
                                        "⚠️ タスク選択処理中にエラーが発生しました。"
                                    )
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    continue

                        # コマンド処理を先に実行
                        if user_message.strip() in commands:
                            print(f"[DEBUG] コマンド処理開始: '{user_message.strip()}'")

                            # --- コマンド分岐の一元化 ---
                            if user_message.strip() == "タスク追加":
                                print("[DEBUG] タスク追加分岐: 処理開始", flush=True)
                                all_tasks = task_service.get_user_tasks(user_id)
                                print(f"[DEBUG] タスク追加分岐: タスク件数={len(all_tasks)}", flush=True)
                                add_flag = f"add_task_mode_{user_id}.flag"
                                with open(add_flag, "w") as f:
                                    f.write("add_task_mode")
                                reply_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                                reply_text += "\n\n📝 タスク追加モード\n\n"
                                reply_text += "タスク名・所要時間・期限を入力してください！\n\n"
                                reply_text += "💡 例：\n"
                                reply_text += "• 「資料作成 30分 明日」\n"
                                reply_text += "• 「会議準備 1時間 今日」\n"
                                reply_text += "• 「筋トレ 20分 明日」\n\n"
                                reply_text += "⚠️ 所要時間は必須です！\n\n"
                                reply_text += "💡 タスクを選択後、「空き時間に配置」で自動スケジュールできます！"
                                print(f"[DEBUG] タスク追加分岐: reply_text=\n{reply_text}", flush=True)
                                print("[DEBUG] LINE API reply_message直前", flush=True)
                                res = line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                print(f"[DEBUG] LINE API reply_message直後: {res}", flush=True)
                                continue
                            elif user_message.strip() == "緊急タスク追加":
                                if not is_google_authenticated(user_id):
                                    auth_url = get_google_auth_url(user_id)
                                    reply_text = f"📅 カレンダー連携が必要です\n\nGoogleカレンダーにアクセスして認証してください：\n{auth_url}"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    continue
                                import os
                                from datetime import datetime
                                urgent_mode_file = f"urgent_task_mode_{user_id}.json"
                                with open(urgent_mode_file, "w") as f:
                                    import json
                                    json.dump({"mode": "urgent_task", "timestamp": datetime.now().isoformat()}, f)
                                reply_text = "🚨 緊急タスク追加モード\n\nタスク名と所要時間を送信してください！\n例：「資料作成 1時間半」\n\n※今日の空き時間に自動でスケジュールされます"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue
                            elif user_message.strip() == "未来タスク追加":
                                import os
                                from datetime import datetime
                                future_mode_file = f"future_task_mode_{user_id}.json"
                                with open(future_mode_file, "w") as f:
                                    import json
                                    json.dump({"mode": "future_task", "timestamp": datetime.now().isoformat()}, f)
                                reply_text = "🔮 未来タスク追加モード\n\n"
                                reply_text += "投資につながるタスク名と所要時間を送信してください！\n\n"
                                reply_text += "📝 例：\n"
                                reply_text += "• 新規事業計画 2時間\n"
                                reply_text += "• 営業資料の見直し 1時間半\n"
                                reply_text += "• 〇〇という本を読む 30分\n"
                                reply_text += "• 3カ年事業計画をつくる 3時間\n\n"
                                reply_text += "⚠️ 所要時間は必須です！\n"
                                reply_text += "※毎週日曜日18時に来週やるタスクを選択できます"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue
                            # ここで他のコマンド分岐（elif ...）をそのまま残す
                            # 既存のelse:（未登録コマンド分岐）は削除
                        else:
                            print(f"[DEBUG] else節（未登録コマンド分岐）到達: '{user_message}' - FlexMessageボタンメニューを返します")
                            print("[DEBUG] Flex送信直前")
                            button_message_sent = False
                            try:
                                from linebot.v3.messaging import FlexMessage
                                flex_message_content = get_simple_flex_menu(user_id)
                                print(f"[DEBUG] get_simple_flex_menu返り値: {flex_message_content}")
                                print("[DEBUG] FlexContainer作成直前")
                                from linebot.v3.messaging import FlexContainer
                                flex_container = FlexContainer.from_dict(flex_message_content)
                                flex_message = FlexMessage(
                                    alt_text="メニュー",
                                    contents=flex_container
                                )
                                print("[DEBUG] FlexMessageオブジェクト作成完了")
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[flex_message],
                                    )
                                )
                                button_message_sent = True
                                print("[DEBUG] FlexMessage送信成功")
                            except Exception as e:
                                print(f"[DEBUG] FlexMessage送信エラー: {e}")
                                import traceback
                                traceback.print_exc()
                                if "Invalid reply token" in str(e) or "400" in str(e):
                                    if user_id:
                                        try:
                                            print("[DEBUG] reply tokenが無効なため、push_messageでFlexMessageを送信")
                                            line_bot_api.push_message(
                                                PushMessageRequest(
                                                    to=str(user_id),
                                                    messages=[flex_message],
                                                )
                                            )
                                            button_message_sent = True
                                            print("[DEBUG] push_messageでFlexMessage送信成功")
                                        except Exception as push_e:
                                            print(f"[DEBUG] push_messageでFlexMessage送信も失敗: {push_e}")
                                            import traceback
                                            traceback.print_exc()
                                            try:
                                                reply_text = "何をお手伝いしますか？\n\n以下のコマンドから選択してください：\n• タスク追加\n• 緊急タスク追加\n• 未来タスク追加\n• タスク削除\n• タスク一覧\n• 未来タスク一覧"
                                                line_bot_api.push_message(
                                                    PushMessageRequest(
                                                        to=str(user_id),
                                                        messages=[TextMessage(text=reply_text)],
                                                    )
                                                )
                                                print("[DEBUG] テキストメッセージ送信成功")
                                            except Exception as text_e:
                                                print(f"[DEBUG] テキストメッセージ送信も失敗: {text_e}")
                                    else:
                                        print("[DEBUG] user_idが取得できないため、push_messageを送信できません")
                                else:
                                    print("[DEBUG] reply token以外のエラーのため、push_messageは使用しません")
                            if not button_message_sent:
                                print("[DEBUG] ボタンメニュー送信に失敗しました")
                            print("[DEBUG] Flex送信後")
                            continue

                        # タスク削除コマンドの処理
                        if user_message.strip() == "タスク削除":
                            print(
                                f"[DEBUG] タスク削除コマンド処理開始: user_id={user_id}"
                            )
                            # 通常のタスクと未来タスクを取得
                            all_tasks = task_service.get_user_tasks(user_id)
                            future_tasks = task_service.get_user_future_tasks(
                                user_id
                            )
                            reply_text = "🗑️ タスク削除\n━━━━━━━━━━━━\n"
                            # 通常のタスクを表示
                            if all_tasks:
                                reply_text += "📋 通常タスク\n"
                                for idx, task in enumerate(all_tasks, 1):
                                    # 優先度アイコン（A/B/C/-）
                                    priority_icon = {
                                        "urgent_important": "A",
                                        "urgent_not_important": "B",
                                        "not_urgent_important": "C",
                                        "normal": "-",
                                    }.get(task.priority, "-")

                                    # 期日表示
                                    if task.due_date:
                                        try:
                                            y, m, d = task.due_date.split("-")
                                            due_date_obj = datetime(
                                                int(y), int(m), int(d)
                                            )
                                            weekday_names = [
                                                "月",
                                                "火",
                                                "水",
                                                "木",
                                                "金",
                                                "土",
                                                "日",
                                            ]
                                            weekday = weekday_names[
                                                due_date_obj.weekday()
                                            ]
                                            due_str = (
                                                f"{int(m)}月{int(d)}日({weekday})"
                                            )
                                        except Exception:
                                            due_str = task.due_date
                                    else:
                                        due_str = "期日未設定"

                                    reply_text += f"タスク {idx}. {priority_icon} {task.name} ({task.duration_minutes}分) - {due_str}\n"
                                reply_text += "\n"
                            else:
                                reply_text += "📋 通常タスク\n登録されているタスクはありません。\n\n"

                            # 未来タスクを表示
                            if future_tasks:
                                reply_text += "🔮 未来タスク\n"
                                for idx, task in enumerate(future_tasks, 1):
                                    reply_text += f"未来タスク {idx}. {task.name} ({task.duration_minutes}分)\n"
                                reply_text += "\n"
                            else:
                                reply_text += "🔮 未来タスク\n登録されている未来タスクはありません。\n\n"

                            reply_text += "━━━━━━━━━━━━\n"
                            reply_text += "削除するタスクを選んでください！\n"
                            reply_text += "例：「タスク 1、3」「未来タスク 2」「タスク 1、未来タスク 2」\n"

                            # 削除モードファイルを作成
                            import os

                            delete_mode_file = f"delete_mode_{user_id}.json"
                            print(
                                f"[DEBUG] 削除モードファイル作成開始: {delete_mode_file}"
                            )
                            try:
                                with open(delete_mode_file, "w") as f:
                                    import json
                                    import datetime

                                    json.dump(
                                        {
                                            "mode": "delete",
                                            "timestamp": datetime.datetime.now().isoformat(),
                                        },
                                        f,
                                    )
                                print(
                                    f"[DEBUG] 削除モードファイル作成完了: {delete_mode_file}, exists={os.path.exists(delete_mode_file)}"
                                )
                            except Exception as e:
                                print(f"[ERROR] 削除モードファイル作成エラー: {e}")
                                import traceback

                                traceback.print_exc()

                            print(
                                f"[DEBUG] 削除メッセージ送信開始: {reply_text[:100]}..."
                            )
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            print(f"[DEBUG] 削除メッセージ送信完了")
                            continue
                        elif user_message.strip() == "はい":
                            import os
                            import json

                            selected_tasks_file = f"selected_tasks_{user_id}.json"
                            if os.path.exists(selected_tasks_file):
                                try:
                                    # 選択されたタスクを読み込み
                                    with open(selected_tasks_file, "r") as f:
                                        task_ids = json.load(f)

                                    all_tasks = task_service.get_user_tasks(user_id)
                                    selected_tasks = [
                                        t
                                        for t in all_tasks
                                        if t.task_id in task_ids
                                    ]

                                    if not selected_tasks:
                                        reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[
                                                    TextMessage(text=reply_text)
                                                ],
                                            )
                                        )
                                        continue

                                    # 選択されたタスクを削除
                                    deleted_tasks = []
                                    for task in selected_tasks:
                                        try:
                                            task_service.delete_task(task.task_id)
                                            deleted_tasks.append(task.name)
                                            print(f"[DEBUG] タスク削除完了: {task.name}")
                                        except Exception as e:
                                            print(f"[DEBUG] タスク削除エラー: {task.name}, {e}")

                                    # 削除結果を報告
                                    if deleted_tasks:
                                        reply_text = f"✅ 選択されたタスクを削除しました！\n\n"
                                        for i, task_name in enumerate(deleted_tasks, 1):
                                            reply_text += f"{i}. {task_name}\n"
                                        reply_text += "\nお疲れさまでした！"
                                    else:
                                        reply_text = "⚠️ タスクの削除に失敗しました。"

                                    # 選択されたタスクファイルを削除
                                    os.remove(selected_tasks_file)
                                    
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    continue

                                except Exception as e:
                                    print(f"[DEBUG] はいコマンド処理エラー: {e}")
                                    reply_text = f"⚠️ スケジュール提案生成中にエラーが発生しました: {e}"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    continue
                            else:
                                reply_text = "⚠️ 先にタスクを選択してください。"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                # ... 省略 ...
                            continue
                        elif user_message.strip() == "8時テスト":
                            try:
                                notification_service.send_daily_task_notification()
                                reply_text = "8時テスト通知を送信しました"
                            except Exception as e:
                                reply_text = f"8時テストエラー: {e}"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        elif user_message.strip() == "21時テスト":
                            try:
                                notification_service.send_carryover_check()
                                reply_text = "21時テスト通知を送信しました"
                            except Exception as e:
                                reply_text = f"21時テストエラー: {e}"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        elif user_message.strip() == "日曜18時テスト":
                            try:
                                notification_service.send_future_task_selection()
                                reply_text = "日曜18時テスト通知を送信しました"
                            except Exception as e:
                                reply_text = f"日曜18時テストエラー: {e}"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        elif user_message.strip() == "スケジューラー確認":
                            scheduler_status = notification_service.is_running
                            thread_status = (
                                notification_service.scheduler_thread.is_alive()
                                if notification_service.scheduler_thread
                                else False
                            )
                            reply_text = f"スケジューラー状態:\n- is_running: {scheduler_status}\n- スレッド動作: {thread_status}"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue
                        elif user_message.strip() == "承認する":
                            try:
                                # スケジュール提案ファイルを確認
                                import os

                                schedule_proposal_file = (
                                    f"schedule_proposal_{user_id}.txt"
                                )
                                if os.path.exists(schedule_proposal_file):
                                    # スケジュール提案を読み込み
                                    with open(schedule_proposal_file, "r") as f:
                                        proposal = f.read()

                                    # Googleカレンダーにスケジュールを追加
                                    from services.calendar_service import (
                                        CalendarService,
                                    )

                                    calendar_service = CalendarService()

                                    # 選択されたタスクを取得
                                    selected_tasks_file = (
                                        f"selected_tasks_{user_id}.json"
                                    )
                                    if os.path.exists(selected_tasks_file):
                                        import json

                                        with open(selected_tasks_file, "r") as f:
                                            task_ids = json.load(f)

                                        # 通常のタスクと未来タスクの両方を確認
                                        all_tasks = task_service.get_user_tasks(
                                            user_id
                                        )
                                        future_tasks = (
                                            task_service.get_user_future_tasks(
                                                user_id
                                            )
                                        )

                                        selected_tasks = [
                                            t
                                            for t in all_tasks
                                            if t.task_id in task_ids
                                        ]
                                        selected_future_tasks = [
                                            t
                                            for t in future_tasks
                                            if t.task_id in task_ids
                                        ]

                                        # 未来タスクがある場合は通常のタスクに変換
                                        for future_task in selected_future_tasks:
                                            task_info = {
                                                "name": future_task.name,
                                                "duration_minutes": future_task.duration_minutes,
                                                "priority": "not_urgent_important",
                                                "due_date": None,
                                                "repeat": False,
                                            }
                                            converted_task = (
                                                task_service.create_task(
                                                    user_id, task_info
                                                )
                                            )
                                            selected_tasks.append(converted_task)

                                            # 元の未来タスクを削除
                                            task_service.delete_future_task(
                                                future_task.task_id
                                            )
                                            print(
                                                f"[DEBUG] 未来タスクを通常タスクに変換: {future_task.name} -> {converted_task.task_id}"
                                            )

                                        # カレンダーに追加
                                        success_count = 0

                                        # 未来タスクがある場合は来週の日付で処理
                                        from datetime import datetime, timedelta
                                        import pytz

                                        jst = pytz.timezone("Asia/Tokyo")

                                        if selected_future_tasks:
                                            # 未来タスクの場合：来週の日付で処理
                                            today = datetime.now(jst)
                                            next_week = today + timedelta(days=7)
                                            target_date = next_week
                                            print(
                                                f"[DEBUG] 未来タスク処理: 来週の日付 {target_date.strftime('%Y-%m-%d')} を使用"
                                            )
                                        else:
                                            # 通常タスクの場合：今日の日付で処理
                                            target_date = datetime.now(jst)
                                            print(
                                                f"[DEBUG] 通常タスク処理: 今日の日付 {target_date.strftime('%Y-%m-%d')} を使用"
                                            )

                                        # スケジュール提案から時刻を抽出してカレンダーに追加
                                        success_count = calendar_service.add_events_to_calendar(user_id, proposal)
                                        
                                        if success_count == 0:
                                            # パースに失敗した場合は、固定時刻で追加
                                            print("[DEBUG] スケジュール提案のパースに失敗、固定時刻で追加")
                                            for task in selected_tasks:
                                                start_time = target_date.replace(
                                                    hour=14,
                                                    minute=0,
                                                    second=0,
                                                    microsecond=0,
                                                )
                                                if calendar_service.add_event_to_calendar(
                                                    user_id,
                                                    task.name,
                                                    start_time,
                                                    task.duration_minutes,
                                                ):
                                                    success_count += 1

                                        reply_text = f"✅ スケジュールを承認しました！\n\n{success_count}個のタスクをカレンダーに追加しました。\n\n"

                                        # 未来タスクの場合は来週のスケジュール、通常タスクの場合は今日のスケジュールを表示
                                        if selected_future_tasks:
                                            # 未来タスクの場合：来週全体のスケジュールを表示
                                            schedule_date = target_date
                                            week_schedule = (
                                                calendar_service.get_week_schedule(
                                                    user_id, schedule_date
                                                )
                                            )
                                            date_label = f"📅 来週のスケジュール ({schedule_date.strftime('%m/%d')}〜):"
                                            print(
                                                f"[DEBUG] 来週のスケジュール取得結果: {len(week_schedule)}日分"
                                            )
                                        else:
                                            # 通常タスクの場合：今日のスケジュールを表示
                                            schedule_date = target_date
                                            schedule_list = (
                                                calendar_service.get_today_schedule(
                                                    user_id
                                                )
                                            )
                                            date_label = "📅 今日のスケジュール："
                                            print(
                                                f"[DEBUG] 今日のスケジュール取得結果: {len(schedule_list)}件"
                                            )

                                        if selected_future_tasks:
                                            # 未来タスクの場合：来週全体のスケジュールを表示
                                            if week_schedule:
                                                reply_text += date_label + "\n"
                                                reply_text += "━━━━━━━━━━━━━━\n"
                                                from datetime import datetime

                                                for day_data in week_schedule:
                                                    day_date = day_data["date"]
                                                    day_events = day_data["events"]

                                                    # 日付ヘッダーを表示
                                                    day_label = day_date.strftime(
                                                        "%m/%d"
                                                    )
                                                    day_of_week = [
                                                        "月",
                                                        "火",
                                                        "水",
                                                        "木",
                                                        "金",
                                                        "土",
                                                        "日",
                                                    ][day_date.weekday()]
                                                    reply_text += f"📅 {day_label}({day_of_week})\n"

                                                    if day_events:
                                                        for event in day_events:
                                                            try:
                                                                start_time = datetime.fromisoformat(
                                                                    event["start"]
                                                                ).strftime(
                                                                    "%H:%M"
                                                                )
                                                                end_time = datetime.fromisoformat(
                                                                    event["end"]
                                                                ).strftime(
                                                                    "%H:%M"
                                                                )
                                                            except Exception:
                                                                start_time = event[
                                                                    "start"
                                                                ]
                                                                end_time = event[
                                                                    "end"
                                                                ]
                                                            summary = event["title"]
                                                            # 📝と[added_by_bot]を削除
                                                            clean_summary = summary.replace(
                                                                "📝 ", ""
                                                            ).replace(
                                                                " [added_by_bot]",
                                                                "",
                                                            )
                                                            reply_text += f"🕐 {start_time}〜{end_time} 📝 {clean_summary}\n"
                                                    else:
                                                        reply_text += " 予定なし\n"

                                                    reply_text += "━━━━━━━━━━━━━━\n"
                                            else:
                                                reply_text += f" 来週のスケジュールはありません。"
                                        else:
                                            # 通常タスクの場合：今日のスケジュールを表示
                                            if schedule_list:
                                                reply_text += date_label + "\n"
                                                reply_text += "━━━━━━━━━━━━━━\n"
                                                from datetime import datetime

                                                for i, event in enumerate(
                                                    schedule_list
                                                ):
                                                    try:
                                                        start_time = (
                                                            datetime.fromisoformat(
                                                                event["start"]
                                                            ).strftime("%H:%M")
                                                        )
                                                        end_time = (
                                                            datetime.fromisoformat(
                                                                event["end"]
                                                            ).strftime("%H:%M")
                                                        )
                                                    except Exception:
                                                        start_time = event["start"]
                                                        end_time = event["end"]
                                                    summary = event["title"]
                                                    # 📝と[added_by_bot]を削除
                                                    clean_summary = summary.replace(
                                                        "📝 ", ""
                                                    ).replace(" [added_by_bot]", "")
                                                    reply_text += f"🕐 {start_time}〜{end_time}\n"
                                                    reply_text += (
                                                        f"📝 {clean_summary}\n"
                                                    )
                                                    reply_text += "━━━━━━━━━━━━━━\n"
                                            else:
                                                reply_text += " 今日のスケジュールはありません。"

                                        # ファイルを削除
                                        if os.path.exists(schedule_proposal_file):
                                            os.remove(schedule_proposal_file)
                                        if os.path.exists(selected_tasks_file):
                                            os.remove(selected_tasks_file)
                                    else:
                                        reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
                                else:
                                    reply_text = (
                                        "⚠️ スケジュール提案が見つかりませんでした。"
                                    )

                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                            except Exception as e:
                                print(f"[ERROR] 承認処理: {e}")
                                import traceback

                                traceback.print_exc()
                                reply_text = (
                                    f"⚠️ 承認処理中にエラーが発生しました: {e}"
                                )
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                            continue
                        elif user_message.strip() == "修正する":
                            try:
                                reply_text = "📝 スケジュール修正モード\n\n修正したい内容を送信してください！\n\n例：\n• 「資料作成を14時に変更」\n• 「会議準備を15時30分に変更」"

                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                            except Exception as e:
                                print(f"[ERROR] 修正処理: {e}")
                                import traceback

                                traceback.print_exc()
                                reply_text = (
                                    f"⚠️ 修正処理中にエラーが発生しました: {e}"
                                )
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                            continue
                        elif (
                            regex.match(r"^(\d+[ ,、]*)+$", user_message.strip())
                            or user_message.strip() == "なし"
                        ):
                            from datetime import datetime, timedelta
                            import pytz

                            jst = pytz.timezone("Asia/Tokyo")
                            today_str = datetime.now(jst).strftime("%Y-%m-%d")
                            tasks = task_service.get_user_tasks(user_id)
                            today_tasks = [
                                t for t in tasks if t.due_date == today_str
                            ]
                            if not today_tasks:
                                continue
                            # 返信が「なし」→全削除
                            if user_message.strip() == "なし":
                                for t in today_tasks:
                                    task_service.archive_task(t.task_id)
                                reply_text = "本日分のタスクはすべて削除しました。お疲れさまでした！"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue
                            # 番号抽出
                            nums = regex.findall(r"\d+", user_message)
                            carryover_indexes = set(int(n) - 1 for n in nums)
                            for idx, t in enumerate(today_tasks):
                                if idx in carryover_indexes:
                                    # 期日を翌日に更新
                                    next_day = (
                                        datetime.now(jst) + timedelta(days=1)
                                    ).strftime("%Y-%m-%d")
                                    t.due_date = next_day
                                    task_service.create_task(
                                        user_id,
                                        {
                                            "name": t.name,
                                            "duration_minutes": t.duration_minutes,
                                            "due_date": next_day,
                                            "priority": t.priority,
                                            "task_type": t.task_type,
                                        },
                                    )
                                    task_service.archive_task(
                                        t.task_id
                                    )  # 元タスクはアーカイブ
                                else:
                                    task_service.archive_task(t.task_id)
                            reply_text = "指定されたタスクを明日に繰り越し、それ以外は削除しました。"
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue

                        continue

                        # コマンドでない場合のみタスク登録処理を実行
                        print(
                            f"[DEBUG] コマンド以外のメッセージ処理開始: '{user_message}'"
                        )

                        # 緊急タスク追加モードでの処理
                        import os
                        from datetime import datetime

                        urgent_mode_file = f"urgent_task_mode_{user_id}.json"
                        print(
                            f"[DEBUG] 緊急タスク追加モードファイル確認: {urgent_mode_file}, exists={os.path.exists(urgent_mode_file)}"
                        )
                        if os.path.exists(urgent_mode_file):
                            print(f"[DEBUG] 緊急タスク追加モードフラグ検出: {urgent_mode_file}")
                            try:
                                task_info = task_service.parse_task_message(user_message)
                                task_info["priority"] = "urgent_not_important"
                                from datetime import datetime
                                import pytz
                                jst = pytz.timezone("Asia/Tokyo")
                                today = datetime.now(jst)
                                task_info["due_date"] = today.strftime("%Y-%m-%d")
                                task = task_service.create_task(user_id, task_info)
                                print(f"[DEBUG] 緊急タスク作成完了: task_id={task.task_id}")
                                # 今日の空き時間に直接スケジュール追加
                                from services.calendar_service import CalendarService
                                calendar_service = CalendarService()
                                free_times = calendar_service.get_free_busy_times(user_id, today)
                                if free_times:
                                    first_free_time = free_times[0]
                                    start_time = first_free_time["start"]
                                    end_time = start_time + timedelta(minutes=task.duration_minutes)
                                    success = calendar_service.add_event_to_calendar(
                                        user_id=user_id,
                                        task_name=task.name,
                                        start_time=start_time,
                                        duration_minutes=task.duration_minutes,
                                        description=f"緊急タスク: {task.name}",
                                    )
                                    if success:
                                        reply_text = "⚡ 緊急タスクを追加しました！\n\n"
                                        reply_text += f"📅 今日のスケジュールに追加：\n"
                                        reply_text += f"🕐 {start_time.strftime('%H:%M')}〜{end_time.strftime('%H:%M')}\n"
                                        reply_text += f"📝 {task.name}\n\n"
                                        reply_text += "✅ カレンダーに直接追加されました！"
                                    else:
                                        reply_text = "⚡ 緊急タスクを追加しました！\n\n"
                                        reply_text += "⚠️ カレンダーへの追加に失敗しました。\n"
                                        reply_text += "手動でスケジュールを調整してください。"
                                else:
                                    reply_text = "⚡ 緊急タスクを追加しました！\n\n"
                                    reply_text += "⚠️ 今日の空き時間が見つかりませんでした。\n"
                                    reply_text += "手動でスケジュールを調整してください。"
                                os.remove(urgent_mode_file)
                                print(f"[DEBUG] 緊急タスク追加モードフラグ削除: {urgent_mode_file}")
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue
                            except Exception as e:
                                print(f"[DEBUG] 緊急タスク追加エラー: {e}")
                                reply_text = f"⚠️ 緊急タスク追加中にエラーが発生しました: {e}"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                os.remove(urgent_mode_file)
                                continue

                        # 未来タスク追加モードでの処理
                        future_mode_file = f"future_task_mode_{user_id}.json"
                        print(
                            f"[DEBUG] 未来タスク追加モードファイル確認: {future_mode_file}, exists={os.path.exists(future_mode_file)}"
                        )
                        if os.path.exists(future_mode_file):
                            print(
                                f"[DEBUG] 未来タスク追加モード開始: user_message='{user_message}'"
                            )
                            try:
                                # 未来タスクとして登録
                                task_info = task_service.parse_task_message(
                                    user_message
                                )
                                task_info["priority"] = (
                                    "not_urgent_important"  # 重要なタスクとして設定
                                )
                                task_info["due_date"] = None  # 期限なし（未来タスク）

                                task = task_service.create_future_task(
                                    user_id, task_info
                                )
                                print(
                                    f"[DEBUG] 未来タスク作成完了: task_id={task.task_id}"
                                )

                                # 未来タスク一覧を取得して表示
                                future_tasks = task_service.get_user_future_tasks(
                                    user_id
                                )
                                print(
                                    f"[DEBUG] 未来タスク一覧取得完了: {len(future_tasks)}件"
                                )

                                # 新しく追加したタスクの情報を確認
                                print(
                                    f"[DEBUG] 新しく追加したタスク: task_id={task.task_id}, name={task.name}, duration={task.duration_minutes}分"
                                )
                                print(f"[DEBUG] 未来タスク一覧詳細:")
                                for i, ft in enumerate(future_tasks):
                                    print(
                                        f"[DEBUG] 未来タスク{i+1}: task_id={ft.task_id}, name={ft.name}, duration={ft.duration_minutes}分, created_at={ft.created_at}"
                                    )

                                reply_text = self.task_service.format_future_task_list(future_tasks, show_select_guide=False)
                                reply_text += "\n\n✅ 未来タスクを追加しました！"

                                # 未来タスク追加モードファイルを削除
                                if os.path.exists(future_mode_file):
                                    os.remove(future_mode_file)

                                print(
                                    f"[DEBUG] 未来タスク追加モード返信メッセージ送信開始: {reply_text[:100]}..."
                                )
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                print(
                                    f"[DEBUG] 未来タスク追加モード返信メッセージ送信完了"
                                )
                                print(
                                    f"[DEBUG] 未来タスク追加モード処理完了、処理を終了"
                                )
                                return "OK", 200
                            except Exception as e:
                                print(f"[DEBUG] 未来タスク追加モード処理エラー: {e}")
                                import traceback

                                traceback.print_exc()
                                reply_text = (
                                    f"⚠️ 未来タスク追加中にエラーが発生しました: {e}"
                                )
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue

                        # 未来タスク選択モードでの処理
                        future_selection_file = f"future_task_selection_{user_id}.json"
                        print(
                            f"[DEBUG] 未来タスク選択モードファイル確認: {future_selection_file}, exists={os.path.exists(future_selection_file)}"
                        )
                        if os.path.exists(future_selection_file):
                            print(
                                f"[DEBUG] 未来タスク選択モード開始: user_message='{user_message}'"
                            )
                            try:
                                # 数字の入力かどうかチェック
                                if user_message.strip().isdigit():
                                    task_number = int(user_message.strip())
                                    print(f"[DEBUG] 未来タスク選択番号: {task_number}")

                                    # 未来タスク一覧を取得
                                    future_tasks = task_service.get_user_future_tasks(
                                        user_id
                                    )
                                    print(
                                        f"[DEBUG] 未来タスク一覧取得: {len(future_tasks)}件"
                                    )

                                    if 1 <= task_number <= len(future_tasks):
                                        selected_task = future_tasks[task_number - 1]
                                        print(
                                            f"[DEBUG] 選択された未来タスク: {selected_task.name}"
                                        )

                                        # 選択された未来タスクをスケジュール提案用に準備
                                        from services.calendar_service import (
                                            CalendarService,
                                        )
                                        from services.openai_service import (
                                            OpenAIService,
                                        )
                                        from datetime import datetime, timedelta
                                        import pytz

                                        calendar_service = CalendarService()
                                        openai_service = OpenAIService()

                                        jst = pytz.timezone("Asia/Tokyo")
                                        today = datetime.now(jst)

                                        # 来週の空き時間を取得（今日から7日後）
                                        next_week = today + timedelta(days=7)
                                        free_times = (
                                            calendar_service.get_free_busy_times(
                                                user_id, next_week
                                            )
                                        )

                                        if free_times:
                                            # スケジュール提案を生成（来週のスケジュールとして）
                                            proposal = openai_service.generate_schedule_proposal(
                                                [selected_task],
                                                free_times,
                                                week_info="来週",
                                            )

                                            # スケジュール提案ファイルを作成
                                            schedule_proposal_file = (
                                                f"schedule_proposal_{user_id}.txt"
                                            )
                                            with open(
                                                schedule_proposal_file,
                                                "w",
                                                encoding="utf-8",
                                            ) as f:
                                                f.write(proposal)

                                            # 選択されたタスクファイルを作成（未来タスクIDを含める）
                                            selected_tasks_file = (
                                                f"selected_tasks_{user_id}.json"
                                            )
                                            import json

                                            with open(
                                                selected_tasks_file,
                                                "w",
                                                encoding="utf-8",
                                            ) as f:
                                                json.dump(
                                                    [selected_task.task_id],
                                                    f,
                                                    ensure_ascii=False,
                                                )

                                            reply_text = (
                                                f"【来週のスケジュール提案】\n\n"
                                            )
                                            reply_text += proposal
                                            reply_text += "\n\n承認する場合は「承認する」、修正する場合は「修正する」と送信してください。"
                                        else:
                                            reply_text = f"⚠️ 来週の空き時間が見つかりませんでした。\n"
                                            reply_text += f"未来タスク「{selected_task.name}」は手動でスケジュールを調整してください。"

                                        # 未来タスク選択モードファイルを削除
                                        if os.path.exists(future_selection_file):
                                            os.remove(future_selection_file)

                                        # 未来タスク選択モードファイルを削除
                                        if os.path.exists(future_selection_file):
                                            os.remove(future_selection_file)

                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                        continue
                                    else:
                                        reply_text = f"⚠️ 無効な番号です。1〜{len(future_tasks)}の間で選択してください。"
                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                        continue
                                else:
                                    reply_text = "⚠️ 数字で選択してください。例: 1、3、5"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    continue
                            except Exception as e:
                                print(f"[DEBUG] 未来タスク選択モード処理エラー: {e}")
                                import traceback

                                traceback.print_exc()
                                reply_text = (
                                    f"⚠️ 未来タスク選択中にエラーが発生しました: {e}"
                                )
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue

                        # 認識されないコマンドの場合、FlexMessageボタンメニューを返す
                        print(
                            f"[DEBUG] 認識されないコマンド: '{user_message}' - FlexMessageボタンメニューを返します"
                        )
                        print("[DEBUG] Flex送信直前")
                        # FlexMessageを使用してボタンメニューを送信
                        button_message_sent = False
                        try:
                            from linebot.v3.messaging import FlexMessage
                            # 既存のget_simple_flex_menu関数を使用
                            flex_message_content = get_simple_flex_menu(user_id)
                            print(f"[DEBUG] get_simple_flex_menu返り値: {flex_message_content}")
                            print("[DEBUG] FlexContainer作成直前")
                            # FlexMessageオブジェクトを作成
                            from linebot.v3.messaging import FlexContainer
                            flex_container = FlexContainer.from_dict(flex_message_content)
                            flex_message = FlexMessage(
                                alt_text="メニュー",
                                contents=flex_container
                            )
                            print("[DEBUG] FlexMessageオブジェクト作成完了")
                            # reply_messageで送信
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[flex_message],
                                )
                            )
                            button_message_sent = True
                            print("[DEBUG] FlexMessage送信成功")
                        except Exception as e:
                            print(f"[DEBUG] FlexMessage送信エラー: {e}")
                            import traceback
                            traceback.print_exc()
                            # reply tokenが無効な場合のみpush_messageを使用
                            if "Invalid reply token" in str(e) or "400" in str(e):
                                if user_id:
                                    try:
                                        print("[DEBUG] reply tokenが無効なため、push_messageでFlexMessageを送信")
                                        line_bot_api.push_message(
                                            PushMessageRequest(
                                                to=str(user_id),
                                                messages=[flex_message],
                                            )
                                        )
                                        button_message_sent = True
                                        print("[DEBUG] push_messageでFlexMessage送信成功")
                                    except Exception as push_e:
                                        print(f"[DEBUG] push_messageでFlexMessage送信も失敗: {push_e}")
                                        import traceback
                                        traceback.print_exc()
                                        # 最後の手段としてテキストメッセージを送信
                                        try:
                                            reply_text = "何をお手伝いしますか？\n\n以下のコマンドから選択してください：\n• タスク追加\n• 緊急タスク追加\n• 未来タスク追加\n• タスク削除\n• タスク一覧\n• 未来タスク一覧"
                                            line_bot_api.push_message(
                                                PushMessageRequest(
                                                    to=str(user_id),
                                                    messages=[TextMessage(text=reply_text)],
                                                )
                                            )
                                            print("[DEBUG] テキストメッセージ送信成功")
                                        except Exception as text_e:
                                            print(f"[DEBUG] テキストメッセージ送信も失敗: {text_e}")
                                else:
                                    print("[DEBUG] user_idが取得できないため、push_messageを送信できません")
                            else:
                                print("[DEBUG] reply token以外のエラーのため、push_messageは使用しません")
                        if not button_message_sent:
                            print("[DEBUG] ボタンメニュー送信に失敗しました")
                        print("[DEBUG] Flex送信後")
                        continue

                    except Exception as e:
                        print("エラー:", e)
                        # 例外発生時もユーザーにエラー内容を返信
                        try:
                            line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[
                                        TextMessage(
                                            text=f"⚠️ エラーが発生しました: {e}\nしばらく時間をおいて再度お試しください。"
                                        )
                                    ],
                                )
                            )
                        except Exception as inner_e:
                            print("LINEへのエラー通知も失敗:", inner_e)
                            # reply_tokenが無効な場合はpush_messageで通知
                            if user_id:
                                try:
                                    line_bot_api.push_message(
                                        PushMessageRequest(
                                            to=str(user_id),
                                            messages=[
                                                TextMessage(
                                                    text=f"⚠️ エラーが発生しました: {e}\nしばらく時間をおいて再度お試しください。"
                                                )
                                            ],
                                        )
                                    )
                                except Exception as push_e:
                                    print("push_messageも失敗:", push_e)
                            else:
                                print("[DEBUG] user_idが取得できないため、push_messageを送信できません")
                        continue
    except Exception as e:
        print("エラー:", e)
    return "OK", 200


# --- Flex Message メニュー定義 ---
def get_simple_flex_menu(user_id=None):
    """認証状態に応じてメニューを動的に生成（dict型で返す）"""
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {
                    "type": "text",
                    "text": "タスク管理Bot",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1DB446"
                },
                {
                    "type": "text",
                    "text": "何をお手伝いしますか？",
                    "size": "sm",
                    "color": "#666666",
                    "wrap": True
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#1DB446",
                    "action": {
                        "type": "message",
                        "label": "タスクを追加する",
                        "text": "タスク追加"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#FF6B6B",
                    "action": {
                        "type": "message",
                        "label": "緊急タスクを追加する",
                        "text": "緊急タスク追加"
                    }
                },
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#4ECDC4",
                    "action": {
                        "type": "message",
                        "label": "未来タスクを追加する",
                        "text": "未来タスク追加"
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "message",
                        "label": "タスクを削除する",
                        "text": "タスク削除"
                    }
                }
            ]
        }
    }


# --- ボタンメニュー定義 ---
def get_button_menu():
    """ボタンメニューを生成（TemplateMessage用）"""
    return {
        "type": "buttons",
        "title": "タスク管理Bot",
        "text": "何をお手伝いしますか？",
        "actions": [
            {
                "type": "message",
                "label": "タスクを追加する",
                "text": "タスク追加"
            },
            {
                "type": "message",
                "label": "緊急タスクを追加する",
                "text": "緊急タスク追加"
            },
            {
                "type": "message",
                "label": "未来タスクを追加する",
                "text": "未来タスク追加"
            },
            {
                "type": "message",
                "label": "タスクを削除する",
                "text": "タスク削除"
            }
        ]
    }


if __name__ == "__main__":
    # アプリケーション起動
    import os
    from datetime import datetime

    port = int(os.getenv("PORT", 5000))
    print(f"[app.py] Flaskアプリケーション起動: port={port}, time={datetime.now()}")
    print(
        f"[DEBUG] LINE_CHANNEL_ACCESS_TOKEN: {os.getenv('LINE_CHANNEL_ACCESS_TOKEN')}"
    )
    if not os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        print("[ERROR] LINE_CHANNEL_ACCESS_TOKENが環境変数に設定されていません！")
    app.run(debug=False, host="0.0.0.0", port=port)
