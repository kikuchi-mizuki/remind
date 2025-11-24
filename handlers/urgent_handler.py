"""
緊急タスクハンドラー
緊急タスク追加コマンドを処理
"""

import os
from datetime import datetime, timedelta
from linebot.v3.messaging import (
    TextMessage,
    ReplyMessageRequest,
    FlexMessage,
    FlexContainer,
)
from .helpers import create_flag_file, send_reply_message, delete_flag_file


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


def handle_urgent_task_process(
    line_bot_api,
    reply_token: str,
    user_id: str,
    user_message: str,
    task_service,
    calendar_service,
    get_simple_flex_menu
) -> bool:
    """
    緊急タスク追加処理（メッセージ受信時）

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        user_message: ユーザーメッセージ
        task_service: タスクサービス
        calendar_service: カレンダーサービス
        get_simple_flex_menu: メニュー生成関数

    Returns:
        bool: 処理成功時True
    """
    try:
        # タスク情報を解析
        task_info = task_service.parse_task_message(user_message)
        task_info["priority"] = "urgent_not_important"

        # 今日の日付を設定
        import pytz
        jst = pytz.timezone("Asia/Tokyo")
        today = datetime.now(jst)
        task_info["due_date"] = today.strftime("%Y-%m-%d")

        # タスク作成
        task = task_service.create_task(user_id, task_info)
        print(f"[DEBUG] 緊急タスク作成完了: task_id={task.task_id}")

        # 今日の空き時間に直接スケジュール追加
        free_times = calendar_service.get_free_busy_times(user_id, today)

        if free_times:
            first_free_time = free_times[0]
            start_time = first_free_time["start"]
            end_time = start_time + timedelta(minutes=task.duration_minutes)
            success = calendar_service.add_event_to_calendar(
                user_id=user_id,
                task_name=task.name,
                start_time=start_time,
                duration_minutes=task.duration_minutes,
                description=f"緊急タスク: {task.name}",
            )

            if success:
                reply_text = "⚡ 緊急タスクを追加しました！\n\n"
                reply_text += f"📅 今日のスケジュールに追加：\n"
                reply_text += f"🕐 {start_time.strftime('%H:%M')}〜{end_time.strftime('%H:%M')}\n"
                reply_text += f"📝 {task.name}\n\n"
                reply_text += "✅ カレンダーに直接追加されました！"
            else:
                reply_text = "⚡ 緊急タスクを追加しました！\n\n"
                reply_text += "⚠️ カレンダーへの追加に失敗しました。\n"
                reply_text += "手動でスケジュールを調整してください。"
        else:
            reply_text = "⚡ 緊急タスクを追加しました！\n\n"
            reply_text += "⚠️ 今日の空き時間が見つかりませんでした。\n"
            reply_text += "手動でスケジュールを調整してください。"

        # フラグ削除
        delete_flag_file(user_id, "urgent_task")
        print(f"[DEBUG] 緊急タスク追加モードフラグ削除: user_id={user_id}")

        # メニュー画面を表示
        flex_message_content = get_simple_flex_menu()
        flex_container = FlexContainer.from_dict(flex_message_content)
        flex_message = FlexMessage(alt_text="メニュー", contents=flex_container)

        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text), flex_message],
            )
        )
        return True

    except Exception as e:
        print(f"[DEBUG] 緊急タスク追加エラー: {e}")
        reply_text = f"⚠️ 緊急タスク追加中にエラーが発生しました: {e}"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        # エラー時もフラグを削除
        delete_flag_file(user_id, "urgent_task")
        return False
