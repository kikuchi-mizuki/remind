#!/usr/bin/env python3
import os
import sys
from datetime import datetime
import pytz

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models.database import init_db
from services.task_service import TaskService

def check_database():
    """データベースの状態を確認"""
    print("=== データベース状態確認 ===")
    
    # データベース初期化
    db = init_db()
    
    # 全ユーザーID取得
    try:
        user_ids = db.get_all_user_ids()
        print(f"登録ユーザー数: {len(user_ids)}")
        for user_id in user_ids:
            print(f"  - {user_id}")
            
            # 各ユーザーのタスク数確認
            task_service = TaskService()
            tasks = task_service.get_user_tasks(user_id)
            print(f"    タスク数: {len(tasks)}")
            
            # 今日のタスク確認
            jst = pytz.timezone('Asia/Tokyo')
            today_str = datetime.now(jst).strftime('%Y-%m-%d')
            today_tasks = [t for t in tasks if t.due_date == today_str]
            print(f"    今日のタスク数: {len(today_tasks)}")
            
            # トークン確認
            token = db.get_token(user_id)
            if token:
                print(f"    トークン: 存在")
            else:
                print(f"    トークン: なし")
                
    except Exception as e:
        print(f"ユーザー取得エラー: {e}")
        import traceback
        traceback.print_exc()
    
    # データベースファイル情報
    print(f"\nデータベースファイル: {db.db_path}")
    if os.path.exists(db.db_path):
        file_size = os.path.getsize(db.db_path)
        print(f"ファイルサイズ: {file_size} bytes")
        mod_time = os.path.getmtime(db.db_path)
        mod_time_str = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')
        print(f"最終更新: {mod_time_str}")
    else:
        print("データベースファイルが存在しません")
    
    print("\n=== 確認完了 ===")

if __name__ == "__main__":
    check_database() 