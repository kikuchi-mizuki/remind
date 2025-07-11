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
import re
from datetime import datetime, timedelta

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
    """tokenファイルの存在と有効性をチェック"""
    token_path = f'tokens/{user_id}_token.json'
    if not os.path.exists(token_path):
        return False
    
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        
        creds = Credentials.from_authorized_user_file(token_path, [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive"
        ])
        
        # refresh_tokenが存在し、有効な場合のみTrue
        if creds and creds.refresh_token:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    # 更新されたトークンを保存
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
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
        
        # refresh_tokenの確認
        if not creds.refresh_token:
            print("[oauth2callback] WARNING: refresh_token not found!")
            return "認証エラー: refresh_tokenが取得できませんでした。<br>ブラウザで「別のアカウントを使用」を選択して再度認証してください。", 400
        
        # ユーザーごとにトークンを保存
        import os
        os.makedirs('tokens', exist_ok=True)
        token_path = f'tokens/{user_id}_token.json'
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        print(f"[oauth2callback] token saved: {token_path}")
        
        # 認証済みユーザーとして登録
        add_google_authenticated_user(user_id)
        print("[oauth2callback] user registered")
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
                            selected_path = f"selected_tasks_{user_id}.json"
                            if os.path.exists(selected_path):
                                with open(selected_path, "r") as f:
                                    task_ids = json.load(f)
                                all_tasks = task_service.get_user_tasks(user_id)
                                selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
                                today = datetime.now()
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
                                rich_lines = []
                                rich_lines.append("🗓️【本日のスケジュール提案】\n")
                                schedule_lines = []
                                reason_lines = []
                                matched = False
                                in_reason = False
                                for line in proposal.split('\n'):
                                    # 柔軟な正規表現: 記号・装飾・全角/半角・区切りの違いも許容
                                    m = re.match(r"[-・*\s]*\*?\*?\s*(\d{1,2})[:：]?(\d{2})\s*[〜~\-ー―‐–—−﹣－:：]?\s*(\d{1,2})[:：]?(\d{2})\*?\*?\s*([\u3000 \t\-–—―‐]*)?(.+?)\s*\((\d+)分\)", line)
                                    if m:
                                        matched = True
                                        schedule_lines.append("━━━━━━━━━━━━━━")
                                        schedule_lines.append(f"🕒 {m.group(1)}:{m.group(2)}〜{m.group(3)}:{m.group(4)}")
                                        schedule_lines.append(f"📝 {m.group(6).strip()}（{m.group(7)}分）")
                                        schedule_lines.append("━━━━━━━━━━━━━━\n")
                                    # 理由やまとめの開始を検出（例: '理由', 'まとめ', '説明' などのキーワード）
                                    elif re.search(r'(理由|まとめ|説明|ポイント|このスケジュールにより|このスケジュールで)', line):
                                        in_reason = True
                                    if in_reason and not m:
                                        reason_lines.append(line)
                                # スケジュール本体
                                if schedule_lines:
                                    rich_lines.extend(schedule_lines)
                                # 理由・まとめ
                                if reason_lines:
                                    rich_lines.append("\n---\n")
                                    rich_lines.append("📝【理由・まとめ】")
                                    rich_lines.extend(reason_lines)
                                # どちらもなければproposal本文をそのまま表示
                                if not schedule_lines and not reason_lines:
                                    rich_lines.append(proposal)
                                rich_lines.append("\nこのスケジュールでよろしければ「承認する」、修正したい場合は「修正する」と返信してください。")
                                reply_text = "\n".join(rich_lines)
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
                        # タスク登録メッセージか判定してDB保存
                        try:
                            task_info = task_service.parse_task_message(user_message)
                            task_service.create_task(user_id, task_info)
                            # タスク一覧を取得
                            all_tasks = task_service.get_user_tasks(user_id)
                            reply_text = "✅タスクを追加しました！\n\n"
                            reply_text += task_service.format_task_list(all_tasks)
                            line_bot_api.reply_message(
                                reply_token,
                                TextSendMessage(text=reply_text.strip())
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
                        
                        # 21時の繰り越し確認への返信処理
                        if re.match(r'^(\d+[ ,、]*)+$', user_message.strip()) or user_message.strip() == 'なし':
                            from datetime import datetime, timedelta
                            today_str = datetime.now().strftime('%Y-%m-%d')
                            tasks = task_service.get_user_tasks(user_id)
                            today_tasks = [t for t in tasks if t.due_date == today_str]
                            if not today_tasks:
                                continue
                            # 返信が「なし」→全削除
                            if user_message.strip() == 'なし':
                                for t in today_tasks:
                                    # Assuming db is available or task_service has an update_task_status method
                                    # For now, using task_service as a placeholder
                                    task_service.update_task_status(t.task_id, 'archived')
                                reply_text = '本日分のタスクはすべて削除しました。お疲れさまでした！'
                                line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
                                continue
                            # 番号抽出
                            nums = re.findall(r'\d+', user_message)
                            carryover_indexes = set(int(n)-1 for n in nums)
                            for idx, t in enumerate(today_tasks):
                                if idx in carryover_indexes:
                                    # 期日を翌日に更新
                                    next_day = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
                                    t.due_date = next_day
                                    # Assuming db is available or task_service has a create_task method
                                    # For now, using task_service as a placeholder
                                    task_service.create_task(t)  # 新規保存（上書き用のupdateがあればそちらを使う）
                                    task_service.update_task_status(t.task_id, 'archived')  # 元タスクはアーカイブ
                                else:
                                    task_service.update_task_status(t.task_id, 'archived')
                            reply_text = '指定されたタスクを明日に繰り越し、それ以外は削除しました。'
                            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
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