"""
未来タスクハンドラー
未来タスク追加コマンドを処理
"""

import os
import re as regex
from linebot.v3.messaging import (
    TextMessage,
    ReplyMessageRequest,
    FlexMessage,
    FlexContainer,
)
from .helpers import create_flag_file, send_reply_message, delete_flag_file


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


def handle_future_task_process(
    line_bot_api,
    reply_token: str,
    user_id: str,
    user_message: str,
    task_service,
    get_simple_flex_menu
) -> bool:
    """
    未来タスク追加処理（メッセージ受信時）

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        user_message: ユーザーメッセージ
        task_service: タスクサービス
        get_simple_flex_menu: メニュー生成関数

    Returns:
        bool: 処理成功時True
    """
    try:
        created_count = 0
        created_names = []

        # 改行区切りで複数登録に対応（全改行コード対応）
        try:
            print(f"[DEBUG] 未来タスク入力repr: {repr(user_message)}")
        except Exception:
            pass

        lines = [l.strip() for l in regex.split(r"[\r\n\u000B\u000C\u0085\u2028\u2029]+", user_message) if l.strip()]
        print(f"[DEBUG] 未来タスク行数判定: {len(lines)}")

        if len(lines) > 1:
            # 複数行の場合
            for line in lines:
                info = task_service.parse_task_message(line)
                info["priority"] = "not_urgent_important"
                info["due_date"] = None
                task = task_service.create_future_task(user_id, info)
                created_count += 1
                created_names.append(task.name)
        else:
            # 単一行の場合
            task_info = task_service.parse_task_message(user_message.strip())
            task_info["priority"] = "not_urgent_important"
            task_info["due_date"] = None
            task = task_service.create_future_task(user_id, task_info)
            created_count = 1
            created_names = [task.name]

        print(f"[DEBUG] 未来タスク作成完了: {created_count}件, names={created_names}")

        # 未来タスク一覧を取得して表示
        future_tasks = task_service.get_user_future_tasks(user_id)
        print(f"[DEBUG] 未来タスク一覧取得完了: {len(future_tasks)}件")

        # 新しく追加したタスクの情報を確認
        print(f"[DEBUG] 新しく追加したタスク: task_id={task.task_id}, name={task.name}, duration={task.duration_minutes}分")
        print(f"[DEBUG] 未来タスク一覧詳細:")
        for i, ft in enumerate(future_tasks):
            print(f"[DEBUG] 未来タスク{i+1}: task_id={ft.task_id}, name={ft.name}, duration={ft.duration_minutes}分, created_at={ft.created_at}")

        reply_text = task_service.format_future_task_list(future_tasks, show_select_guide=False)
        if created_count > 1:
            reply_text += f"\n\n✅ 未来タスクを{created_count}件追加しました！"
        else:
            reply_text += "\n\n✅ 未来タスクを追加しました！"

        # フラグ削除
        delete_flag_file(user_id, "future_task")

        # メニュー画面を表示
        flex_message_content = get_simple_flex_menu()
        flex_container = FlexContainer.from_dict(flex_message_content)
        flex_message = FlexMessage(alt_text="メニュー", contents=flex_container)

        print(f"[DEBUG] 未来タスク追加モード返信メッセージ送信開始: {reply_text[:100]}...")
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text), flex_message],
            )
        )
        print(f"[DEBUG] 未来タスク追加モード返信メッセージ送信完了")
        print(f"[DEBUG] 未来タスク追加モード処理完了、処理を終了")
        return True

    except Exception as e:
        print(f"[DEBUG] 未来タスク追加モード処理エラー: {e}")
        import traceback
        traceback.print_exc()
        reply_text = f"⚠️ 未来タスク追加中にエラーが発生しました: {e}"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        return False
