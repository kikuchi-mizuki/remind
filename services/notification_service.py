import os
import schedule
import time
import threading
from datetime import datetime, timedelta
import pytz
from typing import List
from linebot import LineBotApi
from linebot.models import TextSendMessage
from models.database import db, Task
from services.task_service import TaskService

class NotificationService:
    """通知サービスクラス"""
    
    def __init__(self):
        self.line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
        self.task_service = TaskService()
        self.scheduler_thread = None
        self.is_running = False

    def send_daily_task_notification(self):
        """毎日のタスク通知を送信（タスク一覧コマンドと同じ形式）"""
        print(f"[send_daily_task_notification] 開始: {datetime.now()}")
        try:
            user_ids = self._get_active_user_ids()
            print(f"[send_daily_task_notification] ユーザー数: {len(user_ids)}")
            for user_id in user_ids:
                try:
                    print(f"[send_daily_task_notification] ユーザー {user_id} に送信中...")
                    # タスク一覧を取得
                    all_tasks = self.task_service.get_user_tasks(user_id)
                    print(f"[send_daily_task_notification] タスク数: {len(all_tasks)}")
                    # タスク一覧コマンドと同じ形式で出力
                    message = self.task_service.format_task_list(all_tasks, show_select_guide=True)
                    print(f"[send_daily_task_notification] メッセージ送信: {message[:100]}...")
                    self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
                    print(f"[send_daily_task_notification] ユーザー {user_id} に送信完了")
                except Exception as e:
                    print(f"[send_daily_task_notification] ユーザー {user_id} への送信エラー: {e}")
                    import traceback
                    traceback.print_exc()
            print(f"[send_daily_task_notification] 完了: {datetime.now()}")
        except Exception as e:
            print(f"Error sending daily notifications: {e}")
            import traceback
            traceback.print_exc()

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
            today_str = datetime.now(jst).strftime('%Y-%m-%d')
            
            # 今日が期日のタスクのみ抽出
            today_tasks = [t for t in all_tasks if t.due_date == today_str]
            
            if not today_tasks:
                message = "📋 今日のタスク\n\n本日分のタスクはありません。\n\n新しいタスクを登録してください！\n例: 「筋トレ 20分 明日」"
            else:
                message = self.task_service.format_task_list(today_tasks, show_select_guide=False)
                
                # 期限切れタスクが移動された場合は通知を追加
                if moved_count > 0:
                    message = f"📋 今日のタスク\n\n⚠️ {moved_count}個の期限切れタスクを今日に移動しました\n\n" + message
            
            # LINEでメッセージを送信
            self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
            
        except Exception as e:
            print(f"Error sending notification to user {user_id}: {e}")

    def send_schedule_reminder(self, user_id: str, schedule_info: str):
        """スケジュールリマインダーを送信"""
        try:
            message = f"⏰ スケジュールリマインダー\n\n{schedule_info}\n\n準備を始めましょう！"
            self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
            
        except Exception as e:
            print(f"Error sending schedule reminder: {e}")

    def send_task_completion_reminder(self, user_id: str, task_name: str):
        """タスク完了リマインダーを送信"""
        try:
            message = f"✅ タスク完了確認\n\n「{task_name}」は完了しましたか？\n\n完了した場合は「完了」と返信してください。"
            self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
            
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
            
            self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
            
        except Exception as e:
            print(f"Error sending weekly report: {e}")

    def start_scheduler(self):
        """スケジューラーを開始"""
        if self.is_running:
            return
        self.is_running = True
        
        print(f"[start_scheduler] スケジューラー開始: {datetime.now()}")
        
        # Railway等UTCサーバーの場合、JST 8:00 = UTC 23:00、JST 21:00 = UTC 12:00
        schedule.every().day.at("23:00").do(self.send_daily_task_notification)  # JST 8:00
        schedule.every().sunday.at("11:00").do(self._send_weekly_reports_to_all_users)  # JST 20:00→UTC 11:00
        schedule.every().day.at("12:00").do(self.send_carryover_check)  # JST 21:00
        
        print(f"[start_scheduler] スケジュール設定完了:")
        print(f"[start_scheduler] - 毎日 23:00 UTC (JST 8:00): タスク一覧通知")
        print(f"[start_scheduler] - 毎日 12:00 UTC (JST 21:00): タスク確認通知")
        print(f"[start_scheduler] - 日曜 11:00 UTC (JST 20:00): 週次レポート")
        
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
        while self.is_running:
            try:
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
        return db.get_all_user_ids()

    def _send_weekly_reports_to_all_users(self):
        """全ユーザーに週次レポートを送信"""
        user_ids = self._get_active_user_ids()
        for user_id in user_ids:
            self.send_weekly_report(user_id)

    def _get_completed_tasks_this_week(self, user_id: str) -> List[Task]:
        """今週完了したタスクを取得"""
        # 実際の実装では、完了日時を記録するテーブルが必要
        # ここでは簡略化のため、空のリストを返す
        return []

    def send_custom_notification(self, user_id: str, message: str):
        """カスタム通知を送信（APIレスポンスをprint）"""
        try:
            res = self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
            print(f"[send_custom_notification] push_message response: {res}")
        except Exception as e:
            print(f"Error sending custom notification: {e}")
            import traceback
            traceback.print_exc()

    def send_error_notification(self, user_id: str, error_message: str):
        """エラー通知を送信"""
        try:
            message = f"⚠️ エラーが発生しました\n\n{error_message}\n\nしばらく時間をおいて再度お試しください。"
            self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
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
                user_id,
                FlexSendMessage(
                    alt_text="ご利用案内・操作メニュー",
                    contents=flex_message
                )
            )
        except Exception as e:
            print(f"Error sending help message: {e}")

    def send_carryover_check(self):
        """毎日21時に今日のタスク確認（タスク確認コマンドと同じ形式）"""
        print(f"[send_carryover_check] 開始: {datetime.now()}")
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
                print(f"[send_carryover_check] メッセージ送信: {msg[:100]}...")
                self.line_bot_api.push_message(user_id, TextSendMessage(text=msg))
                print(f"[send_carryover_check] ユーザー {user_id} に送信完了")
            except Exception as e:
                print(f"[send_carryover_check] ユーザー {user_id} への送信エラー: {e}")
                import traceback
                traceback.print_exc()
        print(f"[send_carryover_check] 完了: {datetime.now()}") 

if __name__ == "__main__":
    from models.database import init_db
    init_db()
    n = NotificationService()
    n.start_scheduler()
    print("通知スケジューラーを起動しました")
    import time
    while True:
        time.sleep(60) 