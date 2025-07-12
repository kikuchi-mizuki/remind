import re
import uuid
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Optional
from models.database import db, Task
from collections import defaultdict

class TaskService:
    """タスク管理サービスクラス"""
    
    def __init__(self):
        self.db = db

    def parse_task_message(self, message: str) -> Dict:
        """LINEメッセージからタスク情報を解析"""
        print(f"[parse_task_message] 入力: '{message}'")
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
                print(f"[parse_task_message] 時間抽出: {duration_minutes} (pattern: {pattern})")
                # 時間の場合は分に変換
                if '時間' in pattern or 'hour' in pattern or 'h' in pattern:
                    duration_minutes *= 60
                    print(f"[parse_task_message] 時間→分変換: {duration_minutes}")
                message = re.sub(pattern, '', message)
                print(f"[parse_task_message] 時間除去後: '{message}'")
                break
        if not duration_minutes:
            print("[parse_task_message] 所要時間が見つかりませんでした")
            raise ValueError("所要時間が見つかりませんでした")
        # 頻度の判定
        repeat = False
        repeat_keywords = ['毎日', 'daily', '毎', '日々', 'ルーチン']
        for keyword in repeat_keywords:
            if keyword in message:
                repeat = True
                message = message.replace(keyword, '')
                print(f"[parse_task_message] 頻度抽出: {keyword} → repeat={repeat}")
                break
        # 期日の抽出
        due_date = None
        jst = pytz.timezone('Asia/Tokyo')
        today = datetime.now(jst)
        # 自然言語→日付変換辞書
        natural_date_map = {
            '明日': 1,
            '明後日': 2,
            '明々後日': 3,
            '明明後日': 3,  # 誤表記も吸収
        }
        for key, delta in natural_date_map.items():
            if key in message:
                due_date = (today + timedelta(days=delta)).strftime('%Y-%m-%d')
                message = message.replace(key, '')
                print(f"[parse_task_message] 期日抽出: {key} → {due_date}")
                break
        else:
            m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', message)
            if m:
                due_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                message = message.replace(m.group(0), '')
                print(f"[parse_task_message] 期日抽出: YYYY-MM-DD → {due_date}")
            else:
                m2 = re.search(r'(\d{1,2})[/-](\d{1,2})', message)
                if m2:
                    year = today.year
                    due_date = f"{year}-{int(m2.group(1)):02d}-{int(m2.group(2)):02d}"
                    message = message.replace(m2.group(0), '')
                    print(f"[parse_task_message] 期日抽出: M/D → {due_date}")
                else:
                    m3 = re.search(r'(\d{1,2})月(\d{1,2})日', message)
                    if m3:
                        year = today.year
                        due_date = f"{year}-{int(m3.group(1)):02d}-{int(m3.group(2)):02d}"
                        message = message.replace(m3.group(0), '')
                        print(f"[parse_task_message] 期日抽出: M月D日 → {due_date}")
        # AIで期日抽出（既存ロジックでdue_dateが取れなかった場合のみ）
        if not due_date:
            try:
                from services.openai_service import OpenAIService
                ai_service = OpenAIService()
                ai_due = ai_service.extract_due_date_from_text(message)
                if ai_due:
                    due_date = ai_due
                    print(f"[parse_task_message] AI日付抽出: {due_date}")
            except Exception as e:
                print(f"[parse_task_message] AI日付抽出エラー: {e}")
        # タスク名の抽出
        task_name = message
        print(f"[parse_task_message] タスク名抽出前: '{task_name}'")
        for pattern in time_patterns:
            task_name = re.sub(pattern, '', task_name)
        for keyword in repeat_keywords:
            task_name = task_name.replace(keyword, '')
        task_name = re.sub(r'[\s　]+', ' ', task_name).strip()
        print(f"[parse_task_message] タスク名抽出後: '{task_name}'")
        if not task_name:
            temp_message = message
            for pattern in time_patterns:
                temp_message = re.sub(pattern, '', temp_message)
            for keyword in repeat_keywords:
                temp_message = temp_message.replace(keyword, '')
            temp_message = re.sub(r'明日', '', temp_message)
            temp_message = re.sub(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', '', temp_message)
            temp_message = re.sub(r'(\d{1,2})[/-](\d{1,2})', '', temp_message)
            temp_message = re.sub(r'(\d{1,2})月(\d{1,2})日', '', temp_message)
            task_name = re.sub(r'[\s　]+', ' ', temp_message).strip()
            print(f"[parse_task_message] タスク名再抽出: '{task_name}'")
        if not task_name:
            print("[parse_task_message] タスク名が見つかりませんでした")
            raise ValueError("タスク名が見つかりませんでした")
        print(f"[parse_task_message] 結果: name='{task_name}', duration={duration_minutes}, repeat={repeat}, due_date={due_date}")
        return {
            'name': task_name,
            'duration_minutes': duration_minutes,
            'repeat': repeat,
            'due_date': due_date
        }

    def create_task(self, user_id: str, task_info: Dict) -> Task:
        """タスクを作成"""
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            user_id=user_id,
            name=task_info['name'],
            duration_minutes=task_info['duration_minutes'],
            repeat=task_info['repeat'],
            due_date=task_info.get('due_date')
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

    def format_task_list(self, tasks: List[Task], show_select_guide: bool = True, for_deletion: bool = False) -> str:
        """タスク一覧をフォーマット（期日付き・期日昇順・期日ごとにグループ化、M/D〆切形式）
        show_select_guide: 末尾の案内文を表示するかどうか
        for_deletion: タスク削除用の案内文を表示するかどうか
        """
        if not tasks:
            return "登録されているタスクはありません。"
        # 期日昇順でソート（未設定は最後）
        def due_date_key(task):
            return (task.due_date or '9999-12-31', task.name)
        tasks_sorted = sorted(tasks, key=due_date_key)
        # 期日ごとにグループ化
        from collections import defaultdict
        grouped = defaultdict(list)
        for task in tasks_sorted:
            grouped[task.due_date or '未設定'].append(task)
        formatted_list = "📋 タスク一覧\n＝＝＝＝＝＝\n"
        idx = 1
        jst = pytz.timezone('Asia/Tokyo')
        today = datetime.now(jst)
        today_str = today.strftime('%Y-%m-%d')
        for due, group in sorted(grouped.items()):
            if due == today_str:
                formatted_list += "📌 本日〆切\n"
            elif due != '未設定':
                try:
                    y, m, d = due.split('-')
                    due_str = f"{int(m)}/{int(d)}"
                except Exception:
                    due_str = due
                formatted_list += f"📌 {due_str}〆切\n"
            else:
                formatted_list += "📌 期日未設定\n"
            for task in group:
                # 期日未設定かつタスク名に「今日」など自然言語が含まれる場合は明示
                name = task.name
                if due == '未設定' and ('今日' in name or '明日' in name):
                    name += f" {due}"
                formatted_list += f"{idx}. {name} ({task.duration_minutes}分)\n"
                idx += 1
        formatted_list += "＝＝＝＝＝＝"
        if for_deletion:
            formatted_list += "\n削除するタスクを選んでください！\n例：１、３、５"
        elif show_select_guide:
            formatted_list += "\n今日やるタスクを選んでください！\n例：１、３、５"
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