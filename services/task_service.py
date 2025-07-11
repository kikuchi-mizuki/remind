import re
import uuid
from datetime import datetime
from typing import List, Dict, Optional
from models.database import db, Task

class TaskService:
    """タスク管理サービスクラス"""
    
    def __init__(self):
        self.db = db

    def parse_task_message(self, message: str) -> Dict:
        """LINEメッセージからタスク情報を解析"""
        # 時間の抽出（分、時間、min、hour、h、m）
        time_patterns = [
            r'(\d+)\s*分',
            r'(\d+)\s*時間',
            r'(\d+)\s*min',
            r'(\d+)\s*hour',
            r'(\d+)\s*h',
            r'(\d+)\s*m'
        ]
        
        duration_minutes = None
        for pattern in time_patterns:
            match = re.search(pattern, message)
            if match:
                duration_minutes = int(match.group(1))
                # 時間の場合は分に変換
                if '時間' in pattern or 'hour' in pattern or 'h' in pattern:
                    duration_minutes *= 60
                break
        
        if not duration_minutes:
            raise ValueError("所要時間が見つかりませんでした")
        
        # 頻度の判定
        repeat = False
        repeat_keywords = ['毎日', 'daily', '毎', '日々', 'ルーチン']
        for keyword in repeat_keywords:
            if keyword in message:
                repeat = True
                break
        
        # タスク名の抽出（時間と頻度の部分を除く）
        task_name = message
        for pattern in time_patterns:
            task_name = re.sub(pattern, '', task_name)
        
        for keyword in repeat_keywords:
            task_name = task_name.replace(keyword, '')
        
        # 余分な空白を削除
        task_name = re.sub(r'\s+', ' ', task_name).strip()
        
        if not task_name:
            raise ValueError("タスク名が見つかりませんでした")
        
        return {
            'name': task_name,
            'duration_minutes': duration_minutes,
            'repeat': repeat
        }

    def create_task(self, user_id: str, task_info: Dict) -> Task:
        """タスクを作成"""
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            user_id=user_id,
            name=task_info['name'],
            duration_minutes=task_info['duration_minutes'],
            repeat=task_info['repeat']
        )
        
        if self.db.create_task(task):
            return task
        else:
            raise Exception("タスクの作成に失敗しました")

    def get_user_tasks(self, user_id: str, status: str = "active") -> List[Task]:
        """ユーザーのタスク一覧を取得"""
        return self.db.get_user_tasks(user_id, status)

    def get_selected_tasks(self, user_id: str, selection_message: str) -> List[Task]:
        """選択されたタスクを取得"""
        # 数字を抽出
        numbers = re.findall(r'\d+', selection_message)
        if not numbers:
            return []
        
        # 全タスクを取得
        all_tasks = self.get_user_tasks(user_id)
        
        selected_tasks = []
        for number in numbers:
            index = int(number) - 1  # 1ベースのインデックスを0ベースに変換
            if 0 <= index < len(all_tasks):
                selected_tasks.append(all_tasks[index])
        
        return selected_tasks

    def save_schedule_proposal(self, user_id: str, proposal: str) -> bool:
        """スケジュール提案を保存"""
        proposal_data = {
            'proposal_text': proposal,
            'created_at': datetime.now().isoformat()
        }
        return self.db.save_schedule_proposal(user_id, proposal_data)

    def get_schedule_proposal(self, user_id: str) -> Optional[Dict]:
        """スケジュール提案を取得"""
        return self.db.get_schedule_proposal(user_id)

    def parse_modification_message(self, message: str) -> Dict:
        """スケジュール修正メッセージを解析"""
        # タスク名の抽出
        task_name = None
        time_modification = None
        
        # 「〇〇を〇時に変更」のパターン
        pattern = r'(.+?)を(\d+)時に変更'
        match = re.search(pattern, message)
        if match:
            task_name = match.group(1).strip()
            time_modification = f"{match.group(2)}:00"
        
        # 「〇〇を〇時〇分に変更」のパターン
        pattern2 = r'(.+?)を(\d+)時(\d+)分に変更'
        match2 = re.search(pattern2, message)
        if match2:
            task_name = match2.group(1).strip()
            time_modification = f"{match2.group(2)}:{match2.group(3)}"
        
        if not task_name or not time_modification:
            raise ValueError("修正内容を理解できませんでした")
        
        return {
            'task_name': task_name,
            'new_time': time_modification
        }

    def format_task_list(self, tasks: List[Task]) -> str:
        """タスク一覧をフォーマット"""
        if not tasks:
            return "登録されているタスクはありません。"
        
        formatted_list = "📋 タスク一覧\n\n"
        for i, task in enumerate(tasks, 1):
            repeat_text = "🔄 毎日" if task.repeat else "📌 単発"
            formatted_list += f"{i}. {task.name} ({task.duration_minutes}分) {repeat_text}\n"
        
        formatted_list += "\n今日やるタスクの番号を選んでください。\n例: 1 3 5"
        
        return formatted_list

    def get_daily_tasks(self, user_id: str) -> List[Task]:
        """毎日のタスクを取得"""
        all_tasks = self.get_user_tasks(user_id)
        return [task for task in all_tasks if task.repeat]

    def archive_task(self, task_id: str) -> bool:
        """タスクをアーカイブ"""
        return self.db.update_task_status(task_id, "archived")

    def reactivate_task(self, task_id: str) -> bool:
        """タスクを再アクティブ化"""
        return self.db.update_task_status(task_id, "active") 