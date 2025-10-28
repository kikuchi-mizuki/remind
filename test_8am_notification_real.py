#!/usr/bin/env python3
"""
実際の8時通知テスト（本番環境用）
"""

import os
import sys
from datetime import datetime
from services.notification_service import NotificationService
from models.database import init_db
from services.task_service import TaskService

def test_8am_notification_real():
    """実際の8時通知テスト"""
    print("=== 実際の8時通知テスト開始 ===")
    
    # 環境変数設定
    os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = "IkHMQ9ofRKSSn4lPbYsnzwBJv1VrNBAJkfgiFOgSUSfN6cYbYIxx6mr2iK04qfN/567RLIM+AjkVuFepihrlPaf++IiiFnL43PaMqChddnkCfDItoXMydZj7l0hgzjHe4hE5wQQlODhNqBZ6hHo+XwdB04t89/1O/w1cDnyilFU="
    os.environ['LINE_CHANNEL_SECRET'] = "0458a82f5e85976cd037016936a1bba3"
    
    # データベース初期化
    db = init_db()
    task_service = TaskService(db)
    
    # テスト用ユーザーID（実際のユーザーIDに変更してください）
    test_user_id = "test_normal_user_123"  # 先ほど作成したユーザー
    
    try:
        # 通知サービス初期化
        notification_service = NotificationService()
        
        # 実際の8時通知を送信
        print(f"\n--- 実際の8時通知送信 ---")
        notification_service._send_task_notification_to_user(test_user_id)
        
        print("\n=== 実際の8時通知テスト完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_8am_notification_real()
    sys.exit(0 if success else 1)
