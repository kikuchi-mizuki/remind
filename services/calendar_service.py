import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import json
import re

class CalendarService:
    """Googleカレンダー操作サービスクラス"""

    def __init__(self):
        self.SCOPES = ['https://www.googleapis.com/auth/calendar']
        self.service = None
        self.credentials = None
        # データベースインスタンスを初期化
        from models.database import init_db
        self.db = init_db()

    def authenticate_user(self, user_id: str) -> bool:
        """ユーザーの認証を行う（DB保存方式）"""
        try:
            token_json = self.db.get_token(user_id)
            if not token_json:
                print(f"Token not found in DB for user: {user_id}")
                return False
            
            import json
            creds = Credentials.from_authorized_user_info(json.loads(token_json), self.SCOPES)
            
            # refresh_tokenが無い場合は認証失敗
            if not creds.refresh_token:
                print(f"No refresh_token found for user: {user_id}")
                return False
            
            # トークンが期限切れの場合は更新
            if creds.expired:
                try:
                    creds.refresh(Request())
                    # 更新されたトークンをDBに保存
                    self.db.save_token(user_id, creds.to_json())
                except Exception as e:
                    print(f"Token refresh failed: {e}")
                    return False
            
            self.credentials = creds
            self.service = build('calendar', 'v3', credentials=creds)
            return True
            
        except Exception as e:
            print(f"Authentication error: {e}")
            return False

    def get_free_busy_times(self, user_id: str, date: datetime) -> List[Dict]:
        """指定日の空き時間を取得"""
        if not self.authenticate_user(user_id):
            return []
        
        try:
            # 現在時刻を取得（JST）
            import pytz
            jst = pytz.timezone('Asia/Tokyo')
            now = datetime.now(jst)
            
            # dateがタイムゾーン情報を持っていない場合はJSTを設定
            if date.tzinfo is None:
                date = jst.localize(date)
            elif date.tzinfo != jst:
                date = date.astimezone(jst)
            
            # 指定日の開始と終了時間（現在時刻以降に限定）
            if date.date() == now.date():
                # 今日の場合は現在時刻以降
                start_time = now.replace(second=0, microsecond=0)
                # 現在時刻が8時前の場合は8時から開始
                if start_time.hour < 8:
                    start_time = start_time.replace(hour=8, minute=0)
            else:
                # 今日以外の場合は8時から開始
                start_time = date.replace(hour=8, minute=0, second=0, microsecond=0)
            
            end_time = date.replace(hour=22, minute=0, second=0, microsecond=0)
            
            print(f"[get_free_busy_times] 日付={date.date()}, 開始時刻={start_time}, 終了時刻={end_time}")
            
            # 既存の予定を取得
            time_min_str = start_time.isoformat()
            time_max_str = end_time.isoformat()
            print(f"[get_free_busy_times] カレンダーAPI呼び出し: timeMin={time_min_str}, timeMax={time_max_str}")
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=time_min_str,
                timeMax=time_max_str,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            print(f"[get_free_busy_times] 取得したイベント数: {len(events)}")
            
            # 空き時間を計算
            free_times = []
            current_time = start_time
            
            for event in events:
                start_raw = event['start'].get('dateTime', event['start'].get('date'))
                end_raw = event['end'].get('dateTime', event['end'].get('date'))

                # 日時の正規化（タイムゾーン付き・日付のみの両方に対応）
                def normalize_event_time(value: str, is_start: bool) -> datetime:
                    if 'T' in value:
                        dt = datetime.fromisoformat(value)
                        if dt.tzinfo is None:
                            dt = jst.localize(dt)
                        else:
                            dt = dt.astimezone(jst)
                        return dt
                    # 終日イベントの場合（date形式）
                    date_only = datetime.fromisoformat(value)
                    date_only = date_only.replace(hour=0, minute=0, second=0, microsecond=0)
                    date_only = jst.localize(date_only)
                    if not is_start:
                        date_only += timedelta(days=1)
                    return date_only

                event_start = normalize_event_time(start_raw, True)
                event_end = normalize_event_time(end_raw, False)
                
                # 現在時刻とイベント開始時刻の間に空き時間がある場合
                if current_time < event_start:
                    free_duration = (event_start - current_time).total_seconds() / 60
                    if free_duration >= 15:  # 15分以上の空き時間のみ
                        free_times.append({
                            'start': current_time,
                            'end': event_start,
                            'duration_minutes': int(free_duration)
                        })
                
                current_time = event_end
            
            # 最後のイベントから終了時刻までの空き時間
            if current_time < end_time:
                free_duration = (end_time - current_time).total_seconds() / 60
                if free_duration >= 15:
                    free_times.append({
                        'start': current_time,
                        'end': end_time,
                        'duration_minutes': int(free_duration)
                    })
            
            print(f"[get_free_busy_times] 空き時間数: {len(free_times)}")
            return free_times
            
        except HttpError as error:
            print(f'Calendar API error: {error}')
            return []

    def get_week_free_busy_times(self, user_id: str, start_date: datetime) -> List[Dict]:
        """指定週の空き時間を取得（7日間）"""
        if not self.authenticate_user(user_id):
            return []
        
        try:
            # start_dateがタイムゾーン情報を持っていない場合はJSTを設定
            import pytz
            jst = pytz.timezone('Asia/Tokyo')
            if start_date.tzinfo is None:
                start_date = jst.localize(start_date)
            elif start_date.tzinfo != jst:
                start_date = start_date.astimezone(jst)
            
            print(f"[get_week_free_busy_times] 開始日: {start_date.strftime('%Y-%m-%d %A')}")
            
            # 週全体の空き時間を取得
            free_times = []
            for i in range(7):  # 7日間
                target_date = start_date + timedelta(days=i)
                print(f"[get_week_free_busy_times] 日{i+1}: {target_date.strftime('%Y-%m-%d %A')}")
                day_free_times = self.get_free_busy_times(user_id, target_date)
                # 各空き時間に日付情報を追加
                for ft in day_free_times:
                    ft['date'] = target_date.date()
                free_times.extend(day_free_times)
            
            print(f"[get_week_free_busy_times] 合計空き時間数: {len(free_times)}")
            return free_times
            
        except Exception as e:
            print(f'Error getting week free busy times: {e}')
            return []

    def add_event_to_calendar(self, user_id: str, task_name: str, start_time: datetime, 
                            duration_minutes: int, description: str = "") -> bool:
        """カレンダーにイベントを追加"""
        if not self.authenticate_user(user_id):
            print(f"[add_event_to_calendar] 認証失敗: user_id={user_id}")
            return False
        try:
            # タスク名から⭐️を除去し、⭐に統一
            import re
            clean_task_name = task_name
            # 複数の⭐️を⭐に統一
            while '⭐️⭐️' in clean_task_name:
                clean_task_name = clean_task_name.replace('⭐️⭐️', '⭐')
            clean_task_name = clean_task_name.replace('⭐️', '⭐')
            
            end_time = start_time + timedelta(minutes=duration_minutes)
            event = {
                'summary': f'📝 {clean_task_name}',
                'description': description,
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'Asia/Tokyo',
                },
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 5},
                    ],
                },
            }
            print(f"[add_event_to_calendar] 追加内容: user_id={user_id}, task_name={task_name}, start_time={start_time}, duration={duration_minutes}, event={event}")
            event_result = self.service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            print(f'[add_event_to_calendar] Event created: {event_result.get("htmlLink")}, id={event_result.get("id")}, summary={event_result.get("summary")}, start={event_result.get("start")}, end={event_result.get("end")}')
            return True
        except HttpError as error:
            print(f'[add_event_to_calendar] Calendar API error: {error}')
            return False
        except Exception as e:
            print(f'[add_event_to_calendar] 予期せぬエラー: {e}')
            import traceback
            traceback.print_exc()
            return False

    def add_events_to_calendar(self, user_id: str, schedule_proposal: str) -> int:
        """スケジュール提案をカレンダーに反映（日付パース強化・2行セット対応・未来タスク対応）"""
        try:
            import re
            from datetime import datetime, timedelta
            import pytz
            lines = [line.strip() for line in schedule_proposal.split('\n') if line.strip()]
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst).replace(hour=0, minute=0, second=0, microsecond=0)
            success_count = 0
            unparsable_lines = []
            i = 0
            
            # 未来タスクかどうかを判定（来週のスケジュール提案かチェック）
            is_future_task = any('来週のスケジュール提案' in line for line in lines)

            # base_dateの設定（来週のスケジュール提案の場合は来週の月曜日を基準にする）
            if is_future_task:
                # 来週の月曜日を計算
                days_until_next_monday = (0 - today.weekday() + 7) % 7
                if days_until_next_monday == 0:
                    days_until_next_monday = 7  # 今日が月曜日の場合は1週間後
                base_date = today + timedelta(days=days_until_next_monday)
            else:
                base_date = today

            target_date = base_date  # 初期値を設定

            while i < len(lines):
                line = lines[i]

                # 日付行を検出（例: 12/02(月)）
                date_match = re.match(r'(\d{1,2})/(\d{1,2})\([月火水木金土日]\)', line)
                if date_match:
                    # 日付行が検出された場合、target_dateを更新
                    month = int(date_match.group(1))
                    day = int(date_match.group(2))
                    current_year = today.year

                    # 年を考慮した日付計算
                    try:
                        target_date = jst.localize(datetime(current_year, month, day))
                        # もし計算した日付が過去の場合は来年にする
                        if target_date < today:
                            target_date = jst.localize(datetime(current_year + 1, month, day))
                    except ValueError:
                        # 無効な日付の場合はbase_dateを使用
                        target_date = base_date

                    print(f"[DEBUG] 日付行検出: {line}, target_date={target_date.strftime('%Y-%m-%d')}")
                    i += 1
                    continue
                
                                    # 🕒時刻行＋📝タスク行の2行セットを1つの予定として扱う
                if line.startswith('🕒') and i+1 < len(lines) and lines[i+1].startswith('📝'):
                    # 🕒 08:00〜08:30
                    m_time = re.match(r'🕒\s*(\d{1,2}):(\d{2})[〜~\-ー―‐–—−﹣－:：](\d{1,2}):(\d{2})', line)
                    # 📝 資料作成（30分）
                    m_task = re.match(r'📝\s*(.+)[（(](\d+)分[)）]', lines[i+1])
                    if m_time and m_task:
                        start_hour = int(m_time.group(1))
                        start_min = int(m_time.group(2))
                        end_hour = int(m_time.group(3))
                        end_min = int(m_time.group(4))
                        task_name = m_task.group(1).strip()
                        duration = int(m_task.group(2))
                        start_time = target_date.replace(hour=start_hour, minute=start_min)
                        if self.add_event_to_calendar(user_id, task_name, start_time, duration):
                            success_count += 1
                        i += 2
                        continue
                
                # スケジュール提案形式の特別処理（🕒行の後に📝行が来る場合）
                if line.startswith('🕒'):
                    # 次の行が📝で始まるかチェック
                    next_line_idx = i + 1
                    while next_line_idx < len(lines) and not lines[next_line_idx].startswith('📝'):
                        next_line_idx += 1
                    
                    if next_line_idx < len(lines) and lines[next_line_idx].startswith('📝'):
                        # 🕒 08:00〜08:30
                        m_time = re.match(r'🕒\s*(\d{1,2}):(\d{2})[〜~\-ー―‐–—−﹣－:：](\d{1,2}):(\d{2})', line)
                        # 📝 資料作成（30分）
                        m_task = re.match(r'📝\s*(.+)[（(](\d+)分[)）]', lines[next_line_idx])
                        if m_time and m_task:
                            start_hour = int(m_time.group(1))
                            start_min = int(m_time.group(2))
                            end_hour = int(m_time.group(3))
                            end_min = int(m_time.group(4))
                            task_name = m_task.group(1).strip()
                            duration = int(m_task.group(2))
                            start_time = target_date.replace(hour=start_hour, minute=start_min)
                            if self.add_event_to_calendar(user_id, task_name, start_time, duration):
                                success_count += 1
                            i = next_line_idx + 1
                            continue
                
                # 未来タスク用の1行パターン（日付＋時刻＋タスク）
                # 例: 7/22(月) 08:00〜10:00
                date_time_match = re.match(r'(\d{1,2})/(\d{1,2})\([月火水木金土日]\)\s*(\d{1,2}):(\d{2})[〜~\-ー―‐–—−﹣－:：](\d{1,2}):(\d{2})', line)
                if date_time_match and i+1 < len(lines) and lines[i+1].startswith('📝'):
                    # 日付と時刻を取得
                    month = int(date_time_match.group(1))
                    day = int(date_time_match.group(2))
                    start_hour = int(date_time_match.group(3))
                    start_min = int(date_time_match.group(4))
                    end_hour = int(date_time_match.group(5))
                    end_min = int(date_time_match.group(6))
                    
                    # 来週の日付を計算
                    next_week_date = today + timedelta(days=7)
                    target_date = next_week_date.replace(month=month, day=day)
                    
                    # タスク名を取得
                    m_task = re.match(r'📝\s*(.+)[（(](\d+)分[)）]', lines[i+1])
                    if m_task:
                        task_name = m_task.group(1).strip()
                        duration = int(m_task.group(2))
                        start_time = target_date.replace(hour=start_hour, minute=start_min)
                        if self.add_event_to_calendar(user_id, task_name, start_time, duration):
                            success_count += 1
                        i += 2
                        continue
                # 既存の1行パターンもサポート
                # 1. (所要時間明示あり) 柔軟な正規表現
                m = re.match(r"[-・*\s]*\*?\*?\s*(\d{1,2})[:：]?(\d{2})\s*[〜~\-ー―‐–—−﹣－:：]\s*(\d{1,2})[:：]?(\d{2})\*?\*?\s*([\u3000 \t\-–—―‐]*)?(.+?)\s*\((\d+)分\)", line)
                if m:
                    start_hour = int(m.group(1))
                    start_min = int(m.group(2))
                    end_hour = int(m.group(3))
                    end_min = int(m.group(4))
                    task_name = m.group(6).strip()
                    duration = int(m.group(7))
                    start_time = target_date.replace(hour=start_hour, minute=start_min)
                    if self.add_event_to_calendar(user_id, task_name, start_time, duration):
                        success_count += 1
                    i += 1
                    continue
                # 2. (所要時間明示なし) 例: - **08:00〜08:20** 書類作成 など
                m2 = re.match(r"[-・*\s]*\*?\*?\s*(\d{1,2})[:：]?(\d{2})\s*[〜~\-ー―‐–—−﹣－:：]\s*(\d{1,2})[:：]?(\d{2})\*?\*?\s*([\u3000 \t\-–—―‐]*)?(.+)", line)
                if m2:
                    try:
                        start_hour = int(m2.group(1))
                        start_min = int(m2.group(2))
                        end_hour = int(m2.group(3))
                        end_min = int(m2.group(4))
                        task_name = m2.group(6).strip()
                        start = datetime(2000,1,1,start_hour,start_min)
                        end = datetime(2000,1,1,end_hour,end_min)
                        if end <= start:
                            end += timedelta(days=1)
                        duration = int((end-start).total_seconds()//60)
                        start_time = target_date.replace(hour=start_hour, minute=start_min)
                        if self.add_event_to_calendar(user_id, task_name, start_time, duration):
                            success_count += 1
                    except Exception as e:
                        print(f"[add_events_to_calendar] パース失敗: {line} err={e}")
                    i += 1
                    continue
                # パースできなかった行を記録（ただし、ヘッダーや区切り線は除外）
                if line.strip() and not any(skip in line for skip in ['🗓️【', '━━━', '✅理由', 'このスケジュールで']):
                    print(f"[add_events_to_calendar] パースできなかった行: {line}")
                    unparsable_lines.append(line)
                i += 1
            return success_count
        except Exception as e:
            print(f"Error adding events to calendar: {e}")
            return 0

    def get_today_schedule(self, user_id: str) -> List[Dict]:
        """今日のスケジュールを取得（JST厳密化）"""
        if not self.authenticate_user(user_id):
            return []
        try:
            import pytz
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst).replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=today.isoformat(),
                timeMax=tomorrow.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            if events is None:
                events = []
            schedule = []
            for event in events:
                if not event or not event.get('start') or not event.get('end'):
                    continue
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                schedule.append({
                    'title': event.get('summary', 'タイトルなし'),
                    'start': start,
                    'end': end,
                    'description': event.get('description', '')
                })
            return schedule
        except Exception as error:
            print(f'Calendar API error: {error}')
            return []

    def get_day_schedule(self, user_id: str, target_date: datetime) -> List[Dict]:
        """指定日のスケジュールを取得"""
        if not self.authenticate_user(user_id):
            return []
        try:
            # 指定日の開始と終了時間
            start_time = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=1)
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time.isoformat(),
                timeMax=end_time.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            if events is None:
                events = []
            schedule = []
            for event in events:
                if not event or not event.get('start') or not event.get('end'):
                    continue
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                schedule.append({
                    'title': event.get('summary', 'タイトルなし'),
                    'start': start,
                    'end': end,
                    'description': event.get('description', '')
                })
            return schedule
        except Exception as error:
            print(f'Calendar API error: {error}')
            return []

    def get_week_schedule(self, user_id: str, start_date: datetime) -> List[Dict]:
        """指定週のスケジュールを取得（7日間）"""
        if not self.authenticate_user(user_id):
            return []
        try:
            # 週の開始と終了時間
            week_start = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            week_end = week_start + timedelta(days=7)
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=week_start.isoformat(),
                timeMax=week_end.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            
            # 日付ごとにグループ化
            schedule_by_day = {}
            for i in range(7):
                day_date = week_start + timedelta(days=i)
                schedule_by_day[day_date.date()] = []
            
            # イベントを日付ごとに分類
            for event in events:
                if not event or not event.get('start') or not event.get('end'):
                    continue
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                
                # 日付を抽出
                if 'T' in start:  # dateTime形式
                    event_date = datetime.fromisoformat(start.replace('Z', '+00:00')).date()
                else:  # date形式
                    event_date = datetime.fromisoformat(start).date()
                
                if event_date in schedule_by_day:
                    schedule_by_day[event_date].append({
                        'title': event.get('summary', 'タイトルなし'),
                        'start': start,
                        'end': end,
                        'description': event.get('description', '')
                    })
            
            # 結果を日付順に整理
            result = []
            for i in range(7):
                day_date = week_start + timedelta(days=i)
                day_events = schedule_by_day[day_date.date()]
                result.append({
                    'date': day_date,
                    'events': day_events
                })
            
            return result
        except Exception as error:
            print(f'Calendar API error: {error}')
            return []

    def check_time_conflict(self, user_id: str, start_time: datetime, 
                          duration_minutes: int) -> bool:
        """時間の重複をチェック"""
        if not self.authenticate_user(user_id):
            return True  # 認証できない場合は重複とみなす
        
        try:
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time.isoformat(),
                timeMax=end_time.isoformat(),
                singleEvents=True
            ).execute()
            
            events = events_result.get('items', [])
            return len(events) > 0
            
        except HttpError as error:
            print(f'Calendar API error: {error}')
            return True

    def suggest_optimal_time(self, user_id: str, duration_minutes: int, 
                           task_type: str = "general") -> Optional[datetime]:
        """最適な時間を提案"""
        import pytz
        jst = pytz.timezone('Asia/Tokyo')
        today = datetime.now(jst)
        
        # 今日の空き時間を取得
        free_times = self.get_free_busy_times(user_id, today)
        
        if not free_times:
            print(f"[DEBUG] 空き時間が見つかりません")
            return None
        
        print(f"[DEBUG] 取得した空き時間: {len(free_times)}個")
        for ft in free_times:
            print(f"  - {ft['start'].strftime('%H:%M')}〜{ft['end'].strftime('%H:%M')} ({ft['duration_minutes']}分)")
        
        # 緊急タスクの場合は早い時間を優先
        if task_type == "urgent":
            # 朝8時から夕方6時までの時間帯を優先
            morning_times = [t for t in free_times if 8 <= t['start'].hour < 18]
            if morning_times:
                free_times = morning_times
        elif task_type in ["important", "focus"]:
            # 重要・集中系は午前を優先
            morning_times = [t for t in free_times if t['start'].hour < 12]
            if morning_times:
                free_times = morning_times
        
        # 十分な時間がある空き時間をフィルタリング
        suitable_times = [t for t in free_times if t['duration_minutes'] >= duration_minutes]
        
        if not suitable_times:
            print(f"[DEBUG] 十分な時間の空き時間が見つかりません (必要: {duration_minutes}分)")
            return None
        
        # 最も早い時間を選択
        optimal_time = min(suitable_times, key=lambda x: x['start'])['start']
        print(f"[DEBUG] 最適時刻を選択: {optimal_time.strftime('%H:%M')}")
        return optimal_time

    def auto_schedule_tasks(self, user_id: str, tasks: List[Dict]) -> List[Dict]:
        """タスクを空き時間に自動配置"""
        if not self.authenticate_user(user_id):
            return []
        
        try:
            import pytz
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst)
            
            # 今日の空き時間を取得
            free_times = self.get_free_busy_times(user_id, today)
            if not free_times:
                return []
            
            # タスクを優先度順にソート
            priority_order = {
                "urgent_important": 1,
                "urgent_not_important": 2,
                "not_urgent_important": 3,
                "normal": 4
            }
            
            sorted_tasks = sorted(tasks, key=lambda x: priority_order.get(x.get('priority', 'normal'), 4))
            
            scheduled_tasks = []
            used_times = []
            
            for task in sorted_tasks:
                task_name = task['name']
                duration = task['duration_minutes']
                priority = task.get('priority', 'normal')
                
                # 最適な空き時間を探す
                best_time = None
                best_time_slot = None
                
                for time_slot in free_times:
                    # 既に使用された時間との重複をチェック
                    is_conflict = False
                    for used_time in used_times:
                        if (time_slot['start'] < used_time['end'] and 
                            time_slot['end'] > used_time['start']):
                            is_conflict = True
                            break
                    
                    if is_conflict:
                        continue
                    
                    # 十分な時間があるかチェック
                    if time_slot['duration_minutes'] >= duration:
                        # 優先度に応じた時間帯の好み
                        if priority == "urgent_important":
                            # 緊急かつ重要は早い時間を優先
                            if best_time is None or time_slot['start'] < best_time['start']:
                                best_time = time_slot
                                best_time_slot = time_slot
                        elif priority == "not_urgent_important":
                            # 重要だが緊急ではないは午前中を優先
                            if time_slot['start'].hour < 12:
                                if best_time is None or time_slot['start'] < best_time['start']:
                                    best_time = time_slot
                                    best_time_slot = time_slot
                        else:
                            # その他は利用可能な時間を選択
                            if best_time is None or time_slot['start'] < best_time['start']:
                                best_time = time_slot
                                best_time_slot = time_slot
                
                if best_time_slot:
                    # タスクをスケジュール
                    start_time = best_time_slot['start']
                    end_time = start_time + timedelta(minutes=duration)
                    
                    scheduled_task = {
                        'name': task_name,
                        'start_time': start_time,
                        'end_time': end_time,
                        'duration_minutes': duration,
                        'priority': priority,
                        'date': start_time.strftime('%Y-%m-%d'),
                        'time_str': f"{start_time.strftime('%H:%M')}〜{end_time.strftime('%H:%M')}"
                    }
                    
                    scheduled_tasks.append(scheduled_task)
                    
                    # 使用された時間を記録
                    used_times.append({
                        'start': start_time,
                        'end': end_time
                    })
                    
                    # 空き時間リストを更新
                    remaining_duration = best_time_slot['duration_minutes'] - duration
                    if remaining_duration >= 15:  # 15分以上の残り時間があれば
                        new_free_time = {
                            'start': end_time,
                            'end': best_time_slot['end'],
                            'duration_minutes': remaining_duration
                        }
                        free_times.append(new_free_time)
                    
                    # 使用された時間スロットを削除
                    free_times.remove(best_time_slot)
            
            return scheduled_tasks
            
        except Exception as e:
            print(f"Auto schedule error: {e}")
            return []

    def add_scheduled_tasks_to_calendar(self, user_id: str, scheduled_tasks: List[Dict]) -> bool:
        """スケジュールされたタスクをカレンダーに追加"""
        if not self.authenticate_user(user_id):
            return False
        
        try:
            success_count = 0
            for task in scheduled_tasks:
                success = self.add_event_to_calendar(
                    user_id,
                    task['name'],
                    task['start_time'],
                    task['duration_minutes'],
                    f"自動スケジュール: {task['name']}"
                )
                if success:
                    success_count += 1
            
            return success_count > 0
            
        except Exception as e:
            print(f"Add scheduled tasks error: {e}")
            return False

    def auto_schedule_tasks_next_week(self, user_id: str, tasks: List[Dict], next_monday: datetime) -> List[Dict]:
        """来週の空き時間にタスクを自動配置"""
        if not self.authenticate_user(user_id):
            return []
        
        try:
            # 来週の空き時間を取得（月曜日から金曜日）
            free_times = []
            for i in range(5):  # 月〜金の5日間
                target_date = next_monday + timedelta(days=i)
                day_free_times = self.get_free_busy_times(user_id, target_date)
                for ft in day_free_times:
                    ft['date'] = target_date
                free_times.extend(day_free_times)
            
            if not free_times:
                return []
            
            # タスクを優先度順にソート
            priority_order = {
                "urgent_important": 1,
                "urgent_not_important": 2,
                "not_urgent_important": 3,
                "normal": 4
            }
            
            sorted_tasks = sorted(tasks, key=lambda x: priority_order.get(x.get('priority', 'normal'), 4))
            
            scheduled_tasks = []
            used_times = []
            
            for task in sorted_tasks:
                task_name = task['name']
                duration = task['duration_minutes']
                priority = task.get('priority', 'normal')
                
                # 最適な空き時間を探す
                best_time = None
                best_time_slot = None
                
                for time_slot in free_times:
                    # 既に使用された時間との重複をチェック
                    is_conflict = False
                    for used_time in used_times:
                        if (time_slot['start'] < used_time['end'] and 
                            time_slot['end'] > used_time['start']):
                            is_conflict = True
                            break
                    
                    if is_conflict:
                        continue
                    
                    # 十分な時間があるかチェック
                    if time_slot['duration_minutes'] >= duration:
                        # 優先度に応じた時間帯の好み
                        if priority == "urgent_important":
                            # 緊急かつ重要は早い時間を優先
                            if best_time is None or time_slot['start'] < best_time['start']:
                                best_time = time_slot
                                best_time_slot = time_slot
                        elif priority == "not_urgent_important":
                            # 重要だが緊急ではないは午前中を優先
                            if time_slot['start'].hour < 12:
                                if best_time is None or time_slot['start'] < best_time['start']:
                                    best_time = time_slot
                                    best_time_slot = time_slot
                        else:
                            # その他は利用可能な時間を選択
                            if best_time is None or time_slot['start'] < best_time['start']:
                                best_time = time_slot
                                best_time_slot = time_slot
                
                if best_time_slot:
                    # タスクをスケジュール
                    start_time = best_time_slot['start']
                    end_time = start_time + timedelta(minutes=duration)
                    
                    scheduled_task = {
                        'name': task_name,
                        'start_time': start_time,
                        'end_time': end_time,
                        'duration_minutes': duration,
                        'priority': priority,
                        'date': start_time.strftime('%Y-%m-%d'),
                        'date_str': start_time.strftime('%m/%d(%a)'),
                        'time_str': f"{start_time.strftime('%H:%M')}〜{end_time.strftime('%H:%M')}"
                    }
                    
                    scheduled_tasks.append(scheduled_task)
                    
                    # 使用された時間を記録
                    used_times.append({
                        'start': start_time,
                        'end': end_time
                    })
                    
                    # 空き時間リストを更新
                    remaining_duration = best_time_slot['duration_minutes'] - duration
                    if remaining_duration >= 15:  # 15分以上の残り時間があれば
                        new_free_time = {
                            'start': end_time,
                            'end': best_time_slot['end'],
                            'duration_minutes': remaining_duration
                        }
                        free_times.append(new_free_time)
                    
                    # 使用された時間スロットを削除
                    free_times.remove(best_time_slot)
            
            return scheduled_tasks
            
        except Exception as e:
            print(f"Auto schedule next week error: {e}")
            return []

    def get_authorization_url(self, user_id: str, redirect_uri: str = None) -> str:
        """Google OAuth2認証URLを生成"""
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secrets.json',
                self.SCOPES
            )
            if redirect_uri:
                flow.redirect_uri = redirect_uri
            else:
                flow.redirect_uri = f"https://e66ddb393ad3.ngrok-free.app/oauth2callback"
            # stateパラメータにユーザーIDを含める
            auth_url, _ = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                state=user_id,
                prompt='consent'  # 毎回refresh_tokenを取得
            )
            return auth_url
        except Exception as e:
            print(f"Error generating authorization URL: {e}")
            return ""

    def handle_oauth2_callback(self, code: str, user_id: str, redirect_uri: str = None) -> bool:
        """OAuth2コールバックを処理"""
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secrets.json',
                self.SCOPES
            )
            if redirect_uri:
                flow.redirect_uri = redirect_uri
            else:
                flow.redirect_uri = f"https://e66ddb393ad3.ngrok-free.app/oauth2callback"
            # 認証コードをトークンに交換
            flow.fetch_token(code=code)
            # 認証情報を保存
            creds = flow.credentials

            # トークンをデータベースに保存
            if self.db.save_token(user_id, creds.to_json()):
                print(f"Token saved to database for user: {user_id}")
                return True
            else:
                print(f"Failed to save token to database for user: {user_id}")
                return False
        except Exception as e:
            print(f"Error handling OAuth2 callback: {e}")
            return False 