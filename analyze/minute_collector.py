"""
분봉 데이터 수집 프로그램
키움증권 보유종목에 대한 분봉 데이터를 키움 REST API(ka10080)로 조회하여 DB에 저장
NXT 시간외 거래(15:30~20:00) 포함

사용법:
  python minute_collector.py                  # 보유종목 분봉 수집 (기본)
  python minute_collector.py --count 120      # 분봉 120개 수집
  python minute_collector.py --test           # 테스트 모드 (1종목)
  python minute_collector.py --codes 005930 000660  # 특정 종목 지정
  python minute_collector.py --cleanup        # 오래된 데이터 정리 (30일 이전)
"""
import sys
import os
import time
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import yaml

# 현재 디렉토리 모듈 import
from data_fetcher import DataFetcher
from db_manager import DBManager

# 키움 API 클라이언트
try:
    from kiwoom_api_client import KiwoomAPIClient
    KIWOOM_AVAILABLE = True
except ImportError:
    KIWOOM_AVAILABLE = False


class ConfigManager:
    """설정 관리 클래스"""

    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self.config = {}
        self.load_config()

    def load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)

            if not self.config:
                print(f"config.yaml 파일이 비어있거나 형식이 잘못되었습니다.")
                sys.exit(1)

        except FileNotFoundError:
            print(f"설정 파일 {self.config_path}을 찾을 수 없습니다.")
            sys.exit(1)

    def get_database_config(self):
        db_config = self.config.get('database', {})
        if not db_config:
            print("config.yaml에 'database' 섹션이 없습니다.")
            sys.exit(1)
        return db_config

    def get_minute_collection_config(self):
        """분봉 수집 설정 조회"""
        return self.config.get('minute_collection', {})

    def get_watchlist(self) -> List[str]:
        """관심종목 리스트 조회"""
        minute_config = self.get_minute_collection_config()
        watchlist = minute_config.get('watchlist', [])

        # 빈 항목 제거 및 6자리 종목코드 검증
        valid_watchlist = []
        for code in watchlist:
            code = str(code).strip()
            if code and len(code) == 6 and code.isdigit():
                valid_watchlist.append(code)

        return valid_watchlist

    def is_watchlist_enabled(self) -> bool:
        """관심종목 수집 활성화 여부"""
        minute_config = self.get_minute_collection_config()
        return minute_config.get('collect_watchlist', True)


class MinuteDataCollector:
    """분봉 데이터 수집 클래스"""

    def __init__(self, minute_count: int = 660, test_mode: bool = False, specific_codes: List[str] = None):
        """
        초기화

        Args:
            minute_count: 수집할 분봉 개수 (기본 120개 = 2시간)
            test_mode: 테스트 모드 (1종목만)
            specific_codes: 특정 종목코드 리스트 (None이면 보유종목 조회)
        """
        self.setup_logger()

        self.minute_count = minute_count
        self.test_mode = test_mode
        self.specific_codes = specific_codes

        if test_mode:
            self.logger.info("테스트 모드 활성화: 1종목만 수집")

        # 설정 로드
        self.config_manager = ConfigManager()
        self.db_config = self.config_manager.get_database_config()

        # 관심종목 설정 로드
        self.watchlist = self.config_manager.get_watchlist()
        self.watchlist_enabled = self.config_manager.is_watchlist_enabled()

        if self.watchlist and self.watchlist_enabled:
            self.logger.info(f"관심종목 {len(self.watchlist)}개 설정됨")

        # DataFetcher 초기화 (KIS API)
        self.data_fetcher = DataFetcher()

        # 키움 API 클라이언트 초기화
        # 분봉 조회(ka10080, NXT 포함)에도 사용하므로 specific_codes 여부와 무관하게 초기화
        self.kiwoom_client = None
        if KIWOOM_AVAILABLE:
            try:
                self.kiwoom_client = KiwoomAPIClient()
                self.logger.info("키움 API 클라이언트 초기화 완료 (분봉 수집용)")
            except Exception as e:
                self.logger.warning(f"키움 API 초기화 실패: {e}")

        # DB 매니저 초기화
        self.db_manager = DBManager(self.db_config, self.logger)

        # 통계
        self.stats = {
            'total_stocks': 0,
            'success_stocks': 0,
            'fail_stocks': 0,
            'total_records': 0,
            'success_records': 0,
            'fail_records': 0
        }

    def setup_logger(self):
        """로거 설정"""
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(log_dir, f"minute_collector_{datetime.now().strftime('%Y%m%d')}.log")

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # 기존 핸들러 제거
        if self.logger.hasHandlers():
            self.logger.handlers.clear()

        # 파일 핸들러
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)

        # 콘솔 핸들러
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 포맷 설정
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def get_holdings(self) -> Dict[str, str]:
        """보유종목 + 관심종목 조회

        Returns:
            Dict[str, str]: {종목코드: 종목명}
        """
        # 특정 종목이 지정된 경우
        if self.specific_codes:
            self.logger.info(f"지정 종목 {len(self.specific_codes)}개 사용")
            return {code: code for code in self.specific_codes}

        holdings = {}

        # 1. 키움 API로 보유종목 조회
        if self.kiwoom_client:
            try:
                self.logger.info("키움 보유종목 조회 중...")

                df = self.kiwoom_client.get_holdings_all()

                if not df.empty:
                    # 종목코드: 종목명 딕셔너리 생성
                    for _, row in df.iterrows():
                        stock_code = row.get('stock_code', '')
                        stock_name = row.get('stock_name', stock_code)
                        if stock_code:
                            holdings[stock_code] = stock_name

                    self.logger.info(f"보유종목 {len(holdings)}개 조회 완료")
                else:
                    self.logger.info("보유종목이 없습니다.")

            except Exception as e:
                self.logger.error(f"보유종목 조회 실패: {e}")
        else:
            self.logger.info("키움 API 사용 불가 - 보유종목 조회 생략")

        # 2. 관심종목 추가 (활성화된 경우)
        if self.watchlist_enabled and self.watchlist:
            self.logger.info(f"관심종목 {len(self.watchlist)}개 추가 중...")

            added_count = 0
            for stock_code in self.watchlist:
                if stock_code not in holdings:
                    # 종목명은 나중에 조회되므로 일단 코드로 저장
                    holdings[stock_code] = f"관심종목_{stock_code}"
                    added_count += 1

            if added_count > 0:
                self.logger.info(f"관심종목 {added_count}개 추가 완료 (중복 {len(self.watchlist) - added_count}개 제외)")

        # 3. 최종 결과
        if not holdings:
            self.logger.warning("수집할 종목이 없습니다. (보유종목 0개, 관심종목 0개)")
            self.logger.warning("config.yaml의 minute_collection.watchlist에 종목을 추가하거나 --codes 옵션을 사용하세요.")

        total = len(holdings)
        self.logger.info(f"총 {total}개 종목 수집 대상")

        return holdings

    def collect_minute_data(self, stock_code: str, stock_name: str) -> List[Dict]:
        """종목별 분봉 데이터 수집 (키움 REST API ka10080, NXT 포함)

        KIS API 대신 키움 REST API를 사용하여 NXT 시간외 거래
        (정규장 마감 15:30 ~ 20:00) 데이터까지 수집합니다.

        Args:
            stock_code: 종목코드
            stock_name: 종목명

        Returns:
            List[Dict]: 분봉 레코드 리스트 (DB 포맷 동일)
        """
        try:
            if not self.kiwoom_client:
                self.logger.error(
                    f"{stock_name}({stock_code}): 키움 API 클라이언트 없음 "
                    f"(kiwoom_api_client 초기화 실패 여부 확인)"
                )
                return []

            records = self.kiwoom_client.get_minute_price_data(
                stock_code, self.minute_count
            )

            if not records:
                self.logger.warning(f"{stock_name}({stock_code}): 분봉 데이터 없음")
                return []

            # stock_code 필드 보정 (get_minute_price_data 내부에서 설정되지만 명시적으로 재확인)
            for r in records:
                r['stock_code'] = stock_code

            self.logger.info(f"{stock_name}({stock_code}): {len(records)}건 수집 (NXT 포함)")
            return records

        except Exception as e:
            self.logger.error(f"{stock_name}({stock_code}) 분봉 수집 실패: {e}")
            return []

    def save_to_db(self, stock_code: str, stock_name: str, records: List[Dict]) -> bool:
        """DB에 데이터 저장

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            records: 분봉 레코드 리스트

        Returns:
            bool: 성공 여부
        """
        try:
            if not records:
                return False

            # 종목 정보 저장 (없으면 추가)
            if not self.db_manager.upsert_stock_info(stock_code, stock_name):
                self.logger.warning(f"{stock_code}: 종목 정보 저장 실패, 계속 진행")

            # 분봉 데이터 저장
            success, fail = self.db_manager.bulk_insert_minute_prices(records)

            self.stats['success_records'] += success
            self.stats['fail_records'] += fail

            self.db_manager.commit()
            return True

        except Exception as e:
            self.logger.error(f"DB 저장 실패 ({stock_code}): {e}")
            self.db_manager.rollback()
            return False

    def run(self):
        """수집 실행"""
        start_time = datetime.now()
        batch_id = 0

        try:
            self.logger.info("=" * 70)
            self.logger.info("분봉 데이터 수집 시작")
            self.logger.info("=" * 70)

            # 장 시간 체크
            now = datetime.now()
            if now.weekday() >= 5:  # 주말
                self.logger.warning("주말에는 분봉 데이터가 업데이트되지 않습니다.")

            # DB 연결
            if not self.db_manager.connect():
                raise Exception("데이터베이스 연결 실패")

            # 테이블 생성 확인
            self.db_manager.create_tables()

            # 배치 시작 기록
            batch_id = self.db_manager.start_batch('MINUTE_COLLECTION')

            # 보유종목 조회
            holdings = self.get_holdings()
            if not holdings:
                self.logger.info("수집할 종목이 없습니다.")
                return True

            # 테스트 모드: 1종목만
            if self.test_mode:
                first_code = list(holdings.keys())[0]
                holdings = {first_code: holdings[first_code]}

            self.stats['total_stocks'] = len(holdings)

            self.logger.info(f"수집 설정: {len(holdings)}개 종목 x {self.minute_count}분봉")

            # 각 종목별 데이터 수집
            for idx, (stock_code, stock_name) in enumerate(holdings.items(), 1):
                try:
                    self.logger.info(f"[{idx}/{len(holdings)}] {stock_name}({stock_code}) 처리 중...")

                    # 분봉 데이터 수집
                    records = self.collect_minute_data(stock_code, stock_name)

                    if records:
                        # DB 저장
                        if self.save_to_db(stock_code, stock_name, records):
                            self.stats['success_stocks'] += 1
                            self.stats['total_records'] += len(records)
                        else:
                            self.stats['fail_stocks'] += 1
                    else:
                        self.stats['fail_stocks'] += 1

                    # API 호출 제한
                    time.sleep(0.2)

                except Exception as e:
                    self.logger.error(f"{stock_name}({stock_code}) 처리 실패: {e}")
                    self.stats['fail_stocks'] += 1
                    continue

            # 결과 출력
            self.print_summary(start_time)

            # 배치 종료 기록
            self.db_manager.end_batch(
                batch_id, 'SUCCESS',
                self.stats['total_stocks'],
                self.stats['success_stocks'],
                self.stats['fail_stocks']
            )

            return True

        except Exception as e:
            self.logger.error(f"수집 실행 실패: {e}")

            if batch_id:
                self.db_manager.end_batch(
                    batch_id, 'FAIL',
                    self.stats['total_stocks'],
                    self.stats['success_stocks'],
                    self.stats['fail_stocks'],
                    str(e)
                )

            return False

        finally:
            self.db_manager.disconnect()

    def cleanup_old_data(self, days: int = 30):
        """오래된 분봉 데이터 정리

        Args:
            days: 보관 일수 (기본 30일)
        """
        try:
            self.logger.info(f"오래된 분봉 데이터 정리 ({days}일 이전)")

            if not self.db_manager.connect():
                raise Exception("DB 연결 실패")

            deleted = self.db_manager.delete_old_minute_prices(days)
            self.logger.info(f"삭제 완료: {deleted}건")

        except Exception as e:
            self.logger.error(f"데이터 정리 실패: {e}")

        finally:
            self.db_manager.disconnect()

    def print_summary(self, start_time: datetime):
        """결과 요약 출력"""
        elapsed = datetime.now() - start_time

        self.logger.info("\n" + "=" * 70)
        self.logger.info("분봉 수집 결과")
        self.logger.info("=" * 70)
        self.logger.info(f"소요 시간: {elapsed}")
        self.logger.info(f"전체 종목: {self.stats['total_stocks']}개")
        self.logger.info(f"성공: {self.stats['success_stocks']}개")
        self.logger.info(f"실패: {self.stats['fail_stocks']}개")
        self.logger.info(f"총 레코드: {self.stats['total_records']}건")
        self.logger.info(f"저장 성공: {self.stats['success_records']}건")
        self.logger.info(f"저장 실패: {self.stats['fail_records']}건")

        if self.stats['total_stocks'] > 0:
            success_rate = self.stats['success_stocks'] / self.stats['total_stocks'] * 100
            self.logger.info(f"성공률: {success_rate:.1f}%")

        self.logger.info("=" * 70)


def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(
        description='분봉 데이터 수집 프로그램',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 보유종목 분봉 수집 (기본 120개)
  python minute_collector.py

  # 분봉 개수 지정 (예: 240개 = 약 4시간)
  python minute_collector.py --count 240

  # 테스트 모드 (1종목만)
  python minute_collector.py --test

  # 특정 종목 지정
  python minute_collector.py --codes 005930 000660

  # 오래된 데이터 정리
  python minute_collector.py --cleanup --days 30
        """
    )

    parser.add_argument(
        '--test',
        action='store_true',
        help='테스트 모드 (1종목만 수집)'
    )

    parser.add_argument(
        '--count',
        type=int,
        default=660,
        metavar='N',
        help='수집할 분봉 개수 (기본값: 660, 당일 09:00~20:00)'
    )

    parser.add_argument(
        '--codes',
        nargs='+',
        metavar='CODE',
        help='특정 종목코드 지정 (예: --codes 005930 000660)'
    )

    parser.add_argument(
        '--cleanup',
        action='store_true',
        help='오래된 분봉 데이터 정리'
    )

    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='데이터 보관 일수 (--cleanup 옵션과 함께 사용, 기본값: 30)'
    )

    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='확인 프롬프트 건너뛰기'
    )

    args = parser.parse_args()

    try:
        # 데이터 정리 모드
        if args.cleanup:
            print(f"\n{args.days}일 이전 분봉 데이터를 삭제합니다.")
            if not args.yes:
                print("계속하려면 Enter, 취소: Ctrl+C")
                input()

            collector = MinuteDataCollector()
            collector.cleanup_old_data(args.days)
            return 0

        # 분봉 수집 모드
        if args.test:
            print("\n테스트 모드: 1종목만 수집합니다.")
        elif args.codes:
            print(f"\n지정 종목: {args.codes}")
        else:
            if not KIWOOM_AVAILABLE:
                print("\n키움 API를 사용할 수 없습니다.")
                print("--codes 옵션으로 종목코드를 지정하세요.")
                return 1
            print("\n보유종목 분봉 데이터를 수집합니다.")

        print(f"분봉 개수: {args.count}개")

        if not args.yes and not args.test:
            print("\n시작하려면 Enter, 취소: Ctrl+C")
            input()

        collector = MinuteDataCollector(
            minute_count=args.count,
            test_mode=args.test,
            specific_codes=args.codes
        )

        success = collector.run()

        if success:
            print("\n분봉 수집 완료!")
            return 0
        else:
            print("\n분봉 수집 실패!")
            return 1

    except KeyboardInterrupt:
        print("\n사용자에 의해 중단되었습니다.")
        return 1
    except Exception as e:
        print(f"\n오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
