"""
Tests for selection_handler
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from handlers.selection_handler import (
    handle_task_selection_cancel,
    handle_task_selection_process,
)


class TestHandleTaskSelectionCancel:
    """handle_task_selection_cancel のテスト"""

    def test_cancel_success(self):
        """タスク選択キャンセルが成功すること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        mock_flex_menu_func = Mock(return_value={"type": "bubble"})

        # Act
        with patch('handlers.selection_handler.delete_flag_file') as mock_delete:
            with patch('handlers.selection_handler.send_reply_with_menu') as mock_send:
                result = handle_task_selection_cancel(
                    mock_line_bot_api,
                    reply_token,
                    user_id,
                    mock_flex_menu_func
                )

        # Assert
        assert result is True
        mock_delete.assert_called_once_with(user_id, "task_select")
        mock_send.assert_called_once_with(
            mock_line_bot_api,
            reply_token,
            mock_flex_menu_func
        )


class TestHandleTaskSelectionProcess:
    """handle_task_selection_process のテスト"""

    def test_process_with_valid_numbers(self):
        """有効な数字入力でタスク選択処理が成功すること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "1, 2, 3"

        mock_task_service = Mock()
        mock_openai_service = Mock()
        mock_calendar_service = Mock()
        mock_notification_service = Mock()
        mock_is_google_authenticated = Mock(return_value=True)
        mock_get_google_auth_url = Mock()

        # Mock tasks
        mock_task1 = Mock(name="Task 1", due_date="2025-11-24", priority="normal", task_id=1)
        mock_task2 = Mock(name="Task 2", due_date="2025-11-24", priority="normal", task_id=2)
        mock_task3 = Mock(name="Task 3", due_date="2025-11-24", priority="normal", task_id=3)
        mock_task_service.get_user_tasks.return_value = [mock_task1, mock_task2, mock_task3]

        # Mock OpenAI response
        mock_openai_service.extract_task_numbers_from_message.return_value = {
            "tasks": [1, 2, 3]
        }

        # Act
        with patch('handlers.selection_handler.load_flag_data') as mock_load:
            mock_load.return_value = {"mode": "complete", "timestamp": "2025-11-24T10:00:00"}
            with patch('handlers.selection_handler.delete_flag_file'):
                result = handle_task_selection_process(
                    mock_line_bot_api,
                    reply_token,
                    user_id,
                    user_message,
                    mock_task_service,
                    mock_openai_service,
                    mock_calendar_service,
                    mock_notification_service,
                    mock_is_google_authenticated,
                    mock_get_google_auth_url
                )

        # Assert
        assert result is True
        mock_task_service.get_user_tasks.assert_called_once_with(user_id)
        mock_line_bot_api.reply_message.assert_called_once()

    def test_process_with_invalid_numbers(self):
        """無効な数字入力でエラーメッセージが返ること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "99, 100"  # 範囲外の番号

        mock_task_service = Mock()
        mock_openai_service = Mock()
        mock_calendar_service = Mock()
        mock_notification_service = Mock()
        mock_is_google_authenticated = Mock(return_value=True)
        mock_get_google_auth_url = Mock()

        # Mock tasks (only 3 tasks)
        mock_task1 = Mock(name="Task 1", due_date="2025-11-24", priority="normal", task_id=1)
        mock_task2 = Mock(name="Task 2", due_date="2025-11-24", priority="normal", task_id=2)
        mock_task3 = Mock(name="Task 3", due_date="2025-11-24", priority="normal", task_id=3)
        mock_task_service.get_user_tasks.return_value = [mock_task1, mock_task2, mock_task3]

        # Mock OpenAI response
        mock_openai_service.extract_task_numbers_from_message.return_value = {
            "tasks": [99, 100]
        }

        # Act
        with patch('handlers.selection_handler.load_flag_data') as mock_load:
            mock_load.return_value = {"mode": "complete", "timestamp": "2025-11-24T10:00:00"}
            with patch('handlers.selection_handler.delete_flag_file'):
                result = handle_task_selection_process(
                    mock_line_bot_api,
                    reply_token,
                    user_id,
                    user_message,
                    mock_task_service,
                    mock_openai_service,
                    mock_calendar_service,
                    mock_notification_service,
                    mock_is_google_authenticated,
                    mock_get_google_auth_url
                )

        # Assert
        assert result is False
        mock_line_bot_api.reply_message.assert_called_once()

    def test_process_without_numbers(self):
        """数字が認識できない場合にエラーメッセージが返ること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        user_message = "タスクを選択"  # 数字なし

        mock_task_service = Mock()
        mock_openai_service = Mock()
        mock_calendar_service = Mock()
        mock_notification_service = Mock()
        mock_is_google_authenticated = Mock(return_value=True)
        mock_get_google_auth_url = Mock()

        mock_task_service.get_user_tasks.return_value = []

        # Mock OpenAI response (no numbers detected)
        mock_openai_service.extract_task_numbers_from_message.return_value = {
            "tasks": []
        }

        # Act
        with patch('handlers.selection_handler.load_flag_data') as mock_load:
            mock_load.return_value = {"mode": "complete", "timestamp": "2025-11-24T10:00:00"}
            result = handle_task_selection_process(
                mock_line_bot_api,
                reply_token,
                user_id,
                user_message,
                mock_task_service,
                mock_openai_service,
                mock_calendar_service,
                mock_notification_service,
                mock_is_google_authenticated,
                mock_get_google_auth_url
            )

        # Assert
        assert result is False
        mock_line_bot_api.reply_message.assert_called_once()
