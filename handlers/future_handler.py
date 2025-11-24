"""
未来タスクハンドラー
未来タスク追加コマンドを処理
"""

from .helpers import create_flag_file, send_reply_message


def handle_future_task_add_command(line_bot_api, reply_token: str, user_id: str) -> bool:
    """
    未来タスク追加コマンドの処理（フラグ設定）

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID

    Returns:
        bool: 処理成功時True
    """
    # 未来タスク追加モードフラグを作成
    create_flag_file(user_id, "future_task")

    reply_text = (
        "🔮 未来タスク追加モード\n\n"
        "投資につながるタスク名と所要時間を送信してください！\n\n"
        "📝 例：\n"
        "• 新規事業計画 2時間\n"
        "• 営業資料の見直し 1時間半\n"
        "• 〇〇という本を読む 30分\n"
        "• 3カ年事業計画をつくる 3時間\n\n"
        "⚠️ 所要時間は必須です！\n"
        "※毎週日曜日18時に来週やるタスクを選択できます"
    )

    return send_reply_message(line_bot_api, reply_token, reply_text)
