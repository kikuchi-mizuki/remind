# LINEタスクスケジューリングBot

LINEでタスクを登録し、OpenAI GPT-4oが最適なスケジュールを提案してGoogleカレンダーに自動登録する高機能タスク管理Botです。

## 🚀 機能

### 主要機能
- **タスク登録**: LINEで自然言語でタスクを登録（通常タスク・緊急タスク・未来タスク）
- **AIスケジュール提案**: OpenAI GPT-4oが空き時間を考慮して最適なスケジュールを提案
- **カレンダー連携**: 承認されたスケジュールをGoogleカレンダーに自動登録
- **定期通知**: 毎朝8時・毎晩21時・日曜18時の自動通知
- **優先度管理**: AI自動判定による4段階の優先度管理
- **未来タスク管理**: 長期的な投資タスクの管理と週次選択
- **タスク完了確認**: 夜21時に完了確認と自動繰越
- **マルチテナント対応**: 複数LINEチャネルの同時運用

### 詳細機能
- タスクの頻度設定（毎日/単発）
- 所要時間の自動解析（自然言語対応: 「1時間半」「30分」など）
- 空き時間の自動検出（Google Calendar連携）
- タスク優先度に基づく時間配置（緊急度×重要度マトリクス）
- 期日管理と期限切れタスクの自動移動
- AIによるユーザー意図分類とヘルプ機能
- タスク繰越機能（未完了タスクの翌日自動繰越）
- PostgreSQL/SQLiteデュアルデータベース対応
- Railway環境対応（ボリュームマウント、環境変数自動判定）

## 📋 要件

### 必須
- Python 3.8以上
- LINE Messaging API
- OpenAI API (GPT-4o または GPT-4o-mini)
- Google Calendar API

### データベース（いずれか）
- SQLite（ローカル開発）
- PostgreSQL（本番環境推奨）

### デプロイ環境（推奨）
- Railway（PostgreSQL対応、環境変数自動判定）
- Render
- Heroku
- その他のPython対応ホスティング

## 🏗️ アーキテクチャ

### システム構成図

```
┌─────────────┐
│   LINE User │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────┐
│         LINE Messaging API              │
│  (Webhook / Push Message / Flex Message)│
└──────────────┬──────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────┐
│             Flask Application               │
│  ┌──────────────────────────────────────┐   │
│  │        app.py (3425行)               │   │
│  │  - Webhook受信                       │   │
│  │  - Google OAuth2認証フロー           │   │
│  │  - 会話モード管理（フラグファイル）   │   │
│  │  - ユーザーメッセージ処理             │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │         Services Layer               │   │
│  │  ┌──────────────────────────────┐   │   │
│  │  │  TaskService                 │   │   │
│  │  │  - タスク解析・管理          │   │   │
│  │  │  - 優先度自動判定            │   │   │
│  │  └──────────────────────────────┘   │   │
│  │  ┌──────────────────────────────┐   │   │
│  │  │  OpenAIService               │   │   │
│  │  │  - GPT-4oによるスケジュール  │   │   │
│  │  │  - 意図分類・情報抽出        │   │   │
│  │  └──────────────────────────────┘   │   │
│  │  ┌──────────────────────────────┐   │   │
│  │  │  CalendarService             │   │   │
│  │  │  - Google Calendar連携       │   │   │
│  │  │  - 空き時間取得              │   │   │
│  │  └──────────────────────────────┘   │   │
│  │  ┌──────────────────────────────┐   │   │
│  │  │  NotificationService         │   │   │
│  │  │  - 定期通知（8時・21時・日曜）│   │   │
│  │  │  - スケジューラー管理        │   │   │
│  │  └──────────────────────────────┘   │   │
│  │  ┌──────────────────────────────┐   │   │
│  │  │  MultiTenantService          │   │   │
│  │  │  - 複数チャネル管理          │   │   │
│  │  └──────────────────────────────┘   │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │         Models Layer                 │   │
│  │  - Database (SQLite)                 │   │
│  │  - PostgresDatabase (PostgreSQL)     │   │
│  │  - Task, ScheduleProposal models     │   │
│  └──────────────────────────────────────┘   │
└──────────────┬───────────────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
┌─────────────┐  ┌──────────────┐
│  OpenAI API │  │ Google APIs  │
│  (GPT-4o)   │  │  - Calendar  │
└─────────────┘  │  - OAuth2    │
                 └──────────────┘
```

### 会話フロー

```
1. ユーザー → LINE Bot: メッセージ送信
2. LINE → Flask: Webhook受信
3. Flask: 署名検証 + チャネル判定（マルチテナント）
4. Flask: 会話モード判定（フラグファイル）
5. Services: タスク解析 / OpenAI API呼び出し
6. Database: データ保存・取得
7. Services: Google Calendar連携（必要時）
8. Flask → LINE: 応答メッセージ送信
```

### 通知フロー

```
1. NotificationService: スケジューラー起動（別スレッド）
2. schedule: 定期実行（8時・21時・日曜18時）
3. NotificationService: 重複実行チェック
4. Database: タスク一覧取得
5. Services: メッセージ生成
6. LINE API: Push Message送信
7. Database: 実行履歴記録
```

## 💻 技術スタック

### バックエンド
- **フレームワーク**: Flask 2.x
- **言語**: Python 3.8+
- **非同期処理**: threading（スケジューラー用）

### データベース
- **SQLite**: ローカル開発用
- **PostgreSQL**: 本番環境用（SQLAlchemy ORM）

### 外部API
- **LINE Messaging API**: v3 (linebot-v3)
- **OpenAI API**: GPT-4o / GPT-4o-mini
- **Google Calendar API**: v3
- **Google OAuth2**: Authorization Code Flow

### ライブラリ
- `flask` - Webフレームワーク
- `linebot-v3` - LINE Bot SDK
- `openai` - OpenAI API クライアント
- `google-auth` / `google-auth-oauthlib` - Google認証
- `google-api-python-client` - Google API クライアント
- `sqlalchemy` - PostgreSQL ORM
- `schedule` - スケジューラー
- `pytz` - タイムゾーン処理
- `python-dotenv` - 環境変数管理

### セキュリティ
- HMAC-SHA256署名検証（LINE Webhook）
- Google OAuth2認証
- refresh_tokenによるトークン自動更新
- 環境変数による機密情報管理
- ユーザー単位のデータ分離

## 🛠️ セットアップ

### 1. リポジトリのクローン
```bash
git clone <repository-url>
cd remind
```

### 2. 依存関係のインストール
```bash
pip install -r requirements.txt
```

### 3. 環境変数の設定
```bash
cp env.example .env
```

`.env`ファイルを編集して、以下の値を設定してください：

```env
# LINE Bot設定（単一チャネル）
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token_here
LINE_CHANNEL_SECRET=your_line_channel_secret_here

# LINE Bot設定（マルチテナント - オプション）
# 複数のLINE Botチャネルを運用する場合は以下を設定
MULTI_CHANNEL_CONFIGS={
  "channel_id_1": {
    "access_token": "your_access_token_1",
    "secret": "your_secret_1"
  },
  "channel_id_2": {
    "access_token": "your_access_token_2",
    "secret": "your_secret_2"
  }
}

# OpenAI設定
OPENAI_API_KEY=your_openai_api_key_here

# Google Calendar OAuth2設定
CLIENT_SECRETS_JSON={"web":{"client_id":"...","client_secret":"...","redirect_uris":["..."]}}

# データベース設定
# PostgreSQL（本番環境 - Railway等）
DATABASE_URL=postgresql://user:password@host:port/database

# SQLite（ローカル開発 - DATABASE_URLが未設定の場合に自動使用）
# 自動的に tasks.db が作成されます

# アプリケーション設定
PORT=5000
FLASK_ENV=development
FLASK_SECRET_KEY=your-secret-key-for-session

# ベースURL（デプロイ環境）
BASE_URL=https://your-domain.com
# Railway環境では自動判定されるため設定不要
# RAILWAY_STATIC_URL または RAILWAY_PUBLIC_DOMAIN が自動的に使用されます

# アクティブユーザーID（カンマ区切り - オプション）
ACTIVE_USER_IDS=user_id_1,user_id_2,user_id_3
```

### 4. LINE Botの設定

1. [LINE Developers Console](https://developers.line.biz/)でチャネルを作成
2. Messaging APIを有効化
3. チャネルアクセストークンとチャネルシークレットを取得
4. Webhook URLを設定: `https://your-domain.com/callback`

### 5. OpenAI APIの設定

1. [OpenAI Platform](https://platform.openai.com/)でアカウント作成
2. APIキーを取得
3. 環境変数に設定

### 6. Google Calendar APIの設定

1. [Google Cloud Console](https://console.cloud.google.com/)でプロジェクト作成
2. Google Calendar APIを有効化
3. サービスアカウントキーを作成
4. 環境変数に設定

## 🗄️ データベーススキーマ

### テーブル構造

#### tasks テーブル
タスク情報を管理するメインテーブル

| カラム名 | 型 | 説明 |
|---------|-----|------|
| task_id | TEXT | タスクID（UUID、主キー） |
| user_id | TEXT | ユーザーID（LINE User ID） |
| name | TEXT | タスク名 |
| duration_minutes | INTEGER | 所要時間（分） |
| repeat | BOOLEAN | 繰り返しフラグ |
| status | TEXT | ステータス（active/archived） |
| created_at | TIMESTAMP | 作成日時 |
| due_date | TEXT | 期限（YYYY-MM-DD形式） |
| priority | TEXT | 優先度（urgent_important/not_urgent_important/urgent_not_important/normal） |
| task_type | TEXT | タスクタイプ（daily/future） |

#### tokens テーブル
Google OAuth2トークンを管理

| カラム名 | 型 | 説明 |
|---------|-----|------|
| user_id | TEXT | ユーザーID（主キー） |
| token_json | TEXT | トークン情報（JSON形式） |

#### schedule_proposals テーブル
スケジュール提案履歴

| カラム名 | 型 | 説明 |
|---------|-----|------|
| id | INTEGER | ID（主キー、自動採番） |
| user_id | TEXT | ユーザーID |
| proposal_data | TEXT | 提案データ（JSON形式） |
| created_at | TIMESTAMP | 作成日時 |

#### notification_executions テーブル
通知実行履歴（重複実行防止用）

| カラム名 | 型 | 説明 |
|---------|-----|------|
| notification_type | TEXT | 通知タイプ（主キー） |
| last_execution_time | TEXT | 最終実行日時 |

#### user_channels テーブル
ユーザーとLINEチャネルの関連付け（マルチテナント用）

| カラム名 | 型 | 説明 |
|---------|-----|------|
| user_id | TEXT | ユーザーID（主キー） |
| channel_id | TEXT | チャネルID |
| created_at | TIMESTAMP | 作成日時 |

#### user_settings テーブル
ユーザー設定

| カラム名 | 型 | 説明 |
|---------|-----|------|
| user_id | TEXT | ユーザーID（主キー） |
| calendar_id | TEXT | カレンダーID |
| notification_time | TEXT | 通知時刻（デフォルト: 08:00） |
| created_at | TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | 更新日時 |

### データベースマイグレーション

#### 既存データベースへのカラム追加

既存の `tasks.db` に新しいカラムを追加する場合：

```sh
# 期日管理カラム追加
sqlite3 tasks.db 'ALTER TABLE tasks ADD COLUMN due_date TEXT;'

# 優先度カラム追加
sqlite3 tasks.db 'ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT "normal";'

# タスクタイプカラム追加
sqlite3 tasks.db 'ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT "daily";'
```

**注意**: アプリケーション起動時に自動的にカラムが追加されるため、通常は手動実行不要です。

## 🚀 起動方法

### 開発環境
```bash
python app.py
```

### 本番環境
```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## 📱 使い方

### 1. 初期設定
1. LINEでBotを友だち追加
2. メニュー画面が表示されます
3. Google認証を実行（カレンダー連携に必要）

### 2. タスク登録

#### 通常タスク登録
「タスクを追加する」ボタンをタップ後、以下のように入力：
```
資料作成 30分 明日
筋トレ 20分 毎日
読書 1時間半 今週金曜
```

**対応する表現:**
- 時間: 「30分」「1時間」「1時間半」「2h」「45m」
- 期限: 「今日」「明日」「明後日」「来週中」「○月○日」
- 繰り返し: 「毎日」「毎週」

**複数タスク一括登録:**
```
資料作成 30分 明日
買い物 1時間 今日
メール返信 15分 今日
```

#### 緊急タスク登録
「緊急タスクを追加する」ボタンをタップ後、タスクを入力：
```
会議準備 1時間
```
→ 今日の空き時間に自動でスケジュールされます（Google認証必須）

#### 未来タスク登録
「未来タスクを追加する」ボタンをタップ後、長期的なタスクを入力：
```
新規事業計画 2時間
資格試験勉強 3時間
読書（投資本） 1時間
```
→ 日曜18時の通知で来週やるタスクとして選択できます

### 3. 毎朝のスケジュール提案（8時）

#### タスク選択
毎朝8時に今日のタスク一覧が送信されます。やるタスクの番号を選択：
```
1 3 5
```

#### スケジュール確認
AIが生成したスケジュール提案が表示されます：
```
🕒 09:00〜09:30
📝 資料作成（30分）

🕒 14:00〜15:00
📝 買い物（1時間）

✅ 理由: 午前中に集中作業、午後に外出タスクを配置
```

#### スケジュール承認
「承認する」と返信すると、Googleカレンダーに自動登録されます。

#### スケジュール修正
「修正する」と返信すると、タスク選択画面に戻ります。

### 4. 夜のタスク確認（21時）
毎晩21時に今日のタスク完了確認が送信されます：
1. 完了したタスクの番号を選択
2. 「はい」で確認
3. 完了タスクは削除、未完了タスクは翌日に自動繰越

### 5. 週次の未来タスク選択（日曜18時）
日曜18時に未来タスク一覧が送信されます：
1. 来週やるタスクの番号を選択
2. 来週のスケジュール提案を確認
3. 「承認する」でカレンダーに登録

### 6. タスク削除
「タスクを削除する」ボタンをタップ後、削除するタスクを選択：
```
タスク 1, 3
未来タスク 2
```

### 7. テストコマンド（開発者向け）
```
8時テスト        # 朝8時の通知をテスト送信
21時テスト       # 夜21時の通知をテスト送信
日曜18時テスト   # 日曜18時の通知をテスト送信
スケジューラー確認 # スケジューラーの状態を確認
```

## 📁 プロジェクト構造

```
remind/
├── app.py                          # メインアプリケーション（3425行）
│                                   # - LINE Webhook受信
│                                   # - Google OAuth2認証フロー
│                                   # - 会話モード管理（フラグファイル）
│                                   # - ユーザーメッセージ処理
│
├── requirements.txt                # 依存関係
├── env.example                     # 環境変数例
├── README.md                       # このファイル
│
├── models/                         # データモデル
│   ├── database.py                 # SQLiteデータベースクラス
│   │                               # - Task, ScheduleProposalモデル
│   │                               # - CRUD操作
│   └── postgres_database.py        # PostgreSQLデータベースクラス（Railway対応）
│                                   # - SQLAlchemyモデル
│                                   # - 自動フォールバック機能
│
├── services/                       # ビジネスロジック
│   ├── task_service.py             # タスク管理サービス
│   │                               # - 自然言語タスク解析
│   │                               # - 優先度自動判定
│   │                               # - タスク一覧整形
│   │
│   ├── calendar_service.py         # Googleカレンダーサービス
│   │                               # - OAuth2認証
│   │                               # - 空き時間取得
│   │                               # - イベント追加
│   │
│   ├── openai_service.py           # OpenAI APIサービス
│   │                               # - スケジュール提案生成（GPT-4o）
│   │                               # - ユーザー意図分類
│   │                               # - タスク情報抽出
│   │                               # - 優先度分析
│   │
│   ├── notification_service.py     # 通知サービス
│   │                               # - 定期通知（8時・21時・日曜18時）
│   │                               # - スケジューラー管理
│   │                               # - 重複実行防止
│   │
│   └── multi_tenant_service.py     # マルチテナントサービス
│                                   # - 複数LINEチャネル管理
│                                   # - チャネルルーティング
│
├── session/                        # セッションファイル（フラグファイル）
│   ├── add_task_mode_{user_id}.flag
│   ├── urgent_task_mode_{user_id}.json
│   ├── future_task_mode_{user_id}.json
│   ├── delete_mode_{user_id}.json
│   ├── task_select_mode_{user_id}.flag
│   ├── future_task_selection_{user_id}.json
│   ├── schedule_proposal_{user_id}.txt
│   └── selected_tasks_{user_id}.json
│
├── tokens/                         # Google認証トークン（非推奨、DBに移行済み）
│
├── tasks.db                        # SQLiteデータベース（ローカル開発用）
└── client_secrets.json             # Google OAuth2設定（環境変数から自動生成）
```

## 🔧 カスタマイズ

### 通知時間の変更
`services/notification_service.py`の`start_scheduler`メソッドで変更可能：

```python
# 毎朝8時にタスク通知（UTCで23:00 = JST 8:00）
schedule.every().day.at("23:00").do(self.send_daily_task_notification)

# 毎晩21時にタスク確認（UTCで12:00 = JST 21:00）
schedule.every().day.at("12:00").do(self.send_carryover_check)

# 日曜18時に未来タスク選択（UTCで09:00 = JST 18:00）
schedule.every().sunday.at("09:00").do(self.send_future_task_selection)
```

**注意**: UTCとJSTの時差（+9時間）に注意してください。

### スケジュール提案ルールの変更
`services/openai_service.py`の`_create_schedule_prompt`メソッドで変更可能：

```python
def _create_schedule_prompt(self, task_info, total_duration, free_time_str, week_info, now_str):
    prompt = f"""
    以下のタスクをスケジュールしてください：
    {task_info}

    空き時間：
    {free_time_str}

    ルール：
    - 優先度の高いタスクを優先
    - 集中力が必要なタスクは午前中に
    - 外出タスクは午後にまとめる
    """
    return prompt
```

### OpenAIモデルの変更
`services/openai_service.py`の`__init__`メソッドで変更可能：

```python
def __init__(self):
    self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    self.model = "gpt-4o"  # または "gpt-4o-mini" (コスト削減)
```

### 優先度判定ロジックのカスタマイズ
`services/task_service.py`の`_determine_priority`メソッドで変更可能：

```python
def _determine_priority(self, task_name, due_date, duration_minutes):
    # カスタムロジックを実装
    if "緊急" in task_name or "urgent" in task_name.lower():
        return "urgent_important"
    # ...
```

### データベースの切り替え
環境変数 `DATABASE_URL` の有無で自動的に切り替わります：

- **PostgreSQL**: `DATABASE_URL` が設定されている場合
- **SQLite**: `DATABASE_URL` が未設定の場合（ローカル開発用）

```python
# models/database.py
if os.environ.get('DATABASE_URL'):
    from models.postgres_database import PostgresDatabase
    db = PostgresDatabase()
else:
    from models.database import Database
    db = Database()
```

## 🚀 デプロイ

### Railway（推奨）

#### 1. PostgreSQLデータベースの作成
1. Railwayダッシュボードで「New」→「Database」→「PostgreSQL」を選択
2. データベースが作成されると `DATABASE_URL` が自動的に設定されます

#### 2. Volumeの設定（オプション - フラグファイル永続化）
1. Railwayダッシュボードで「Settings」→「Volumes」を選択
2. 「Add Volume」をクリック
3. Mount Path: `/app/vol`
4. Size: 1GB（最小サイズ）

**注意**: Volumeを設定しない場合、フラグファイルは `/tmp` に保存され、デプロイごとにリセットされます。

#### 3. アプリケーションのデプロイ
1. Railwayでプロジェクトを作成
2. GitHubリポジトリを連携
3. 環境変数を設定（下記参照）
4. デプロイ

#### 4. 環境変数の設定
以下の環境変数をRailway Dashboardで設定：

```
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_CHANNEL_SECRET=your_line_channel_secret
OPENAI_API_KEY=your_openai_api_key
CLIENT_SECRETS_JSON={"web":{"client_id":"...","client_secret":"...","redirect_uris":["..."]}}
DATABASE_URL=postgresql://... (自動設定)
FLASK_SECRET_KEY=your-random-secret-key
BASE_URL=https://your-railway-domain.railway.app (オプション、自動判定可能)
```

#### 5. Webhook URLの設定
1. RailwayでデプロイされたURLを確認（例: `https://your-app.railway.app`）
2. LINE Developers ConsoleでWebhook URLを設定: `https://your-app.railway.app/callback`
3. 「検証」をクリックして接続を確認

#### 6. Google OAuth2のリダイレクトURI設定
1. Google Cloud Consoleで「認証情報」を開く
2. OAuth 2.0 クライアントIDを選択
3. 「承認済みのリダイレクトURI」に追加: `https://your-app.railway.app/oauth2callback`

### Render

#### 1. Web Serviceの作成
1. RenderでWeb Serviceを作成
2. GitHubリポジトリを連携
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn -w 4 -b 0.0.0.0:$PORT app:app`

#### 2. PostgreSQLの追加
1. Renderダッシュボードで「New」→「PostgreSQL」を選択
2. Web Serviceに接続
3. `DATABASE_URL` が自動的に設定されます

#### 3. 環境変数の設定
Railwayと同様の環境変数を設定

#### 4. Webhook URLとリダイレクトURIの設定
Railwayと同様の手順

### Heroku

#### 1. Heroku CLIでデプロイ
```bash
heroku create your-app-name
heroku addons:create heroku-postgresql:mini
git push heroku main
```

#### 2. 環境変数の設定
```bash
heroku config:set LINE_CHANNEL_ACCESS_TOKEN=your_token
heroku config:set LINE_CHANNEL_SECRET=your_secret
heroku config:set OPENAI_API_KEY=your_api_key
heroku config:set CLIENT_SECRETS_JSON='{"web":{"client_id":"..."}}'
heroku config:set FLASK_SECRET_KEY=your-secret-key
```

#### 3. Webhook URLとリダイレクトURIの設定
Railwayと同様の手順

### デプロイ後の確認

#### ヘルスチェック
```bash
curl https://your-app.railway.app/
# 期待される応答: "LINEタスクスケジューリングBot is running!"
```

#### スケジューラーの確認
LINE Botに「スケジューラー確認」と送信して、スケジューラーの状態を確認

#### 通知のテスト
LINE Botに以下のコマンドを送信してテスト：
- 「8時テスト」: 朝8時の通知をテスト
- 「21時テスト」: 夜21時の通知をテスト
- 「日曜18時テスト」: 日曜18時の通知をテスト

## 🔒 セキュリティ

- 環境変数で機密情報を管理
- LINE Webhookの署名検証
- Google OAuth2認証
- ユーザー単位でのタスク分離

## ✅ 実装済み機能

- ✅ タスク優先度設定（AI自動判定による4段階）
- ✅ タスク完了報告機能（夜21時の自動通知）
- ✅ 未来タスク管理（長期的な投資タスク）
- ✅ 緊急タスク自動スケジュール
- ✅ タスク繰越機能
- ✅ マルチテナント対応（複数LINEチャネル）
- ✅ PostgreSQL対応（Railway環境）
- ✅ AIによるユーザー意図分類
- ✅ 複数タスク一括登録
- ✅ 期限切れタスク自動移動

## 📈 今後の拡張予定

- [ ] 複数人予定調整機能
- [ ] タスク統計・分析ダッシュボード
- [ ] 日報・週報自動生成（AIレポート）
- [ ] プロジェクト分類機能（カテゴリー管理）
- [ ] タスクテンプレート機能
- [ ] リマインダー設定（カスタム通知時刻）
- [ ] タスク完了率の可視化
- [ ] モバイルアプリ対応（LINE LIFF）
- [ ] 音声入力対応（LINE音声メッセージ）
- [ ] タスクの依存関係管理

## 🤝 コントリビューション

1. このリポジトリをフォーク
2. 機能ブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing-feature`)
5. プルリクエストを作成

## 📄 ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## 🆘 サポート

問題が発生した場合は、以下の手順で対処してください：

1. ログを確認
2. 環境変数が正しく設定されているか確認
3. APIキーが有効か確認
4. データベースファイルの権限を確認

## 📞 お問い合わせ

ご質問やご要望がございましたら、お気軽にお聞かせください。 