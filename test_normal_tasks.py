#!/usr/bin/env python3
"""
通常タスクの追加と8時通知テスト
"""

import os
import sys
from datetime import datetime, timedelta
from models.database import init_db
from services.task_service import TaskService

def test_normal_tasks():
    """通常タスクの追加と8時通知テスト"""
    print("=== 通常タスク追加と8時通知テスト ===")
    
    # データベース初期化
    db = init_db()
    task_service = TaskService(db)
    
    # テスト用ユーザーID
    test_user_id = "test_normal_user_123"
    
    try:
        # 通常タスクを追加
        print(f"\n--- 通常タスク追加 ---")
        
        # 今日のタスク
        today_task = task_service.create_task(test_user_id, {
            'name': '今日の会議準備',
            'duration_minutes': 60,
            'priority': 'high',
            'due_date': datetime.now().strftime('%Y-%m-%d'),
            'repeat': False
        })
        print(f"今日のタスク作成: {today_task.task_id if today_task else '失敗'}")
        
        # 明日のタスク
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_task = task_service.create_task(test_user_id, {
            'name': '明日の資料作成',
            'duration_minutes': 90,
            'priority': 'normal',
            'due_date': tomorrow.strftime('%Y-%m-%d'),
            'repeat': False
        })
        print(f"明日のタスク作成: {tomorrow_task.task_id if tomorrow_task else '失敗'}")
        
        # 来週のタスク
        next_week = datetime.now() + timedelta(days=7)
        next_week_task = task_service.create_task(test_user_id, {
            'name': '来週のプレゼン準備',
            'duration_minutes': 120,
            'priority': 'urgent_important',
            'due_date': next_week.strftime('%Y-%m-%d'),
            'repeat': False
        })
        print(f"来週のタスク作成: {next_week_task.task_id if next_week_task else '失敗'}")
        
        # タスク一覧を取得
        print(f"\n--- タスク一覧確認 ---")
        all_tasks = task_service.get_user_tasks(test_user_id)
        print(f"全タスク数: {len(all_tasks)}")
        
        for i, task in enumerate(all_tasks, 1):
            print(f"  {i}. {task.name} (期限: {task.due_date}, 優先度: {task.priority}, タイプ: {task.task_type})")
        
        # 8時通知のメッセージを生成
        print(f"\n--- 8時通知メッセージ生成 ---")
        morning_guide = "今日やるタスクを選んでください！\n例：１、３、５"
        message = task_service.format_task_list(all_tasks, show_select_guide=True, guide_text=morning_guide)
        
        print("8時通知メッセージ:")
        print("---")
        print(message)
        print("---")
        
        print("\n=== テスト完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_normal_tasks()
    sys.exit(0 if success else 1)
