#!/usr/bin/env python3
"""
8時通知修正のテスト
"""

import os
import sys
from datetime import datetime
from services.notification_service import NotificationService
from models.database import init_db
from services.task_service import TaskService

def test_8am_fix():
    """8時通知修正のテスト"""
    print("=== 8時通知修正テスト開始 ===")
    
    # 環境変数設定
    os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = "IkHMQ9ofRKSSn4lPbYsnzwBJv1VrNBAJkfgiFOgSUSfN6cYbYIxx6mr2iK04qfN/567RLIM+AjkVuFepihrlPaf++IiiFnL43PaMqChddnkCfDItoXMydZj7l0hgzjHe4hE5wQQlODhNqBZ6hHo+XwdB04t89/1O/w1cDnyilFU="
    os.environ['LINE_CHANNEL_SECRET'] = "0458a82f5e85976cd037016936a1bba3"
    
    # データベース初期化
    db = init_db()
    task_service = TaskService(db)
    
    # テスト用ユーザーID
    test_user_id = "test_normal_user_123"  # 先ほど作成したユーザー
    
    try:
        # 通知サービス初期化
        notification_service = NotificationService()
        
        # 8時通知を送信
        print(f"\n--- 8時通知送信テスト ---")
        notification_service.send_daily_task_notification()
        
        print("\n=== 8時通知修正テスト完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_8am_fix()
    sys.exit(0 if success else 1)
