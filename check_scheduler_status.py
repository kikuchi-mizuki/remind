#!/usr/bin/env python3
import os
import sys
from datetime import datetime, timedelta
import pytz
import schedule

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.notification_service import NotificationService
from models.database import init_db

def check_scheduler_status():
    """スケジューラーの状態を確認"""
    print("=== スケジューラー状態確認 ===")
    
    # 現在時刻を表示
    utc_now = datetime.now(pytz.UTC)
    jst_now = datetime.now(pytz.timezone('Asia/Tokyo'))
    print(f"現在時刻 - UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"現在時刻 - JST: {jst_now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # データベース初期化
    db = init_db()
    
    # 通知サービス初期化
    notification_service = NotificationService()
    
    # スケジューラーを開始
    if not notification_service.is_running:
        print("スケジューラーを開始中...")
        notification_service.start_scheduler()
        print("スケジューラー開始完了")
    
    # スケジューラーの状態確認
    print(f"\nスケジューラー状態:")
    print(f"  動作中: {notification_service.is_running}")
    print(f"  スレッド存在: {notification_service.scheduler_thread is not None}")
    if notification_service.scheduler_thread:
        print(f"  スレッド動作中: {notification_service.scheduler_thread.is_alive()}")
    
    # 登録されているジョブを確認
    print(f"\n登録されているジョブ:")
    jobs = schedule.jobs
    if jobs:
        for i, job in enumerate(jobs, 1):
            job_name = getattr(job.job_func, '__name__', str(job.job_func))
            print(f"  {i}. {job_name} - 次回実行: {job.next_run}")
    else:
        print("  登録されているジョブはありません")
    
    # アクティブユーザー確認
    print(f"\nアクティブユーザー:")
    try:
        user_ids = notification_service._get_active_user_ids()
        print(f"  ユーザー数: {len(user_ids)}")
        for user_id in user_ids:
            print(f"    - {user_id}")
            
            # 各ユーザーのタスク確認
            tasks = notification_service.task_service.get_user_tasks(user_id)
            today_tasks = [t for t in tasks if t.due_date == jst_now.strftime('%Y-%m-%d')]
            print(f"      タスク数: {len(tasks)}, 今日のタスク: {len(today_tasks)}")
    except Exception as e:
        print(f"  ユーザー取得エラー: {e}")
    
    # 次の8時通知時刻を計算
    print(f"\n次回通知予定:")
    next_8am_jst = jst_now.replace(hour=8, minute=0, second=0, microsecond=0)
    if jst_now.hour >= 8:
        next_8am_jst += timedelta(days=1)
    
    next_8am_utc = next_8am_jst.replace(tzinfo=pytz.timezone('Asia/Tokyo')).astimezone(pytz.UTC)
    print(f"  次回8時通知 (JST): {next_8am_jst.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  次回8時通知 (UTC): {next_8am_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 現在時刻から次回通知までの時間
    time_until_8am = next_8am_jst - jst_now
    print(f"  8時まであと: {time_until_8am}")
    
    print("\n=== 確認完了 ===")

if __name__ == "__main__":
    check_scheduler_status() 