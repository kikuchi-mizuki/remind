#!/usr/bin/env python3
import os
import sys
from datetime import datetime, timedelta
import pytz
import schedule
import time
import threading

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.notification_service import NotificationService
from models.database import init_db

def test_scheduler():
    """スケジューラーのテスト"""
    print("=== スケジューラーテスト開始 ===")
    
    # データベース初期化
    init_db()
    
    # 通知サービス初期化
    notification_service = NotificationService()
    
    # 現在時刻を表示
    utc_now = datetime.now(pytz.UTC)
    jst_now = datetime.now(pytz.timezone('Asia/Tokyo'))
    print(f"現在時刻 - UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"現在時刻 - JST: {jst_now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # スケジューラーの状態確認
    print(f"スケジューラー動作中: {notification_service.is_running}")
    print(f"スケジューラースレッド存在: {notification_service.scheduler_thread is not None}")
    if notification_service.scheduler_thread:
        print(f"スケジューラースレッド動作中: {notification_service.scheduler_thread.is_alive()}")
    
    # アクティブユーザー確認
    try:
        user_ids = notification_service._get_active_user_ids()
        print(f"アクティブユーザー数: {len(user_ids)}")
        for user_id in user_ids:
            print(f"  - {user_id}")
    except Exception as e:
        print(f"ユーザー取得エラー: {e}")
    
    # スケジューラー開始
    print("\n=== スケジューラー開始 ===")
    notification_service.start_scheduler()
    
    # 5分間動作確認
    print("\n=== 5分間動作確認 ===")
    for i in range(5):
        print(f"{i+1}分経過: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  スケジューラー動作中: {notification_service.is_running}")
        if notification_service.scheduler_thread:
            print(f"  スケジューラースレッド動作中: {notification_service.scheduler_thread.is_alive()}")
        
        # 次の実行時刻を確認
        next_run = schedule.next_run()
        if next_run:
            print(f"  次回実行予定: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        
        time.sleep(60)
    
    # 手動で通知テスト
    print("\n=== 手動通知テスト ===")
    try:
        user_ids = notification_service._get_active_user_ids()
        if user_ids:
            test_user_id = user_ids[0]
            print(f"テストユーザー {test_user_id} に通知送信")
            notification_service.send_custom_notification(
                test_user_id, 
                f"🧪 スケジューラーテスト通知\n\n時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nこの通知が届けば、通知システムは正常に動作しています。"
            )
            print("テスト通知送信完了")
        else:
            print("テスト対象のユーザーが見つかりません")
    except Exception as e:
        print(f"テスト通知送信エラー: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n=== テスト完了 ===")

if __name__ == "__main__":
    test_scheduler() 