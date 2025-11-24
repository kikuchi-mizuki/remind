"""
共通ヘルパー関数
LINE botのコマンド処理で共通して使われる機能を提供
"""

import os
import json
from datetime import datetime
from typing import Optional
from linebot.v3.messaging import (
    TextMessage,
    ReplyMessageRequest,
    PushMessageRequest,
)


def create_flag_file(user_id: str, mode: str, data: Optional[dict] = None) -> bool:
    """
    フラグファイルを作成

    Args:
        user_id: ユーザーID
        mode: モード名（add_task, urgent_task, future_task, delete など）
        data: 追加で保存するデータ（オプション）

    Returns:
        bool: 作成成功時True
    """
    try:
        flag_file = f"{mode}_mode_{user_id}.json" if mode not in ["add_task"] else f"{mode}_mode_{user_id}.flag"

        if flag_file.endswith('.json'):
            with open(flag_file, "w") as f:
                default_data = {"mode": mode, "timestamp": datetime.now().isoformat()}
                if data:
                    default_data.update(data)
                json.dump(default_data, f)
        else:
            with open(flag_file, "w") as f:
                f.write(f"{mode}_mode")

        print(f"[create_flag_file] フラグファイル作成: {flag_file}, exists={os.path.exists(flag_file)}")
        return True
    except Exception as e:
        print(f"[create_flag_file] エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_flag_file(user_id: str, mode: str) -> bool:
    """
    フラグファイルの存在をチェック

    Args:
        user_id: ユーザーID
        mode: モード名

    Returns:
        bool: ファイルが存在する場合True
    """
    flag_file = f"{mode}_mode_{user_id}.json" if mode not in ["add_task"] else f"{mode}_mode_{user_id}.flag"
    exists = os.path.exists(flag_file)
    if exists:
        print(f"[check_flag_file] フラグ検出: {flag_file}")
    return exists


def delete_flag_file(user_id: str, mode: str) -> bool:
    """
    フラグファイルを削除

    Args:
        user_id: ユーザーID
        mode: モード名

    Returns:
        bool: 削除成功時True
    """
    try:
        flag_file = f"{mode}_mode_{user_id}.json" if mode not in ["add_task"] else f"{mode}_mode_{user_id}.flag"
        if os.path.exists(flag_file):
            os.remove(flag_file)
            print(f"[delete_flag_file] フラグファイル削除: {flag_file}")
            return True
        return False
    except Exception as e:
        print(f"[delete_flag_file] エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_reply_message(line_bot_api, reply_token: str, text: str) -> bool:
    """
    LINEにreplyメッセージを送信

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        text: 送信するテキスト

    Returns:
        bool: 送信成功時True
    """
    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
        print(f"[send_reply_message] メッセージ送信成功")
        return True
    except Exception as e:
        print(f"[send_reply_message] エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_reply_with_fallback(line_bot_api, reply_token: str, user_id: str, text: str) -> bool:
    """
    LINEにreplyメッセージを送信（失敗時はpushでフォールバック）

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID（push送信用）
        text: 送信するテキスト

    Returns:
        bool: 送信成功時True
    """
    try:
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
        print(f"[send_reply_with_fallback] reply送信成功")
        return True
    except Exception as e:
        print(f"[send_reply_with_fallback] reply送信エラー: {e}")
        # pushでフォールバック
        try:
            line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=text)],
                )
            )
            print(f"[send_reply_with_fallback] push送信成功")
            return True
        except Exception as e2:
            print(f"[send_reply_with_fallback] push送信エラー: {e2}")
            import traceback
            traceback.print_exc()
            return False


def format_due_date(due_date_str: str) -> str:
    """
    期日文字列を読みやすい形式にフォーマット

    Args:
        due_date_str: YYYY-MM-DD形式の期日文字列

    Returns:
        str: フォーマットされた期日（例: "12月25日(月)"）
    """
    try:
        y, m, d = due_date_str.split("-")
        due_date_obj = datetime(int(y), int(m), int(d))
        weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
        weekday = weekday_names[due_date_obj.weekday()]
        return f"{int(m)}月{int(d)}日({weekday})"
    except Exception as e:
        print(f"[format_due_date] エラー: {e}")
        return due_date_str


def load_flag_data(user_id: str, mode: str) -> Optional[dict]:
    """
    フラグファイルからデータを読み込み

    Args:
        user_id: ユーザーID
        mode: モード名

    Returns:
        Optional[dict]: 読み込んだデータ、失敗時None
    """
    try:
        flag_file = f"{mode}_mode_{user_id}.json"
        if os.path.exists(flag_file):
            with open(flag_file, "r") as f:
                return json.load(f)
        return None
    except Exception as e:
        print(f"[load_flag_data] エラー: {e}")
        return None


def save_data_file(filename: str, data: dict) -> bool:
    """
    データをJSONファイルに保存

    Args:
        filename: ファイル名
        data: 保存するデータ

    Returns:
        bool: 保存成功時True
    """
    try:
        with open(filename, "w") as f:
            json.dump(data, f)
        print(f"[save_data_file] データ保存成功: {filename}")
        return True
    except Exception as e:
        print(f"[save_data_file] エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def load_data_file(filename: str) -> Optional[dict]:
    """
    JSONファイルからデータを読み込み

    Args:
        filename: ファイル名

    Returns:
        Optional[dict]: 読み込んだデータ、失敗時None
    """
    try:
        if os.path.exists(filename):
            with open(filename, "r") as f:
                return json.load(f)
        return None
    except Exception as e:
        print(f"[load_data_file] エラー: {e}")
        return None


def delete_data_file(filename: str) -> bool:
    """
    データファイルを削除

    Args:
        filename: ファイル名

    Returns:
        bool: 削除成功時True
    """
    try:
        if os.path.exists(filename):
            os.remove(filename)
            print(f"[delete_data_file] ファイル削除: {filename}")
            return True
        return False
    except Exception as e:
        print(f"[delete_data_file] エラー: {e}")
        return None
