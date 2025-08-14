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
#print(f"현재 디렉토리: {current_dir}")
#print(f"Python 경로: {sys.path[:3]}")

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
    if not os.path.exists(full_path):
        #print(f"✅ {file_path}")
    #else:
        print(f"❌ {file_path} - 파일이 없습니다!")

# 프로젝트 모듈 임포트
try:
    from config.config_manager import ConfigManager
    #print("✅ ConfigManager 임포트 성공")
except ImportError as e:
    print(f"❌ ConfigManager 임포트 실패: {e}")
    sys.exit(1)

try:
    from data.kis_api_client import KISAPIClient
    #print("✅ KISAPIClient 임포트 성공")
except ImportError as e:
    print(f"❌ KISAPIClient 임포트 실패: {e}")
    sys.exit(1)

try:
    from trading.position_manager import PositionManager
    #print("✅ PositionManager 임포트 성공")
except ImportError as e:
    print(f"❌ PositionManager 임포트 실패: {e}")
    sys.exit(1)

try:
    from trading.order_manager import OrderManager
    #print("✅ OrderManager 임포트 성공")
except ImportError as e:
    print(f"❌ OrderManager 임포트 실패: {e}")
    sys.exit(1)

try:
    from trading.order_tracker import OrderTracker
    #print("✅ OrderTracker 임포트 성공")
except ImportError as e:
    print(f"❌ OrderTracker 임포트 실패: {e}")
    sys.exit(1)

try:
    from strategy.hybrid_strategy import HybridStrategy
    #print("✅ HybridStrategy 임포트 성공")
except ImportError as e:
    print(f"❌ HybridStrategy 임포트 실패: {e}")
    sys.exit(1)

try:
    from notification.discord_notifier import DiscordNotifier
    #print("✅ DiscordNotifier 임포트 성공")
except ImportError as e:
    print(f"❌ DiscordNotifier 임포트 실패: {e}")
    sys.exit(1)

try:
    from utils.logger import setup_logger
    #print("✅ setup_logger 임포트 성공")
except ImportError as e:
    print(f"❌ setup_logger 임포트 실패: {e}")
    sys.exit(1)

try:
    from utils.helpers import create_logs_directory, check_dependencies
    #print("✅ helpers 임포트 성공")
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
        self.max_symbols = trading_config.get('max_symbols', 5)
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
    

    def run_hybrid_strategy(self, check_interval_minutes=30):
        """하이브리드 전략 실행"""
        self.logger.info("🚀 하이브리드 전략 시작")
        self.logger.info(f"📊 일봉 분석 + 분봉 실행 시스템")
        self.logger.info(f"⏰ 체크 간격: {check_interval_minutes}분")
        
        # 시작 알림
        symbol_list_with_names = [f"{self.get_stock_name(s)}({s})" for s in self.symbols]
        self.notifier.notify_system_start("하이브리드 전략", check_interval_minutes, symbol_list_with_names)
        
        # 🆕 시작 시 초기 포지션 로드
        self.logger.info("📊 시작 시 포지션 정보 로드 중...")
        self.update_all_positions()
        
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
                    
                    cycle_start_trades = self.trade_count
                    
                    try:
                        # 포지션 업데이트 (첫 사이클 또는 10분마다)
                        if (current_time - last_position_update > timedelta(minutes=10) or 
                            not hasattr(self, '_initial_position_loaded')):
                            self.logger.info("🔄 포지션 정보 업데이트 중...")
                            self.update_all_positions()
                            last_position_update = current_time
                            self._initial_position_loaded = True
                        
                        # 백테스트 파일 업데이트 확인 (1시간마다)
                        if current_time.hour % 1 == 0 and current_time.minute < 30:
                            if self.def check_backtest_update(self) -> bool:
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
        """매도 신호 처리 - 로그 개선 버전"""
        if not self.all_positions:
            return
        
        positions_to_process = dict(self.all_positions)
        
        for i, (symbol, position) in enumerate(positions_to_process.items(), 1):
            stock_name = self.get_stock_name(symbol)
            self.logger.info(f"🔍 [매도 {i}/{len(positions_to_process)}] {stock_name}({symbol}) 매도 분석 시작")
            
            try:
                if symbol not in self.all_positions:
                    self.logger.info(f"⏭️ {stock_name}({symbol}) 포지션 없음 - 매도 분석 제외")
                    continue
                    
                self.process_sell_for_symbol(symbol, position)
                time.sleep(0.5)
            except Exception as e:
                self.logger.error(f"❌ {stock_name}({symbol}) 매도 처리 오류: {e}")
    
    def process_sell_for_symbol(self, symbol: str, position: dict):
        """개별 종목 매도 처리 - 로그 개선 버전"""
        stock_name = self.get_stock_name(symbol)
        
        try:
            if symbol not in self.all_positions:
                self.logger.info(f"⏭️ {stock_name}({symbol}) 포지션 이미 청산됨")
                return
                
            quantity = position['quantity']
            profit_loss_pct = position['profit_loss']
            profit_loss_decimal = profit_loss_pct / 100
            current_price = position.get('current_price', 0)
            
            self.logger.info(f"📊 {stock_name}({symbol}) 현재 수익률: {profit_loss_pct:+.2f}% ({quantity}주, {current_price:,}원)")
            
            # 1순위: 손절 (무조건 실행)
            if profit_loss_decimal <= -self.stop_loss_pct:
                self.logger.warning(f"🛑 {stock_name}({symbol}) 손절 조건 충족! ({profit_loss_pct:+.2f}% <= -{self.stop_loss_pct:.1%})")
                self.execute_sell(symbol, quantity, "urgent", "손절매")
                return
            
            # 2순위: 익절 (최소 보유기간 확인)
            if profit_loss_decimal >= self.take_profit_pct:
                can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                
                if can_sell:
                    self.logger.info(f"🎯 {stock_name}({symbol}) 익절 조건 충족! ({profit_loss_pct:+.2f}% >= +{self.take_profit_pct:.1%})")
                    self.execute_sell(symbol, quantity, "patient_limit", "익절매")
                    return
                else:
                    self.logger.info(f"💎 {stock_name}({symbol}) 익절 조건이지만 보유 지속: {sell_reason}")
            
            # 3순위: 매도 신호 확인 (거래 대상 종목만)
            if symbol in self.symbols:
                self.logger.info(f"📅 {stock_name}({symbol}) 일봉 매도 신호 분석 시작")
                daily_analysis = self.hybrid_strategy.analyze_daily_strategy(symbol)
                
                if daily_analysis['signal'] == 'SELL' and daily_analysis['strength'] >= 3.0:
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    
                    if can_sell:
                        self.logger.info(f"📉 {stock_name}({symbol}) 일봉 매도 신호 감지 (강도: {daily_analysis['strength']:.1f})")
                        self.execute_sell(symbol, quantity, "aggressive_limit", "일봉 매도신호")
                        return
                    else:
                        self.logger.info(f"⏰ {stock_name}({symbol}) 일봉 매도신호이지만 보유 지속: {sell_reason}")
                else:
                    signal_text = daily_analysis.get('signal', 'UNKNOWN')
                    strength = daily_analysis.get('strength', 0)
                    self.logger.info(f"📈 {stock_name}({symbol}) 일봉 매도신호 없음 ({signal_text}, 강도: {strength:.1f})")
            else:
                self.logger.info(f"⚪ {stock_name}({symbol}) 거래대상 외 종목 - 일봉 분석 제외")
            
            # 매도 조건 미충족
            self.logger.info(f"✋ {stock_name}({symbol}) 매도 조건 미충족 - 보유 지속")
            
        except Exception as e:
            self.logger.error(f"❌ {stock_name}({symbol}) 매도 처리 중 오류: {e}")
    
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
