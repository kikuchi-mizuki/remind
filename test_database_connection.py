#!/usr/bin/env python3
"""
データベース接続テストスクリプト
"""
import os
import sys
from datetime import datetime

# プロジェクトのルートディレクトリをパスに追加
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_database_connection():
    """データベース接続をテスト"""
    print("=== データベース接続テスト ===")
    print(f"現在時刻: {datetime.now()}")
    
    # 環境変数確認
    print(f"\n環境変数確認:")
    print(f"DATABASE_URL: {'設定済み' if os.getenv('DATABASE_URL') else '未設定'}")
    print(f"RAILWAY_ENVIRONMENT: {os.getenv('RAILWAY_ENVIRONMENT', '未設定')}")
    
    if os.getenv('DATABASE_URL'):
        print(f"DATABASE_URL先頭50文字: {os.getenv('DATABASE_URL')[:50]}...")
    
    # データベース初期化テスト
    print(f"\nデータベース初期化テスト:")
    try:
        from models.database import init_db
        db = init_db()
        print(f"✅ データベース初期化成功")
        print(f"データベースタイプ: {type(db).__name__}")
        
        # PostgreSQLかSQLiteかを判定
        if hasattr(db, 'Session') and db.Session:
            print(f"📊 PostgreSQLデータベースを使用中")
        else:
            print(f"📁 SQLiteデータベースを使用中")
            
    except Exception as e:
        print(f"❌ データベース初期化エラー: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # トークン保存テスト
    print(f"\nトークン保存テスト:")
    test_user_id = "test_user_123"
    test_token = '{"access_token": "test_token", "refresh_token": "test_refresh"}'
    
    try:
        result = db.save_token(test_user_id, test_token)
        if result:
            print(f"✅ トークン保存成功")
        else:
            print(f"❌ トークン保存失敗")
    except Exception as e:
        print(f"❌ トークン保存エラー: {e}")
    
    # トークン取得テスト
    print(f"\nトークン取得テスト:")
    try:
        retrieved_token = db.get_token(test_user_id)
        if retrieved_token:
            print(f"✅ トークン取得成功")
            print(f"トークン長: {len(retrieved_token)}文字")
        else:
            print(f"❌ トークン取得失敗（トークンなし）")
    except Exception as e:
        print(f"❌ トークン取得エラー: {e}")
    
    # ユーザーチャネル保存テスト
    print(f"\nユーザーチャネル保存テスト:")
    test_channel_id = "test_channel_456"
    
    try:
        result = db.save_user_channel(test_user_id, test_channel_id)
        if result:
            print(f"✅ ユーザーチャネル保存成功")
        else:
            print(f"❌ ユーザーチャネル保存失敗")
    except Exception as e:
        print(f"❌ ユーザーチャネル保存エラー: {e}")
    
    # ユーザーチャネル取得テスト
    print(f"\nユーザーチャネル取得テスト:")
    try:
        retrieved_channel = db.get_user_channel(test_user_id)
        if retrieved_channel:
            print(f"✅ ユーザーチャネル取得成功: {retrieved_channel}")
        else:
            print(f"❌ ユーザーチャネル取得失敗（チャネルIDなし）")
    except Exception as e:
        print(f"❌ ユーザーチャネル取得エラー: {e}")
    
    # 通知実行履歴テスト
    print(f"\n通知実行履歴テスト:")
    test_notification_type = "test_notification"
    test_execution_time = datetime.now().isoformat()
    
    try:
        result = db.save_notification_execution(test_notification_type, test_execution_time)
        if result:
            print(f"✅ 通知実行履歴保存成功")
        else:
            print(f"❌ 通知実行履歴保存失敗")
    except Exception as e:
        print(f"❌ 通知実行履歴保存エラー: {e}")
    
    # 通知実行履歴取得テスト
    print(f"\n通知実行履歴取得テスト:")
    try:
        retrieved_execution = db.get_last_notification_execution(test_notification_type)
        if retrieved_execution:
            print(f"✅ 通知実行履歴取得成功: {retrieved_execution}")
        else:
            print(f"❌ 通知実行履歴取得失敗（履歴なし）")
    except Exception as e:
        print(f"❌ 通知実行履歴取得エラー: {e}")
    
    print(f"\n=== データベース接続テスト完了 ===")

if __name__ == "__main__":
    test_database_connection()
