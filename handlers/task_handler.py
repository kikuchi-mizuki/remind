"""
タスクコマンドハンドラー
タスク追加・削除コマンドを処理
"""

from .helpers import (
    create_flag_file,
    send_reply_message,
    send_reply_with_fallback,
    format_due_date,
)


def handle_task_add_command(line_bot_api, reply_token: str, user_id: str) -> bool:
    """
    タスク追加コマンドの処理（フラグ設定）

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID

    Returns:
        bool: 処理成功時True
    """
    print("[handle_task_add_command] タスク追加分岐: 処理開始", flush=True)

    # タスク追加モードフラグを作成
    create_flag_file(user_id, "add_task")

    guide_text = (
        "📝 タスク追加モード\n\n"
        "タスク名・所要時間・期限を入力してください！\n\n"
        "💡 例：\n"
        "• 「資料作成 30分 明日」\n"
        "• 「会議準備 1時間 今日」\n"
        "• 「筋トレ 20分 今週中」\n\n"
        "⚠️ 所要時間は必須です！\n"
    )

    return send_reply_with_fallback(line_bot_api, reply_token, user_id, guide_text)


def handle_task_delete_command(line_bot_api, reply_token: str, user_id: str, task_service) -> bool:
    """
    タスク削除コマンドの処理

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        task_service: タスクサービス

    Returns:
        bool: 処理成功時True
    """
    print(f"[handle_task_delete_command] タスク削除コマンド処理開始: user_id={user_id}")

    # 通常のタスクと未来タスクを取得
    all_tasks = task_service.get_user_tasks(user_id)
    future_tasks = task_service.get_user_future_tasks(user_id)

    reply_text = "🗑️ タスク削除\n━━━━━━━━━━━━\n"

    # 通常のタスクを表示
    if all_tasks:
        reply_text += "📋 通常タスク\n"
        for idx, task in enumerate(all_tasks, 1):
            # 期日表示
            if task.due_date:
                due_str = format_due_date(task.due_date)
            else:
                due_str = "期日未設定"

            # カード風に改行分割（タイトル行→メタ行）
            reply_text += f"タスク {idx}\n"
            reply_text += f"{task.name}\n"
            reply_text += f"   ⏳ {task.duration_minutes}分   📅 {due_str}\n\n"
    else:
        reply_text += "📋 通常タスク\n登録されているタスクはありません。\n\n"

    # 未来タスクを表示
    if future_tasks:
        reply_text += "🔮 未来タスク\n"
        for idx, task in enumerate(future_tasks, 1):
            reply_text += f"未来タスク {idx}\n"
            reply_text += f"{task.name}\n"
            reply_text += f"   ▸ ⏳ {task.duration_minutes}分\n\n"
    else:
        reply_text += "🔮 未来タスク\n登録されている未来タスクはありません。\n\n"

    reply_text += "━━━━━━━━━━━━\n"
    reply_text += "削除するタスクを選んでください！\n"
    reply_text += "例：「タスク 1、3」「未来タスク 2」「タスク 1、未来タスク 2」\n"

    # 削除モードファイルを作成
    create_flag_file(user_id, "delete")

    return send_reply_message(line_bot_api, reply_token, reply_text)
