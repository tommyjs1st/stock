"""
주식 매매 시뮬레이터
DB에 저장된 일봉 데이터로 특정 기간의 매매 손익을 시뮬레이션

사용법:
  python stock_simulator.py --code 005930 --buy 2025-01-01 --sell 2025-01-15
  python stock_simulator.py --code 삼성전자 --buy 2025-01-01 --sell 2025-01-15
  python stock_simulator.py --code 005930 --buy 2025-01-01 --sell 2025-01-15 --amount 1000000
  python stock_simulator.py --interactive  # 대화형 모드
"""
import sys
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import logging

try:
    import yaml
except ImportError:
    print("❌ PyYAML 패키지가 필요합니다: pip install PyYAML")
    sys.exit(1)

from db_manager import DBManager


class StockSimulator:
    """주식 매매 시뮬레이터 클래스"""

    def __init__(self, db_config: Dict):
        """초기화"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # 콘솔 핸들러
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(message)s')
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        # DB 매니저 초기화
        self.db_manager = DBManager(db_config, self.logger)

    def get_stock_info(self, stock_code: str) -> Optional[Dict]:
        """종목 정보 조회"""
        try:
            sql = "SELECT stock_code, stock_name FROM stock_info WHERE stock_code = %s"
            self.db_manager.cursor.execute(sql, (stock_code,))
            result = self.db_manager.cursor.fetchone()
            return result
        except Exception as e:
            self.logger.error(f"❌ 종목 정보 조회 실패: {e}")
            return None

    def search_stock_by_name(self, stock_name: str) -> List[Dict]:
        """종목명으로 검색 (부분 일치)"""
        try:
            sql = """
            SELECT stock_code, stock_name
            FROM stock_info
            WHERE stock_name LIKE %s
            ORDER BY stock_name
            """
            self.db_manager.cursor.execute(sql, (f"%{stock_name}%",))
            results = self.db_manager.cursor.fetchall()
            return results if results else []
        except Exception as e:
            self.logger.error(f"❌ 종목명 검색 실패: {e}")
            return []

    def resolve_stock_code(self, input_value: str) -> Optional[str]:
        """
        종목코드 또는 종목명을 받아서 종목코드로 변환

        Args:
            input_value: 종목코드(6자리) 또는 종목명

        Returns:
            종목코드 또는 None
        """
        # 6자리 숫자면 종목코드로 간주
        if len(input_value) == 6 and input_value.isdigit():
            stock_info = self.get_stock_info(input_value)
            if stock_info:
                return input_value
            else:
                self.logger.error(f"❌ 종목코드 '{input_value}'를 찾을 수 없습니다.")
                return None

        # 종목명으로 검색
        stocks = self.search_stock_by_name(input_value)

        if not stocks:
            self.logger.error(f"❌ '{input_value}'와 일치하는 종목을 찾을 수 없습니다.")
            return None

        # 정확히 일치하는 종목이 1개면 바로 반환
        if len(stocks) == 1:
            stock_code = stocks[0]['stock_code']
            stock_name = stocks[0]['stock_name']
            self.logger.info(f"✅ 종목 찾음: {stock_name}({stock_code})")
            return stock_code

        # 여러 개 발견 시 선택
        self.logger.info(f"\n'{input_value}'로 검색한 결과 {len(stocks)}개 종목 발견:")
        for idx, stock in enumerate(stocks, 1):
            print(f"  {idx}. {stock['stock_name']} ({stock['stock_code']})")

        try:
            choice = input(f"\n선택하세요 (1-{len(stocks)}): ").strip()
            choice_idx = int(choice) - 1

            if 0 <= choice_idx < len(stocks):
                selected = stocks[choice_idx]
                self.logger.info(f"✅ 선택: {selected['stock_name']}({selected['stock_code']})")
                return selected['stock_code']
            else:
                self.logger.error("❌ 올바른 번호를 입력하세요.")
                return None
        except (ValueError, KeyboardInterrupt):
            self.logger.error("❌ 선택이 취소되었습니다.")
            return None

    def get_price_on_date(self, stock_code: str, trade_date: str) -> Optional[Dict]:
        """특정 날짜의 가격 정보 조회"""
        try:
            sql = """
            SELECT trade_date, open_price, high_price, low_price, close_price, volume
            FROM daily_stock_prices
            WHERE stock_code = %s AND trade_date = %s
            """
            self.db_manager.cursor.execute(sql, (stock_code, trade_date))
            result = self.db_manager.cursor.fetchone()
            return result
        except Exception as e:
            self.logger.error(f"❌ 가격 조회 실패: {e}")
            return None

    def get_nearest_trading_date(self, stock_code: str, target_date: str,
                                  direction: str = 'after') -> Optional[str]:
        """가장 가까운 거래일 찾기"""
        try:
            if direction == 'after':
                sql = """
                SELECT trade_date FROM daily_stock_prices
                WHERE stock_code = %s AND trade_date >= %s
                ORDER BY trade_date ASC LIMIT 1
                """
            else:  # before
                sql = """
                SELECT trade_date FROM daily_stock_prices
                WHERE stock_code = %s AND trade_date <= %s
                ORDER BY trade_date DESC LIMIT 1
                """

            self.db_manager.cursor.execute(sql, (stock_code, target_date))
            result = self.db_manager.cursor.fetchone()

            if result:
                return str(result['trade_date'])
            return None
        except Exception as e:
            self.logger.error(f"❌ 거래일 조회 실패: {e}")
            return None

    def get_period_stats(self, stock_code: str, start_date: str, end_date: str) -> Optional[Dict]:
        """보유 기간 동안의 통계 정보"""
        try:
            sql = """
            SELECT
                MAX(high_price) as max_high,
                MIN(low_price) as min_low,
                AVG(volume) as avg_volume,
                COUNT(*) as trading_days
            FROM daily_stock_prices
            WHERE stock_code = %s AND trade_date BETWEEN %s AND %s
            """
            self.db_manager.cursor.execute(sql, (stock_code, start_date, end_date))
            result = self.db_manager.cursor.fetchone()
            return result
        except Exception as e:
            self.logger.error(f"❌ 통계 조회 실패: {e}")
            return None

    def simulate(self, stock_code_or_name: str, buy_date: str, sell_date: str,
                 amount: int = 1000000) -> Optional[Dict]:
        """
        매매 시뮬레이션 실행

        Args:
            stock_code_or_name: 종목코드(6자리) 또는 종목명
            buy_date: 매수일 (YYYY-MM-DD)
            sell_date: 매도일 (YYYY-MM-DD)
            amount: 투자금액 (기본값: 100만원)

        Returns:
            시뮬레이션 결과 딕셔너리
        """
        try:
            # DB 연결
            if not self.db_manager.connect():
                return None

            # 종목코드 확인
            stock_code = self.resolve_stock_code(stock_code_or_name)
            if not stock_code:
                return None

            # 종목 정보 조회
            stock_info = self.get_stock_info(stock_code)
            if not stock_info:
                self.logger.error(f"❌ 종목코드 '{stock_code}'를 찾을 수 없습니다.")
                return None

            stock_name = stock_info['stock_name']

            # 매수일 데이터 조회 (해당 날짜가 비거래일이면 이후 첫 거래일)
            buy_data = self.get_price_on_date(stock_code, buy_date)
            if not buy_data:
                self.logger.warning(f"⚠️ {buy_date}는 거래일이 아닙니다. 이후 거래일을 찾습니다...")
                actual_buy_date = self.get_nearest_trading_date(stock_code, buy_date, 'after')
                if not actual_buy_date:
                    self.logger.error(f"❌ {buy_date} 이후 거래 데이터가 없습니다.")
                    return None
                buy_data = self.get_price_on_date(stock_code, actual_buy_date)
                buy_date = actual_buy_date

            # 매도일 데이터 조회 (해당 날짜가 비거래일이면 이전 거래일)
            sell_data = self.get_price_on_date(stock_code, sell_date)
            if not sell_data:
                self.logger.warning(f"⚠️ {sell_date}는 거래일이 아닙니다. 이전 거래일을 찾습니다...")
                actual_sell_date = self.get_nearest_trading_date(stock_code, sell_date, 'before')
                if not actual_sell_date:
                    self.logger.error(f"❌ {sell_date} 이전 거래 데이터가 없습니다.")
                    return None
                sell_data = self.get_price_on_date(stock_code, actual_sell_date)
                sell_date = actual_sell_date

            # 날짜 검증
            if buy_date >= sell_date:
                self.logger.error("❌ 매수일이 매도일보다 늦습니다.")
                return None

            # 기간 통계 조회
            period_stats = self.get_period_stats(stock_code, buy_date, sell_date)

            # 매매 계산
            buy_price = buy_data['close_price']
            sell_price = sell_data['close_price']

            # 매수 가능 주식 수 (수수료 제외)
            shares = amount // buy_price

            if shares == 0:
                self.logger.error(f"❌ 투자금액이 부족합니다. (필요금액: {buy_price}원 이상)")
                return None

            # 실제 투자금액
            actual_investment = shares * buy_price

            # 매도 금액
            sell_amount = shares * sell_price

            # 손익
            profit = sell_amount - actual_investment
            profit_rate = (profit / actual_investment) * 100

            # 최대 수익/손실 (보유 기간 중)
            max_profit = 0
            max_loss = 0
            if period_stats:
                max_high = period_stats['max_high']
                min_low = period_stats['min_low']

                max_profit_amount = shares * max_high - actual_investment
                max_profit = (max_profit_amount / actual_investment) * 100

                max_loss_amount = shares * min_low - actual_investment
                max_loss = (max_loss_amount / actual_investment) * 100

            # 결과 반환
            result = {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'buy_date': buy_date,
                'sell_date': sell_date,
                'buy_price': buy_price,
                'sell_price': sell_price,
                'shares': shares,
                'investment': actual_investment,
                'sell_amount': sell_amount,
                'profit': profit,
                'profit_rate': profit_rate,
                'period_stats': period_stats,
                'max_profit_rate': max_profit,
                'max_loss_rate': max_loss
            }

            return result

        except Exception as e:
            self.logger.error(f"❌ 시뮬레이션 실패: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            self.db_manager.disconnect()

    def print_result(self, result: Dict):
        """결과 출력"""
        if not result:
            return

        print("\n" + "="*70)
        print("📊 매매 시뮬레이션 결과")
        print("="*70)

        # 기본 정보
        print(f"\n📌 종목정보")
        print(f"   종목코드: {result['stock_code']}")
        print(f"   종목명: {result['stock_name']}")

        # 매매 정보
        print(f"\n💰 매매내역")
        print(f"   매수일: {result['buy_date']}")
        print(f"   매수가: {result['buy_price']:,}원")
        print(f"   매수수량: {result['shares']:,}주")
        print(f"   투자금액: {result['investment']:,}원")
        print(f"\n   매도일: {result['sell_date']}")
        print(f"   매도가: {result['sell_price']:,}원")
        print(f"   매도금액: {result['sell_amount']:,}원")

        # 손익
        profit_symbol = "📈" if result['profit'] >= 0 else "📉"
        profit_sign = "+" if result['profit'] >= 0 else ""

        print(f"\n{profit_symbol} 손익결과")
        print(f"   손익금액: {profit_sign}{result['profit']:,}원")
        print(f"   수익률: {profit_sign}{result['profit_rate']:.2f}%")

        # 보유 기간 통계
        if result['period_stats']:
            stats = result['period_stats']
            print(f"\n📊 보유기간 통계")
            print(f"   거래일수: {stats['trading_days']}일")
            print(f"   최고가: {stats['max_high']:,}원 (최대수익률: +{result['max_profit_rate']:.2f}%)")
            print(f"   최저가: {stats['min_low']:,}원 (최대손실률: {result['max_loss_rate']:.2f}%)")
            print(f"   평균거래량: {int(stats['avg_volume']):,}주")

        print("\n" + "="*70)


def load_config():
    """설정 파일 로드"""
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            return config.get('database', {})
    except FileNotFoundError:
        print("❌ config.yaml 파일을 찾을 수 없습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 설정 파일 로드 실패: {e}")
        sys.exit(1)


def interactive_mode(simulator: StockSimulator):
    """대화형 모드"""
    print("\n" + "="*70)
    print("📈 주식 매매 시뮬레이터 (대화형 모드)")
    print("="*70)

    try:
        # 종목코드/종목명 입력
        stock_input = input("\n종목코드(6자리) 또는 종목명: ").strip()
        if not stock_input:
            print("❌ 종목코드 또는 종목명을 입력하세요.")
            return

        # 매수일 입력
        buy_date = input("매수일 (YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(buy_date, '%Y-%m-%d')
        except ValueError:
            print("❌ 날짜 형식이 올바르지 않습니다. (예: 2025-01-01)")
            return

        # 매도일 입력
        sell_date = input("매도일 (YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(sell_date, '%Y-%m-%d')
        except ValueError:
            print("❌ 날짜 형식이 올바르지 않습니다. (예: 2025-01-15)")
            return

        # 투자금액 입력
        amount_input = input("투자금액 (기본값: 1,000,000원): ").strip()
        amount = 1000000
        if amount_input:
            try:
                amount = int(amount_input.replace(',', ''))
            except ValueError:
                print("⚠️ 올바르지 않은 금액입니다. 기본값(100만원)을 사용합니다.")

        # 시뮬레이션 실행
        result = simulator.simulate(stock_input, buy_date, sell_date, amount)

        if result:
            simulator.print_result(result)

    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")


def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(
        description='주식 매매 시뮬레이터',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 종목코드로 조회
  python stock_simulator.py --code 005930 --buy 2025-01-01 --sell 2025-01-15
  python stock_simulator.py --code 005930 --buy 2025-01-01 --sell 2025-01-15 --amount 5000000

  # 종목명으로 조회
  python stock_simulator.py --code 삼성전자 --buy 2025-01-01 --sell 2025-01-15
  python stock_simulator.py --code "SK하이닉스" --buy 2025-01-01 --sell 2025-01-15

  # 대화형 모드
  python stock_simulator.py --interactive
        """
    )

    parser.add_argument(
        '--code',
        type=str,
        help='종목코드(6자리) 또는 종목명 (예: 005930, 삼성전자)'
    )

    parser.add_argument(
        '--buy',
        type=str,
        help='매수일 (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--sell',
        type=str,
        help='매도일 (YYYY-MM-DD)'
    )

    parser.add_argument(
        '--amount',
        type=int,
        default=1000000,
        help='투자금액 (기본값: 1,000,000원)'
    )

    parser.add_argument(
        '--interactive', '-i',
        action='store_true',
        help='대화형 모드로 실행'
    )

    args = parser.parse_args()

    # 설정 로드
    db_config = load_config()

    # 시뮬레이터 생성
    simulator = StockSimulator(db_config)

    # 대화형 모드
    if args.interactive:
        interactive_mode(simulator)
        return 0

    # 명령행 모드 - 인자 검증
    if not args.code or not args.buy or not args.sell:
        print("❌ 필수 인자가 누락되었습니다.")
        print("사용법: python stock_simulator.py --code 종목코드(또는 종목명) --buy 매수일 --sell 매도일")
        print("또는: python stock_simulator.py --interactive")
        return 1

    # 날짜 형식 검증
    try:
        datetime.strptime(args.buy, '%Y-%m-%d')
        datetime.strptime(args.sell, '%Y-%m-%d')
    except ValueError:
        print("❌ 날짜 형식이 올바르지 않습니다. (예: 2025-01-01)")
        return 1

    # 시뮬레이션 실행
    result = simulator.simulate(args.code, args.buy, args.sell, args.amount)

    if result:
        simulator.print_result(result)
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
