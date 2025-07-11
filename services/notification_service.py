import os
import schedule
import time
import threading
from datetime import datetime, timedelta
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
        """毎日のタスク通知を送信"""
        try:
            # 全ユーザーのタスクを取得（実際の実装では、ユーザー管理が必要）
            # ここでは簡略化のため、固定のユーザーIDを使用
            user_ids = self._get_active_user_ids()
            
            for user_id in user_ids:
                self._send_task_notification_to_user(user_id)
                
        except Exception as e:
            print(f"Error sending daily notifications: {e}")

    def _send_task_notification_to_user(self, user_id: str):
        """特定ユーザーにタスク通知を送信"""
        try:
            # ユーザーのタスク一覧を取得
            tasks = self.task_service.get_user_tasks(user_id)
            
            if not tasks:
                message = "📋 今日のタスク\n\n登録されているタスクはありません。\n\n新しいタスクを登録してください！\n例: 「筋トレ 20分 毎日」"
            else:
                message = self.task_service.format_task_list(tasks)
            
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
        
        # 毎朝8時にタスク通知
        schedule.every().day.at("08:00").do(self.send_daily_task_notification)
        
        # 毎週日曜日の20時に週次レポート
        schedule.every().sunday.at("20:00").do(self._send_weekly_reports_to_all_users)
        
        # スケジューラーを別スレッドで実行
        self.scheduler_thread = threading.Thread(target=self._run_scheduler)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()

    def stop_scheduler(self):
        """スケジューラーを停止"""
        self.is_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join()

    def _run_scheduler(self):
        """スケジューラーの実行"""
        while self.is_running:
            schedule.run_pending()
            time.sleep(60)  # 1分ごとにチェック

    def _get_active_user_ids(self) -> List[str]:
        """アクティブなユーザーID一覧を取得"""
        # 実際の実装では、データベースからユーザー一覧を取得
        # ここでは簡略化のため、環境変数から取得
        user_ids_str = os.getenv('ACTIVE_USER_IDS', '')
        if user_ids_str:
            return user_ids_str.split(',')
        return []

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
        """カスタム通知を送信"""
        try:
            self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
        except Exception as e:
            print(f"Error sending custom notification: {e}")

    def send_error_notification(self, user_id: str, error_message: str):
        """エラー通知を送信"""
        try:
            message = f"⚠️ エラーが発生しました\n\n{error_message}\n\nしばらく時間をおいて再度お試しください。"
            self.line_bot_api.push_message(user_id, TextSendMessage(text=message))
        except Exception as e:
            print(f"Error sending error notification: {e}")

    def send_help_message(self, user_id: str):
        """ヘルプメッセージを送信"""
        help_message = """🤖 LINEタスクスケジューリングBot

【使い方】

📝 タスク登録
例: 「筋トレ 20分 毎日」
例: 「買い物 30分」

📅 スケジュール確認
毎朝8時に今日のタスク一覧をお送りします

✅ スケジュール承認
提案されたスケジュールに「承認」と返信

🔄 スケジュール修正
例: 「筋トレを15時に変更して」

📊 週次レポート
毎週日曜日の20時に週次レポートをお送りします

何かご質問がございましたら、お気軽にお聞きください！"""
        
        try:
            self.line_bot_api.push_message(user_id, TextSendMessage(text=help_message))
        except Exception as e:
            print(f"Error sending help message: {e}") 