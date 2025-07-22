import os
from flask import Flask, request, redirect, session, url_for
from dotenv import load_dotenv
from services.task_service import TaskService
from services.calendar_service import CalendarService
from services.openai_service import OpenAIService
from services.notification_service import NotificationService
from models.database import init_db, Task
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient, ReplyMessageRequest, PushMessageRequest, TextMessage, FlexMessage, ImageMessage, FlexContainer
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
configuration = Configuration(access_token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
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
    print(f"[is_google_authenticated] DBから取得: token_json={token_json[:100] if token_json else 'None'}")
    if not token_json:
        print(f"[is_google_authenticated] トークンが存在しません")
        return False
    try:
        from google.oauth2.credentials import Credentials
        import json
        print(f"[is_google_authenticated] JSONパース開始")
        creds = Credentials.from_authorized_user_info(json.loads(token_json), [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive"
        ])
        print(f"[is_google_authenticated] Credentials作成成功: refresh_token={getattr(creds, 'refresh_token', None) is not None}")
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
        'client_secrets.json',
        scopes=[
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive"
        ],
        redirect_uri="https://web-production-bf2e2.up.railway.app/oauth2callback"
    )
    # stateにuser_idを含める
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',  # 確実にrefresh_tokenを取得するため
        state=user_id
    )
    # stateをセッションに保存（本番はDB推奨）
    session['state'] = state
    session['user_id'] = user_id
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    try:
        print("[oauth2callback] start")
        state = request.args.get('state')
        print(f"[oauth2callback] state: {state}")
        user_id = state or session.get('user_id')
        print(f"[oauth2callback] user_id: {user_id}")
        flow = Flow.from_client_secrets_file(
            'client_secrets.json',
            scopes=[
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/drive"
            ],
            state=state,
            redirect_uri="https://web-production-bf2e2.up.railway.app/oauth2callback"
        )
        print("[oauth2callback] flow created")
        flow.fetch_token(authorization_response=request.url)
        print("[oauth2callback] token fetched")
        creds = flow.credentials
        print(f"[oauth2callback] creds: {creds}")
        print(f"[oauth2callback] creds.refresh_token: {getattr(creds, 'refresh_token', None)}")
        print(f"[oauth2callback] user_id: {user_id}")
        # refresh_tokenの確認
        if not creds.refresh_token:
            print("[oauth2callback] ERROR: refresh_token not found! 必ずGoogle認証時に『別のアカウントを選択』してください。")
            return "認証エラー: refresh_tokenが取得できませんでした。<br>ブラウザで『別のアカウントを使用』を選択して再度認証してください。", 400
        
        # ユーザーごとにトークンを保存
        import os
        try:
            from models.database import db
            if not user_id:
                print(f"[oauth2callback] ERROR: user_id is None, token保存スキップ")
            else:
                token_json = creds.to_json()
                print(f"[oauth2callback] save_token呼び出し: user_id={user_id}, token_json先頭100={token_json[:100]}")
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
                    PushMessageRequest(to=str(user_id), messages=[TextMessage(text=guide_text)])
                )
                print("[oauth2callback] 認証完了ガイド送信成功")
            except Exception as e:
                print(f"[oauth2callback] ガイドメッセージ送信エラー: {e}")
                if "429" in str(e) or "monthly limit" in str(e):
                    print(f"[oauth2callback] LINE API制限エラー: {e}")
                    line_api_limited = True
                    # 制限エラーの場合は、認証完了のみを通知
                    try:
                        print(f"[oauth2callback] 簡潔メッセージ送信試行: user_id={user_id}")
                        line_bot_api.push_message(
                            PushMessageRequest(to=str(user_id), messages=[TextMessage(text="✅ Googleカレンダー連携完了！\n\n「タスク追加」と送信してタスクを追加してください。")] )
                        )
                        print("[oauth2callback] 簡潔な認証完了メッセージ送信成功")
                    except Exception as e2:
                        print(f"[oauth2callback] 簡潔メッセージ送信も失敗: {e2}")
                        print("[oauth2callback] LINE API制限により、すべてのメッセージ送信が失敗しました")
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
                        PushMessageRequest(to=str(user_id), messages=[FlexMessage(
                            alt_text="操作メニュー",
                            contents=flex_container
                        )])
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
                reply_text = task_service.format_task_list(all_tasks, show_select_guide=True)
                line_bot_api.reply_message(
                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
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
                    jst = pytz.timezone('Asia/Tokyo')
                    today = datetime.now(jst)
                    free_times = calendar_service.get_free_busy_times(str(user_id), today)
                    if not free_times and len(free_times) == 0:
                        # Google認証エラーの可能性
                        reply_text = "❌ Googleカレンダーへのアクセスに失敗しました。\n\n"
                        reply_text += "以下の手順で再認証をお願いします：\n"
                        reply_text += "1. 下記のリンクからGoogle認証を実行\n"
                        reply_text += "2. 認証時は必ずアカウント選択画面でアカウントを選び直してください\n"
                        reply_text += "3. 認証完了後、再度「はい」と送信してください\n\n"
                        auth_url = get_google_auth_url(user_id)
                        reply_text += f"🔗 {auth_url}"
                        line_bot_api.reply_message(
                            ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                        )
                        return "OK", 200
                    proposal = openai_service.generate_schedule_proposal(selected_tasks, free_times)
                    with open(f"schedule_proposal_{user_id}.txt", "w") as f:
                        f.write(proposal)
                    # ここでproposalをそのまま送信
                    print('[LINE送信直前 proposal]', proposal)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=proposal)])
                    )
                    return "OK", 200
                else:
                    reply_text = "先に今日やるタスクを選択してください。"
                    line_bot_api.reply_message(
                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
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
                            ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                        )
                        continue
                    # --- ここから下は認証済みユーザーのみ ---
                    
                    try:
                        # Google認証が必要な機能でのみ認証チェックを行う
                        # 基本的なタスク管理機能は認証なしでも利用可能
                        
                        # タスク登録メッセージか判定してDB保存（コマンドでない場合のみ）
                        # コマンド一覧
                        commands = [
                            "タスク追加", "緊急タスク追加", "未来タスク追加", "タスク削除",
                            "タスク一覧", "未来タスク一覧", "キャンセル", "認証確認", "DB確認",
                            "8時テスト", "８時テスト", "21時テスト", "日曜18時テスト", "はい", "修正する", "承認する"
                        ]
                        
                        print(f"[DEBUG] コマンド判定: user_message='{user_message.strip()}', in commands={user_message.strip() in commands}")
                        print(f"[DEBUG] コマンド一覧: {commands}")
                        
                        # タスク選択処理を先に実行（数字入力の場合）
                        import os
                        select_flag = f"task_select_mode_{user_id}.flag"
                        if user_message.strip().isdigit() or (',' in user_message or '、' in user_message):
                            if os.path.exists(select_flag):
                                print(f"[DEBUG] タスク選択フラグ検出: {select_flag}")
                                try:
                                    # タスク一覧を取得
                                    all_tasks = task_service.get_user_tasks(user_id)
                                    future_tasks = task_service.get_user_future_tasks(user_id)
                                    # 選択された数字を解析
                                    selected_numbers = [int(n.strip()) for n in user_message.replace('、', ',').split(',') if n.strip().isdigit()]
                                    if not selected_numbers:
                                        reply_text = "⚠️ 有効な数字を入力してください。\n例: 1、2、3"
                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                        )
                                        continue
                                    # タスク一覧をformat_task_listと同じ順序で並べる
                                    all_for_display = all_tasks + future_tasks
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
                                    display_tasks = sorted(all_for_display, key=sort_key)
                                    print(f"[DEBUG] 表示順序タスク: {[f'{i+1}.{task.name}' for i, task in enumerate(display_tasks)]}")
                                    selected_tasks = []
                                    for num in selected_numbers:
                                        idx = num - 1
                                        if 0 <= idx < len(display_tasks):
                                            selected_tasks.append(display_tasks[idx])
                                            print(f"[DEBUG] タスク選択: 番号={num}, インデックス={idx}, タスク名={display_tasks[idx].name}")
                                        else:
                                            print(f"[DEBUG] タスク選択エラー: 番号={num}, インデックス={idx}, 最大インデックス={len(display_tasks)-1}")
                                    if not selected_tasks:
                                        reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                        )
                                        continue
                                    reply_text = "✅ 選択されたタスク:\n\n"
                                    for i, task in enumerate(selected_tasks, 1):
                                        reply_text += f"{i}. {task.name} ({task.duration_minutes}分)\n"
                                    reply_text += "\nこれらのタスクを今日のスケジュールに追加しますか？\n「はい」で承認、「修正する」で修正できます。"
                                    # 選択されたタスクをファイルに保存
                                    import json
                                    selected_tasks_file = f"selected_tasks_{user_id}.json"
                                    with open(selected_tasks_file, "w") as f:
                                        json.dump([task.task_id for task in selected_tasks], f)
                                    # 選択後はフラグを削除
                                    os.remove(select_flag)
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                    )
                                    continue
                                except Exception as e:
                                    print(f"[DEBUG] タスク選択処理エラー: {e}")
                                    reply_text = "⚠️ タスク選択処理中にエラーが発生しました。"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                    )
                                    continue
                        
                        # コマンド処理を先に実行
                        if user_message.strip() in commands:
                            print(f"[DEBUG] コマンド処理開始: '{user_message.strip()}'")
                            
                            # 「タスク追加」コマンドの処理
                            if user_message.strip() == "タスク追加":
                                print("[DEBUG] タスク追加分岐: 処理開始", flush=True)
                                all_tasks = task_service.get_user_tasks(user_id)
                                print(f"[DEBUG] タスク追加分岐: タスク件数={len(all_tasks)}", flush=True)
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
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                print(f"[DEBUG] LINE API reply_message直後: {res}", flush=True)
                                continue
                            
                            # 他のコマンド処理もここに配置...
                            # 「緊急タスク追加」コマンドの処理
                            if user_message.strip() == "緊急タスク追加":
                                # Google認証チェック
                                if not is_google_authenticated(user_id):
                                    auth_url = get_google_auth_url(user_id)
                                    reply_text = f"📅 カレンダー連携が必要です\n\nGoogleカレンダーにアクセスして認証してください：\n{auth_url}"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                    )
                                    continue
                                # 緊急タスク追加モードファイルを作成
                                import os
                                from datetime import datetime
                                urgent_mode_file = f"urgent_task_mode_{user_id}.json"
                                with open(urgent_mode_file, "w") as f:
                                    import json
                                    json.dump({"mode": "urgent_task", "timestamp": datetime.now().isoformat()}, f)
                                reply_text = "🚨 緊急タスク追加モード\n\nタスク名と所要時間を送信してください！\n例：「資料作成 1時間半」\n\n※今日の空き時間に自動でスケジュールされます"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                            
                            # 「未来タスク追加」コマンドの処理
                            if user_message.strip() == "未来タスク追加":
                                # 未来タスク追加モードファイルを作成
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
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                            
                            # 「タスク削除」コマンドの処理
                            if user_message.strip() == "タスク削除":
                                print(f"[DEBUG] タスク削除コマンド処理開始: user_id={user_id}")
                                # 通常のタスクと未来タスクを取得
                                all_tasks = task_service.get_user_tasks(user_id)
                                future_tasks = task_service.get_user_future_tasks(user_id)
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
                                            "normal": "-"
                                        }.get(task.priority, "-")
                                        
                                        # 期日表示
                                        if task.due_date:
                                            try:
                                                y, m, d = task.due_date.split('-')
                                                due_date_obj = datetime(int(y), int(m), int(d))
                                                weekday_names = ['月', '火', '水', '木', '金', '土', '日']
                                                weekday = weekday_names[due_date_obj.weekday()]
                                                due_str = f"{int(m)}月{int(d)}日({weekday})"
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
                                print(f"[DEBUG] 削除モードファイル作成開始: {delete_mode_file}")
                                with open(delete_mode_file, "w") as f:
                                    import json
                                    import datetime
                                    json.dump({"mode": "delete", "timestamp": datetime.datetime.now().isoformat()}, f)
                                print(f"[DEBUG] 削除モードファイル作成完了: {delete_mode_file}, exists={os.path.exists(delete_mode_file)}")
                                
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                            
                            # その他のコマンド処理
                            if user_message.strip() == "タスク一覧":
                                all_tasks = task_service.get_user_tasks(user_id)
                                reply_text = task_service.format_task_list(all_tasks, show_select_guide=True)
                                # タスク選択待ちフラグを作成
                                import os
                                with open(f"task_select_mode_{user_id}.flag", "w") as f:
                                    f.write("selecting")
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue

                            if user_message.strip() == "未来タスク一覧":
                                future_tasks = task_service.get_user_future_tasks(user_id)
                                reply_text = task_service.format_future_task_list(future_tasks, show_select_guide=False)
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue

                            if user_message.strip() == "キャンセル":
                                import os
                                # すべての操作モードファイルを削除
                                files_to_remove = [
                                    f"task_check_mode_{user_id}.flag",
                                    f"delete_mode_{user_id}.json",
                                    f"selected_tasks_{user_id}.json",
                                    f"schedule_proposal_{user_id}.txt",
                                    f"urgent_task_mode_{user_id}.json",
                                    f"future_task_mode_{user_id}.json",
                                    f"future_task_selection_{user_id}.json"
                                ]
                                
                                for file_path in files_to_remove:
                                    if os.path.exists(file_path):
                                        os.remove(file_path)
                                
                                # pending_actionsディレクトリ内のファイルも削除
                                pending_dir = "pending_actions"
                                if os.path.exists(pending_dir):
                                    pending_file = f"{pending_dir}/pending_action_{user_id}.json"
                                    if os.path.exists(pending_file):
                                        os.remove(pending_file)
                                
                                reply_text = "✅操作をキャンセルしました"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue

                            # デバッグ用コマンド (認証確認, DB確認, 21時テスト, 8時テスト, 日曜18時テスト)
                            if user_message.strip() == "認証確認":
                                auth_status = is_google_authenticated(user_id)
                                reply_text = f"認証状態: {auth_status}"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                            if user_message.strip() == "DB確認":
                                all_tasks = task_service.get_user_tasks(user_id)
                                future_tasks = task_service.get_user_future_tasks(user_id)
                                reply_text = f"通常タスク: {len(all_tasks)}件\n未来タスク: {len(future_tasks)}件"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                            if user_message.strip() == "21時テスト":
                                try:
                                    notification_service.send_carryover_check()
                                    reply_text = "21時テスト通知を送信しました"
                                except Exception as e:
                                    reply_text = f"21時テストエラー: {e}"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                            if user_message.strip() == "8時テスト" or user_message.strip() == "８時テスト":
                                try:
                                    notification_service.send_daily_task_notification()
                                    # タスク選択待ちフラグを作成
                                    import os
                                    with open(f"task_select_mode_{user_id}.flag", "w") as f:
                                        f.write("selecting")
                                    reply_text = "8時テスト通知を送信しました"
                                except Exception as e:
                                    reply_text = f"8時テストエラー: {e}"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue

                            # 「はい」コマンドの処理
                            if user_message.strip() == "はい":
                                import os
                                import json
                                selected_tasks_file = f"selected_tasks_{user_id}.json"
                                if os.path.exists(selected_tasks_file):
                                    try:
                                        # 選択されたタスクを読み込み
                                        with open(selected_tasks_file, "r") as f:
                                            task_ids = json.load(f)
                                        
                                        all_tasks = task_service.get_user_tasks(user_id)
                                        selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                                        
                                        if not selected_tasks:
                                            reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
                                            line_bot_api.reply_message(
                                                ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                            )
                                            continue
                                        
                                        # スケジュール提案を生成
                                        from services.calendar_service import CalendarService
                                        from services.openai_service import OpenAIService
                                        from datetime import datetime
                                        import pytz
                                        
                                        calendar_service = CalendarService()
                                        openai_service = OpenAIService()
                                        
                                        jst = pytz.timezone('Asia/Tokyo')
                                        today = datetime.now(jst)
                                        free_times = calendar_service.get_free_busy_times(user_id, today)
                                        
                                        if not free_times:
                                            reply_text = "❌ 空き時間の取得に失敗しました。"
                                            line_bot_api.reply_message(
                                                ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                            )
                                            continue
                                        
                                        # スケジュール提案を生成
                                        proposal = openai_service.generate_schedule_proposal(selected_tasks, free_times)
                                        
                                        # 提案をファイルに保存
                                        with open(f"schedule_proposal_{user_id}.txt", "w") as f:
                                            f.write(proposal)
                                        
                                        # 提案を送信
                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=proposal)])
                                        )
                                        continue
                                        
                                    except Exception as e:
                                        print(f"[DEBUG] はいコマンド処理エラー: {e}")
                                        reply_text = f"⚠️ スケジュール提案生成中にエラーが発生しました: {e}"
                                        line_bot_api.reply_message(
                                            ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                        )
                                        continue
                                else:
                                    reply_text = "⚠️ 先にタスクを選択してください。"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                    )
                                    continue
                            if user_message.strip() == "日曜18時テスト":
                                try:
                                    notification_service.send_future_task_selection()
                                    reply_text = "日曜18時テスト通知を送信しました"
                                except Exception as e:
                                    reply_text = f"日曜18時テストエラー: {e}"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                            if user_message.strip() == "スケジューラー確認":
                                scheduler_status = notification_service.is_running
                                thread_status = notification_service.scheduler_thread.is_alive() if notification_service.scheduler_thread else False
                                reply_text = f"スケジューラー状態:\n- is_running: {scheduler_status}\n- スレッド動作: {thread_status}"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue

                            # スケジュール提案への返信処理
                            if user_message.strip() == "承認する":
                                try:
                                    # スケジュール提案ファイルを確認
                                    import os
                                    schedule_proposal_file = f"schedule_proposal_{user_id}.txt"
                                    if os.path.exists(schedule_proposal_file):
                                        # スケジュール提案を読み込み
                                        with open(schedule_proposal_file, "r") as f:
                                            proposal = f.read()
                                        
                                        # Googleカレンダーにスケジュールを追加
                                        from services.calendar_service import CalendarService
                                        calendar_service = CalendarService()
                                        
                                        # 選択されたタスクを取得
                                        selected_tasks_file = f"selected_tasks_{user_id}.json"
                                        if os.path.exists(selected_tasks_file):
                                            import json
                                            with open(selected_tasks_file, "r") as f:
                                                task_ids = json.load(f)
                                            
                                            all_tasks = task_service.get_user_tasks(user_id)
                                            selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                                            
                                            # カレンダーに追加
                                            success_count = 0
                                            for task in selected_tasks:
                                                # スケジュール提案から開始時刻を抽出（簡易版：14:00を固定）
                                                from datetime import datetime, timedelta
                                                import pytz
                                                jst = pytz.timezone('Asia/Tokyo')
                                                today = datetime.now(jst)
                                                start_time = today.replace(hour=14, minute=0, second=0, microsecond=0)
                                                
                                                if calendar_service.add_event_to_calendar(user_id, task.name, start_time, task.duration_minutes):
                                                    success_count += 1
                                            
                                            reply_text = f"✅ スケジュールを承認しました！\n\n{success_count}個のタスクをカレンダーに追加しました。\n\n"
                                            
                                            # 今日のスケジュール一覧を取得して表示
                                            today_schedule = calendar_service.get_today_schedule(user_id)
                                            print(f"[DEBUG] 今日のスケジュール取得結果: {len(today_schedule)}件")
                                            for i, event in enumerate(today_schedule):
                                                print(f"[DEBUG] イベント{i+1}: {event}")
                                            
                                            if today_schedule:
                                                reply_text += "📅 今日のスケジュール：\n"
                                                reply_text += "━━━━━━━━━━━━━━\n"
                                                from datetime import datetime
                                                for event in today_schedule:
                                                    try:
                                                        start_time = datetime.fromisoformat(event['start']).strftime('%H:%M')
                                                        end_time = datetime.fromisoformat(event['end']).strftime('%H:%M')
                                                    except Exception:
                                                        start_time = event['start']
                                                        end_time = event['end']
                                                    summary = event['title']
                                                    # 📝と[added_by_bot]を削除
                                                    clean_summary = summary.replace('📝 ', '').replace(' [added_by_bot]', '')
                                                    reply_text += f"🕐 {start_time}〜{end_time}\n"
                                                    reply_text += f"📝 {clean_summary}\n"
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
                                        reply_text = "⚠️ スケジュール提案が見つかりませんでした。"
                                    
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                    )
                                except Exception as e:
                                    print(f"[ERROR] 承認処理: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    reply_text = f"⚠️ 承認処理中にエラーが発生しました: {e}"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                    )
                                continue

                            if user_message.strip() == "修正する":
                                try:
                                    reply_text = "📝 スケジュール修正モード\n\n修正したい内容を送信してください！\n\n例：\n• 「資料作成を14時に変更」\n• 「会議準備を15時30分に変更」"
                                    
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                    )
                                except Exception as e:
                                    print(f"[ERROR] 修正処理: {e}")
                                    import traceback
                                    traceback.print_exc()
                                    reply_text = f"⚠️ 修正処理中にエラーが発生しました: {e}"
                                    line_bot_api.reply_message(
                                        ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                    )
                                continue

                            # 21時の繰り越し確認への返信処理
                            if regex.match(r'^(\d+[ ,、]*)+$', user_message.strip()) or user_message.strip() == 'なし':
                                from datetime import datetime, timedelta
                                import pytz
                                jst = pytz.timezone('Asia/Tokyo')
                                today_str = datetime.now(jst).strftime('%Y-%m-%d')
                                tasks = task_service.get_user_tasks(user_id)
                                today_tasks = [t for t in tasks if t.due_date == today_str]
                                if not today_tasks:
                                    continue
                                # 返信が「なし」→全削除
                                if user_message.strip() == 'なし':
                                    for t in today_tasks:
                                        task_service.archive_task(t.task_id)
                                    reply_text = '本日分のタスクはすべて削除しました。お疲れさまでした！'
                                    line_bot_api.reply_message(ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)]))
                                    continue
                                # 番号抽出
                                nums = regex.findall(r'\d+', user_message)
                                carryover_indexes = set(int(n)-1 for n in nums)
                                for idx, t in enumerate(today_tasks):
                                    if idx in carryover_indexes:
                                        # 期日を翌日に更新
                                        next_day = (datetime.now(jst) + timedelta(days=1)).strftime('%Y-%m-%d')
                                        t.due_date = next_day
                                        task_service.create_task(user_id, {
                                            'name': t.name,
                                            'duration_minutes': t.duration_minutes,
                                            'due_date': next_day,
                                            'priority': t.priority,
                                            'task_type': t.task_type
                                        })
                                        task_service.archive_task(t.task_id)  # 元タスクはアーカイブ
                                    else:
                                        task_service.archive_task(t.task_id)
                                reply_text = '指定されたタスクを明日に繰り越し、それ以外は削除しました。'
                                line_bot_api.reply_message(ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)]))
                                continue
                            
                            continue
                        
                        # コマンドでない場合のみタスク登録処理を実行
                        print(f"[DEBUG] コマンド以外のメッセージ処理開始: '{user_message}'")
                        
                        # 緊急タスク追加モードでの処理
                        import os
                        from datetime import datetime
                        urgent_mode_file = f"urgent_task_mode_{user_id}.json"
                        print(f"[DEBUG] 緊急タスク追加モードファイル確認: {urgent_mode_file}, exists={os.path.exists(urgent_mode_file)}")
                        if os.path.exists(urgent_mode_file):
                            print(f"[DEBUG] 緊急タスク追加モード開始: user_message='{user_message}'")
                            try:
                                # 緊急タスクとして登録
                                task_info = task_service.parse_task_message(user_message)
                                task_info['priority'] = 'urgent_not_important'  # 緊急タスクとして設定
                                task_info['due_date'] = datetime.now().strftime('%Y-%m-%d')  # 今日の日付に設定
                                
                                task = task_service.create_task(user_id, task_info)
                                print(f"[DEBUG] 緊急タスク作成完了: task_id={task.task_id}")
                                
                                # 今日の空き時間に自動スケジュール
                                from datetime import datetime
                                import pytz
                                from services.calendar_service import CalendarService
                                from services.openai_service import OpenAIService
                                
                                calendar_service = CalendarService()
                                openai_service = OpenAIService()
                                
                                jst = pytz.timezone('Asia/Tokyo')
                                today = datetime.now(jst)
                                
                                free_times = calendar_service.get_free_busy_times(user_id, today)
                                if free_times:
                                    proposal = openai_service.generate_schedule_proposal([task], free_times)
                                    
                                    # スケジュール提案ファイルを作成
                                    schedule_proposal_file = f"schedule_proposal_{user_id}.txt"
                                    with open(schedule_proposal_file, "w", encoding="utf-8") as f:
                                        f.write(proposal)
                                    
                                    # 選択されたタスクファイルを作成
                                    selected_tasks_file = f"selected_tasks_{user_id}.json"
                                    import json
                                    with open(selected_tasks_file, "w", encoding="utf-8") as f:
                                        json.dump([task.task_id], f, ensure_ascii=False)
                                    
                                    reply_text = "⚡ 緊急タスクを追加しました！\n\n"
                                    reply_text += "📅 今日の空き時間に自動スケジュール：\n\n"
                                    reply_text += proposal
                                else:
                                    reply_text = "⚡ 緊急タスクを追加しました！\n\n"
                                    reply_text += "⚠️ 今日の空き時間が見つかりませんでした。\n"
                                    reply_text += "手動でスケジュールを調整してください。"
                                
                                # 緊急タスク追加モードファイルを削除
                                if os.path.exists(urgent_mode_file):
                                    os.remove(urgent_mode_file)
                                
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                            except Exception as e:
                                print(f"[DEBUG] 緊急タスク追加モード処理エラー: {e}")
                                import traceback
                                traceback.print_exc()
                                reply_text = f"⚠️ 緊急タスク追加中にエラーが発生しました: {e}"
                                line_bot_api.reply_message(
                                    ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text)])
                                )
                                continue
                        
                        # タスク登録処理を試行
                        try:
                            print(f"[DEBUG] タスク登録処理開始: user_message='{user_message}'")
                            # 通常のタスク登録処理
                            task_info = task_service.parse_task_message(user_message)
                            print(f"[DEBUG] タスク情報解析完了: {task_info}")
                            task = task_service.create_task(user_id, task_info)
                            print(f"[DEBUG] タスク作成完了: task_id={task.task_id}")
                            all_tasks = task_service.get_user_tasks(user_id)
                            print(f"[DEBUG] タスク一覧取得完了: {len(all_tasks)}件")
                            priority_messages = {
                                "urgent_important": "🚨緊急かつ重要なタスクを追加しました！",
                                "not_urgent_important": "⭐重要なタスクを追加しました！",
                                "urgent_not_important": "⚡緊急タスクを追加しました！",
                                "normal": "✅タスクを追加しました！"
                            }
                            priority = task_info.get('priority', 'normal')
                            reply_text = priority_messages.get(priority, "✅タスクを追加しました！") + "\n\n"
                            reply_text += task_service.format_task_list(all_tasks, show_select_guide=False)
                            reply_text += "\n\nタスクの追加や削除があれば、いつでもお気軽にお声かけください！"
                            print(f"[DEBUG] 返信メッセージ送信開始")
                            line_bot_api.reply_message(
                                ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=reply_text.strip())])
                            )
                            print(f"[DEBUG] 返信メッセージ送信完了")
                            continue
                        except Exception as e:
                            print(f"[DEBUG] タスク登録エラー詳細: {e}")
                            import traceback
                            print(f"[DEBUG] エラートレースバック:")
                            traceback.print_exc()
                            # タスク登録に失敗した場合はFlexMessageで案内
                            print(f"[DEBUG] タスク登録失敗、FlexMessage処理へ")
                        # FlexMessageでボタン付きメニューを送信
                        from linebot.v3.messaging import FlexMessage, FlexContainer
                        flex_message = get_simple_flex_menu(user_id)
                        print(f"[DEBUG] FlexMessage生成: {flex_message}")
                        try:
                            # FlexContainer.from_dict()を使用して正しく作成
                            flex_container = FlexContainer.from_dict(flex_message)
                            flex_msg = FlexMessage(alt_text="ご利用案内・操作メニュー", contents=flex_container)
                            print(f"[DEBUG] FlexMessage作成完了: {flex_msg}")
                            line_bot_api.reply_message(
                                ReplyMessageRequest(replyToken=reply_token, messages=[flex_msg])
                            )
                            print("[DEBUG] FlexMessage送信完了")
                        except Exception as flex_e:
                            print(f"[DEBUG] FlexMessage送信エラー: {flex_e}")
                            # FlexMessage送信に失敗した場合はテキストで案内
                            line_bot_api.reply_message(
                                ReplyMessageRequest(replyToken=reply_token, messages=[
                                    TextMessage(text="「タスク追加」などのコマンドを送信してください。")
                                ])
                            )
                        continue
                    except Exception as e:
                        print("エラー:", e)
                        # 例外発生時もユーザーにエラー内容を返信
                        try:
                            line_bot_api.reply_message(
                                ReplyMessageRequest(replyToken=reply_token, messages=[TextMessage(text=f"⚠️ エラーが発生しました: {e}\nしばらく時間をおいて再度お試しください。")] )
                            )
                        except Exception as inner_e:
                            print("LINEへのエラー通知も失敗:", inner_e)
                            # reply_tokenが無効な場合はpush_messageで通知
                            if user_id:
                                try:
                                    line_bot_api.push_message(
                                        PushMessageRequest(to=str(user_id), messages=[TextMessage(text=f"⚠️ エラーが発生しました: {e}\nしばらく時間をおいて再度お試しください。")] )
                                    )
                                except Exception as push_e:
                                    print("push_messageも失敗:", push_e)
                        continue
    except Exception as e:
        print("エラー:", e)
    return "OK", 200

# --- Flex Message メニュー定義 ---
def get_simple_flex_menu(user_id=None):
    """認証状態に応じてメニューを動的に生成（dict型で返す）"""
    return {
        "type": "bubble",
        "size": "kilo",
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

if __name__ == "__main__":
    # アプリケーション起動
    import os
    from datetime import datetime
    port = int(os.getenv('PORT', 5000))
    print(f"[app.py] Flaskアプリケーション起動: port={port}, time={datetime.now()}")
    print(f"[DEBUG] LINE_CHANNEL_ACCESS_TOKEN: {os.getenv('LINE_CHANNEL_ACCESS_TOKEN')}")
    if not os.getenv('LINE_CHANNEL_ACCESS_TOKEN'):
        print("[ERROR] LINE_CHANNEL_ACCESS_TOKENが環境変数に設定されていません！")
    app.run(debug=False, host='0.0.0.0', port=port) 