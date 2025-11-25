"""
タイムゾーンユーティリティ
全てのdatetime操作でJSTを使用するためのヘルパー関数
"""
from datetime import datetime
import pytz


def get_jst():
    """日本時間のタイムゾーンを取得"""
    return pytz.timezone('Asia/Tokyo')


def get_jst_now():
    """現在の日本時間を取得（タイムゾーン対応）"""
    return datetime.now(get_jst())


def to_jst(dt: datetime):
    """datetimeオブジェクトをJSTに変換"""
    jst = get_jst()
    if dt.tzinfo is None:
        # ナイーブなdatetimeの場合、JSTとして扱う
        return jst.localize(dt)
    else:
        # 既にタイムゾーン情報がある場合、JSTに変換
        return dt.astimezone(jst)
