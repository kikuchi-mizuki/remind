"""
通知サービスのエラーハンドリングとリトライロジック
"""
import time
import logging
from typing import Callable, Any, Optional, Dict
from enum import Enum
from datetime import datetime
import pytz


class ErrorType(Enum):
    """エラーの種類"""
    NETWORK_ERROR = "network_error"  # ネットワーク関連エラー
    TIMEOUT_ERROR = "timeout_error"  # タイムアウトエラー
    RATE_LIMIT_ERROR = "rate_limit_error"  # レート制限エラー
    AUTHENTICATION_ERROR = "authentication_error"  # 認証エラー
    INVALID_REQUEST = "invalid_request"  # 無効なリクエスト
    SERVER_ERROR = "server_error"  # サーバーエラー（5xx）
    UNKNOWN_ERROR = "unknown_error"  # 不明なエラー


class NotificationError(Exception):
    """通知エラーの基底クラス"""
    def __init__(self, message: str, error_type: ErrorType, original_error: Exception = None):
        self.message = message
        self.error_type = error_type
        self.original_error = original_error
        self.timestamp = datetime.now(pytz.timezone('Asia/Tokyo'))
        super().__init__(self.message)


class RetryConfig:
    """リトライ設定"""
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        timeout: float = 30.0
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.timeout = timeout


class NotificationErrorHandler:
    """通知サービスのエラーハンドラー"""

    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()
        self.logger = self._setup_logger()
        self.error_stats = {
            'total_calls': 0,
            'total_errors': 0,
            'total_retries': 0,
            'errors_by_type': {}
        }

    def _setup_logger(self) -> logging.Logger:
        """ロガーのセットアップ"""
        logger = logging.getLogger('NotificationErrorHandler')
        logger.setLevel(logging.INFO)

        # ハンドラーが既に存在する場合は追加しない
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def classify_error(self, error: Exception) -> ErrorType:
        """エラーを分類"""
        error_str = str(error).lower()
        error_type_name = type(error).__name__.lower()

        # タイムアウトエラー
        if 'timeout' in error_str or 'timeout' in error_type_name:
            return ErrorType.TIMEOUT_ERROR

        # ネットワークエラー
        if any(keyword in error_str for keyword in ['connection', 'network', 'unreachable', 'refused']):
            return ErrorType.NETWORK_ERROR

        # レート制限エラー
        if 'rate' in error_str or '429' in error_str:
            return ErrorType.RATE_LIMIT_ERROR

        # 認証エラー
        if any(keyword in error_str for keyword in ['auth', 'unauthorized', '401', '403']):
            return ErrorType.AUTHENTICATION_ERROR

        # 無効なリクエスト
        if '400' in error_str or 'bad request' in error_str or 'invalid' in error_str:
            return ErrorType.INVALID_REQUEST

        # サーバーエラー
        if any(keyword in error_str for keyword in ['500', '502', '503', '504', 'server error']):
            return ErrorType.SERVER_ERROR

        return ErrorType.UNKNOWN_ERROR

    def should_retry(self, error_type: ErrorType, attempt: int) -> bool:
        """リトライすべきかどうかを判定"""
        # 最大リトライ回数を超えている場合はリトライしない
        if attempt >= self.config.max_retries:
            return False

        # リトライ可能なエラータイプ
        retryable_types = {
            ErrorType.NETWORK_ERROR,
            ErrorType.TIMEOUT_ERROR,
            ErrorType.RATE_LIMIT_ERROR,
            ErrorType.SERVER_ERROR
        }

        return error_type in retryable_types

    def calculate_delay(self, attempt: int, error_type: ErrorType) -> float:
        """リトライまでの待機時間を計算（指数バックオフ）"""
        # レート制限エラーの場合は長めに待機
        if error_type == ErrorType.RATE_LIMIT_ERROR:
            base_delay = self.config.initial_delay * 10
        else:
            base_delay = self.config.initial_delay

        # 指数バックオフ
        delay = base_delay * (self.config.exponential_base ** attempt)

        # 最大遅延時間を超えないようにする
        delay = min(delay, self.config.max_delay)

        # ジッターを追加（ランダム性）
        import random
        jitter = random.uniform(0, delay * 0.1)
        delay += jitter

        return delay

    def execute_with_retry(
        self,
        func: Callable,
        *args,
        operation_name: str = "operation",
        **kwargs
    ) -> Any:
        """
        関数をリトライロジック付きで実行

        Args:
            func: 実行する関数
            operation_name: 操作名（ログ用）
            *args, **kwargs: funcに渡す引数

        Returns:
            funcの戻り値

        Raises:
            NotificationError: リトライ後も失敗した場合
        """
        self.error_stats['total_calls'] += 1
        attempt = 0

        while attempt <= self.config.max_retries:
            try:
                if attempt > 0:
                    self.logger.info(
                        f"[{operation_name}] リトライ {attempt}/{self.config.max_retries}"
                    )

                # タイムアウト付きで実行
                result = func(*args, **kwargs)

                if attempt > 0:
                    self.logger.info(f"[{operation_name}] リトライ成功（試行回数: {attempt + 1}）")

                return result

            except Exception as e:
                self.error_stats['total_errors'] += 1
                error_type = self.classify_error(e)

                # エラー統計を更新
                error_type_str = error_type.value
                if error_type_str not in self.error_stats['errors_by_type']:
                    self.error_stats['errors_by_type'][error_type_str] = 0
                self.error_stats['errors_by_type'][error_type_str] += 1

                # エラーログ
                self.logger.error(
                    f"[{operation_name}] エラー発生 "
                    f"(試行回数: {attempt + 1}, エラータイプ: {error_type.value}): {str(e)}"
                )

                # リトライ判定
                if not self.should_retry(error_type, attempt):
                    self.logger.error(
                        f"[{operation_name}] リトライ不可能なエラー、または最大リトライ回数に到達"
                    )
                    raise NotificationError(
                        f"{operation_name} failed after {attempt + 1} attempts",
                        error_type,
                        e
                    )

                # 次のリトライまで待機
                attempt += 1
                if attempt <= self.config.max_retries:
                    delay = self.calculate_delay(attempt - 1, error_type)
                    self.error_stats['total_retries'] += 1
                    self.logger.warning(
                        f"[{operation_name}] {delay:.2f}秒後にリトライします..."
                    )
                    time.sleep(delay)

        # ここには到達しないはずだが、念のため
        raise NotificationError(
            f"{operation_name} failed after all retries",
            ErrorType.UNKNOWN_ERROR
        )

    def get_stats(self) -> Dict[str, Any]:
        """エラー統計を取得"""
        success_rate = 0.0
        if self.error_stats['total_calls'] > 0:
            success_rate = (
                (self.error_stats['total_calls'] - self.error_stats['total_errors']) /
                self.error_stats['total_calls'] * 100
            )

        return {
            **self.error_stats,
            'success_rate': success_rate,
            'average_retries_per_error': (
                self.error_stats['total_retries'] / self.error_stats['total_errors']
                if self.error_stats['total_errors'] > 0 else 0
            )
        }

    def reset_stats(self):
        """統計をリセット"""
        self.error_stats = {
            'total_calls': 0,
            'total_errors': 0,
            'total_retries': 0,
            'errors_by_type': {}
        }

    def log_stats(self):
        """統計をログに出力"""
        stats = self.get_stats()
        self.logger.info("=== 通知エラーハンドラー統計 ===")
        self.logger.info(f"総呼び出し数: {stats['total_calls']}")
        self.logger.info(f"総エラー数: {stats['total_errors']}")
        self.logger.info(f"総リトライ数: {stats['total_retries']}")
        self.logger.info(f"成功率: {stats['success_rate']:.2f}%")
        self.logger.info(f"エラーあたりの平均リトライ数: {stats['average_retries_per_error']:.2f}")
        self.logger.info("エラータイプ別:")
        for error_type, count in stats['errors_by_type'].items():
            self.logger.info(f"  {error_type}: {count}")
