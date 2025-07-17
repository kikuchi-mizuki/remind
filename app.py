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
from linebot.models import ImageSendMessage
import json
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

line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))

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
        
        # 認証完了メッセージと動的メニューを送信
        try:
            from linebot.models import FlexSendMessage
            flex_message = get_simple_flex_menu(str(user_id))
            line_bot_api.push_message(
                str(user_id),
                FlexSendMessage(
                    alt_text="認証完了・ご利用案内・操作メニュー",
                    contents=flex_message
                )
            )
            print("[oauth2callback] 認証完了メニューを送信しました")
        except Exception as e:
            print(f"[oauth2callback] 認証完了メニュー送信エラー: {e}")
        
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
                line_bot_api.push_message(
                    str(user_id),
                    TextSendMessage(text=reply_text)
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
                            reply_token,
                            TextSendMessage(text=reply_text)
                        )
                        return "OK", 200
                    proposal = openai_service.generate_schedule_proposal(selected_tasks, free_times)
                    with open(f"schedule_proposal_{user_id}.txt", "w") as f:
                        f.write(proposal)
                    # ここでproposalをそのまま送信
                    print('[LINE送信直前 proposal]', proposal)
                    line_bot_api.reply_message(
                        reply_token,
                        TextSendMessage(text=proposal)
                    )
                    return "OK", 200
                else:
                    reply_text = "先に今日やるタスクを選択してください。"
                    line_bot_api.reply_message(
                        reply_token,
                        TextSendMessage(text=reply_text)
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
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                .success { color: green; font-size: 24px; margin-bottom: 20px; }
                .message { color: #666; margin-bottom: 30px; }
            </style>
        </head>
        <body>
            <div class="success">✅ 認証完了</div>
            <div class="message">
                Googleカレンダーとの連携が完了しました。
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
                            reply_token,
                            TextSendMessage(text=reply_text)
                        )
                        continue
                    # --- ここから下は認証済みユーザーのみ ---
                    
                    try:
                        # Google認証が必要な機能でのみ認証チェックを行う
                        # 基本的なタスク管理機能は認証なしでも利用可能
                        
                        # 「キャンセル」コマンドの処理
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
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        # 認証状態確認コマンド（デバッグ用）
                        if user_message.strip() == "認証確認":
                            auth_status = is_google_authenticated(user_id)
                            reply_text = f"🔍 認証状態確認\n\n"
                            reply_text += f"ユーザーID: {user_id}\n"
                            reply_text += f"認証状態: {'✅ 認証済み' if auth_status else '❌ 未認証'}\n\n"
                            if not auth_status:
                                auth_url = get_google_auth_url(user_id)
                                reply_text += f"認証が必要です:\n{auth_url}"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # データベース確認コマンド（デバッグ用）
                        if user_message.strip() == "DB確認":
                            from models.database import db
                            reply_text = f"🔍 データベース確認\n\n"
                            reply_text += f"DBファイルパス: {db.db_path}\n"
                            user_ids = db.get_all_user_ids()
                            reply_text += f"登録ユーザー数: {len(user_ids)}\n"
                            if user_ids:
                                reply_text += f"ユーザーID: {user_ids}\n"
                            token = db.get_token(user_id)
                            reply_text += f"トークン存在: {'✅' if token else '❌'}\n"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # 21時通知テストコマンド（デバッグ用）
                        if user_message.strip() == "21時テスト":
                            notification_service.send_carryover_check()
                            reply_text = "✅ 21時通知を手動実行しました"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # 8時通知テストコマンド（デバッグ用）
                        if user_message.strip() == "8時テスト":
                            notification_service.send_daily_task_notification()
                            reply_text = "✅ 8時通知を手動実行しました"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # タスク一覧コマンド
                        if user_message.strip() == "タスク一覧":
                            all_tasks = task_service.get_user_tasks(user_id)
                            reply_text = task_service.format_task_list(all_tasks, show_select_guide=True)
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # 未来タスク一覧コマンド
                        if user_message.strip() == "未来タスク一覧":
                            future_tasks = task_service.get_user_future_tasks(user_id)
                            reply_text = task_service.format_future_task_list(future_tasks, show_select_guide=False)
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        # 「タスク確認」コマンド（スペース・改行除去の部分一致で判定）
                        if "タスク確認" in user_message.replace(' ', '').replace('　', '').replace('\n', ''):
                            import pytz
                            from datetime import datetime
                            import os
                            jst = pytz.timezone('Asia/Tokyo')
                            today_str = datetime.now(jst).strftime('%Y-%m-%d')
                            # 今日が〆切のタスクのみ抽出
                            tasks = task_service.get_user_tasks(user_id)
                            today_tasks = [t for t in tasks if t.due_date == today_str]
                            print(f"[DEBUG] today_str={today_str}, today_tasks={[{'name': t.name, 'due_date': t.due_date} for t in today_tasks]}")
                            # タスク確認モードフラグを一時ファイルで保存
                            with open(f"task_check_mode_{user_id}.flag", "w") as f:
                                f.write("1")
                            if not today_tasks:
                                reply_text = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n本日分のタスクはありません。\n＝＝＝＝＝＝"
                            else:
                                reply_text = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n"
                                for idx, t in enumerate(today_tasks, 1):
                                    reply_text += f"{idx}. {t.name} ({t.duration_minutes}分)\n"
                                reply_text += "＝＝＝＝＝＝\n終わったタスクを選んでください！\n例：１、３、５"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        # 「タスク確認」後の番号選択で完了/繰り越し処理（タスク確認モードフラグがある場合のみ）
                        import os
                        if regex.fullmatch(r'[\d\s,、.．]+', user_message.strip()) and os.path.exists(f"task_check_mode_{user_id}.flag"):
                            os.remove(f"task_check_mode_{user_id}.flag")
                            import pytz
                            from datetime import datetime, timedelta
                            jst = pytz.timezone('Asia/Tokyo')
                            today_str = datetime.now(jst).strftime('%Y-%m-%d')
                            tasks = task_service.get_user_tasks(user_id)
                            today_tasks = [t for t in tasks if t.due_date == today_str]
                            if not today_tasks:
                                continue
                            # 番号抽出
                            nums = regex.findall(r'\d+', user_message)
                            selected_indexes = set(int(n)-1 for n in nums)
                            reply_text = ''
                            completed = []
                            carried = []
                            next_day = (datetime.now(jst) + timedelta(days=1)).strftime('%Y-%m-%d')
                            for idx, t in enumerate(today_tasks):
                                if idx in selected_indexes:
                                    task_service.archive_task(t.task_id)
                                    completed.append(t)
                                else:
                                    # 期日を明日にして新規登録、元タスクはアーカイブ
                                    t.due_date = next_day
                                    task_service.create_task(user_id, {
                                        'name': t.name,
                                        'duration_minutes': t.duration_minutes,
                                        'repeat': t.repeat if hasattr(t, 'repeat') else False,
                                        'due_date': t.due_date
                                    })
                                    task_service.archive_task(t.task_id)
                                    carried.append(t)
                            reply_text = '✅タスクを更新しました！\n\n'
                            reply_text += task_service.format_task_list(task_service.get_user_tasks(user_id), show_select_guide=False)
                            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                            continue
                        # タスク選択（番号のみのメッセージ: 半角/全角数字・カンマ・ピリオド・スペース対応）
                        import re
                        if regex.fullmatch(r'[\d\s,、.．]+', user_message.strip()):
                            # 削除モードかどうかをチェック
                            import os
                            delete_mode_file = f"delete_mode_{user_id}.json"
                            is_delete_mode = os.path.exists(delete_mode_file)
                            
                            selected_tasks = task_service.get_selected_tasks(user_id, user_message)
                            if selected_tasks:
                                if is_delete_mode:
                                    # 削除モードの場合
                                    try:
                                        # 選択されたタスクを削除
                                        deleted_count = 0
                                        for task in selected_tasks:
                                            if task_service.archive_task(task.task_id):
                                                deleted_count += 1
                                        
                                        # 削除モードファイルを削除
                                        if os.path.exists(delete_mode_file):
                                            os.remove(delete_mode_file)
                                        
                                        # 削除結果を表示
                                        reply_text = f"✅ {deleted_count}個のタスクを削除しました！\n\n"
                                        reply_text += "削除されたタスク：\n"
                                        for task in selected_tasks:
                                            reply_text += f"・{task.name}（{task.duration_minutes}分）\n"
                                        
                                        # 残りのタスク一覧を表示
                                        remaining_tasks = task_service.get_user_tasks(user_id)
                                        if remaining_tasks:
                                            reply_text += "\n" + task_service.format_task_list(remaining_tasks, show_select_guide=False)
                                        else:
                                            reply_text += "\n📋 タスク一覧\n＝＝＝＝＝＝\n登録されているタスクはありません。\n＝＝＝＝＝＝"
                                        
                                    except Exception as e:
                                        reply_text = f"❌ タスク削除中にエラーが発生しました: {e}"
                                        # 削除モードファイルを削除
                                        if os.path.exists(delete_mode_file):
                                            os.remove(delete_mode_file)
                                else:
                                    # スケジュール選択モードの場合（既存の処理）
                                    with open(f"selected_tasks_{user_id}.json", "w") as f:
                                        import json
                                        json.dump([t.task_id for t in selected_tasks], f)
                                    # --- テキストメッセージのみで確認案内 ---
                                    reply_text = "🤖今日やるタスクはこちらで良いですか？\n\n"
                                    reply_text += "\n".join([f"・{t.name}（{t.duration_minutes}分）" for t in selected_tasks])
                                    reply_text += "\n\n「はい」もしくは「修正する」でお答えください！"
                                
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                                continue
                        # 「はい」と返信された場合は自動でスケジュール提案
                        if user_message.strip() == "はい":
                            print(f"[はい処理] 開始: user_id={user_id}")
                            import os
                            import json
                            import re
                            from datetime import datetime
                            import pytz
                            selected_path = f"selected_tasks_{user_id}.json"
                            print(f"[はい処理] selected_path={selected_path}, exists={os.path.exists(selected_path)}")
                            if os.path.exists(selected_path):
                                with open(selected_path, "r") as f:
                                    task_ids = json.load(f)
                                print(f"[はい処理] task_ids={task_ids}")
                                all_tasks = task_service.get_user_tasks(user_id)
                                print(f"[はい処理] all_tasks数={len(all_tasks)}")
                                selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                                print(f"[はい処理] selected_tasks数={len(selected_tasks)}")
                                # Google認証チェック（カレンダー連携機能）
                                if not is_google_authenticated(user_id):
                                    # 認証が必要な場合、pending_actionファイルに内容を保存
                                    import json, os
                                    pending_action = {
                                        "user_message": user_message,
                                        "reply_token": reply_token
                                    }
                                    os.makedirs("pending_actions", exist_ok=True)
                                    with open(f"pending_actions/pending_action_{user_id}.json", "w") as f:
                                        json.dump(pending_action, f)
                                    auth_url = get_google_auth_url(user_id)
                                    reply_text = f"Googleカレンダー連携のため、まずこちらから認証をお願いします:\n{auth_url}"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                    continue
                                
                                jst = pytz.timezone('Asia/Tokyo')
                                today = datetime.now(jst)
                                print(f"[はい処理] 空き時間検索開始: user_id={user_id}, today={today}")
                                free_times = calendar_service.get_free_busy_times(user_id, today)
                                print(f"[はい処理] 空き時間検索結果: {len(free_times)}件")
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
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                    continue
                                print(f"[はい処理] スケジュール提案生成開始")
                                proposal = openai_service.generate_schedule_proposal(selected_tasks, free_times)
                                print(f"[はい処理] スケジュール提案生成完了: {len(proposal)}文字")
                                # スケジュール提案を一時保存
                                with open(f"schedule_proposal_{user_id}.txt", "w") as f:
                                    f.write(proposal)
                                print(f"[はい処理] スケジュール提案保存完了")
                                # --- リッチテキスト整形 ---
                                # 1. AI出力から案内文を除去
                                proposal_clean = regex.sub(r'このスケジュールでよろしければ.*?返信してください。', '', proposal, flags=regex.DOTALL)
                                # 2. 📝を全て削除
                                proposal_clean = proposal_clean.replace('📝', '')
                                # 3. 【】で囲まれた見出しが正しく出力されるように補正（例: 半角スペースや改行の直後に【が来る場合も対応）
                                proposal_clean = regex.sub(r'\n+\s*【', '\n【', proposal_clean)
                                proposal_clean = regex.sub(r'\s*】', '】', proposal_clean)
                                # 4. スケジュール本体・理由・まとめ抽出
                                fallback = []
                                for line in proposal_clean.split('\n'):
                                    if '---' in line or '【理由' in line or '【まとめ' in line:
                                        break
                                    if line.strip():
                                        fallback.append(line.strip())
                                reply_text = "\n".join(fallback)
                                reply_text += "\n\nこのスケジュールでよろしければ「承認する」、追加しない場合は「キャンセル」と返信してください。"
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                                continue
                            else:
                                reply_text = "先に今日やるタスクを選択してください。"
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                                continue
                        # 「修正する」と返信された場合はタスク選択の最初に戻る
                        if user_message.strip() == "修正する":
                            import os
                            selected_path = f"selected_tasks_{user_id}.json"
                            if os.path.exists(selected_path):
                                os.remove(selected_path)
                            # タスク一覧を再表示
                            all_tasks = task_service.get_user_tasks(user_id)
                            reply_text = task_service.format_task_list(all_tasks, show_select_guide=True)
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
                            import pytz
                            selected_path = f"selected_tasks_{user_id}.json"
                            if os.path.exists(selected_path):
                                with open(selected_path, "r") as f:
                                    task_ids = json.load(f)
                                all_tasks = task_service.get_user_tasks(user_id)
                                selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                                # Google認証チェック（カレンダー連携機能）
                                if not is_google_authenticated(user_id):
                                    # 認証が必要な場合、pending_actionファイルに内容を保存
                                    import json, os
                                    pending_action = {
                                        "user_message": user_message,
                                        "reply_token": reply_token
                                    }
                                    os.makedirs("pending_actions", exist_ok=True)
                                    with open(f"pending_actions/pending_action_{user_id}.json", "w") as f:
                                        json.dump(pending_action, f)
                                    auth_url = get_google_auth_url(user_id)
                                    reply_text = f"Googleカレンダー連携のため、まずこちらから認証をお願いします:\n{auth_url}"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                    continue
                                
                                # Googleカレンダーの空き時間を取得
                                jst = pytz.timezone('Asia/Tokyo')
                                today = datetime.now(jst)
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
                        if user_message.strip() == "承認する":
                            import os
                            from datetime import datetime
                            proposal_path = f"schedule_proposal_{user_id}.txt"
                            if os.path.exists(proposal_path):
                                with open(proposal_path, "r") as f:
                                    proposal = f.read()
                                print(f"[承認する] 読み込んだ提案: {proposal}")
                                # Google認証チェック（カレンダー連携機能）
                                if not is_google_authenticated(user_id):
                                    # 認証が必要な場合、pending_actionファイルに内容を保存
                                    import json, os
                                    pending_action = {
                                        "user_message": user_message,
                                        "reply_token": reply_token
                                    }
                                    os.makedirs("pending_actions", exist_ok=True)
                                    with open(f"pending_actions/pending_action_{user_id}.json", "w") as f:
                                        json.dump(pending_action, f)
                                    auth_url = get_google_auth_url(user_id)
                                    reply_text = f"Googleカレンダー連携のため、まずこちらから認証をお願いします:\n{auth_url}"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                    continue
                                
                                # Googleカレンダーに登録
                                try:
                                    success = calendar_service.add_events_to_calendar(user_id, proposal)
                                    print(f"[承認する] カレンダー登録結果: {success}")
                                except Exception as e:
                                    print(f"[承認する] カレンダー登録時エラー: {e}")
                                    success = False
                                if success:
                                    # 今日のスケジュール一覧を取得
                                    import pytz
                                    jst = pytz.timezone('Asia/Tokyo')
                                    today = datetime.now(jst)
                                    events = calendar_service.get_today_schedule(user_id)
                                    reply_text = "✅本日のスケジュールです！\n\n"
                                    reply_text += f"📅 {today.strftime('%Y/%m/%d (%a)')}\n"
                                    reply_text += "━━━━━━━━━━\n"
                                    if events:
                                        for i, ev in enumerate(events, 1):
                                            title = ev['title']
                                            # 📝や余計な記号を除去
                                            title_clean = title.replace('📝', '').replace('[added_by_bot]', '').strip()
                                            # 1. 番号付き（1. タイトル🔥）
                                            reply_text += f"{i}. {title_clean}"
                                            if '[added_by_bot]' in title:
                                                reply_text += "🔥"
                                            reply_text += "\n"
                                            # 2. 時刻（🕐8:00～8:30）
                                            def fmt_time(dtstr):
                                                m = regex.search(r'T(\d{2}):(\d{2})', dtstr)
                                                if m:
                                                    return f"{int(m.group(1))}:{m.group(2)}"
                                                return dtstr
                                            start = fmt_time(ev['start'])
                                            end = fmt_time(ev['end'])
                                            reply_text += f"🕐{start}～{end}\n\n"
                                    reply_text += "━━━━━━━━━━"
                                    line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                                    continue
                                else:
                                    reply_text = "❌ カレンダー登録に失敗しました。\n\n"
                                    reply_text += "Google認証に問題がある可能性があります。\n"
                                    reply_text += "以下の手順で再認証をお願いします：\n"
                                    reply_text += "1. 下記のリンクからGoogle認証を実行\n"
                                    reply_text += "2. 認証時は必ずアカウント選択画面でアカウントを選び直してください\n"
                                    reply_text += "3. 認証完了後、再度「承認する」と送信してください\n\n"
                                    auth_url = get_google_auth_url(user_id)
                                    reply_text += f"🔗 {auth_url}"
                            else:
                                print("[承認する] proposalファイルが存在しません")
                                reply_text = "先にスケジュール提案を受け取ってください。"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue
                        # スケジュール修正指示（タスク登録より先にチェック）
                        if "を" in user_message and "時" in user_message and "変更" in user_message:
                            # Google認証チェック（カレンダー連携機能）
                            if not is_google_authenticated(user_id):
                                # 認証が必要な場合、pending_actionファイルに内容を保存
                                import json, os
                                pending_action = {
                                    "user_message": user_message,
                                    "reply_token": reply_token
                                }
                                os.makedirs("pending_actions", exist_ok=True)
                                with open(f"pending_actions/pending_action_{user_id}.json", "w") as f:
                                    json.dump(pending_action, f)
                                auth_url = get_google_auth_url(user_id)
                                reply_text = f"Googleカレンダー連携のため、まずこちらから認証をお願いします:\n{auth_url}"
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                                continue
                            
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

                        # 「タスク追加」と送信された場合、案内文付きでタスク一覧を表示
                        print(f"[DEBUG] タスク追加分岐判定: '{user_message.strip()}'", flush=True)
                        # 「緊急タスク追加」と送信された場合、緊急タスク追加モードを開始
                        if user_message.strip() == "緊急タスク追加":
                            # Google認証チェック
                            if not is_google_authenticated(user_id):
                                auth_url = get_google_auth_url(user_id)
                                reply_text = f"📅 カレンダー連携が必要です\n\nGoogleカレンダーにアクセスして認証してください：\n{auth_url}"
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
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
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue



                        # 「タスク削除」と送信された場合、案内文付きでタスク一覧を表示
                        if user_message.strip() == "タスク削除":
                            all_tasks = task_service.get_user_tasks(user_id)
                            reply_text = task_service.format_task_list(all_tasks, show_select_guide=False, for_deletion=True)
                            
                            # 削除モードファイルを作成
                            import os
                            delete_mode_file = f"delete_mode_{user_id}.json"
                            with open(delete_mode_file, "w") as f:
                                import json
                                import datetime
                                json.dump({"mode": "delete", "timestamp": datetime.datetime.now().isoformat()}, f)
                            
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # 「緊急タスク追加」と送信された場合、緊急タスク追加モードを開始
                        if user_message.strip() == "緊急タスク追加":
                            # Google認証チェック
                            if not is_google_authenticated(user_id):
                                auth_url = get_google_auth_url(user_id)
                                reply_text = f"📅 カレンダー連携が必要です\n\nGoogleカレンダーにアクセスして認証してください：\n{auth_url}"
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
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
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # 「未来タスク追加」と送信された場合、未来タスク追加モードを開始
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
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # 通常のタスク追加処理（未来タスク追加コマンドより後に配置）
                        if "タスク追加" in user_message.replace(' ', '').replace('　', ''):
                            try:
                                print("[DEBUG] タスク追加分岐: get_user_tasks呼び出し", flush=True)
                                all_tasks = task_service.get_user_tasks(user_id)
                                print(f"[DEBUG] タスク追加分岐: タスク件数={len(all_tasks)}", flush=True)
                                reply_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                                if not reply_text:
                                    reply_text = "📋 タスク一覧\n＝＝＝＝＝＝\n登録されているタスクはありません。\n＝＝＝＝＝＝"
                                reply_text += "\n追加するタスク・所要時間・期限を送信してください！\n\n優先度が高いものがあれば、こちらも記載ください\nA: 緊急かつ重要  B: 緊急  C: 重要  -: その他\n\n例：「資料作成　30分　明日　急ぎ」"
                                print(f"[DEBUG] タスク追加分岐: reply_text=\n{reply_text}", flush=True)
                                print("[DEBUG] LINE API reply_message直前", flush=True)
                                res = line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                                print(f"[DEBUG] LINE API reply_message直後: {res}", flush=True)
                            except Exception as e:
                                import traceback
                                print(f"[ERROR] タスク追加分岐: {e}", flush=True)
                                traceback.print_exc()
                                try:
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=f"⚠️ 内部エラーが発生しました: {e}")
                                    )
                                except Exception as ee:
                                    print(f"[ERROR] LINEへのエラー通知も失敗: {ee}", flush=True)
                                continue
                            continue

                        # 「タスク確認」コマンド（スペース・改行除去の部分一致で判定）
                        if "タスク確認" in user_message.replace(' ', '').replace('　', '').replace('\n', ''):
                            import pytz
                            from datetime import datetime
                            import os
                            jst = pytz.timezone('Asia/Tokyo')
                            today_str = datetime.now(jst).strftime('%Y-%m-%d')
                            # 今日が〆切のタスクのみ抽出
                            tasks = task_service.get_user_tasks(user_id)
                            today_tasks = [t for t in tasks if t.due_date == today_str]
                            print(f"[DEBUG] today_str={today_str}, today_tasks={[{'name': t.name, 'due_date': t.due_date} for t in today_tasks]}")
                            # タスク確認モードフラグを一時ファイルで保存
                            with open(f"task_check_mode_{user_id}.flag", "w") as f:
                                f.write("1")
                            if not today_tasks:
                                reply_text = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n本日分のタスクはありません。\n＝＝＝＝＝＝"
                            else:
                                reply_text = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n"
                                for idx, t in enumerate(today_tasks, 1):
                                    reply_text += f"{idx}. {t.name} ({t.duration_minutes}分)\n"
                                reply_text += "＝＝＝＝＝＝\n終わったタスクを選んでください！\n例：１、３、５"
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text)
                            )
                            continue

                        # 未来タスク追加モードでの処理
                        import os
                        future_mode_file = f"future_task_mode_{user_id}.json"
                        print(f"[DEBUG] 未来タスクモードファイル確認: {future_mode_file}, exists={os.path.exists(future_mode_file)}")
                        if os.path.exists(future_mode_file):
                            print(f"[DEBUG] 未来タスク追加モード開始: user_message='{user_message}'")
                            try:
                                # 未来タスク用のパース
                                task_info = task_service.parse_future_task_message(user_message)
                                
                                # 未来タスクをDBに保存
                                task = task_service.create_future_task(user_id, task_info)
                                
                                # 未来タスク追加モードを終了
                                os.remove(future_mode_file)
                                
                                # 成功メッセージ
                                reply_text = f"🔮 未来タスクを追加しました！\n\n"
                                reply_text += f"📝 {task.name}\n"
                                reply_text += f"⏱️ {task.duration_minutes}分\n"
                                reply_text += f"📅 毎週日曜日18時に選択可能\n\n"
                                reply_text += "毎週日曜日18時に「どのタスクを来週やりますか？」と質問されます。\n\n"
                                
                                # 未来タスク一覧を表示
                                future_tasks = task_service.get_user_future_tasks(user_id)
                                reply_text += task_service.format_future_task_list(future_tasks, show_select_guide=False)
                                
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                                
                            except ValueError as e:
                                # 所要時間が見つからない場合の特別処理
                                if "所要時間が見つかりませんでした" in str(e):
                                    reply_text = "⚠️ 所要時間が見つかりませんでした。\n\n"
                                    reply_text += "未来タスクには所要時間が必要です。\n"
                                    reply_text += "例：「新規事業計画 2時間」\n"
                                    reply_text += "例：「営業資料の見直し 1時間半」\n"
                                    reply_text += "例：「〇〇という本を読む 30分」\n\n"
                                    reply_text += "タスク名と所要時間を一緒に送信してください。"
                                    
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                else:
                                    # その他のエラーの場合
                                    reply_text = f"⚠️ 未来タスク追加中にエラーが発生しました: {e}\n\n"
                                    reply_text += "正しい形式で入力してください。\n"
                                    reply_text += "例：「新規事業計画 2時間」"
                                    
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                            except Exception as e:
                                print(f"[ERROR] 未来タスク追加処理: {e}")
                                import traceback
                                traceback.print_exc()
                                reply_text = f"⚠️ 未来タスク追加中にエラーが発生しました: {e}"
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                            continue

                        # 緊急タスク追加モードでの処理
                        import os
                        urgent_mode_file = f"urgent_task_mode_{user_id}.json"
                        print(f"[DEBUG] 緊急タスクモードファイル確認: {urgent_mode_file}, exists={os.path.exists(urgent_mode_file)}")
                        if os.path.exists(urgent_mode_file):
                            print(f"[DEBUG] 緊急タスク追加モード開始: user_message='{user_message}'")
                            try:
                                import pytz
                                from datetime import datetime, timedelta
                                # 緊急タスク用の簡易パース（期日は今日固定）
                                task_name = None
                                duration_minutes = None
                                
                                # 時間パターンの定義（タスクサービスと同じ）
                                complex_time_patterns = [
                                    r'(\d+)\s*時間\s*半',  # 1時間半
                                    r'(\d+)\s*時間\s*(\d+)\s*分',  # 1時間30分
                                    r'(\d+)\s*hour\s*(\d+)\s*min',  # 1hour 30min
                                    r'(\d+)\s*h\s*(\d+)\s*m',  # 1h 30m
                                ]
                                
                                simple_time_patterns = [
                                    r'(\d+)\s*分',
                                    r'(\d+)\s*時間',
                                    r'(\d+)\s*min',
                                    r'(\d+)\s*hour',
                                    r'(\d+)\s*h',
                                    r'(\d+)\s*m'
                                ]
                                
                                # 時間の抽出
                                temp_message = user_message
                                print(f"[DEBUG] 時間抽出開始: temp_message='{temp_message}'")
                                for pattern in complex_time_patterns:
                                    match = re.search(pattern, temp_message)
                                    if match:
                                        if '半' in pattern:
                                            hours = int(match.group(1))
                                            duration_minutes = hours * 60 + 30
                                        else:
                                            hours = int(match.group(1))
                                            minutes = int(match.group(2))
                                            duration_minutes = hours * 60 + minutes
                                        temp_message = re.sub(pattern, '', temp_message)
                                        break
                                
                                if not duration_minutes:
                                    for pattern in simple_time_patterns:
                                        match = re.search(pattern, temp_message)
                                        if match:
                                            duration_minutes = int(match.group(1))
                                            if '時間' in pattern or 'hour' in pattern or 'h' in pattern:
                                                duration_minutes *= 60
                                            temp_message = re.sub(pattern, '', temp_message)
                                            break
                                
                                if not duration_minutes:
                                    reply_text = "⚠️ 所要時間が見つかりませんでした。\n例：「資料作成 1時間半」"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                    continue
                                
                                # タスク名の抽出
                                task_name = re.sub(r'[\s　]+', ' ', temp_message).strip()
                                if not task_name:
                                    reply_text = "⚠️ タスク名が見つかりませんでした。\n例：「資料作成 1時間半」"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                    continue
                                
                                # 今日の日付を取得
                                import pytz
                                from datetime import datetime, timedelta
                                jst = pytz.timezone('Asia/Tokyo')
                                today = datetime.now(jst)
                                today_str = today.strftime('%Y-%m-%d')
                                
                                # 空き時間を検索
                                print(f"[DEBUG] 空き時間検索開始: user_id={user_id}, today={today}")
                                free_times = calendar_service.get_free_busy_times(user_id, today)
                                print(f"[DEBUG] 空き時間検索結果: {len(free_times)}件")
                                
                                if not free_times:
                                    reply_text = "⚠️ 今日の空き時間が見つかりませんでした。\n別の日時を指定するか、通常のタスク追加をお試しください。"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                    continue
                                
                                # 十分な時間がある空き時間をフィルタリング
                                suitable_times = [t for t in free_times if t['duration_minutes'] >= duration_minutes]
                                
                                if not suitable_times:
                                    reply_text = f"⚠️ {duration_minutes}分の空き時間が見つかりませんでした。\n最長の空き時間: {max(free_times, key=lambda x: x['duration_minutes'])['duration_minutes']}分"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                    continue
                                
                                # 最も早い時間を選択
                                selected_time = min(suitable_times, key=lambda x: x['start'])
                                start_time = selected_time['start']
                                
                                # カレンダーにイベントを追加
                                success = calendar_service.add_event_to_calendar(
                                    user_id, task_name, start_time, duration_minutes, 
                                    f"緊急タスク: {task_name}"
                                )
                                
                                if success:
                                    # タスクもDBに保存
                                    task_info = {
                                        'name': task_name,
                                        'duration_minutes': duration_minutes,
                                        'repeat': False,
                                        'due_date': today_str
                                    }
                                    task_service.create_task(user_id, task_info)
                                    
                                    # 緊急タスク追加モードを終了
                                    os.remove(urgent_mode_file)
                                    
                                    # 成功メッセージ
                                    start_time_str = start_time.strftime('%H:%M')
                                    end_time = start_time + timedelta(minutes=duration_minutes)
                                    end_time_str = end_time.strftime('%H:%M')
                                    
                                    reply_text = f"✅ 緊急タスクを追加しました！\n\n"
                                    reply_text += f"📝 {task_name}\n"
                                    reply_text += f"🕐 {start_time_str}〜{end_time_str}\n"
                                    reply_text += f"📅 {today_str}\n\n"
                                    reply_text += "Googleカレンダーにも登録されました。"
                                    
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                else:
                                    reply_text = "⚠️ カレンダーへの登録に失敗しました。\nしばらく時間をおいて再度お試しください。"
                                    line_bot_api.reply_message(
                                        reply_token,
                                        TextSendMessage(text=reply_text)
                                    )
                                
                            except Exception as e:
                                print(f"[ERROR] 緊急タスク追加処理: {e}")
                                import traceback
                                traceback.print_exc()
                                reply_text = f"⚠️ 緊急タスク追加中にエラーが発生しました: {e}"
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text)
                                )
                            continue



                        # タスク登録メッセージか判定してDB保存
                        try:
                            print(f"[DEBUG] タスク登録処理開始: user_message='{user_message}'")
                            
                            # 改行で区切られた複数タスクかチェック
                            if '\n' in user_message:
                                print(f"[DEBUG] 複数タスク処理開始")
                                # 複数タスク処理
                                task_infos = task_service.parse_multiple_tasks(user_message)
                                if not task_infos:
                                    raise ValueError("有効なタスクが見つかりませんでした")
                                
                                # 各タスクをDBに保存
                                created_tasks = []
                                for task_info in task_infos:
                                    task = task_service.create_task(user_id, task_info)
                                    created_tasks.append(task)
                                
                                # タスク一覧を取得
                                all_tasks = task_service.get_user_tasks(user_id)
                                
                                # 成功メッセージ
                                if len(created_tasks) == 1:
                                    priority = task_infos[0].get('priority', 'normal')
                                    priority_messages = {
                                        "urgent_important": "🚨緊急かつ重要なタスクを追加しました！",
                                        "not_urgent_important": "⭐重要なタスクを追加しました！",
                                        "urgent_not_important": "⚡緊急タスクを追加しました！",
                                        "normal": "✅タスクを追加しました！"
                                    }
                                    reply_text = priority_messages.get(priority, "✅タスクを追加しました！") + "\n\n"
                                else:
                                    reply_text = f"✅ {len(created_tasks)}個のタスクを追加しました！\n\n"
                                
                                reply_text += task_service.format_task_list(all_tasks, show_select_guide=False)
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text.strip())
                                )
                            else:
                                print(f"[DEBUG] 単一タスク処理開始")
                                # 単一タスク処理（既存の処理）
                                task_info = task_service.parse_task_message(user_message)
                                print(f"[DEBUG] タスク情報解析完了: {task_info}")
                                
                                task = task_service.create_task(user_id, task_info)
                                print(f"[DEBUG] タスク作成完了: task_id={task.task_id}")
                                
                                # タスク一覧を取得
                                all_tasks = task_service.get_user_tasks(user_id)
                                print(f"[DEBUG] タスク一覧取得完了: {len(all_tasks)}件")
                                
                                # 優先度に応じたメッセージ
                                priority_messages = {
                                   "urgent_important": "🚨緊急かつ重要なタスクを追加しました！",
                              "not_urgent_important": "⭐重要なタスクを追加しました！",
                              "urgent_not_important": "⚡緊急タスクを追加しました！",
                              "normal": "✅タスクを追加しました！"
                                }
                                
                                priority = task_info.get('priority', 'normal')
                                reply_text = priority_messages.get(priority, "✅タスクを追加しました！") + "\n\n"
                                reply_text += task_service.format_task_list(all_tasks, show_select_guide=False)
                                
                                print(f"[DEBUG] 返信メッセージ送信開始")
                                line_bot_api.reply_message(
                                    reply_token,
                                    TextSendMessage(text=reply_text.strip())
                                )
                                print(f"[DEBUG] 返信メッセージ送信完了")
                            continue
                        except Exception as e:
                            # タスク登録エラーの場合は、Flex Messageメニューを返信
                            print(f"[DEBUG] タスク登録エラー詳細: {e}")
                            import traceback
                            print(f"[DEBUG] エラートレースバック:")
                            traceback.print_exc()
                            print(f"[DEBUG] メニュー生成開始: user_id={user_id}")
                            from linebot.models import FlexSendMessage
                            flex_message = get_simple_flex_menu(user_id)
                            print(f"[DEBUG] メニュー生成完了: {flex_message}")
                            line_bot_api.reply_message(
                                reply_token,
                                FlexSendMessage(
                                    alt_text="ご利用案内・操作メニュー",
                                    contents=flex_message
                                )
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
                                    # Assuming db is available or task_service has an update_task_status method
                                    # For now, using task_service as a placeholder
                                    task_service.archive_task(t.task_id)
                                reply_text = '本日分のタスクはすべて削除しました。お疲れさまでした！'
                                line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                                continue
                            # 番号抽出
                            nums = regex.findall(r'\d+', user_message)
                            carryover_indexes = set(int(n)-1 for n in nums)
                            for idx, t in enumerate(today_tasks):
                                if idx in carryover_indexes:
                                    # 期日を翌日に更新
                                    next_day = (datetime.now(jst) + timedelta(days=1)).strftime('%Y-%m-%d')
                                    t.due_date = next_day
                                    # Assuming db is available or task_service has a create_task method
                                    # For now, using task_service as a placeholder
                                    task_service.create_task(t)  # 新規保存（上書き用のupdateがあればそちらを使う）
                                    task_service.archive_task(t.task_id)  # 元タスクはアーカイブ
                                else:
                                    task_service.archive_task(t.task_id)
                            reply_text = '指定されたタスクを明日に繰り越し、それ以外は削除しました。'
                            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                            continue


                        # どのコマンドにも該当しない場合はガイドメッセージを返信
                        print(f"[DEBUG] 認識されていないコマンド: {user_message}")
                        print(f"[DEBUG] メニュー生成開始: user_id={user_id}")
                        from linebot.models import FlexSendMessage
                        flex_message = get_simple_flex_menu(user_id)
                        print(f"[DEBUG] メニュー生成完了: {flex_message}")
                        line_bot_api.reply_message(
                            reply_token,
                            FlexSendMessage(
                                alt_text="ご利用案内・操作メニュー",
                                contents=flex_message
                            )
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

# --- Flex Message メニュー定義 ---
def get_simple_flex_menu(user_id=None):
    """認証状態に応じてメニューを動的に生成"""
    print(f"[get_simple_flex_menu] user_id={user_id}")
    
    # 全ボタンを表示（緊急タスクボタン含む）
    basic_buttons = [
        {
            "type": "button",
            "action": {"type": "message", "label": "タスクを追加する", "text": "タスク追加"},
            "style": "primary"
        },
        {
            "type": "button",
            "action": {"type": "message", "label": "緊急タスクを追加する", "text": "緊急タスク追加"},
            "style": "primary",
            "color": "#FF6B6B"
        },
        {
            "type": "button",
            "action": {"type": "message", "label": "未来タスクを追加する", "text": "未来タスク追加"},
            "style": "primary",
            "color": "#4ECDC4"
        },
        {
            "type": "button",
            "action": {"type": "message", "label": "タスクを削除する", "text": "タスク削除"},
            "style": "secondary"
        }
    ]
    
    print(f"[get_simple_flex_menu] 全ボタンを表示（緊急タスクボタン含む）")
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "タスク管理Bot", "weight": "bold", "size": "xl"},
                {"type": "text", "text": "何をお手伝いしますか？", "size": "md", "margin": "md", "color": "#666666"}
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": basic_buttons
        }
    }

if __name__ == "__main__":
    # アプリケーション起動
    port = int(os.getenv('PORT', 5000))
    print(f"[app.py] Flaskアプリケーション起動: port={port}, time={datetime.now()}")
    app.run(debug=True, host='0.0.0.0', port=port) 