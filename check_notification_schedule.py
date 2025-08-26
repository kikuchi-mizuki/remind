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

def check_notification_schedule():
    """通知スケジュールの詳細確認"""
    print("=== 通知スケジュール詳細確認 ===")
    
    # 現在時刻を表示
    utc_now = datetime.now(pytz.UTC)
    jst_now = datetime.now(pytz.timezone('Asia/Tokyo'))
    print(f"現在時刻 - UTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"現在時刻 - JST: {jst_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"曜日: {jst_now.strftime('%A')}")
    
    # データベース初期化
    db = init_db()
    
    # 通知サービス初期化
    notification_service = NotificationService()
    
    # スケジューラーを開始
    if not notification_service.is_running:
        print("\nスケジューラーを開始中...")
        notification_service.start_scheduler()
        print("スケジューラー開始完了")
    
    # 登録されているジョブの詳細確認
    print(f"\n📅 登録されている通知スケジュール:")
    jobs = schedule.jobs
    if jobs:
        for i, job in enumerate(jobs, 1):
            job_name = getattr(job.job_func, '__name__', str(job.job_func))
            next_run = job.next_run
            
            # 次回実行時刻をJSTに変換
            if next_run:
                next_run_jst = next_run.replace(tzinfo=pytz.UTC).astimezone(pytz.timezone('Asia/Tokyo'))
                time_until = next_run_jst - jst_now
                
                print(f"\n{i}. {job_name}")
                print(f"   次回実行: {next_run_jst.strftime('%Y-%m-%d %H:%M:%S')} JST")
                print(f"   残り時間: {time_until}")
                
                # 通知内容の説明
                if "send_daily_task_notification" in job_name:
                    print(f"   📋 内容: 毎日8時のタスク一覧通知")
                elif "send_carryover_check" in job_name:
                    print(f"   📋 内容: 毎日21時のタスク確認通知")
                elif "send_future_task_selection" in job_name:
                    print(f"   📋 内容: 日曜18時の未来タスク選択通知")
                elif "_send_weekly_reports_to_all_users" in job_name:
                    print(f"   📋 内容: 日曜20時の週次レポート")
    else:
        print("  登録されているジョブはありません")
    
    # アクティブユーザー確認
    print(f"\n👥 アクティブユーザー:")
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
    
    # 次の通知予定時刻を計算
    print(f"\n⏰ 次回通知予定:")
    
    # 8時の通知
    next_8am_jst = jst_now.replace(hour=8, minute=0, second=0, microsecond=0)
    if jst_now.hour >= 8:
        next_8am_jst += timedelta(days=1)
    time_until_8am = next_8am_jst - jst_now
    print(f"  🕐 8時通知: {next_8am_jst.strftime('%Y-%m-%d %H:%M:%S')} JST (あと{time_until_8am})")
    
    # 21時の通知
    next_9pm_jst = jst_now.replace(hour=21, minute=0, second=0, microsecond=0)
    if jst_now.hour >= 21:
        next_9pm_jst += timedelta(days=1)
    time_until_9pm = next_9pm_jst - jst_now
    print(f"  🕘 21時通知: {next_9pm_jst.strftime('%Y-%m-%d %H:%M:%S')} JST (あと{time_until_9pm})")
    
    # 日曜18時の通知
    days_until_sunday = (6 - jst_now.weekday()) % 7
    if days_until_sunday == 0 and jst_now.hour >= 18:
        days_until_sunday = 7
    next_sunday_6pm = jst_now.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
    time_until_sunday_6pm = next_sunday_6pm - jst_now
    print(f"  🕕 日曜18時通知: {next_sunday_6pm.strftime('%Y-%m-%d %H:%M:%S')} JST (あと{time_until_sunday_6pm})")
    
    # スケジューラーの動作状況
    print(f"\n🔧 スケジューラー動作状況:")
    print(f"  動作中: {notification_service.is_running}")
    print(f"  スレッド存在: {notification_service.scheduler_thread is not None}")
    if notification_service.scheduler_thread:
        print(f"  スレッド動作中: {notification_service.scheduler_thread.is_alive()}")
    
    print("\n=== 確認完了 ===")

if __name__ == "__main__":
    check_notification_schedule() 