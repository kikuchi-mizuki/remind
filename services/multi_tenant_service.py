import os
import json
from typing import Dict, Optional
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi

class MultiTenantService:
    """マルチテナント対応サービスクラス"""
    
    def __init__(self):
        self.channel_configs = self._load_channel_configs()
    
    def _load_channel_configs(self) -> Dict[str, Dict]:
        """チャネル設定を環境変数から読み込み"""
        configs = {}
        
        # 環境変数からマルチチャネル設定を読み込み
        # 形式: MULTI_CHANNEL_CONFIGS={"channel_id_1": {"access_token": "...", "secret": "..."}, ...}
        multi_channel_config = os.getenv('MULTI_CHANNEL_CONFIGS')
        if multi_channel_config:
            try:
                configs = json.loads(multi_channel_config)
                print(f"[MultiTenantService] マルチチャネル設定読み込み: {len(configs)}個のチャネル")
            except Exception as e:
                print(f"[MultiTenantService] マルチチャネル設定読み込みエラー: {e}")
        
        # 従来の単一チャネル設定もサポート
        if not configs:
            single_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
            single_secret = os.getenv('LINE_CHANNEL_SECRET')
            if single_access_token and single_secret:
                # デフォルトチャネルとして設定
                configs['default'] = {
                    'access_token': single_access_token,
                    'secret': single_secret
                }
                print(f"[MultiTenantService] 単一チャネル設定を使用")
        
        return configs
    
    def get_channel_config(self, channel_id: str) -> Optional[Dict]:
        """指定されたチャネルIDの設定を取得"""
        # 直接チャネルIDで検索
        if channel_id in self.channel_configs:
            return self.channel_configs[channel_id]
        
        # デフォルトチャネルを返す
        if 'default' in self.channel_configs:
            return self.channel_configs['default']
        
        print(f"[MultiTenantService] チャネル設定が見つかりません: {channel_id}")
        return None
    
    def get_messaging_api(self, channel_id: str) -> Optional[MessagingApi]:
        """指定されたチャネルIDのMessagingApiクライアントを取得"""
        config = self.get_channel_config(channel_id)
        if not config:
            return None
        
        try:
            configuration = Configuration(access_token=config['access_token'])
            api_client = ApiClient(configuration)
            return MessagingApi(api_client)
        except Exception as e:
            print(f"[MultiTenantService] MessagingApi作成エラー: {e}")
            return None
    
    def get_channel_secret(self, channel_id: str) -> Optional[str]:
        """指定されたチャネルIDのシークレットを取得"""
        config = self.get_channel_config(channel_id)
        if config:
            return config.get('secret')
        return None
    
    def get_all_channel_ids(self) -> list:
        """全てのチャネルIDを取得"""
        return list(self.channel_configs.keys())
    
    def is_multi_tenant(self) -> bool:
        """マルチテナントモードかどうかを判定"""
        return len(self.channel_configs) > 1 or 'default' not in self.channel_configs
