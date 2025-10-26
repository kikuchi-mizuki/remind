#!/usr/bin/env python3
"""
自然言語処理機能のテストスクリプト
"""

import os
import sys
from services.openai_service import OpenAIService

def test_intent_classification():
    """意図分類機能のテスト"""
    print("=== 自然言語処理機能テスト開始 ===")
    
    # OpenAIサービス初期化
    openai_service = OpenAIService()
    
    # テストケース
    test_cases = [
        # キャンセル系
        ("キャンセル", "cancel"),
        ("やめる", "cancel"),
        ("中止", "cancel"),
        ("終了", "cancel"),
        
        # 不完全なタスク
        ("資料作成", "incomplete_task"),
        ("2時間", "incomplete_task"),
        ("会議準備", "incomplete_task"),
        ("30分", "incomplete_task"),
        
        # 完全なタスク
        ("資料作成 2時間", "complete_task"),
        ("会議準備 1時間半", "complete_task"),
        ("新規事業計画 3時間", "complete_task"),
        ("営業資料の見直し 30分", "complete_task"),
        
        # ヘルプ系
        ("使い方を教えて", "help"),
        ("ヘルプ", "help"),
        ("どうやって使うの？", "help"),
        
        # その他
        ("こんにちは", "other"),
        ("ありがとう", "other"),
    ]
    
    success_count = 0
    total_count = len(test_cases)
    
    for message, expected_intent in test_cases:
        print(f"\n--- テスト: '{message}' ---")
        
        try:
            result = openai_service.classify_user_intent(message)
            intent = result.get("intent", "unknown")
            confidence = result.get("confidence", 0.0)
            reason = result.get("reason", "不明")
            
            print(f"期待: {expected_intent}")
            print(f"結果: {intent} (信頼度: {confidence:.2f})")
            print(f"理由: {reason}")
            
            # 信頼度が0.7以上で期待する意図と一致する場合を成功とする
            if confidence >= 0.7 and intent == expected_intent:
                print("✅ 成功")
                success_count += 1
            else:
                print("❌ 失敗")
                
        except Exception as e:
            print(f"❌ エラー: {e}")
    
    print(f"\n=== テスト結果 ===")
    print(f"成功: {success_count}/{total_count}")
    print(f"成功率: {success_count/total_count*100:.1f}%")
    
    return success_count >= total_count * 0.8  # 80%以上で成功とする

if __name__ == "__main__":
    success = test_intent_classification()
    sys.exit(0 if success else 1)
