#!/usr/bin/env python3
"""
スケジューラーの動作をテストするスクリプト
"""

import schedule
import time
from datetime import datetime
import pytz

def test_scheduler():
    """スケジューラーの動作をテスト"""
    print("=== スケジューラーテスト開始 ===")
    
    # 現在時刻を取得
    jst = pytz.timezone('Asia/Tokyo')
    now = datetime.now(jst)
    print(f"現在時刻 (JST): {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # スケジューラーをクリア
    schedule.clear()
    
    # テスト用のジョブを追加
    def job_8am():
        print("✅ 8:00のジョブが実行されました")
    
    def job_21pm():
        print("✅ 21:00のジョブが実行されました")
    
    # スケジュール設定
    schedule.every().day.at("08:00").do(job_8am)
    schedule.every().day.at("21:00").do(job_21pm)
    
    print("設定されたジョブ:")
    for job in schedule.jobs:
        print(f"  - {job.next_run} (JST)")
    
    # 次の実行時刻を計算
    next_8am = schedule.jobs[0].next_run
    next_21pm = schedule.jobs[1].next_run
    
    print(f"\n次の8:00実行予定: {next_8am}")
    print(f"次の21:00実行予定: {next_21pm}")
    
    # 現在時刻と比較（タイムゾーンを合わせる）
    if next_8am:
        next_8am_jst = next_8am.replace(tzinfo=jst)
        if next_8am_jst > now:
            time_until_8am = next_8am_jst - now
            print(f"8:00まであと: {time_until_8am}")
        else:
            print("8:00は今日既に過ぎています")
    
    if next_21pm:
        next_21pm_jst = next_21pm.replace(tzinfo=jst)
        if next_21pm_jst > now:
            time_until_21pm = next_21pm_jst - now
            print(f"21:00まであと: {time_until_21pm}")
        else:
            print("21:00は今日既に過ぎています")

if __name__ == "__main__":
    test_scheduler() 