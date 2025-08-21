"""
메인 실행 파일 - 리팩토링된 자동매매 시스템
"""
import os
import sys
import time
import json
import logging
import pandas as pd  # 추가된 import
import numpy as np   # 추가된 import
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 기존 import들...
try:
    from config.config_manager import ConfigManager
    from data.kis_api_client import KISAPIClient
    from trading.position_manager import PositionManager
    from trading.order_manager import OrderManager
    from trading.order_tracker import OrderTracker
    from strategy.hybrid_strategy import HybridStrategy
    from notification.discord_notifier import DiscordNotifier
    from utils.logger import setup_logger
    from utils.helpers import create_logs_directory, check_dependencies
    #print("✅ 모든 모듈 임포트 성공")
except ImportError as e:
    print(f"❌ 모듈 임포트 실패: {e}")
    sys.exit(1)


class AutoTrader:
    """메인 자동매매 클래스"""
    
    def __init__(self, config_path: str = "config.yaml"):
        # 설정 로드
        self.config_manager = ConfigManager(config_path)
        
        # 로거 설정
        self.logger = setup_logger()
        
        # 기본 변수들 먼저 초기화
        self.positions = {}
        self.all_positions = {}
        self.symbols = []
        self.stock_names = {}
        self.daily_pnl = 0
        self.trade_count = 0
        
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
        self.stop_loss_pct = 0.06  # 개선: 8% → 6%
        self.take_profit_pct = 0.20  # 개선: 25% → 20%
        
        # 종목 및 종목명 로드 (다른 초기화 전에 먼저)
        self.load_stock_names()
        self.load_symbols_and_names()
        
        # 포지션 관리자 초기화
        position_config = self.config_manager.get_position_config()
        self.position_manager = PositionManager(
            logger=self.logger,
            max_purchases_per_symbol=position_config.get('max_purchases_per_symbol', 2),
            max_quantity_per_symbol=position_config.get('max_quantity_per_symbol', 200),  # 개선: 300 → 200
            min_holding_period_hours=position_config.get('min_holding_period_hours', 72),
            purchase_cooldown_hours=position_config.get('purchase_cooldown_hours', 48)
        )
        
        # 주문 관리자 초기화 (get_stock_name 메서드가 이제 존재함)
        self.order_manager = OrderManager(
            api_client=self.api_client,
            logger=self.logger,
            max_position_ratio=trading_config.get('max_position_ratio', 0.25),  # 개선: 0.4 → 0.25
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

        # 하이브리드 전략 초기화 (get_stock_name 메서드가 이제 존재함)
        self.hybrid_strategy = HybridStrategy(
            api_client=self.api_client,
            order_manager=self.order_manager,
            position_manager=self.position_manager,
            notifier=self.notifier,
            logger=self.logger,
            order_tracker=self.order_tracker, 
            get_stock_name_func=self.get_stock_name
        )

        # 자동 종료 설정 추가
        system_config = self.config_manager.get_system_config()
        self.auto_shutdown_enabled = system_config.get('auto_shutdown_enabled', True)
        self.weekend_shutdown_enabled = system_config.get('weekend_shutdown_enabled', True)
        self.shutdown_delay_hours = system_config.get('shutdown_delay_hours', 1)

        # 일일 성과 추적기 추가
        from monitoring.daily_performance import DailyPerformanceTracker
        self.daily_tracker = DailyPerformanceTracker(self.api_client, self.logger)
    
        self.logger.info("✅ 개선된 자동매매 시스템 초기화 완료")


    def check_market_close_shutdown(self, current_time=None):
        """장 마감 시 자동 종료 확인"""
        if current_time is None:
            current_time = datetime.now()
        
        market_info = self.get_market_status_info(current_time)
        
        # 장 마감 후 자동 종료 조건
        if self.auto_shutdown_enabled and market_info['status'] == 'CLOSED':
            hour = current_time.hour
            weekday = current_time.weekday()
            
            # 평일 장 마감 후 (15:30 + shutdown_delay_hours 이후)
            shutdown_hour = 15 + self.shutdown_delay_hours
            if weekday < 5 and hour >= shutdown_hour:
                self.logger.info("🏁 장 마감 후 자동 종료 조건 충족")
                return True, "평일 장 마감"
            
            # 주말 자동 종료
            if self.weekend_shutdown_enabled and weekday >= 5 and hour >= 18:
                self.logger.info("🏁 주말 자동 종료 조건 충족")
                return True, "주말 자동 종료"

        return False, None

    def reload_symbols_from_discovery(self) -> bool:
        """종목발굴 결과에서 종목 다시 로드"""
        try:
            old_symbols = set(self.symbols)
            self.load_symbols_and_names()
            new_symbols_set = set(self.symbols)
            
            added_symbols = new_symbols_set - old_symbols
            removed_symbols = old_symbols - new_symbols_set
            
            if added_symbols or removed_symbols:
                self.notifier.notify_symbol_changes(added_symbols, removed_symbols, self.get_stock_name)
            
            self.last_symbol_update = time.time()
            return True
            
        except Exception as e:
            self.logger.error(f"종목발굴 결과 재로드 실패: {e}")
            return False

    def process_sell_for_symbol(self, symbol: str, position: dict):
        """개선된 개별 종목 매도 처리"""
        try:
            if symbol not in self.all_positions:
                return
                
            quantity = position['quantity']
            profit_loss_pct = position['profit_loss']
            profit_loss_decimal = profit_loss_pct / 100
            stock_name = self.get_stock_name(symbol)
            current_price = position['current_price']
            
            # 1순위: 강화된 손절 (6%)
            if profit_loss_decimal <= -self.stop_loss_pct:
                self.logger.warning(f"🛑 {stock_name}({symbol}) 강화된 손절! ({profit_loss_pct:+.2f}%)")
                self.execute_sell(symbol, quantity, "urgent", "강화된손절")
                return
            
            # 2순위: 급락 감지 손절
            rapid_drop = self.check_rapid_drop(symbol, current_price)
            if rapid_drop['should_sell']:
                self.logger.warning(f"💥 {stock_name}({symbol}) 급락 감지: {rapid_drop['reason']}")
                self.execute_sell(symbol, quantity, "urgent", rapid_drop['reason'])
                return
            
            # 3순위: 빠른 익절 (20%)
            if profit_loss_decimal >= self.take_profit_pct:
                can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                
                if can_sell:
                    self.logger.info(f"🎯 {stock_name}({symbol}) 빠른 익절! ({profit_loss_pct:+.2f}%)")
                    self.execute_sell(symbol, quantity, "aggressive_limit", "빠른익절")
                    return
                else:
                    self.logger.info(f"💎 {stock_name}({symbol}) 익절 조건이지만 보유 지속: {sell_reason}")
            
            # 4순위: 강화된 기술적 매도 (4.0점)
            if symbol in self.symbols:
                daily_analysis = self.hybrid_strategy.analyze_daily_strategy(symbol)
                
                if daily_analysis['signal'] == 'SELL' and daily_analysis['strength'] >= 4.0:
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    
                    if can_sell:
                        self.logger.info(f"📉 {stock_name}({symbol}) 강한 기술적 매도")
                        self.execute_sell(symbol, quantity, "aggressive_limit", "강한기술적매도")
                        return
                
        except Exception as e:
            self.logger.error(f"{symbol} 매도 처리 중 오류: {e}")

    def check_rapid_drop(self, symbol: str, current_price: float) -> Dict:
        """급락 감지 시스템"""
        try:
            minute_df = self.api_client.get_minute_data(symbol, minutes=60)
            
            if minute_df.empty or len(minute_df) < 10:
                return {'should_sell': False, 'reason': '데이터부족'}
            
            # 1시간 전 가격과 비교
            hour_ago_price = minute_df['stck_prpr'].iloc[0]
            hour_change = (current_price - hour_ago_price) / hour_ago_price
            
            # 30분 내 최고가와 비교
            recent_30min = minute_df.tail(30)
            if not recent_30min.empty:
                recent_high = recent_30min['stck_prpr'].max()
                drop_from_high = (current_price - recent_high) / recent_high
                
                # 급락 조건
                if hour_change < -0.05:  # 1시간 내 5% 급락
                    return {'should_sell': True, 'reason': f"1시간급락({hour_change:.1%})"}
                elif drop_from_high < -0.08:  # 30분 고점 대비 8% 급락
                    return {'should_sell': True, 'reason': f"단기급락({drop_from_high:.1%})"}
            
            return {'should_sell': False, 'reason': '정상'}
            
        except Exception as e:
            return {'should_sell': False, 'reason': f'오류:{e}'}

    def load_symbols_and_names(self):
        """종목 및 종목명 로드 - 환경파일 + trading_list.json 합치기"""
        try:
            all_symbols = []
            all_stock_names = {}
            
            # 1. 환경파일에서 기본 종목 로드
            trading_config = self.config_manager.get_trading_config()
            config_symbols = trading_config.get('symbols', [])
            
            if config_symbols:
                all_symbols.extend(config_symbols)
                self.logger.info(f"설정 파일에서 {len(config_symbols)}개 종목 로드: {config_symbols}")
            
            # 2. trading_list.json에서 추가 종목 로드
            trading_list_file = "trading_list.json"
            if os.path.exists(trading_list_file):
                with open(trading_list_file, 'r', encoding='utf-8') as f:
                    candidate_data = json.load(f)
                
                if isinstance(candidate_data, list) and candidate_data:
                    sorted_candidates = sorted(candidate_data, key=lambda x: x.get('score', 0), reverse=True)
                    
                    trading_list_symbols = []
                    for item in sorted_candidates:
                        code = item['code']
                        if code not in all_symbols:
                            trading_list_symbols.append(code)
                            all_stock_names[code] = item.get('name', code)
                    
                    all_symbols.extend(trading_list_symbols)
                    self.logger.info(f"trading_list.json에서 {len(trading_list_symbols)}개 종목 추가")
            
            # 3. max_symbols 제한 적용
            if len(all_symbols) > self.max_symbols:
                final_symbols = config_symbols[:self.max_symbols]
                remaining_slots = self.max_symbols - len(final_symbols)
                if remaining_slots > 0:
                    trading_list_only = [s for s in all_symbols if s not in config_symbols]
                    final_symbols.extend(trading_list_only[:remaining_slots])
                self.symbols = final_symbols
            else:
                self.symbols = all_symbols
            
            # 4. 종목명 설정 (trading_list의 name만 미리 설정)
            self.stock_names.update(all_stock_names)
            
            self.logger.info(f"✅ 총 {len(self.symbols)}개 종목 선택 (최대: {self.max_symbols}개)")
            # get_stock_name이 필요할 때마다 자동으로 API 조회함
            self.logger.info(f"최종 선택 종목: {[f'{self.get_stock_name(s)}({s})' for s in self.symbols]}")
            
            if not self.symbols:
                self.symbols = ['278470', '062040', '042660']
                self.logger.warning("종목이 없어 기본 종목 사용")
                        
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
        """종목명 조회 - 캐시 우선, 없으면 종목기본정보 API 조회"""
        # 이미 캐시된 종목명이 있으면 사용
        if code in self.stock_names:
            return self.stock_names[code]
        
        # 종목기본정보 API로 종목명 조회
        try:
            basic_info = self.api_client.get_stock_basic_info(code)
            
            if basic_info and basic_info.get('output'):
                output = basic_info['output']
                
                # prdt_abrv_name 필드에서 종목명 가져오기
                if 'prdt_abrv_name' in output and output['prdt_abrv_name']:
                    stock_name = str(output['prdt_abrv_name']).strip()
                
                    if stock_name:
                        # 캐시에 저장
                        self.stock_names[code] = stock_name
                        self.save_stock_names()
                        self.logger.info(f"✅ {code} 종목명 조회 성공: {stock_name}")
                        return stock_name
                
        except Exception as e:
            self.logger.warning(f"❌ {code} 종목기본정보 조회 오류: {e}")
        
        # 조회 실패 시 코드 반환
        return code

    def save_stock_names(self):
        """종목명을 파일에 저장"""
        try:
            with open('stock_names.json', 'w', encoding='utf-8') as f:
                json.dump(self.stock_names, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.debug(f"종목명 저장 실패: {e}")

    
    def check_symbol_list_update(self) -> bool:
        """종목 리스트 업데이트 확인"""
        try:
            current_time = time.time()
            if hasattr(self, 'last_symbol_check'):
                if current_time - self.last_symbol_check < 3600:  # 1시간 이내 체크했으면 스킵
                    return False
        
            self.last_symbol_check = current_time
        
            if not hasattr(self, 'last_symbol_update'):
                self.last_symbol_update = 0
            
            if os.path.exists("trading_list.json"):
                file_mtime = os.path.getmtime("trading_list.json")
                
                # 파일이 업데이트되었는지 확인
                if file_mtime > self.last_symbol_update:
                    self.logger.info("📋 trading_list.json 업데이트 감지")
                    return True
            
            return False
        
        except Exception as e:
            self.logger.error(f"종목 리스트 업데이트 확인 오류: {e}")
            return False

    def update_all_positions(self):
        """모든 보유 종목 포지션 업데이트"""
        try:
            self.all_positions = self.api_client.get_all_holdings()
            
            # 매수후보 종목 중 보유 개수 확인
            candidate_holdings = sum(1 for symbol in self.symbols if symbol in self.all_positions)
        
            self.logger.info(f"💼 포지션 업데이트: 매수후보 {len(self.symbols)}개 중 보유 {candidate_holdings}개, 전체보유 {len(self.all_positions)}개")
            
        except Exception as e:
            self.logger.error(f"포지션 업데이트 실패: {e}")

    def execute_sell(self, symbol: str, quantity: int, order_strategy: str, reason: str):
        """매도 실행 - 알림 개선"""
        stock_name = self.get_stock_name(symbol)
        
        # 주문 추적기 사용
        result = self.order_manager.place_order_with_tracking(
            symbol, 'SELL', quantity, order_strategy, self.order_tracker
        )
        
        if result['success']:
            executed_price = result.get('limit_price', 0)
            order_no = result.get('order_no', 'Unknown')
            
            # 시장가 주문인 경우 즉시 포지션에 기록
            if executed_price == 0:
                current_price_data = self.api_client.get_current_price(symbol)
                if current_price_data and current_price_data.get('output'):
                    executed_price = float(current_price_data['output'].get('stck_prpr', 0))
                
                self.position_manager.record_sale(symbol, quantity, executed_price, reason)
            
            # 메모리에서 포지션 제거
            try:
                if symbol in self.positions:
                    del self.positions[symbol]
                if symbol in self.all_positions:
                    del self.all_positions[symbol]
            except KeyError:
                pass
            
            self.logger.info(f"✅ {stock_name}({symbol}) 매도 완료: {quantity}주 @ {executed_price:,}원 - {reason}")
            
            # 강제 알림 전송
            if self.notifier.webhook_url:
                self.notifier.notify_trade_success('SELL', symbol, quantity, executed_price, order_no, stock_name)
            
            return True
        else:
            error_msg = result.get('error', 'Unknown error')
            self.logger.error(f"❌ {stock_name}({symbol}) 매도 실패: {error_msg}")
            
            # 실패 알림
            if self.notifier.webhook_url:
                self.notifier.notify_trade_failure('SELL', symbol, error_msg, stock_name)
            
            return False
    
    def is_market_open(self, current_time=None):
        """한국 증시 개장 시간 확인"""
        if current_time is None:
            current_time = datetime.now()
        
        weekday = current_time.weekday()
        if weekday >= 5:
            return False
        
        hour = current_time.hour
        minute = current_time.minute
        current_time_minutes = hour * 60 + minute
        
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
            
            if weekday >= 5:
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
        """개선된 하이브리드 전략 실행 - 자동 종료 기능 추가"""
        self.logger.info("🚀 개선된 하이브리드 전략 시작 (자동 종료 기능 포함)")
        self.logger.info(f"📊 고점 매수 방지 + 빠른 손절 시스템")
        self.logger.info(f"⏰ 체크 간격: {check_interval_minutes}분")
        self.logger.info(f"🏁 자동 종료: {'활성화' if self.auto_shutdown_enabled else '비활성화'}")
        
        symbol_list_with_names = [f"{self.get_stock_name(s)}({s})" for s in self.symbols]
        self.notifier.notify_system_start("개선된 하이브리드 (자동종료)", check_interval_minutes, symbol_list_with_names)
        
        daily_trades = 0
        last_daily_summary = datetime.now().date()
        last_position_update = datetime.now()
        
        try:
            while True:
                current_time = datetime.now()
                
                market_info = self.get_market_status_info(current_time)

                # 🆕 시작 시 자동 종료 조건 확인
                should_shutdown, shutdown_reason = self.check_market_close_shutdown(current_time)
                if should_shutdown:
                    # 🆕 종료 전 일일 요약 전송
                    self.logger.info("📊 종료 전 일일 거래 요약 전송 중...")
                    self.send_daily_summary()

                    self.logger.info(f"🏁 자동 종료 실행: {shutdown_reason}")
                    self.notifier.notify_system_stop(f"자동 종료 - {shutdown_reason}")
                    break
                
                self.order_tracker.check_all_pending_orders(self.position_manager, self.get_stock_name)

                market_info = self.get_market_status_info(current_time)
                
                self.logger.info(f"🕐 {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                self.logger.info(f"📊 시장: {market_info['status']} - {market_info['message']}")
                
                if market_info['is_trading_time']:
                    cycle_start_trades = self.trade_count
                    
                    try:
                        if current_time - last_position_update > timedelta(minutes=10):
                            self.update_all_positions()
                            last_position_update = current_time
                        
                        if (current_time.hour % 2 == 0 and 
                            0 <= current_time.minute <= 5 and 
                            self.check_symbol_list_update()):
                            self.logger.info("🔄 종목 리스트 업데이트 시작")
                            self.reload_symbols_from_discovery()
                        
                        # 🆕 매도 분석 전에 포지션 업데이트 실행
                        self.logger.info("🔄 포지션 업데이트 중...")
                        self.update_all_positions()

                        # 개선된 매도 로직 먼저 실행
                        self.logger.info("💼 개선된 손절/익절 시스템 실행...")
                        self.logger.info(f"📊 현재 보유 종목: {len(self.all_positions)}개")
                        for symbol, position in list(self.all_positions.items()):
                            try:
                                stock_name = self.get_stock_name(symbol)
                                self.logger.info(f"🔍 {stock_name}({symbol}) 매도 분석: {position['profit_loss']:+.2f}%")
                                self.process_sell_for_symbol(symbol, position)
                                time.sleep(0.2)
                            except Exception as e:
                                self.logger.error(f"{symbol} 매도 처리 오류: {e}")
                        
                        # 종목별 하이브리드 매수
                        self.logger.info(f"🎯 고점 방지 매수 분석 시작 (총 {len(self.symbols)}개)")
                        
                        for i, symbol in enumerate(self.symbols, 1):
                            stock_name = self.get_stock_name(symbol)
                            self.logger.info(f"🔍 [{i}/{len(self.symbols)}] {stock_name}({symbol}) 분석 시작")
                            
                            try:

                                trade_executed = self.hybrid_strategy.execute_hybrid_trade(symbol, self.positions)
      
                                if trade_executed:
                                    daily_trades += 1
                                    self.trade_count += 1
                                    self.logger.info(f"  🎉 {stock_name}({symbol}) 매수 완료!")
                                else:
                                    self.logger.debug(f"  ⏸️ {stock_name}({symbol}) 타이밍 부적절")
            
                                time.sleep(2)
                                
                            except Exception as e:
                                self.logger.error(f"❌ {stock_name}({symbol}) 분석 오류: {e}")
                        
                        cycle_end_trades = self.trade_count
                        cycle_trades = cycle_end_trades - cycle_start_trades
                        self.logger.info(f"✅ 간소화된 사이클 완료 (거래: {cycle_trades}회)")
                        
                    except Exception as e:
                        self.logger.error(f"❌ 사이클 실행 오류: {e}")
                        self.notifier.notify_error("개선된 시스템 오류", str(e))
                
                else:
                    self.logger.info(f"⏰ 장 외 시간: {market_info['message']}")

                    # 🆕 장 외 시간에도 자동 종료 조건 확인
                    should_shutdown, shutdown_reason = self.check_market_close_shutdown(current_time)
                    if should_shutdown:
                    # 🆕 종료 전 일일 요약 전송
                        self.logger.info("📊 종료 전 일일 거래 요약 전송 중...")
                        self.send_daily_summary()

                        self.logger.info(f"🏁 장 외 자동 종료 실행: {shutdown_reason}")
                        self.notifier.notify_system_stop(f"자동 종료 - {shutdown_reason}")
                        break
                
                
                # 대기 시간 계산
                if market_info['is_trading_time']:
                    sleep_time = check_interval_minutes * 60
                    next_run = current_time + timedelta(minutes=check_interval_minutes)
                    self.logger.info(f"⏰ 다음 체크: {next_run.strftime('%H:%M:%S')}")
                else:
                    # 🆕 장 외 시간 대기 시간 단축 (자동 종료 체크를 위해)
                    sleep_minutes = 30 if current_time.weekday() >= 5 else 30  # 기존 120분 → 30분으로 단축
                    sleep_time = sleep_minutes * 60
                    next_run = current_time + timedelta(minutes=sleep_minutes)
                    self.logger.info(f"⏰ 다음 체크: {next_run.strftime('%H:%M:%S')} (자동 종료 체크 포함)")
                
                # 분할 대기 (자동 종료 체크를 위해 더 자주 확인)
                sleep_chunk = 60  # 1분마다 체크
                remaining_sleep = sleep_time
                
                while remaining_sleep > 0:
                    chunk_sleep = min(sleep_chunk, remaining_sleep)
                    time.sleep(chunk_sleep)
                    remaining_sleep -= chunk_sleep
                    
                    # 🆕 대기 중에도 자동 종료 체크
                    if remaining_sleep > 0:
                        current_time_check = datetime.now()
                        should_shutdown, shutdown_reason = self.check_market_close_shutdown(current_time_check)
                        if should_shutdown:
                            self.logger.info(f"🏁 대기 중 자동 종료 실행: {shutdown_reason}")
                            self.notifier.notify_system_stop(f"자동 종료 - {shutdown_reason}")
                            return  # while 루프 종료
                    
                    if remaining_sleep > 0 and int(remaining_sleep) % 300 == 0:
                        remaining_minutes = remaining_sleep // 60
                        self.logger.debug(f"⏳ 대기 중... (남은 시간: {remaining_minutes:.0f}분)")
                
        except KeyboardInterrupt:
            self.send_daily_summary()
            self.logger.info("🛑 사용자가 개선된 시스템을 종료했습니다.")
            self.notifier.notify_system_stop("사용자 종료")
        except Exception as e:
            self.logger.error(f"❌ 개선된 시스템 치명적 오류: {e}")
            self.notifier.notify_error("개선된 시스템 오류", str(e))
            self.send_daily_summary()
        finally:
            self.logger.info("🔚 개선된 하이브리드 시스템 종료")

    def send_daily_summary(self):
        """일일 요약 전송 - 거래 내역이 없어도 포트폴리오 현황 전송"""
        try:
            self.logger.info("📊 일일 포트폴리오 현황 생성 중...")
            
            # 일일 요약 계산
            summary = self.daily_tracker.calculate_daily_summary()
            
            # 🆕 데이터가 없어도 기본 요약 전송
            if not summary:
                self.logger.warning("⚠️ 포트폴리오 데이터 조회 실패")
                self.notifier.send_notification(
                    "⚠️ 포트폴리오 현황", 
                    f"오늘 ({datetime.now().strftime('%Y-%m-%d')}) 포트폴리오 데이터를 조회할 수 없습니다.", 
                    0xff0000
                )
                return
            
            # 트렌드 분석
            trend_analysis = self.daily_tracker.get_trend_analysis(7)
            
            # 🆕 항상 Discord 알림 전송
            success = self.notifier.notify_daily_summary(summary, trend_analysis)
            
            if success:
                self.logger.info("✅ 일일 포트폴리오 현황 Discord 전송 완료")
            else:
                self.logger.error("❌ 일일 포트폴리오 현황 Discord 전송 실패")
            
            # 콘솔 요약
            total_profit_loss = summary.get('total_profit_loss', 0)
            total_return_pct = summary.get('total_return_pct', 0)
            total_assets = summary.get('total_assets', 0)
            position_count = summary.get('position_count', 0)
            today_trades = len(summary.get('today_trades', []))
            
            self.logger.info("=" * 60)
            self.logger.info("📊 일일 포트폴리오 현황")
            self.logger.info("=" * 60)
            self.logger.info(f"💰 총 자산: {total_assets:,.0f}원")
            
            if position_count > 0:
                self.logger.info(f"📈 평가손익: {total_profit_loss:+,.0f}원 ({total_return_pct:+.2f}%)")
                self.logger.info(f"📋 보유종목: {position_count}개")
            else:
                self.logger.info("📋 보유종목: 없음")
            
            self.logger.info(f"🔄 오늘 프로그램 거래: {today_trades}건")
            self.logger.info("=" * 60)
            
        except Exception as e:
            self.logger.error(f"❌ 일일 현황 전송 실패: {e}")
            
            try:
                self.notifier.send_notification(
                    "⚠️ 포트폴리오 현황 오류", 
                    f"포트폴리오 현황 생성 중 오류: {str(e)}", 
                    0xff0000
                )
            except:
                pass

def main():
    """메인 함수"""
    print("🚀 개선된 자동매매 시스템 시작")
    print("="*50)

    try:
        # 의존성 확인
        if not check_dependencies():
            sys.exit(1)
        #print("✅ 의존성 확인 완료")

        #print("2️⃣ 로그 디렉토리 생성 중...")
        create_logs_directory()
        #print("✅ 로그 디렉토리 생성 완료")

        #print("3️⃣ 개선된 시스템 초기화 중...")
        trader = AutoTrader()
        #print("✅ 개선된 시스템 초기화 완료")

        # 실행 모드
        test_mode = '--test' in sys.argv
        debug_mode = '--debug' in sys.argv
        
        if test_mode:
            print("🧪 테스트 모드 실행")
            test_symbol = trader.symbols[0] if trader.symbols else "005930"
            daily_analysis = trader.hybrid_strategy.analyze_daily_strategy(test_symbol)
            print(f"테스트 결과: {daily_analysis}")
        else:
            interval = 15 if debug_mode else 30
            print(f"🚀 개선된 하이브리드 모드 시작 (체크 간격: {interval}분)")
            trader.run_hybrid_strategy(check_interval_minutes=interval)

    except Exception as e:
        print(f"❌ 프로그램 실행 중 오류: {e}")
        import traceback
        print(f"상세 오류:\n{traceback.format_exc()}")


if __name__ == "__main__":
    from market_schedule_checker import check_market_schedule_and_exit
    check_market_schedule_and_exit()

    main()
