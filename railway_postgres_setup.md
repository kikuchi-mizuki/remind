# Railway PostgreSQL設定手順

## 問題の概要
新規プロジェクトでGoogle認証が一定時間後に切れる問題は、SQLiteデータベースの永続化が不十分なことが原因です。

## 解決方法: PostgreSQLの設定

### 1. RailwayでPostgreSQLを追加

#### 手順
1. **Railwayダッシュボード**でプロジェクトを開く
2. **+ New** ボタンをクリック
3. **Database** → **PostgreSQL** を選択
4. PostgreSQLサービスが追加される

#### 自動設定される環境変数
```
DATABASE_URL=postgresql://postgres:password@host:port/database
```

### 2. 環境変数の確認

#### Railwayダッシュボードで確認
1. **Variables**タブを開く
2. `DATABASE_URL`が自動設定されていることを確認

#### 設定例
```
DATABASE_URL=postgresql://postgres:abc123@containers-us-west-1.railway.app:5432/railway
```

### 3. アプリケーションの動作

#### PostgreSQL優先
- `DATABASE_URL`が設定されている場合、PostgreSQLを使用
- トークン、ユーザー情報、通知履歴が永続化される

#### SQLiteフォールバック
- `DATABASE_URL`が未設定の場合、SQLiteを使用
- 既存の動作を維持

### 4. 確認方法

#### ログで確認
```
[init_db] PostgreSQLデータベースを使用
[save_token] PostgreSQL保存成功: user_id=Ua0cf1a45a9126eebdff952202704385e
[get_token] PostgreSQL取得成功: user_id=Ua0cf1a45a9126eebdff952202704385e
```

#### データベース接続テスト
```bash
# Railway CLIでデータベースに接続
railway connect postgres
```

### 5. メリット

#### PostgreSQL使用時
- ✅ **永続化**: サービス再起動後もデータが保持される
- ✅ **スケーラビリティ**: 複数のインスタンスでデータを共有
- ✅ **信頼性**: トランザクションサポート
- ✅ **バックアップ**: Railwayが自動バックアップ

#### SQLite使用時
- ⚠️ **一時的**: サービス再起動でデータが失われる可能性
- ⚠️ **単一インスタンス**: 複数インスタンスでデータが共有されない

### 6. トラブルシューティング

#### PostgreSQL接続エラー
```
[init_db] PostgreSQL初期化エラー: connection failed
[init_db] SQLiteにフォールバック
```
→ `DATABASE_URL`の確認、Railwayサービスの状態確認

#### データベーステーブル未作成
```
[PostgreSQLDatabase] PostgreSQL接続完了
```
→ アプリケーション起動時にテーブルが自動作成される

### 7. 推奨設定

#### 本番環境
- **PostgreSQL**: 必須（データ永続化のため）
- **ボリューム**: 不要（PostgreSQLがデータを管理）

#### 開発環境
- **SQLite**: 可能（ローカル開発用）
- **PostgreSQL**: 推奨（本番環境と同じ設定）

## まとめ

PostgreSQLを設定することで：
1. **Google認証トークンが永続化**される
2. **サービス再起動後も認証状態が維持**される
3. **複数のRailwayインスタンスでデータを共有**できる
4. **より堅牢なデータベース運用**が可能になる

**PostgreSQLの設定は必須ではありませんが、本番環境では強く推奨されます。**
