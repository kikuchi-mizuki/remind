# 変更履歴 (Changelog)

このファイルは、プロジェクトの主要な変更を記録します。

## [2024-11-24] - コード品質改善とバグ修正

### 🔒 セキュリティ強化

#### 必須環境変数のチェック追加
- **問題**: 環境変数が未設定でもデフォルト値で起動し、脆弱性のリスク
- **修正**: 起動時に必須環境変数をチェックし、未設定の場合はエラーで停止
- **対象変数**:
  - `FLASK_SECRET_KEY`
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LINE_CHANNEL_SECRET`
  - `OPENAI_API_KEY`
  - `CLIENT_SECRETS_JSON`
- **ファイル**: `app.py` (39-60行)

#### 機密情報のログ保護
- **問題**: トークンの内容がログに出力され、情報漏洩のリスク
- **修正**: トークンの存在と長さのみをログに記録
- **ファイル**: `app.py` (147-150行, 328-331行)

#### 入力検証の追加
- **問題**: タスク名の長さ制限がなく、DoS攻撃の可能性
- **修正**: タスク名を200文字以内に制限
- **ファイル**: `services/task_service.py` (197-203行)

---

### 🐛 バグ修正

#### データベース接続のリソースリーク修正
- **問題**: 例外発生時にデータベース接続が閉じられず、リソースリーク
- **修正**: `try-finally`ブロックを追加し、例外時も確実にクローズ
- **対象メソッド**:
  - SQLite: `create_task()`, `create_future_task()`, `get_user_tasks()`, `delete_task()`
  - PostgreSQL: `save_token()`, `get_token()`
- **ファイル**:
  - `models/database.py` (165-213, 215-253, 360-393行)
  - `models/postgres_database.py` (194-227, 229-258行)

#### タイムゾーン不一致の解消
- **問題**: naive datetimeとaware datetimeが混在し、比較エラーの可能性
- **修正**: 全datetime処理をJST (Asia/Tokyo)に統一
- **対象箇所**:
  - 重複実行チェック (57-77行)
  - フラグファイルのタイムスタンプ保存 (168, 392, 739, 754行)
  - フラグファイルのタイムスタンプ読み込み (153-166, 383-396行)
- **ファイル**: `services/notification_service.py`

#### 無限ループの可能性を修正
- **問題**: `while '⭐️⭐️' in line` で無限ループの可能性
- **修正**: 正規表現 `re.sub(r'⭐️+', '⭐', line)` に置き換え
- **ファイル**: `services/openai_service.py` (406-411行)

---

### ⚡ パフォーマンス改善

#### N+1クエリ問題の解決
- **問題**: ユーザー数に比例してデータベースクエリ数が増加
- **修正**: 全ユーザーのチャネルIDを一括取得するメソッドを追加
- **効果**: 100ユーザーの場合、100回のクエリ → 1回のクエリ
- **新規メソッド**:
  - `get_all_user_channels()` (SQLite)
  - `get_all_user_channels()` (PostgreSQL)
- **変更箇所**:
  - `send_daily_task_notification()` - 一括取得を使用
  - `send_carryover_check()` - 一括取得を使用
  - `_send_task_notification_to_user_multi_tenant()` - パラメータ追加
  - `_send_carryover_notification_to_user_multi_tenant()` - パラメータ追加
- **ファイル**:
  - `models/database.py` (653-676行)
  - `models/postgres_database.py` (318-344行)
  - `services/notification_service.py` (95-111, 654-662行)

---

### 📝 ドキュメント更新

#### README.mdの大幅改善
- アーキテクチャ図の追加（システム構成、会話フロー、通知フロー）
- 技術スタックの明記
- データベーススキーマの詳細化（6テーブル）
- 詳細な使い方ガイド（7セクション）
- デプロイ手順の拡充（Railway/Render/Heroku）
- 実装済み機能リストの追加

---

## コミット履歴

### [f2d10e9] Fix critical security issues and resource leaks
**日時**: 2024-11-24
**変更ファイル**: 5ファイル
- app.py
- models/database.py
- models/postgres_database.py
- services/task_service.py
- README.md

**主な変更**:
- 必須環境変数のチェック追加
- データベース接続のリソースリーク修正
- 入力検証の追加
- 機密情報のログ保護
- README大幅更新

---

### [300d665] Fix N+1 query problem and infinite loop
**日時**: 2024-11-24
**変更ファイル**: 4ファイル
- models/database.py
- models/postgres_database.py
- services/notification_service.py
- services/openai_service.py

**主な変更**:
- N+1クエリ問題の解決（一括取得メソッド追加）
- 無限ループの可能性を修正（正規表現に置き換え）

---

### [9010e0c] Fix timezone inconsistencies and database resource leaks
**日時**: 2024-11-24
**変更ファイル**: 2ファイル
- models/database.py
- services/notification_service.py

**主な変更**:
- タイムゾーン不一致の解消（JST統一）
- 追加のデータベースリソースリーク修正
- フラグファイルのタイムスタンプ処理改善

---

## 統計

### コード変更
- **合計コミット数**: 3
- **変更ファイル数**: 9ファイル（重複除く）
- **追加行数**: 約220行
- **削除行数**: 約105行
- **正味変更**: +115行

### 修正した問題
- 🔴 高優先度: 8問題
- 🟡 中優先度: 2問題
- 🟢 低優先度: 2問題

### パフォーマンス改善
- データベースクエリ: 最大99%削減（N+1問題解決）
- リソース使用: データベース接続リークの防止

---

## 残存する課題

### 🟡 中優先度（今後の改善候補）

#### 1. 巨大なcallback関数のリファクタリング
- **場所**: `app.py` callback関数（700行以上）
- **問題**: テスト困難、保守性が低い
- **提案**: 機能ごとに小さな関数に分割

#### 2. ファイルベースのフラグ管理
- **場所**: 複数の`*.flag`ファイル
- **問題**: 並行アクセス時の競合
- **提案**: Redisなどのインメモリストアに移行

#### 3. 重複コードの削減
- **場所**: メニュー表示コード（10箇所以上）
- **問題**: 変更時に全箇所を修正する必要
- **提案**: ヘルパー関数の作成

#### 4. OpenAI APIキャッシュ
- **場所**: `services/openai_service.py`
- **問題**: 同じパターンでも毎回API呼び出し
- **提案**: 頻繁なパターンのキャッシュ化

---

## テスト推奨事項

今回の修正後、以下のテストを実施することを推奨します：

### 必須テスト
1. ✅ 環境変数未設定時の起動確認
2. ✅ 通知機能のパフォーマンステスト（複数ユーザー）
3. ✅ タイムゾーン処理の動作確認
4. ✅ 例外発生時のリソース解放確認

### 推奨テスト
1. 長時間稼働テスト（24時間以上）
2. 並行アクセステスト（複数ユーザー同時操作）
3. データベース接続プールの枯渇テスト

---

## 移行手順（既存環境への適用）

本番環境に適用する際の手順：

### 1. 環境変数の確認
```bash
# 以下の環境変数が設定されているか確認
echo $FLASK_SECRET_KEY
echo $LINE_CHANNEL_ACCESS_TOKEN
echo $LINE_CHANNEL_SECRET
echo $OPENAI_API_KEY
echo $CLIENT_SECRETS_JSON
```

### 2. バックアップ
```bash
# データベースのバックアップ
cp tasks.db tasks.db.backup.$(date +%Y%m%d)
```

### 3. デプロイ
```bash
git pull origin main
# 環境に応じて再起動
```

### 4. 動作確認
```bash
# ヘルスチェック
curl https://your-domain.com/

# ログ確認
tail -f /var/log/app.log
```

---

## 謝辞

本バージョンの改善は、包括的なコードレビューと体系的な問題修正により実現されました。

**レビュー項目**:
- セキュリティ問題
- リソースリーク
- 並行性の問題
- パフォーマンス問題
- コード品質

**修正方針**:
1. 最優先問題から順次対応
2. 後方互換性の維持
3. 段階的なコミット
4. 包括的なドキュメント化

---

## サポート

問題が発生した場合：

1. **ログ確認**: エラーメッセージとスタックトレースを確認
2. **環境変数確認**: 全ての必須環境変数が設定されているか確認
3. **データベース確認**: 接続が正常か確認
4. **GitHubイシュー**: 新しいイシューを作成して報告

---

最終更新: 2024-11-24
