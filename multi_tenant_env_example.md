# マルチテナント対応環境変数設定例

## Railwayでの環境変数設定

### 1. マルチチャネル設定（推奨）
```json
MULTI_CHANNEL_CONFIGS={
  "U6c6dc3b40ae2418a20468e400405838a": {
    "access_token": "LINE_CHANNEL_ACCESS_TOKEN_1",
    "secret": "LINE_CHANNEL_SECRET_1"
  },
  "U7d7dc3b40ae2418a20468e400405838b": {
    "access_token": "LINE_CHANNEL_ACCESS_TOKEN_2", 
    "secret": "LINE_CHANNEL_SECRET_2"
  }
}
```

### 2. 従来の単一チャネル設定（後方互換）
```
LINE_CHANNEL_ACCESS_TOKEN=your_access_token
LINE_CHANNEL_SECRET=your_secret
```

## 設定手順

### Railwayダッシュボードで設定
1. **Variables**タブを開く
2. 新しい環境変数を追加:
   - 名前: `MULTI_CHANNEL_CONFIGS`
   - 値: 上記のJSON形式で設定

### 各LINE公式アカウントの設定
1. LINE Developersコンソールで各アカウントの設定を確認
2. Webhook URLを同じRailwayサービスに設定
3. 各アカウントの`destination`（チャネルID）を取得

## チャネルIDの取得方法
LINE Developersコンソールの「Basic settings」で「Channel ID」を確認できます。

## 注意事項
- 各LINEアカウントのWebhook URLは同じRailwayサービスを指す必要があります
- 環境変数のJSONは一行で設定してください（改行なし）
- チャネルIDは正確に設定してください（大文字小文字を区別）
