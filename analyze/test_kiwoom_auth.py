"""
키움 REST API 연결 테스트
보유종목 조회 및 출력
"""
import sys
import os
import logging
from datetime import datetime

# 현재 디렉토리를 path에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from kiwoom_api_client import KiwoomAPIClient
from kiwoom_config import KiwoomConfig


def setup_logger():
    """로거 설정"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 포맷터
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    return logger


def test_token():
    """토큰 발급 테스트"""
    print("=" * 60)
    print("🔐 토큰 발급 테스트")
    print("=" * 60)

    try:
        client = KiwoomAPIClient()
        token = client.get_access_token()

        if token:
            print(f"✅ 토큰 발급 성공")
            print(f"   토큰: {token[:20]}...{token[-20:]}")
            return True
        else:
            print("❌ 토큰 발급 실패 - 토큰이 None입니다")
            return False

    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_account_balance():
    """계좌 잔고 조회 테스트"""
    print("\n" + "=" * 60)
    print("💰 계좌 잔고 조회 테스트")
    print("=" * 60)
    
    try:
        client = KiwoomAPIClient()
        config = client.config
        enabled_accounts = config.get_enabled_accounts()
        
        if not enabled_accounts:
            print("⚠️ 활성화된 계좌가 없습니다.")
            return False
        
        for alias, account_info in enabled_accounts.items():
            account_no = account_info['account_no']
            description = account_info['description']
            
            print(f"\n📊 {alias} ({description})")
            print(f"   계좌번호: {account_no}")
            
            balance = client.get_account_balance(account_no)
            
            if balance:
                print(f"   총평가금액: {balance.get('total_eval_amount', 0):,.0f}원")
                print(f"   총매입금액: {balance.get('total_purchase_amount', 0):,.0f}원")
                print(f"   총평가손익: {balance.get('total_profit_loss', 0):+,.0f}원")
                print(f"   수익률: {balance.get('profit_loss_rate', 0):+.2f}%")
                print(f"   예수금: {balance.get('deposit', 0):,.0f}원")
                print(f"   보유종목수: {balance.get('holdings_count', 0)}개")
            else:
                print("   ⚠️ 잔고 조회 실패")
        
        return True
        
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        return False


def test_holdings():
    """보유종목 조회 테스트"""
    print("\n" + "=" * 60)
    print("📈 보유종목 조회 테스트")
    print("=" * 60)
    
    try:
        client = KiwoomAPIClient()
        
        # 전체 계좌 조회
        df = client.get_holdings_all()
        
        if df.empty:
            print("⚠️ 보유종목이 없습니다.")
            return True
        
        print(f"\n✅ 총 {len(df)}개 종목 보유")
        print(f"   계좌 수: {df['account_alias'].nunique()}개")
        
        # 계좌별 출력
        for alias in df['account_alias'].unique():
            account_df = df[df['account_alias'] == alias]
            
            print(f"\n{'=' * 60}")
            print(f"📌 계좌: {alias}")
            print(f"{'=' * 60}")
            
            for _, row in account_df.iterrows():
                print(f"\n종목코드: {row['stock_code']}")
                print(f"종목명: {row['stock_name']}")
                print(f"보유수량: {row['quantity']:,}주")
                print(f"평균단가: {row['avg_price']:,.0f}원")
                print(f"현재가: {row['current_price']:,.0f}원")
                print(f"평가금액: {row['eval_amount']:,.0f}원")
                print(f"평가손익: {row['profit_loss']:+,.0f}원 ({row['profit_rate']:+.2f}%)")
            
            # 계좌 합계
            total_eval = account_df['eval_amount'].sum()
            total_profit = account_df['profit_loss'].sum()
            
            print(f"\n{'-' * 60}")
            print(f"계좌 합계:")
            print(f"  총평가금액: {total_eval:,.0f}원")
            print(f"  총평가손익: {total_profit:+,.0f}원")
        
        # 전체 합계
        print(f"\n{'=' * 60}")
        print(f"📊 전체 합계")
        print(f"{'=' * 60}")
        print(f"총평가금액: {df['eval_amount'].sum():,.0f}원")
        print(f"총평가손익: {df['profit_loss'].sum():+,.0f}원")
        
        return True
        
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_current_price():
    """현재가 조회 테스트"""
    print("\n" + "=" * 60)
    print("💹 현재가 조회 테스트")
    print("=" * 60)
    
    # 테스트할 종목 (삼성전자)
    test_stock = "005930"
    
    try:
        client = KiwoomAPIClient()
        
        print(f"\n종목코드: {test_stock}")
        current_price = client.get_current_price(test_stock)
        
        if current_price:
            print(f"✅ 현재가: {current_price:,.0f}원")
            return True
        else:
            print("❌ 현재가 조회 실패")
            return False
            
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
        return False


def main():
    """메인 실행 함수"""
    print("\n")
    print("*" * 60)
    print("  키움 REST API 연결 테스트")
    print("*" * 60)
    print(f"  실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("*" * 60)
    
    # 로거 설정
    logger = setup_logger()
    
    # 설정 검증
    try:
        config = KiwoomConfig()
        config.validate_config()
        print("\n✅ 설정 검증 완료")
        print(f"   APP_KEY: {config.APP_KEY[:10]}...{config.APP_KEY[-10:]}" if config.APP_KEY else "   APP_KEY: 미설정")
        print(f"   활성 계좌: {len(config.get_enabled_accounts())}개")
    except FileNotFoundError as e:
        print(f"\n❌ 설정 파일 오류: {e}")
        print("\n💡 config.yaml 파일에 kiwoom 섹션을 추가해주세요.")
        return
    except Exception as e:
        print(f"\n❌ 설정 오류: {e}")
        print("\n💡 config.yaml 파일의 kiwoom 섹션을 확인해주세요:")
        print("   - app_key")
        print("   - app_secret")
        print("   - accounts (최소 1개 계좌 enabled: true)")
        return
    
    # 테스트 실행
    tests = [
        ("토큰 발급", test_token),
        ("계좌 잔고", test_account_balance),
        ("보유종목", test_holdings),
        ("현재가", test_current_price),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} 테스트 중 예외 발생: {e}")
            results.append((test_name, False))
    
    # 결과 요약
    print("\n\n" + "=" * 60)
    print("📋 테스트 결과 요약")
    print("=" * 60)
    
    for test_name, result in results:
        status = "✅ 성공" if result else "❌ 실패"
        print(f"{test_name:15s}: {status}")
    
    success_count = sum(1 for _, result in results if result)
    total_count = len(results)
    
    print(f"\n총 {total_count}개 테스트 중 {success_count}개 성공")
    
    if success_count == total_count:
        print("\n🎉 모든 테스트 통과!")
    else:
        print("\n⚠️ 일부 테스트 실패")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
