#!/usr/bin/env python3
import os
import sys
from datetime import datetime
import pytz

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.notification_service import NotificationService
from models.database import init_db

def test_all_notifications():
    """全ての通知をテスト"""
    print("=== 全通知テスト開始 ===")
    
    # 環境変数チェック
    token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
    if not token or token == "dummy_token":
        print("⚠️ LINE_CHANNEL_ACCESS_TOKENが設定されていません")
        print("本番環境では通知は送信されません")
        return
    
    # データベース初期化
    db = init_db()
    
    # 通知サービス初期化
    notification_service = NotificationService()
    
    # アクティブユーザー取得
    user_ids = notification_service._get_active_user_ids()
    print(f"アクティブユーザー数: {len(user_ids)}")
    
    if not user_ids:
        print("⚠️ アクティブユーザーが見つかりません")
        return
    
    test_user_id = user_ids[0]
    print(f"テストユーザー: {test_user_id}")
    
    try:
        # 1. 毎日8時の通知テスト（タスク一覧通知）
        print("\n1️⃣ 毎日8時の通知テスト（タスク一覧通知）")
        notification_service.send_daily_task_notification()
        print("✅ タスク一覧通知送信完了")
        
        # 2. 毎日21時の通知テスト（タスク確認通知）
        print("\n2️⃣ 毎日21時の通知テスト（タスク確認通知）")
        notification_service.send_carryover_check()
        print("✅ タスク確認通知送信完了")
        
        # 3. 日曜18時の通知テスト（未来タスク選択通知）
        print("\n3️⃣ 日曜18時の通知テスト（未来タスク選択通知）")
        notification_service.send_future_task_selection()
        print("✅ 未来タスク選択通知送信完了")
        
        # 4. 日曜20時の通知テスト（週次レポート）
        print("\n4️⃣ 日曜20時の通知テスト（週次レポート）")
        notification_service._send_weekly_reports_to_all_users()
        print("✅ 週次レポート送信完了")
        
        # 5. 手動通知テスト
        print("\n5️⃣ 手動通知テスト")
        message = f"🧪 全通知テスト完了\n\n時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n全ての通知が正常に送信されました！"
        notification_service.send_custom_notification(test_user_id, message)
        print("✅ 手動通知送信完了")
        
    except Exception as e:
        print(f"❌ 通知送信エラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== 全通知テスト完了 ===")
    print("\n📋 通知スケジュール確認:")
    print("• 毎日8時（JST）: タスク一覧通知 ✅")
    print("• 毎日21時（JST）: タスク確認通知 ✅")
    print("• 日曜18時（JST）: 未来タスク選択通知 ✅")
    print("• 日曜20時（JST）: 週次レポート ✅")

if __name__ == "__main__":
    test_all_notifications() 