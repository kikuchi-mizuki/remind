"""
緊急タスクハンドラー
緊急タスク追加コマンドを処理
"""

from .helpers import create_flag_file, send_reply_message


def handle_urgent_task_add_command(
    line_bot_api, reply_token: str, user_id: str, is_google_authenticated_func, get_google_auth_url_func
) -> bool:
    """
    緊急タスク追加コマンドの処理（フラグ設定）

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        is_google_authenticated_func: Google認証チェック関数
        get_google_auth_url_func: Google認証URL取得関数

    Returns:
        bool: 処理成功時True
    """
    # Google認証チェック
    if not is_google_authenticated_func(user_id):
        auth_url = get_google_auth_url_func(user_id)
        reply_text = f"📅 カレンダー連携が必要です\n\nGoogleカレンダーにアクセスして認証してください：\n{auth_url}"
        return send_reply_message(line_bot_api, reply_token, reply_text)

    # 緊急タスク追加モードフラグを作成
    create_flag_file(user_id, "urgent_task")

    reply_text = (
        "🚨 緊急タスク追加モード\n\n"
        "タスク名と所要時間を送信してください！\n"
        "例：「資料作成 1時間半」\n\n"
        "※今日の空き時間に自動でスケジュールされます"
    )

    return send_reply_message(line_bot_api, reply_token, reply_text)
