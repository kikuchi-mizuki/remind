"""
Tests for approval_handler
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, mock_open
from handlers.approval_handler import (
    handle_approval,
    handle_modification,
)


class TestHandleApproval:
    """handle_approval のテスト"""

    def test_approval_without_schedule_proposal(self):
        """スケジュール提案がない場合にタスク削除処理が実行されること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        mock_task_service = Mock()
        mock_calendar_service = Mock()
        mock_get_simple_flex_menu = Mock(return_value={"type": "bubble"})

        # Mock selected tasks file
        mock_task1 = Mock(task_id=1, name="Task 1")
        mock_task2 = Mock(task_id=2, name="Task 2")
        mock_task_service.get_user_tasks.return_value = [mock_task1, mock_task2]

        # Act
        with patch('handlers.approval_handler.os.path.exists') as mock_exists:
            mock_exists.side_effect = lambda path: "selected_tasks" in path
            with patch('builtins.open', mock_open(read_data='[1, 2]')):
                with patch('handlers.approval_handler.os.remove'):
                    result = handle_approval(
                        mock_line_bot_api,
                        reply_token,
                        user_id,
                        mock_task_service,
                        mock_calendar_service,
                        mock_get_simple_flex_menu
                    )

        # Assert
        assert result is True
        mock_task_service.delete_task.assert_called()
        mock_line_bot_api.reply_message.assert_called_once()

    def test_approval_without_selected_tasks_file(self):
        """selected_tasks ファイルがない場合にエラーメッセージが返ること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        mock_task_service = Mock()
        mock_calendar_service = Mock()
        mock_get_simple_flex_menu = Mock(return_value={"type": "bubble"})

        # Act
        with patch('handlers.approval_handler.os.path.exists', return_value=False):
            result = handle_approval(
                mock_line_bot_api,
                reply_token,
                user_id,
                mock_task_service,
                mock_calendar_service,
                mock_get_simple_flex_menu
            )

        # Assert
        assert result is False
        mock_line_bot_api.reply_message.assert_called_once()


class TestHandleModification:
    """handle_modification のテスト"""

    def test_modification_with_normal_mode(self):
        """通常モードの場合にタスク一覧が表示されること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        mock_task_service = Mock()

        mock_task_service.get_user_tasks.return_value = []
        mock_task_service.format_task_list.return_value = "タスク一覧"

        # Act
        with patch('handlers.approval_handler.load_flag_data') as mock_load:
            mock_load.return_value = {"mode": "schedule"}
            with patch('handlers.approval_handler.os.path.exists', return_value=False):
                with patch('handlers.approval_handler.create_flag_file'):
                    result = handle_modification(
                        mock_line_bot_api,
                        reply_token,
                        user_id,
                        mock_task_service
                    )

        # Assert
        assert result is True
        mock_task_service.format_task_list.assert_called_once()
        mock_line_bot_api.reply_message.assert_called_once()

    def test_modification_with_future_mode(self):
        """未来タスクモードの場合に未来タスク一覧が表示されること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        mock_task_service = Mock()

        mock_task_service.get_user_future_tasks.return_value = []
        mock_task_service.format_future_task_list.return_value = "未来タスク一覧"

        # Act
        with patch('handlers.approval_handler.load_flag_data') as mock_load:
            mock_load.return_value = {"mode": "future_schedule"}
            with patch('handlers.approval_handler.os.path.exists', return_value=False):
                result = handle_modification(
                    mock_line_bot_api,
                    reply_token,
                    user_id,
                    mock_task_service
                )

        # Assert
        assert result is True
        mock_task_service.format_future_task_list.assert_called_once()
        mock_line_bot_api.reply_message.assert_called_once()

    def test_modification_with_error(self):
        """エラーが発生した場合にエラーメッセージが返ること"""
        # Arrange
        mock_line_bot_api = Mock()
        reply_token = "test_reply_token"
        user_id = "test_user_id"
        mock_task_service = Mock()

        # Mock error
        mock_task_service.get_user_tasks.side_effect = Exception("Database error")

        # Act
        with patch('handlers.approval_handler.load_flag_data') as mock_load:
            mock_load.return_value = {"mode": "schedule"}
            with patch('handlers.approval_handler.os.path.exists', return_value=False):
                with patch('handlers.approval_handler.create_flag_file'):
                    result = handle_modification(
                        mock_line_bot_api,
                        reply_token,
                        user_id,
                        mock_task_service
                    )

        # Assert
        assert result is False
        mock_line_bot_api.reply_message.assert_called_once()
