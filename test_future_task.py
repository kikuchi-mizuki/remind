#!/usr/bin/env python3
"""
未来タスク機能のテストスクリプト
"""

import os
import sys
from datetime import datetime
from models.database import init_db, Task
from services.task_service import TaskService

def test_future_task_creation():
    """未来タスク作成のテスト"""
    print("=== 未来タスク作成テスト開始 ===")
    
    # データベース初期化
    db = init_db()
    print(f"データベース初期化完了: {db.db_path}")
    
    # タスクサービス初期化
    task_service = TaskService(db)
    
    # テスト用ユーザーID
    test_user_id = "test_user_123"
    
    # 未来タスクの情報
    task_info = {
        'name': '新規事業計画',
        'duration_minutes': 120,
        'priority': 'normal'
    }
    
    try:
        # 未来タスクを作成
        print(f"未来タスク作成中: {task_info['name']}")
        future_task = task_service.create_future_task(test_user_id, task_info)
        print(f"未来タスク作成成功: {future_task.task_id}")
        
        # 未来タスク一覧を取得
        print("未来タスク一覧を取得中...")
        future_tasks = task_service.get_user_future_tasks(test_user_id)
        print(f"取得した未来タスク数: {len(future_tasks)}")
        
        for task in future_tasks:
            print(f"  - {task.name} ({task.duration_minutes}分) - {task.task_type}")
        
        print("=== 未来タスク作成テスト完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_future_task_creation()
    sys.exit(0 if success else 1)
