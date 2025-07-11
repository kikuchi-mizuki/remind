# LINEタスクスケジューリングBot

LINEでタスクを登録し、ChatGPTが最適なスケジュールを提案してGoogleカレンダーに自動登録するBotです。

## 🚀 機能

### 主要機能
- **タスク登録**: LINEで自然言語でタスクを登録
- **スケジュール提案**: ChatGPTが空き時間を考慮して最適なスケジュールを提案
- **カレンダー連携**: 承認されたスケジュールをGoogleカレンダーに自動登録
- **定期通知**: 毎朝8時にタスク一覧を通知
- **スケジュール修正**: LINEで簡単にスケジュールを修正

### 詳細機能
- タスクの頻度設定（毎日/単発）
- 所要時間の自動解析
- 空き時間の自動検出
- タスク優先度に基づく時間配置
- 週次レポートの自動生成

## 📋 要件

- Python 3.8以上
- LINE Messaging API
- OpenAI API
- Google Calendar API
- SQLite（データベース）

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
# LINE Bot設定
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token_here
LINE_CHANNEL_SECRET=your_line_channel_secret_here

# OpenAI設定
OPENAI_API_KEY=your_openai_api_key_here

# Google Calendar設定
GOOGLE_CREDENTIALS={"type": "service_account", "project_id": "your_project_id", ...}

# アプリケーション設定
PORT=5000
FLASK_ENV=development

# アクティブユーザーID（カンマ区切り）
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

### タスク登録
```
筋トレ 20分 毎日
買い物 30分
読書 1時間
```

### スケジュール確認
毎朝8時に今日のタスク一覧が送信されます。

### タスク選択
送信されたタスク一覧から、今日やるタスクの番号を選択：
```
1 3 5
```

### スケジュール承認
提案されたスケジュールに「承認」と返信すると、Googleカレンダーに登録されます。

### スケジュール修正
```
筋トレを15時に変更して
買い物を14時30分に変更して
```

## 📁 プロジェクト構造

```
remind/
├── app.py                 # メインアプリケーション
├── requirements.txt       # 依存関係
├── env.example           # 環境変数例
├── README.md             # このファイル
├── models/
│   └── database.py       # データベースモデル
├── services/
│   ├── task_service.py   # タスク管理サービス
│   ├── calendar_service.py # Googleカレンダーサービス
│   ├── openai_service.py # OpenAI APIサービス
│   └── notification_service.py # 通知サービス
└── tokens/               # Google認証トークン（自動生成）
```

## 🔧 カスタマイズ

### 通知時間の変更
`services/notification_service.py`の`start_scheduler`メソッドで変更可能：

```python
# 毎朝8時にタスク通知
schedule.every().day.at("08:00").do(self.send_daily_task_notification)
```

### スケジュール提案ルールの変更
`services/openai_service.py`の`_create_schedule_prompt`メソッドで変更可能。

## 🚀 デプロイ

### Railway
1. Railwayでプロジェクトを作成
2. GitHubリポジトリを連携
3. 環境変数を設定
4. デプロイ

### Render
1. RenderでWeb Serviceを作成
2. GitHubリポジトリを連携
3. 環境変数を設定
4. デプロイ

## 🔒 セキュリティ

- 環境変数で機密情報を管理
- LINE Webhookの署名検証
- Google OAuth2認証
- ユーザー単位でのタスク分離

## 📈 今後の拡張予定

- [ ] タスク優先度設定
- [ ] 複数人予定調整
- [ ] タスク完了報告機能
- [ ] 日報・週報自動生成
- [ ] プロジェクト分類機能
- [ ] モバイルアプリ対応

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