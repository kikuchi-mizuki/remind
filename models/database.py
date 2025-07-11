import os
import sqlite3
from datetime import datetime
from typing import List, Optional
import json

class Task:
    """タスクモデルクラス"""
    def __init__(self, task_id: str, user_id: str, name: str, duration_minutes: int, 
                 repeat: bool, status: str = "active", created_at: Optional[datetime] = None):
        self.task_id = task_id
        self.user_id = user_id
        self.name = name
        self.duration_minutes = duration_minutes
        self.repeat = repeat
        self.status = status
        self.created_at = created_at or datetime.now()

class ScheduleProposal:
    """スケジュール提案モデルクラス"""
    def __init__(self, user_id: str, proposal_data: dict, created_at: Optional[datetime] = None):
        self.user_id = user_id
        self.proposal_data = proposal_data
        self.created_at = created_at or datetime.now()

class Database:
    """データベース操作クラス"""
    def __init__(self, db_path: str = "tasks.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """データベースとテーブルの初期化"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # タスクテーブルの作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                repeat BOOLEAN NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # スケジュール提案テーブルの作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedule_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                proposal_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # ユーザー設定テーブルの作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                calendar_id TEXT,
                notification_time TEXT DEFAULT '08:00',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()

    def create_task(self, task: Task) -> bool:
        """タスクを作成"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO tasks (task_id, user_id, name, duration_minutes, repeat, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (task.task_id, task.user_id, task.name, task.duration_minutes, 
                  task.repeat, task.status, task.created_at))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error creating task: {e}")
            return False

    def get_user_tasks(self, user_id: str, status: str = "active") -> List[Task]:
        """ユーザーのタスク一覧を取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT task_id, user_id, name, duration_minutes, repeat, status, created_at
                FROM tasks
                WHERE user_id = ? AND status = ?
                ORDER BY created_at DESC
            ''', (user_id, status))
            
            tasks = []
            for row in cursor.fetchall():
                task = Task(
                    task_id=row[0],
                    user_id=row[1],
                    name=row[2],
                    duration_minutes=row[3],
                    repeat=bool(row[4]),
                    status=row[5],
                    created_at=datetime.fromisoformat(row[6])
                )
                tasks.append(task)
            
            conn.close()
            return tasks
        except Exception as e:
            print(f"Error getting user tasks: {e}")
            return []

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """タスクIDでタスクを取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT task_id, user_id, name, duration_minutes, repeat, status, created_at
                FROM tasks
                WHERE task_id = ?
            ''', (task_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return Task(
                    task_id=row[0],
                    user_id=row[1],
                    name=row[2],
                    duration_minutes=row[3],
                    repeat=bool(row[4]),
                    status=row[5],
                    created_at=datetime.fromisoformat(row[6])
                )
            return None
        except Exception as e:
            print(f"Error getting task by id: {e}")
            return None

    def update_task_status(self, task_id: str, status: str) -> bool:
        """タスクのステータスを更新"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE tasks
                SET status = ?
                WHERE task_id = ?
            ''', (status, task_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error updating task status: {e}")
            return False

    def save_schedule_proposal(self, user_id: str, proposal_data: dict) -> bool:
        """スケジュール提案を保存"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 古い提案を削除
            cursor.execute('DELETE FROM schedule_proposals WHERE user_id = ?', (user_id,))
            
            # 新しい提案を保存
            cursor.execute('''
                INSERT INTO schedule_proposals (user_id, proposal_data)
                VALUES (?, ?)
            ''', (user_id, json.dumps(proposal_data, ensure_ascii=False)))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving schedule proposal: {e}")
            return False

    def get_schedule_proposal(self, user_id: str) -> Optional[dict]:
        """スケジュール提案を取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT proposal_data
                FROM schedule_proposals
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            ''', (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return json.loads(row[0])
            return None
        except Exception as e:
            print(f"Error getting schedule proposal: {e}")
            return None

    def save_user_settings(self, user_id: str, calendar_id: Optional[str] = None, 
                          notification_time: str = "08:00") -> bool:
        """ユーザー設定を保存"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO user_settings (user_id, calendar_id, notification_time, updated_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, calendar_id, notification_time, datetime.now()))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error saving user settings: {e}")
            return False

    def get_user_settings(self, user_id: str) -> Optional[dict]:
        """ユーザー設定を取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT calendar_id, notification_time
                FROM user_settings
                WHERE user_id = ?
            ''', (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "calendar_id": row[0],
                    "notification_time": row[1]
                }
            return None
        except Exception as e:
            print(f"Error getting user settings: {e}")
            return None

# グローバルデータベースインスタンス
db = Database()

def init_db():
    """データベースの初期化"""
    global db
    db = Database()
    return db 