import os
from flask import Flask, request, redirect, session, url_for
from dotenv import load_dotenv
from services.task_service import TaskService
from services.calendar_service import CalendarService
from services.openai_service import OpenAIService
from services.notification_service import NotificationService
from services.multi_tenant_service import MultiTenantService
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
import json
import hmac
import hashlib
import base64

# ハンドラーのインポート
from handlers.test_handler import (
    handle_8am_test,
    handle_9pm_test,
    handle_sunday_6pm_test,
    handle_scheduler_check,
)
from handlers.task_handler import (
    handle_task_add_command,
    handle_task_delete_command,
)
from handlers.urgent_handler import handle_urgent_task_add_command
from handlers.future_handler import handle_future_task_add_command
from handlers.helpers import send_reply_with_menu
from handlers.selection_handler import (
    handle_task_selection_cancel,
    handle_task_selection_process,
)

load_dotenv()

# 必須環境変数のチェック
required_env_vars = {
    "FLASK_SECRET_KEY": "Flaskセッション暗号化キー",
    "LINE_CHANNEL_ACCESS_TOKEN": "LINEチャネルアクセストークン",
    "LINE_CHANNEL_SECRET": "LINEチャネルシークレット",
    "OPENAI_API_KEY": "OpenAI APIキー",
    "CLIENT_SECRETS_JSON": "Google OAuth2設定"
}

missing_vars = []
for var, description in required_env_vars.items():
    if not os.environ.get(var):
        missing_vars.append(f"{var} ({description})")

if missing_vars:
    error_message = "以下の必須環境変数が設定されていません:\n" + "\n".join(f"  - {var}" for var in missing_vars)
    print(f"[ERROR] {error_message}")
    raise RuntimeError(error_message)

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]  # デフォルト値を削除
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


def validate_line_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    """LINE webhook署名を検証"""
    if not signature or not channel_secret:
        return False

    mac = hmac.new(
        channel_secret.encode("utf-8"), body, hashlib.sha256
    ).digest()
    expected_signature = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected_signature, signature)

# データベースを最初に初期化
init_db()
print(f"[app.py] データベース初期化完了: {datetime.now()}")

from models.database import db

# PostgreSQLテーブル作成の確認
if hasattr(db, 'Session') and db.Session:
    print("[app.py] PostgreSQLデータベースを使用中")
    try:
        # テーブル作成を確実にする
        if hasattr(db, '_ensure_tables_exist'):
            db._ensure_tables_exist()
        print("[app.py] PostgreSQLテーブル作成確認完了")
    except Exception as e:
        print(f"[app.py] PostgreSQLテーブル作成確認エラー: {e}")
else:
    print("[app.py] SQLiteデータベースを使用中")

# ルートパスを追加
@app.route("/")
def index():
    return "LINEタスクスケジューリングBot is running!", 200

# データベースインスタンスの確認
if hasattr(db, 'db_path'):
    print(f"[app.py] データベースインスタンス確認: {db.db_path}")
elif hasattr(db, 'engine'):
    print(f"[app.py] PostgreSQLデータベースインスタンス確認: {type(db).__name__}")
else:
    print(f"[app.py] データベースインスタンス確認: {type(db).__name__}")

task_service = TaskService(db)
calendar_service = CalendarService()
openai_service = OpenAIService()
notification_service = NotificationService()
multi_tenant_service = MultiTenantService()

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
    # セキュリティ: トークンの内容はログに出力しない
    print(
        f"[is_google_authenticated] DBから取得: token_json={'存在する' if token_json else 'None'} (長さ: {len(token_json) if token_json else 0})"
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


def get_base_url() -> str:
    """現在のデプロイ環境からベースURLを自動判定"""
    # 明示指定があれば最優先
    base_url = os.getenv("BASE_URL")
    if base_url:
        return base_url.rstrip("/")

    # Railway が提供するドメイン
    domain = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        if domain.startswith("http"):
            return domain.rstrip("/")
        return f"https://{domain}"

    # リクエストコンテキストがあればそこから取得
    try:
        host = request.host
        if host:
            scheme = "https"
            return f"{scheme}://{host}"
    except Exception:
        pass

    # フォールバック（最後の手段）
    return "https://app52.mmms-11.com"


# Google認証URL生成（ベースURLを自動判定）
def get_google_auth_url(user_id):
    return f"{get_base_url()}/google_auth?user_id={user_id}"


@app.route("/google_auth")
def google_auth():
    user_id = request.args.get("user_id")
    print(f"[google_auth] 開始: user_id={user_id}")
    
    # Google OAuth2フロー開始
    try:
        flow = Flow.from_client_secrets_file(
            "client_secrets.json",
            scopes=[
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/drive",
            ],
            redirect_uri=f"{get_base_url()}/oauth2callback",
        )
        print(f"[google_auth] flow作成成功")
        
        # stateにuser_idを含める
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",  # 確実にrefresh_tokenを取得するため
            state=user_id,
        )
        print(f"[google_auth] 認証URL生成成功: state={state}")
        
        # stateをセッションに保存（本番はDB推奨）
        session["state"] = state
        session["user_id"] = user_id
        print(f"[google_auth] セッション保存完了: state={state}, user_id={user_id}")
        
        return redirect(auth_url)
    except Exception as e:
        print(f"[google_auth] エラー: {e}")
        import traceback
        traceback.print_exc()
        return f"認証URL生成エラー: {e}", 500


@app.route("/oauth2callback")
def oauth2callback():
    try:
        print("[oauth2callback] start")
        state = request.args.get("state")
        print(f"[oauth2callback] state: {state}")
        user_id = state or session.get("user_id")
        print(f"[oauth2callback] user_id: {user_id}")
        
        if not user_id:
            print("[oauth2callback] ERROR: user_id is None")
            return "認証エラー: user_idが取得できませんでした。", 400
        
        flow = Flow.from_client_secrets_file(
            "client_secrets.json",
            scopes=[
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/drive",
            ],
            state=state,
            redirect_uri=f"{get_base_url()}/oauth2callback",
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
                # セキュリティ: トークンの内容はログに出力しない
                print(
                    f"[oauth2callback] save_token呼び出し: user_id={user_id}, token_json_length={len(token_json)}"
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
                # datetime は先頭でインポート済み
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
    # グローバル変数を明示的に宣言
    global calendar_service, openai_service, task_service, multi_tenant_service
    
    try:
        signature = request.headers.get("X-Line-Signature", "")
        body_bytes = request.get_data()
        body_text = body_bytes.decode("utf-8") if body_bytes else ""
        try:
            data = json.loads(body_text) if body_text else {}
        except json.JSONDecodeError:
            print("[callback] 受信データのJSONデコードに失敗しました")
            data = {}

        destination = data.get("destination", "")
        default_line_bot_api = line_bot_api
        channel_secret = multi_tenant_service.get_channel_secret(destination) or os.getenv(
            "LINE_CHANNEL_SECRET", ""
        )

        if not channel_secret:
            print(f"[callback] チャネルシークレットが設定されていません: {destination}")
            return "Internal Server Error", 500

        if not validate_line_signature(body_bytes, signature, channel_secret):
            print("[callback] 署名検証に失敗しました")
            return "Invalid signature", 403

        print("受信:", data)
        if data:
            events = data.get("events", [])
            # マルチテナント対応: チャネルID別のLINE APIクライアントを取得
            base_line_bot_api = multi_tenant_service.get_messaging_api(destination)
            active_line_bot_api = base_line_bot_api or default_line_bot_api
            if not active_line_bot_api:
                print(f"[callback] チャネル設定が見つかりません: {destination}")
                return "OK", 200
            
            for event in events:
                if event.get("type") == "message" and "replyToken" in event:
                    reply_token = event["replyToken"]
                    user_message = event["message"]["text"]
                    print(f"[DEBUG] 受信user_message: '{user_message}'", flush=True)
                    user_id = event["source"].get("userId", "")

                    # ユーザーをデータベースに登録（初回メッセージ時）
                    from models.database import db

                    db.register_user(user_id)
                    
                    # ユーザーのチャネルIDを保存（マルチテナント対応）
                    if destination:
                        db.save_user_channel(user_id, destination)
                        print(f"[callback] ユーザー {user_id} のチャネルID {destination} を保存")

                    # ここで認証未済なら認証案内のみ返す
                    if not is_google_authenticated(user_id):
                        auth_url = get_google_auth_url(user_id)
                        reply_text = f"Googleカレンダー連携のため、まずこちらから認証をお願いします:\n{auth_url}"
                        active_line_bot_api.reply_message(
                            ReplyMessageRequest(
                                replyToken=reply_token,
                                messages=[TextMessage(text=reply_text)],
                            )
                        )
                        continue
                    # --- ここから下は認証済みユーザーのみ ---

                    # 緊急タスク追加モードフラグを最優先で判定
                    if check_flag_file(user_id, "urgent_task"):
                        print(f"[DEBUG] 緊急タスク追加モードフラグ検出: user_id={user_id}")
                        try:
                            task_info = task_service.parse_task_message(user_message)
                            task = task_service.create_task(user_id, task_info)
                            # 緊急タスクとして今日のスケジュールに追加
                            if is_google_authenticated(user_id):
                                try:
                                    from services.calendar_service import CalendarService
                                    import pytz
                                    
                                    calendar_service = CalendarService()
                                    
                                    # 今日の日付を取得（JST）
                                    jst = pytz.timezone('Asia/Tokyo')
                                    today = datetime.now(jst).replace(hour=0, minute=0, second=0, microsecond=0)
                                    
                                    # 最適な開始時刻を提案（空き時間ベース）
                                    optimal_time = calendar_service.suggest_optimal_time(user_id, task.duration_minutes, "urgent")
                                    
                                    if optimal_time:
                                        print(f"[DEBUG] 最適時刻を取得: {optimal_time.strftime('%H:%M')}")
                                        # 念のため重複チェック（空き時間から取得しているので通常は重複しない）
                                        if calendar_service.check_time_conflict(user_id, optimal_time, task.duration_minutes):
                                            print(f"[DEBUG] 最適時刻で重複検出: {optimal_time.strftime('%H:%M')}")
                                            # 空き時間から別の時刻を探す
                                            free_times = calendar_service.get_free_busy_times(user_id, today)
                                            alternative_times = []
                                            for ft in free_times:
                                                if ft['duration_minutes'] >= task.duration_minutes:
                                                    # 空き時間の開始時刻を試す
                                                    test_time = ft['start']
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

                            delete_flag_file(user_id, "urgent_task")
                            
                            # メニュー画面を表示
                            send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                            continue
                        except Exception as e:
                            print(f"[DEBUG] 緊急タスク追加エラー: {e}")
                            reply_text = f"⚠️ 緊急タスク追加中にエラーが発生しました: {e}"
                            active_line_bot_api.reply_message(
                                ReplyMessageRequest(
                                    replyToken=reply_token,
                                    messages=[TextMessage(text=reply_text)],
                                )
                            )
                            continue

                    # 未来タスク追加モードフラグを判定
                    if check_flag_file(user_id, "future_task"):
                        print(f"[DEBUG] 未来タスク追加モードフラグ検出: user_id={user_id}")
                        
                        # キャンセル処理を先に確認
                        cancel_words = ["キャンセル", "やめる", "中止", "戻る"]
                        normalized_message = user_message.strip().replace('　','').replace('\n','').lower()
                        if normalized_message in [w.lower() for w in cancel_words]:
                            delete_flag_file(user_id, "future_task")
                            reply_text = "❌ 未来タスク追加をキャンセルしました。\n\n何かお手伝いできることがあれば、お気軽にお声かけください！"
                            
                            # メニュー画面を表示
                            send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                            continue
                        
                        # まずパース処理を試行（単一行または複数行に対応）
                        parse_success = False
                        task_info = None
                        parse_error_msg = None
                        
                        try:
                            # 複数行の場合は最初の行のみをパース（複数行の処理は後で行う）
                            first_line = user_message.split('\n')[0].strip() if '\n' in user_message else user_message.strip()
                            task_info = task_service.parse_task_message(first_line)
                            # パースが成功し、タスク名と所要時間の両方が存在する場合
                            if task_info.get("name") and task_info.get("duration_minutes"):
                                print(f"[DEBUG] パース成功: {task_info}")
                                parse_success = True
                        except Exception as parse_error:
                            print(f"[DEBUG] パース失敗: {parse_error}")
                            parse_error_msg = str(parse_error)
                            parse_success = False
                        
                        # パースが成功した場合
                        if parse_success:
                            try:
                                created_count = 0
                                # 複数行対応：すべての改行コードに対応して分割
                                lines = [l.strip() for l in regex.split(r"[\r\n\u000B\u000C\u0085\u2028\u2029]+", user_message) if l.strip()]
                                if len(lines) > 1:
                                    # 複数タスクの場合は各行を処理
                                    for line in lines:
                                        info = task_service.parse_task_message(line)
                                        info["priority"] = "not_urgent_important"
                                        info["due_date"] = None
                                        task_service.create_future_task(user_id, info)
                                        created_count += 1
                                else:
                                    # 単一タスクの場合は最初にパースした情報を使用
                                    task_info["priority"] = "not_urgent_important"
                                    task_info["due_date"] = None
                                    task_service.create_future_task(user_id, task_info)
                                    created_count = 1

                                # フラグ削除
                                delete_flag_file(user_id, "future_task")
                                
                                # 未来タスク一覧を取得して表示
                                future_tasks = task_service.get_user_future_tasks(user_id)
                                reply_text = task_service.format_future_task_list(future_tasks, show_select_guide=False)
                                if created_count > 1:
                                    reply_text += f"\n\n✅ 未来タスクを{created_count}件追加しました！"
                                else:
                                    reply_text += "\n\n✅ 未来タスクを追加しました！"

                                # メニュー画面を表示
                                send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                                continue
                            except Exception as e:
                                print(f"[DEBUG] 未来タスク追加エラー: {e}")
                                # エラー時はモードを終了してメニューを表示
                                delete_flag_file(user_id, "future_task")
                                reply_text = f"⚠️ 未来タスク追加中にエラーが発生しました: {e}"

                                # メニュー画面を表示
                                send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                                continue
                        
                        # パースが失敗した場合：AIで意図を分類
                        else:
                            intent_result = openai_service.classify_user_intent(user_message)
                            intent = intent_result.get("intent", "other")
                            confidence = intent_result.get("confidence", 0.0)
                            
                            print(f"[DEBUG] 意図分類結果: {intent} (信頼度: {confidence})")
                            
                            # ヘルプ要求の処理
                            if intent == "help" and confidence > 0.7:
                                reply_text = """🔮 未来タスク追加モード

📝 正しい形式で送信してください：
・タスク名と所要時間の両方を記載
・例：「新規事業計画 2時間」
・例：「営業資料の見直し 1時間半」

⏰ 時間の表記例：
・「2時間」「1時間半」「30分」
・「2h」「1.5h」「30m」

❌ キャンセルする場合：
「キャンセル」「やめる」「中止」と送信してください。"""
                                active_line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue
                            
                            # 不完全なタスク依頼またはその他の場合：モードを終了してメニューを表示
                            else:
                                # モードを終了してメニューを表示
                                delete_flag_file(user_id, "future_task")
                                reply_text = """⚠️ タスクの情報が不完全です。

📝 正しい形式で送信してください：
・タスク名と所要時間の両方を記載
・例：「新規事業計画 2時間」
・例：「営業資料の見直し 1時間半」

⏰ 時間の表記例：
・「2時間」「1時間半」「30分」
・「2h」「1.5h」「30m」

もう一度、タスク名と所要時間を含めて送信してください。"""

                                # メニュー画面を表示
                                send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                                continue

                    # タスク追加モードフラグを判定
                    if check_flag_file(user_id, "add_task"):
                        print(f"[DEBUG] タスク追加モードフラグ検出: user_id={user_id}")
                        
                        # キャンセル処理を先に確認
                        cancel_words = ["キャンセル", "やめる", "中止", "戻る"]
                        normalized_message = user_message.strip().replace('　','').replace('\n','').lower()
                        if normalized_message in [w.lower() for w in cancel_words]:
                            delete_flag_file(user_id, "add_task")
                            reply_text = "❌ タスク追加をキャンセルしました。\n\n何かお手伝いできることがあれば、お気軽にお声かけください！"
                            
                            # メニュー画面を表示
                            send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                            continue
                        
                        # まずパース処理を試行（単一行または複数行に対応）
                        parse_success = False
                        task_info = None
                        
                        try:
                            # 複数行の場合は最初の行のみをパース（複数行の処理は後で行う）
                            first_line = user_message.split('\n')[0].strip() if '\n' in user_message else user_message.strip()
                            task_info = task_service.parse_task_message(first_line)
                            # パースが成功し、タスク名・所要時間・期限の全てが存在する場合
                            if task_info.get("name") and task_info.get("duration_minutes") and task_info.get("due_date"):
                                print(f"[DEBUG] パース成功: {task_info}")
                                parse_success = True
                            elif task_info.get("name") and task_info.get("duration_minutes"):
                                # タスク名と所要時間はあるが期限がない場合は不完全
                                print(f"[DEBUG] パース成功だが期限なし: {task_info}")
                                parse_success = False
                        except Exception as parse_error:
                            print(f"[DEBUG] パース失敗: {parse_error}")
                            parse_success = False
                        
                        # パースが成功した場合
                        if parse_success:
                            try:
                                # 改行がある場合は複数タスクとして処理
                                if '\n' in user_message:
                                    print(f"[DEBUG] 複数タスク検出: {user_message}")
                                    tasks_info = task_service.parse_multiple_tasks(user_message)
                                    created_tasks = []
                                    for task_info in tasks_info:
                                        task = task_service.create_task(user_id, task_info)
                                        created_tasks.append(task.name)

                                    delete_flag_file(user_id, "add_task")
                                    all_tasks = task_service.get_user_tasks(user_id)
                                    task_list_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                                    reply_text = f"✅ {len(created_tasks)}個のタスクを追加しました！\n\n{task_list_text}\n\nタスクの追加や削除があれば、いつでもお気軽にお声かけください！"
                                else:
                                    # 単一タスクの場合は最初にパースした情報を使用
                                    task = task_service.create_task(user_id, task_info)
                                    delete_flag_file(user_id, "add_task")
                                    all_tasks = task_service.get_user_tasks(user_id)
                                    task_list_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                                    reply_text = f"✅ タスクを追加しました！\n\n{task_list_text}\n\nタスクの追加や削除があれば、いつでもお気軽にお声かけください！"
                                
                                # メニュー画面を表示
                                from linebot.v3.messaging import FlexMessage, FlexContainer
                                flex_message_content = get_simple_flex_menu()
                                flex_container = FlexContainer.from_dict(flex_message_content)
                                flex_message = FlexMessage(
                                    alt_text="メニュー",
                                    contents=flex_container
                                )
                                
                                active_line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text), flex_message],
                                    )
                                )
                                continue
                            except Exception as e:
                                print(f"[DEBUG] タスク追加エラー: {e}")
                                # エラー時はモードを終了してメニューを表示
                                delete_flag_file(user_id, "add_task")
                                reply_text = f"⚠️ タスク追加中にエラーが発生しました: {e}"

                                # メニュー画面を表示
                                send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                                continue
                        
                        # パースが失敗した場合：AIで意図を分類
                        else:
                            intent_result = openai_service.classify_user_intent(user_message)
                            intent = intent_result.get("intent", "other")
                            confidence = intent_result.get("confidence", 0.0)
                            
                            print(f"[DEBUG] 意図分類結果: {intent} (信頼度: {confidence})")
                            
                            # ヘルプ要求の処理
                            if intent == "help" and confidence > 0.7:
                                reply_text = """📋 タスク追加モード

📝 正しい形式で送信してください：
・タスク名・所要時間・期限の3つが必要です
・例：「資料作成 2時間 明日」
・例：「会議準備 1時間半 明後日」

⏰ 時間の表記例：
・「2時間」「1時間半」「30分」
・「2h」「1.5h」「30m」

📅 期限の表記例：
・「今日」「明日」「明後日」
・「来週中」「来週末」など

❌ キャンセルする場合：
「キャンセル」「やめる」「中止」と送信してください。"""
                                active_line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue
                            
                            # 不完全なタスク依頼またはその他の場合：モードを終了してメニューを表示
                            else:
                                # モードを終了してメニューを表示
                                delete_flag_file(user_id, "add_task")
                                reply_text = """⚠️ タスクの情報が不完全です。

📝 正しい形式で送信してください：
・タスク名・所要時間・期限の3つが必要です
・例：「資料作成 2時間 明日」
・例：「会議準備 1時間半 明後日」

⏰ 時間の表記例：
・「2時間」「1時間半」「30分」
・「2h」「1.5h」「30m」

📅 期限の表記例：
・「今日」「明日」「明後日」
・「来週中」「来週末」など

もう一度、タスク名・所要時間・期限の3つを含めて送信してください。"""

                                # メニュー画面を表示
                                send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                                continue

                    try:
                        # 削除モード判定を追加
                        if check_flag_file(user_id, "delete"):
                            print(f"[DEBUG] 削除モード判定: user_id={user_id} 存在")
                            
                            # 削除モードでキャンセル処理
                            cancel_words = ["キャンセル", "やめる", "中止", "戻る"]
                            normalized_message = user_message.strip().replace('　','').replace('\n','').lower()
                            print(f"[DEBUG] 削除モードキャンセル判定: normalized_message='{normalized_message}'")
                            if normalized_message in [w.lower() for w in cancel_words]:
                                # 削除モードファイルを削除してモードをリセット
                                delete_flag_file(user_id, "delete")
                                print(f"[DEBUG] 削除モードリセット: user_id={user_id} 削除")
                                
                                reply_text = "❌ タスク削除をキャンセルしました。\n\n何かお手伝いできることがあれば、お気軽にお声かけください！"

                                # メニュー画面を表示
                                send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
                                continue
                            
                            # ユーザーの入力から削除対象タスクを抽出
                            # 例：「タスク 1、3」「未来タスク 2」「タスク 1、未来タスク 2」
                            import re
                            # AIで番号抽出
                            from services.openai_service import OpenAIService
                            openai_service = OpenAIService()
                            print(f"[DEBUG] AI抽出開始: 入力メッセージ='{user_message}'")
                            ai_result = openai_service.extract_task_numbers_from_message(user_message)
                            print(f"[DEBUG] AI抽出結果: {ai_result}")
                            if ai_result and (ai_result.get("tasks") or ai_result.get("future_tasks")):
                                task_numbers = [str(n) for n in ai_result.get("tasks", [])]
                                future_task_numbers = [str(n) for n in ai_result.get("future_tasks", [])]
                                print(f"[DEBUG] AI抽出成功: 通常タスク番号: {task_numbers}, 未来タスク番号: {future_task_numbers}")
                            else:
                                print(f"[DEBUG] AI抽出失敗、フォールバック処理に移行")
                                # 全角数字→半角数字へ変換
                                def z2h(s):
                                    return s.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
                                normalized_message = z2h(user_message)
                                
                                # 「タスク2.5」のような形式も処理
                                # まず「タスク」で始まる部分を抽出
                                task_match = re.search(r"タスク\s*([\d\.\,\、]+)", normalized_message)
                                if task_match:
                                    task_numbers = re.findall(r'\d+', task_match.group(1))
                                    print(f"[DEBUG] フォールバック抽出: タスク部分='{task_match.group(1)}', 抽出番号={task_numbers}")
                                else:
                                    task_numbers = re.findall(r"タスク\s*(\d+)", normalized_message)
                                    print(f"[DEBUG] フォールバック抽出: 通常パターン, 抽出番号={task_numbers}")
                                
                                # 未来タスクも同様に処理
                                future_match = re.search(r"未来タスク\s*([\d\.\,\、]+)", normalized_message)
                                if future_match:
                                    future_task_numbers = re.findall(r'\d+', future_match.group(1))
                                else:
                                    future_task_numbers = re.findall(r"未来タスク\s*(\d+)", normalized_message)
                                
                                print(f"[DEBUG] fallback: 通常タスク番号: {task_numbers}, 未来タスク番号: {future_task_numbers}")
                            all_tasks = task_service.get_user_tasks(user_id)
                            future_tasks = task_service.get_user_future_tasks(user_id)
                            deleted = []
                            
                            print(f"[DEBUG] 削除対象: 通常タスク番号={task_numbers}, 未来タスク番号={future_task_numbers}")
                            print(f"[DEBUG] 全タスク数: 通常={len(all_tasks)}, 未来={len(future_tasks)}")
                            
                            # 通常タスク削除（降順で削除してインデックスのずれを防ぐ）
                            task_numbers_sorted = sorted([int(num) for num in task_numbers], reverse=True)
                            print(f"[DEBUG] 通常タスク削除順序: {task_numbers_sorted}")
                            for num in task_numbers_sorted:
                                idx = num - 1
                                print(f"[DEBUG] タスク{num}削除試行: idx={idx}, 全タスク数={len(all_tasks)}")
                                if 0 <= idx < len(all_tasks):
                                    task = all_tasks[idx]
                                    print(f"[DEBUG] 削除対象タスク: {task.name} (ID: {task.task_id})")
                                    if task_service.delete_task(task.task_id):
                                        deleted.append(f"タスク {num}. {task.name}")
                                        print(f"[DEBUG] タスク削除成功: {num}. {task.name}")
                                    else:
                                        print(f"[DEBUG] タスク削除失敗: {num}. {task.name}")
                                else:
                                    print(f"[DEBUG] タスク{num}削除スキップ: インデックス範囲外 (idx={idx})")
                            
                            # 未来タスク削除（降順で削除してインデックスのずれを防ぐ）
                            future_task_numbers_sorted = sorted([int(num) for num in future_task_numbers], reverse=True)
                            for num in future_task_numbers_sorted:
                                idx = num - 1
                                if 0 <= idx < len(future_tasks):
                                    task = future_tasks[idx]
                                    if task_service.delete_future_task(task.task_id):
                                        deleted.append(f"未来タスク {num}. {task.name}")
                                        print(f"[DEBUG] 未来タスク削除成功: {num}. {task.name}")
                                    else:
                                        print(f"[DEBUG] 未来タスク削除失敗: {num}. {task.name}")
                            # 削除モードファイルを削除
                            delete_flag_file(user_id, "delete")
                            print(f"[DEBUG] 削除モードファイル削除: user_id={user_id}")
                            if deleted:
                                reply_text = "✅ タスクを削除しました！\n" + "\n".join(deleted)
                            else:
                                reply_text = "⚠️ 削除対象のタスクが見つかりませんでした。"
                            active_line_bot_api.reply_message(
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
                        # ただしモード中（未来/緊急/削除等）はここをスキップして各モードの処理へ委譲
                        from handlers.helpers import check_flag_file
                        future_mode_guard = check_flag_file(user_id, "future_task")
                        urgent_mode_guard = check_flag_file(user_id, "urgent_task")
                        delete_mode_guard = check_flag_file(user_id, "delete")
                        if user_message.strip() not in commands and not (future_mode_guard or urgent_mode_guard or delete_mode_guard):
                            print(f"[DEBUG] 自然言語タスク追加判定: '{user_message}' はコマンドではありません")
                            # 時間表現が含まれているかチェック（分、時間、半など）
                            time_patterns = ['分', '時間', '半', 'hour', 'min', 'minute']
                            has_time = any(pattern in user_message for pattern in time_patterns)
                            
                            if has_time:
                                print(f"[DEBUG] 時間表現検出: '{user_message}' をタスク追加として処理します")
                                try:
                                    # 改行がある場合は複数タスクとして処理
                                    if '\n' in user_message:
                                        print(f"[DEBUG] 自然言語複数タスク検出: {user_message}")
                                        tasks_info = task_service.parse_multiple_tasks(user_message)
                                        created_tasks = []
                                        for task_info in tasks_info:
                                            task = task_service.create_task(user_id, task_info)
                                            created_tasks.append(task.name)
                                        
                                        all_tasks = task_service.get_user_tasks(user_id)
                                        task_list_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                                        reply_text = f"✅ {len(created_tasks)}個のタスクを追加しました！\n\n{task_list_text}\n\nタスクの追加や削除があれば、いつでもお気軽にお声かけください！"
                                    else:
                                        # 単一タスクとして処理
                                        task_info = task_service.parse_task_message(user_message)
                                        task = task_service.create_task(user_id, task_info)
                                        all_tasks = task_service.get_user_tasks(user_id)
                                        task_list_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                                        reply_text = f"✅ タスクを追加しました！\n\n{task_list_text}\n\nタスクの追加や削除があれば、いつでもお気軽にお声かけください！"
                                    
                                    # メニュー画面を表示
                                    from linebot.v3.messaging import FlexMessage, FlexContainer
                                    flex_message_content = get_simple_flex_menu()
                                    flex_container = FlexContainer.from_dict(flex_message_content)
                                    flex_message = FlexMessage(
                                        alt_text="メニュー",
                                        contents=flex_container
                                    )
                                    
                                    active_line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text), flex_message],
                                        )
                                    )
                                    continue
                                except Exception as e:
                                    print(f"[DEBUG] 自然言語タスク追加エラー: {e}")
                                    # エラーの場合は通常のFlexMessageメニューを表示
                                    pass

                        # タスク選択処理を先に実行（数字入力の場合）
                        print(
                            f"[DEBUG] タスク選択フラグ確認: user_id={user_id}, exists={check_flag_file(user_id, 'task_select')}"
                        )
                        
                        # タスク選択モードでキャンセル処理
                        if check_flag_file(user_id, "task_select"):
                            cancel_words = ["キャンセル", "やめる", "中止", "戻る"]
                            normalized_message = user_message.strip().replace('　','').replace('\n','').lower()
                            print(f"[DEBUG] タスク選択キャンセル判定: normalized_message='{normalized_message}'")
                            if normalized_message in [w.lower() for w in cancel_words]:
                                handle_task_selection_cancel(active_line_bot_api, reply_token, user_id, get_simple_flex_menu)
                                continue
                        # AIによる数字入力判定を試行
                        is_number_input = False
                        try:
                            ai_result = openai_service.extract_task_numbers_from_message(user_message)
                            if ai_result and ("tasks" in ai_result or "future_tasks" in ai_result):
                                is_number_input = True
                                print(f"[DEBUG] AI判定結果: 数字入力として認識")
                            else:
                                # AI判定に失敗した場合は従来の判定を実行
                                is_number_input = (
                                    user_message.strip().isdigit() or  # 整数
                                    ("," in user_message or "、" in user_message) or  # カンマ区切り
                                    (user_message.strip().replace(".", "").isdigit() and "." in user_message)  # 小数点付き
                                )
                        except Exception as e:
                            print(f"[DEBUG] AI判定エラー: {e}")
                            # エラーの場合は従来の判定を実行
                            is_number_input = (
                                user_message.strip().isdigit() or  # 整数
                                ("," in user_message or "、" in user_message) or  # カンマ区切り
                                (user_message.strip().replace(".", "").isdigit() and "." in user_message)  # 小数点付き
                            )
                        
                        if is_number_input:
                            if check_flag_file(user_id, "task_select"):
                                print(f"[DEBUG] タスク選択フラグ検出: user_id={user_id}")
                                print(
                                    f"[DEBUG] タスク選択処理開始: user_message='{user_message}'"
                                )
                                try:
                                    # 選択モードを先に判定（display_tasksの作成方法を決めるため）
                                    flag_data = load_flag_data(user_id, "task_select")
                                    mode_content = ""
                                    flag_timestamp = None
                                    target_date_str = None

                                    if flag_data:
                                        mode = flag_data.get("mode", "")
                                        flag_timestamp = flag_data.get("timestamp")
                                        target_date_str = flag_data.get("target_date")
                                        # mode=schedule の形式に変換
                                        if mode:
                                            mode_content = f"mode={mode}"
                                    else:
                                        print(f"[DEBUG] フラグデータの読み込みに失敗しました")
                                        mode_content = ""

                                    is_schedule_mode = "mode=schedule" in mode_content
                                    is_future_schedule_mode = "mode=future_schedule" in mode_content
                                    is_complete_mode = "mode=complete" in mode_content
                                    print(f"[DEBUG] 選択モード: {'future_schedule' if is_future_schedule_mode else ('schedule' if is_schedule_mode else ('complete' if is_complete_mode else 'unknown'))}, フラグ作成時刻: {flag_timestamp}")
                                    
                                    # datetime は先頭でインポート済み
                                    import pytz
                                    jst = pytz.timezone('Asia/Tokyo')
                                    today = datetime.now(jst)
                                    today_str = today.strftime('%Y-%m-%d')
                                    effective_today_str = target_date_str or today_str
                                    print(f"[DEBUG] 今日の日付文字列: {today_str}, target_date_str: {target_date_str}, effective_today_str: {effective_today_str}")
                                    
                                    all_tasks = task_service.get_user_tasks(user_id)
                                    print(f"[DEBUG] 全タスク取得: {len(all_tasks)}件, タスク一覧={[(i+1, t.name, t.due_date) for i, t in enumerate(all_tasks)]}")
                                    
                                    # 削除モード（夜の通知）の場合は、通知と同じ方法で今日のタスクを取得
                                    if is_complete_mode:
                                        # 通知と同じ方法で今日のタスクを取得（単純なフィルタリング）
                                        # デバッグ: 各タスクのdue_dateとtoday_strを比較
                                        for t in all_tasks:
                                            due_date_str = str(t.due_date) if t.due_date else None
                                            match = (t.due_date == effective_today_str) if t.due_date else False
                                            print(f"[DEBUG] タスク比較: name={t.name}, due_date={due_date_str}, type={type(t.due_date)}, match={match}")
                                        if effective_today_str:
                                            display_tasks = [t for t in all_tasks if t.due_date and str(t.due_date) == effective_today_str]
                                        else:
                                            display_tasks = [t for t in all_tasks if t.due_date and str(t.due_date) == today_str]
                                        print(f"[DEBUG] 削除モード: 今日のタスク数={len(display_tasks)}, タスク一覧={[(i+1, t.name) for i, t in enumerate(display_tasks)]}")
                                    else:
                                        # スケジュールモード（朝の通知）の場合は、format_task_listと同じソート順序を適用
                                        def sort_key(task):
                                            priority_order = {
                                                "urgent_important": 0,
                                                "not_urgent_important": 1,
                                                "urgent_not_important": 2,
                                                "normal": 3
                                            }
                                            priority_score = priority_order.get(task.priority, 3)
                                            due_date = task.due_date or '9999-12-31'
                                            return (priority_score, due_date, task.name)
                                        
                                        # 優先度と期日でソート
                                        from collections import defaultdict
                                        tasks_sorted = sorted(all_tasks, key=sort_key)
                                        print(f"[DEBUG] ソート後タスク数: {len(tasks_sorted)}件")
                                        
                                        # format_task_listと同じ順序でタスクを取得
                                        # 期日ごとにグループ化（format_task_listと同じロジック）
                                        grouped = defaultdict(list)
                                        for task in tasks_sorted:
                                            grouped[task.due_date or '未設定'].append(task)
                                        print(f"[DEBUG] グループ化後: {len(grouped)}グループ")
                                        
                                        # 期日の順序を正確に再現（format_task_listと同じ）
                                        due_order = []
                                        for due, group in sorted(grouped.items()):
                                            if due == today_str:
                                                due_order.append(('本日まで', due, group))
                                            elif due != '未設定':
                                                try:
                                                    y, m, d = due.split('-')
                                                    due_date_obj = datetime(int(y), int(m), int(d))
                                                    weekday_names = ['月', '火', '水', '木', '金', '土', '日']
                                                    weekday = weekday_names[due_date_obj.weekday()]
                                                    due_str = f"{int(m)}月{int(d)}日({weekday})"
                                                    due_order.append((due_str, due, group))
                                                except Exception:
                                                    due_order.append((due, due, group))
                                            else:
                                                due_order.append(('期日未設定', due, group))
                                        
                                        # 表示順序と同じタスクリストを作成
                                        display_tasks = []
                                        for due_str, due, group in due_order:
                                            display_tasks.extend(group)
                                        
                                        print(f"[DEBUG] スケジュールモード: タスク数={len(display_tasks)}, タスク一覧={[(i+1, t.name) for i, t in enumerate(display_tasks)]}")
                                    
                                    # display_tasksが空の場合のデバッグ
                                    if not display_tasks:
                                        print(f"[DEBUG] 警告: display_tasksが空です！ all_tasks={len(all_tasks)}, is_complete_mode={is_complete_mode}, is_schedule_mode={is_schedule_mode}, is_future_schedule_mode={is_future_schedule_mode}, mode_content='{mode_content}'")
                                    
                                    # AIによる数字解析を試行
                                    selected_numbers = []
                                    try:
                                        ai_result = openai_service.extract_task_numbers_from_message(user_message)
                                        if ai_result and "tasks" in ai_result:
                                            selected_numbers = ai_result["tasks"]
                                            print(f"[DEBUG] AI解析結果: {ai_result}")
                                        else:
                                            print(f"[DEBUG] AI解析失敗、従来の処理を実行")
                                            # AI解析に失敗した場合は従来の処理を実行
                                            if "," in user_message or "、" in user_message:
                                                selected_numbers = [
                                                    int(n.strip())
                                                    for n in user_message.replace("、", ",").replace("，", ",").split(
                                                        ","
                                                    )
                                                    if n.strip().isdigit()
                                                ]
                                            elif "." in user_message:
                                                parts = user_message.split(".")
                                                for part in parts:
                                                    if part.strip().isdigit():
                                                        selected_numbers.append(int(part.strip()))
                                            else:
                                                if user_message.strip().isdigit():
                                                    selected_numbers.append(int(user_message.strip()))
                                    except Exception as e:
                                        print(f"[DEBUG] AI解析エラー: {e}")
                                        # エラーの場合は従来の処理を実行
                                        if "," in user_message or "、" in user_message:
                                            selected_numbers = [
                                                int(n.strip())
                                                for n in user_message.replace("、", ",").replace("，", ",").split(
                                                    ","
                                                )
                                                if n.strip().isdigit()
                                            ]
                                        elif "." in user_message:
                                            parts = user_message.split(".")
                                            for part in parts:
                                                if part.strip().isdigit():
                                                    selected_numbers.append(int(part.strip()))
                                        else:
                                            if user_message.strip().isdigit():
                                                selected_numbers.append(int(user_message.strip()))
                                    if not selected_numbers:
                                        reply_text = "⚠️ 有効な数字を入力してください。\n例: 1、2、3"
                                        active_line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                        continue
                                    
                                    # デバッグ情報を追加
                                    print(f"[DEBUG] 選択された数字: {selected_numbers}")
                                    print(f"[DEBUG] ソート済みタスク数: {len(display_tasks)}")
                                    print(f"[DEBUG] ソート済みタスク一覧: {[(i+1, task.name) for i, task in enumerate(display_tasks)]}")
                                    
                                    selected_tasks = []
                                    for num in selected_numbers:
                                        idx = num - 1
                                        if 0 <= idx < len(display_tasks):
                                            selected_tasks.append(display_tasks[idx])
                                            print(
                                                f"[DEBUG] タスク選択: 番号={num}, インデックス={idx}, タスク名={display_tasks[idx].name}"
                                            )
                                        else:
                                            print(
                                                f"[DEBUG] タスク選択エラー: 番号={num}, インデックス={idx}, 最大インデックス={len(display_tasks)-1}"
                                            )
                                    if not selected_tasks:
                                        # より詳細なエラーメッセージを提供
                                        if display_tasks:
                                            available_numbers = list(range(1, len(display_tasks) + 1))
                                            reply_text = (
                                                f"⚠️ 選択されたタスクが見つかりませんでした。\n\n"
                                                f"選択可能な番号: {', '.join(map(str, available_numbers))}\n"
                                                f"入力された番号: {', '.join(map(str, selected_numbers))}"
                                            )
                                        else:
                                            # display_tasksが空の場合の特別なエラーメッセージ
                                            reply_text = (
                                                f"⚠️ エラーが発生しました。\n\n"
                                                f"タスク一覧を取得できませんでした。\n"
                                                f"入力された番号: {', '.join(map(str, selected_numbers))}\n\n"
                                                f"もう一度「タスク一覧」と送信して、タスク一覧を確認してください。"
                                            )
                                            print(f"[DEBUG] エラー: display_tasksが空です。all_tasks={len(all_tasks)}, mode_content='{mode_content}'")
                                        active_line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                        continue

                                    if is_schedule_mode or is_future_schedule_mode:
                                        # スケジュール提案フロー（朝）
                                        # future_schedule の場合は未来タスクから再マッピング
                                        if is_future_schedule_mode:
                                            try:
                                                future_tasks_list = task_service.get_user_future_tasks(user_id)
                                                remapped_selected_tasks = []
                                                for num in selected_numbers:
                                                    idx = num - 1
                                                    if 0 <= idx < len(future_tasks_list):
                                                        remapped_selected_tasks.append(future_tasks_list[idx])
                                                if remapped_selected_tasks:
                                                    selected_tasks = remapped_selected_tasks
                                            except Exception as _e:
                                                pass

                                        print(f"[DEBUG] スケジュール提案開始: {len(selected_tasks)}個のタスク")
                                        print(f"[DEBUG] 選択されたタスク詳細: {[(i+1, task.name, task.duration_minutes) for i, task in enumerate(selected_tasks)]}")
                                        jst = pytz.timezone('Asia/Tokyo')
                                        today = datetime.now(jst)
                                        if is_future_schedule_mode:
                                            # 来週のスケジュール提案の場合：来週の月曜日から7日間の空き時間を取得
                                            # 来週の月曜日を計算（月曜日は0）
                                            days_until_next_monday = (0 - today.weekday() + 7) % 7
                                            if days_until_next_monday == 0:
                                                days_until_next_monday = 7  # 今日が月曜日の場合は1週間後
                                            next_week_monday = today + timedelta(days=days_until_next_monday)
                                            next_week_monday = next_week_monday.replace(hour=0, minute=0, second=0, microsecond=0)
                                            # タイムゾーン情報が保持されていることを確認
                                            print(f"[DEBUG] 来週の月曜日計算: 今日={today.strftime('%Y-%m-%d %A')}, 来週月曜日={next_week_monday.strftime('%Y-%m-%d %A')}, タイムゾーン={next_week_monday.tzinfo}")
                                            free_times = calendar_service.get_week_free_busy_times(user_id, next_week_monday)
                                            print(f"[DEBUG] 来週の空き時間取得: 開始日={next_week_monday.strftime('%Y-%m-%d %A')}, 取得数={len(free_times)}")
                                        else:
                                            # 今日のスケジュール提案の場合：今日の空き時間を取得
                                            free_times = calendar_service.get_free_busy_times(user_id, today)
                                        if free_times:
                                            week_info = "来週" if is_future_schedule_mode else ""
                                            base_date = next_week_monday if is_future_schedule_mode else today
                                            proposal = openai_service.generate_schedule_proposal(
                                                selected_tasks,
                                                free_times,
                                                week_info=week_info,
                                                base_date=base_date
                                            )
                                            schedule_proposal_file = f"schedule_proposal_{user_id}.txt"
                                            with open(schedule_proposal_file, "w", encoding="utf-8") as f:
                                                f.write(proposal)
                                            selected_tasks_file = f"selected_tasks_{user_id}.json"
                                            with open(selected_tasks_file, "w", encoding="utf-8") as f:
                                                json.dump([task.task_id for task in selected_tasks], f, ensure_ascii=False)
                                            # proposalに既にタイトルが含まれている場合は追加しない
                                            if "【来週のスケジュール提案】" in proposal or "【本日のスケジュール提案】" in proposal or "【今日のスケジュール提案】" in proposal:
                                                reply_text = proposal
                                            else:
                                                header = "【来週のスケジュール提案】" if is_future_schedule_mode else "【今日のスケジュール提案】"
                                                reply_text = f"{header}\n\n{proposal}"
                                            # スケジュールに含まれなかったタスクを追記
                                            missing_tasks = []
                                            normalized_reply_text = reply_text
                                            for task in selected_tasks:
                                                if task.name not in normalized_reply_text:
                                                    missing_tasks.append(task)
                                            if missing_tasks:
                                                missing_section_lines = ["━━━━━━━━━━━━━━", "🟡未割り当てタスク"]
                                                for task in missing_tasks:
                                                    missing_section_lines.append(f"・{task.name}（{task.duration_minutes}分）")
                                                missing_section = "\n".join(missing_section_lines)
                                                if "✅理由・まとめ" in reply_text:
                                                    reply_text = reply_text.replace("✅理由・まとめ", f"{missing_section}\n━━━━━━━━━━━━━━\n✅理由・まとめ", 1)
                                                else:
                                                    reply_text = f"{reply_text}\n{missing_section}"
                                        else:
                                            base_date = next_week_monday if is_future_schedule_mode else today
                                            week_info = "来週" if is_future_schedule_mode else ""
                                            fallback_proposal = openai_service.generate_schedule_proposal(
                                                selected_tasks,
                                                [],
                                                week_info=week_info,
                                                base_date=base_date
                                            )
                                            if fallback_proposal:
                                                reply_text = fallback_proposal
                                            else:
                                                reply_text = "⚠️ 空き時間が見つかりませんでした。\n手動でスケジュールを調整してください。"
                                    else:
                                        # 完了（削除確認）フロー（夜）
                                        print(f"[DEBUG] タスク削除開始: {len(selected_tasks)}個のタスク")
                                        task_names = [task.name for task in selected_tasks]
                                        reply_text = f"以下のタスクを削除しますか？\n\n"
                                        for i, name in enumerate(task_names, 1):
                                            reply_text += f"{i}. {name}\n"
                                        reply_text += "\n削除する場合は「はい」、キャンセルする場合は「キャンセル」と送信してください。"
                                        selected_tasks_file = f"selected_tasks_{user_id}.json"
                                        with open(selected_tasks_file, "w", encoding="utf-8") as f:
                                            json.dump([task.task_id for task in selected_tasks], f, ensure_ascii=False)

                                    # フラグ削除と送信
                                    delete_flag_file(user_id, "task_select")
                                    print(f"[DEBUG] タスク選択モードフラグ削除完了: user_id={user_id}")
                                    print(f"[DEBUG] 選択結果送信開始: {reply_text[:100]}...")
                                    active_line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    print(f"[DEBUG] 選択結果送信完了")
                                    continue
                                except Exception as e:
                                    print(f"[DEBUG] タスク選択処理エラー: {e}")
                                    reply_text = (
                                        "⚠️ タスク選択処理中にエラーが発生しました。"
                                    )
                                    active_line_bot_api.reply_message(
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
                                handle_task_add_command(active_line_bot_api, reply_token, user_id)
                                continue
                            elif user_message.strip() == "緊急タスク追加":
                                handle_urgent_task_add_command(active_line_bot_api, reply_token, user_id, is_google_authenticated, get_google_auth_url)
                                continue
                            elif user_message.strip() == "未来タスク追加":
                                handle_future_task_add_command(active_line_bot_api, reply_token, user_id)
                                continue
                            # ここで他のコマンド分岐（elif ...）をそのまま残す
                            # 既存のelse:（未登録コマンド分岐）は削除
                        else:
                            print(f"[DEBUG] else節（未登録コマンド分岐）到達: '{user_message}' - FlexMessageボタンメニューを返します")
                            print("[DEBUG] Flex送信直前")
                            button_message_sent = send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, user_id=user_id)
                            if button_message_sent:
                                print("[DEBUG] FlexMessage送信成功")
                            else:
                                print("[DEBUG] ボタンメニュー送信に失敗しました")
                            print("[DEBUG] Flex送信後")
                            continue

                        # タスク削除コマンドの処理
                        if user_message.strip() == "タスク削除":
                            handle_task_delete_command(active_line_bot_api, reply_token, user_id, task_service)
                            continue
                        elif user_message.strip() == "はい":
                            import os

                            # まずスケジュール提案ファイルをチェック
                            schedule_proposal_file = f"schedule_proposal_{user_id}.txt"
                            if os.path.exists(schedule_proposal_file):
                                # スケジュール提案が存在する場合、「承認する」と同じ処理を実行
                                try:
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

                                            # 未来タスクは残す（削除しない）
                                            print(
                                                f"[DEBUG] 未来タスクを通常タスクに変換（未来タスクは保持）: {future_task.name} -> {converted_task.task_id}"
                                            )

                                        # カレンダーに追加
                                        success_count = 0

                                        # 未来タスクがある場合は来週の日付で処理
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

                                        # スケジュール提案に「来週のスケジュール提案」が含まれているかチェック
                                        is_future_schedule_proposal = "来週のスケジュール提案" in proposal
                                        
                                        # 未来タスクの場合は来週のスケジュール、通常タスクの場合は今日のスケジュールを表示
                                        if selected_future_tasks or is_future_schedule_proposal:
                                            # 来週のスケジュール提案の場合：来週の最初の日（次の週の月曜日）を計算
                                            today = datetime.now(jst)
                                            # 来週の月曜日を計算（月曜日は0）
                                            days_until_next_monday = (0 - today.weekday() + 7) % 7
                                            if days_until_next_monday == 0:
                                                days_until_next_monday = 7  # 今日が月曜日の場合は1週間後
                                            next_week_monday = today + timedelta(days=days_until_next_monday)
                                            schedule_date = next_week_monday.replace(hour=0, minute=0, second=0, microsecond=0)
                                            week_schedule = (
                                                calendar_service.get_week_schedule(
                                                    user_id, schedule_date
                                                )
                                            )
                                            date_label = f"📅 来週のスケジュール ({schedule_date.strftime('%m/%d')}〜):"
                                            print(
                                                f"[DEBUG] 来週のスケジュール取得結果: {len(week_schedule)}日分, 開始日={schedule_date.strftime('%Y-%m-%d')}"
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

                                        if selected_future_tasks or is_future_schedule_proposal:
                                            # 来週のスケジュール提案の場合：来週全体のスケジュールを表示
                                            if week_schedule:
                                                reply_text += date_label + "\n"
                                                reply_text += "━━━━━━━━━━━━━━\n"
                                                # datetime は先頭でインポート済み

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
                                                # datetime は先頭でインポート済み

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
                                        
                                        # メニュー画面を表示
                                        from linebot.v3.messaging import FlexMessage, FlexContainer
                                        flex_message_content = get_simple_flex_menu()
                                        flex_container = FlexContainer.from_dict(flex_message_content)
                                        flex_message = FlexMessage(
                                            alt_text="メニュー",
                                            contents=flex_container
                                        )
                                        
                                        active_line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text), flex_message],
                                            )
                                        )
                                    else:
                                        reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
                                        active_line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                except Exception as e:
                                    print(f"[ERROR] 承認処理（はいコマンド）: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    reply_text = f"⚠️ スケジュール承認中にエラーが発生しました: {e}"
                                    active_line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                continue
                            
                            # スケジュール提案がない場合の従来の削除処理
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
                                        active_line_bot_api.reply_message(
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
                                    
                                    # メニュー画面を表示
                                    from linebot.v3.messaging import FlexMessage, FlexContainer
                                    flex_message_content = get_simple_flex_menu()
                                    flex_container = FlexContainer.from_dict(flex_message_content)
                                    flex_message = FlexMessage(
                                        alt_text="メニュー",
                                        contents=flex_container
                                    )
                                    
                                    active_line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text), flex_message],
                                        )
                                    )
                                    continue

                                except Exception as e:
                                    print(f"[DEBUG] はいコマンド削除処理エラー: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    reply_text = f"⚠️ タスク削除中にエラーが発生しました: {e}"
                                    active_line_bot_api.reply_message(
                                        ReplyMessageRequest(
                                            replyToken=reply_token,
                                            messages=[TextMessage(text=reply_text)],
                                        )
                                    )
                                    continue
                            else:
                                reply_text = "⚠️ 先にタスクを選択してください。"
                                active_line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                            continue
                        elif user_message.strip() == "8時テスト":
                            handle_8am_test(active_line_bot_api, reply_token, user_id, notification_service)
                            continue
                        elif user_message.strip() == "21時テスト":
                            handle_9pm_test(active_line_bot_api, reply_token, user_id, notification_service)
                            continue
                        elif user_message.strip() == "日曜18時テスト":
                            handle_sunday_6pm_test(active_line_bot_api, reply_token, user_id, notification_service)
                            continue
                        elif user_message.strip() == "スケジューラー確認":
                            handle_scheduler_check(active_line_bot_api, reply_token, user_id, notification_service)
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

                                            # 未来タスクは残す（削除しない）
                                            print(
                                                f"[DEBUG] 未来タスクを通常タスクに変換（未来タスクは保持）: {future_task.name} -> {converted_task.task_id}"
                                            )

                                        # カレンダーに追加
                                        success_count = 0

                                        # 未来タスクがある場合は来週の日付で処理
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

                                        # スケジュール提案に「来週のスケジュール提案」が含まれているかチェック
                                        is_future_schedule_proposal = "来週のスケジュール提案" in proposal
                                        
                                        # 未来タスクの場合は来週のスケジュール、通常タスクの場合は今日のスケジュールを表示
                                        if selected_future_tasks or is_future_schedule_proposal:
                                            # 来週のスケジュール提案の場合：来週の最初の日（次の週の月曜日）を計算
                                            today = datetime.now(jst)
                                            # 来週の月曜日を計算（月曜日は0）
                                            days_until_next_monday = (0 - today.weekday() + 7) % 7
                                            if days_until_next_monday == 0:
                                                days_until_next_monday = 7  # 今日が月曜日の場合は1週間後
                                            next_week_monday = today + timedelta(days=days_until_next_monday)
                                            schedule_date = next_week_monday.replace(hour=0, minute=0, second=0, microsecond=0)
                                            week_schedule = (
                                                calendar_service.get_week_schedule(
                                                    user_id, schedule_date
                                                )
                                            )
                                            date_label = f"📅 来週のスケジュール ({schedule_date.strftime('%m/%d')}〜):"
                                            print(
                                                f"[DEBUG] 来週のスケジュール取得結果: {len(week_schedule)}日分, 開始日={schedule_date.strftime('%Y-%m-%d')}"
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

                                        if selected_future_tasks or is_future_schedule_proposal:
                                            # 来週のスケジュール提案の場合：来週全体のスケジュールを表示
                                            if week_schedule:
                                                reply_text += date_label + "\n"
                                                reply_text += "━━━━━━━━━━━━━━\n"
                                                # datetime は先頭でインポート済み

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
                                                # datetime は先頭でインポート済み

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
                                        
                                        # メニュー画面を表示
                                        from linebot.v3.messaging import FlexMessage, FlexContainer
                                        flex_message_content = get_simple_flex_menu()
                                        flex_container = FlexContainer.from_dict(flex_message_content)
                                        flex_message = FlexMessage(
                                            alt_text="メニュー",
                                            contents=flex_container
                                        )
                                        
                                        active_line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text), flex_message],
                                            )
                                        )
                                    else:
                                        reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
                                        active_line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                else:
                                    reply_text = (
                                        "⚠️ スケジュール提案が見つかりませんでした。"
                                    )
                                    active_line_bot_api.reply_message(
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
                                active_line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                            continue
                        elif user_message.strip() == "修正する":
                            try:
                                # 現在のモードを判定
                                current_mode = "schedule"  # デフォルト

                                # フラグデータベースから現在のモードを読み取り
                                flag_data = load_flag_data(user_id, "task_select")
                                if flag_data:
                                    current_mode = flag_data.get("mode", "schedule")
                                    print(f"[修正処理] フラグデータを読み取り: mode={current_mode}")
                                else:
                                    print(f"[修正処理] フラグデータが見つかりません、デフォルトモード使用")
                                
                                # 未来タスク選択モードファイルの存在も確認（ただし、フラグファイルで既に判定済みの場合はスキップ）
                                if current_mode == "schedule":  # デフォルトの場合は追加確認
                                    future_selection_file = f"future_task_selection_{user_id}.json"
                                    if os.path.exists(future_selection_file):
                                        # 未来タスク選択モードファイルの内容を確認
                                        try:
                                            with open(future_selection_file, "r", encoding="utf-8") as f:
                                                future_mode_data = json.load(f)
                                                if future_mode_data.get("mode") == "future_schedule":
                                                    print(f"[修正処理] 未来タスク選択モードファイル内容確認: {future_mode_data}")
                                                    current_mode = "future_schedule"
                                                else:
                                                    print(f"[修正処理] 未来タスク選択モードファイル存在するが内容が異なる: {future_mode_data}")
                                        except Exception as e:
                                            print(f"[修正処理] 未来タスク選択モードファイル読み取りエラー: {e}")
                                            # ファイルが存在する場合は未来タスクモードと判定
                                            current_mode = "future_schedule"
                                
                                # スケジュール提案ファイルの内容も確認
                                schedule_proposal_file = f"schedule_proposal_{user_id}.txt"
                                if os.path.exists(schedule_proposal_file):
                                    try:
                                        with open(schedule_proposal_file, "r", encoding="utf-8") as f:
                                            proposal_content = f.read()
                                            if "来週のスケジュール提案" in proposal_content:
                                                print(f"[修正処理] 来週のスケジュール提案を検出")
                                                current_mode = "future_schedule"
                                            elif "本日のスケジュール提案" in proposal_content:
                                                print(f"[修正処理] 本日のスケジュール提案を検出")
                                                current_mode = "schedule"
                                    except Exception as e:
                                        print(f"[修正処理] スケジュール提案ファイル読み取りエラー: {e}")
                                
                                print(f"[修正処理] 現在のモード: {current_mode}")
                                
                                if current_mode == "future_schedule":
                                    # 未来タスク選択モードの場合：来週のタスク選択画面に戻る
                                    future_tasks = task_service.get_user_future_tasks(user_id)
                                    reply_text = task_service.format_future_task_list(future_tasks, show_select_guide=True)
                                    print(f"[修正処理] 未来タスク選択画面に戻る")
                                else:
                                    # 通常タスク選択モードの場合：今日のタスク選択画面に戻る
                                    all_tasks = task_service.get_user_tasks(user_id)
                                    morning_guide = "今日やるタスクを選んでください！\n例：１、３、５"
                                    reply_text = task_service.format_task_list(all_tasks, show_select_guide=True, guide_text=morning_guide)
                                    print(f"[修正処理] 今日のタスク選択画面に戻る")

                                    # 今日のタスク選択モードに戻るため、フラグを更新
                                    create_flag_file(user_id, "task_select", {"mode": "schedule"})
                                    print(f"[修正処理] 今日のタスク選択モードフラグ更新: user_id={user_id}")

                                active_line_bot_api.reply_message(
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
                                active_line_bot_api.reply_message(
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
                                active_line_bot_api.reply_message(
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
                            active_line_bot_api.reply_message(
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
                        # datetime は先頭でインポート済み

                        urgent_mode_file = f"urgent_task_mode_{user_id}.json"
                        print(
                            f"[DEBUG] 緊急タスク追加モードファイル確認: {urgent_mode_file}, exists={os.path.exists(urgent_mode_file)}"
                        )
                        if os.path.exists(urgent_mode_file):
                            print(f"[DEBUG] 緊急タスク追加モードフラグ検出: {urgent_mode_file}")
                            try:
                                task_info = task_service.parse_task_message(user_message)
                                task_info["priority"] = "urgent_not_important"
                                # datetime は先頭でインポート済み
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
                                
                                # メニュー画面を表示
                                from linebot.v3.messaging import FlexMessage, FlexContainer
                                flex_message_content = get_simple_flex_menu()
                                flex_container = FlexContainer.from_dict(flex_message_content)
                                flex_message = FlexMessage(
                                    alt_text="メニュー",
                                    contents=flex_container
                                )
                                
                                active_line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text), flex_message],
                                    )
                                )
                                continue
                            except Exception as e:
                                print(f"[DEBUG] 緊急タスク追加エラー: {e}")
                                reply_text = f"⚠️ 緊急タスク追加中にエラーが発生しました: {e}"
                                active_line_bot_api.reply_message(
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
                                created_count = 0
                                created_names = []
                                # 改行区切りで複数登録に対応（全改行コード対応）
                                try:
                                    print(f"[DEBUG] 未来タスク入力repr: {repr(user_message)}")
                                except Exception:
                                    pass
                                lines = [l.strip() for l in regex.split(r"[\r\n\u000B\u000C\u0085\u2028\u2029]+", user_message) if l.strip()]
                                print(f"[DEBUG] 未来タスク行数判定: {len(lines)}")
                                if len(lines) > 1:
                                    for line in lines:
                                        info = task_service.parse_task_message(line)
                                        info["priority"] = "not_urgent_important"
                                        info["due_date"] = None
                                        task = task_service.create_future_task(user_id, info)
                                        created_count += 1
                                        created_names.append(task.name)
                                else:
                                    # 単一登録
                                    task_info = task_service.parse_task_message(user_message.strip())
                                    task_info["priority"] = "not_urgent_important"
                                    task_info["due_date"] = None
                                    task = task_service.create_future_task(user_id, task_info)
                                    created_count = 1
                                    created_names = [task.name]
                                print(f"[DEBUG] 未来タスク作成完了: {created_count}件, names={created_names}")

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
                                if created_count > 1:
                                    reply_text += f"\n\n✅ 未来タスクを{created_count}件追加しました！"
                                else:
                                    reply_text += "\n\n✅ 未来タスクを追加しました！"

                                # 未来タスク追加モードファイルを削除
                                if os.path.exists(future_mode_file):
                                    os.remove(future_mode_file)

                                # メニュー画面を表示
                                from linebot.v3.messaging import FlexMessage, FlexContainer
                                flex_message_content = get_simple_flex_menu()
                                flex_container = FlexContainer.from_dict(flex_message_content)
                                flex_message = FlexMessage(
                                    alt_text="メニュー",
                                    contents=flex_container
                                )

                                print(
                                    f"[DEBUG] 未来タスク追加モード返信メッセージ送信開始: {reply_text[:100]}..."
                                )
                                active_line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text), flex_message],
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
                                active_line_bot_api.reply_message(
                                    ReplyMessageRequest(
                                        replyToken=reply_token,
                                        messages=[TextMessage(text=reply_text)],
                                    )
                                )
                                continue

                        # 未来タスク選択モードでの処理
                        # session ディレクトリのファイルも確認
                        future_selection_file = f"future_task_selection_{user_id}.json"
                        future_selection_file_alt = os.path.abspath(os.path.join(os.path.dirname(__file__), "session", f"future_task_selection_{user_id}.json"))
                        # 互換の選択フラグ（task_select_mode）が future_schedule を指す場合も拾う
                        legacy_mode = None
                        flag_data = load_flag_data(user_id, "task_select")
                        if flag_data:
                            mode = flag_data.get("mode", "")
                            if mode:
                                legacy_mode = f"mode={mode}"
                        print(
                            f"[DEBUG] 未来タスク選択モードファイル確認: {future_selection_file}={os.path.exists(future_selection_file)}, alt={future_selection_file_alt}={os.path.exists(future_selection_file_alt)}, legacy_mode={legacy_mode}"
                        )
                        flag_path = future_selection_file if os.path.exists(future_selection_file) else (future_selection_file_alt if os.path.exists(future_selection_file_alt) else None)
                        if flag_path or (legacy_mode and "future_schedule" in legacy_mode):
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
                                        # 未来タスク選択モードファイルを削除
                                        for path in [future_selection_file, future_selection_file_alt]:
                                            try:
                                                if os.path.exists(path):
                                                    os.remove(path)
                                            except Exception:
                                                pass

                                        active_line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                        continue
                                    else:
                                        reply_text = f"⚠️ 無効な番号です。1〜{len(future_tasks)}の間で選択してください。"
                                        active_line_bot_api.reply_message(
                                            ReplyMessageRequest(
                                                replyToken=reply_token,
                                                messages=[TextMessage(text=reply_text)],
                                            )
                                        )
                                        continue
                                else:
                                    reply_text = "⚠️ 数字で選択してください。例: 1、3、5"
                                    active_line_bot_api.reply_message(
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
                                active_line_bot_api.reply_message(
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
                        button_message_sent = send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, user_id=user_id)
                        if button_message_sent:
                            print("[DEBUG] FlexMessage送信成功")
                        else:
                            print("[DEBUG] ボタンメニュー送信に失敗しました")
                        print("[DEBUG] Flex送信後")
                        continue

                    except Exception as e:
                        print("エラー:", e)
                        # 例外発生時もユーザーにエラー内容を返信
                        try:
                            active_line_bot_api.reply_message(
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
                                    active_line_bot_api.push_message(
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
    # datetime は先頭でインポート済み

    port = int(os.getenv("PORT", 5000))
    print(f"[app.py] Flaskアプリケーション起動: port={port}, time={datetime.now()}")
    if not os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        print("[ERROR] LINE_CHANNEL_ACCESS_TOKENが環境変数に設定されていません！")
    else:
        print("[app.py] LINE_CHANNEL_ACCESS_TOKENが設定されています")
    app.run(debug=False, host="0.0.0.0", port=port)
