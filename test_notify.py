from services.notification_service import NotificationService
from models.database import init_db

if __name__ == "__main__":
    init_db()
    n = NotificationService()
    n.send_daily_task_notification()  # 8時の通知テスト
    print("テスト通知を送信しました") 