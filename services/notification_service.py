import os
import schedule
import time
import threading
from datetime import datetime, timedelta
import pytz
from typing import List
# --- v3 importへ ---
# from linebot import LineBotApi
# from linebot.models import TextSendMessage
from linebot.v3.messaging import MessagingApi, PushMessageRequest, TextMessage, FlexMessage, Configuration, ApiClient
from models.database import db, Task
from services.task_service import TaskService

class NotificationService:
    """通知サービスクラス"""
    
    def __init__(self):
        import os
        print(f"[DEBUG] (notification_service.py) LINE_CHANNEL_ACCESS_TOKEN: {os.getenv('LINE_CHANNEL_ACCESS_TOKEN')}")
        print(f"[DEBUG] (notification_service.py) os.environ: {os.environ}")
        if not os.getenv('LINE_CHANNEL_ACCESS_TOKEN'):
            print("[ERROR] LINE_CHANNEL_ACCESS_TOKENが環境変数に設定されていません！")
        # --- v3インスタンス生成 ---
        configuration = Configuration(access_token=os.environ['LINE_CHANNEL_ACCESS_TOKEN'])
        api_client = ApiClient(configuration)
        self.line_bot_api = MessagingApi(api_client)
        self.task_service = TaskService()
        self.scheduler_thread = None
        self.is_running = False
        # 重複実行防止用のタイムスタンプ
        self.last_notification_times = {}
        # データベース初期化
        from models.database import init_db
        self.db = init_db()

    def _check_duplicate_execution(self, notification_type: str, cooldown_minutes: int = 5) -> bool:
        """重複実行をチェックし、必要に応じて実行を防ぐ"""
        now = datetime.now()
        last_time = self.last_notification_times.get(notification_type)
        
        if last_time and (now - last_time).total_seconds() < cooldown_minutes * 60:
            print(f"[_check_duplicate_execution] {notification_type} の重複実行を防止: 前回実行から {(now - last_time).total_seconds():.1f}秒")
            return True
        
        self.last_notification_times[notification_type] = now
        return False

    def send_daily_task_notification(self):
        """毎日のタスク通知を送信（タスク一覧コマンドと同じ形式）"""
        print(f"[send_daily_task_notification] 開始: {datetime.now()}")
        
        # 重複実行防止チェック
        if self._check_duplicate_execution("daily_task_notification", cooldown_minutes=5):
            print(f"[send_daily_task_notification] 重複実行をスキップ")
            return
        
        user_ids = self._get_active_user_ids()
        print(f"[send_daily_task_notification] ユーザー数: {len(user_ids)}")
        for user_id in user_ids:
            try:
                print(f"[send_daily_task_notification] ユーザー {user_id} に送信中...")
                self._send_task_notification_to_user(user_id)
                print(f"[send_daily_task_notification] ユーザー {user_id} に送信完了")
            except Exception as e:
                print(f"[send_daily_task_notification] ユーザー {user_id} への送信エラー: {e}")
                import traceback
                traceback.print_exc()
        print(f"[send_daily_task_notification] 完了: {datetime.now()}")

    def _is_google_authenticated(self, user_id):
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

    def _get_google_auth_url(self, user_id):
        """Google認証URL生成"""
        return f"https://web-production-bf2e2.up.railway.app/google_auth?user_id={user_id}"

    def _move_overdue_tasks_to_today(self, user_id: str):
        """昨日の日付より前のタスクを今日の日付に移動"""
        try:
            # JSTで今日の日付を取得
            jst = pytz.timezone('Asia/Tokyo')
            today_str = datetime.now(jst).strftime('%Y-%m-%d')
            
            # ユーザーの全タスクを取得
            all_tasks = self.task_service.get_user_tasks(user_id)
            
            # 昨日より前のタスクを抽出
            overdue_tasks = []
            for task in all_tasks:
                if task.due_date and task.due_date < today_str:
                    overdue_tasks.append(task)
            
            # 期限切れタスクを今日の日付に更新
            for task in overdue_tasks:
                # 元のタスクをアーカイブ
                self.task_service.archive_task(task.task_id)
                # 今日の日付で新しいタスクを作成
                self.task_service.create_task(user_id, {
                    'name': task.name,
                    'duration_minutes': task.duration_minutes,
                    'repeat': task.repeat,
                    'due_date': today_str
                })
            
            if overdue_tasks:
                print(f"[{user_id}] {len(overdue_tasks)}個の期限切れタスクを今日に移動しました")
                return len(overdue_tasks)
            return 0
            
        except Exception as e:
            print(f"Error moving overdue tasks for user {user_id}: {e}")
            return 0

    def _send_task_notification_to_user(self, user_id: str):
        """特定ユーザーにタスク通知を送信"""
        try:
            # 期限切れタスクを今日に移動
            moved_count = self._move_overdue_tasks_to_today(user_id)
            
            # ユーザーのタスク一覧を取得
            all_tasks = self.task_service.get_user_tasks(user_id)
            
            # JSTで今日の日付を取得
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst)
            today_str = today.strftime('%Y-%m-%d')

            # タスクのdue_dateもJSTでパースしてdate型で比較
            today_tasks = []
            for t in all_tasks:
                try:
                    if not t.due_date:
                        continue
                    task_due = datetime.strptime(t.due_date, '%Y-%m-%d').date()
                    if task_due == today.date():
                        today_tasks.append(t)
                except Exception:
                    continue

            # --- ここでタスク選択モードフラグを必ず作成 ---
            import os
            select_flag = f"task_select_mode_{user_id}.flag"
            with open(select_flag, "w") as f:
                # 朝8時: スケジュール提案モード
                f.write("mode=schedule")
            print(f"[send_daily_task_notification] タスク選択モードフラグ作成: {select_flag}")

            # タスク一覧コマンドと同じ詳細な形式で送信（朝8時は「今日やるタスク」ガイド）
            morning_guide = "今日やるタスクを選んでください！\n例：１、３、５"
            message = self.task_service.format_task_list(all_tasks, show_select_guide=True, guide_text=morning_guide)
            # 期限切れタスクが移動された場合は通知を追加
            if moved_count > 0:
                message = f"⚠️ {moved_count}個の期限切れタスクを今日に移動しました\n\n" + message
            # LINEでメッセージを送信
            self.line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
            
        except Exception as e:
            print(f"Error sending notification to user {user_id}: {e}")

    def send_schedule_reminder(self, user_id: str, schedule_info: str):
        """スケジュールリマインダーを送信"""
        try:
            message = f"⏰ スケジュールリマインダー\n\n{schedule_info}\n\n準備を始めましょう！"
            self.line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
            
        except Exception as e:
            print(f"Error sending schedule reminder: {e}")

    def send_task_completion_reminder(self, user_id: str, task_name: str):
        """タスク完了リマインダーを送信"""
        try:
            message = f"✅ タスク完了確認\n\n「{task_name}」は完了しましたか？\n\n完了した場合は「完了」と返信してください。"
            self.line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
            
        except Exception as e:
            print(f"Error sending completion reminder: {e}")

    def send_weekly_report(self, user_id: str):
        """週次レポートを送信"""
        try:
            # 過去1週間のタスク完了状況を取得
            completed_tasks = self._get_completed_tasks_this_week(user_id)
            total_tasks = len(completed_tasks)
            
            message = f"📊 週次レポート\n\n今週完了したタスク: {total_tasks}個\n\n"
            
            if completed_tasks:
                message += "完了したタスク:\n"
                for task in completed_tasks[:5]:  # 最大5個まで表示
                    message += f"• {task.name}\n"
                
                if len(completed_tasks) > 5:
                    message += f"... 他 {len(completed_tasks) - 5}個\n"
            else:
                message += "今週は完了したタスクがありません。\n"
            
            message += "\n来週も頑張りましょう！"
            
            self.line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
            
        except Exception as e:
            print(f"Error sending weekly report: {e}")

    def start_scheduler(self):
        """スケジューラーを開始"""
        if self.is_running:
            print(f"[start_scheduler] スケジューラーは既に動作中: {datetime.now()}")
            return
        
        # スレッドが既に存在する場合は待機
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            print(f"[start_scheduler] スケジューラースレッドは既に動作中: {datetime.now()}")
            return
            
        self.is_running = True
        
        print(f"[start_scheduler] スケジューラー開始: {datetime.now()}")
        
        # Railway等UTCサーバーの場合、JST 8:00 = UTC 23:00、JST 21:00 = UTC 12:00、JST 18:00 = UTC 09:00
        schedule.every().day.at("23:00").do(self.send_daily_task_notification)  # JST 8:00
        schedule.every().sunday.at("09:00").do(self.send_future_task_selection)  # JST 18:00
        schedule.every().sunday.at("11:00").do(self._send_weekly_reports_to_all_users)  # JST 20:00→UTC 11:00
        schedule.every().day.at("12:00").do(self.send_carryover_check)  # JST 21:00
        
        print(f"[start_scheduler] スケジュール設定完了:")
        print(f"[start_scheduler] - 毎日 23:00 UTC (JST 8:00): タスク一覧通知")
        print(f"[start_scheduler] - 毎日 12:00 UTC (JST 21:00): タスク確認通知")
        print(f"[start_scheduler] - 日曜 09:00 UTC (JST 18:00): 未来タスク選択通知")
        print(f"[start_scheduler] - 日曜 11:00 UTC (JST 20:00): 週次レポート")
        
        # 現在時刻と次の実行時刻を表示
        import pytz
        utc_now = datetime.now(pytz.UTC)
        jst_now = datetime.now(pytz.timezone('Asia/Tokyo'))
        print(f"[start_scheduler] 現在時刻 - UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[start_scheduler] 現在時刻 - JST: {jst_now.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 次の実行時刻を計算
        next_8am_jst = jst_now.replace(hour=8, minute=0, second=0, microsecond=0)
        if jst_now.hour >= 8:
            next_8am_jst += timedelta(days=1)
        
        next_6pm_jst = jst_now.replace(hour=18, minute=0, second=0, microsecond=0)
        if jst_now.hour >= 18:
            next_6pm_jst += timedelta(days=1)
        
        next_9pm_jst = jst_now.replace(hour=21, minute=0, second=0, microsecond=0)
        if jst_now.hour >= 21:
            next_9pm_jst += timedelta(days=1)
        
        print(f"[start_scheduler] 次回8時通知予定: {next_8am_jst.strftime('%Y-%m-%d %H:%M:%S')} JST")
        print(f"[start_scheduler] 次回18時通知予定: {next_6pm_jst.strftime('%Y-%m-%d %H:%M:%S')} JST")
        print(f"[start_scheduler] 次回21時通知予定: {next_9pm_jst.strftime('%Y-%m-%d %H:%M:%S')} JST")
        
        # スケジューラーを別スレッドで実行
        self.scheduler_thread = threading.Thread(target=self._run_scheduler)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        print(f"[start_scheduler] スケジューラースレッド開始完了")

    def stop_scheduler(self):
        """スケジューラーを停止"""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join()

    def _run_scheduler(self):
        """スケジューラーの実行"""
        print(f"[_run_scheduler] スケジューラーループ開始: {datetime.now()}")
        check_count = 0
        while self.is_running:
            try:
                check_count += 1
                if check_count % 10 == 0:  # 10分ごとにログ出力
                    print(f"[_run_scheduler] スケジューラー動作中: {datetime.now()}, チェック回数: {check_count}")
                
                schedule.run_pending()
                time.sleep(60)  # 1分ごとにチェック
            except Exception as e:
                print(f"[_run_scheduler] スケジューラーエラー: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(60)  # エラーが発生しても1分後に再試行
        print(f"[_run_scheduler] スケジューラーループ終了: {datetime.now()}")

    def _get_active_user_ids(self) -> List[str]:
        """
        アクティブなユーザーID一覧を取得（DBから取得）
        """
        try:
            from models.database import init_db
            db_instance = init_db()
            return db_instance.get_all_user_ids()
        except Exception as e:
            print(f"Error getting active user ids: {e}")
            return []

    def _send_weekly_reports_to_all_users(self):
        """全ユーザーに週次レポートを送信"""
        print(f"[_send_weekly_reports_to_all_users] 開始: {datetime.now()}")
        
        # 重複実行防止チェック
        if self._check_duplicate_execution("weekly_reports", cooldown_minutes=5):
            print(f"[_send_weekly_reports_to_all_users] 重複実行をスキップ")
            return
        
        user_ids = self._get_active_user_ids()
        for user_id in user_ids:
            self.send_weekly_report(user_id)
        print(f"[_send_weekly_reports_to_all_users] 完了: {datetime.now()}")

    def _get_completed_tasks_this_week(self, user_id: str) -> List[Task]:
        """今週完了したタスクを取得"""
        # 実際の実装では、完了日時を記録するテーブルが必要
        # ここでは簡略化のため、空のリストを返す
        return []

    def send_custom_notification(self, user_id: str, message: str):
        """カスタム通知を送信（APIレスポンスをprint）"""
        try:
            res = self.line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
            print(f"[send_custom_notification] push_message response: {res}")
        except Exception as e:
            print(f"Error sending custom notification: {e}")
            import traceback
            traceback.print_exc()

    def send_error_notification(self, user_id: str, error_message: str):
        """エラー通知を送信"""
        try:
            message = f"⚠️ エラーが発生しました\n\n{error_message}\n\nしばらく時間をおいて再度お試しください。"
            self.line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
        except Exception as e:
            print(f"Error sending error notification: {e}")

    def send_help_message(self, user_id: str):
        """ヘルプメッセージをFlex Messageで送信"""
        from linebot.models import FlexSendMessage
        flex_message = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "ご利用ありがとうございます！", "weight": "bold", "size": "lg", "margin": "md"},
                    {"type": "text", "text": "主な機能は下記のボタンからご利用いただけます。", "size": "md", "margin": "md", "color": "#666666"}
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
                    },
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "スケジュール確認", "text": "タスク確認"},
                        "style": "secondary"
                    },
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "スケジュール修正", "text": "スケジュール修正"},
                        "style": "secondary"
                    }
                ]
            }
        }
        try:
            self.line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[FlexMessage(alt_text="ご利用案内・操作メニュー", contents=flex_message)]
                )
            )
        except Exception as e:
            print(f"Error sending help message: {e}")

    def send_carryover_check(self):
        """毎日21時に今日のタスク確認（タスク確認コマンドと同じ形式）"""
        print(f"[send_carryover_check] 開始: {datetime.now()}")
        
        # 重複実行防止チェック
        if self._check_duplicate_execution("carryover_check", cooldown_minutes=5):
            print(f"[send_carryover_check] 重複実行をスキップ")
            return
        
        import pytz
        user_ids = self._get_active_user_ids()
        print(f"[send_carryover_check] ユーザー数: {len(user_ids)}")
        jst = pytz.timezone('Asia/Tokyo')
        today_str = datetime.now(jst).strftime('%Y-%m-%d')
        print(f"[send_carryover_check] 今日の日付: {today_str}")
        for user_id in user_ids:
            try:
                print(f"[send_carryover_check] ユーザー {user_id} に送信中...")
                tasks = self.task_service.get_user_tasks(user_id)
                today_tasks = [t for t in tasks if t.due_date == today_str]
                print(f"[send_carryover_check] 今日のタスク数: {len(today_tasks)}")
                if not today_tasks:
                    msg = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n本日分のタスクはありません。\n＝＝＝＝＝＝"
                else:
                    msg = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n"
                    for idx, t in enumerate(today_tasks, 1):
                        msg += f"{idx}. {t.name} ({t.duration_minutes}分)\n"
                    msg += "＝＝＝＝＝＝\n終わったタスクを選んでください！\n例：１、３、５"
                    
                    # タスク選択モードフラグを作成
                    import os
                    select_flag = f"task_select_mode_{user_id}.flag"
                    with open(select_flag, "w") as f:
                        # 21時: 完了（削除確認）モード
                        f.write("mode=complete")
                    print(f"[send_carryover_check] タスク選択モードフラグ作成: {select_flag}")
                
                print(f"[send_carryover_check] メッセージ送信: {msg[:100]}...")
                self.line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=msg)]))
                print(f"[send_carryover_check] ユーザー {user_id} に送信完了")
            except Exception as e:
                print(f"[send_carryover_check] ユーザー {user_id} への送信エラー: {e}")
                import traceback
                traceback.print_exc()
        print(f"[send_carryover_check] 完了: {datetime.now()}")

    def send_future_task_selection(self):
        """未来タスク選択通知を送信（毎週日曜日18時）"""
        print(f"[send_future_task_selection] 開始: {datetime.now()}")
        
        # 重複実行防止チェック
        if self._check_duplicate_execution("future_task_selection", cooldown_minutes=5):
            print(f"[send_future_task_selection] 重複実行をスキップ")
            return
        
        try:
            user_ids = self._get_active_user_ids()
            print(f"[send_future_task_selection] ユーザー数: {len(user_ids)}")
            for user_id in user_ids:
                try:
                    print(f"[send_future_task_selection] ユーザー {user_id} に送信中...")
                    
                    # 未来タスク一覧を取得
                    future_tasks = self.task_service.get_user_future_tasks(user_id)
                    print(f"[send_future_task_selection] 未来タスク数: {len(future_tasks)}")
                    
                    if not future_tasks:
                        message = "⭐未来タスク一覧\n━━━━━━━━━━━━\n登録されている未来タスクはありません。\n\n新しい未来タスクを追加してください！\n例: 「新規事業を考える 2時間」"
                    else:
                        message = self.task_service.format_future_task_list(future_tasks, show_select_guide=True)
                        
                        # 未来タスク選択モードファイルを作成
                        import os
                        future_selection_file = f"future_task_selection_{user_id}.json"
                        with open(future_selection_file, "w") as f:
                            import json
                            json.dump({"mode": "future_selection", "timestamp": datetime.now().isoformat()}, f)
                    
                    print(f"[send_future_task_selection] メッセージ送信: {message[:100]}...")
                    self.line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=message)]))
                    print(f"[send_future_task_selection] ユーザー {user_id} に送信完了")
                    
                except Exception as e:
                    print(f"[send_future_task_selection] ユーザー {user_id} への送信エラー: {e}")
                    import traceback
                    traceback.print_exc()
            print(f"[send_future_task_selection] 完了: {datetime.now()}")
        except Exception as e:
            print(f"Error sending future task selection: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    from models.database import init_db
    init_db()
    n = NotificationService()
    n.start_scheduler()
    print("通知スケジューラーを起動しました")
    import time
    while True:
        time.sleep(60) 