"""
通知エラーハンドリング機能のユニットテスト
"""
import pytest
import time
from unittest.mock import Mock, patch
from services.notification_error_handler import (
    NotificationErrorHandler,
    RetryConfig,
    NotificationError,
    ErrorType
)


class TestErrorTypeClassification:
    """エラータイプ分類のテスト"""

    @pytest.fixture
    def error_handler(self):
        return NotificationErrorHandler()

    def test_classify_timeout_error(self, error_handler):
        """タイムアウトエラーが正しく分類される"""
        error = TimeoutError("Connection timed out")
        error_type = error_handler.classify_error(error)
        assert error_type == ErrorType.TIMEOUT_ERROR

    def test_classify_network_error(self, error_handler):
        """ネットワークエラーが正しく分類される"""
        error = ConnectionError("Network unreachable")
        error_type = error_handler.classify_error(error)
        assert error_type == ErrorType.NETWORK_ERROR

    def test_classify_rate_limit_error(self, error_handler):
        """レート制限エラーが正しく分類される"""
        error = Exception("HTTP 429: Rate limit exceeded")
        error_type = error_handler.classify_error(error)
        assert error_type == ErrorType.RATE_LIMIT_ERROR

    def test_classify_authentication_error(self, error_handler):
        """認証エラーが正しく分類される"""
        error = Exception("HTTP 401: Unauthorized")
        error_type = error_handler.classify_error(error)
        assert error_type == ErrorType.AUTHENTICATION_ERROR

    def test_classify_server_error(self, error_handler):
        """サーバーエラーが正しく分類される"""
        error = Exception("HTTP 500: Internal Server Error")
        error_type = error_handler.classify_error(error)
        assert error_type == ErrorType.SERVER_ERROR

    def test_classify_unknown_error(self, error_handler):
        """不明なエラーが正しく分類される"""
        error = Exception("Something went wrong")
        error_type = error_handler.classify_error(error)
        assert error_type == ErrorType.UNKNOWN_ERROR


class TestRetryLogic:
    """リトライロジックのテスト"""

    @pytest.fixture
    def error_handler(self):
        config = RetryConfig(max_retries=3, initial_delay=0.1, timeout=5.0)
        return NotificationErrorHandler(config)

    def test_should_retry_network_error(self, error_handler):
        """ネットワークエラーはリトライすべき"""
        assert error_handler.should_retry(ErrorType.NETWORK_ERROR, 0) is True
        assert error_handler.should_retry(ErrorType.NETWORK_ERROR, 1) is True
        assert error_handler.should_retry(ErrorType.NETWORK_ERROR, 2) is True
        assert error_handler.should_retry(ErrorType.NETWORK_ERROR, 3) is False  # max_retries到達

    def test_should_not_retry_authentication_error(self, error_handler):
        """認証エラーはリトライすべきでない"""
        assert error_handler.should_retry(ErrorType.AUTHENTICATION_ERROR, 0) is False

    def test_should_not_retry_invalid_request(self, error_handler):
        """無効なリクエストはリトライすべきでない"""
        assert error_handler.should_retry(ErrorType.INVALID_REQUEST, 0) is False

    def test_calculate_delay_exponential_backoff(self, error_handler):
        """指数バックオフで遅延が増加する"""
        delay0 = error_handler.calculate_delay(0, ErrorType.NETWORK_ERROR)
        delay1 = error_handler.calculate_delay(1, ErrorType.NETWORK_ERROR)
        delay2 = error_handler.calculate_delay(2, ErrorType.NETWORK_ERROR)

        # 指数的に増加する（ジッターがあるので厳密には確認できないが、傾向を確認）
        assert delay0 < delay1 < delay2

    def test_calculate_delay_rate_limit(self, error_handler):
        """レート制限エラーは長めの遅延"""
        delay_network = error_handler.calculate_delay(0, ErrorType.NETWORK_ERROR)
        delay_rate_limit = error_handler.calculate_delay(0, ErrorType.RATE_LIMIT_ERROR)

        # レート制限エラーの方が長い遅延
        assert delay_rate_limit > delay_network * 5  # 基本的に10倍だが、ジッターがある


class TestExecuteWithRetry:
    """リトライ実行のテスト"""

    @pytest.fixture
    def error_handler(self):
        config = RetryConfig(max_retries=3, initial_delay=0.01, timeout=5.0)
        return NotificationErrorHandler(config)

    def test_successful_execution_no_retry(self, error_handler):
        """成功時はリトライせず即座に結果を返す"""
        mock_func = Mock(return_value="success")

        result = error_handler.execute_with_retry(
            mock_func,
            operation_name="test_operation"
        )

        assert result == "success"
        assert mock_func.call_count == 1  # 1回だけ呼ばれる

    def test_retry_on_network_error(self, error_handler):
        """ネットワークエラー時にリトライする"""
        mock_func = Mock()
        mock_func.side_effect = [
            ConnectionError("Network error"),
            ConnectionError("Network error"),
            "success"  # 3回目で成功
        ]

        result = error_handler.execute_with_retry(
            mock_func,
            operation_name="test_operation"
        )

        assert result == "success"
        assert mock_func.call_count == 3  # 3回呼ばれる

    def test_max_retries_exceeded(self, error_handler):
        """最大リトライ回数を超えると例外が発生"""
        mock_func = Mock()
        mock_func.side_effect = ConnectionError("Network error")

        with pytest.raises(NotificationError) as exc_info:
            error_handler.execute_with_retry(
                mock_func,
                operation_name="test_operation"
            )

        assert exc_info.value.error_type == ErrorType.NETWORK_ERROR
        assert mock_func.call_count == 4  # 初回 + 3回リトライ = 4回

    def test_no_retry_on_authentication_error(self, error_handler):
        """認証エラー時はリトライしない"""
        mock_func = Mock()
        mock_func.side_effect = Exception("HTTP 401: Unauthorized")

        with pytest.raises(NotificationError) as exc_info:
            error_handler.execute_with_retry(
                mock_func,
                operation_name="test_operation"
            )

        assert exc_info.value.error_type == ErrorType.AUTHENTICATION_ERROR
        assert mock_func.call_count == 1  # リトライしないので1回だけ


class TestErrorStats:
    """エラー統計のテスト"""

    @pytest.fixture
    def error_handler(self):
        config = RetryConfig(max_retries=2, initial_delay=0.01)
        return NotificationErrorHandler(config)

    def test_stats_successful_calls(self, error_handler):
        """成功時の統計が正しく記録される"""
        mock_func = Mock(return_value="success")

        for _ in range(5):
            error_handler.execute_with_retry(mock_func)

        stats = error_handler.get_stats()
        assert stats['total_calls'] == 5
        assert stats['total_errors'] == 0
        assert stats['success_rate'] == 100.0

    def test_stats_with_errors_and_retries(self, error_handler):
        """エラーとリトライの統計が正しく記録される"""
        # 2回失敗して3回目で成功
        mock_func1 = Mock()
        mock_func1.side_effect = [
            ConnectionError("Network error"),
            ConnectionError("Network error"),
            "success"
        ]

        error_handler.execute_with_retry(mock_func1)

        # 常に失敗
        mock_func2 = Mock()
        mock_func2.side_effect = ConnectionError("Network error")

        try:
            error_handler.execute_with_retry(mock_func2)
        except NotificationError:
            pass

        stats = error_handler.get_stats()
        assert stats['total_calls'] == 2
        assert stats['total_errors'] == 3  # 2回 + 1回（最終失敗）
        assert stats['total_retries'] == 4  # 2回リトライ + 2回リトライ
        assert ErrorType.NETWORK_ERROR.value in stats['errors_by_type']

    def test_reset_stats(self, error_handler):
        """統計をリセットできる"""
        mock_func = Mock(return_value="success")
        error_handler.execute_with_retry(mock_func)

        error_handler.reset_stats()

        stats = error_handler.get_stats()
        assert stats['total_calls'] == 0
        assert stats['total_errors'] == 0
        assert stats['total_retries'] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
