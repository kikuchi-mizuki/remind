import os
import sqlite3
from datetime import datetime
from typing import List, Optional
import json
from sqlalchemy import Column, String, Text

class Task:
    """タスクモデルクラス"""
    def __init__(self, task_id: str, user_id: str, name: str, duration_minutes: int, 
                 repeat: bool, status: str = "active", created_at: Optional[datetime] = None, due_date: Optional[str] = None, priority: str = "normal", task_type: str = "daily"):
        self.task_id = task_id
        self.user_id = user_id
        self.name = name
        self.duration_minutes = duration_minutes
        self.repeat = repeat
        self.status = status
        self.created_at = created_at or datetime.now()
        self.due_date = due_date  # 期日（YYYY-MM-DD 形式の文字列）
        self.priority = priority  # 優先度: "urgent_important", "not_urgent_important", "urgent_not_important", "normal"
        self.task_type = task_type  # タスクタイプ: "daily"（毎日のタスク）, "future"（未来タスク）

class ScheduleProposal:
    """スケジュール提案モデルクラス"""
    def __init__(self, user_id: str, proposal_data: dict, created_at: Optional[datetime] = None):
        self.user_id = user_id
        self.proposal_data = proposal_data
        self.created_at = created_at or datetime.now()

class Database:
    """データベース操作クラス"""
    def __init__(self, db_path: str = "tasks.db"):
        if db_path == "tasks.db":
            # Railway環境では絶対パスを使用
            import os
            # Railway環境の検出を改善
            if os.path.exists('/app') or os.environ.get('RAILWAY_ENVIRONMENT'):
                # ボリュームがマウントされているかチェック
                if os.path.exists('/app/vol'):
                    self.db_path = "/app/vol/tasks.db"
                    print(f"[Database] Railway環境（ボリューム有）: {self.db_path}")
                else:
                    # ボリュームがマウントされていない場合は/app直下に保存
                    self.db_path = "/app/tasks.db"
                    print(f"[Database] Railway環境（ボリューム無）: {self.db_path}")
            else:
                self.db_path = "tasks.db"
                print(f"[Database] ローカル環境: {self.db_path}")
        else:
            self.db_path = db_path
        self.init_database()

    def init_database(self):
        """データベースとテーブルの初期化"""
        # データベースファイルの親ディレクトリを必ず作成
        db_dir = os.path.dirname(self.db_path)
        if db_dir:  # ディレクトリパスが存在する場合のみ作成
            os.makedirs(db_dir, exist_ok=True)
        print(f"[init_database] 開始: {self.db_path}")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # タスクテーブルの作成（task_typeカラムを追加）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                repeat BOOLEAN NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                due_date TEXT,
                priority TEXT DEFAULT 'normal',
                task_type TEXT DEFAULT 'daily'
            )
        ''')
        
        # 既存のテーブルにtask_typeカラムが存在しない場合は追加
        try:
            cursor.execute('ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT "daily"')
            print("[init_database] task_typeカラムを追加しました")
        except sqlite3.OperationalError:
            print("[init_database] task_typeカラムは既に存在します")
        
        # 既存のテーブルにpriorityカラムが存在しない場合は追加
        try:
            cursor.execute('ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT "normal"')
            print("[init_database] priorityカラムを追加しました")
        except sqlite3.OperationalError:
            print("[init_database] priorityカラムは既に存在します")
        
        # 未来タスクテーブルの作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS future_tasks (
                task_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                priority TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                category TEXT DEFAULT 'investment'
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
        
        # tokensテーブルの作成
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                user_id TEXT PRIMARY KEY,
                token_json TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
        print(f"[init_database] 完了: {self.db_path}")

    def create_task(self, task: Task) -> bool:
        """タスクを作成"""
        try:
            print(f"[create_task] INSERT値: task_id={task.task_id}, user_id={task.user_id}, name={task.name}, duration_minutes={task.duration_minutes}, repeat={task.repeat}, status={task.status}, created_at={task.created_at}, due_date={task.due_date}, priority={task.priority}, task_type={task.task_type}")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tasks (task_id, user_id, name, duration_minutes, repeat, status, created_at, due_date, priority, task_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (task.task_id, task.user_id, task.name, task.duration_minutes, 
                  task.repeat, task.status, task.created_at, task.due_date, task.priority, task.task_type))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[create_task] Error creating task: {e}")
            return False

    def create_future_task(self, task: Task) -> bool:
        """未来タスクを作成（tasksテーブルに統一）"""
        try:
            print(f"[create_future_task] INSERT値: task_id={task.task_id}, user_id={task.user_id}, name={task.name}, duration_minutes={task.duration_minutes}, priority={task.priority}, status={task.status}, created_at={task.created_at}, task_type={task.task_type}")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tasks (task_id, user_id, name, duration_minutes, repeat, status, created_at, due_date, priority, task_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (task.task_id, task.user_id, task.name, task.duration_minutes, 
                  task.repeat, task.status, task.created_at, task.due_date, task.priority, task.task_type))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"[create_future_task] Error creating future task: {e}")
            return False

    def get_user_tasks(self, user_id: str, status: str = "active", task_type: str = "daily") -> List[Task]:
        """ユーザーのタスク一覧を取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT task_id, user_id, name, duration_minutes, repeat, status, created_at, due_date, priority, task_type
                FROM tasks
                WHERE user_id = ? AND status = ? AND task_type = ?
                ORDER BY created_at DESC
            ''', (user_id, status, task_type))
            
            tasks = []
            for row in cursor.fetchall():
                task = Task(
                    task_id=row[0],
                    user_id=row[1],
                    name=row[2],
                    duration_minutes=row[3],
                    repeat=bool(row[4]),
                    status=row[5],
                    created_at=datetime.fromisoformat(row[6]),
                    due_date=row[7],
                    priority=row[8] if row[8] else "normal",
                    task_type=row[9] if row[9] else "daily"
                )
                tasks.append(task)
            
            conn.close()
            return tasks
        except Exception as e:
            print(f"Error getting user tasks: {e}")
            return []

    def get_user_future_tasks(self, user_id: str, status: str = "active") -> List[Task]:
        """ユーザーの未来タスク一覧を取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT task_id, user_id, name, duration_minutes, repeat, status, created_at, due_date, priority, task_type
                FROM tasks
                WHERE user_id = ? AND status = ? AND task_type = 'future'
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
                    created_at=datetime.fromisoformat(row[6]),
                    due_date=row[7],
                    priority=row[8] if row[8] else "normal",
                    task_type=row[9] if row[9] else "future"
                )
                tasks.append(task)
            
            conn.close()
            return tasks
        except Exception as e:
            print(f"Error getting user future tasks: {e}")
            return []

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """タスクIDでタスクを取得"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT task_id, user_id, name, duration_minutes, repeat, status, created_at, due_date, priority
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
                    created_at=datetime.fromisoformat(row[6]),
                    due_date=row[7],
                    priority=row[8] if row[8] else "normal"
                )
            return None
        except Exception as e:
            print(f"Error getting task by id: {e}")
            return None

    def update_task_status(self, task_id: str, status: str) -> bool:
        """タスクのステータスを更新（通常タスクと未来タスクの両方に対応）"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 通常タスクテーブルで更新を試行
            cursor.execute('''
                UPDATE tasks
                SET status = ?
                WHERE task_id = ?
            ''', (status, task_id))
            
            # 更新された行数を確認
            rows_updated = cursor.rowcount
            
            # 通常タスクで更新されなかった場合、未来タスクテーブルで更新を試行
            if rows_updated == 0:
                cursor.execute('''
                    UPDATE future_tasks
                    SET status = ?
                    WHERE task_id = ?
                ''', (status, task_id))
                rows_updated = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            if rows_updated > 0:
                print(f"[update_task_status] 成功: task_id={task_id}, status={status}, rows_updated={rows_updated}")
                return True
            else:
                print(f"[update_task_status] 失敗: task_id={task_id} が見つかりません")
                return False
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

    def register_user(self, user_id: str) -> bool:
        """ユーザーを登録（初回メッセージ時に呼び出し）"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # user_settingsテーブルにユーザーを登録（既に存在する場合は何もしない）
            cursor.execute('''
                INSERT OR IGNORE INTO user_settings (user_id, created_at)
                VALUES (?, ?)
            ''', (user_id, datetime.now()))
            
            conn.commit()
            conn.close()
            print(f"[register_user] ユーザー {user_id} を登録しました")
            return True
        except Exception as e:
            print(f"Error registering user: {e}")
            return False

    def get_all_user_ids(self) -> List[str]:
        """
        全ユーザーのuser_id一覧を取得（tasksテーブルとuser_settingsテーブルから一意に抽出）
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # tasksテーブルとuser_settingsテーブルの両方からユーザーIDを取得
            cursor.execute('''
                SELECT DISTINCT user_id FROM (
                    SELECT user_id FROM tasks
                    UNION
                    SELECT user_id FROM user_settings
                )
            ''')
            
            user_ids = [row[0] for row in cursor.fetchall()]
            conn.close()
            print(f"[get_all_user_ids] 取得したユーザー数: {len(user_ids)}")
            return user_ids
        except Exception as e:
            print(f"Error getting all user ids: {e}")
            return []

    def save_token(self, user_id: str, token_json: str) -> bool:
        """Google認証トークンを保存"""
        try:
            print(f"[save_token] 開始: user_id={user_id}, db_path={self.db_path}")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO tokens (user_id, token_json)
                VALUES (?, ?)
            ''', (user_id, token_json))
            
            conn.commit()
            conn.close()
            print(f"[save_token] 成功: user_id={user_id}")
            return True
        except Exception as e:
            print(f"Error saving token: {e}")
            return False

    def get_token(self, user_id: str) -> Optional[str]:
        """Google認証トークンを取得"""
        try:
            print(f"[get_token] 開始: user_id={user_id}, db_path={self.db_path}")
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT token_json
                FROM tokens
                WHERE user_id = ?
            ''', (user_id,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                print(f"[get_token] 成功: user_id={user_id}, token_length={len(row[0])}")
                return row[0]
            print(f"[get_token] トークンなし: user_id={user_id}")
            return None
        except Exception as e:
            print(f"Error getting token: {e}")
            return None

# グローバルデータベースインスタンス
db = None

def init_db():
    """データベースの初期化"""
    global db
    if db is None:
        db = Database()
        print(f"[init_db] 新しいデータベースインスタンスを作成: {db.db_path}")
    else:
        print(f"[init_db] 既存のデータベースインスタンスを再利用: {db.db_path}")
    return db 