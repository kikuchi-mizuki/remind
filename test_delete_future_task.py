#!/usr/bin/env python3
"""
未来タスク削除機能のテストスクリプト
"""

import os
import sys
from datetime import datetime
from models.database import init_db, Task
from services.task_service import TaskService

def test_future_task_deletion():
    """未来タスク削除のテスト"""
    print("=== 未来タスク削除テスト開始 ===")
    
    # データベース初期化
    db = init_db()
    print(f"データベース初期化完了: {db.db_path}")
    
    # タスクサービス初期化
    task_service = TaskService(db)
    
    # テスト用ユーザーID
    test_user_id = "test_user_123"
    
    # 未来タスクの情報
    task_info = {
        'name': 'テスト未来タスク',
        'duration_minutes': 60,
        'priority': 'normal'
    }
    
    try:
        # 未来タスクを作成
        print(f"未来タスク作成中: {task_info['name']}")
        future_task = task_service.create_future_task(test_user_id, task_info)
        print(f"未来タスク作成成功: {future_task.task_id}")
        
        # 未来タスク一覧を確認
        future_tasks = task_service.get_user_future_tasks(test_user_id)
        print(f"削除前の未来タスク数: {len(future_tasks)}")
        
        # 未来タスクを削除
        print(f"未来タスク削除中: {future_task.task_id}")
        delete_result = task_service.delete_future_task(future_task.task_id)
        print(f"削除結果: {delete_result}")
        
        # 削除後の未来タスク一覧を確認
        future_tasks_after = task_service.get_user_future_tasks(test_user_id)
        print(f"削除後の未来タスク数: {len(future_tasks_after)}")
        
        # 削除されたタスクが存在しないことを確認
        deleted_task_exists = any(task.task_id == future_task.task_id for task in future_tasks_after)
        
        if not deleted_task_exists and len(future_tasks_after) == len(future_tasks) - 1:
            print("✅ 未来タスク削除テスト成功")
            return True
        else:
            print("❌ 未来タスク削除テスト失敗")
            return False
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_future_task_deletion()
    sys.exit(0 if success else 1)
