import os
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from openai import OpenAI
from models.database import Task

class OpenAIService:
    """OpenAI APIを使用したスケジュール提案サービスクラス"""
    
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.model = "gpt-4o-mini"  # または "gpt-4o"

    def generate_schedule_proposal(self, tasks: List[Task], free_times: List[dict] = []) -> str:
        """選択されたタスクと空き時間からスケジュール提案を生成"""
        if not tasks:
            return "タスクが選択されていません。"
        
        # タスク情報を整理
        task_info = []
        total_duration = 0
        for task in tasks:
            task_info.append({
                'name': task.name,
                'duration': task.duration_minutes,
                'repeat': task.repeat
            })
            total_duration += task.duration_minutes
        
        # 空き時間情報を整形
        free_time_str = ""
        if free_times:
            free_time_str = "\n空き時間リスト:\n"
            for ft in free_times:
                start = ft['start'].strftime('%H:%M')
                end = ft['end'].strftime('%H:%M')
                free_time_str += f"- {start}〜{end} ({ft['duration_minutes']}分)\n"
        
        # 現在日時（日本時間）を取得
        from datetime import datetime, timedelta, timezone
        import pytz
        jst = pytz.timezone('Asia/Tokyo')
        now_jst = datetime.now(jst)
        now_str = now_jst.strftime("%Y-%m-%dT%H:%M:%S%z")
        now_str = now_str[:-2] + ":" + now_str[-2:]  # +0900 → +09:00 形式に
        
        # プロンプトを作成
        prompt = (
            f"現在の日時（日本時間）は {now_str} です。\n"
            "この日時は、すべての自然言語の解釈において常に絶対的な基準としてください。\n"
            "会話の流れや前回の入力に引きずられることなく、毎回この現在日時を最優先にしてください。\n"
        )
        prompt += self._create_schedule_prompt(task_info, total_duration, free_time_str)
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたは効率的なスケジュール管理の専門家です。与えられたタスクと空き時間をもとに、生産性を最大化するスケジュールを提案してください。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return self._generate_fallback_schedule(tasks) or ""

    def generate_modified_schedule(self, user_id: str, modification: Dict) -> str:
        """修正されたスケジュールを生成"""
        prompt = f"""
以下の修正要求に基づいて、新しいスケジュールを提案してください：

修正内容：
- タスク名: {modification.get('task_name', '')}
- 新しい時間: {modification.get('new_time', '')}

既存のスケジュールを考慮して、最適な時間に再配置してください。
他のタスクとの重複を避け、効率的な順序で配置してください。

提案フォーマット：
時間 タスク名 (所要時間)
例：
09:00 筋トレ (20分)
10:30 買い物 (30分)
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたはスケジュール調整の専門家です。修正要求に基づいて最適なスケジュールを提案してください。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=500,
                temperature=0.7
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return "スケジュールの修正に失敗しました。"

    def _create_schedule_prompt(self, task_info: List[Dict], total_duration: int, free_time_str: str = "") -> str:
        """スケジュール提案用のプロンプトを作成（空き時間対応・表記厳密化）"""
        task_list = "\n".join([
            f"- {task['name']} ({task['duration']}分)" for task in task_info
        ])
        return f"""
以下のタスクを今日のスケジュールに最適に配置してください。

【要件】
- 必ずカレンダーの空き時間リスト内にのみタスクを割り当ててください。
- タスク一覧に含まれていないものは絶対に提案しないでください。
- 必ず全てのタスクを使い切る必要はありません（空き時間に収まる範囲で）。
- 出力は必ず下記のフォーマット例に厳密に従ってください。
- 最後に必ず「✅理由・まとめ」を記載してください。

【タスク一覧】
{task_list}

総所要時間: {total_duration}分
{free_time_str}

【表記フォーマット例】
🗓️【本日のスケジュール提案】

━━━━━━━━━━━━━━
🕒 08:00〜08:30
📝 資料作成（30分）
━━━━━━━━━━━━━━
🕒 09:00〜09:30
📝 別のタスク（30分）
━━━━━━━━━━━━━━

✅理由・まとめ
・なぜこの順序・割り当てにしたかを簡潔に説明してください。

このスケジュールでよろしければ「承認する」、修正したい場合は「修正する」と返信してください。
"""

    def _generate_fallback_schedule(self, tasks: List[Task]) -> str:
        """OpenAI APIが利用できない場合のフォールバックスケジュール"""
        schedule = "📅 スケジュール提案\n\n"
        
        current_time = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        
        for i, task in enumerate(tasks):
            # 30分のマージンを追加
            if i > 0:
                current_time += timedelta(minutes=30)
            
            schedule += f"{current_time.strftime('%H:%M')} {task.name} ({task.duration_minutes}分)\n"
            
            # タスク時間を加算
            current_time += timedelta(minutes=task.duration_minutes)
        
        schedule += "\n承認する場合は「承認」と返信してください。"
        return schedule

    def analyze_task_priority(self, task_name: str, duration: int) -> str:
        """タスクの優先度を分析"""
        prompt = f"""
以下のタスクの優先度を分析してください：

タスク名: {task_name}
所要時間: {duration}分

優先度の分類：
- high: 重要で緊急なタスク
- medium: 重要だが緊急ではないタスク
- low: 重要でも緊急でもないタスク

優先度のみを返してください（high/medium/low）
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたはタスク管理の専門家です。タスクの優先度を適切に判断してください。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=10,
                temperature=0.3
            )
            return (response.choices[0].message.content or "").strip().lower()
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return "medium"  # デフォルトは中優先度

    def suggest_task_optimization(self, tasks: List[Task]) -> str:
        """タスクの最適化提案を生成"""
        task_list = "\n".join([
            f"- {task.name} ({task.duration_minutes}分)"
            for task in tasks
        ])
        
        prompt = f"""
以下のタスクリストを分析し、効率化の提案をしてください：

タスク一覧：
{task_list}

以下の観点で提案してください：
1. タスクの順序の最適化
2. 時間短縮の可能性
3. バッチ処理できるタスク
4. 削除・委譲できるタスク

具体的で実践的な提案をお願いします。
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたは生産性向上の専門家です。タスクの効率化について具体的な提案をしてください。"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=500,
                temperature=0.7
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return "タスクの最適化提案を生成できませんでした。" 