#!/usr/bin/env python3
"""
21時通知の実際の内容をテストするスクリプト
"""
import os
import sys
from datetime import datetime
import pytz

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.notification_service import NotificationService
from models.database import init_db

def test_21pm_actual_notification():
    """21時通知の実際の内容をテスト"""
    print("=== 21時通知の実際の内容テスト開始 ===")
    
    # 現在時刻を表示
    jst_now = datetime.now(pytz.timezone('Asia/Tokyo'))
    print(f"現在時刻 - JST: {jst_now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # データベース初期化
    db = init_db()
    
    # アクティブユーザー確認
    print("\nアクティブユーザー確認:")
    try:
        user_ids = db.get_all_user_ids()
        print(f"登録ユーザー数: {len(user_ids)}")
        for user_id in user_ids:
            print(f"  - {user_id}")
            
            # 各ユーザーのタスク確認
            tasks = db.get_user_tasks(user_id)
            today_tasks = [t for t in tasks if t.due_date == jst_now.strftime('%Y-%m-%d')]
            print(f"    全タスク数: {len(tasks)}, 今日のタスク: {len(today_tasks)}")
            
            for task in today_tasks:
                print(f"      - {task.name} ({task.duration_minutes}分)")
    except Exception as e:
        print(f"ユーザー取得エラー: {e}")
        import traceback
        traceback.print_exc()
    
    # 通知サービス初期化
    print(f"\n通知サービス初期化:")
    try:
        notification_service = NotificationService()
        
        # 実際の21時通知の内容をシミュレート
        print(f"\n21時通知の実際の内容:")
        jst = pytz.timezone('Asia/Tokyo')
        today_str = datetime.now(jst).strftime('%Y-%m-%d')
        print(f"今日の日付: {today_str}")
        
        for user_id in user_ids:
            tasks = notification_service.task_service.get_user_tasks(user_id)
            today_tasks = [t for t in tasks if t.due_date == today_str]
            print(f"ユーザー {user_id} の今日のタスク数: {len(today_tasks)}")
            
            if not today_tasks:
                msg = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n本日分のタスクはありません。\n＝＝＝＝＝＝"
            else:
                msg = "📋 今日のタスク一覧\n＝＝＝＝＝＝\n"
                for idx, t in enumerate(today_tasks, 1):
                    msg += f"{idx}. {t.name} ({t.duration_minutes}分)\n"
                msg += "＝＝＝＝＝＝\n終わったタスクを選んでください！\n例：１、３、５"
            
            print(f"\n実際に送信されるメッセージ:")
            print(f"---")
            print(msg)
            print(f"---")
            
    except Exception as e:
        print(f"通知サービス初期化エラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== 21時通知の実際の内容テスト完了 ===")

if __name__ == "__main__":
    test_21pm_actual_notification()

