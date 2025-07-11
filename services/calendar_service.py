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
        """ユーザーの認証を行う（app.pyの認証フローに依存）"""
        try:
            token_path = f'tokens/{user_id}_token.json'
            if not os.path.exists(token_path):
                print(f"Token file not found: {token_path}")
                return False
            
            creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)
            
            # refresh_tokenが無い場合は認証失敗
            if not creds.refresh_token:
                print(f"No refresh_token found for user: {user_id}")
                return False
            
            # トークンが期限切れの場合は更新
            if creds.expired:
                try:
                    creds.refresh(Request())
                    # 更新されたトークンを保存
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
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
            # 指定日の開始と終了時間
            start_time = date.replace(hour=8, minute=0, second=0, microsecond=0)
            end_time = date.replace(hour=22, minute=0, second=0, microsecond=0)
            
            # 既存の予定を取得
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
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
        """カレンダーにイベントを追加"""
        if not self.authenticate_user(user_id):
            return False
        
        try:
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            event = {
                'summary': f'📝 {task_name}',
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
        """スケジュール提案をカレンダーに反映"""
        try:
            lines = schedule_proposal.split('\n')
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            event_added = False
            for line in lines:
                # 柔軟な正規表現: 記号・装飾・全角/半角・区切りの違いも許容
                m = re.match(r"[-・*\s]*\*?\*?\s*(\d{1,2})[:：]?(\d{2})\s*[〜~\-ー―‐–—−﹣－:：]?\s*(\d{1,2})[:：]?(\d{2})\*?\*?\s*([\u3000 \t\-–—―‐]*)?(.+?)\s*\((\d+)分\)", line)
                if m:
                    start_hour = int(m.group(1))
                    start_min = int(m.group(2))
                    end_hour = int(m.group(3))
                    end_min = int(m.group(4))
                    task_name = m.group(6).strip()
                    duration = int(m.group(7))
                    # 開始日時
                    start_time = today.replace(hour=start_hour, minute=start_min)
                    self.add_event_to_calendar(user_id, task_name, start_time, duration)
                    event_added = True
                else:
                    # パースできなかった行を警告
                    if line.strip():
                        print(f"[add_events_to_calendar] パースできなかった行: {line}")
            return event_added
        except Exception as e:
            print(f"Error adding events to calendar: {e}")
            return False

    def get_today_schedule(self, user_id: str) -> List[Dict]:
        """今日のスケジュールを取得"""
        if not self.authenticate_user(user_id):
            return []
        
        try:
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            
            events_result = self.service.events().list(
                calendarId='primary',
                timeMin=today.isoformat() + 'Z',
                timeMax=tomorrow.isoformat() + 'Z',
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
            
        except HttpError as error:
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
                timeMin=start_time.isoformat() + 'Z',
                timeMax=end_time.isoformat() + 'Z',
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
            # トークンをファイルに保存
            os.makedirs('tokens', exist_ok=True)
            token_path = f'tokens/{user_id}_token.json'
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
            return True
        except Exception as e:
            print(f"Error handling OAuth2 callback: {e}")
            return False 