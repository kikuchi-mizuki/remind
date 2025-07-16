#!/usr/bin/env python3
"""
8時の通知処理をテストするスクリプト
"""

import os
from dotenv import load_dotenv
from services.notification_service import NotificationService
from models.database import init_db

# 環境変数を読み込み
load_dotenv()

def test_daily_notification():
    """8時の通知処理をテスト"""
    print("=== 8時通知テスト開始 ===")
    
    # データベース初期化
    init_db()
    
    # 通知サービス初期化
    notification_service = NotificationService()
    
    try:
        # アクティブユーザーIDを取得
        print("アクティブユーザーIDを取得中...")
        user_ids = notification_service._get_active_user_ids()
        print(f"取得されたユーザーID: {user_ids}")
        
        if not user_ids:
            print("❌ アクティブユーザーが見つかりません")
            return
        
        # 各ユーザーのタスクを確認
        for user_id in user_ids:
            print(f"\n--- ユーザー {user_id} の処理 ---")
            
            # ユーザーのタスクを取得
            all_tasks = notification_service.task_service.get_user_tasks(user_id)
            print(f"全タスク数: {len(all_tasks)}")
            
            # 今日のタスクを抽出
            import pytz
            from datetime import datetime
            jst = pytz.timezone('Asia/Tokyo')
            today_str = datetime.now(jst).strftime('%Y-%m-%d')
            today_tasks = [t for t in all_tasks if t.due_date == today_str]
            print(f"今日のタスク数: {len(today_tasks)}")
            print(f"今日の日付: {today_str}")
            
            for task in today_tasks:
                print(f"  - {task.name} (期限: {task.due_date})")
        
        # 8時の通知処理を実行
        print("\nsend_daily_task_notification() を実行中...")
        notification_service.send_daily_task_notification()
        print("✅ 通知処理が正常に完了しました")
        
    except Exception as e:
        print(f"❌ 通知処理でエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_daily_notification() 