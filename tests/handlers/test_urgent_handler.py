"""
Tests for urgent_handler
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta
from handlers.urgent_handler import (
    handle_urgent_task_add_command,
    handle_urgent_task_process,
)


class TestHandleUrgentTaskAddCommand:
    """handle_urgent_task_add_command のテスト"""

    def test_add_command_with_authentication(self):
        """Google認証済みの場合にフラグが作成されること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        mock_is_google_authenticated = Mock(return_value=True)
        mock_get_google_auth_url = Mock()

        # Act
        with patch('handlers.urgent_handler.create_flag_file') as mock_create:
            with patch('handlers.urgent_handler.send_reply_message') as mock_send:
                result = handle_urgent_task_add_command(
                    mock_line_bot_api,
                    reply_token,
                    user_id,
                    mock_is_google_authenticated,
                    mock_get_google_auth_url
                )

        # Assert
        assert result is True
        mock_create.assert_called_once_with(user_id, "urgent_task")
        mock_send.assert_called_once()

    def test_add_command_without_authentication(self):
        """Google認証未完了の場合に認証URLが返ること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        mock_is_google_authenticated = Mock(return_value=False)
        mock_get_google_auth_url = Mock(return_value="https://auth.example.com")

        # Act
        with patch('handlers.urgent_handler.send_reply_message') as mock_send:
            result = handle_urgent_task_add_command(
                mock_line_bot_api,
                reply_token,
                user_id,
                mock_is_google_authenticated,
                mock_get_google_auth_url
            )

        # Assert
        assert result is True
        mock_get_google_auth_url.assert_called_once_with(user_id)
        mock_send.assert_called_once()


class TestHandleUrgentTaskProcess:
    """handle_urgent_task_process のテスト"""

    def test_process_with_free_time_available(self):
        """空き時間がある場合にタスクが作成されカレンダーに追加されること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "資料作成 1時間"

        mock_task_service = Mock()
        mock_calendar_service = Mock()
        mock_get_simple_flex_menu = Mock(return_value={"type": "bubble"})

        # Mock task
        mock_task = Mock(
            task_id=1,
            name="資料作成",
            duration_minutes=60
        )
        mock_task_service.parse_task_message.return_value = {
            "name": "資料作成",
            "duration_minutes": 60
        }
        mock_task_service.create_task.return_value = mock_task

        # Mock free times
        start_time = datetime.now()
        mock_calendar_service.get_free_busy_times.return_value = [
            {"start": start_time, "end": start_time + timedelta(hours=2)}
        ]
        mock_calendar_service.add_event_to_calendar.return_value = True

        # Act
        with patch('handlers.urgent_handler.delete_flag_file'):
            result = handle_urgent_task_process(
                mock_line_bot_api,
                reply_token,
                user_id,
                user_message,
                mock_task_service,
                mock_calendar_service,
                mock_get_simple_flex_menu
            )

        # Assert
        assert result is True
        mock_task_service.create_task.assert_called_once()
        mock_calendar_service.add_event_to_calendar.assert_called_once()
        mock_line_bot_api.reply_message.assert_called_once()

    def test_process_without_free_time(self):
        """空き時間がない場合に警告メッセージが返ること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "資料作成 1時間"

        mock_task_service = Mock()
        mock_calendar_service = Mock()
        mock_get_simple_flex_menu = Mock(return_value={"type": "bubble"})

        # Mock task
        mock_task = Mock(
            task_id=1,
            name="資料作成",
            duration_minutes=60
        )
        mock_task_service.parse_task_message.return_value = {
            "name": "資料作成",
            "duration_minutes": 60
        }
        mock_task_service.create_task.return_value = mock_task

        # No free times
        mock_calendar_service.get_free_busy_times.return_value = []

        # Act
        with patch('handlers.urgent_handler.delete_flag_file'):
            result = handle_urgent_task_process(
                mock_line_bot_api,
                reply_token,
                user_id,
                user_message,
                mock_task_service,
                mock_calendar_service,
                mock_get_simple_flex_menu
            )

        # Assert
        assert result is True
        mock_task_service.create_task.assert_called_once()
        mock_line_bot_api.reply_message.assert_called_once()
        # Verify warning message contains expected text
        call_args = mock_line_bot_api.reply_message.call_args
        messages = call_args[0][0].messages
        assert "空き時間が見つかりませんでした" in messages[0].text

    def test_process_with_error(self):
        """エラーが発生した場合にエラーメッセージが返ること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "無効なメッセージ"

        mock_task_service = Mock()
        mock_calendar_service = Mock()
        mock_get_simple_flex_menu = Mock(return_value={"type": "bubble"})

        # Mock error
        mock_task_service.parse_task_message.side_effect = Exception("Parse error")

        # Act
        with patch('handlers.urgent_handler.delete_flag_file'):
            result = handle_urgent_task_process(
                mock_line_bot_api,
                reply_token,
                user_id,
                user_message,
                mock_task_service,
                mock_calendar_service,
                mock_get_simple_flex_menu
            )

        # Assert
        assert result is False
        mock_line_bot_api.reply_message.assert_called_once()
