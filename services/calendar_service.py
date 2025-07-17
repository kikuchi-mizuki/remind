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

    def authenticate_user(self, user_id: str) -> bool:
        """ユーザーの認証を行う（DB保存方式）"""
        try:
            from models.database import db
            token_json = db.get_token(user_id)
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
                    db.save_token(user_id, creds.to_json())
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
            
            # 既存の予定を取得
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time.isoformat(),
                timeMax=end_time.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # 空き時間を計算
            free_times = []
            current_time = start_time
            
            for event in events:
                event_start = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date')))
                event_end = datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
                
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
            
            return free_times
            
        except HttpError as error:
            print(f'Calendar API error: {error}')
            return []

    def add_event_to_calendar(self, user_id: str, task_name: str, start_time: datetime, 
                            duration_minutes: int, description: str = "") -> bool:
        """カレンダーにイベントを追加（bot追加分はsummaryに[added_by_bot]を付与）"""
        if not self.authenticate_user(user_id):
            return False
        try:
            end_time = start_time + timedelta(minutes=duration_minutes)
            event = {
                'summary': f'📝 {task_name} [added_by_bot]',
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
            event = self.service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            print(f'Event created: {event.get("htmlLink")}')
            return True
        except HttpError as error:
            print(f'Calendar API error: {error}')
            return False

    def add_events_to_calendar(self, user_id: str, schedule_proposal: str) -> bool:
        """スケジュール提案をカレンダーに反映（日付パース強化・2行セット対応・未来タスク対応）"""
        try:
            import re
            from datetime import datetime, timedelta
            import pytz
            lines = [line.strip() for line in schedule_proposal.split('\n') if line.strip()]
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst).replace(hour=0, minute=0, second=0, microsecond=0)
            event_added = False
            unparsable_lines = []
            i = 0
            
            # 未来タスクかどうかを判定（来週のスケジュール提案かチェック）
            is_future_task = any('来週のスケジュール提案' in line for line in lines)
            
            while i < len(lines):
                line = lines[i]
                
                # 日付行を検出（例: 7/22(月)）
                date_match = re.match(r'(\d{1,2})/(\d{1,2})\([月火水木金土日]\)', line)
                target_date = today
                if date_match and is_future_task:
                    # 来週の日付を計算
                    month = int(date_match.group(1))
                    day = int(date_match.group(2))
                    current_year = today.year
                    # 来週の日付を計算（簡易版）
                    target_date = today + timedelta(days=7)
                    target_date = target_date.replace(month=month, day=day)
                
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
                        self.add_event_to_calendar(user_id, task_name, start_time, duration)
                        event_added = True
                        i += 2
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
                        self.add_event_to_calendar(user_id, task_name, start_time, duration)
                        event_added = True
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
                    self.add_event_to_calendar(user_id, task_name, start_time, duration)
                    event_added = True
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
                        self.add_event_to_calendar(user_id, task_name, start_time, duration)
                        event_added = True
                    except Exception as e:
                        print(f"[add_events_to_calendar] パース失敗: {line} err={e}")
                    i += 1
                    continue
                # パースできなかった行を記録
                if line.strip():
                    print(f"[add_events_to_calendar] パースできなかった行: {line}")
                    unparsable_lines.append(line)
                i += 1
            return event_added
        except Exception as e:
            print(f"Error adding events to calendar: {e}")
            return False

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
            schedule = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                end = event['end'].get('dateTime', event['end'].get('date'))
                schedule.append({
                    'title': event['summary'],
                    'start': start,
                    'end': end,
                    'description': event.get('description', '')
                })
            return schedule
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
        free_times = self.get_free_busy_times(user_id, datetime.now())
        
        if not free_times:
            return None
        
        # タスクタイプに応じて優先順位を設定
        if task_type in ["important", "focus"]:
            # 重要・集中系は午前を優先
            morning_times = [t for t in free_times if t['start'].hour < 12]
            if morning_times:
                free_times = morning_times
        
        # 十分な時間がある空き時間をフィルタリング
        suitable_times = [t for t in free_times if t['duration_minutes'] >= duration_minutes]
        
        if not suitable_times:
            return None
        
        # 最も早い時間を選択
        return min(suitable_times, key=lambda x: x['start'])['start']

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
            from models.database import db
            if db.save_token(user_id, creds.to_json()):
                print(f"Token saved to database for user: {user_id}")
                return True
            else:
                print(f"Failed to save token to database for user: {user_id}")
                return False
        except Exception as e:
            print(f"Error handling OAuth2 callback: {e}")
            return False 