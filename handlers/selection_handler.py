"""
タスク選択ハンドラー
タスク選択処理（朝の通知・夜の通知）を処理
"""

import json
from datetime import datetime, timedelta
from typing import Optional
from linebot.v3.messaging import (
    TextMessage,
    ReplyMessageRequest,
)


def handle_task_selection_cancel(line_bot_api, reply_token: str, user_id: str, flex_menu_func) -> bool:
    """
    タスク選択のキャンセル処理

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        flex_menu_func: メニュー生成関数

    Returns:
        bool: 処理成功時True
    """
    from .helpers import delete_flag_file, send_reply_with_menu

    # フラグファイルを削除してモードをリセット
    delete_flag_file(user_id, "task_select")
    print(f"[DEBUG] タスク選択モードリセット: user_id={user_id} 削除")

    # 通常のFlexMessageメニューを表示
    send_reply_with_menu(line_bot_api, reply_token, flex_menu_func)
    return True


def handle_task_selection_process(
    line_bot_api,
    reply_token: str,
    user_id: str,
    user_message: str,
    task_service,
    openai_service,
    calendar_service,
    notification_service,
    is_google_authenticated,
    get_google_auth_url,
    db=None
) -> bool:
    """
    タスク選択処理（数字入力時）

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        user_message: ユーザーメッセージ
        task_service: タスクサービス
        openai_service: OpenAIサービス
        calendar_service: カレンダーサービス
        notification_service: 通知サービス
        is_google_authenticated: Google認証確認関数
        get_google_auth_url: Google認証URL取得関数

    Returns:
        bool: 処理成功時True
    """
    from .helpers import load_flag_data, delete_flag_file

    print(f"[DEBUG] タスク選択フラグ検出: user_id={user_id}")
    print(f"[DEBUG] タスク選択処理開始: user_message='{user_message}'")

    try:
        # 選択モードを先に判定（display_tasksの作成方法を決めるため）
        flag_data = load_flag_data(user_id, "task_select")
        mode_content = ""
        flag_timestamp = None
        target_date_str = None

        if flag_data:
            mode = flag_data.get("mode", "")
            flag_timestamp = flag_data.get("timestamp")
            target_date_str = flag_data.get("target_date")
            # mode=schedule の形式に変換
            if mode:
                mode_content = f"mode={mode}"
        else:
            print(f"[DEBUG] フラグデータの読み込みに失敗しました")
            mode_content = ""

        is_schedule_mode = "mode=schedule" in mode_content
        is_future_schedule_mode = "mode=future_schedule" in mode_content
        is_complete_mode = "mode=complete" in mode_content
        print(f"[DEBUG] 選択モード: {'future_schedule' if is_future_schedule_mode else ('schedule' if is_schedule_mode else ('complete' if is_complete_mode else 'unknown'))}, フラグ作成時刻: {flag_timestamp}")

        # datetime は先頭でインポート済み
        import pytz
        jst = pytz.timezone('Asia/Tokyo')
        today = datetime.now(jst)
        today_str = today.strftime('%Y-%m-%d')
        effective_today_str = target_date_str or today_str
        print(f"[DEBUG] 今日の日付文字列: {today_str}, target_date_str: {target_date_str}, effective_today_str: {effective_today_str}")

        # 未来タスク選択モードの場合は未来タスクを取得
        if is_future_schedule_mode:
            all_tasks = task_service.get_user_future_tasks(user_id)
            print(f"[DEBUG] 未来タスク取得: {len(all_tasks)}件, タスク一覧={[(i+1, t.name, t.due_date) for i, t in enumerate(all_tasks)]}")
        else:
            all_tasks = task_service.get_user_tasks(user_id)
            print(f"[DEBUG] 全タスク取得: {len(all_tasks)}件, タスク一覧={[(i+1, t.name, t.due_date) for i, t in enumerate(all_tasks)]}")

        # 削除モード（夜の通知）の場合は、通知と同じ方法で今日のタスクを取得
        if is_complete_mode:
            # 通知と同じ方法で今日のタスクを取得（単純なフィルタリング）
            for t in all_tasks:
                due_date_str = str(t.due_date) if t.due_date else None
                match = (t.due_date == effective_today_str) if t.due_date else False
                print(f"[DEBUG] タスク比較: name={t.name}, due_date={due_date_str}, type={type(t.due_date)}, match={match}")
            if effective_today_str:
                display_tasks = [t for t in all_tasks if t.due_date and str(t.due_date) == effective_today_str]
            else:
                display_tasks = [t for t in all_tasks if t.due_date and str(t.due_date) == today_str]
            print(f"[DEBUG] 削除モード: 今日のタスク数={len(display_tasks)}, タスク一覧={[(i+1, t.name) for i, t in enumerate(display_tasks)]}")
        else:
            # スケジュールモード（朝の通知）の場合は、format_task_listと同じソート順序を適用
            def sort_key(task):
                priority_order = {
                    "urgent_important": 0,
                    "not_urgent_important": 1,
                    "urgent_not_important": 2,
                    "normal": 3
                }
                priority_score = priority_order.get(task.priority, 3)
                due_date = task.due_date or '9999-12-31'
                return (priority_score, due_date, task.name)

            # 優先度と期日でソート
            from collections import defaultdict
            tasks_sorted = sorted(all_tasks, key=sort_key)
            print(f"[DEBUG] ソート後タスク数: {len(tasks_sorted)}件")

            # format_task_listと同じ順序でタスクを取得
            grouped = defaultdict(list)
            for task in tasks_sorted:
                grouped[task.due_date or '未設定'].append(task)
            print(f"[DEBUG] グループ化後: {len(grouped)}グループ")

            # 期日の順序を正確に再現
            due_order = []
            for due, group in sorted(grouped.items()):
                if due == today_str:
                    due_order.append(('本日まで', due, group))
                elif due != '未設定':
                    try:
                        y, m, d = due.split('-')
                        due_date_obj = datetime(int(y), int(m), int(d))
                        weekday_names = ['月', '火', '水', '木', '金', '土', '日']
                        weekday = weekday_names[due_date_obj.weekday()]
                        due_str = f"{int(m)}月{int(d)}日({weekday})"
                        due_order.append((due_str, due, group))
                    except (ValueError, IndexError) as e:
                        print(f"[DEBUG] Date parsing error: {e}")
                        due_order.append((due, due, group))
                else:
                    due_order.append(('期日未設定', due, group))

            # 表示順序と同じタスクリストを作成
            display_tasks = []
            for due_str, due, group in due_order:
                display_tasks.extend(group)

            print(f"[DEBUG] スケジュールモード: タスク数={len(display_tasks)}, タスク一覧={[(i+1, t.name) for i, t in enumerate(display_tasks)]}")

        # display_tasksが空の場合のデバッグ
        if not display_tasks:
            print(f"[DEBUG] 警告: display_tasksが空です！ all_tasks={len(all_tasks)}, is_complete_mode={is_complete_mode}, is_schedule_mode={is_schedule_mode}, is_future_schedule_mode={is_future_schedule_mode}, mode_content='{mode_content}'")

        # AIによる数字解析を試行
        selected_numbers = []
        try:
            ai_result = openai_service.extract_task_numbers_from_message(user_message)
            if ai_result and isinstance(ai_result.get("tasks"), list):
                selected_numbers = ai_result["tasks"]
                print(f"[DEBUG] AI数字解析成功: {selected_numbers}")
        except Exception as e:
            print(f"[DEBUG] AI数字解析失敗: {e}, フォールバック処理に移行")
            import traceback
            traceback.print_exc()

        # AIが失敗した場合は従来の方法で解析
        if not selected_numbers:
            import re
            # カンマ・句読点・スペースで区切って数字を抽出
            user_message_normalized = user_message.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
            matches = re.findall(r'\d+', user_message_normalized)
            selected_numbers = [int(m) for m in matches]
            print(f"[DEBUG] フォールバック数字解析: {selected_numbers}")

        if not selected_numbers:
            reply_text = "⚠️ タスク番号を認識できませんでした。\n数字で入力してください（例：1, 3, 5）"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
            return False

        # 選択されたタスクを取得
        selected_tasks = []
        for num in selected_numbers:
            idx = num - 1
            if 0 <= idx < len(display_tasks):
                selected_tasks.append(display_tasks[idx])
                print(f"[DEBUG] タスク選択: {num}. {display_tasks[idx].name}")
            else:
                print(f"[DEBUG] 無効なタスク番号: {num} (範囲: 1-{len(display_tasks)})")

        if not selected_tasks:
            reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
            return False

        # スケジュールモードまたは完了モードに応じて処理を分岐
        if is_schedule_mode or is_future_schedule_mode:
            # スケジュール提案フロー（朝）
            print(f"[DEBUG] スケジュール提案開始: {len(selected_tasks)}個のタスク")

            # Google認証チェック
            if not is_google_authenticated(user_id):
                auth_url = get_google_auth_url(user_id)
                reply_text = f"📅 カレンダー連携が必要です\n\nGoogleカレンダーにアクセスして認証してください：\n{auth_url}"
                delete_flag_file(user_id, "task_select")
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        replyToken=reply_token,
                        messages=[TextMessage(text=reply_text)],
                    )
                )
                return False

            # カレンダー情報取得
            if is_future_schedule_mode:
                # 来週月曜日を計算
                next_week_monday = today + timedelta(days=(7 - today.weekday()))
                base_date = next_week_monday
                week_info = "来週"
            else:
                base_date = today
                week_info = ""

            # スケジュール提案を生成
            try:
                from services.calendar_service import CalendarService
                calendar_service = CalendarService()
                free_times = calendar_service.get_free_busy_times(user_id, base_date)

                # OpenAIでスケジュール提案を生成
                proposal = openai_service.generate_schedule_proposal(
                    selected_tasks,
                    free_times,
                    week_info=week_info,
                    base_date=base_date
                )

                if proposal:
                    reply_text = proposal

                    # スケジュール提案をデータベースに保存
                    if db:
                        db.set_user_session(user_id, 'schedule_proposal', proposal, expires_hours=24)
                        db.set_user_session(
                            user_id,
                            'selected_tasks',
                            json.dumps([task.task_id for task in selected_tasks]),
                            expires_hours=24
                        )
                else:
                    reply_text = "⚠️ スケジュール提案の生成に失敗しました。"
            except Exception as e:
                print(f"[DEBUG] スケジュール提案エラー: {e}")
                import traceback
                traceback.print_exc()
                reply_text = f"⚠️ スケジュール提案中にエラーが発生しました: {e}"
        else:
            # 完了（削除確認）フロー（夜）
            print(f"[DEBUG] タスク削除開始: {len(selected_tasks)}個のタスク")
            task_names = [task.name for task in selected_tasks]
            reply_text = f"以下のタスクを削除しますか？\n\n"
            for i, name in enumerate(task_names, 1):
                reply_text += f"{i}. {name}\n"
            reply_text += "\n削除する場合は「はい」、キャンセルする場合は「キャンセル」と送信してください。"
            # 選択されたタスクをデータベースに保存
            if db:
                db.set_user_session(
                    user_id,
                    'selected_tasks',
                    json.dumps([task.task_id for task in selected_tasks]),
                    expires_hours=24
                )

        # フラグ削除と送信
        delete_flag_file(user_id, "task_select")
        print(f"[DEBUG] タスク選択モードフラグ削除完了: user_id={user_id}")
        print(f"[DEBUG] 選択結果送信開始: {reply_text[:100]}...")
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        print(f"[DEBUG] 選択結果送信完了")
        return True
    except Exception as e:
        print(f"[DEBUG] タスク選択処理エラー: {e}")
        reply_text = "⚠️ タスク選択処理中にエラーが発生しました。"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        return False
