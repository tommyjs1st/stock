"""
급락 매수 전략 - 전일 종가 대비 15% 하락 시 매수
9:00~9:30 사이 전일 종가 대비 15% 하락한 종목 매수
당일 오후 3시에 시장가로 전량 매도
"""
import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional
from pathlib import Path

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# analyze 디렉토리 추가
analyze_dir = os.path.join(os.path.dirname(current_dir), 'analyze')
if analyze_dir not in sys.path:
    sys.path.insert(0, analyze_dir)

try:
    from config.config_manager import ConfigManager
    from data.kis_api_client import KISAPIClient
    from trading.order_manager import OrderManager
    from notification.discord_notifier import DiscordNotifier

    # analyze 디렉토리의 utils 및 db_manager import
    from utils import setup_logger
    from db_manager import DBManager
except ImportError as e:
    print(f"❌ 모듈 임포트 실패: {e}")
    sys.exit(1)


class SharpDeclineTrader:
    """
    급락 매수 전략 트레이더

    전략 개요:
    1. 코스피 시가총액 상위 200개 종목 모니터링 (제외 목록 제외)
    2. 9:00~9:30 사이 전일 종가 대비 15% 이상 하락 시 시장가 매수
    3. 당일 오후 3시에 급락매수한 종목만 시장가 전량 매도

    중요: 다른 전략으로 매수한 종목이나 기존 보유 종목은 매도하지 않음
    """

    def __init__(self, config_path: str = "config.yaml", dry_run: bool = False):
        """
        초기화

        Args:
            config_path: 설정 파일 경로
            dry_run: True면 실제 주문 없이 시뮬레이션만 (테스트용)
        """
        # 드라이런 모드 설정
        self.dry_run = dry_run
        if self.dry_run:
            print("⚠️  드라이런 모드: 실제 주문 없이 시뮬레이션만 실행합니다")

        # 설정 로드
        self.config_manager = ConfigManager(config_path)

        # 로거 설정
        self.logger = setup_logger(log_filename="sharp_decline_trader.log")

        # KIS API 클라이언트 초기화
        kis_config = self.config_manager.get_kis_config()
        self.api_client = KISAPIClient(
            app_key=kis_config['app_key'],
            app_secret=kis_config['app_secret'],
            base_url=kis_config['base_url'],
            account_no=kis_config['account_no']
        )

        # 주문 관리자 초기화
        trading_config = self.config_manager.get_trading_config()
        self.order_manager = OrderManager(
            api_client=self.api_client,
            logger=self.logger,
            max_position_ratio=0.15,  # 종목당 15% 제한
            get_stock_name_func=self.get_stock_name
        )

        # 알림 관리자 초기화
        notification_config = self.config_manager.get_notification_config()
        self.notifier = DiscordNotifier(
            webhook_url=notification_config.get('discord_webhook_auto', ''),
            notify_on_trade=True,
            notify_on_error=True,
            notify_on_daily_summary=True,
            logger=self.logger
        )

        # DB 매니저 초기화
        db_config = self.config_manager.get_database_config()
        self.db_manager = DBManager(db_config, self.logger)

        # 종목명 캐시
        self.stock_names = {}
        self.load_stock_names()

        # 거래 설정
        self.decline_threshold = 0.15  # 15% 하락
        self.buy_time_start = (9, 0)   # 9:00
        self.buy_time_end = (9, 30)    # 9:30
        self.sell_time = (15, 0)       # 15:00

        # 매수한 종목 목록 (당일)
        self.purchased_stocks = {}  # {종목코드: {'quantity': int, 'price': int, 'prev_close': int}}

        # 전일 종가 데이터 (프로그램 시작시 로드)
        self.prev_close_prices = {}  # {종목코드: 전일종가}

        # 제외 종목 목록 로드
        self.exclude_stocks = self.load_exclude_list()

        self.logger.info("✅ 급락 매수 전략 시스템 초기화 완료")
        self.logger.info(f"📊 매수 시간: {self.buy_time_start[0]:02d}:{self.buy_time_start[1]:02d} ~ {self.buy_time_end[0]:02d}:{self.buy_time_end[1]:02d}")
        self.logger.info(f"📊 매도 시간: {self.sell_time[0]:02d}:{self.sell_time[1]:02d}")
        self.logger.info(f"📊 하락 기준: {self.decline_threshold*100}%")

    def load_stock_names(self):
        """종목명 파일에서 로드"""
        try:
            if os.path.exists('stock_names.json'):
                with open('stock_names.json', 'r', encoding='utf-8') as f:
                    saved_names = json.load(f)
                    self.stock_names.update(saved_names)
                self.logger.info(f"종목명 {len(saved_names)}개 로드")
        except Exception as e:
            self.logger.warning(f"종목명 로드 실패: {e}")

    def get_stock_name(self, code: str) -> str:
        """종목명 조회"""
        if code in self.stock_names:
            return self.stock_names[code]

        try:
            basic_info = self.api_client.get_stock_basic_info(code)
            if basic_info and basic_info.get('output'):
                stock_name = str(basic_info['output'].get('prdt_abrv_name', code)).strip()
                if stock_name:
                    self.stock_names[code] = stock_name
                    self.save_stock_names()
                    return stock_name
        except Exception as e:
            self.logger.warning(f"❌ {code} 종목명 조회 오류: {e}")

        return code

    def save_stock_names(self):
        """종목명을 파일에 저장"""
        try:
            with open('stock_names.json', 'w', encoding='utf-8') as f:
                json.dump(self.stock_names, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.debug(f"종목명 저장 실패: {e}")

    def load_exclude_list(self) -> set:
        """제외 종목 목록 로드"""
        exclude_set = set()
        exclude_file = "exclude_stocks.json"

        try:
            if os.path.exists(exclude_file):
                with open(exclude_file, 'r', encoding='utf-8') as f:
                    exclude_list = json.load(f)
                    exclude_set = set(exclude_list)
                    self.logger.info(f"📋 제외 종목 {len(exclude_set)}개 로드")
            else:
                self.logger.info("📋 제외 종목 파일 없음 (exclude_stocks.json)")
        except Exception as e:
            self.logger.error(f"제외 종목 로드 실패: {e}")

        return exclude_set

    def get_top_kospi_stocks(self, top_n: int = 200) -> Dict[str, str]:
        """코스피 시가총액 상위 종목 조회 (제외 목록 제외)"""
        self.logger.info(f"📊 코스피 시가총액 상위 {top_n}개 종목 조회 시작...")

        all_stocks = []
        exclude_keywords = ["KODEX", "TIGER", "PLUS", "ACE", "ETF", "ETN", "리츠", "우", "스팩", "커버드"]

        try:
            import requests
            from bs4 import BeautifulSoup

            # 코스피만 수집 (sosok=0)
            for page in range(1, 15):
                url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok=0&page={page}"
                headers = {"User-Agent": "Mozilla/5.0"}

                response = requests.get(url, headers=headers, timeout=10)
                soup = BeautifulSoup(response.text, "html.parser")
                rows = soup.select("table.type_2 tr")

                for row in rows:
                    link = row.select_one("a.tltle")
                    if link:
                        name = link.text.strip()
                        href = link["href"]
                        code = href.split("=")[-1]

                        # 제외 키워드 체크
                        if any(keyword in name for keyword in exclude_keywords):
                            continue

                        # 제외 목록 체크
                        if code in self.exclude_stocks:
                            self.logger.debug(f"  제외: {name}({code})")
                            continue

                        # 시가총액 파싱 (억원 단위)
                        market_cap = 0
                        cols = row.select("td")
                        if len(cols) >= 7:
                            market_cap_text = cols[6].text.strip().replace(",", "")
                            try:
                                market_cap = int(market_cap_text) if market_cap_text else 0
                            except:
                                market_cap = 0

                        all_stocks.append({
                            'code': code,
                            'name': name,
                            'market_cap': market_cap
                        })

                time.sleep(0.3)

                # 충분히 수집했으면 중단
                if len(all_stocks) >= top_n * 1.5:
                    break

            # 시가총액 기준으로 정렬 (내림차순)
            all_stocks.sort(key=lambda x: x['market_cap'], reverse=True)

            # 상위 N개 선택
            top_stocks = all_stocks[:top_n]

            # 딕셔너리로 변환 (code: name)
            result = {stock['code']: stock['name'] for stock in top_stocks}

            self.logger.info(f"✅ 코스피 상위 {len(result)}개 종목 조회 완료 (제외 {len(self.exclude_stocks)}개 제외)")

            return result

        except Exception as e:
            self.logger.error(f"❌ 종목 리스트 조회 실패: {e}")
            return {}

    def load_previous_close_prices(self, stock_codes: List[str]) -> Dict[str, int]:
        """전일 종가 데이터 DB에서 로드"""
        self.logger.info(f"📊 전일 종가 데이터 로드 시작 ({len(stock_codes)}개 종목)...")

        prev_close_prices = {}

        try:
            # DB 연결
            if not self.db_manager.connect():
                raise Exception("DB 연결 실패")

            # 각 종목별 전일 종가 조회
            success_count = 0
            fail_count = 0

            for stock_code in stock_codes:
                try:
                    # 최근 7일치 데이터 조회 (주말 고려)
                    daily_data = self.db_manager.get_daily_prices(stock_code, days=7)

                    if daily_data and len(daily_data) >= 1:
                        # 가장 최근 데이터가 전일 종가
                        latest_data = daily_data[-1]
                        close_price = latest_data.get('stck_clpr')

                        if close_price:
                            prev_close_prices[stock_code] = int(close_price)
                            success_count += 1
                        else:
                            fail_count += 1
                    else:
                        fail_count += 1

                    # API 제한 고려
                    if len(prev_close_prices) % 50 == 0:
                        self.logger.info(f"  진행: {len(prev_close_prices)}/{len(stock_codes)}")

                except Exception as e:
                    self.logger.debug(f"  {stock_code} 전일 종가 조회 실패: {e}")
                    fail_count += 1

            self.logger.info(f"✅ 전일 종가 로드 완료: 성공 {success_count}개, 실패 {fail_count}개")

        except Exception as e:
            self.logger.error(f"❌ 전일 종가 로드 실패: {e}")

        finally:
            self.db_manager.disconnect()

        return prev_close_prices

    def is_in_buy_time_window(self, current_time: datetime = None) -> bool:
        """매수 시간대인지 확인 (9:00~9:30)"""
        if current_time is None:
            current_time = datetime.now()

        current_hour = current_time.hour
        current_minute = current_time.minute

        start_hour, start_minute = self.buy_time_start
        end_hour, end_minute = self.buy_time_end

        current_minutes = current_hour * 60 + current_minute
        start_minutes = start_hour * 60 + start_minute
        end_minutes = end_hour * 60 + end_minute

        return start_minutes <= current_minutes < end_minutes

    def is_sell_time(self, current_time: datetime = None) -> bool:
        """매도 시간인지 확인 (오후 3시)"""
        if current_time is None:
            current_time = datetime.now()

        sell_hour, sell_minute = self.sell_time

        return current_time.hour == sell_hour and current_time.minute == sell_minute

    def check_decline_and_buy(self, stock_code: str, stock_name: str, prev_close: int):
        """하락률 체크 및 매수 실행"""
        try:
            # 이미 매수한 종목은 스킵
            if stock_code in self.purchased_stocks:
                return

            # 현재가 조회
            price_data = self.api_client.get_current_price(stock_code)
            if not price_data or not price_data.get('output'):
                return

            current_price = int(price_data['output'].get('stck_prpr', 0))
            if current_price == 0:
                return

            # 하락률 계산
            decline_rate = (current_price - prev_close) / prev_close

            # 15% 이상 하락했는지 체크
            if decline_rate <= -self.decline_threshold:
                self.logger.warning(f"🔥 {stock_name}({stock_code}) 급락 감지! "
                                   f"전일종가 {prev_close:,}원 → 현재가 {current_price:,}원 "
                                   f"({decline_rate*100:.2f}%)")

                # 드라이런 모드: 시뮬레이션만
                if self.dry_run:
                    self.logger.info(f"🧪 [드라이런] {stock_name}({stock_code}) 매수 시뮬레이션")
                    # 가상 주문 결과 생성
                    estimated_quantity = int(1000000 / current_price)  # 100만원 기준
                    result = {
                        'success': True,
                        'limit_price': current_price,
                        'quantity': estimated_quantity,
                        'order_no': 'DRY_RUN_' + stock_code
                    }
                else:
                    # 실제 매수 실행
                    result = self.order_manager.place_order_with_tracking(
                        symbol=stock_code,
                        side='BUY',
                        quantity=None,  # 금액 기반 계산
                        order_strategy='market',  # 시장가 매수
                        order_tracker=None
                    )

                if result['success']:
                    executed_price = result.get('limit_price', current_price)
                    quantity = result.get('quantity', 0)

                    # 당일 급락매수 종목으로 기록 (오후 3시에 이 종목들만 매도)
                    self.purchased_stocks[stock_code] = {
                        'quantity': quantity,
                        'price': executed_price,
                        'prev_close': prev_close,
                        'decline_rate': decline_rate,
                        'buy_time': datetime.now().isoformat(),
                        'strategy': 'sharp_decline'  # 전략 구분
                    }

                    self.logger.info(f"✅ {stock_name}({stock_code}) 급락매수 완료: "
                                   f"{quantity}주 @ {executed_price:,}원 "
                                   f"(오후 3시 매도 예정)")

                    # Discord 알림
                    self.notifier.notify_trade_success(
                        'BUY', stock_code, quantity, executed_price,
                        result.get('order_no', ''), stock_name
                    )

                    # 매수 목록 저장
                    self.save_purchased_stocks()
                else:
                    self.logger.error(f"❌ {stock_name}({stock_code}) 매수 실패: {result.get('error')}")

        except Exception as e:
            self.logger.error(f"❌ {stock_code} 하락 체크/매수 실패: {e}")

    def sell_purchased_today(self):
        """당일 급락시 매수한 종목만 전량 매도 (오후 3시)"""
        self.logger.info(f"🔔 오후 3시 도달 - 당일 급락매수 종목 매도 시작")

        if not self.purchased_stocks:
            self.logger.info("💼 당일 급락매수한 종목 없음 - 매도 스킵")
            return

        # 계좌의 실제 보유 종목 확인
        try:
            account_holdings = self.api_client.get_all_holdings()
            self.logger.info(f"📊 계좌 전체 보유 종목: {len(account_holdings)}개")
            self.logger.info(f"📊 당일 급락매수 종목: {len(self.purchased_stocks)}개")

            # 급락매수 종목과 계좌 보유 종목 비교
            for stock_code in self.purchased_stocks.keys():
                stock_name = self.get_stock_name(stock_code)
                if stock_code in account_holdings:
                    self.logger.info(f"  ✓ {stock_name}({stock_code}) - 계좌에 존재 (매도 대상)")
                else:
                    self.logger.warning(f"  ✗ {stock_name}({stock_code}) - 계좌에 없음 (스킵)")

        except Exception as e:
            self.logger.warning(f"계좌 확인 실패: {e} - 그래도 매도 진행")

        sell_count = 0
        for stock_code, position in list(self.purchased_stocks.items()):
            try:
                stock_name = self.get_stock_name(stock_code)
                quantity = position['quantity']
                buy_price = position['price']

                # 계좌에 실제로 보유하고 있는지 재확인
                if 'account_holdings' in locals() and stock_code not in account_holdings:
                    self.logger.warning(f"⚠️ {stock_name}({stock_code}) - 계좌에 없어서 매도 스킵")
                    del self.purchased_stocks[stock_code]
                    continue

                self.logger.info(f"📤 {stock_name}({stock_code}) 급락매수 종목 매도 시작: {quantity}주")

                # 드라이런 모드: 시뮬레이션만
                if self.dry_run:
                    self.logger.info(f"🧪 [드라이런] {stock_name}({stock_code}) 매도 시뮬레이션")
                    # 현재가 조회
                    price_data = self.api_client.get_current_price(stock_code)
                    if price_data and price_data.get('output'):
                        sell_price = int(price_data['output'].get('stck_prpr', buy_price))
                    else:
                        sell_price = buy_price

                    result = {
                        'success': True,
                        'limit_price': sell_price,
                        'order_no': 'DRY_RUN_SELL_' + stock_code
                    }
                else:
                    # 실제 시장가 매도
                    result = self.order_manager.place_order_with_tracking(
                        symbol=stock_code,
                        side='SELL',
                        quantity=quantity,
                        order_strategy='market',
                        order_tracker=None
                    )

                if result['success']:
                    sell_price = result.get('limit_price', 0)

                    # 현재가로 추정 (시장가인 경우)
                    if sell_price == 0:
                        price_data = self.api_client.get_current_price(stock_code)
                        if price_data and price_data.get('output'):
                            sell_price = int(price_data['output'].get('stck_prpr', 0))

                    # 손익 계산
                    profit_loss = (sell_price - buy_price) * quantity
                    profit_loss_pct = ((sell_price - buy_price) / buy_price) * 100

                    self.logger.info(f"✅ {stock_name}({stock_code}) 매도 완료: "
                                   f"{quantity}주 @ {sell_price:,}원 "
                                   f"(손익: {profit_loss:+,}원, {profit_loss_pct:+.2f}%)")

                    # Discord 알림
                    self.notifier.notify_trade_success(
                        'SELL', stock_code, quantity, sell_price,
                        result.get('order_no', ''), stock_name
                    )

                    sell_count += 1

                    # 매수 목록에서 제거
                    del self.purchased_stocks[stock_code]
                else:
                    self.logger.error(f"❌ {stock_name}({stock_code}) 매도 실패: {result.get('error')}")

                time.sleep(0.5)

            except Exception as e:
                self.logger.error(f"❌ {stock_code} 매도 처리 실패: {e}")

        self.logger.info(f"✅ 매도 완료: {sell_count}개 종목")

        # 매도 완료 후 파일 삭제
        self.delete_purchased_stocks_file()

    def save_purchased_stocks(self):
        """매수 종목 목록 저장"""
        try:
            filename = f"purchased_stocks_{datetime.now().strftime('%Y%m%d')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.purchased_stocks, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.debug(f"매수 목록 저장 실패: {e}")

    def load_purchased_stocks(self):
        """매수 종목 목록 로드 (재시작 시)"""
        try:
            filename = f"purchased_stocks_{datetime.now().strftime('%Y%m%d')}.json"
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    self.purchased_stocks = json.load(f)
                    self.logger.info(f"📋 매수 목록 {len(self.purchased_stocks)}개 로드")
        except Exception as e:
            self.logger.warning(f"매수 목록 로드 실패: {e}")

    def delete_purchased_stocks_file(self):
        """매도 완료 후 매수 목록 파일 삭제"""
        try:
            filename = f"purchased_stocks_{datetime.now().strftime('%Y%m%d')}.json"
            if os.path.exists(filename):
                os.remove(filename)
                self.logger.info(f"✅ 매수 목록 파일 삭제: {filename}")
            else:
                self.logger.debug(f"파일 없음: {filename}")
        except Exception as e:
            self.logger.warning(f"파일 삭제 실패: {e}")

    def is_market_open(self, current_time=None):
        """한국 증시 개장 시간 확인"""
        if current_time is None:
            current_time = datetime.now()

        weekday = current_time.weekday()
        if weekday >= 5:  # 주말
            return False

        hour = current_time.hour
        minute = current_time.minute
        current_time_minutes = hour * 60 + minute

        # 거래시간: 오전 9시 ~ 오후 3시 30분
        market_open_minutes = 9 * 60      # 09:00
        market_close_minutes = 15 * 60 + 30  # 15:30

        return market_open_minutes <= current_time_minutes < market_close_minutes

    def run(self):
        """메인 실행 루프"""
        mode_str = "드라이런 모드" if self.dry_run else "실전 모드"
        self.logger.info(f"🚀 급락 매수 전략 시작 ({mode_str})")

        # Discord 알림
        title = "🧪 급락 매수 전략 시작 (드라이런)" if self.dry_run else "🚀 급락 매수 전략 시작"
        color = 0xffa500 if self.dry_run else 0x00ff00  # 주황색(테스트) vs 녹색(실전)

        self.notifier.send_notification(
            title,
            f"모드: {mode_str}\n"
            f"매수 시간: {self.buy_time_start[0]:02d}:{self.buy_time_start[1]:02d}~{self.buy_time_end[0]:02d}:{self.buy_time_end[1]:02d}\n"
            f"매도 시간: {self.sell_time[0]:02d}:{self.sell_time[1]:02d}\n"
            f"하락 기준: {self.decline_threshold*100}%",
            color
        )

        # 당일 매수 목록 로드 (재시작 대비)
        self.load_purchased_stocks()

        # 코스피 상위 200개 종목 조회
        target_stocks = self.get_top_kospi_stocks(top_n=200)
        if not target_stocks:
            self.logger.error("❌ 종목 리스트 조회 실패 - 프로그램 종료")
            return

        # 전일 종가 데이터 로드
        self.prev_close_prices = self.load_previous_close_prices(list(target_stocks.keys()))

        if not self.prev_close_prices:
            self.logger.error("❌ 전일 종가 데이터 로드 실패 - 프로그램 종료")
            return

        self.logger.info(f"📊 모니터링 종목: {len(self.prev_close_prices)}개")

        try:
            sold_today = False  # 당일 매도 완료 플래그

            while True:
                current_time = datetime.now()

                # 장 시간 체크
                if not self.is_market_open(current_time):
                    self.logger.info("⏰ 장 외 시간 - 대기 중...")
                    time.sleep(60)
                    continue

                # 매수 시간대 (9:00~9:30)
                if self.is_in_buy_time_window(current_time):
                    self.logger.info(f"🔍 매수 모니터링 중... ({current_time.strftime('%H:%M:%S')})")

                    # 전일 종가가 있는 종목만 체크
                    check_count = 0
                    for stock_code, prev_close in self.prev_close_prices.items():
                        if stock_code in self.purchased_stocks:
                            continue

                        stock_name = target_stocks.get(stock_code, stock_code)
                        self.check_decline_and_buy(stock_code, stock_name, prev_close)

                        check_count += 1

                        # 일부 종목만 체크 후 짧은 대기 (API 제한)
                        if check_count % 10 == 0:
                            time.sleep(1)

                    self.logger.info(f"  체크 완료: {len(self.prev_close_prices)}개 종목, "
                                   f"매수: {len(self.purchased_stocks)}개")

                    # 다음 체크까지 대기
                    time.sleep(30)

                # 매도 시간 (오후 3시)
                elif self.is_sell_time(current_time) and not sold_today:
                    # 당일 급락매수한 종목만 매도
                    self.sell_purchased_today()
                    sold_today = True

                    # 매도 완료 후 종료
                    self.logger.info("✅ 당일 급락매수 종목 매도 완료 - 프로그램 종료")
                    self.logger.info("💡 주의: 다른 전략으로 매수한 종목은 매도하지 않았습니다")
                    break

                else:
                    # 매수 시간대도 아니고 매도 시간도 아니면 대기
                    time.sleep(60)

        except KeyboardInterrupt:
            self.logger.info("🛑 사용자가 프로그램을 종료했습니다.")

            # 종료 시 보유 종목이 있으면 알림
            if self.purchased_stocks:
                self.logger.warning(f"⚠️ 보유 종목 {len(self.purchased_stocks)}개 존재")
                for stock_code, position in self.purchased_stocks.items():
                    stock_name = self.get_stock_name(stock_code)
                    self.logger.info(f"  - {stock_name}({stock_code}): {position['quantity']}주")

        except Exception as e:
            self.logger.error(f"❌ 프로그램 오류: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

        finally:
            self.logger.info("🔚 급락 매수 전략 종료")


def main():
    """메인 함수"""
    import sys

    # 드라이런 모드 체크
    dry_run = '--dry-run' in sys.argv or '--test' in sys.argv

    if dry_run:
        print("🧪 급락 매수 전략 시작 (드라이런 모드)")
        print("⚠️  실제 주문 없이 시뮬레이션만 실행합니다")
    else:
        print("🚀 급락 매수 전략 시작 (실전 모드)")
        print("⚠️  실제 주문이 실행됩니다!")

    print("="*50)

    try:
        trader = SharpDeclineTrader(dry_run=dry_run)
        trader.run()

    except Exception as e:
        print(f"❌ 프로그램 실행 중 오류: {e}")
        import traceback
        print(f"상세 오류:\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
