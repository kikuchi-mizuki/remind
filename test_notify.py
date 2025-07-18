#!/usr/bin/env python3
import os
import sys
from datetime import datetime
import pytz

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.notification_service import NotificationService
from models.database import init_db

def test_notification():
    """通知のテスト"""
    print("=== 通知テスト開始 ===")
    
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
    
    # テストユーザーに通知送信
    test_user_id = user_ids[0]
    print(f"テストユーザー {test_user_id} に通知送信")
    
    try:
        # 手動通知テスト
        message = f"🧪 手動通知テスト\n\n時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nこの通知が届けば、通知システムは正常に動作しています。"
        notification_service.send_custom_notification(test_user_id, message)
        print("✅ 手動通知送信完了")
        
        # タスク一覧通知テスト
        print("タスク一覧通知を送信中...")
        notification_service.send_daily_task_notification()
        print("✅ タスク一覧通知送信完了")
        
    except Exception as e:
        print(f"❌ 通知送信エラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("=== 通知テスト完了 ===")

if __name__ == "__main__":
    test_notification() 