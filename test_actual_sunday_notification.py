#!/usr/bin/env python3
"""
実際の日曜18時通知送信テスト
"""

import os
import sys
from datetime import datetime
from services.notification_service import NotificationService
from models.database import init_db
from services.task_service import TaskService

def test_actual_sunday_notification():
    """実際の日曜18時通知送信テスト"""
    print("=== 実際の日曜18時通知送信テスト開始 ===")
    
    # 環境変数設定（環境変数から読み込む - ハードコードしない）
    if not os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'):
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN environment variable is required")
    if not os.environ.get('LINE_CHANNEL_SECRET'):
        raise ValueError("LINE_CHANNEL_SECRET environment variable is required")
    
    # データベース初期化
    db = init_db()
    task_service = TaskService(db)
    
    # テスト用ユーザーID
    test_user_id = "test_actual_sunday_user_123"
    
    try:
        # 未来タスクを追加
        print(f"\n--- 未来タスク追加 ---")
        task_info = {
            'name': '来週の新規事業計画',
            'duration_minutes': 120,
            'priority': 'high'
        }
        
        future_task = task_service.create_future_task(test_user_id, task_info)
        print(f"未来タスク作成: {future_task.task_id if future_task else '失敗'}")
        
        # 通知サービス初期化
        notification_service = NotificationService()
        
        # 実際の日曜18時通知を送信
        print(f"\n--- 実際の日曜18時通知送信 ---")
        notification_service.send_future_task_selection()
        
        print("\n=== 実際の日曜18時通知送信テスト完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_actual_sunday_notification()
    sys.exit(0 if success else 1)
