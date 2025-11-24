# テストガイド

このディレクトリには、handlersモジュールのユニットテストが含まれています。

## セットアップ

テストを実行するには、pytestをインストールする必要があります:

```bash
pip install pytest pytest-mock
```

## テストの実行

### 全てのテストを実行

```bash
pytest tests/
```

### 特定のハンドラーのテストを実行

```bash
# selection_handler のテスト
pytest tests/handlers/test_selection_handler.py -v

# urgent_handler のテスト
pytest tests/handlers/test_urgent_handler.py -v

# future_handler のテスト
pytest tests/handlers/test_future_handler.py -v

# approval_handler のテスト
pytest tests/handlers/test_approval_handler.py -v
```

### カバレッジレポートの生成

```bash
pip install pytest-cov
pytest tests/ --cov=handlers --cov-report=html
```

カバレッジレポートは `htmlcov/index.html` に生成されます。

## テスト構造

```
tests/
├── __init__.py
├── README.md
└── handlers/
    ├── __init__.py
    ├── test_selection_handler.py    # タスク選択処理のテスト
    ├── test_approval_handler.py      # 承認/修正処理のテスト
    ├── test_urgent_handler.py        # 緊急タスク処理のテスト
    └── test_future_handler.py        # 未来タスク処理のテスト
```

## テストカバレッジ

各ハンドラーのテストは以下をカバーしています:

### selection_handler
- タスク選択のキャンセル処理
- 有効な数字入力での処理
- 無効な数字入力での処理
- 数字が認識できない場合の処理

### urgent_handler
- Google認証済みの場合のコマンド処理
- Google認証未完了の場合のコマンド処理
- 空き時間がある場合のタスク処理
- 空き時間がない場合のタスク処理
- エラー発生時の処理

### future_handler
- 単一タスク追加処理
- 複数タスク追加処理
- エラー発生時の処理

### approval_handler
- スケジュール提案がない場合の承認処理
- selected_tasksファイルがない場合の処理
- 通常モードでの修正処理
- 未来タスクモードでの修正処理
- エラー発生時の処理

## モック

テストでは以下の外部依存関係をモック化しています:

- LINE Messaging API (`line_bot_api`)
- タスクサービス (`task_service`)
- カレンダーサービス (`calendar_service`)
- OpenAIサービス (`openai_service`)
- データベース操作 (`helpers`モジュールの関数)

## 今後の改善

- より詳細なテストケースの追加
- カバレッジの向上（目標: 80%以上）
- 統合テストの追加
- エッジケースのテスト強化
