"""
ユーザーセッション機能のユニットテスト
"""
import pytest
import json
import os
from models.database import Database


class TestUserSessionsCRUD:
    """ユーザーセッションCRUD操作のテスト"""

    @pytest.fixture
    def db(self):
        """テスト用データベースのセットアップ"""
        # テスト用の一時データベースを作成
        test_db_path = "test_user_sessions.db"
        if os.path.exists(test_db_path):
            os.remove(test_db_path)

        db = Database(test_db_path)
        yield db

        # テスト後にクリーンアップ
        if os.path.exists(test_db_path):
            os.remove(test_db_path)

    def test_set_and_get_session(self, db):
        """セッションデータの保存と取得"""
        user_id = "test_user_123"
        session_type = "selected_tasks"
        data = json.dumps([1, 2, 3, 4, 5])

        # セッションデータを保存
        result = db.set_user_session(user_id, session_type, data)
        assert result is True

        # セッションデータを取得
        retrieved_data = db.get_user_session(user_id, session_type)
        assert retrieved_data == data
        assert json.loads(retrieved_data) == [1, 2, 3, 4, 5]

    def test_set_session_with_expiration(self, db):
        """有効期限付きセッションデータの保存"""
        user_id = "test_user_456"
        session_type = "schedule_proposal"
        data = "テストスケジュール提案"

        # 24時間有効なセッションデータを保存
        result = db.set_user_session(user_id, session_type, data, expires_hours=24)
        assert result is True

        # セッションデータを取得（まだ有効期限内）
        retrieved_data = db.get_user_session(user_id, session_type)
        assert retrieved_data == data

    def test_update_existing_session(self, db):
        """既存セッションデータの更新（UPSERT）"""
        user_id = "test_user_789"
        session_type = "future_task_selection"

        # 初回保存
        data1 = json.dumps({"mode": "future_schedule", "timestamp": "2025-01-01"})
        db.set_user_session(user_id, session_type, data1)

        # 同じユーザー・セッションタイプで更新
        data2 = json.dumps({"mode": "future_schedule", "timestamp": "2025-01-02"})
        db.set_user_session(user_id, session_type, data2)

        # 最新のデータが取得できることを確認
        retrieved_data = db.get_user_session(user_id, session_type)
        assert retrieved_data == data2
        assert json.loads(retrieved_data)["timestamp"] == "2025-01-02"

    def test_get_nonexistent_session(self, db):
        """存在しないセッションデータの取得"""
        user_id = "nonexistent_user"
        session_type = "selected_tasks"

        # 存在しないセッションデータを取得
        retrieved_data = db.get_user_session(user_id, session_type)
        assert retrieved_data is None

    def test_delete_session(self, db):
        """セッションデータの削除"""
        user_id = "test_user_delete"
        session_type = "selected_tasks"
        data = json.dumps([10, 20, 30])

        # セッションデータを保存
        db.set_user_session(user_id, session_type, data)

        # 削除前に存在確認
        assert db.get_user_session(user_id, session_type) is not None

        # セッションデータを削除
        result = db.delete_user_session(user_id, session_type)
        assert result is True

        # 削除後に存在しないことを確認
        assert db.get_user_session(user_id, session_type) is None

    def test_multiple_session_types(self, db):
        """同一ユーザーの複数セッションタイプ"""
        user_id = "test_user_multi"

        # 3種類のセッションデータを保存
        selected_tasks = json.dumps([1, 2, 3])
        schedule_proposal = "スケジュール提案テキスト"
        future_selection = json.dumps({"mode": "future_schedule"})

        db.set_user_session(user_id, "selected_tasks", selected_tasks)
        db.set_user_session(user_id, "schedule_proposal", schedule_proposal)
        db.set_user_session(user_id, "future_task_selection", future_selection)

        # それぞれが独立して取得できることを確認
        assert db.get_user_session(user_id, "selected_tasks") == selected_tasks
        assert db.get_user_session(user_id, "schedule_proposal") == schedule_proposal
        assert db.get_user_session(user_id, "future_task_selection") == future_selection

    def test_cleanup_expired_sessions(self, db):
        """期限切れセッションのクリーンアップ"""
        user_id = "test_user_cleanup"

        # 有効期限を0時間（すぐに期限切れ）に設定
        data = "期限切れテストデータ"
        db.set_user_session(user_id, "expired_session", data, expires_hours=0)

        # クリーンアップを実行
        deleted_count = db.cleanup_expired_sessions()
        assert deleted_count >= 1

        # クリーンアップ後にデータが取得できないことを確認
        retrieved_data = db.get_user_session(user_id, "expired_session")
        assert retrieved_data is None

    def test_session_isolation_between_users(self, db):
        """ユーザー間のセッション分離"""
        user1 = "test_user_1"
        user2 = "test_user_2"
        session_type = "selected_tasks"

        data1 = json.dumps([1, 2, 3])
        data2 = json.dumps([4, 5, 6])

        # 2人のユーザーが同じセッションタイプで異なるデータを保存
        db.set_user_session(user1, session_type, data1)
        db.set_user_session(user2, session_type, data2)

        # それぞれのユーザーが自分のデータのみ取得できることを確認
        assert db.get_user_session(user1, session_type) == data1
        assert db.get_user_session(user2, session_type) == data2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
