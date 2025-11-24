# 変更履歴 (Changelog)

このファイルは、プロジェクトの主要な変更を記録します。

## [2025-11-24 続き] - リファクタリング継続とハンドラー抽出

### 📝 セッション概要
前回セッションからの継続作業として、以下の3つの大きな改善を実施しました：
1. フラグ管理のデータベース移行完了
2. メニュー表示の重複削減完了
3. タスク選択ハンドラーの抽出開始（進行中）

### ✅ 完了した作業

#### 1. フラグ管理のデータベース移行完了
- **コミット**: `c1e8d71`
- **変更内容**: すべてのファイルベースフラグ操作をデータベースベースに移行
- **対象フラグ（合計28箇所）**:
  - `urgent_task_mode` (3箇所)
  - `future_task_mode` (5箇所)
  - `add_task_mode` (6箇所)
  - `delete_mode` (4箇所)
  - `task_select_mode` (10箇所以上)
- **使用API**:
  - `check_flag_file(user_id, mode)` - フラグの存在確認
  - `create_flag_file(user_id, mode, data)` - フラグの作成/更新
  - `delete_flag_file(user_id, mode)` - フラグの削除
  - `load_flag_data(user_id, mode)` - フラグデータの読み込み
- **効果**:
  - コード削減: 107行削減、62行追加（差し引き45行削減）
  - 並行性の改善: ファイルベースの競合問題を解消
  - 保守性の向上: 一貫性のあるAPI使用
  - スケーラビリティの向上: データベースベースの状態管理

#### 2. メニュー表示の重複削減完了
- **コミット**: `f84ccdc`
- **変更内容**: 残り6箇所のFlexMessage重複コードを削減
- **修正箇所**:
  - Lines 805-820付近（未来タスク追加成功時）
  - Lines 814-828付近（未来タスク追加エラー時）
  - Lines 866-880付近（未来タスク不完全時）
  - Lines 951-965付近（タスク追加エラー時）
  - Lines 1011-1025付近（タスク追加不完全時）
  - Lines 1031-1045付近（タスク削除キャンセル時）
- **パターン変更**:
  ```python
  # Before (15行):
  from linebot.v3.messaging import FlexMessage, FlexContainer
  flex_message_content = get_simple_flex_menu()
  flex_container = FlexContainer.from_dict(flex_message_content)
  flex_message = FlexMessage(alt_text="メニュー", contents=flex_container)
  active_line_bot_api.reply_message(...)

  # After (1行):
  send_reply_with_menu(active_line_bot_api, reply_token, get_simple_flex_menu, text=reply_text)
  ```
- **効果**:
  - コード削減: 90行削減、12行追加（差し引き78行削減）
  - 前回セッションと合わせて合計約160行削減
  - メニュー表示の完全な一元化

#### 3. タスク選択ハンドラーの抽出開始
- **コミット**: `afcf736` (WIP)
- **新規ファイル**: `handlers/selection_handler.py` (312行)
- **実装内容**:
  - `handle_task_selection_cancel()`: キャンセル処理
  - `handle_task_selection_process()`: 数字入力処理（準備完了）
- **app.py の変更**:
  - インポートセクションに新しいハンドラーを追加
  - キャンセル処理をハンドラー呼び出しに置き換え（7行削減）

### 🔄 進行中の作業

#### タスク選択ハンドラーの完全な統合
- **残作業**: app.py Lines 1248-1570（約320行）の数字入力処理をハンドラーに置き換え
- **現状**: ハンドラー関数は実装済み、app.pyへの統合が未完了
- **次ステップ**: 大規模な置き換え作業のため、次セッションで完了予定

#### 承認/修正ハンドラーの抽出（未着手）
- **予定**: `handlers/approval_handler.py` の作成
- **対象**: 約350行の承認/修正処理
- **推定時間**: 2-3時間

### 📊 セッション統計

#### コミット履歴
1. `c1e8d71` - Complete flag management database migration
2. `f84ccdc` - Complete menu display duplication reduction
3. `afcf736` - Add task selection handler (WIP)

#### コード削減効果
- フラグ管理移行: -45行
- メニュー重複削減: -78行
- キャンセル処理: -7行
- **合計削減**: -130行
- **追加**: +312行（selection_handler.py）
- **差し引き**: +182行（将来的にさらに320行削減予定）

#### 改善されたファイル
- `app.py`: 130行削減、インポート追加
- `handlers/helpers.py`: フラグ管理関数が完全にデータベース化
- `handlers/__init__.py`: 新しいハンドラーをエクスポート
- `handlers/selection_handler.py`: 新規作成（312行）

### 🎯 次回の作業計画

1. **優先度1**: タスク選択ハンドラーの完全統合
   - app.py Lines 1248-1570の置き換え
   - 推定時間: 1時間

2. **優先度2**: 承認/修正ハンドラーの抽出
   - `handlers/approval_handler.py` の作成
   - app.pyから約350行を抽出
   - 推定時間: 2-3時間

3. **優先度3**: 一時データファイルのデータベース移行（オプション）
   - `selected_tasks_{user_id}.json`
   - `schedule_proposal_{user_id}.txt`
   - `future_task_selection_{user_id}.json`

## [2025-11-24] - コードリファクタリングとアーキテクチャ改善

### 🏗️ アーキテクチャ改善

#### コールバック関数のリファクタリング（第1弾）
- **問題**: callback関数が約2773行で、テストと保守が困難
- **修正**: コマンド処理を独立したハンドラーに分離
- **成果**:
  - `handlers/` ディレクトリを新規作成
  - 5つのハンドラーファイルを作成
    - `test_handler.py`: テストコマンド（8時/21時/日曜18時テスト、スケジューラー確認）
    - `task_handler.py`: タスク追加・削除コマンド
    - `urgent_handler.py`: 緊急タスク追加コマンド
    - `future_handler.py`: 未来タスク追加コマンド
    - `helpers.py`: 共通ヘルパー関数
  - 約150行のコマンド処理を分離
- **効果**: テスト可能性と保守性が大幅に向上
- **ファイル**:
  - `handlers/*.py` (新規作成)
  - `app.py` (コマンド処理をハンドラー呼び出しに変更)
- **コミット**: `c5e80ab`

#### メニュー表示の重複コード削減
- **問題**: FlexMessageメニュー表示コードが16箇所以上で重複
- **修正**: 共通ヘルパー関数を作成して重複を削減
- **成果**:
  - `send_reply_with_menu()`: テキスト+メニューまたはメニューのみ送信
  - `create_flex_menu()`: FlexMessage作成
  - 6箇所の重複コードを削減（約90行削減）
- **効果**: DRY原則の適用、保守性向上
- **ファイル**:
  - `handlers/helpers.py` (関数追加)
  - `app.py` (6箇所を置き換え)
- **残存**: 約10箇所の重複コードが残存（今後対応予定）
- **コミット**: `ca1c2ea`

#### フラグ管理のデータベース移行（進行中）
- **問題**: ファイルベースの状態管理による並行アクセス時の競合
- **修正**: データベースベースの状態管理に移行
- **成果**:
  - **Phase 1: データベーススキーマ追加** (`863d35c`)
    - `user_states` テーブルを新規作成
      - user_id: ユーザーID
      - state_type: 状態タイプ
      - state_data: JSON形式の状態データ
      - created_at/updated_at: タイムスタンプ
    - 4つのデータベース操作メソッドを追加
      - `set_user_state()`: 状態を設定
      - `get_user_state()`: 状態を取得
      - `check_user_state()`: 状態の存在確認
      - `delete_user_state()`: 状態を削除
  - **Phase 2: ヘルパー関数の更新** (`449e137`)
    - `create_flag_file()`: データベース版に更新
    - `check_flag_file()`: データベース版に更新
    - `delete_flag_file()`: データベース版に更新
    - `load_flag_data()`: データベース版に更新
    - app.pyの3箇所をDB版に移行
- **効果**:
  - 並行アクセス時の競合を解決
  - ファイルシステムへの依存を削減
  - トランザクション管理が可能に
- **ファイル**:
  - `models/database.py` (テーブルとメソッド追加: 702-840行)
  - `handlers/helpers.py` (関数をDB版に更新)
  - `app.py` (一部をDB版に移行: 1236-1239行)
- **残存**: app.py内の約20箇所のフラグファイル直接操作（今後対応予定）
- **コミット**: `863d35c`, `449e137`

---

### 📊 コード改善統計

#### 今回のセッション（2025-11-24）
- **コミット数**: 4
- **削減行数**: 約240行
- **新規作成ファイル**: 6ファイル（handlers/*.py）
- **新規テーブル**: 1テーブル（user_states）
- **新規メソッド**: 8メソッド

#### コード品質指標
- **重複コード削減**: 6箇所（約90行）
- **関数分離**: 4ハンドラー + 1ヘルパー
- **保守性向上**: callback関数から150行を分離

---

### 🔄 移行の進捗

#### 完了
- ✅ ハンドラーアーキテクチャの導入
- ✅ メニュー表示の部分的な重複削減（37.5%）
- ✅ データベーススキーマの拡張
- ✅ フラグ管理のDB移行基盤構築

#### 進行中
- 🟡 フラグ管理のDB移行（Phase 3以降）
  - app.py内の残り20箇所を置き換え
  - selected_tasks, schedule_proposalなどの一時データのDB移行

#### 今後の予定
- ⏳ メニュー表示の完全な重複削減（残り10箇所）
- ⏳ 複雑な処理のリファクタリング
  - タスク選択処理（約300行）
  - 承認・修正処理（約350行）
- ⏳ OpenAI APIキャッシュの実装

---

### 📝 コミット履歴

#### [c5e80ab] Refactor callback function: Extract command handlers
**日時**: 2025-11-24
**変更ファイル**: 7ファイル
- app.py
- handlers/__init__.py
- handlers/helpers.py
- handlers/test_handler.py
- handlers/task_handler.py
- handlers/urgent_handler.py
- handlers/future_handler.py

**主な変更**:
- handlers/ディレクトリを作成
- 各コマンド処理を独立したハンドラーに分離
- 共通ヘルパー関数を実装

---

#### [ca1c2ea] Reduce menu display code duplication
**日時**: 2025-11-24
**変更ファイル**: 3ファイル
- app.py
- handlers/__init__.py
- handlers/helpers.py

**主な変更**:
- send_reply_with_menu()ヘルパー関数を作成
- 6箇所の重複コードを削減
- FlexMessage処理を統一化

---

#### [863d35c] Add user_states table for database-based state management
**日時**: 2025-11-24
**変更ファイル**: 1ファイル
- models/database.py

**主な変更**:
- user_statesテーブルを追加
- 4つのデータベース操作メソッドを実装
- 並行アクセス問題の解決基盤を構築

---

#### [449e137] Migrate flag management from files to database (Phase 1)
**日時**: 2025-11-24
**変更ファイル**: 2ファイル
- app.py
- handlers/helpers.py

**主な変更**:
- helpers.pyの4つの関数をデータベース版に更新
- app.pyの3箇所をDB版に移行
- ファイルベースからDBベースへの移行開始

---

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
