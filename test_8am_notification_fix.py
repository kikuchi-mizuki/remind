#!/usr/bin/env python3
"""
8時通知の修正テストスクリプト
"""

import os
import sys
from datetime import datetime, timedelta
from services.notification_service import NotificationService
from models.database import init_db
from services.task_service import TaskService

def test_8am_notification_fix():
    """8時通知の修正テスト"""
    print("=== 8時通知修正テスト開始 ===")
    
    # 環境変数設定
    os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = "IkHMQ9ofRKSSn4lPbYsnzwBJv1VrNBAJkfgiFOgSUSfN6cYbYIxx6mr2iK04qfN/567RLIM+AjkVuFepihrlPaf++IiiFnL43PaMqChddnkCfDItoXMydZj7l0hgzjHe4hE5wQQlODhNqBZ6hHo+XwdB04t89/1O/w1cDnyilFU="
    os.environ['LINE_CHANNEL_SECRET'] = "0458a82f5e85976cd037016936a1bba3"
    
    # データベース初期化
    db = init_db()
    task_service = TaskService(db)
    
    # テスト用ユーザーID
    test_user_id = "test_8am_fix_user_123"
    
    try:
        # 今日のタスクを追加
        print(f"\n--- 今日のタスク追加テスト ---")
        task_info = {
            'name': '今日の会議準備',
            'duration_minutes': 60,
            'priority': 'high',
            'due_date': datetime.now().strftime('%Y-%m-%d')
        }
        
        today_task = task_service.create_task(test_user_id, task_info)
        print(f"今日のタスク作成: {today_task.task_id if today_task else '失敗'}")
        
        # 通知サービス初期化
        notification_service = NotificationService()
        
        # 8時通知の内容を生成
        print(f"\n--- 8時通知内容生成テスト ---")
        
        # 今日のタスクを取得
        all_tasks = task_service.get_user_tasks(test_user_id)
        print(f"全タスク数: {len(all_tasks)}")
        
        # 今日のタスクのみをフィルタリング
        import pytz
        jst = pytz.timezone('Asia/Tokyo')
        today = datetime.now(jst)
        today_str = today.strftime('%Y-%m-%d')
        
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
        
        print(f"今日のタスク数: {len(today_tasks)}")
        
        # 8時通知のメッセージを生成
        morning_guide = "今日やるタスクを選んでください！\n例：１、３、５"
        if today_tasks:
            message = task_service.format_task_list(today_tasks, show_select_guide=True, guide_text=morning_guide)
        else:
            message = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n本日分のタスクはありません。\n＝＝＝＝＝＝"
        
        print("生成された8時通知内容:")
        print("---")
        print(message)
        print("---")
        
        # タスクがない場合のテスト
        print(f"\n--- タスクなしの場合のテスト ---")
        empty_message = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n本日分のタスクはありません。\n＝＝＝＝＝＝"
        print("タスクなしの場合のメッセージ:")
        print("---")
        print(empty_message)
        print("---")
        
        print("\n=== 8時通知修正テスト完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_8am_notification_fix()
    sys.exit(0 if success else 1)
