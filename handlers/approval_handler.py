"""
承認・修正ハンドラー
スケジュール提案の承認・修正処理、タスク削除の承認処理
"""

import json
import os
from datetime import datetime, timedelta
from linebot.v3.messaging import (
    TextMessage,
    ReplyMessageRequest,
    FlexMessage,
    FlexContainer,
)
from .helpers import load_flag_data


def handle_approval(
    line_bot_api,
    reply_token: str,
    user_id: str,
    task_service,
    calendar_service,
    get_simple_flex_menu,
    db=None
) -> bool:
    """
    「はい」コマンドの処理
    - スケジュール提案がある場合: カレンダーに追加
    - それ以外: タスク削除の承認

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        task_service: タスクサービス
        calendar_service: カレンダーサービス
        get_simple_flex_menu: メニュー生成関数
        db: データベースインスタンス

    Returns:
        bool: 処理成功時True
    """
    # データベースからスケジュール提案をチェック
    schedule_proposal = db.get_user_session(user_id, 'schedule_proposal') if db else None
    if schedule_proposal:
        # スケジュール提案が存在する場合、承認処理を実行
        return _handle_schedule_approval(
            line_bot_api,
            reply_token,
            user_id,
            task_service,
            calendar_service,
            get_simple_flex_menu,
            schedule_proposal,
            db
        )

    # スケジュール提案がない場合の削除処理
    return _handle_task_deletion(
        line_bot_api,
        reply_token,
        user_id,
        task_service,
        get_simple_flex_menu,
        db
    )


def _handle_schedule_approval(
    line_bot_api,
    reply_token: str,
    user_id: str,
    task_service,
    calendar_service,
    get_simple_flex_menu,
    proposal: str,
    db=None
) -> bool:
    """スケジュール提案の承認処理"""
    try:
        # 選択されたタスクを取得
        selected_tasks_data = db.get_user_session(user_id, 'selected_tasks') if db else None
        if not selected_tasks_data:
            reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
            return False

        try:
            task_ids = json.loads(selected_tasks_data)
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON parsing failed: {e}")
            reply_text = "⚠️ タスクデータの読み込みに失敗しました。もう一度タスクを選択してください。"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
            return False

        # モードを判定
        current_mode = "schedule"  # デフォルト
        flag_data = load_flag_data(user_id, "task_select")
        if flag_data:
            current_mode = flag_data.get("mode", "schedule")
            print(f"[DEBUG] 承認処理モード判定: mode={current_mode}")

        # 未来タスク選択モードの場合は追加確認
        if current_mode == "schedule" and db:
            future_selection_data = db.get_user_session(user_id, 'future_task_selection')
            if future_selection_data:
                try:
                    future_mode_data = json.loads(future_selection_data)
                    if future_mode_data.get("mode") == "future_schedule":
                        current_mode = "future_schedule"
                        print(f"[DEBUG] 未来タスク選択モード検出")
                except Exception:
                    pass

        # モードに応じて適切なタスクリストを取得
        is_future_mode = (current_mode == "future_schedule")

        if is_future_mode:
            # 未来タスクのみ取得
            future_tasks = task_service.get_user_future_tasks(user_id)
            selected_tasks = []
            selected_future_tasks = [t for t in future_tasks if t.task_id in task_ids]
            print(f"[DEBUG] 未来タスクモード: {len(selected_future_tasks)}個の未来タスクを選択")
        else:
            # 通常タスクのみ取得
            all_tasks = task_service.get_user_tasks(user_id)
            selected_tasks = [t for t in all_tasks if t.task_id in task_ids]
            selected_future_tasks = []
            print(f"[DEBUG] 通常タスクモード: {len(selected_tasks)}個のタスクを選択")

        # 未来タスクがある場合は通常のタスクに変換
        for future_task in selected_future_tasks:
            task_info = {
                "name": future_task.name,
                "duration_minutes": future_task.duration_minutes,
                "priority": "not_urgent_important",
                "due_date": None,
                "repeat": False,
            }
            converted_task = task_service.create_task(user_id, task_info)
            selected_tasks.append(converted_task)
            print(f"[DEBUG] 未来タスクを通常タスクに変換（未来タスクは保持）: {future_task.name} -> {converted_task.task_id}")

        # カレンダーに追加
        import pytz
        jst = pytz.timezone("Asia/Tokyo")

        if selected_future_tasks:
            # 未来タスクの場合：来週の日付で処理
            today = datetime.now(jst)
            next_week = today + timedelta(days=7)
            target_date = next_week
            print(f"[DEBUG] 未来タスク処理: 来週の日付 {target_date.strftime('%Y-%m-%d')} を使用")
        else:
            # 通常タスクの場合：今日の日付で処理
            target_date = datetime.now(jst)
            print(f"[DEBUG] 通常タスク処理: 今日の日付 {target_date.strftime('%Y-%m-%d')} を使用")

        # スケジュール提案から時刻を抽出してカレンダーに追加
        success_count = calendar_service.add_events_to_calendar(user_id, proposal)

        if success_count == 0:
            # パースに失敗した場合は、固定時刻で追加
            print("[DEBUG] スケジュール提案のパースに失敗、固定時刻で追加")
            for task in selected_tasks:
                start_time = target_date.replace(hour=14, minute=0, second=0, microsecond=0)
                if calendar_service.add_event_to_calendar(
                    user_id,
                    task.name,
                    start_time,
                    task.duration_minutes,
                ):
                    success_count += 1

        reply_text = f"✅ スケジュールを承認しました！\n\n{success_count}個のタスクをカレンダーに追加しました。\n\n"

        # スケジュール提案に「来週のスケジュール提案」が含まれているかチェック
        is_future_schedule_proposal = "来週のスケジュール提案" in proposal

        # スケジュール表示処理
        reply_text += _format_schedule_display(
            calendar_service,
            user_id,
            selected_future_tasks,
            is_future_schedule_proposal,
            target_date,
            jst
        )

        # データベースからセッションデータを削除
        if db:
            db.delete_user_session(user_id, 'schedule_proposal')
            db.delete_user_session(user_id, 'selected_tasks')

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
        print(f"[ERROR] 承認処理（はいコマンド）: {e}")
        import traceback
        traceback.print_exc()
        reply_text = f"⚠️ スケジュール承認中にエラーが発生しました: {e}"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        return False


def _format_schedule_display(
    calendar_service,
    user_id: str,
    selected_future_tasks: list,
    is_future_schedule_proposal: bool,
    target_date,
    jst
) -> str:
    """スケジュール表示のフォーマット"""
    reply_text = ""

    # 未来タスクの場合は来週のスケジュール、通常タスクの場合は今日のスケジュールを表示
    if selected_future_tasks or is_future_schedule_proposal:
        # 来週のスケジュール提案の場合：来週の最初の日（次の週の月曜日）を計算
        today = datetime.now(jst)
        # 来週の月曜日を計算（月曜日は0）
        days_until_next_monday = (0 - today.weekday() + 7) % 7
        if days_until_next_monday == 0:
            days_until_next_monday = 7  # 今日が月曜日の場合は1週間後
        next_week_monday = today + timedelta(days=days_until_next_monday)
        schedule_date = next_week_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        week_schedule = calendar_service.get_week_schedule(user_id, schedule_date)
        date_label = f"📅 来週のスケジュール ({schedule_date.strftime('%m/%d')}〜):"
        print(f"[DEBUG] 来週のスケジュール取得結果: {len(week_schedule)}日分, 開始日={schedule_date.strftime('%Y-%m-%d')}")

        # 来週のスケジュール提案の場合：来週全体のスケジュールを表示
        if week_schedule:
            reply_text += date_label + "\n"
            reply_text += "━━━━━━━━━━━━━━\n"

            for day_data in week_schedule:
                day_date = day_data["date"]
                day_events = day_data["events"]

                # 日付ヘッダーを表示
                day_label = day_date.strftime("%m/%d")
                day_of_week = ["月", "火", "水", "木", "金", "土", "日"][day_date.weekday()]
                reply_text += f"📅 {day_label}({day_of_week})\n"

                if day_events:
                    for event in day_events:
                        try:
                            start_time = datetime.fromisoformat(event["start"]).strftime("%H:%M")
                            end_time = datetime.fromisoformat(event["end"]).strftime("%H:%M")
                        except Exception:
                            start_time = event["start"]
                            end_time = event["end"]
                        summary = event["title"]
                        # 📝と[added_by_bot]を削除
                        clean_summary = summary.replace("📝 ", "").replace(" [added_by_bot]", "")
                        reply_text += f"🕐 {start_time}〜{end_time} 📝 {clean_summary}\n"
                else:
                    reply_text += " 予定なし\n"

                reply_text += "━━━━━━━━━━━━━━\n"
        else:
            reply_text += f" 来週のスケジュールはありません。"
    else:
        # 通常タスクの場合：今日のスケジュールを表示
        schedule_date = target_date
        schedule_list = calendar_service.get_today_schedule(user_id)
        date_label = "📅 今日のスケジュール："
        print(f"[DEBUG] 今日のスケジュール取得結果: {len(schedule_list)}件")

        if schedule_list:
            reply_text += date_label + "\n"
            reply_text += "━━━━━━━━━━━━━━\n"

            for i, event in enumerate(schedule_list):
                try:
                    start_time = datetime.fromisoformat(event["start"]).strftime("%H:%M")
                    end_time = datetime.fromisoformat(event["end"]).strftime("%H:%M")
                except Exception:
                    start_time = event["start"]
                    end_time = event["end"]
                summary = event["title"]
                # 📝と[added_by_bot]を削除
                clean_summary = summary.replace("📝 ", "").replace(" [added_by_bot]", "")
                reply_text += f"🕐 {start_time}〜{end_time}\n"
                reply_text += f"📝 {clean_summary}\n"
                reply_text += "━━━━━━━━━━━━━━\n"
        else:
            reply_text += " 今日のスケジュールはありません。"

    return reply_text


def _handle_task_deletion(
    line_bot_api,
    reply_token: str,
    user_id: str,
    task_service,
    get_simple_flex_menu,
    db=None
) -> bool:
    """タスク削除の承認処理"""
    selected_tasks_data = db.get_user_session(user_id, 'selected_tasks') if db else None

    if not selected_tasks_data:
        reply_text = "⚠️ 先にタスクを選択してください。"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        return False

    try:
        # 選択されたタスクを読み込み
        try:
            task_ids = json.loads(selected_tasks_data)
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON parsing failed in task deletion: {e}")
            reply_text = "⚠️ タスクデータの読み込みに失敗しました。もう一度タスクを選択してください。"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
            return False

        # モードを判定（削除モードは通常タスクのみなので、通常はscheduleまたはcomplete）
        # ただし、将来的に未来タスクの削除もサポートする可能性を考慮
        current_mode = "complete"  # デフォルト（削除モード）
        flag_data = load_flag_data(user_id, "task_select")
        if flag_data:
            current_mode = flag_data.get("mode", "complete")
            print(f"[DEBUG] 削除処理モード判定: mode={current_mode}")

        # 現状、削除は通常タスクのみなのでget_user_tasksを使用
        # 将来的に未来タスクの削除もサポートする場合は条件分岐を追加
        all_tasks = task_service.get_user_tasks(user_id)
        selected_tasks = [t for t in all_tasks if t.task_id in task_ids]

        if not selected_tasks:
            reply_text = "⚠️ 選択されたタスクが見つかりませんでした。"
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    replyToken=reply_token,
                    messages=[TextMessage(text=reply_text)],
                )
            )
            return False

        # 選択されたタスクを削除
        deleted_tasks = []
        for task in selected_tasks:
            try:
                task_service.delete_task(task.task_id)
                deleted_tasks.append(task.name)
                print(f"[DEBUG] タスク削除完了: {task.name}")
            except Exception as e:
                print(f"[DEBUG] タスク削除エラー: {task.name}, {e}")

        # 削除結果を報告
        if deleted_tasks:
            reply_text = f"✅ 選択されたタスクを削除しました！\n\n"
            for i, task_name in enumerate(deleted_tasks, 1):
                reply_text += f"{i}. {task_name}\n"
            reply_text += "\nお疲れさまでした！"
        else:
            reply_text = "⚠️ タスクの削除に失敗しました。"

        # データベースからセッションデータを削除
        if db:
            db.delete_user_session(user_id, 'selected_tasks')

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
        print(f"[DEBUG] はいコマンド削除処理エラー: {e}")
        import traceback
        traceback.print_exc()
        reply_text = f"⚠️ タスク削除中にエラーが発生しました: {e}"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        return False


def handle_modification(
    line_bot_api,
    reply_token: str,
    user_id: str,
    task_service,
    db=None
) -> bool:
    """
    「修正する」コマンドの処理
    スケジュール提案を修正するためにタスク選択画面に戻る

    Args:
        line_bot_api: LINE Messaging APIクライアント
        reply_token: リプライトークン
        user_id: ユーザーID
        task_service: タスクサービス
        db: データベースインスタンス

    Returns:
        bool: 処理成功時True
    """
    from .helpers import create_flag_file

    try:
        # 現在のモードを判定
        current_mode = "schedule"  # デフォルト

        # フラグデータベースから現在のモードを読み取り
        flag_data = load_flag_data(user_id, "task_select")
        if flag_data:
            current_mode = flag_data.get("mode", "schedule")
            print(f"[修正処理] フラグデータを読み取り: mode={current_mode}")
        else:
            print(f"[修正処理] フラグデータが見つかりません、デフォルトモード使用")

        # データベースから未来タスク選択モードをチェック
        if current_mode == "schedule" and db:  # デフォルトの場合は追加確認
            future_selection_data = db.get_user_session(user_id, 'future_task_selection')
            if future_selection_data:
                # 未来タスク選択モードデータの内容を確認
                try:
                    future_mode_data = json.loads(future_selection_data)
                    if future_mode_data.get("mode") == "future_schedule":
                        print(f"[修正処理] 未来タスク選択モードデータ内容確認: {future_mode_data}")
                        current_mode = "future_schedule"
                    else:
                        print(f"[修正処理] 未来タスク選択モードデータ存在するが内容が異なる: {future_mode_data}")
                except Exception as e:
                    print(f"[修正処理] 未来タスク選択モードデータ読み取りエラー: {e}")
                    # データが存在する場合は未来タスクモードと判定
                    current_mode = "future_schedule"

        # データベースからスケジュール提案の内容も確認
        if db:
            schedule_proposal = db.get_user_session(user_id, 'schedule_proposal')
            if schedule_proposal:
                try:
                    if "来週のスケジュール提案" in schedule_proposal:
                        print(f"[修正処理] 来週のスケジュール提案を検出")
                        current_mode = "future_schedule"
                    elif "本日のスケジュール提案" in schedule_proposal:
                        print(f"[修正処理] 本日のスケジュール提案を検出")
                        current_mode = "schedule"
                except Exception as e:
                    print(f"[修正処理] スケジュール提案データ読み取りエラー: {e}")

        print(f"[修正処理] 現在のモード: {current_mode}")

        if current_mode == "future_schedule":
            # 未来タスク選択モードの場合：来週のタスク選択画面に戻る
            future_tasks = task_service.get_user_future_tasks(user_id)
            reply_text = task_service.format_future_task_list(future_tasks, show_select_guide=True)
            print(f"[修正処理] 未来タスク選択画面に戻る")
        else:
            # 通常タスク選択モードの場合：今日のタスク選択画面に戻る
            all_tasks = task_service.get_user_tasks(user_id)
            morning_guide = "今日やるタスクを選んでください！\n例：１、３、５"
            reply_text = task_service.format_task_list(all_tasks, show_select_guide=True, guide_text=morning_guide)
            print(f"[修正処理] 今日のタスク選択画面に戻る")

            # 今日のタスク選択モードに戻るため、フラグを更新
            create_flag_file(user_id, "task_select", {"mode": "schedule"})
            print(f"[修正処理] 今日のタスク選択モードフラグ更新: user_id={user_id}")

        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        return True

    except Exception as e:
        print(f"[ERROR] 修正処理: {e}")
        import traceback
        traceback.print_exc()
        reply_text = f"⚠️ 修正処理中にエラーが発生しました: {e}"
        line_bot_api.reply_message(
            ReplyMessageRequest(
                replyToken=reply_token,
                messages=[TextMessage(text=reply_text)],
            )
        )
        return False
