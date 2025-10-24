#!/usr/bin/env python3
"""
8時通知のテストスクリプト
"""
import os
import sys
from datetime import datetime
import pytz

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.notification_service import NotificationService
from models.database import init_db

def test_8am_notification():
    """8時通知をテスト"""
    print("=== 8時通知テスト開始 ===")
    
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
    
    # 通知実行履歴確認
    print("\n通知実行履歴確認:")
    try:
        last_execution = db.get_last_notification_execution("daily_task_notification")
        if last_execution:
            print(f"最後の8時通知実行: {last_execution}")
        else:
            print("8時通知の実行履歴なし")
    except Exception as e:
        print(f"実行履歴取得エラー: {e}")
    
    # 通知サービス初期化（環境変数チェック）
    print(f"\n環境変数確認:")
    print(f"LINE_CHANNEL_ACCESS_TOKEN: {'設定済み' if os.getenv('LINE_CHANNEL_ACCESS_TOKEN') else '未設定'}")
    print(f"DISABLE_DUPLICATE_PREVENTION: {os.getenv('DISABLE_DUPLICATE_PREVENTION', '未設定')}")
    
    if not os.getenv('LINE_CHANNEL_ACCESS_TOKEN'):
        print("⚠️  LINE_CHANNEL_ACCESS_TOKENが設定されていません")
        print("本番環境では通知は送信されません")
        return
    
    try:
        # 通知サービス初期化
        notification_service = NotificationService()
        
        # 8時通知を手動実行
        print("\n8時通知を手動実行中...")
        notification_service.send_daily_task_notification()
        print("✅ 8時通知テスト完了")
        
    except Exception as e:
        print(f"❌ 8時通知テストエラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== 8時通知テスト完了 ===")

if __name__ == "__main__":
    test_8am_notification()
