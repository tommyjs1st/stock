"""
급락 매수 전략 테스트 스크립트
실제 매매 없이 로직만 테스트
"""
import os
import sys

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# analyze 디렉토리 추가
analyze_dir = os.path.join(os.path.dirname(current_dir), 'analyze')
if analyze_dir not in sys.path:
    sys.path.insert(0, analyze_dir)

from config.config_manager import ConfigManager
from data.kis_api_client import KISAPIClient
from db_manager import DBManager
import yaml

def test_config():
    """설정 파일 확인"""
    print("\n" + "="*60)
    print("1️⃣ 설정 파일 확인")
    print("="*60)

    try:
        config_manager = ConfigManager()
        print("✅ config.yaml 로드 성공")

        # KIS 설정 확인
        kis_config = config_manager.get_kis_config()
        print(f"✅ KIS API 설정 확인")
        print(f"   - Base URL: {kis_config.get('base_url')}")
        print(f"   - Account: {kis_config.get('account_no')}")

        # DB 설정 확인
        db_config = config_manager.get_database_config()
        print(f"✅ DB 설정 확인")
        print(f"   - Host: {db_config.get('host')}")
        print(f"   - Database: {db_config.get('database')}")

        return True
    except Exception as e:
        print(f"❌ 설정 확인 실패: {e}")
        return False

def test_db_connection():
    """DB 연결 테스트"""
    print("\n" + "="*60)
    print("2️⃣ DB 연결 테스트")
    print("="*60)

    try:
        config_manager = ConfigManager()
        db_config = config_manager.get_database_config()

        import logging
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)

        db_manager = DBManager(db_config, logger)

        if db_manager.connect():
            print("✅ DB 연결 성공")

            # 테이블 확인
            db_manager.cursor.execute("SHOW TABLES LIKE 'daily_stock_prices'")
            result = db_manager.cursor.fetchone()

            if result:
                print("✅ daily_stock_prices 테이블 존재")

                # 데이터 개수 확인
                db_manager.cursor.execute("SELECT COUNT(*) as cnt FROM daily_stock_prices")
                count = db_manager.cursor.fetchone()
                print(f"✅ 저장된 일봉 데이터: {count['cnt']:,}건")

                # 최근 데이터 확인
                db_manager.cursor.execute("""
                    SELECT MAX(trade_date) as latest_date
                    FROM daily_stock_prices
                """)
                latest = db_manager.cursor.fetchone()
                print(f"✅ 최근 데이터 날짜: {latest['latest_date']}")

            else:
                print("⚠️ daily_stock_prices 테이블 없음")
                print("   → daily_collector.py를 먼저 실행하세요")

            db_manager.disconnect()
            return True
        else:
            print("❌ DB 연결 실패")
            return False

    except Exception as e:
        print(f"❌ DB 테스트 실패: {e}")
        return False

def test_api_connection():
    """API 연결 테스트"""
    print("\n" + "="*60)
    print("3️⃣ KIS API 연결 테스트")
    print("="*60)

    try:
        config_manager = ConfigManager()
        kis_config = config_manager.get_kis_config()

        api_client = KISAPIClient(
            app_key=kis_config['app_key'],
            app_secret=kis_config['app_secret'],
            base_url=kis_config['base_url'],
            account_no=kis_config['account_no']
        )

        # 삼성전자 현재가 조회 테스트
        print("테스트: 삼성전자(005930) 현재가 조회...")
        price_data = api_client.get_current_price('005930')

        if price_data and price_data.get('output'):
            current_price = price_data['output'].get('stck_prpr')
            print(f"✅ API 연결 성공")
            print(f"   - 삼성전자 현재가: {int(current_price):,}원")
            return True
        else:
            print("❌ API 응답 없음")
            return False

    except Exception as e:
        print(f"❌ API 테스트 실패: {e}")
        return False

def test_previous_close_data():
    """전일 종가 데이터 테스트"""
    print("\n" + "="*60)
    print("4️⃣ 전일 종가 데이터 확인")
    print("="*60)

    try:
        config_manager = ConfigManager()
        db_config = config_manager.get_database_config()

        import logging
        logger = logging.getLogger(__name__)

        db_manager = DBManager(db_config, logger)

        if not db_manager.connect():
            print("❌ DB 연결 실패")
            return False

        # 테스트용 종목들
        test_codes = ['005930', '000660', '035420', '005380']

        print("테스트 종목: 삼성전자, SK하이닉스, NAVER, 현대차")
        success_count = 0

        for code in test_codes:
            daily_data = db_manager.get_daily_prices(code, days=2)

            if daily_data and len(daily_data) >= 1:
                latest = daily_data[-1]
                close_price = latest.get('stck_clpr')
                trade_date = latest.get('stck_bsop_date')

                print(f"✅ {code}: {trade_date} 종가 {close_price:,}원")
                success_count += 1
            else:
                print(f"⚠️ {code}: 데이터 없음")

        db_manager.disconnect()

        if success_count > 0:
            print(f"\n✅ 전일 종가 데이터 {success_count}/{len(test_codes)}개 확인")
            return True
        else:
            print("\n❌ 전일 종가 데이터 없음")
            print("   → daily_collector.py를 먼저 실행하세요")
            return False

    except Exception as e:
        print(f"❌ 전일 종가 테스트 실패: {e}")
        return False

def test_exclude_list():
    """제외 목록 확인"""
    print("\n" + "="*60)
    print("5️⃣ 제외 종목 목록 확인")
    print("="*60)

    exclude_file = "exclude_stocks.json"

    if os.path.exists(exclude_file):
        try:
            import json
            with open(exclude_file, 'r', encoding='utf-8') as f:
                exclude_list = json.load(f)

            print(f"✅ 제외 종목 파일 존재")
            print(f"   - 제외 종목 수: {len(exclude_list)}개")
            if exclude_list:
                print(f"   - 제외 종목: {', '.join(exclude_list)}")
            return True
        except Exception as e:
            print(f"⚠️ 제외 종목 파일 읽기 실패: {e}")
            return False
    else:
        print(f"⚠️ 제외 종목 파일 없음 ({exclude_file})")
        print("   → 모든 종목 모니터링 (권장: 파일 생성)")
        return True

def main():
    """메인 테스트 실행"""
    print("\n" + "="*60)
    print("🧪 급락 매수 전략 테스트")
    print("="*60)

    results = []

    # 1. 설정 확인
    results.append(("설정 파일", test_config()))

    # 2. DB 연결
    results.append(("DB 연결", test_db_connection()))

    # 3. API 연결
    results.append(("API 연결", test_api_connection()))

    # 4. 전일 종가 데이터
    results.append(("전일 종가", test_previous_close_data()))

    # 5. 제외 목록
    results.append(("제외 목록", test_exclude_list()))

    # 결과 요약
    print("\n" + "="*60)
    print("📊 테스트 결과 요약")
    print("="*60)

    for name, result in results:
        status = "✅ 통과" if result else "❌ 실패"
        print(f"{status} - {name}")

    success_count = sum(1 for _, r in results if r)
    total_count = len(results)

    print("\n" + "="*60)

    if success_count == total_count:
        print("🎉 모든 테스트 통과!")
        print("✅ 프로그램 실행 준비 완료")
        print("\n실행 명령:")
        print("  python3 sharp_decline_trader.py")
    else:
        print(f"⚠️ {total_count - success_count}개 테스트 실패")
        print("❌ 실패한 항목을 먼저 해결하세요")

        if not results[1][1] or not results[3][1]:  # DB나 전일종가 실패
            print("\n💡 해결 방법:")
            print("  cd /Users/jsshin/RESTAPI/analyze")
            print("  python daily_collector.py --daily")

    print("="*60 + "\n")

if __name__ == "__main__":
    main()
