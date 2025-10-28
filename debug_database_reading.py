#!/usr/bin/env python3
"""
データベース読み込み状況のデバッグスクリプト
"""

import os
import sys
from datetime import datetime
from models.database import init_db
from services.task_service import TaskService

def debug_database_reading():
    """データベース読み込み状況のデバッグ"""
    print("=== データベース読み込み状況デバッグ ===")
    
    # データベース初期化
    db = init_db()
    print(f"データベースタイプ: {type(db).__name__}")
    
    # タスクサービス初期化
    task_service = TaskService(db)
    
    try:
        # 全ユーザーIDを取得
        print(f"\n--- 全ユーザーID取得 ---")
        all_user_ids = db.get_all_user_ids()
        print(f"登録ユーザー数: {len(all_user_ids)}")
        for user_id in all_user_ids:
            print(f"  - {user_id}")
        
        # 各ユーザーのタスクを確認
        for user_id in all_user_ids:
            print(f"\n--- ユーザー {user_id} のタスク確認 ---")
            
            # 全タスクを取得
            all_tasks = task_service.get_user_tasks(user_id)
            print(f"全タスク数: {len(all_tasks)}")
            
            for i, task in enumerate(all_tasks, 1):
                print(f"  {i}. {task.name} (期限: {task.due_date}, 優先度: {task.priority}, タイプ: {task.task_type})")
            
            # 今日のタスクをフィルタリング
            import pytz
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst)
            today_str = today.strftime('%Y-%m-%d')
            print(f"今日の日付: {today_str}")
            
            today_tasks = []
            for task in all_tasks:
                try:
                    if not task.due_date:
                        print(f"  期限未設定タスク: {task.name}")
                        continue
                    task_due = datetime.strptime(task.due_date, '%Y-%m-%d').date()
                    if task_due == today.date():
                        today_tasks.append(task)
                        print(f"  今日のタスク: {task.name} (期限: {task.due_date})")
                    else:
                        print(f"  未来のタスク: {task.name} (期限: {task.due_date})")
                except Exception as e:
                    print(f"  タスク期限解析エラー: {task.name} - {e}")
            
            print(f"今日のタスク数: {len(today_tasks)}")
            
            # 8時通知のメッセージを生成
            morning_guide = "今日やるタスクを選んでください！\n例：１、３、５"
            message = task_service.format_task_list(all_tasks, show_select_guide=True, guide_text=morning_guide)
            
            print(f"\n8時通知メッセージ:")
            print("---")
            print(message)
            print("---")
        
        print("\n=== デバッグ完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = debug_database_reading()
    sys.exit(0 if success else 1)
