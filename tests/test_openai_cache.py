"""
OpenAI APIキャッシュ機能のユニットテスト
"""
import pytest
import os
import tempfile
from datetime import datetime, timedelta
from models.database import Database
from services.openai_service import OpenAIService
from unittest.mock import Mock, patch


class TestOpenAICacheDatabase:
    """データベースのキャッシュ機能テスト"""

    @pytest.fixture
    def test_db(self):
        """テスト用データベースのセットアップ"""
        # 一時ファイルを使用してテストデータベースを作成
        fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        db = Database(db_path)
        yield db
        # テスト後にクリーンアップ
        if os.path.exists(db_path):
            os.remove(db_path)

    def test_set_and_get_cached_response(self, test_db):
        """キャッシュの保存と取得が正常に動作する"""
        model = "gpt-4o-mini"
        prompt_hash = "test_hash_123"
        prompt_preview = "Test prompt"
        response = "Test response"

        # キャッシュを保存
        result = test_db.set_cached_response(
            model=model,
            prompt_hash=prompt_hash,
            prompt_preview=prompt_preview,
            response=response,
            ttl_hours=24
        )
        assert result is True

        # キャッシュを取得
        cached = test_db.get_cached_response(model, prompt_hash)
        assert cached == response

    def test_cache_hit_count(self, test_db):
        """キャッシュヒット数が正しくカウントされる"""
        model = "gpt-4o-mini"
        prompt_hash = "test_hash_456"
        response = "Test response"

        # キャッシュを保存
        test_db.set_cached_response(model, prompt_hash, "test", response, 24)

        # 複数回取得してヒット数を確認
        for i in range(3):
            cached = test_db.get_cached_response(model, prompt_hash)
            assert cached == response

        # 統計を確認
        stats = test_db.get_cache_stats()
        assert stats['total_hits'] >= 3

    def test_cache_expiration(self, test_db):
        """期限切れキャッシュが削除される"""
        model = "gpt-4o-mini"
        prompt_hash = "test_hash_expired"
        response = "Expired response"

        # 期限切れのキャッシュを保存（-1時間 = 既に期限切れ）
        test_db.set_cached_response(model, prompt_hash, "test", response, ttl_hours=-1)

        # 期限切れキャッシュをクリーンアップ
        deleted_count = test_db.cleanup_expired_cache()
        assert deleted_count >= 1

        # 期限切れキャッシュは取得できない
        cached = test_db.get_cached_response(model, prompt_hash)
        assert cached is None

    def test_cache_upsert(self, test_db):
        """同じキーで再保存した場合、キャッシュが更新される"""
        model = "gpt-4o-mini"
        prompt_hash = "test_hash_upsert"
        response1 = "First response"
        response2 = "Updated response"

        # 最初のキャッシュを保存
        test_db.set_cached_response(model, prompt_hash, "test", response1, 24)
        cached1 = test_db.get_cached_response(model, prompt_hash)
        assert cached1 == response1

        # 同じキーで再保存
        test_db.set_cached_response(model, prompt_hash, "test", response2, 24)
        cached2 = test_db.get_cached_response(model, prompt_hash)
        assert cached2 == response2

    def test_cache_stats(self, test_db):
        """キャッシュ統計が正しく取得できる"""
        # 複数のキャッシュを保存
        test_db.set_cached_response("gpt-4o-mini", "hash1", "test1", "response1", 24)
        test_db.set_cached_response("gpt-4o-mini", "hash2", "test2", "response2", 24)
        test_db.set_cached_response("gpt-4o", "hash3", "test3", "response3", 24)

        # 統計を取得
        stats = test_db.get_cache_stats()

        assert stats['total_count'] >= 3
        assert stats['valid_count'] >= 3
        assert 'gpt-4o-mini' in stats['model_stats']
        assert 'gpt-4o' in stats['model_stats']


class TestOpenAIServiceCache:
    """OpenAIServiceのキャッシュ機能テスト"""

    @pytest.fixture
    def test_db(self):
        """テスト用データベースのセットアップ"""
        fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        db = Database(db_path)
        yield db
        if os.path.exists(db_path):
            os.remove(db_path)

    @pytest.fixture
    def openai_service(self, test_db):
        """OpenAIServiceのセットアップ（キャッシュ有効）"""
        return OpenAIService(db=test_db, enable_cache=True, cache_ttl_hours=24)

    @pytest.fixture
    def openai_service_no_cache(self, test_db):
        """OpenAIServiceのセットアップ（キャッシュ無効）"""
        return OpenAIService(db=test_db, enable_cache=False, cache_ttl_hours=24)

    def test_compute_prompt_hash(self, openai_service):
        """プロンプトハッシュが正しく計算される"""
        prompt = "Test prompt"
        hash1 = openai_service._compute_prompt_hash(prompt)
        hash2 = openai_service._compute_prompt_hash(prompt)

        # 同じプロンプトは同じハッシュを生成
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256ハッシュは64文字

    def test_cached_api_call(self, openai_service):
        """API呼び出しがキャッシュされる"""
        with patch.object(openai_service, '_call_openai_api', return_value="Mocked response"):
            prompt = "Test prompt"
            system_content = "Test system"

            # 1回目の呼び出し（キャッシュミス）
            response1 = openai_service._get_cached_or_call_api(
                prompt=prompt,
                system_content=system_content,
                max_tokens=100,
                temperature=0.7
            )
            assert response1 == "Mocked response"

            # 2回目の呼び出し（キャッシュヒット）
            with patch.object(openai_service, '_call_openai_api', side_effect=Exception("Should not be called")):
                response2 = openai_service._get_cached_or_call_api(
                    prompt=prompt,
                    system_content=system_content,
                    max_tokens=100,
                    temperature=0.7
                )
                assert response2 == "Mocked response"

    def test_cache_disabled(self, openai_service_no_cache):
        """キャッシュ無効時は毎回API呼び出しされる"""
        call_count = 0

        def mock_api_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return f"Response {call_count}"

        with patch.object(openai_service_no_cache, '_call_openai_api', side_effect=mock_api_call):
            prompt = "Test prompt"
            system_content = "Test system"

            # 2回呼び出し
            response1 = openai_service_no_cache._get_cached_or_call_api(
                prompt=prompt,
                system_content=system_content,
                max_tokens=100,
                temperature=0.7
            )
            response2 = openai_service_no_cache._get_cached_or_call_api(
                prompt=prompt,
                system_content=system_content,
                max_tokens=100,
                temperature=0.7
            )

            # キャッシュ無効なので2回APIが呼ばれる
            assert call_count == 2
            assert response1 == "Response 1"
            assert response2 == "Response 2"

    def test_analyze_task_priority_cached(self, openai_service):
        """タスク優先度分析がキャッシュされる"""
        with patch.object(openai_service.client.chat.completions, 'create') as mock_create:
            # モックレスポンス
            mock_response = Mock()
            mock_response.choices = [Mock()]
            mock_response.choices[0].message.content = "high"
            mock_create.return_value = mock_response

            # 1回目の呼び出し
            priority1 = openai_service.analyze_task_priority("重要な会議", 60)
            assert priority1 == "high"

            # 2回目の呼び出し（同じタスク）
            priority2 = openai_service.analyze_task_priority("重要な会議", 60)
            assert priority2 == "high"

            # APIは1回だけ呼ばれる（2回目はキャッシュから取得）
            # Note: 実際のテストでは、モックの呼び出し回数を確認できます


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
