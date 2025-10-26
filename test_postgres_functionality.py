#!/usr/bin/env python3
"""
PostgreSQL機能のテストスクリプト
"""

import os
import sys
from datetime import datetime
from models.database import init_db, Task
from services.task_service import TaskService

def test_postgres_functionality():
    """PostgreSQL機能のテスト"""
    print("=== PostgreSQL機能テスト開始 ===")
    
    # データベース初期化
    db = init_db()
    print(f"データベース初期化完了: {type(db).__name__}")
    
    # タスクサービス初期化
    task_service = TaskService(db)
    
    # テスト用ユーザーID
    test_user_id = "test_postgres_user_123"
    
    try:
        # 1. スケジュール提案のテスト
        print("\n--- スケジュール提案テスト ---")
        proposal_text = 'テストスケジュール提案'
        
        # 保存
        save_result = task_service.save_schedule_proposal(test_user_id, proposal_text)
        print(f"スケジュール提案保存結果: {save_result}")
        
        # 取得
        retrieved_proposal = task_service.get_schedule_proposal(test_user_id)
        print(f"取得したスケジュール提案: {retrieved_proposal}")
        
        if retrieved_proposal and retrieved_proposal.get('proposal_text') == proposal_text:
            print("✅ スケジュール提案テスト成功")
        else:
            print("❌ スケジュール提案テスト失敗")
            return False
        
        # 2. ユーザー設定のテスト
        print("\n--- ユーザー設定テスト ---")
        
        # 保存
        settings_result = db.save_user_settings(test_user_id, "test_calendar_id", "09:00")
        print(f"ユーザー設定保存結果: {settings_result}")
        
        # 取得
        retrieved_settings = db.get_user_settings(test_user_id)
        print(f"取得したユーザー設定: {retrieved_settings}")
        
        if retrieved_settings and retrieved_settings.get('calendar_id') == 'test_calendar_id':
            print("✅ ユーザー設定テスト成功")
        else:
            print("❌ ユーザー設定テスト失敗")
            return False
        
        # 3. 未来タスクのテスト
        print("\n--- 未来タスクテスト ---")
        task_info = {
            'name': 'PostgreSQLテストタスク',
            'duration_minutes': 90,
            'priority': 'normal'
        }
        
        # 作成
        future_task = task_service.create_future_task(test_user_id, task_info)
        print(f"未来タスク作成結果: {future_task.task_id if future_task else '失敗'}")
        
        # 取得
        future_tasks = task_service.get_user_future_tasks(test_user_id)
        print(f"取得した未来タスク数: {len(future_tasks)}")
        
        if future_tasks and any(task.name == 'PostgreSQLテストタスク' for task in future_tasks):
            print("✅ 未来タスクテスト成功")
        else:
            print("❌ 未来タスクテスト失敗")
            return False
        
        print("\n=== PostgreSQL機能テスト完了 ===")
        return True
        
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_postgres_functionality()
    sys.exit(0 if success else 1)
