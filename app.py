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

# Google認証済みユーザー管理（tokenファイルの存在と有効性で判定）
def is_google_authenticated(user_id):
    """tokenの存在と有効性をDBでチェック"""
    from models.database import db
    token_json = db.get_token(user_id)
    if not token_json:
        return False
    try:
        from google.oauth2.credentials import Credentials
        import json
        creds = Credentials.from_authorized_user_info(json.loads(token_json), [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive"
        ])
        if creds and creds.refresh_token:
            if creds.expired and creds.refresh_token:
                try:
                    from google.auth.transport.requests import Request
                    creds.refresh(Request())
                    db.save_token(user_id, creds.to_json())
                    return True
                except Exception as e:
                    print(f"Token refresh failed: {e}")
                    return False
            return True
        return False
    except Exception as e:
        print(f"Token validation failed: {e}")
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
                db_path = os.path.abspath('tasks.db')
                print(f"[oauth2callback] save_token呼び出し: user_id={user_id}, token_json先頭100={token_json[:100]}")
                print(f"[oauth2callback] DBファイルパス: {db_path}")
                db.save_token(str(user_id), token_json)
                print(f"[oauth2callback] token saved to DB for user: {user_id}")
        except Exception as e:
            print(f"[oauth2callback] token保存エラー: {e}")
            import traceback
            traceback.print_exc()
        
        # 認証済みユーザーとして登録
        add_google_authenticated_user(user_id)
        print("[oauth2callback] user registered")
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
                from linebot.models import FlexSendMessage
                flex_message = {
                    "type": "bubble",
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {"type": "text", "text": "タスク管理Bot", "weight": "bold", "size": "lg"},
                            {"type": "text", "text": "何をお手伝いしますか？", "size": "md", "margin": "md", "color": "#666666"}
                        ]
                    },
                    "footer": {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "action": {"type": "message", "label": "タスクを追加する", "text": "タスク追加"},
                                "style": "primary"
                            },
                            {
                                "type": "button",
                                "action": {"type": "message", "label": "タスクを削除する", "text": "タスク削除"},
                                "style": "secondary"
                            }
                        ]
                    }
                }
                line_bot_api.push_message(
                    str(user_id),
                    FlexSendMessage(
                        alt_text="タスク管理Botメニュー",
                        contents=flex_message
                    )
                )
        else:
            from linebot.models import FlexSendMessage
            flex_message = {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "text", "text": "タスク管理Bot", "weight": "bold", "size": "lg"},
                        {"type": "text", "text": "何をお手伝いしますか？", "size": "md", "margin": "md", "color": "#666666"}
                    ]
                },
                "footer": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "button",
                            "action": {"type": "message", "label": "タスクを追加する", "text": "タスク追加"},
                            "style": "primary"
                        },
                        {
                            "type": "button",
                            "action": {"type": "message", "label": "タスクを削除する", "text": "タスク削除"},
                            "style": "secondary"
                        }
                    ]
                }
            }
            line_bot_api.push_message(
                str(user_id),
                FlexSendMessage(
                    alt_text="タスク管理Botメニュー",
                    contents=flex_message
                )
            )
        return "Google認証が完了しました。LINEに戻って操作を続けてください。"
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
                    try:
                        # すべてのメッセージで最初にGoogle認証チェック
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
                        
                        # 「キャンセル」コマンドの処理
                        if user_message.strip() == "キャンセル":
                            import os
                            # すべての操作モードファイルを削除
                            files_to_remove = [
                                f"task_check_mode_{user_id}.flag",
                                f"delete_mode_{user_id}.json",
                                f"selected_tasks_{user_id}.json",
                                f"schedule_proposal_{user_id}.txt"
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
                        # タスク一覧コマンド
                        if user_message.strip() == "タスク一覧":
                            all_tasks = task_service.get_user_tasks(user_id)
                            reply_text = task_service.format_task_list(all_tasks, show_select_guide=True)
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
                            import os
                            import json
                            import re
                            from datetime import datetime
                            import pytz
                            selected_path = f"selected_tasks_{user_id}.json"
                            if os.path.exists(selected_path):
                                with open(selected_path, "r") as f:
                                    task_ids = json.load(f)
                                all_tasks = task_service.get_user_tasks(user_id)
                                selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                                jst = pytz.timezone('Asia/Tokyo')
                                today = datetime.now(jst)
                                free_times = calendar_service.get_free_busy_times(user_id, today)
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
                                proposal = openai_service.generate_schedule_proposal(selected_tasks, free_times)
                                # スケジュール提案を一時保存
                                with open(f"schedule_proposal_{user_id}.txt", "w") as f:
                                    f.write(proposal)
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
                        if "タスク追加" in user_message.replace(' ', '').replace('　', ''):
                            try:
                                print("[DEBUG] タスク追加分岐: get_user_tasks呼び出し", flush=True)
                                all_tasks = task_service.get_user_tasks(user_id)
                                print(f"[DEBUG] タスク追加分岐: タスク件数={len(all_tasks)}", flush=True)
                                reply_text = task_service.format_task_list(all_tasks, show_select_guide=False)
                                if not reply_text:
                                    reply_text = "📋 タスク一覧\n＝＝＝＝＝＝\n登録されているタスクはありません。\n＝＝＝＝＝＝"
                                reply_text += "\n追加するタスク・所要時間・期限を送信してください！\n例：「資料作成　30分　明日」"
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
                        # タスク登録メッセージか判定してDB保存
                        try:
                            task_info = task_service.parse_task_message(user_message)
                            task_service.create_task(user_id, task_info)
                            # タスク一覧を取得
                            all_tasks = task_service.get_user_tasks(user_id)
                            reply_text = "✅タスクを追加しました！\n\n"
                            reply_text += task_service.format_task_list(all_tasks, show_select_guide=False)
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text.strip())
                            )
                            continue
                        except Exception as e:
                            # タスク登録エラーの場合はFlex Messageメニューを返信
                            from linebot.models import FlexSendMessage
                            flex_message = get_simple_flex_menu()
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
                        from linebot.models import FlexSendMessage
                        flex_message = get_simple_flex_menu()
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

# --- Flex Message 2ボタン定義 ---
def get_simple_flex_menu():
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
            "contents": [
                {
                    "type": "button",
                    "action": {"type": "message", "label": "タスクを追加する", "text": "タスク追加"},
                    "style": "primary"
                },
                {
                    "type": "button",
                    "action": {"type": "message", "label": "タスクを削除する", "text": "タスク削除"},
                    "style": "secondary"
                }
            ]
        }
    }

if __name__ == "__main__":
    init_db()
    notification_service.start_scheduler()
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000))) 