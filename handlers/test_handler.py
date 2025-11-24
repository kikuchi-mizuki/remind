"""
テストコマンドハンドラー
デバッグ用のテストコマンドを処理
"""

from .helpers import send_reply_message


def handle_8am_test(line_bot_api, reply_token: str, user_id: str, notification_service) -> bool:
    """
    8時テストコマンドの処理

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        notification_service: 通知サービス

    Returns:
        bool: 処理成功時True
    """
    try:
        notification_service.send_daily_task_notification()
        reply_text = "8時テスト通知を送信しました"
    except Exception as e:
        reply_text = f"8時テストエラー: {e}"

    return send_reply_message(line_bot_api, reply_token, reply_text)


def handle_9pm_test(line_bot_api, reply_token: str, user_id: str, notification_service) -> bool:
    """
    21時テストコマンドの処理

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        notification_service: 通知サービス

    Returns:
        bool: 処理成功時True（実際の通知が送信されるため、確認メッセージは送信しない）
    """
    try:
        notification_service.send_carryover_check()
        # 実際の通知内容も送信するため、確認メッセージは送信しない
        return True
    except Exception as e:
        reply_text = f"21時テストエラー: {e}"
        return send_reply_message(line_bot_api, reply_token, reply_text)


def handle_sunday_6pm_test(line_bot_api, reply_token: str, user_id: str, notification_service) -> bool:
    """
    日曜18時テストコマンドの処理

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        notification_service: 通知サービス

    Returns:
        bool: 処理成功時True（実際の通知が送信されるため、確認メッセージは送信しない）
    """
    try:
        notification_service.send_future_task_selection()
        # 実際の通知内容も送信するため、確認メッセージは送信しない
        return True
    except Exception as e:
        reply_text = f"日曜18時テストエラー: {e}"
        return send_reply_message(line_bot_api, reply_token, reply_text)


def handle_scheduler_check(line_bot_api, reply_token: str, user_id: str, notification_service) -> bool:
    """
    スケジューラー確認コマンドの処理

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        notification_service: 通知サービス

    Returns:
        bool: 処理成功時True
    """
    scheduler_status = notification_service.is_running
    thread_status = (
        notification_service.scheduler_thread.is_alive()
        if notification_service.scheduler_thread
        else False
    )
    reply_text = f"スケジューラー状態:\n- is_running: {scheduler_status}\n- スレッド動作: {thread_status}"

    return send_reply_message(line_bot_api, reply_token, reply_text)
