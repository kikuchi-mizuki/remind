"""
入力バリデーションユーティリティ
ユーザー入力のサニタイゼーションとバリデーション
"""
import html
import re


# 定数
MAX_MESSAGE_LENGTH = 1000
MAX_TASK_NAME_LENGTH = 200


def sanitize_user_input(text: str) -> str:
    """
    ユーザー入力をサニタイズ

    Args:
        text: ユーザーからの入力文字列

    Returns:
        str: サニタイズされた文字列
    """
    if not text:
        return ""

    # HTMLエンティティをエスケープ（XSS対策）
    text = html.escape(text)

    # 制御文字を除去（改行・タブは保持）
    text = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', text)

    return text


def validate_message_length(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> bool:
    """
    メッセージ長をバリデーション

    Args:
        text: チェックする文字列
        max_length: 最大文字数

    Returns:
        bool: バリデーション成功時True
    """
    if not text:
        return True

    return len(text) <= max_length


def validate_and_sanitize(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> tuple[bool, str, str]:
    """
    入力を検証してサニタイズ

    Args:
        text: ユーザー入力
        max_length: 最大文字数

    Returns:
        tuple: (is_valid, sanitized_text, error_message)
    """
    if not text:
        return True, "", ""

    # 長さチェック
    if not validate_message_length(text, max_length):
        return False, "", f"入力が長すぎます（最大{max_length}文字）"

    # サニタイズ
    sanitized = sanitize_user_input(text)

    return True, sanitized, ""
