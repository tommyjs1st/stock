"""
메인 실행 파일 - 리팩토링된 자동매매 시스템
"""
import os
import sys
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional  # 타입 힌트 추가

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 디버그: 경로 확인
print(f"현재 디렉토리: {current_dir}")
print(f"Python 경로: {sys.path[:3]}")

# 파일 존재 여부 확인
required_files = [
    'config/config_manager.py',
    'data/kis_api_client.py', 
    'trading/position_manager.py',
    'trading/order_manager.py',
    'trading/order_tracker.py',
    'strategy/hybrid_strategy.py',
    'notification/discord_notifier.py',
    'utils/logger.py',
    'utils/helpers.py'
]

for file_path in required_files:
    full_path = os.path.join(current_dir, file_path)
    if os.path.exists(full_path):
        print(f"✅ {file_path}")
    else:
        print(f"❌ {file_path} - 파일이 없습니다!")

# 프로젝트 모듈 임포트
try:
    from config.config_manager import ConfigManager
    print("✅ ConfigManager 임포트 성공")
except ImportError as e:
    print(f"❌ ConfigManager 임포트 실패: {e}")
    sys.exit(1)

try:
    from data.kis_api_client import KISAPIClient
    print("✅ KISAPIClient 임포트 성공")
except ImportError as e:
    print(f"❌ KISAPIClient 임포트 실패: {e}")
    sys.exit(1)

try:
    from trading.position_manager import PositionManager
    print("✅ PositionManager 임포트 성공")
except ImportError as e:
    print(f"❌ PositionManager 임포트 실패: {e}")
    sys.exit(1)

try:
    from trading.order_manager import OrderManager
    print("✅ OrderManager 임포트 성공")
except ImportError as e:
    print(f"❌ OrderManager 임포트 실패: {e}")
    sys.exit(1)

try:
    from trading.order_tracker import OrderTracker
    print("✅ OrderTracker 임포트 성공")
except ImportError as e:
    print(f"❌ OrderTracker 임포트 실패: {e}")
    sys.exit(1)

try:
    from strategy.hybrid_strategy import HybridStrategy
    print("✅ HybridStrategy 임포트 성공")
except ImportError as e:
    print(f"❌ HybridStrategy 임포트 실패: {e}")
    sys.exit(1)

try:
    from notification.discord_notifier import DiscordNotifier
    print("✅ DiscordNotifier 임포트 성공")
except ImportError as e:
    print(f"❌ DiscordNotifier 임포트 실패: {e}")
    sys.exit(1)

try:
    from utils.logger import setup_logger
    print("✅ setup_logger 임포트 성공")
except ImportError as e:
    print(f"❌ setup_logger 임포트 실패: {e}")
    sys.exit(1)

try:
    from utils.helpers import create_logs_directory, check_dependencies
    print("✅ helpers 임포트 성공")
except ImportError as e:
    print(f"❌ helpers 임포트 실패: {e}")
    sys.exit(1)


class AutoTrader:
    """메인 자동매매 클래스"""
    
    def __init__(self, config_path: str = "config.yaml"):
        # 설정 로드
        self.config_manager = ConfigManager(config_path)
        
        # 로거 설정
        self.logger = setup_logger()
        
        # KIS API 클라이언트 초기화
        kis_config = self.config_manager.get_kis_config()
        self.api_client = KISAPIClient(
            app_key=kis_config['app_key'],
            app_secret=kis_config['app_secret'],
            base_url=kis_config['base_url'],
            account_no=kis_config['account_no']
        )
        
        # 거래 설정
        trading_config = self.config_manager.get_trading_config()
        self.max_symbols = trading_config.get('max_symbols', 3)
        self.stop_loss_pct = trading_config.get('stop_loss_pct', 0.08)
        self.take_profit_pct = trading_config.get('take_profit_pct', 0.25)
        
        # 포지션 관리자 초기화
        position_config = self.config_manager.get_position_config()
        self.position_manager = PositionManager(
            logger=self.logger,
            max_purchases_per_symbol=position_config.get('max_purchases_per_symbol', 2),
            max_quantity_per_symbol=position_config.get('max_quantity_per_symbol', 300),
            min_holding_period_hours=position_config.get('min_holding_period_hours', 72),
            purchase_cooldown_hours=position_config.get('purchase_cooldown_hours', 48)
        )
        
        # 주문 관리자 초기화
        self.order_manager = OrderManager(
            api_client=self.api_client,
            logger=self.logger,
            max_position_ratio=trading_config.get('max_position_ratio', 0.4),
            get_stock_name_func=self.get_stock_name
        )
        
        # 알림 관리자 초기화
        notification_config = self.config_manager.get_notification_config()
        self.notifier = DiscordNotifier(
            webhook_url=notification_config.get('discord_webhook_auto', ''),
            notify_on_trade=notification_config.get('notify_on_trade', True),
            notify_on_error=notification_config.get('notify_on_error', True),
            notify_on_daily_summary=notification_config.get('notify_on_daily_summary', True),
            logger=self.logger
        )
        
        # 주문 추적기 초기화
        self.order_tracker = OrderTracker(self.api_client, self.logger)

        # 하이브리드 전략 초기화
        self.hybrid_strategy = HybridStrategy(
            api_client=self.api_client,
            order_manager=self.order_manager,
            position_manager=self.position_manager,
            notifier=self.notifier,
            logger=self.logger,
            order_tracker=self.order_tracker, 
            get_stock_name_func=self.get_stock_name
        )
        
        # 거래 관련 변수
        self.positions = {}
        self.all_positions = {}
        self.symbols = []
        self.stock_names = {}
        self.daily_pnl = 0
        self.trade_count = 0
        
        # 백테스트 관련
        backtest_config = self.config_manager.get_backtest_config()
        self.backtest_results_file = backtest_config.get('results_file', 'backtest_results.json')
        self.min_return_threshold = backtest_config.get('min_return_threshold', 5.0)
        self.last_backtest_update = self.get_backtest_file_modified_time()
        
        # 초기화
        self.load_symbols_and_names()
        self.load_stock_names()
        
        self.logger.info("✅ 자동매매 시스템 초기화 완료")
    
    def load_symbols_and_names(self):
        """종목 및 종목명 로드"""
        try:
            # 설정에서 직접 지정된 종목 확인
            trading_config = self.config_manager.get_trading_config()
            if 'symbols' in trading_config:
                self.symbols = trading_config['symbols']
                self.logger.info(f"설정 파일에서 {len(self.symbols)}개 종목 로드")
                return
            
            # 백테스트 결과에서 로드
            if os.path.exists(self.backtest_results_file):
                with open(self.backtest_results_file, 'r', encoding='utf-8') as f:
                    backtest_data = json.load(f)
                
                verified_symbols = backtest_data.get('verified_symbols', [])
                filtered_symbols = [
                    item for item in verified_symbols 
                    if item['return'] >= self.min_return_threshold
                ]
                
                filtered_symbols.sort(key=lambda x: x['priority'])
                selected = filtered_symbols[:self.max_symbols]
                
                self.symbols = [item['symbol'] for item in selected]
                self.stock_names = {item['symbol']: item.get('name', item['symbol']) for item in selected}
                
                self.logger.info(f"백테스트 결과에서 {len(self.symbols)}개 종목 로드")
            else:
                # 기본 종목
                self.symbols = ['278470', '062040', '042660']
                self.logger.warning(f"백테스트 파일 없음, 기본 종목 사용: {self.symbols}")
                
        except Exception as e:
            self.logger.error(f"종목 로드 실패: {e}")
            self.symbols = ['278470', '062040', '042660']
    
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
        return self.stock_names.get(code, code)
    
    def get_backtest_file_modified_time(self) -> float:
        """백테스트 결과 파일의 수정 시간 반환"""
        try:
            if os.path.exists(self.backtest_results_file):
                return os.path.getmtime(self.backtest_results_file)
        except Exception:
            pass
        return 0
    
    def check_backtest_update(self) -> bool:
        """백테스트 결과 파일이 업데이트되었는지 확인"""
        current_time = self.get_backtest_file_modified_time()
        
        if current_time > self.last_backtest_update:
            self.logger.info("🔄 백테스트 결과 파일이 업데이트됨을 감지")
            return True
        return False
    
    def reload_symbols_from_backtest(self) -> bool:
        """백테스트 결과에서 종목 다시 로드"""
        try:
            self.logger.info("📊 백테스트 결과 다시 로드 중...")
            
            old_symbols = set(self.symbols)
            self.load_symbols_and_names()
            new_symbols_set = set(self.symbols)
            
            added_symbols = new_symbols_set - old_symbols
            removed_symbols = old_symbols - new_symbols_set
            
            if added_symbols:
                self.logger.info(f"➕ 추가된 종목: {list(added_symbols)}")
            if removed_symbols:
                self.logger.info(f"➖ 제거된 종목: {list(removed_symbols)}")
            
            self.last_backtest_update = self.get_backtest_file_modified_time()
            
            if added_symbols or removed_symbols:
                self.notifier.notify_symbol_changes(added_symbols, removed_symbols, self.get_stock_name)
            
            return True
            
        except Exception as e:
            self.logger.error(f"백테스트 결과 재로드 실패: {e}")
            return False
    
    def update_all_positions(self):
        """모든 보유 종목 포지션 업데이트"""
        try:
            all_holdings = self.api_client.get_all_holdings()
            
            self.positions = {}
            for symbol in self.symbols:
                if symbol in all_holdings:
                    self.positions[symbol] = all_holdings[symbol]
            
            self.all_positions = all_holdings
            
            self.logger.info(f"💼 포지션 업데이트: 거래대상 {len(self.positions)}개, 전체 {len(self.all_positions)}개")
            
        except Exception as e:
            self.logger.error(f"포지션 업데이트 실패: {e}")
    
    def process_sell_signals(self):
        """매도 신호 처리"""
        if not self.all_positions:
            return
        
        positions_to_process = dict(self.all_positions)
        
        for symbol, position in positions_to_process.items():
            try:
                if symbol not in self.all_positions:
                    continue
                    
                self.process_sell_for_symbol(symbol, position)
                time.sleep(0.5)
            except Exception as e:
                self.logger.error(f"{symbol} 매도 처리 오류: {e}")
    
    def process_sell_for_symbol(self, symbol: str, position: dict):
        """개별 종목 매도 처리"""
        try:
            if symbol not in self.all_positions:
                return
                
            quantity = position['quantity']
            profit_loss_pct = position['profit_loss']
            profit_loss_decimal = profit_loss_pct / 100
            
            # 1순위: 손절 (무조건 실행)
            if profit_loss_decimal <= -self.stop_loss_pct:
                self.logger.warning(f"🛑 {symbol} 손절 조건 충족! ({profit_loss_pct:+.2f}%)")
                self.execute_sell(symbol, quantity, "urgent", "손절매")
                return
            
            # 2순위: 익절 (최소 보유기간 확인)
            if profit_loss_decimal >= self.take_profit_pct:
                can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                
                if can_sell:
                    self.logger.info(f"🎯 {symbol} 익절 조건 충족! ({profit_loss_pct:+.2f}%)")
                    self.execute_sell(symbol, quantity, "patient_limit", "익절매")
                    return
                else:
                    self.logger.info(f"💎 {symbol} 익절 조건이지만 보유 지속: {sell_reason}")
            
            # 3순위: 매도 신호 확인 (거래 대상 종목만)
            if symbol in self.symbols:
                daily_analysis = self.hybrid_strategy.analyze_daily_strategy(symbol)
                
                if daily_analysis['signal'] == 'SELL' and daily_analysis['strength'] >= 3.0:
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    
                    if can_sell:
                        self.logger.info(f"📉 {symbol} 일봉 매도 신호 감지")
                        self.execute_sell(symbol, quantity, "aggressive_limit", "일봉 매도신호")
                        return
            
        except Exception as e:
            self.logger.error(f"{symbol} 매도 처리 중 오류: {e}")
    
    def execute_sell(self, symbol: str, quantity: int, order_strategy: str, reason: str):
        """매도 실행"""
        result = self.order_manager.place_order_with_strategy(symbol, 'SELL', quantity, order_strategy)
        
        if result['success']:
            executed_price = result.get('limit_price', 0)
            self.position_manager.record_sale(symbol, quantity, executed_price, reason)
            
            # 메모리에서 포지션 제거
            try:
                if symbol in self.positions:
                    del self.positions[symbol]
                if symbol in self.all_positions:
                    del self.all_positions[symbol]
            except KeyError:
                pass
            
            self.logger.info(f"✅ {symbol} 매도 완료: {quantity}주 @ {executed_price:,}원 - {reason}")
            
            # 알림 전송
            stock_name = self.get_stock_name(symbol)
            self.notifier.notify_trade_success('SELL', symbol, quantity, executed_price, 
                                             result.get('order_no', ''), stock_name)
    
    def is_market_open(self, current_time=None):
        """한국 증시 개장 시간 확인"""
        if current_time is None:
            current_time = datetime.now()
        
        # 주말 체크
        weekday = current_time.weekday()
        if weekday >= 5:
            return False
        
        # 시간 체크
        hour = current_time.hour
        minute = current_time.minute
        current_time_minutes = hour * 60 + minute
        
        # 개장: 09:00 (540분), 마감: 15:30 (930분)
        market_open_minutes = 9 * 60
        market_close_minutes = 15 * 60 + 30
        
        return market_open_minutes <= current_time_minutes <= market_close_minutes
    
    def get_market_status_info(self, current_time=None):
        """장 상태 정보 반환"""
        if current_time is None:
            current_time = datetime.now()
        
        is_open = self.is_market_open(current_time)
        
        if is_open:
            today_close = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            time_to_close = today_close - current_time
            
            hours, remainder = divmod(time_to_close.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            
            return {
                'status': 'OPEN',
                'message': f'장 시간 중 (마감까지 {int(hours)}시간 {int(minutes)}분)',
                'next_change': today_close,
                'is_trading_time': True
            }
        else:
            weekday = current_time.weekday()
            
            if weekday >= 5:  # 주말
                days_until_monday = 7 - weekday
                next_open = current_time + timedelta(days=days_until_monday)
                next_open = next_open.replace(hour=9, minute=0, second=0, microsecond=0)
                message = f'주말 휴장 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            elif current_time.hour < 9:
                next_open = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
                time_to_open = next_open - current_time
                hours, remainder = divmod(time_to_open.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                message = f'장 시작 전 (개장까지 {int(hours)}시간 {int(minutes)}분)'
            else:
                next_day = current_time + timedelta(days=1)
                while next_day.weekday() >= 5:
                    next_day += timedelta(days=1)
                
                next_open = next_day.replace(hour=9, minute=0, second=0, microsecond=0)
                message = f'장 마감 후 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            
            return {
                'status': 'CLOSED',
                'message': message,
                'next_change': next_open if 'next_open' in locals() else current_time + timedelta(hours=12),
                'is_trading_time': False
            }
    
    def run_hybrid_strategy(self, check_interval_minutes=30):
        """하이브리드 전략 실행"""
        self.logger.info("🚀 하이브리드 전략 시작")
        self.logger.info(f"📊 일봉 분석 + 분봉 실행 시스템")
        self.logger.info(f"⏰ 체크 간격: {check_interval_minutes}분")
        
        # 시작 알림
        symbol_list_with_names = [f"{s}({self.get_stock_name(s)})" for s in self.symbols]
        self.notifier.notify_system_start("하이브리드 전략", check_interval_minutes, symbol_list_with_names)
        
        daily_trades = 0
        last_daily_summary = datetime.now().date()
        last_position_update = datetime.now()
        
        try:
            while True:

                # 매 사이클마다 미체결 주문 확인
                self.order_tracker.check_all_pending_orders(
                    self.position_manager, 
                    self.get_stock_name
                )

                current_time = datetime.now()
                market_info = self.get_market_status_info(current_time)
                
                self.logger.info(f"🕐 현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                self.logger.info(f"📊 시장 상태: {market_info['status']} - {market_info['message']}")
                
                if market_info['is_trading_time']:
                    self.logger.info(f"📊 하이브리드 사이클 시작 - {current_time.strftime('%H:%M:%S')}")
                    
                    # 🔄 미체결 주문 확인 (매 사이클마다)
                    self.order_tracker.check_all_pending_orders(
                        self.position_manager, 
                        self.get_stock_name
                    )
                    cycle_start_trades = self.trade_count
                    
                    try:
                        # 포지션 업데이트 (10분마다)
                        if current_time - last_position_update > timedelta(minutes=10):
                            self.logger.info("🔄 포지션 정보 업데이트 중...")
                            self.update_all_positions()
                            last_position_update = current_time
                        
                        # 백테스트 파일 업데이트 확인 (1시간마다)
                        if current_time.hour % 1 == 0 and current_time.minute < 30:
                            if self.check_backtest_update():
                                self.reload_symbols_from_backtest()
                        
                        # 각 종목별 하이브리드 매매 실행
                        self.logger.info(f"🎯 종목별 하이브리드 분석 시작 (총 {len(self.symbols)}개)")
                        
                        for i, symbol in enumerate(self.symbols, 1):
                            stock_name = self.get_stock_name(symbol)
                            self.logger.info(f"🔍 [{i}/{len(self.symbols)}] {stock_name}({symbol}) 하이브리드 분석 시작")
                            
                            try:
                                trade_executed = self.hybrid_strategy.execute_hybrid_trade(symbol, self.positions)
                                
                                if trade_executed:
                                    daily_trades += 1
                                    self.trade_count += 1
                                    self.logger.info(f"✅ {stock_name}({symbol}) 하이브리드 매매 실행됨")
                                else:
                                    self.logger.info(f"⏸️ {stock_name}({symbol}) 매매 조건 미충족")
                                    
                                time.sleep(2)
                                
                            except Exception as e:
                                self.logger.error(f"❌ {stock_name}({symbol}) 하이브리드 실행 오류: {e}")
                        
                        # 기존 포지션 손익 관리
                        self.logger.info("💼 기존 포지션 손익 관리 중...")
                        self.process_sell_signals()
                        
                        cycle_end_trades = self.trade_count
                        cycle_trades = cycle_end_trades - cycle_start_trades
                        self.logger.info(f"✅ 하이브리드 사이클 완료 (이번 사이클 거래: {cycle_trades}회)")
                        
                    except Exception as e:
                        self.logger.error(f"❌ 하이브리드 실행 중 오류: {e}")
                        self.notifier.notify_error("하이브리드 실행 오류", str(e))
                
                else:
                    self.logger.info(f"⏰ 장 외 시간: {market_info['message']}")
                
                # 일일 요약 (장 마감 후 한 번만)
                if (current_time.date() != last_daily_summary and 
                    current_time.hour >= 16):
                    
                    self.logger.info(f"📈 일일 거래 요약 전송 중...")
                    self.notifier.notify_daily_summary(daily_trades, self.daily_pnl, daily_trades, symbol_list_with_names)
                    daily_trades = 0
                    self.daily_pnl = 0
                    last_daily_summary = current_time.date()
                
                # 대기 시간 계산
                if market_info['is_trading_time']:
                    sleep_time = check_interval_minutes * 60
                    next_run = current_time + timedelta(minutes=check_interval_minutes)
                    self.logger.info(f"⏰ 다음 하이브리드 체크: {next_run.strftime('%H:%M:%S')} ({check_interval_minutes}분 후)")
                else:
                    if current_time.weekday() >= 5:  # 주말
                        sleep_minutes = 120  # 2시간
                    else:
                        sleep_minutes = 60   # 1시간
                    
                    sleep_time = sleep_minutes * 60
                    next_run = current_time + timedelta(minutes=sleep_minutes)
                    self.logger.info(f"⏰ 다음 상태 체크: {next_run.strftime('%H:%M:%S')} ({sleep_minutes}분 후)")
                
                # 실제 대기
                self.logger.debug(f"😴 {sleep_time//60:.0f}분 대기 중...")
                
                # 긴 대기 시간을 작은 단위로 나누어 중간에 상태 확인
                sleep_chunk = 60  # 1분씩 나누어 대기
                remaining_sleep = sleep_time
                
                while remaining_sleep > 0:
                    chunk_sleep = min(sleep_chunk, remaining_sleep)
                    time.sleep(chunk_sleep)
                    remaining_sleep -= chunk_sleep
                    
                    # 5분마다 상태 로그
                    if remaining_sleep > 0 and int(remaining_sleep) % 300 == 0:
                        remaining_minutes = remaining_sleep // 60
                        self.logger.debug(f"⏳ 대기 중... (남은 시간: {remaining_minutes:.0f}분)")
                
                self.logger.debug("⏰ 대기 완료, 다음 사이클 시작")
                
        except KeyboardInterrupt:
            self.logger.info("🛑 사용자가 하이브리드 전략을 종료했습니다.")
            self.notifier.notify_system_stop("사용자 종료")
        except Exception as e:
            self.logger.error(f"❌ 하이브리드 전략 실행 중 치명적 오류: {e}")
            self.notifier.notify_error("하이브리드 전략 치명적 오류", str(e))
        finally:
            self.logger.info("🔚 하이브리드 전략 프로그램 종료")


def main():
    """메인 함수"""
    print("🚀 리팩토링된 자동매매 시스템 시작")
    print("="*50)

    try:
        # 의존성 확인
        print("1️⃣ 의존성 확인 중...")
        if not check_dependencies():
            print("❌ 의존성 확인 실패")
            sys.exit(1)
        print("✅ 의존성 확인 완료")

        # 로그 디렉토리 생성
        print("2️⃣ 로그 디렉토리 생성 중...")
        create_logs_directory()
        print("✅ 로그 디렉토리 생성 완료")

        # 자동매매 시스템 초기화
        print("3️⃣ 자동매매 시스템 초기화 중...")
        trader = AutoTrader()
        print("✅ 자동매매 시스템 초기화 완료")

        # 실행 모드 결정
        test_mode = '--test' in sys.argv
        debug_mode = '--debug' in sys.argv
        
        if test_mode:
            print("🧪 테스트 모드 실행")
            # 테스트 코드 실행
            test_symbol = trader.symbols[0] if trader.symbols else "005930"
            daily_analysis = trader.hybrid_strategy.analyze_daily_strategy(test_symbol)
            print(f"테스트 결과: {daily_analysis}")
        else:
            interval = 15 if debug_mode else 30
            print(f"🚀 하이브리드 전략 모드 시작 (체크 간격: {interval}분)")
            trader.run_hybrid_strategy(check_interval_minutes=interval)

    except Exception as e:
        print(f"❌ 프로그램 실행 중 오류: {e}")
        import traceback
        print(f"상세 오류:\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
