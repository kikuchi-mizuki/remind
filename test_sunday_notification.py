#!/usr/bin/env python3
"""
日曜18時通知のテストスクリプト
"""

import os
import sys
from datetime import datetime, timedelta
from services.notification_service import NotificationService
from models.database import init_db
from services.task_service import TaskService

def test_sunday_notification():
    """日曜18時通知のテスト"""
    print("=== 日曜18時通知テスト開始 ===")
    
    # 環境変数設定（環境変数から読み込む - ハードコードしない）
    if not os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'):
        raise ValueError("LINE_CHANNEL_ACCESS_TOKEN environment variable is required")
    if not os.environ.get('LINE_CHANNEL_SECRET'):
        raise ValueError("LINE_CHANNEL_SECRET environment variable is required")
    
    # データベース初期化
    db = init_db()
    task_service = TaskService(db)
    
    # テスト用ユーザーID
    test_user_id = "test_sunday_user_123"
    
    try:
        # 未来タスクを追加
        print(f"\n--- 未来タスク追加テスト ---")
        task_info = {
            'name': '来週の新規事業計画',
            'duration_minutes': 120,
            'priority': 'high'
        }
        
        future_task = task_service.create_future_task(test_user_id, task_info)
        print(f"未来タスク作成: {future_task.task_id if future_task else '失敗'}")
        
        # 未来タスク一覧を取得
        future_tasks = task_service.get_user_future_tasks(test_user_id)
        print(f"未来タスク数: {len(future_tasks)}")
        
        # 通知サービス初期化
        notification_service = NotificationService()
        
        # 日曜18時通知の内容を生成
        print(f"\n--- 日曜18時通知内容生成 ---")
        
        # 未来タスク一覧をフォーマット
        if future_tasks:
            reply_text = "🔮 来週の未来タスク選択\n"
            reply_text += "＝＝＝＝＝＝\n"
            for i, task in enumerate(future_tasks, 1):
                reply_text += f"{i}. {task.name} ({task.duration_minutes}分)\n"
            reply_text += "＝＝＝＝＝＝\n"
            reply_text += "📝 選択したいタスクの番号を送信してください！\n"
            reply_text += "例：「1,3」で1番と3番を選択"
        else:
            reply_text = "🔮 来週の未来タスク選択\n"
            reply_text += "＝＝＝＝＝＝\n"
            reply_text += "未来タスクがありません。\n"
            reply_text += "「未来タスク追加」でタスクを追加してください。\n"
            reply_text += "＝＝＝＝＝＝"
        
        print("生成された通知内容:")
        print("---")
        print(reply_text)
        print("---")
        
        # 実際の通知送信（コメントアウト）
        # print(f"\n--- 実際の通知送信 ---")
        # success = notification_service.send_message_to_user(test_user_id, reply_text)
        # print(f"通知送信結果: {success}")
        
        print("\n=== 日曜18時通知テスト完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_sunday_notification()
    sys.exit(0 if success else 1)
