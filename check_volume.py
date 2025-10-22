#!/usr/bin/env python3
"""
Railwayボリューム設定確認スクリプト
"""
import os
import sqlite3
from datetime import datetime

def check_volume_setup():
    """ボリューム設定を確認"""
    print("=== Railwayボリューム設定確認 ===")
    print(f"現在時刻: {datetime.now()}")
    
    # 環境変数確認
    print(f"\n環境変数:")
    print(f"RAILWAY_ENVIRONMENT: {os.getenv('RAILWAY_ENVIRONMENT')}")
    print(f"RAILWAY_STATIC_URL: {os.getenv('RAILWAY_STATIC_URL')}")
    print(f"RAILWAY_PUBLIC_DOMAIN: {os.getenv('RAILWAY_PUBLIC_DOMAIN')}")
    
    # ディレクトリ確認
    print(f"\nディレクトリ確認:")
    print(f"/app 存在: {os.path.exists('/app')}")
    print(f"/app/vol 存在: {os.path.exists('/app/vol')}")
    
    # データベースパス確認
    db_paths = [
        "/app/vol/tasks.db",
        "/app/tasks.db",
        "tasks.db"
    ]
    
    print(f"\nデータベースファイル確認:")
    for db_path in db_paths:
        exists = os.path.exists(db_path)
        size = os.path.getsize(db_path) if exists else 0
        print(f"{db_path}: 存在={exists}, サイズ={size} bytes")
        
        if exists:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # テーブル一覧
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                print(f"  テーブル: {[t[0] for t in tables]}")
                
                # tokensテーブルの内容確認
                if ('tokens',) in tables:
                    cursor.execute("SELECT COUNT(*) FROM tokens")
                    token_count = cursor.fetchone()[0]
                    print(f"  トークン数: {token_count}")
                    
                    if token_count > 0:
                        cursor.execute("SELECT user_id, LENGTH(token_json) FROM tokens LIMIT 5")
                        tokens = cursor.fetchall()
                        print(f"  トークン例: {tokens}")
                
                conn.close()
            except Exception as e:
                print(f"  データベース読み込みエラー: {e}")
    
    # 推奨設定
    print(f"\n推奨設定:")
    if not os.path.exists('/app/vol'):
        print("⚠️  /app/vol ディレクトリが存在しません")
        print("   Railwayダッシュボードでボリュームを /app/vol にマウントしてください")
    else:
        print("✅ /app/vol ディレクトリが存在します")

if __name__ == "__main__":
    check_volume_setup()
