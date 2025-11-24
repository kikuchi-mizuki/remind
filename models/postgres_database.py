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

class ScheduleProposalModel(Base):
    """スケジュール提案モデル（SQLAlchemy）"""
    __tablename__ = 'schedule_proposals'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False)
    proposal_data = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

class UserSettingsModel(Base):
    """ユーザー設定モデル（SQLAlchemy）"""
    __tablename__ = 'user_settings'

    user_id = Column(String, primary_key=True)
    calendar_id = Column(String)
    notification_time = Column(String, default="08:00")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class UserStateModel(Base):
    """ユーザー状態モデル（SQLAlchemy）"""
    __tablename__ = 'user_states'

    user_id = Column(String, primary_key=True)
    state_type = Column(String, primary_key=True)
    state_data = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

class OpenAICacheModel(Base):
    """OpenAI APIキャッシュモデル（SQLAlchemy）"""
    __tablename__ = 'openai_cache'

    cache_key = Column(String, primary_key=True)
    model = Column(String, nullable=False)
    prompt_hash = Column(String, nullable=False)
    prompt_preview = Column(String)
    response = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    hit_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

class UserSessionModel(Base):
    """ユーザーセッションモデル（SQLAlchemy）"""
    __tablename__ = 'user_sessions'

    user_id = Column(String, primary_key=True)
    session_type = Column(String, primary_key=True)
    data = Column(Text, nullable=False)
    expires_at = Column(DateTime)
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
                UserChannelModel.__table__,
                ScheduleProposalModel.__table__,
                UserSettingsModel.__table__,
                UserStateModel.__table__,
                OpenAICacheModel.__table__,
                UserSessionModel.__table__
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
                        print(f"[save_token] PostgreSQL保存成功: user_id={user_id}")
                        return True
                    except Exception as e:
                        session.rollback()
                        print(f"[save_token] PostgreSQL保存エラー: {e}")
                        import traceback
                        traceback.print_exc()
                        return False
                    finally:
                        session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.save_token(user_id, token_json)
        except Exception as e:
            print(f"Error saving token: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_token(self, user_id: str) -> Optional[str]:
        """Google認証トークンを取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        token = session.query(TokenModel).filter_by(user_id=user_id).first()

                        if token:
                            print(f"[get_token] PostgreSQL取得成功: user_id={user_id}")
                            return token.token_json
                        else:
                            print(f"[get_token] PostgreSQLトークンなし: user_id={user_id}")
                            return None
                    except Exception as e:
                        print(f"[get_token] PostgreSQL取得エラー: {e}")
                        import traceback
                        traceback.print_exc()
                        return None
                    finally:
                        session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_token(user_id)
        except Exception as e:
            print(f"Error getting token: {e}")
            import traceback
            traceback.print_exc()
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

    def get_all_user_channels(self) -> dict:
        """全ユーザーのチャネルIDを一括取得（N+1クエリ問題の解決）"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        print(f"[get_all_user_channels] PostgreSQL一括取得開始")
                        user_channels_list = session.query(UserChannelModel).all()
                        user_channels = {uc.user_id: uc.channel_id for uc in user_channels_list}
                        print(f"[get_all_user_channels] PostgreSQL成功: {len(user_channels)}件取得")
                        return user_channels
                    except Exception as e:
                        print(f"[get_all_user_channels] PostgreSQLエラー: {e}")
                        import traceback
                        traceback.print_exc()
                        return {}
                    finally:
                        session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_all_user_channels()
        except Exception as e:
            print(f"Error getting all user channels: {e}")
            import traceback
            traceback.print_exc()
            return {}

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
        """スケジュール提案を保存"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        # 古い提案を削除
                        session.query(ScheduleProposalModel).filter_by(user_id=user_id).delete()
                        
                        # 新しい提案を保存
                        proposal_json = json.dumps(proposal_data, ensure_ascii=False)
                        proposal = ScheduleProposalModel(
                            user_id=user_id,
                            proposal_data=proposal_json
                        )
                        session.add(proposal)
                        session.commit()
                        session.close()
                        print(f"[save_schedule_proposal] PostgreSQL保存成功: user_id={user_id}")
                        return True
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[save_schedule_proposal] PostgreSQL保存エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.save_schedule_proposal(user_id, proposal_data)
        except Exception as e:
            print(f"Error saving schedule proposal: {e}")
            return False

    def get_schedule_proposal(self, user_id: str) -> Optional[dict]:
        """スケジュール提案を取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        proposal = session.query(ScheduleProposalModel).filter_by(user_id=user_id).order_by(ScheduleProposalModel.created_at.desc()).first()
                        session.close()
                        
                        if proposal:
                            proposal_data = json.loads(proposal.proposal_data)
                            print(f"[get_schedule_proposal] PostgreSQL取得成功: user_id={user_id}")
                            return proposal_data
                        else:
                            print(f"[get_schedule_proposal] PostgreSQL提案なし: user_id={user_id}")
                            return None
                    except Exception as e:
                        session.close()
                        print(f"[get_schedule_proposal] PostgreSQL取得エラー: {e}")
                        return None
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_schedule_proposal(user_id)
        except Exception as e:
            print(f"Error getting schedule proposal: {e}")
            return None

    def save_user_settings(self, user_id: str, calendar_id: Optional[str] = None, 
                          notification_time: str = "08:00") -> bool:
        """ユーザー設定を保存"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        # 既存の設定を更新または新規作成
                        settings = session.query(UserSettingsModel).filter_by(user_id=user_id).first()
                        if settings:
                            settings.calendar_id = calendar_id
                            settings.notification_time = notification_time
                            settings.updated_at = datetime.now()
                        else:
                            settings = UserSettingsModel(
                                user_id=user_id,
                                calendar_id=calendar_id,
                                notification_time=notification_time
                            )
                            session.add(settings)
                        
                        session.commit()
                        session.close()
                        print(f"[save_user_settings] PostgreSQL保存成功: user_id={user_id}")
                        return True
                    except Exception as e:
                        session.rollback()
                        session.close()
                        print(f"[save_user_settings] PostgreSQL保存エラー: {e}")
                        return False
            else:
                # SQLiteフォールバック
                return self.sqlite_db.save_user_settings(user_id, calendar_id, notification_time)
        except Exception as e:
            print(f"Error saving user settings: {e}")
            return False

    def get_user_settings(self, user_id: str) -> Optional[dict]:
        """ユーザー設定を取得"""
        try:
            if self.Session:
                session = self._get_session()
                if session:
                    try:
                        settings = session.query(UserSettingsModel).filter_by(user_id=user_id).first()
                        session.close()
                        
                        if settings:
                            result = {
                                "calendar_id": settings.calendar_id,
                                "notification_time": settings.notification_time
                            }
                            print(f"[get_user_settings] PostgreSQL取得成功: user_id={user_id}")
                            return result
                        else:
                            print(f"[get_user_settings] PostgreSQL設定なし: user_id={user_id}")
                            return None
                    except Exception as e:
                        session.close()
                        print(f"[get_user_settings] PostgreSQL取得エラー: {e}")
                        return None
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_user_settings(user_id)
        except Exception as e:
            print(f"Error getting user settings: {e}")
            return None

    def check_user_state(self, user_id: str, state_type: str) -> bool:
        """
        ユーザーの状態が存在するかチェック

        Args:
            user_id: ユーザーID
            state_type: 状態タイプ

        Returns:
            bool: 存在する場合True
        """
        try:
            if self.engine:
                session = self._get_session()
                try:
                    result = session.query(UserStateModel).filter_by(
                        user_id=user_id,
                        state_type=state_type
                    ).first()
                    return result is not None
                except Exception as e:
                    print(f"[check_user_state] PostgreSQLエラー: {e}")
                    return False
                finally:
                    session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.check_user_state(user_id, state_type)
        except Exception as e:
            print(f"[check_user_state] エラー: {e}")
            return False

    def delete_user_state(self, user_id: str, state_type: str) -> bool:
        """
        ユーザーの状態を削除

        Args:
            user_id: ユーザーID
            state_type: 状態タイプ

        Returns:
            bool: 成功時True
        """
        try:
            if self.engine:
                session = self._get_session()
                try:
                    session.query(UserStateModel).filter_by(
                        user_id=user_id,
                        state_type=state_type
                    ).delete()
                    session.commit()
                    print(f"[delete_user_state] 状態削除: user_id={user_id}, state_type={state_type}")
                    return True
                except Exception as e:
                    session.rollback()
                    print(f"[delete_user_state] PostgreSQLエラー: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
                finally:
                    session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.delete_user_state(user_id, state_type)
        except Exception as e:
            print(f"[delete_user_state] エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_cached_response(self, model: str, prompt_hash: str) -> Optional[str]:
        """キャッシュされたOpenAI APIレスポンスを取得"""
        try:
            if self.engine:
                session = self._get_session()
                try:
                    cache_key = f"{model}:{prompt_hash}"
                    # 有効期限内のキャッシュを取得
                    result = session.query(OpenAICacheModel).filter(
                        OpenAICacheModel.cache_key == cache_key,
                        OpenAICacheModel.expires_at > datetime.now()
                    ).first()

                    if result:
                        # ヒット数を更新
                        result.hit_count += 1
                        session.commit()
                        print(f"[get_cached_response] キャッシュヒット: key={cache_key}, hit_count={result.hit_count}")
                        return result.response
                    else:
                        print(f"[get_cached_response] キャッシュミス: key={cache_key}")
                        return None
                except Exception as e:
                    print(f"[get_cached_response] PostgreSQLエラー: {e}")
                    import traceback
                    traceback.print_exc()
                    return None
                finally:
                    session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_cached_response(model, prompt_hash)
        except Exception as e:
            print(f"[get_cached_response] エラー: {e}")
            import traceback
            traceback.print_exc()
            return None

    def set_cached_response(self, model: str, prompt_hash: str, prompt_preview: str, response: str, ttl_hours: int = 24) -> bool:
        """OpenAI APIレスポンスをキャッシュに保存"""
        try:
            if self.engine:
                session = self._get_session()
                try:
                    from datetime import timedelta
                    cache_key = f"{model}:{prompt_hash}"
                    expires_at = datetime.now() + timedelta(hours=ttl_hours)

                    # prompt_previewは最初の200文字のみ保存
                    preview = prompt_preview[:200] if prompt_preview else ""

                    # UPSERT操作（既存の場合は更新、存在しない場合は挿入）
                    existing = session.query(OpenAICacheModel).filter_by(cache_key=cache_key).first()
                    if existing:
                        existing.response = response
                        existing.expires_at = expires_at
                        existing.created_at = datetime.now()
                        existing.hit_count = 0
                    else:
                        new_cache = OpenAICacheModel(
                            cache_key=cache_key,
                            model=model,
                            prompt_hash=prompt_hash,
                            prompt_preview=preview,
                            response=response,
                            expires_at=expires_at,
                            hit_count=0
                        )
                        session.add(new_cache)

                    session.commit()
                    print(f"[set_cached_response] キャッシュ保存: key={cache_key}, ttl={ttl_hours}h, expires_at={expires_at}")
                    return True
                except Exception as e:
                    session.rollback()
                    print(f"[set_cached_response] PostgreSQLエラー: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
                finally:
                    session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.set_cached_response(model, prompt_hash, prompt_preview, response, ttl_hours)
        except Exception as e:
            print(f"[set_cached_response] エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

    def set_user_session(self, user_id: str, session_type: str, data: str, expires_hours: Optional[int] = None) -> bool:
        """
        ユーザーセッションデータを保存（UPSERT）

        Args:
            user_id: ユーザーID
            session_type: セッションタイプ ('selected_tasks', 'schedule_proposal', 'future_task_selection')
            data: セッションデータ（文字列またはJSON文字列）
            expires_hours: 有効期限（時間）、Noneの場合は無期限

        Returns:
            保存成功時True、失敗時False
        """
        try:
            if self.engine:
                session = self._get_session()
                try:
                    from datetime import timedelta

                    # 有効期限を計算
                    expires_at = None
                    if expires_hours is not None:
                        expires_at = datetime.now() + timedelta(hours=expires_hours)

                    # UPSERT: 既存レコードがあれば更新、なければ挿入
                    existing = session.query(UserSessionModel).filter_by(
                        user_id=user_id,
                        session_type=session_type
                    ).first()

                    if existing:
                        existing.data = data
                        existing.expires_at = expires_at
                        existing.created_at = datetime.now()
                    else:
                        new_session = UserSessionModel(
                            user_id=user_id,
                            session_type=session_type,
                            data=data,
                            expires_at=expires_at
                        )
                        session.add(new_session)

                    session.commit()
                    print(f"[set_user_session] セッション保存成功: user_id={user_id}, type={session_type}, データ長={len(data)}, 期限={expires_at}")
                    return True
                except Exception as e:
                    session.rollback()
                    print(f"[set_user_session] PostgreSQLエラー: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
                finally:
                    session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.set_user_session(user_id, session_type, data, expires_hours)
        except Exception as e:
            print(f"[set_user_session] エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

    def set_user_state(self, user_id: str, state_type: str, state_data: Optional[dict] = None) -> bool:
        """
        ユーザーの状態を設定（フラグファイルの代替）

        Args:
            user_id: ユーザーID
            state_type: 状態タイプ ('add_task_mode', 'urgent_task_mode', 'future_task_mode', 'delete_mode', 'task_select_mode' など)
            state_data: 状態に関連するデータ（オプション、辞書形式）

        Returns:
            bool: 成功時True
        """
        try:
            if self.engine:
                session = self._get_session()
                try:
                    import json
                    state_data_json = json.dumps(state_data) if state_data else None

                    # UPSERT: 既存レコードがあれば更新、なければ挿入
                    existing = session.query(UserStateModel).filter_by(
                        user_id=user_id,
                        state_type=state_type
                    ).first()

                    if existing:
                        existing.state_data = state_data_json
                        existing.updated_at = datetime.now()
                    else:
                        new_state = UserStateModel(
                            user_id=user_id,
                            state_type=state_type,
                            state_data=state_data_json
                        )
                        session.add(new_state)

                    session.commit()
                    print(f"[set_user_state] 状態設定: user_id={user_id}, state_type={state_type}")
                    return True
                except Exception as e:
                    session.rollback()
                    print(f"[set_user_state] PostgreSQLエラー: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
                finally:
                    session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.set_user_state(user_id, state_type, state_data)
        except Exception as e:
            print(f"[set_user_state] エラー: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_user_state(self, user_id: str, state_type: str) -> Optional[dict]:
        """
        ユーザーの状態を取得

        Args:
            user_id: ユーザーID
            state_type: 状態タイプ

        Returns:
            Optional[dict]: 状態データ（存在しない場合はNone）
        """
        try:
            if self.engine:
                session = self._get_session()
                try:
                    result = session.query(UserStateModel).filter_by(
                        user_id=user_id,
                        state_type=state_type
                    ).first()

                    if result and result.state_data:
                        import json
                        return json.loads(result.state_data)
                    return None
                except Exception as e:
                    print(f"[get_user_state] PostgreSQLエラー: {e}")
                    import traceback
                    traceback.print_exc()
                    return None
                finally:
                    session.close()
            else:
                # SQLiteフォールバック
                return self.sqlite_db.get_user_state(user_id, state_type)
        except Exception as e:
            print(f"[get_user_state] エラー: {e}")
            import traceback
            traceback.print_exc()
            return None

# グローバルデータベースインスタンス
postgres_db = None

def init_postgres_db():
    """PostgreSQLデータベースを初期化"""
    global postgres_db
    if postgres_db is None:
        postgres_db = PostgreSQLDatabase()
    return postgres_db
