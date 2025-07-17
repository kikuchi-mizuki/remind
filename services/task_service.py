import re
import uuid
from datetime import datetime, timedelta
import pytz
from typing import List, Dict, Optional
from models.database import db, Task
from collections import defaultdict

class TaskService:
    """タスク管理サービスクラス"""
    
    def __init__(self, db_instance=None):
        from models.database import db
        self.db = db_instance or db

    def parse_task_message(self, message: str) -> Dict:
        """LINEメッセージからタスク情報を解析"""
        print(f"[parse_task_message] 入力: '{message}'")
        
        # 時間パターンの定義
        complex_time_patterns = [
            r'(\d+)\s*時間\s*半',  # 1時間半
            r'(\d+)\s*時間\s*(\d+)\s*分',  # 1時間30分
            r'(\d+)\s*hour\s*(\d+)\s*min',  # 1hour 30min
            r'(\d+)\s*h\s*(\d+)\s*m',  # 1h 30m
        ]
        
        simple_time_patterns = [
            r'(\d+)\s*分',
            r'(\d+)\s*時間',
            r'(\d+)\s*min',
            r'(\d+)\s*hour',
            r'(\d+)\s*h',
            r'(\d+)\s*m'
        ]
        
        # 時間の抽出（複合時間表現に対応）
        duration_minutes = None
        
        # 複合時間表現を先にチェック
        for pattern in complex_time_patterns:
            match = re.search(pattern, message)
            if match:
                if '半' in pattern:
                    # 1時間半の場合
                    hours = int(match.group(1))
                    duration_minutes = hours * 60 + 30
                    print(f"[parse_task_message] 複合時間抽出: {hours}時間半 → {duration_minutes}分")
                else:
                    # 1時間30分の場合
                    hours = int(match.group(1))
                    minutes = int(match.group(2))
                    duration_minutes = hours * 60 + minutes
                    print(f"[parse_task_message] 複合時間抽出: {hours}時間{minutes}分 → {duration_minutes}分")
                message = re.sub(pattern, '', message)
                print(f"[parse_task_message] 複合時間除去後: '{message}'")
                break
        
        # 単純な時間表現のパターン
        if not duration_minutes:
            for pattern in simple_time_patterns:
                match = re.search(pattern, message)
                if match:
                    duration_minutes = int(match.group(1))
                    print(f"[parse_task_message] 単純時間抽出: {duration_minutes} (pattern: {pattern})")
                    # 時間の場合は分に変換
                    if '時間' in pattern or 'hour' in pattern or 'h' in pattern:
                        duration_minutes *= 60
                        print(f"[parse_task_message] 時間→分変換: {duration_minutes}")
                    message = re.sub(pattern, '', message)
                    print(f"[parse_task_message] 単純時間除去後: '{message}'")
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
        ai_date_keywords = ['今日', '明日', '明後日', '今週', '来週', '今週中', '来週中', '今週末', '来週末', '今月末', '来月', '来月末']
        used_date_keywords = []  # 使用された日付キーワードを記録
        original_message = message  # 元のメッセージを保存
        
        if not due_date:
            try:
                from services.openai_service import OpenAIService
                ai_service = OpenAIService()
                ai_due = ai_service.extract_due_date_from_text(message)
                if ai_due:
                    due_date = ai_due
                    print(f"[parse_task_message] AI日付抽出: {due_date}")
                    # AI抽出時に使用されたキーワードを特定して除去
                    for key in ai_date_keywords:
                        if key in original_message:
                            used_date_keywords.append(key)
                            original_message = original_message.replace(key, '')
            except Exception as e:
                print(f"[parse_task_message] AI日付抽出エラー: {e}")
        else:
            # 既存ロジックでdue_dateが取れた場合も使用されたキーワードを除去
            for key in ai_date_keywords:
                if key in original_message:
                    used_date_keywords.append(key)
                    original_message = original_message.replace(key, '')
        # タスク名の抽出
        task_name = original_message
        print(f"[parse_task_message] タスク名抽出前: '{task_name}'")
        
        # 使用された日付キーワードを除去
        for keyword in used_date_keywords:
            task_name = task_name.replace(keyword, '')
        
        for pattern in simple_time_patterns:
            task_name = re.sub(pattern, '', task_name)
        for keyword in repeat_keywords:
            task_name = task_name.replace(keyword, '')
        task_name = re.sub(r'[\s　]+', ' ', task_name).strip()
        print(f"[parse_task_message] タスク名抽出後: '{task_name}'")
        
        if not task_name:
            temp_message = original_message
            # 使用された日付キーワードを除去
            for keyword in used_date_keywords:
                temp_message = temp_message.replace(keyword, '')
            
            for pattern in simple_time_patterns:
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
        # 優先度の判定（AIを使用）
        priority = self._determine_priority(task_name, due_date or "", duration_minutes)
        
        print(f"[parse_task_message] 結果: name='{task_name}', duration={duration_minutes}, repeat={repeat}, due_date={due_date}, priority={priority}")
        return {
            'name': task_name,
            'duration_minutes': duration_minutes,
            'repeat': repeat,
            'due_date': due_date,
            'priority': priority
        }

    def _determine_priority(self, task_name: str, due_date: str, duration_minutes: int) -> str:
        """タスクの優先度を判定（AIを使用）"""
        try:
            from services.openai_service import OpenAIService
            ai_service = OpenAIService()
            
            # 現在の日付を取得
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst)
            today_str = today.strftime('%Y-%m-%d')
            
            # 期日までの日数を計算
            if due_date:
                due_date_obj = datetime.strptime(due_date, '%Y-%m-%d')
                days_until_due = (due_date_obj - today).days
            else:
                days_until_due = 7  # 期日がない場合は7日後と仮定
            
            # AIに優先度判定を依頼
            prompt = f"""
            以下のタスクの緊急度と重要度を判定し、適切な優先度カテゴリを選択してください。

            タスク名: {task_name}
            所要時間: {duration_minutes}分
            期日: {due_date or '未設定'}
            期日までの日数: {days_until_due}日

            優先度カテゴリ:
            - urgent_important: 緊急かつ重要（最優先で処理すべき）
            - not_urgent_important: 緊急ではないが重要（計画的に処理すべき）
            - urgent_not_important: 緊急だが重要ではない（可能な限り委譲・簡略化すべき）
            - normal: 緊急でも重要でもない（通常の優先度）

            判定基準:
            - 緊急度: 期日が近い、即座の対応が必要
            - 重要度: 長期的な価値、目標達成への影響度

            回答は上記のカテゴリ名のみを返してください。
            """
            
            priority = ai_service.get_priority_classification(prompt)
            
            # 有効な優先度かチェック
            valid_priorities = ["urgent_important", "not_urgent_important", "urgent_not_important", "normal"]
            if priority not in valid_priorities:
                priority = "normal"  # デフォルト
            
            print(f"[_determine_priority] AI判定結果: {priority}")
            return priority
            
        except Exception as e:
            print(f"[_determine_priority] AI判定エラー: {e}")
            # エラーの場合は簡易判定
            return self._simple_priority_determination(task_name, due_date, duration_minutes)

    def _simple_priority_determination(self, task_name: str, due_date: str, duration_minutes: int) -> str:
        """簡易的な優先度判定（AIが使えない場合のフォールバック）"""
        # 緊急度のキーワード
        urgent_keywords = ['緊急', '急ぎ', 'すぐ', '今すぐ', '至急', 'ASAP', 'urgent', 'immediate', 'deadline', '締切']
        # 重要度のキーワード
        important_keywords = ['重要', '大切', '必須', '必要', 'essential', 'important', 'critical', 'key', '主要']
        
        is_urgent = any(keyword in task_name for keyword in urgent_keywords)
        is_important = any(keyword in task_name for keyword in important_keywords)
        
        # 期日が今日または明日の場合は緊急と判定
        if due_date:
            jst = pytz.timezone('Asia/Tokyo')
            today = datetime.now(jst)
            today_str = today.strftime('%Y-%m-%d')
            tomorrow_str = (today + timedelta(days=1)).strftime('%Y-%m-%d')
            
            if due_date in [today_str, tomorrow_str]:
                is_urgent = True
        
        # 優先度判定
        if is_urgent and is_important:
            return "urgent_important"
        elif not is_urgent and is_important:
            return "not_urgent_important"
        elif is_urgent and not is_important:
            return "urgent_not_important"
        else:
            return "normal"

    def create_task(self, user_id: str, task_info: Dict) -> Task:
        """タスクを作成"""
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            user_id=user_id,
            name=task_info['name'],
            duration_minutes=task_info['duration_minutes'],
            repeat=task_info['repeat'],
            due_date=task_info.get('due_date'),
            priority=task_info.get('priority', 'normal')
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
        """タスク一覧をフォーマット（優先度・期日付き・期日昇順・期日ごとにグループ化、M/D〆切形式）
        show_select_guide: 末尾の案内文を表示するかどうか
        for_deletion: タスク削除用の案内文を表示するかどうか
        """
        if not tasks:
            return "登録されているタスクはありません。"
        
        # 優先度と期日でソート
        def sort_key(task):
            priority_order = {
                "urgent_important": 0,
                "not_urgent_important": 1,
                "urgent_not_important": 2,
                "normal": 3
            }
            priority_score = priority_order.get(task.priority, 3)
            due_date = task.due_date or '9999-12-31'
            return (priority_score, due_date, task.name)
        
        tasks_sorted = sorted(tasks, key=sort_key)
        
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
                # 優先度アイコン
                priority_icon = {
                    "urgent_important": "🚨",
                    "not_urgent_important": "⭐",
                    "urgent_not_important": "⚡",
                    "normal": "📝"
                }.get(task.priority, "📝")
                
                # 期日未設定かつタスク名に「今日」など自然言語が含まれる場合は明示
                name = task.name
                if due == '未設定' and ('今日' in name or '明日' in name):
                    name += f" {due}"
                
                formatted_list += f"{idx}. {priority_icon} {name} ({task.duration_minutes}分)\n"
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