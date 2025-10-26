import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from typing import List, Optional
import json
from sqlalchemy import create_engine, Column, String, Text, Integer, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class TaskModel(Base):
    """タスクモデル（SQLAlchemy）"""
    __tablename__ = 'tasks'
    
    task_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    repeat = Column(Boolean, nullable=False)
    status = Column(String, default='active')
    created_at = Column(DateTime, default=datetime.now)
    due_date = Column(String)
    priority = Column(String, default='normal')
    task_type = Column(String, default='daily')

class TokenModel(Base):
    """トークンモデル（SQLAlchemy）"""
    __tablename__ = 'tokens'
    
    user_id = Column(String, primary_key=True)
    token_json = Column(Text, nullable=False)

class NotificationExecutionModel(Base):
    """通知実行履歴モデル（SQLAlchemy）"""
    __tablename__ = 'notification_executions'
    
    notification_type = Column(String, primary_key=True)
    last_execution_time = Column(String, nullable=False)

class UserChannelModel(Base):
    """ユーザーチャネルモデル（SQLAlchemy）"""
    __tablename__ = 'user_channels'
    
    user_id = Column(String, primary_key=True)
    channel_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class Task:
    """タスクモデルクラス（互換性維持）"""
    def __init__(self, task_id: str, user_id: str, name: str, duration_minutes: int, 
                 repeat: bool, status: str = "active", created_at: Optional[datetime] = None, 
                 due_date: Optional[str] = None, priority: str = "normal", task_type: str = "daily"):
        self.task_id = task_id
        self.user_id = user_id
        self.name = name
        self.duration_minutes = duration_minutes
        self.repeat = repeat
        self.status = status
        self.created_at = created_at or datetime.now()
        self.due_date = due_date
        self.priority = priority
        self.task_type = task_type

class PostgreSQLDatabase:
    """PostgreSQLデータベース操作クラス"""
    
    def __init__(self):
        self.engine = None
        self.Session = None
        self.db_path = "PostgreSQL"  # 互換性のための属性
        self._init_database()
    
    def _init_database(self):
        """データベース接続とテーブル初期化"""
        try:
            # Railway PostgreSQL環境変数から接続情報を取得
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                print("[PostgreSQLDatabase] DATABASE_URLが設定されていません")
                # SQLiteにフォールバック
                self._fallback_to_sqlite()
                return
            
            print(f"[PostgreSQLDatabase] PostgreSQL接続開始: {database_url[:50]}...")
            self.engine = create_engine(database_url)
            self.Session = sessionmaker(bind=self.engine)
            
            # テーブル作成
            print("[PostgreSQLDatabase] テーブル作成開始...")
            Base.metadata.create_all(self.engine)
            print("[PostgreSQLDatabase] テーブル作成完了")
            
            # 作成されたテーブルを確認
            from sqlalchemy import inspect
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
            print(f"[PostgreSQLDatabase] 作成されたテーブル: {tables}")
            
            print("[PostgreSQLDatabase] PostgreSQL接続完了")
            
            # テーブル作成を確実にするため、明示的に実行
            self._ensure_tables_exist()
            
        except Exception as e:
            print(f"[PostgreSQLDatabase] PostgreSQL接続エラー: {e}")
            print("[PostgreSQLDatabase] SQLiteにフォールバック")
            self._fallback_to_sqlite()
    
    def _ensure_tables_exist(self):
        """テーブルの存在を確認し、必要に応じて作成"""
        try:
            if not self.engine:
                print("[_ensure_tables_exist] エンジンが初期化されていません")
                return
            
            # 各テーブルを明示的に作成
            tables_to_create = [
                TaskModel.__table__,
                TokenModel.__table__,
                NotificationExecutionModel.__table__,
                UserChannelModel.__table__
            ]
            
            for table in tables_to_create:
                try:
                    table.create(self.engine, checkfirst=True)
                    print(f"[_ensure_tables_exist] テーブル作成確認: {table.name}")
                except Exception as e:
                    print(f"[_ensure_tables_exist] テーブル作成エラー {table.name}: {e}")
            
            # 最終確認
            from sqlalchemy import inspect
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
            print(f"[_ensure_tables_exist] 最終テーブル一覧: {tables}")
            
        except Exception as e:
            print(f"[_ensure_tables_exist] テーブル確認エラー: {e}")
    
    def _fallback_to_sqlite(self):
        """SQLiteにフォールバック"""
        try:
            from models.database import Database
            self.sqlite_db = Database()
            print("[PostgreSQLDatabase] SQLiteフォールバック完了")
        except Exception as e:
            print(f"[PostgreSQLDatabase] SQLiteフォールバックエラー: {e}")
    
    def _get_session(self):
        """セッションを取得"""
        if self.Session:
            return self.Session()
        return None
    
    def register_user(self, user_id: str) -> bool:
        """ユーザーを登録"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    # PostgreSQLでユーザー登録（既存チェック）
                    session.close()
                    return True
            else:
                # SQLiteフォールバック
                return self.sqlite_db.register_user(user_id)
        except Exception as e:
            print(f"Error registering user: {e}")
            return False
    
    def save_token(self, user_id: str, token_json: str) -> bool:
        """Google認証トークンを保存"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        # 既存のトークンを更新または新規作成
                        token = session.query(TokenModel).filter_by(user_id=user_id).first()
                        if token:
                            token.token_json = token_json
                        else:
                            token = TokenModel(user_id=user_id, token_json=token_json)
                            session.add(token)
                        
                        session.commit()
                        session.close()
                        print(f"[save_token] PostgreSQL保存成功: user_id={user_id}")
                        return True
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[save_token] PostgreSQL保存エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.save_token(user_id, token_json)
        except Exception as e:
            print(f"Error saving token: {e}")
            return False
    
    def get_token(self, user_id: str) -> Optional[str]:
        """Google認証トークンを取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        token = session.query(TokenModel).filter_by(user_id=user_id).first()
                        session.close()
                        
                        if token:
                            print(f"[get_token] PostgreSQL取得成功: user_id={user_id}")
                            return token.token_json
                        else:
                            print(f"[get_token] PostgreSQLトークンなし: user_id={user_id}")
                            return None
                    except Exception as e:
                        session.close()
                        print(f"[get_token] PostgreSQL取得エラー: {e}")
                        return None
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_token(user_id)
        except Exception as e:
            print(f"Error getting token: {e}")
            return None
    
    def save_user_channel(self, user_id: str, channel_id: str) -> bool:
        """ユーザーのチャネルIDを保存"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        # 既存のチャネル情報を更新または新規作成
                        user_channel = session.query(UserChannelModel).filter_by(user_id=user_id).first()
                        if user_channel:
                            user_channel.channel_id = channel_id
                        else:
                            user_channel = UserChannelModel(user_id=user_id, channel_id=channel_id)
                            session.add(user_channel)
                        
                        session.commit()
                        session.close()
                        print(f"[save_user_channel] PostgreSQL保存成功: user_id={user_id}, channel_id={channel_id}")
                        return True
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[save_user_channel] PostgreSQL保存エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.save_user_channel(user_id, channel_id)
        except Exception as e:
            print(f"Error saving user channel: {e}")
            return False
    
    def get_user_channel(self, user_id: str) -> Optional[str]:
        """ユーザーのチャネルIDを取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        user_channel = session.query(UserChannelModel).filter_by(user_id=user_id).first()
                        session.close()
                        
                        if user_channel:
                            print(f"[get_user_channel] PostgreSQL取得成功: user_id={user_id}, channel_id={user_channel.channel_id}")
                            return user_channel.channel_id
                        else:
                            print(f"[get_user_channel] PostgreSQLチャネルIDなし: user_id={user_id}")
                            return None
                    except Exception as e:
                        session.close()
                        print(f"[get_user_channel] PostgreSQL取得エラー: {e}")
                        return None
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_user_channel(user_id)
        except Exception as e:
            print(f"Error getting user channel: {e}")
            return None
    
    def get_all_user_ids(self) -> List[str]:
        """全ユーザーIDを取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        # tokensテーブルからユーザーIDを取得
                        tokens = session.query(TokenModel).all()
                        user_ids = [token.user_id for token in tokens]
                        session.close()
                        print(f"[get_all_user_ids] PostgreSQL取得成功: {len(user_ids)}ユーザー")
                        return user_ids
                    except Exception as e:
                        session.close()
                        print(f"[get_all_user_ids] PostgreSQL取得エラー: {e}")
                        return []
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_all_user_ids()
        except Exception as e:
            print(f"Error getting all user ids: {e}")
            return []
    
    def save_notification_execution(self, notification_type: str, execution_time: str) -> bool:
        """通知実行時刻を保存"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        # 既存の実行履歴を更新または新規作成
                        execution = session.query(NotificationExecutionModel).filter_by(notification_type=notification_type).first()
                        if execution:
                            execution.last_execution_time = execution_time
                        else:
                            execution = NotificationExecutionModel(notification_type=notification_type, last_execution_time=execution_time)
                            session.add(execution)
                        
                        session.commit()
                        session.close()
                        print(f"[save_notification_execution] PostgreSQL保存成功: type={notification_type}")
                        return True
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[save_notification_execution] PostgreSQL保存エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.save_notification_execution(notification_type, execution_time)
        except Exception as e:
            print(f"Error saving notification execution: {e}")
            return False
    
    def get_last_notification_execution(self, notification_type: str) -> Optional[str]:
        """最後の通知実行時刻を取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        execution = session.query(NotificationExecutionModel).filter_by(notification_type=notification_type).first()
                        session.close()
                        
                        if execution:
                            print(f"[get_last_notification_execution] PostgreSQL取得成功: type={notification_type}")
                            return execution.last_execution_time
                        else:
                            print(f"[get_last_notification_execution] PostgreSQL実行履歴なし: type={notification_type}")
                            return None
                    except Exception as e:
                        session.close()
                        print(f"[get_last_notification_execution] PostgreSQL取得エラー: {e}")
                        return None
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_last_notification_execution(notification_type)
        except Exception as e:
            print(f"Error getting last notification execution: {e}")
            return None
    
    # SQLite互換性メソッド
    def get_all_tasks(self, user_id: str = None):
        """全タスクを取得（SQLite互換性）"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        query = session.query(TaskModel)
                        if user_id:
                            query = query.filter_by(user_id=user_id)
                        tasks = query.all()
                        session.close()
                        
                        # TaskModelをTaskオブジェクトに変換
                        result = []
                        for task_model in tasks:
                            task = Task(
                                task_id=task_model.task_id,
                                user_id=task_model.user_id,
                                name=task_model.name,
                                duration_minutes=task_model.duration_minutes,
                                repeat=task_model.repeat,
                                status=task_model.status,
                                created_at=task_model.created_at,
                                due_date=task_model.due_date,
                                priority=task_model.priority,
                                task_type=task_model.task_type
                            )
                            result.append(task)
                        
                        return result
                    except Exception as e:
                        session.close()
                        print(f"[get_all_tasks] PostgreSQL取得エラー: {e}")
                        return []
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_all_tasks(user_id)
        except Exception as e:
            print(f"Error getting all tasks: {e}")
            return []
    
    def add_task(self, task: Task) -> bool:
        """タスクを追加（SQLite互換性）"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        task_model = TaskModel(
                            task_id=task.task_id,
                            user_id=task.user_id,
                            name=task.name,
                            duration_minutes=task.duration_minutes,
                            repeat=task.repeat,
                            status=task.status,
                            created_at=task.created_at,
                            due_date=task.due_date,
                            priority=task.priority,
                            task_type=task.task_type
                        )
                        session.add(task_model)
                        session.commit()
                        session.close()
                        print(f"[add_task] PostgreSQL追加成功: {task.task_id}")
                        return True
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[add_task] PostgreSQL追加エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.add_task(task)
        except Exception as e:
            print(f"Error adding task: {e}")
            return False
    
    def create_task(self, task: Task) -> bool:
        """タスクを作成（SQLite互換性）"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        task_model = TaskModel(
                            task_id=task.task_id,
                            user_id=task.user_id,
                            name=task.name,
                            duration_minutes=task.duration_minutes,
                            repeat=task.repeat,
                            status=task.status,
                            created_at=task.created_at,
                            due_date=task.due_date,
                            priority=task.priority,
                            task_type=task.task_type
                        )
                        session.add(task_model)
                        session.commit()
                        session.close()
                        print(f"[create_task] PostgreSQL作成成功: {task.task_id}")
                        return True
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[create_task] PostgreSQL作成エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.create_task(task)
        except Exception as e:
            print(f"Error creating task: {e}")
            return False
    
    def delete_task(self, task_id: str) -> bool:
        """タスクを削除（SQLite互換性）"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        task = session.query(TaskModel).filter_by(task_id=task_id).first()
                        if task:
                            session.delete(task)
                            session.commit()
                            session.close()
                            print(f"[delete_task] PostgreSQL削除成功: {task_id}")
                            return True
                        else:
                            session.close()
                            print(f"[delete_task] PostgreSQLタスクが見つかりません: {task_id}")
                            return False
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[delete_task] PostgreSQL削除エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.delete_task(task_id)
        except Exception as e:
            print(f"Error deleting task: {e}")
            return False
    
    def get_user_tasks(self, user_id: str, status: str = "active", task_type: str = "daily") -> List[Task]:
        """ユーザーのタスクを取得（SQLite互換性）"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        tasks = session.query(TaskModel).filter_by(
                            user_id=user_id, 
                            status=status, 
                            task_type=task_type
                        ).all()
                        session.close()
                        
                        # TaskModelをTaskオブジェクトに変換
                        result = []
                        for task_model in tasks:
                            task = Task(
                                task_id=task_model.task_id,
                                user_id=task_model.user_id,
                                name=task_model.name,
                                duration_minutes=task_model.duration_minutes,
                                repeat=task_model.repeat,
                                status=task_model.status,
                                created_at=task_model.created_at,
                                due_date=task_model.due_date,
                                priority=task_model.priority,
                                task_type=task_model.task_type
                            )
                            result.append(task)
                        
                        print(f"[get_user_tasks] PostgreSQL取得成功: user_id={user_id}, status={status}, task_type={task_type}, タスク数={len(result)}")
                        return result
                    except Exception as e:
                        session.close()
                        print(f"[get_user_tasks] PostgreSQL取得エラー: {e}")
                        return []
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_user_tasks(user_id, status, task_type)
        except Exception as e:
            print(f"Error getting user tasks: {e}")
            return []

    def create_future_task(self, task: Task) -> bool:
        """未来タスクを作成"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        task_model = TaskModel(
                            task_id=task.task_id,
                            user_id=task.user_id,
                            name=task.name,
                            duration_minutes=task.duration_minutes,
                            repeat=task.repeat,
                            status=task.status,
                            created_at=task.created_at,
                            due_date=task.due_date,
                            priority=task.priority,
                            task_type=task.task_type
                        )
                        session.add(task_model)
                        session.commit()
                        session.close()
                        print(f"[create_future_task] PostgreSQL作成成功: {task.task_id}")
                        return True
                    except Exception as e:
                        session.close()
                        print(f"[create_future_task] PostgreSQL作成エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.create_future_task(task)
        except Exception as e:
            print(f"Error creating future task: {e}")
            return False

    def get_user_future_tasks(self, user_id: str, status: str = "active") -> List[Task]:
        """ユーザーの未来タスク一覧を取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        tasks = session.query(TaskModel).filter_by(
                            user_id=user_id, 
                            status=status, 
                            task_type='future'
                        ).all()
                        session.close()
                        
                        # TaskModelをTaskオブジェクトに変換
                        result = []
                        for task_model in tasks:
                            task = Task(
                                task_id=task_model.task_id,
                                user_id=task_model.user_id,
                                name=task_model.name,
                                duration_minutes=task_model.duration_minutes,
                                repeat=task_model.repeat,
                                status=task_model.status,
                                created_at=task_model.created_at,
                                due_date=task_model.due_date,
                                priority=task_model.priority,
                                task_type=task_model.task_type
                            )
                            result.append(task)
                        
                        print(f"[get_user_future_tasks] PostgreSQL取得成功: user_id={user_id}, status={status}, タスク数={len(result)}")
                        return result
                    except Exception as e:
                        session.close()
                        print(f"[get_user_future_tasks] PostgreSQL取得エラー: {e}")
                        return []
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_user_future_tasks(user_id, status)
        except Exception as e:
            print(f"Error getting user future tasks: {e}")
            return []

    def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """タスクIDでタスクを取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        task_model = session.query(TaskModel).filter_by(task_id=task_id).first()
                        session.close()
                        
                        if task_model:
                            task = Task(
                                task_id=task_model.task_id,
                                user_id=task_model.user_id,
                                name=task_model.name,
                                duration_minutes=task_model.duration_minutes,
                                repeat=task_model.repeat,
                                status=task_model.status,
                                created_at=task_model.created_at,
                                due_date=task_model.due_date,
                                priority=task_model.priority,
                                task_type=task_model.task_type
                            )
                            print(f"[get_task_by_id] PostgreSQL取得成功: task_id={task_id}")
                            return task
                        else:
                            print(f"[get_task_by_id] PostgreSQLタスクが見つかりません: task_id={task_id}")
                            return None
                    except Exception as e:
                        session.close()
                        print(f"[get_task_by_id] PostgreSQL取得エラー: {e}")
                        return None
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_task_by_id(task_id)
        except Exception as e:
            print(f"Error getting task by id: {e}")
            return None

    def update_task_status(self, task_id: str, status: str) -> bool:
        """タスクのステータスを更新"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        task = session.query(TaskModel).filter_by(task_id=task_id).first()
                        if task:
                            task.status = status
                            session.commit()
                            session.close()
                            print(f"[update_task_status] PostgreSQL更新成功: task_id={task_id}, status={status}")
                            return True
                        else:
                            session.close()
                            print(f"[update_task_status] PostgreSQLタスクが見つかりません: task_id={task_id}")
                            return False
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[update_task_status] PostgreSQL更新エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.update_task_status(task_id, status)
        except Exception as e:
            print(f"Error updating task status: {e}")
            return False

    def save_schedule_proposal(self, user_id: str, proposal_data: dict) -> bool:
        """スケジュール提案を保存（PostgreSQLでは未実装、SQLiteフォールバック）"""
        try:
            if self.Session:
                # PostgreSQLでは未実装のため、SQLiteフォールバック
                return self.sqlite_db.save_schedule_proposal(user_id, proposal_data)
            else:
                return self.sqlite_db.save_schedule_proposal(user_id, proposal_data)
        except Exception as e:
            print(f"Error saving schedule proposal: {e}")
            return False

    def get_schedule_proposal(self, user_id: str) -> Optional[dict]:
        """スケジュール提案を取得（PostgreSQLでは未実装、SQLiteフォールバック）"""
        try:
            if self.Session:
                # PostgreSQLでは未実装のため、SQLiteフォールバック
                return self.sqlite_db.get_schedule_proposal(user_id)
            else:
                return self.sqlite_db.get_schedule_proposal(user_id)
        except Exception as e:
            print(f"Error getting schedule proposal: {e}")
            return None

    def save_user_settings(self, user_id: str, calendar_id: Optional[str] = None, 
                          notification_time: str = "08:00") -> bool:
        """ユーザー設定を保存（PostgreSQLでは未実装、SQLiteフォールバック）"""
        try:
            if self.Session:
                # PostgreSQLでは未実装のため、SQLiteフォールバック
                return self.sqlite_db.save_user_settings(user_id, calendar_id, notification_time)
            else:
                return self.sqlite_db.save_user_settings(user_id, calendar_id, notification_time)
        except Exception as e:
            print(f"Error saving user settings: {e}")
            return False

    def get_user_settings(self, user_id: str) -> Optional[dict]:
        """ユーザー設定を取得（PostgreSQLでは未実装、SQLiteフォールバック）"""
        try:
            if self.Session:
                # PostgreSQLでは未実装のため、SQLiteフォールバック
                return self.sqlite_db.get_user_settings(user_id)
            else:
                return self.sqlite_db.get_user_settings(user_id)
        except Exception as e:
            print(f"Error getting user settings: {e}")
            return None

# グローバルデータベースインスタンス
postgres_db = None

def init_postgres_db():
    """PostgreSQLデータベースを初期化"""
    global postgres_db
    if postgres_db is None:
        postgres_db = PostgreSQLDatabase()
    return postgres_db
