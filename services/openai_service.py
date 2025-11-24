import os
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from openai import OpenAI
from models.database import Task
import hashlib
import json

class OpenAIService:
    """OpenAI APIを使用したスケジュール提案サービスクラス"""

    def __init__(self, db=None, enable_cache: bool = True, cache_ttl_hours: int = 24):
        self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        self.model = "gpt-4o-mini"  # または "gpt-4o"
        self.db = db
        self.enable_cache = enable_cache
        self.cache_ttl_hours = cache_ttl_hours

    def generate_schedule_proposal(
        self,
        tasks: List[Task],
        free_times: List[dict] = [],
        week_info: str = "",
        base_date: Optional[datetime] = None
    ) -> str:
        """選択されたタスクと空き時間からスケジュール提案を生成"""
        if not tasks:
            return "タスクが選択されていません。"
        
        # デバッグ情報を追加
        print(f"[DEBUG] OpenAIサービス: 受信したタスク数: {len(tasks)}")
        print(f"[DEBUG] OpenAIサービス: 受信したタスク詳細: {[(i+1, task.name, task.duration_minutes) for i, task in enumerate(tasks)]}")
        
        # タスク情報を整理（優先度付き）
        task_info = []
        total_duration = 0
        for task in tasks:
            task_info.append({
                'name': task.name,
                'duration': task.duration_minutes,
                'repeat': task.repeat,
                'priority': task.priority
            })
            total_duration += task.duration_minutes
        
        # 空き時間情報を整形
        free_time_str = ""
        if free_times:
            free_time_str = "\n空き時間リスト:\n"
            for ft in free_times:
                start = ft['start'].strftime('%H:%M')
                end = ft['end'].strftime('%H:%M')
                # 日付情報がある場合は表示（来週のスケジュール提案の場合）
                if 'date' in ft:
                    date_str = ft['date'].strftime('%m/%d')
                    weekday_names = ['月', '火', '水', '木', '金', '土', '日']
                    weekday = weekday_names[ft['date'].weekday()]
                    free_time_str += f"- {date_str}({weekday}) {start}〜{end} ({ft['duration_minutes']}分)\n"
                else:
                    free_time_str += f"- {start}〜{end} ({ft['duration_minutes']}分)\n"
        
        # 現在日時（日本時間）を取得
        from datetime import datetime, timedelta, timezone
        import pytz
        jst = pytz.timezone('Asia/Tokyo')
        now_jst = datetime.now(jst)
        now_str = now_jst.strftime("%Y-%m-%dT%H:%M:%S%z")
        now_str = now_str[:-2] + ":" + now_str[-2:]  # +0900 → +09:00 形式に
        
        # デバッグ情報を追加
        print(f"[DEBUG] OpenAIサービス: プロンプト作成前のタスク情報: {task_info}")
        
        # プロンプトを作成
        prompt = (
            f"現在の日時（日本時間）は {now_str} です。\n"
            "この日時は、すべての自然言語の解釈において常に絶対的な基準としてください。\n"
            "会話の流れや前回の入力に引きずられることなく、毎回この現在日時を最優先にしてください。\n"
        )
        prompt += self._create_schedule_prompt(task_info, total_duration, free_time_str, week_info, now_str)
        
        # デバッグ情報を追加
        print(f"[DEBUG] OpenAIサービス: 作成されたプロンプト: {prompt[:500]}...")
        
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
            raw = response.choices[0].message.content or ""
            proposal = self._format_schedule_output(raw)
            if self._needs_fallback(proposal, tasks):
                print("[DEBUG] フォールバック判定: AI出力が要件を満たしていません。決定的スケジュールを生成します。")
                fallback = self._build_deterministic_schedule(tasks, free_times, week_info, base_date)
                if fallback:
                    return fallback
            return proposal
        except Exception as e:
            print(f"OpenAI API error: {e}")
            fallback = self._build_deterministic_schedule(tasks, free_times, week_info, base_date)
            if fallback:
                return fallback
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

    def _create_schedule_prompt(self, task_info: List[Dict], total_duration: int, free_time_str: str = "", week_info: str = "", now_str: str = "") -> str:
        """スケジュール提案用のプロンプトを作成（空き時間対応・表記厳密化・重複禁止・本文必須・優先度考慮）"""
        # 優先度に応じたアイコンを追加（🔥を削除、⭐️を⭐に変更）
        priority_icons = {
            "urgent_important": "🚨",
            "not_urgent_important": "⭐",
            "urgent_not_important": "⚡",
            "normal": "📝"
        }
        
        task_list = "\n".join([
            f"- {priority_icons.get(task.get('priority', 'normal'), '📝')} {task['name']} ({task['duration']}分)" for task in task_info
        ])
        
        # ヘッダーを動的に設定
        if week_info:
            header = f"以下のタスクを{week_info}に最適に配置してください。"
        else:
            header = "以下のタスクを今日のスケジュールに最適に配置してください。"
        
        return f"""
{header}

【要件】
- 必ずカレンダーの空き時間リスト内にのみタスクを割り当ててください。
- タスク一覧に含まれていないものは絶対に提案しないでください。
- 必ず全てのタスクを使い切る必要はありません（空き時間に収まる範囲で）。
- 出力は必ず下記のフォーマット例に厳密に従ってください。
- 各タスクには必ず「日付（M/D）・曜日・時間帯（開始時刻・終了時刻）」を明記してください。
- 日付と曜日の計算は必ず現在日時（{now_str}）を基準に正確に行ってください。
- 7月21日は月曜日、7月22日は火曜日、7月23日は水曜日、7月24日は木曜日、7月25日は金曜日、7月26日は土曜日、7月27日は日曜日です。
- スケジュール本文（🕒や📝の行）は必ず1つ以上出力してください。本文が1つもない場合は「エラー: スケジュール本文が生成できませんでした」とだけ出力してください。
- 最後に必ず「✅理由・まとめ」を記載してください。
- 「このスケジュールでよろしければ…」などの案内文や「理由・まとめ」は1回だけ記載し、繰り返さないでください。
- 案内文や理由・まとめ以外の余計な文章は出力しないでください。
- 絵文字の使用について：
  * 優先度アイコンは必ず1つだけ使用してください（⭐️⭐️ではなく⭐のみ）
  * 複数の⭐️（⭐️⭐️など）は絶対に使用しないでください
  * 🔥絵文字は使用しないでください
  * 各タスクの優先度アイコンは最大1つまでです
- 優先度を考慮してスケジュールを組んでください：
  * 🚨（緊急かつ重要）: 最優先で早い時間に配置
  * ⭐（重要だが緊急ではない）: 計画的に配置
  * ⚡（緊急だが重要ではない）: 可能な限り委譲・簡略化
  * 📝（通常）: 通常の優先度

【タスク一覧】
{task_list}

総所要時間: {total_duration}分
{free_time_str}

【表記フォーマット例】
{week_info and '🗓️【来週のスケジュール提案】' or '🗓️【本日のスケジュール提案】'}

━━━━━━━━━━━━━━
{week_info and '7/22(月) 08:00〜10:00' or '08:00〜10:00'}
⭐ 新規事業計画（120分）
━━━━━━━━━━━━━━
{week_info and '7/24(水) 14:00〜15:30' or '14:00〜15:30'}
⭐ 営業資料の見直し（90分）
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

    def get_priority_classification(self, prompt: str) -> str:
        """タスクの優先度を分類"""
        try:
            system_content = "あなたはタスク管理の専門家です。与えられたタスクの緊急度と重要度を分析し、適切な優先度カテゴリを選択してください。"
            result = self._get_cached_or_call_api(
                prompt=prompt,
                system_content=system_content,
                max_tokens=50,
                temperature=0.3
            )
            return result.strip() if result else "normal"
        except Exception as e:
            print(f"OpenAI API error in priority classification: {e}")
            return "normal"

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
            system_content = "あなたはタスク管理の専門家です。タスクの優先度を適切に判断してください。"
            result = self._get_cached_or_call_api(
                prompt=prompt,
                system_content=system_content,
                max_tokens=10,
                temperature=0.3
            )
            return result.strip().lower() if result else "medium"
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

    def _format_schedule_output(self, raw: str) -> str:
        """スケジュール提案の出力を指定フォーマットに整形・補正（重複案内文・理由・まとめ除去、本文が空の場合の補正）"""
        import re
        print('AI raw output:', raw)  # デバッグ用
        lines = [line.strip() for line in raw.split('\n') if line.strip()]
        result = []
        seen_guide = False
        seen_reason = False
        # 1. ヘッダー
        if not any('スケジュール提案' in l for l in lines):
            result.append('🗓️【本日のスケジュール提案】')
        # 2. 本文（区切り線・時刻・タスク）
        in_reason = False
        for i, line in enumerate(lines):
            # 案内文重複除去
            if 'このスケジュールでよろしければ' in line or '修正する' in line:
                if not seen_guide:
                    seen_guide = True
                    continue  # 案内文は最後に1回だけ付与
                else:
                    continue
            # 理由・まとめ開始検出
            if re.search(r'(理由|まとめ)', line) and not in_reason:
                if not seen_reason:
                    in_reason = True
                    seen_reason = True
                    # 区切り線が直前にない場合は追加
                    if result and not re.match(r'^[━―ー=＿_]+$', result[-1]):
                        result.append('━━━━━━━━━━━━━━')
                    result.append('✅理由・まとめ')
                continue
            if in_reason:
                # 理由・まとめ本文
                if line not in result:
                    result.append(line)
                continue
            # 区切り線補正
            if re.match(r'^[━―ー=＿_]+$', line):
                if result and re.match(r'^[━―ー=＿_]+$', result[-1]):
                    continue  # 連続区切り線は1つに
                result.append('━━━━━━━━━━━━━━')
                continue
            # 時刻・タスク行補正（🕒/📝がなくても柔軟に拾う）
            m = re.match(r'([0-2]?\d)[:：](\d{2})[〜~\-ー―‐–—−﹣－:：]([0-2]?\d)[:：](\d{2})', line)
            if m:
                result.append(f'🕒 {m.group(1).zfill(2)}:{m.group(2)}〜{m.group(3).zfill(2)}:{m.group(4)}')
                continue
            m2 = re.match(r'(.+)[（(](\d+)分[)）]', line)
            if m2:
                # 既に📝が含まれている場合は追加しない
                task_name = m2.group(1).strip()
                if not task_name.startswith('📝'):
                    result.append(f'📝 {task_name}（{m2.group(2)}分）')
                else:
                    result.append(f'{task_name}（{m2.group(2)}分）')
                continue
            # 時刻＋タスク名パターン（例: 08:00-08:30 資料作成）
            m3 = re.match(r'(\d{1,2}):(\d{2})[〜~\-ー―‐–—−﹣－:：](\d{1,2}):(\d{2})\s+(.+)', line)
            if m3:
                result.append(f'🕒 {m3.group(1).zfill(2)}:{m3.group(2)}〜{m3.group(3).zfill(2)}:{m3.group(4)}')
                # 既に📝が含まれている場合は追加しない
                task_name = m3.group(5).strip()
                if not task_name.startswith('📝'):
                    result.append(f'📝 {task_name}')
                else:
                    result.append(f'{task_name}')
                continue
            # 🔥を除去し、⭐️を⭐に変更（複数の⭐️も対応）
            line = line.replace('🔥', '')
            # 複数の⭐️を⭐に統一（正規表現で一度に処理）
            import re
            line = re.sub(r'⭐️+', '⭐', line)
            result.append(line)
        # 3. 理由・まとめがなければ追加
        if not seen_reason:
            result.append('━━━━━━━━━━━━━━')
            result.append('✅理由・まとめ')
            result.append('・なぜこの順序・割り当てにしたかを簡潔に説明してください。')
        # 4. 本文が空 or 時間帯が1つもない場合の補正（ダミー挿入を削除）
        # has_time = any(l.startswith('🕒') for l in result)
        # if not has_time:
        #     # ダミーのスケジュール本文を自動挿入
        #     result.insert(1, '━━━━━━━━━━━━━━')
        #     result.insert(2, '🕒 09:00〜09:30')
        #     result.insert(3, '📝 タスク（30分）')
        #     result.insert(4, '━━━━━━━━━━━━━━')
        # 5. 最後に案内文を1回だけ
        result.append('このスケジュールでよろしければ「承認する」、修正したい場合は「修正する」と返信してください。')
        return '\n'.join(result) 

    def _needs_fallback(self, proposal: str, tasks: List[Task]) -> bool:
        """AI提案の妥当性を検証し、不足していればフォールバックを要求"""
        lines = proposal.splitlines()
        has_time_line = any(line.startswith('🕒') for line in lines)
        has_task_line = any(line.startswith('📝') for line in lines)
        contains_unassigned = any('未割り当てタスク' in line for line in lines)
        if not has_time_line or not has_task_line:
            print(f"[DEBUG] フォールバック理由: 時刻行有={has_time_line}, タスク行有={has_task_line}")
            return True
        if contains_unassigned and not has_task_line:
            print("[DEBUG] フォールバック理由: 未割り当てセクションのみ検出")
            return True
        normalized_proposal = proposal.replace(' ', '')
        for task in tasks:
            if task.name and task.name.replace(' ', '') not in normalized_proposal:
                print(f"[DEBUG] フォールバック理由: タスク '{task.name}' が提案に含まれていません")
                return True
        if 'エラー' in proposal:
            print("[DEBUG] フォールバック理由: エラーメッセージを検出")
            return True
        return False

    def _build_deterministic_schedule(
        self,
        tasks: List[Task],
        free_times: List[dict],
        week_info: str,
        base_date: Optional[datetime]
    ) -> str:
        """空き時間情報を用いた決定的なスケジュール生成（フォールバック用）"""
        import pytz
        from collections import deque

        if not free_times:
            free_times = self._generate_default_free_times(week_info, base_date)
        if not free_times:
            print("[DEBUG] 決定的スケジュール生成中止: 空き時間情報がありません。")
            return ""

        jst = pytz.timezone('Asia/Tokyo')
        slots = []
        for ft in free_times:
            start = ft.get('start')
            end = ft.get('end')
            if not start or not end:
                print(f"[DEBUG] 空き時間データ不正: start={start}, end={end}")
                continue
            if start.tzinfo is None:
                start = jst.localize(start)
            else:
                start = start.astimezone(jst)
            if end.tzinfo is None:
                end = jst.localize(end)
            else:
                end = end.astimezone(jst)
            if end <= start:
                print(f"[DEBUG] 空き時間スキップ: end<=start (start={start}, end={end})")
                continue
            slots.append([start, end])

        if not slots:
            print("[DEBUG] 決定的スケジュール生成中止: 有効な空き時間スロットがありません。")
            return ""

        slots.sort(key=lambda pair: pair[0])
        remaining_tasks = deque(tasks)
        assignments = []
        unassigned = []

        print(f"[DEBUG] 決定的スケジュール割当開始: タスク数={len(remaining_tasks)}, スロット数={len(slots)}")
        while remaining_tasks:
            task = remaining_tasks.popleft()
            duration = max(task.duration_minutes, 0)
            assigned = False
            for slot in slots:
                slot_start, slot_end = slot
                available = int((slot_end - slot_start).total_seconds() / 60)
                print(f"[DEBUG] スロット確認: task={task.name}, duration={duration}, slot_start={slot_start}, slot_end={slot_end}, available={available}")
                if available >= duration and duration > 0:
                    assigned_start = slot_start
                    assigned_end = slot_start + timedelta(minutes=duration)
                    assignments.append((assigned_start, assigned_end, task))
                    slot[0] = assigned_end
                    assigned = True
                    print(f"[DEBUG] 割当成功: task={task.name}, start={assigned_start}, end={assigned_end}")
                    break
            if not assigned:
                print(f"[DEBUG] 割当失敗: task={task.name}")
                unassigned.append(task)

        if not assignments:
            print("[DEBUG] 決定的スケジュール生成失敗: 割当結果が空です。")
            return ""

        weekday_map = ['月', '火', '水', '木', '金', '土', '日']
        priority_icons = {
            "urgent_important": "🚨",
            "not_urgent_important": "⭐",
            "urgent_not_important": "⚡",
            "normal": "📝"
        }

        header = "🗓️【来週のスケジュール提案】" if week_info else "🗓️【本日のスケジュール提案】"
        def append_separator(container: List[str]):
            if not container or container[-1] != "━━━━━━━━━━━━━━":
                container.append("━━━━━━━━━━━━━━")

        lines = [header]
        append_separator(lines)
        assignments.sort(key=lambda item: item[0])

        current_date = None
        for start, end, task in assignments:
            task_date = start.date()
            if week_info and current_date != task_date:
                append_separator(lines)
                lines.append(f"{start.strftime('%m/%d')}({weekday_map[start.weekday()]})")
                append_separator(lines)
                current_date = task_date
            elif not week_info and current_date is None:
                current_date = task_date

            append_separator(lines)
            lines.append(f"🕒 {start.strftime('%H:%M')}〜{end.strftime('%H:%M')}")
            icon = priority_icons.get(task.priority, "📝")
            lines.append(f"📝 {icon} {task.name}（{task.duration_minutes}分）")
            append_separator(lines)

        if unassigned:
            append_separator(lines)
            lines.append("🟡未割り当てタスク")
            for task in unassigned:
                lines.append(f"・{task.name}（{task.duration_minutes}分）")
            append_separator(lines)

        append_separator(lines)
        lines.append("✅理由・まとめ")
        lines.append("・空き時間に基づき機械的に割り当てました。")
        lines.append("このスケジュールでよろしければ「承認する」、修正したい場合は「修正する」と返信してください。")
        return "\n".join(lines)

    def _generate_default_free_times(
        self,
        week_info: str,
        base_date: Optional[datetime]
    ) -> List[dict]:
        """カレンダー情報が取得できない場合のデフォルト空き時間を生成"""
        import pytz

        jst = pytz.timezone('Asia/Tokyo')
        if base_date is None:
            base_date = datetime.now(jst)
        elif base_date.tzinfo is None:
            base_date = jst.localize(base_date)
        else:
            base_date = base_date.astimezone(jst)

        days = 7 if week_info else 1
        slots = []
        for i in range(days):
            day_start = base_date + timedelta(days=i)
            start_time = day_start.replace(hour=9, minute=0, second=0, microsecond=0)
            end_time = day_start.replace(hour=17, minute=0, second=0, microsecond=0)
            slots.append({
                "start": start_time,
                "end": end_time
            })
        return slots

    def extract_due_date_from_text(self, text: str) -> Optional[str]:
        """自然言語テキストから期日を抽出し、YYYY-MM-DD形式で返す（JST基準・口語対応）"""
        import pytz
        from datetime import datetime
        jst = pytz.timezone('Asia/Tokyo')
        now_jst = datetime.now(jst)
        now_str = now_jst.strftime("%Y-%m-%dT%H:%M:%S%z")
        now_str = now_str[:-2] + ":" + now_str[-2:]
        prompt = f"""
現在の日時（日本時間）は {now_str} です。
以下のテキストから「期日」「締切日」「日付」「いつやるか」などを柔軟に抽出し、YYYY-MM-DD形式で1つだけ返してください。

【口語表現の対応例】
- 「来週中」「来週まで」「来週いっぱい」→ 来週の日曜日（来週の最終日）
- 「今週中」「今週まで」「今週いっぱい」→ 今週の日曜日（今週の最終日）
- 「来週末」「来週の土日」→ 来週の土曜日
- 「今週末」「今週の土日」→ 今週の土曜日
- 「来月まで」「来月いっぱい」→ 来月末
- 「今月まで」「今月いっぱい」→ 今月末
- 「そのうち」「暇な時」「余裕がある時」→ 1週間後
- 「急ぎじゃない」「ゆっくりでいい」→ 2週間後
- 「なるべく早く」「早めに」→ 3日後
- 「来週の頭」「来週の初め」→ 来週の月曜日
- 「来週の終わり」「来週の終盤」→ 来週の金曜日

【重要：週の計算ルール】
- 週は月曜日から日曜日まで（日曜日が週の最終日）
- 「来週中」= 来週の月曜日から日曜日まで = 来週の日曜日が期限
- 「今週中」= 今週の月曜日から日曜日まで = 今週の日曜日が期限
- 現在が月曜日の場合：「来週中」は来週の日曜日、「今週中」は今週の日曜日
- 現在が火曜日の場合：「来週中」は来週の日曜日、「今週中」は今週の日曜日
- 現在が日曜日の場合：「来週中」は来週の日曜日、「今週中」は今週の日曜日
- 日本時間（JST）基準で計算する

テキスト: {text}

出力は日付のみ、余計な説明や記号は一切不要です。
"""
        try:
            system_content = "あなたは日本語の自然言語日付抽出の専門家です。口語表現や曖昧な表現も柔軟に解釈して、適切な期日を設定してください。"
            raw = self._get_cached_or_call_api(
                prompt=prompt,
                system_content=system_content,
                max_tokens=20,
                temperature=0.1
            )
            # 日付形式だけ抽出
            import re
            m = re.search(r'(\d{4}-\d{2}-\d{2})', raw)
            if m:
                return m.group(1)
            return None
        except Exception as e:
            print(f"OpenAI API error (extract_due_date): {e}")
            return None 

    def classify_user_intent(self, message: str) -> dict:
        """ユーザーの意図をAIで分類する"""
        prompt = f"""
次の日本語メッセージの意図を分類し、JSONで返してください。
メッセージ: '{message}'

分類項目:
1. "cancel" - キャンセル、やめる、中止、終了などの操作終了を表す言葉
2. "incomplete_task" - タスク名はあるが時間が不明、または時間はあるがタスク名が不明
3. "complete_task" - タスク名と時間の両方が含まれている
4. "help" - ヘルプ、使い方、説明を求めている
5. "other" - 上記以外

出力形式:
{{
    "intent": "cancel|incomplete_task|complete_task|help|other",
    "confidence": 0.95,
    "reason": "分類理由の簡潔な説明"
}}

例:
- "キャンセル" → {{"intent": "cancel", "confidence": 0.98, "reason": "操作終了の意図"}}
- "資料作成" → {{"intent": "incomplete_task", "confidence": 0.9, "reason": "タスク名のみで時間が不明"}}
- "資料作成 2時間" → {{"intent": "complete_task", "confidence": 0.95, "reason": "タスク名と時間の両方あり"}}
- "使い方を教えて" → {{"intent": "help", "confidence": 0.9, "reason": "ヘルプを求めている"}}

JSON以外の余計な説明や文章は一切出力しないでください。
"""
        try:
            system_content = "あなたは日本語メッセージの意図を分類するAIです。指定された形式でJSONのみを返してください。"
            result_text = self._get_cached_or_call_api(
                prompt=prompt,
                system_content=system_content,
                max_tokens=300,
                temperature=0.1
            )

            print(f"[classify_user_intent] AI応答: {result_text}")

            # JSONパース
            import json
            import re
            m = re.search(r'\{.*\}', result_text, re.DOTALL)
            if m:
                result = json.loads(m.group(0))
                print(f"[classify_user_intent] 分類結果: {result}")
                return result

            return {"intent": "other", "confidence": 0.0, "reason": "JSON解析エラー"}

        except Exception as e:
            print(f"[classify_user_intent] エラー: {e}")
            return {"intent": "other", "confidence": 0.0, "reason": "分類エラー"}

    def _compute_prompt_hash(self, prompt: str) -> str:
        """プロンプトのSHA256ハッシュを計算"""
        return hashlib.sha256(prompt.encode('utf-8')).hexdigest()

    def _get_cached_or_call_api(
        self,
        prompt: str,
        system_content: str,
        max_tokens: int,
        temperature: float,
        model: Optional[str] = None
    ) -> str:
        """
        キャッシュをチェックし、存在すればそれを返す。
        存在しなければAPIを呼び出し、結果をキャッシュに保存してから返す。
        """
        if model is None:
            model = self.model

        # キャッシュが無効化されている、またはdbが設定されていない場合は直接API呼び出し
        if not self.enable_cache or not self.db:
            return self._call_openai_api(prompt, system_content, max_tokens, temperature, model)

        # プロンプトのハッシュを計算
        prompt_hash = self._compute_prompt_hash(prompt + system_content)

        # キャッシュをチェック
        cached_response = self.db.get_cached_response(model, prompt_hash)
        if cached_response:
            print(f"[_get_cached_or_call_api] キャッシュから取得: hash={prompt_hash[:16]}...")
            return cached_response

        # キャッシュミス: APIを呼び出し
        response = self._call_openai_api(prompt, system_content, max_tokens, temperature, model)

        # レスポンスをキャッシュに保存
        if response:
            self.db.set_cached_response(
                model=model,
                prompt_hash=prompt_hash,
                prompt_preview=prompt[:200],
                response=response,
                ttl_hours=self.cache_ttl_hours
            )
            print(f"[_get_cached_or_call_api] キャッシュに保存: hash={prompt_hash[:16]}...")

        return response

    def _call_openai_api(
        self,
        prompt: str,
        system_content: str,
        max_tokens: int,
        temperature: float,
        model: str
    ) -> str:
        """OpenAI APIを直接呼び出す"""
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"[_call_openai_api] OpenAI API error: {e}")
            return ""

    def extract_task_numbers_from_message(self, message: str) -> Optional[dict]:
        """日本語メッセージから通常タスク・未来タスクの番号をAIで抽出し、{"tasks": [1,3], "future_tasks": [2]}のdictで返す"""
        prompt = f"""
次の日本語メッセージから、通常タスクと未来タスクの番号をそれぞれ抽出し、JSONで返してください。
メッセージ: '{message}'

重要: 数字の区切り文字（.、,、、）は複数の番号を示します。
例:
- 「タスク2.5」→ 2番と5番 → {{"tasks": [2, 5], "future_tasks": []}}
- 「タスク3.4」→ 3番と4番 → {{"tasks": [3, 4], "future_tasks": []}}
- 「1.2」→ 1番と2番 → {{"tasks": [1, 2], "future_tasks": []}}
- 「1,3」→ 1番と3番 → {{"tasks": [1, 3], "future_tasks": []}}
- 「1、2、3」→ 1番と2番と3番 → {{"tasks": [1, 2, 3], "future_tasks": []}}
- 「タスク1、未来タスク2」→ 1番と2番 → {{"tasks": [1], "future_tasks": [2]}}

特に注意: 「タスク2.5」のような形式では、2と5の両方の番号を抽出してください。

出力例: {{"tasks": [1, 3], "future_tasks": [2]}}
- 通常タスクは"tasks"、未来タスクは"future_tasks"の配列にしてください。
- 番号はすべて半角数字で昇順にしてください。
- 番号がなければ空配列で返してください。
- JSON以外の余計な説明や文章は一切出力しないでください。
"""
        try:
            system_content = "あなたは日本語の自然言語解析の専門家です。"
            raw = self._get_cached_or_call_api(
                prompt=prompt,
                system_content=system_content,
                max_tokens=100,
                temperature=0.0
            )
            import json
            import re
            # JSON部分のみ抽出
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group(0))
            return None
        except Exception as e:
            print(f"OpenAI API error (extract_task_numbers): {e}")
            return None 