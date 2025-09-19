#!/usr/bin/env python3
"""
단계별 import 테스트
"""

import os
import sys

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
trading_system_path = os.path.join(parent_dir, 'trading_system')

print(f"📁 현재 디렉토리: {current_dir}")
print(f"📁 trading_system 경로: {trading_system_path}")
print(f"📁 경로 존재 여부: {os.path.exists(trading_system_path)}")

if os.path.exists(trading_system_path):
    sys.path.insert(0, trading_system_path)
    print(f"✅ sys.path에 추가됨")
    print(f"📋 sys.path: {sys.path[:3]}...")  # 첫 3개만 출력

# 1단계: data 모듈 테스트
try:
    print("\n1️⃣ data 모듈 import 테스트...")
    import data
    print("✅ data 모듈 import 성공")
    
    print(f"📁 data 모듈 경로: {data.__file__}")
    print(f"📋 data 모듈 내용: {dir(data)}")
    
except ImportError as e:
    print(f"❌ data 모듈 import 실패: {e}")

# 2단계: kis_api_client 모듈 테스트
try:
    print("\n2️⃣ kis_api_client 모듈 import 테스트...")
    from data import kis_api_client
    print("✅ kis_api_client 모듈 import 성공")
    
    print(f"📋 kis_api_client 모듈 내용: {[x for x in dir(kis_api_client) if not x.startswith('_')]}")
    
except ImportError as e:
    print(f"❌ kis_api_client 모듈 import 실패: {e}")

# 3단계: KISAPIClient 클래스 테스트
try:
    print("\n3️⃣ KISAPIClient 클래스 import 테스트...")
    from data.kis_api_client import KISAPIClient
    print("✅ KISAPIClient 클래스 import 성공")
    
    print(f"📋 KISAPIClient 클래스: {KISAPIClient}")
    
except ImportError as e:
    print(f"❌ KISAPIClient 클래스 import 실패: {e}")

# 4단계: strategy 모듈 테스트
try:
    print("\n4️⃣ strategy 모듈 import 테스트...")
    import strategy
    print("✅ strategy 모듈 import 성공")
    
    print(f"📋 strategy 모듈 내용: {dir(strategy)}")
    
except ImportError as e:
    print(f"❌ strategy 모듈 import 실패: {e}")

# 5단계: TechnicalIndicators 클래스 테스트
try:
    print("\n5️⃣ TechnicalIndicators 클래스 import 테스트...")
    from strategy.technical_indicators import TechnicalIndicators
    print("✅ TechnicalIndicators 클래스 import 성공")
    
    # 메서드 확인
    methods = [method for method in dir(TechnicalIndicators) if not method.startswith('_')]
    print(f"📋 TechnicalIndicators 메서드들: {methods}")
    
    # detect_macd_golden_cross 메서드 확인
    if hasattr(TechnicalIndicators, 'detect_macd_golden_cross'):
        print("✅ detect_macd_golden_cross 메서드 존재")
    else:
        print("❌ detect_macd_golden_cross 메서드 없음")
    
except ImportError as e:
    print(f"❌ TechnicalIndicators 클래스 import 실패: {e}")

print("\n✅ 단계별 테스트 완료")
