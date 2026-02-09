"""
데이터 수집 상태 확인 프로그램
daily_collector와 minute_collector로 수집한 데이터의 현황을 확인

사용법:
  python check_collection_status.py                    # 전체 현황 확인
  python check_collection_status.py --daily            # 일봉 데이터만 확인
  python check_collection_status.py --minute           # 분봉 데이터만 확인
  python check_collection_status.py --detailed         # 상세 리포트
  python check_collection_status.py --stock 005930     # 특정 종목 확인
"""
import sys
import argparse
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
import pymysql
import yaml
from collections import defaultdict


class CollectionStatusChecker:
    """데이터 수집 상태 확인 클래스"""

    def __init__(self, config_path="config.yaml"):
        """초기화"""
        self.config = self.load_config(config_path)
        self.db_config = self.config.get('database', {})
        self.connection = None
        self.cursor = None

    def load_config(self, config_path: str) -> dict:
        """설정 파일 로드"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return config
        except FileNotFoundError:
            print(f"❌ 설정 파일 {config_path}을 찾을 수 없습니다.")
            sys.exit(1)
        except Exception as e:
            print(f"❌ 설정 파일 로드 실패: {e}")
            sys.exit(1)

    def connect(self) -> bool:
        """DB 연결"""
        try:
            self.connection = pymysql.connect(
                host=self.db_config.get('host', 'localhost'),
                port=self.db_config.get('port', 3306),
                user=self.db_config.get('user'),
                password=self.db_config.get('password'),
                database=self.db_config.get('database'),
                charset=self.db_config.get('charset', 'utf8mb4'),
                cursorclass=pymysql.cursors.DictCursor
            )
            self.cursor = self.connection.cursor()
            return True
        except Exception as e:
            print(f"❌ DB 연결 실패: {e}")
            return False

    def disconnect(self):
        """DB 연결 해제"""
        try:
            if self.cursor:
                self.cursor.close()
            if self.connection:
                self.connection.close()
        except Exception as e:
            print(f"⚠️ 연결 해제 중 오류: {e}")

    def check_daily_data_overview(self) -> Dict:
        """일봉 데이터 전체 현황"""
        try:
            # 기본 통계
            self.cursor.execute("""
                SELECT
                    COUNT(DISTINCT stock_code) as total_stocks,
                    COUNT(*) as total_records,
                    MIN(trade_date) as min_date,
                    MAX(trade_date) as max_date
                FROM daily_stock_prices
            """)
            overview = self.cursor.fetchone()

            # 최근 7일 데이터 수
            self.cursor.execute("""
                SELECT COUNT(*) as recent_count
                FROM daily_stock_prices
                WHERE trade_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            """)
            recent = self.cursor.fetchone()
            overview['recent_7days_count'] = recent['recent_count']

            # 오늘 데이터 수
            self.cursor.execute("""
                SELECT COUNT(*) as today_count
                FROM daily_stock_prices
                WHERE trade_date = CURDATE()
            """)
            today = self.cursor.fetchone()
            overview['today_count'] = today['today_count']

            return overview

        except Exception as e:
            print(f"❌ 일봉 데이터 조회 실패: {e}")
            return {}

    def check_minute_data_overview(self) -> Dict:
        """분봉 데이터 전체 현황"""
        try:
            # 기본 통계
            self.cursor.execute("""
                SELECT
                    COUNT(DISTINCT stock_code) as total_stocks,
                    COUNT(*) as total_records,
                    MIN(trade_datetime) as min_datetime,
                    MAX(trade_datetime) as max_datetime
                FROM minute_stock_prices
            """)
            overview = self.cursor.fetchone()

            # 오늘 데이터 수
            self.cursor.execute("""
                SELECT COUNT(*) as today_count
                FROM minute_stock_prices
                WHERE DATE(trade_datetime) = CURDATE()
            """)
            today = self.cursor.fetchone()
            overview['today_count'] = today['today_count']

            # 최근 1시간 데이터 수
            self.cursor.execute("""
                SELECT COUNT(*) as recent_hour_count
                FROM minute_stock_prices
                WHERE trade_datetime >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
            """)
            recent = self.cursor.fetchone()
            overview['recent_hour_count'] = recent['recent_hour_count']

            return overview

        except Exception as e:
            print(f"❌ 분봉 데이터 조회 실패: {e}")
            return {}

    def check_batch_history(self, limit: int = 10) -> List[Dict]:
        """배치 실행 이력 확인"""
        try:
            self.cursor.execute(f"""
                SELECT
                    batch_type,
                    start_time,
                    end_time,
                    status,
                    total_stocks,
                    success_count,
                    fail_count,
                    TIMESTAMPDIFF(SECOND, start_time, end_time) as elapsed_seconds
                FROM batch_history
                ORDER BY start_time DESC
                LIMIT {limit}
            """)
            return self.cursor.fetchall()

        except Exception as e:
            print(f"❌ 배치 이력 조회 실패: {e}")
            return []

    def check_daily_per_stock(self) -> List[Dict]:
        """종목별 일봉 데이터 수"""
        try:
            self.cursor.execute("""
                SELECT
                    d.stock_code,
                    s.stock_name,
                    COUNT(*) as record_count,
                    MIN(d.trade_date) as first_date,
                    MAX(d.trade_date) as last_date,
                    DATEDIFF(MAX(d.trade_date), MIN(d.trade_date)) + 1 as date_range_days
                FROM daily_stock_prices d
                LEFT JOIN stock_info s ON d.stock_code = s.stock_code
                GROUP BY d.stock_code, s.stock_name
                ORDER BY record_count DESC
                LIMIT 20
            """)
            return self.cursor.fetchall()

        except Exception as e:
            print(f"❌ 종목별 일봉 조회 실패: {e}")
            return []

    def check_minute_per_stock(self) -> List[Dict]:
        """종목별 분봉 데이터 수 (오늘 기준)"""
        try:
            self.cursor.execute("""
                SELECT
                    m.stock_code,
                    s.stock_name,
                    COUNT(*) as record_count,
                    MIN(m.trade_datetime) as first_datetime,
                    MAX(m.trade_datetime) as last_datetime
                FROM minute_stock_prices m
                LEFT JOIN stock_info s ON m.stock_code COLLATE utf8mb4_unicode_ci = s.stock_code
                WHERE DATE(m.trade_datetime) = CURDATE()
                GROUP BY m.stock_code, s.stock_name
                ORDER BY record_count DESC
                LIMIT 20
            """)
            return self.cursor.fetchall()

        except Exception as e:
            print(f"❌ 종목별 분봉 조회 실패: {e}")
            return []

    def check_data_quality(self) -> Dict:
        """데이터 품질 체크"""
        quality = {}

        try:
            # 일봉: 종가가 0이거나 NULL인 레코드
            self.cursor.execute("""
                SELECT COUNT(*) as count
                FROM daily_stock_prices
                WHERE close_price IS NULL OR close_price = 0
            """)
            quality['daily_invalid_price'] = self.cursor.fetchone()['count']

            # 일봉: 거래량이 0인 레코드
            self.cursor.execute("""
                SELECT COUNT(*) as count
                FROM daily_stock_prices
                WHERE volume = 0
            """)
            quality['daily_zero_volume'] = self.cursor.fetchone()['count']

            # 분봉: 종가가 0이거나 NULL인 레코드
            self.cursor.execute("""
                SELECT COUNT(*) as count
                FROM minute_stock_prices
                WHERE close_price IS NULL OR close_price = 0
            """)
            quality['minute_invalid_price'] = self.cursor.fetchone()['count']

            # 분봉: 거래량이 0인 레코드
            self.cursor.execute("""
                SELECT COUNT(*) as count
                FROM minute_stock_prices
                WHERE volume = 0
            """)
            quality['minute_zero_volume'] = self.cursor.fetchone()['count']

            return quality

        except Exception as e:
            print(f"❌ 데이터 품질 체크 실패: {e}")
            return {}

    def check_missing_dates(self, days: int = 7) -> List[Dict]:
        """최근 N일 중 데이터가 누락된 날짜 체크"""
        try:
            # 최근 N일의 모든 날짜 생성 (주말 제외)
            self.cursor.execute(f"""
                SELECT trade_date, COUNT(DISTINCT stock_code) as stock_count
                FROM daily_stock_prices
                WHERE trade_date >= DATE_SUB(CURDATE(), INTERVAL {days} DAY)
                GROUP BY trade_date
                ORDER BY trade_date DESC
            """)
            return self.cursor.fetchall()

        except Exception as e:
            print(f"❌ 누락 날짜 체크 실패: {e}")
            return []

    def check_specific_stock(self, stock_code: str) -> Dict:
        """특정 종목 상세 확인"""
        result = {
            'stock_code': stock_code,
            'daily': {},
            'minute': {}
        }

        try:
            # 종목 정보
            self.cursor.execute("""
                SELECT stock_code, stock_name, market_cap, updated_at
                FROM stock_info
                WHERE stock_code = %s
            """, (stock_code,))
            stock_info = self.cursor.fetchone()
            result['stock_info'] = stock_info

            # 일봉 통계
            self.cursor.execute("""
                SELECT
                    COUNT(*) as record_count,
                    MIN(trade_date) as first_date,
                    MAX(trade_date) as last_date
                FROM daily_stock_prices
                WHERE stock_code = %s
            """, (stock_code,))
            result['daily'] = self.cursor.fetchone()

            # 분봉 통계 (최근 7일)
            self.cursor.execute("""
                SELECT
                    COUNT(*) as record_count,
                    MIN(trade_datetime) as first_datetime,
                    MAX(trade_datetime) as last_datetime
                FROM minute_stock_prices
                WHERE stock_code COLLATE utf8mb4_unicode_ci = %s
                  AND trade_datetime >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            """, (stock_code,))
            result['minute'] = self.cursor.fetchone()

            # 오늘 분봉 수
            self.cursor.execute("""
                SELECT COUNT(*) as today_minute_count
                FROM minute_stock_prices
                WHERE stock_code COLLATE utf8mb4_unicode_ci = %s
                  AND DATE(trade_datetime) = CURDATE()
            """, (stock_code,))
            result['minute']['today_count'] = self.cursor.fetchone()['today_minute_count']

            return result

        except Exception as e:
            print(f"❌ 종목 조회 실패: {e}")
            return result

    def print_separator(self, char="=", length=80):
        """구분선 출력"""
        print(char * length)

    def print_daily_report(self):
        """일봉 데이터 리포트 출력"""
        print("\n")
        self.print_separator("=")
        print("📊 일봉 데이터 수집 현황")
        self.print_separator("=")

        overview = self.check_daily_data_overview()
        if overview:
            print(f"\n✅ 전체 통계:")
            print(f"   - 총 종목 수: {overview.get('total_stocks', 0):,}개")
            print(f"   - 총 레코드 수: {overview.get('total_records', 0):,}건")
            print(f"   - 데이터 기간: {overview.get('min_date')} ~ {overview.get('max_date')}")
            print(f"   - 오늘 수집: {overview.get('today_count', 0):,}건")
            print(f"   - 최근 7일 수집: {overview.get('recent_7days_count', 0):,}건")

        # 최근 날짜별 수집 현황
        print(f"\n📅 최근 7일 수집 현황:")
        missing_dates = self.check_missing_dates(7)
        if missing_dates:
            for row in missing_dates:
                trade_date = row['trade_date']
                stock_count = row['stock_count']
                # 주말 체크
                weekday = trade_date.weekday()
                day_name = ['월', '화', '수', '목', '금', '토', '일'][weekday]
                indicator = "✅" if stock_count > 0 else "❌"
                print(f"   {indicator} {trade_date} ({day_name}): {stock_count:,}개 종목")

        # 종목별 TOP 10
        print(f"\n🏆 데이터 보유 TOP 10 종목:")
        per_stock = self.check_daily_per_stock()
        if per_stock:
            for idx, row in enumerate(per_stock[:10], 1):
                print(f"   {idx:2d}. {row['stock_name'] or row['stock_code']}({row['stock_code']}): "
                      f"{row['record_count']:,}건 "
                      f"({row['first_date']} ~ {row['last_date']})")

    def print_minute_report(self):
        """분봉 데이터 리포트 출력"""
        print("\n")
        self.print_separator("=")
        print("⏱️  분봉 데이터 수집 현황")
        self.print_separator("=")

        overview = self.check_minute_data_overview()
        if overview:
            print(f"\n✅ 전체 통계:")
            print(f"   - 총 종목 수: {overview.get('total_stocks', 0):,}개")
            print(f"   - 총 레코드 수: {overview.get('total_records', 0):,}건")

            min_dt = overview.get('min_datetime')
            max_dt = overview.get('max_datetime')
            if min_dt and max_dt:
                print(f"   - 데이터 기간: {min_dt} ~ {max_dt}")

            print(f"   - 오늘 수집: {overview.get('today_count', 0):,}건")
            print(f"   - 최근 1시간: {overview.get('recent_hour_count', 0):,}건")

        # 오늘 종목별 TOP 10
        print(f"\n🏆 오늘 수집 TOP 10 종목:")
        per_stock = self.check_minute_per_stock()
        if per_stock:
            for idx, row in enumerate(per_stock[:10], 1):
                first_dt = row['first_datetime']
                last_dt = row['last_datetime']
                print(f"   {idx:2d}. {row['stock_name'] or row['stock_code']}({row['stock_code']}): "
                      f"{row['record_count']:,}건 "
                      f"({first_dt.strftime('%H:%M') if first_dt else '?'} ~ "
                      f"{last_dt.strftime('%H:%M') if last_dt else '?'})")
        else:
            print("   ⚠️ 오늘 수집된 분봉 데이터가 없습니다.")

    def print_batch_report(self):
        """배치 실행 이력 리포트"""
        print("\n")
        self.print_separator("=")
        print("📜 최근 배치 실행 이력 (최근 10건)")
        self.print_separator("=")

        history = self.check_batch_history(10)
        if history:
            print(f"\n{'타입':<20} {'시작시간':<20} {'상태':<10} {'성공/실패':<15} {'소요시간'}")
            self.print_separator("-")
            for row in history:
                batch_type = row['batch_type']
                start_time = row['start_time'].strftime('%Y-%m-%d %H:%M:%S') if row['start_time'] else 'N/A'
                status = row['status']
                success = row['success_count'] or 0
                fail = row['fail_count'] or 0
                elapsed = row['elapsed_seconds']

                status_icon = "✅" if status == 'SUCCESS' else "❌" if status == 'FAIL' else "⏳"
                elapsed_str = f"{elapsed}초" if elapsed else 'N/A'

                print(f"{status_icon} {batch_type:<18} {start_time:<20} {status:<10} {success:>3}/{fail:<3} 종목     {elapsed_str:>10}")
        else:
            print("   ℹ️ 배치 실행 이력이 없습니다.")

    def print_quality_report(self):
        """데이터 품질 리포트"""
        print("\n")
        self.print_separator("=")
        print("🔍 데이터 품질 체크")
        self.print_separator("=")

        quality = self.check_data_quality()
        if quality:
            print(f"\n일봉 데이터:")
            daily_invalid = quality.get('daily_invalid_price', 0)
            daily_zero_vol = quality.get('daily_zero_volume', 0)

            print(f"   {'✅' if daily_invalid == 0 else '⚠️'} 잘못된 가격(0 또는 NULL): {daily_invalid:,}건")
            print(f"   {'✅' if daily_zero_vol == 0 else 'ℹ️'} 거래량 0: {daily_zero_vol:,}건 (공휴일/휴장일 가능)")

            print(f"\n분봉 데이터:")
            minute_invalid = quality.get('minute_invalid_price', 0)
            minute_zero_vol = quality.get('minute_zero_volume', 0)

            print(f"   {'✅' if minute_invalid == 0 else '⚠️'} 잘못된 가격(0 또는 NULL): {minute_invalid:,}건")
            print(f"   {'✅' if minute_zero_vol == 0 else 'ℹ️'} 거래량 0: {minute_zero_vol:,}건")

    def print_stock_report(self, stock_code: str):
        """특정 종목 리포트"""
        print("\n")
        self.print_separator("=")
        print(f"🔎 종목 상세 정보: {stock_code}")
        self.print_separator("=")

        result = self.check_specific_stock(stock_code)

        # 종목 정보
        stock_info = result.get('stock_info')
        if stock_info:
            print(f"\n종목명: {stock_info['stock_name']}")
            print(f"시가총액: {stock_info['market_cap']:,}원" if stock_info.get('market_cap') else "시가총액: N/A")
            print(f"최종 업데이트: {stock_info['updated_at']}")
        else:
            print(f"\n⚠️ 종목 정보가 stock_info 테이블에 없습니다.")

        # 일봉 데이터
        daily = result.get('daily', {})
        if daily and daily.get('record_count', 0) > 0:
            print(f"\n📊 일봉 데이터:")
            print(f"   - 레코드 수: {daily['record_count']:,}건")
            print(f"   - 기간: {daily['first_date']} ~ {daily['last_date']}")
        else:
            print(f"\n⚠️ 일봉 데이터가 없습니다.")

        # 분봉 데이터
        minute = result.get('minute', {})
        if minute and minute.get('record_count', 0) > 0:
            print(f"\n⏱️  분봉 데이터 (최근 7일):")
            print(f"   - 레코드 수: {minute['record_count']:,}건")

            first_dt = minute.get('first_datetime')
            last_dt = minute.get('last_datetime')
            if first_dt and last_dt:
                print(f"   - 기간: {first_dt} ~ {last_dt}")

            print(f"   - 오늘 수집: {minute.get('today_count', 0):,}건")
        else:
            print(f"\n⚠️ 분봉 데이터가 없습니다 (최근 7일).")

    def run(self, daily_only=False, minute_only=False, detailed=False, stock_code=None):
        """실행"""
        try:
            if not self.connect():
                return False

            print("\n" + "=" * 80)
            print(f"📈 데이터 수집 상태 점검 리포트")
            print(f"생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 80)

            # 특정 종목 확인
            if stock_code:
                self.print_stock_report(stock_code)
                return True

            # 일봉만 확인
            if daily_only:
                self.print_daily_report()
                if detailed:
                    self.print_quality_report()
                return True

            # 분봉만 확인
            if minute_only:
                self.print_minute_report()
                if detailed:
                    self.print_quality_report()
                return True

            # 전체 확인 (기본)
            self.print_daily_report()
            self.print_minute_report()
            self.print_batch_report()

            if detailed:
                self.print_quality_report()

            print("\n" + "=" * 80)
            print("✅ 리포트 생성 완료")
            print("=" * 80 + "\n")

            return True

        except Exception as e:
            print(f"\n❌ 실행 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            self.disconnect()


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='데이터 수집 상태 확인 프로그램',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 전체 현황 확인
  python check_collection_status.py

  # 일봉 데이터만 확인
  python check_collection_status.py --daily

  # 분봉 데이터만 확인
  python check_collection_status.py --minute

  # 상세 리포트 (데이터 품질 포함)
  python check_collection_status.py --detailed

  # 특정 종목 확인
  python check_collection_status.py --stock 005930
        """
    )

    parser.add_argument(
        '--daily',
        action='store_true',
        help='일봉 데이터만 확인'
    )

    parser.add_argument(
        '--minute',
        action='store_true',
        help='분봉 데이터만 확인'
    )

    parser.add_argument(
        '--detailed',
        action='store_true',
        help='상세 리포트 (데이터 품질 포함)'
    )

    parser.add_argument(
        '--stock',
        type=str,
        metavar='CODE',
        help='특정 종목 코드 확인 (예: 005930)'
    )

    args = parser.parse_args()

    try:
        checker = CollectionStatusChecker()
        success = checker.run(
            daily_only=args.daily,
            minute_only=args.minute,
            detailed=args.detailed,
            stock_code=args.stock
        )

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\n사용자에 의해 중단되었습니다.")
        return 1
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
