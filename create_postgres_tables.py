#!/usr/bin/env python3
"""
PostgreSQLテーブル作成スクリプト
"""
import os
import sys
from datetime import datetime

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def create_postgres_tables():
    """PostgreSQLテーブルを作成"""
    print("=== PostgreSQLテーブル作成スクリプト ===")
    print(f"現在時刻: {datetime.now()}")
    
    # 環境変数確認
    print(f"\n環境変数確認:")
    print(f"DATABASE_URL: {'設定済み' if os.getenv('DATABASE_URL') else '未設定'}")
    
    if not os.getenv('DATABASE_URL'):
        print("❌ DATABASE_URLが設定されていません")
        print("RailwayでPostgreSQLを追加してください")
        return
    
    try:
        # PostgreSQLデータベースを初期化
        from models.postgres_database import init_postgres_db
        postgres_db = init_postgres_db()
        
        if not postgres_db.Session:
            print("❌ PostgreSQLデータベースの初期化に失敗しました")
            return
        
        print("✅ PostgreSQLデータベースの初期化が完了しました")
        
        # テーブル作成を明示的に実行
        if hasattr(postgres_db, '_ensure_tables_exist'):
            postgres_db._ensure_tables_exist()
        
        # テーブル一覧を確認
        from sqlalchemy import inspect
        inspector = inspect(postgres_db.engine)
        tables = inspector.get_table_names()
        print(f"\n作成されたテーブル: {tables}")
        
        # 各テーブルの詳細を確認
        for table_name in tables:
            try:
                columns = inspector.get_columns(table_name)
                print(f"\n{table_name}テーブル:")
                for column in columns:
                    print(f"  - {column['name']}: {column['type']}")
            except Exception as e:
                print(f"  {table_name}テーブルの詳細取得エラー: {e}")
        
        print("\n✅ PostgreSQLテーブル作成が完了しました")
        
    except Exception as e:
        print(f"❌ PostgreSQLテーブル作成エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    create_postgres_tables()
