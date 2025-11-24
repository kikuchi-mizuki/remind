"""
Tests for future_handler
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from handlers.future_handler import (
    handle_future_task_add_command,
    handle_future_task_process,
)


class TestHandleFutureTaskAddCommand:
    """handle_future_task_add_command のテスト"""

    def test_add_command_success(self):
        """未来タスク追加コマンドが成功すること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"

        # Act
        with patch('handlers.future_handler.create_flag_file') as mock_create:
            with patch('handlers.future_handler.send_reply_message') as mock_send:
                result = handle_future_task_add_command(
                    mock_line_bot_api,
                    reply_token,
                    user_id
                )

        # Assert
        assert result is True
        mock_create.assert_called_once_with(user_id, "future_task")
        mock_send.assert_called_once()


class TestHandleFutureTaskProcess:
    """handle_future_task_process のテスト"""

    def test_process_single_task(self):
        """単一タスク追加が成功すること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "新規事業計画 2時間"

        mock_task_service = Mock()
        mock_get_simple_flex_menu = Mock(return_value={"type": "bubble"})

        # Mock task
        mock_task = Mock(
            task_id=1,
            name="新規事業計画",
            duration_minutes=120,
            created_at="2025-11-24T10:00:00"
        )
        mock_task_service.parse_task_message.return_value = {
            "name": "新規事業計画",
            "duration_minutes": 120
        }
        mock_task_service.create_future_task.return_value = mock_task
        mock_task_service.get_user_future_tasks.return_value = [mock_task]
        mock_task_service.format_future_task_list.return_value = "未来タスク一覧"

        # Act
        with patch('handlers.future_handler.delete_flag_file'):
            result = handle_future_task_process(
                mock_line_bot_api,
                reply_token,
                user_id,
                user_message,
                mock_task_service,
                mock_get_simple_flex_menu
            )

        # Assert
        assert result is True
        mock_task_service.create_future_task.assert_called_once()
        mock_task_service.get_user_future_tasks.assert_called_once_with(user_id)
        mock_line_bot_api.reply_message.assert_called_once()

    def test_process_multiple_tasks(self):
        """複数タスク追加が成功すること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "新規事業計画 2時間\n営業資料の見直し 1時間半"

        mock_task_service = Mock()
        mock_get_simple_flex_menu = Mock(return_value={"type": "bubble"})

        # Mock tasks
        mock_task1 = Mock(
            task_id=1,
            name="新規事業計画",
            duration_minutes=120,
            created_at="2025-11-24T10:00:00"
        )
        mock_task2 = Mock(
            task_id=2,
            name="営業資料の見直し",
            duration_minutes=90,
            created_at="2025-11-24T10:01:00"
        )

        # Mock parse_task_message to return different values for each call
        mock_task_service.parse_task_message.side_effect = [
            {"name": "新規事業計画", "duration_minutes": 120},
            {"name": "営業資料の見直し", "duration_minutes": 90}
        ]
        mock_task_service.create_future_task.side_effect = [mock_task1, mock_task2]
        mock_task_service.get_user_future_tasks.return_value = [mock_task1, mock_task2]
        mock_task_service.format_future_task_list.return_value = "未来タスク一覧"

        # Act
        with patch('handlers.future_handler.delete_flag_file'):
            result = handle_future_task_process(
                mock_line_bot_api,
                reply_token,
                user_id,
                user_message,
                mock_task_service,
                mock_get_simple_flex_menu
            )

        # Assert
        assert result is True
        assert mock_task_service.create_future_task.call_count == 2
        mock_task_service.get_user_future_tasks.assert_called_once_with(user_id)
        mock_line_bot_api.reply_message.assert_called_once()

        # Verify message contains "2件追加"
        call_args = mock_line_bot_api.reply_message.call_args
        messages = call_args[0][0].messages
        assert "2件追加" in messages[0].text

    def test_process_with_error(self):
        """エラーが発生した場合にエラーメッセージが返ること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "無効なメッセージ"

        mock_task_service = Mock()
        mock_get_simple_flex_menu = Mock(return_value={"type": "bubble"})

        # Mock error
        mock_task_service.parse_task_message.side_effect = Exception("Parse error")

        # Act
        result = handle_future_task_process(
            mock_line_bot_api,
            reply_token,
            user_id,
            user_message,
            mock_task_service,
            mock_get_simple_flex_menu
        )

        # Assert
        assert result is False
        mock_line_bot_api.reply_message.assert_called_once()
