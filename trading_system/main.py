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
        """보수적 매도 처리 - 좋은 종목 보호 우선"""
        try:
            if symbol not in self.all_positions:
                return
                
            quantity = position['quantity']
            profit_loss_pct = position['profit_loss']
            profit_loss_decimal = profit_loss_pct / 100
            stock_name = self.get_stock_name(symbol)
            current_price = position['current_price']
            
            # 🔥 1순위: 극단적 손실 방지 (-7% 이상 손실시 무조건 손절) - 기존 유지
            if profit_loss_decimal <= -0.07:
                self.logger.warning(f"🛑 {stock_name}({symbol}) 극한 손절! ({profit_loss_pct:+.2f}%)")
                self.execute_sell(symbol, quantity, "urgent", "극한손절")
                return
            
            # 🔥 2순위: 단계적 익절 시스템 - 기존 유지  
            if profit_loss_decimal >= 0.15:  # 15% 이상 익절
                can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                if can_sell:
                    self.logger.info(f"🎯 {stock_name}({symbol}) 1차 익절! ({profit_loss_pct:+.2f}%)")
                    self.execute_sell(symbol, quantity, "aggressive_limit", "1차익절")
                    return
            elif profit_loss_decimal >= 0.10:  # 10% 이상에서 기술적 확인 후 익절
                daily_analysis = self.hybrid_strategy.analyze_daily_strategy(symbol)
                if daily_analysis['signal'] == 'SELL' and daily_analysis['strength'] >= 2.0:
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    if can_sell:
                        self.logger.info(f"🎯 {stock_name}({symbol}) 기술적 익절! ({profit_loss_pct:+.2f}%)")
                        self.execute_sell(symbol, quantity, "aggressive_limit", "기술적익절")
                        return
            
            # 🆕 3순위: 현재 상승 중이면 미래 점수 무시하고 보유 (NEW!)
            daily_analysis = self.hybrid_strategy.analyze_daily_strategy(symbol)
            if daily_analysis['signal'] == 'BUY' and daily_analysis['strength'] >= 3.0:
                self.logger.info(f"📈 {stock_name}({symbol}) 상승신호로 보유유지: "
                               f"매수신호 {daily_analysis['strength']:.1f}점 ({profit_loss_pct:+.2f}%)")
                return
            
            # 🆕 추가 조건: 당일 상승률로도 판단
            if profit_loss_pct > 3.0:  # 당일 3% 이상 상승
                # 분봉 데이터로 상승 추세 확인
                minute_df = self.api_client.get_minute_data(symbol, minutes=30)
                if not minute_df.empty and len(minute_df) >= 10:
                    recent_prices = minute_df['stck_prpr'].tail(10).tolist()
                    rising_count = sum(1 for i in range(1, len(recent_prices)) 
                                     if recent_prices[i] > recent_prices[i-1])
        
                    if rising_count >= 6:  # 10분 중 6분 이상 상승
                        self.logger.info(f"📈 {stock_name}({symbol}) 실시간상승추세로 보유유지: "
                                       f"분봉상승 {rising_count}/10, 수익률 {profit_loss_pct:+.2f}%")
                        return

            # 🆕 추가 조건: RSI가 과매도가 아니고 수익이 나는 경우
            daily_df = self.api_client.get_daily_data(symbol, days=20)
            if not daily_df.empty:
                daily_df_with_rsi = self.hybrid_strategy.calculate_daily_indicators(daily_df)
                current_rsi = daily_df_with_rsi['rsi'].iloc[-1]
    
                # RSI 50 이상이고 수익이 2% 이상인 경우 D등급이어도 보호
                if current_rsi >= 50 and profit_loss_pct >= 2.0:
                    self.logger.info(f"📈 {stock_name}({symbol}) RSI양호+수익으로 보유유지: "
                                   f"RSI {current_rsi:.1f}, 수익률 {profit_loss_pct:+.2f}%")
                    return

            # 🆕 4순위: 매우 보수적인 절대 점수 기준 (25점 미만으로 완화)
            try:
                future_analysis = self.hybrid_strategy.calculate_future_potential(symbol)
                future_score = future_analysis['total_score']
                
                # 매우 낮은 점수 + 손실인 경우만 매도
                if future_score < 35 and profit_loss_decimal < -0.02:  # 35점 미만 + 2% 이상 손실
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    if can_sell:
                        self.logger.warning(f"📊 {stock_name}({symbol}) 극저점수+손실매도: "
                                          f"{future_score:.1f}점 + {profit_loss_pct:+.2f}%")
                        self.execute_sell(symbol, quantity, "aggressive_limit", "극저점수매도")
                        return
                
                # 매우 큰 손실 + 점수 낮음
                elif profit_loss_decimal < -0.12 and future_score < 40:  # 12% 이상 손실 + 40점 미만
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    if can_sell:
                        self.logger.warning(f"📊 {stock_name}({symbol}) 큰손실+점수매도: "
                                          f"{future_score:.1f}점 + {profit_loss_pct:+.2f}%")
                        self.execute_sell(symbol, quantity, "aggressive_limit", "큰손실매도")
                        return
                elif future_analysis['grade'].startswith('D') and profit_loss_decimal < 0:  # D등급
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    if can_sell:
                        self.logger.warning(f"📊 {stock_name}({symbol}) D등급+손실매도: "
                                          f"{future_score:.1f}점 + {profit_loss_pct:+.2f}%")
                        self.execute_sell(symbol, quantity, "aggressive_limit", "D등급매도")
                        return
                
                elif future_analysis['grade'].startswith('D'):
                    # D등급이어도 수익이 나는 경우는 매도하지 않음
                    if profit_loss_pct > 0:
                        self.logger.info(f"📊 {stock_name}({symbol}) D등급이지만 수익으로 보유유지: "
                                       f"{future_score:.1f}점, 수익률 {profit_loss_pct:+.2f}%")
                        return
    
            except Exception as e:
                self.logger.error(f"미래 점수 계산 오류 ({symbol}): {e}")
                # 오류 발생시 기존 로직으로 진행
            
            # 🔥 5순위: 지능형 손절 판단 (-3% ~ -7% 구간) - 기존 유지
            if -0.07 < profit_loss_decimal <= -0.03:
                recovery_analysis = self.analyze_recovery_potential(symbol, current_price)
                
                if recovery_analysis['should_hold']:
                    self.logger.info(f"💎 {stock_name}({symbol}) 손절 보류: {recovery_analysis['reason']} "
                                   f"(현재: {profit_loss_pct:+.2f}%)")
                    return
                else:
                    self.logger.warning(f"🛑 {stock_name}({symbol}) 지능형 손절: {recovery_analysis['reason']} "
                                      f"({profit_loss_pct:+.2f}%)")
                    self.execute_sell(symbol, quantity, "aggressive_limit", "지능형손절")
                    return
            
            # 🔥 6순위: 급락 감지 - 기존 유지
            rapid_drop = self.check_rapid_drop(symbol, current_price)
            if rapid_drop['should_sell']:
                recovery_analysis = self.analyze_recovery_potential(symbol, current_price)
                
                if recovery_analysis['strong_recovery_signal']:
                    self.logger.info(f"🔄 {stock_name}({symbol}) 급락이지만 회복 신호로 보유: {recovery_analysis['reason']}")
                    return
                else:
                    self.logger.warning(f"💥 {stock_name}({symbol}) 급락 매도: {rapid_drop['reason']}")
                    self.execute_sell(symbol, quantity, "urgent", rapid_drop['reason'])
                    return
            
            # 🔥 7순위: 일반적 기술적 매도 (기준 강화)
            if symbol in self.symbols:
                if daily_analysis['signal'] == 'SELL' and daily_analysis['strength'] >= 3.5:  # 2.5 → 3.5로 강화
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    
                    if can_sell:
                        self.logger.info(f"📉 {stock_name}({symbol}) 강한 기술적 매도 신호")
                        self.execute_sell(symbol, quantity, "aggressive_limit", "기술적매도")
                        return
            
            # 🔥 8순위: 장기 보유 익절 - 기존 유지
            if profit_loss_decimal >= 0.05:
                position_summary = self.position_manager.get_position_summary(symbol)
                first_purchase = position_summary.get('first_purchase_time')
                
                if first_purchase:
                    first_time = datetime.fromisoformat(first_purchase)
                    holding_days = (datetime.now() - first_time).total_seconds() / (24 * 3600)
                    
                    if holding_days >= 5:  # 5일 이상 보유
                        can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                        if can_sell:
                            self.logger.info(f"⏰ {stock_name}({symbol}) 장기보유 익절: {holding_days:.1f}일 보유 ({profit_loss_pct:+.2f}%)")
                            self.execute_sell(symbol, quantity, "aggressive_limit", "장기익절")
                            return
            
            # 보유 유지 로그 (미래 점수 포함)
            try:
                future_score = future_analysis.get('total_score', 50) if 'future_analysis' in locals() else 50
                self.logger.info(f"💎 {stock_name}({symbol}) 보유유지: "
                               f"수익률 {profit_loss_pct:+.2f}%, 예상점수 {future_score:.1f}점")
            except:
                self.logger.info(f"💎 {stock_name}({symbol}) 보유유지: 수익률 {profit_loss_pct:+.2f}%")
                    
        except Exception as e:
            self.logger.error(f"{symbol} 매도 처리 중 오류: {e}")
    
    def execute_portfolio_optimization_sell(self):
        """
        포트폴리오 최적화 매도 (주 1회만 실행) - 더욱 보수적으로
        """
        try:
            current_day = datetime.now().weekday()
            
            # 금요일(4)에만 실행 (주 1회로 축소)
            if current_day != 4:
                return
            
            # 5개 이상 보유시만 실행 (3개 → 5개로 상향)
            if len(self.all_positions) < 5:
                self.logger.info("📊 포트폴리오 최적화: 보유종목 5개 미만으로 스킵")
                return
            
            self.logger.info("🎯 포트폴리오 최적화 매도 분석 시작 (주 1회)")
            
            # 전체 포트폴리오 분석
            try:
                portfolio_analysis = self.evaluate_portfolio_optimization()
                sell_candidates = portfolio_analysis.get('sell_candidates', [])
            except Exception as e:
                self.logger.error(f"포트폴리오 분석 오류: {e}")
                return
            
            if not sell_candidates:
                self.logger.info("📊 포트폴리오 최적화: 매도 후보 없음")
                return
            
            # 매우 엄격한 기준으로만 매도
            worst_candidate = sell_candidates[0]
            symbol = worst_candidate['symbol']
            combined_score = worst_candidate['combined_score']
            current_return = worst_candidate['current_return']
            
            # 매우 낮은 점수 + 큰 손실인 경우만 매도 (기준 강화)
            if combined_score < 30 and current_return < -12:  # 30점 미만 + 12% 이상 손실
                position = self.all_positions.get(symbol)
                if position:
                    quantity = position['quantity']
                    can_sell, sell_reason = self.position_manager.can_sell_symbol(symbol, quantity)
                    
                    if can_sell:
                        stock_name = self.get_stock_name(symbol)
                        self.logger.warning(f"🎯 포트폴리오 최적화 매도: {stock_name}({symbol}) "
                                          f"점수 {combined_score:.1f}점, 수익률 {current_return:+.2f}%")
                        self.execute_sell(symbol, quantity, "limit", "포트폴리오최적화")
                    else:
                        self.logger.info(f"📊 포트폴리오 최적화: {symbol} 매도 불가 - {sell_reason}")
            else:
                self.logger.info(f"📊 포트폴리오 최적화: 하위종목도 보유 기준 충족 "
                               f"(점수: {combined_score:.1f}, 수익률: {current_return:+.2f}%)")
        
        except Exception as e:
            self.logger.error(f"포트폴리오 최적화 매도 오류: {e}")
    
    
    def evaluate_portfolio_optimization(self) -> Dict:
        """
        포트폴리오 최적화를 위한 종목별 미래 상승 가능성 평가
        """
        try:
            self.logger.info("🎯 포트폴리오 최적화 분석 시작")
            
            portfolio_analysis = {}
            sell_candidates = []
            
            # 모든 보유 종목의 미래 상승 가능성 분석
            for symbol, position in self.all_positions.items():
                # 미래 상승 가능성 점수 계산
                future_potential = self.hybrid_strategy.calculate_future_potential(symbol)
                
                # 현재 수익률 정보
                current_return = position['profit_loss_pct']
                holding_period = self.get_holding_period(symbol)
                
                # 종합 평가 점수 (미래 가능성 70% + 현재 수익률 30%)
                # 현재 수익률이 마이너스면 페널티, 플러스면 보너스
                return_adjustment = max(min(current_return * 0.3, 10), -15)  # -15~+10 범위
                combined_score = future_potential['total_score'] + return_adjustment
                
                portfolio_analysis[symbol] = {
                    'stock_name': future_potential['stock_name'],
                    'current_return': current_return,
                    'future_potential': future_potential['total_score'],
                    'combined_score': combined_score,
                    'grade': future_potential['grade'],
                    'holding_period': holding_period,
                    'recommendation': future_potential['recommendation'],
                    'position_value': position['total_value'],
                    'top_reasons': future_potential.get('top_reasons', [])
                }
                
                # 매도 후보 선정 (점수 50점 미만 또는 현재 손실 5% 이상)
                if combined_score < 50 or current_return < -5:
                    sell_candidates.append({
                        'symbol': symbol,
                        'stock_name': future_potential['stock_name'],
                        'combined_score': combined_score,
                        'current_return': current_return,
                        'reason': '낮은 미래 가능성' if combined_score < 50 else '큰 손실'
                    })
            
            # 매도 우선순위 결정 (점수가 낮은 순)
            sell_candidates.sort(key=lambda x: x['combined_score'])
            
            # 결과 정리
            sorted_portfolio = sorted(portfolio_analysis.items(), 
                                    key=lambda x: x[1]['combined_score'], reverse=True)
            
            self.logger.info(f"📊 포트폴리오 최적화 분석 완료: {len(portfolio_analysis)}개 종목")
            for symbol, analysis in sorted_portfolio:
                self.logger.info(f"  {analysis['stock_name']}: {analysis['combined_score']:.1f}점 "
                               f"(미래:{analysis['future_potential']:.1f} + 수익:{analysis['current_return']:+.1f}%)")
            
            return {
                'portfolio_analysis': portfolio_analysis,
                'sorted_portfolio': sorted_portfolio,
                'sell_candidates': sell_candidates,
                'total_positions': len(portfolio_analysis),
                'analysis_time': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"포트폴리오 최적화 분석 오류: {e}")
            return {
                'portfolio_analysis': {},
                'sell_candidates': [],
                'error': str(e)
            }
    
    
    def get_holding_period(self, symbol: str) -> float:
        """보유 기간 계산 (일 단위)"""
        try:
            position_summary = self.position_manager.get_position_summary(symbol)
            first_purchase = position_summary.get('first_purchase_time')
            
            if first_purchase:
                first_time = datetime.fromisoformat(first_purchase)
                holding_days = (datetime.now() - first_time).total_seconds() / (24 * 3600)
                return holding_days
            
            return 0
            
        except Exception:
            return 0

    def analyze_recovery_potential(self, symbol: str, current_price: float) -> Dict:
        """상승 회복 가능성 분석 - 새로운 메서드"""
        try:
            stock_name = self.get_stock_name(symbol)
            self.logger.info(f"🔍 {stock_name}({symbol}) 회복 가능성 분석 시작")
            
            recovery_score = 0
            reasons = []
            
            # 1. 일봉 기술적 분석 (가장 중요)
            daily_analysis = self.hybrid_strategy.analyze_daily_strategy(symbol)
            
            if daily_analysis['signal'] == 'BUY':
                recovery_score += daily_analysis['strength']
                reasons.append(f"일봉매수신호({daily_analysis['strength']:.1f}점)")
            
            # 2. 가격 위치 분석
            daily_df = self.api_client.get_daily_data(symbol, days=60)
            if not daily_df.empty and len(daily_df) >= 20:
                # 20일 평균선 대비 위치
                ma20 = daily_df['stck_prpr'].rolling(20).mean().iloc[-1]
                ma20_ratio = current_price / ma20
                
                if ma20_ratio <= 0.95:  # 평균선 5% 아래
                    recovery_score += 2.0
                    reasons.append(f"평균선하회({ma20_ratio:.3f})")
                
                # 60일 고점 대비 위치
                high_60 = daily_df['stck_prpr'].rolling(60).max().iloc[-1]
                price_position = current_price / high_60
                
                if price_position <= 0.7:  # 고점 대비 30% 이상 하락
                    recovery_score += 1.5
                    reasons.append(f"고점대비저점({price_position:.1%})")
            
            # 3. RSI 과매도 확인
            if not daily_df.empty:
                daily_df_with_rsi = self.hybrid_strategy.calculate_daily_indicators(daily_df)
                current_rsi = daily_df_with_rsi['rsi'].iloc[-1]
                
                if current_rsi < 30:  # 과매도
                    recovery_score += 2.0
                    reasons.append(f"RSI과매도({current_rsi:.1f})")
                elif current_rsi < 40:
                    recovery_score += 1.0
                    reasons.append(f"RSI매수권({current_rsi:.1f})")
            
            # 4. 분봉 반등 신호 확인
            minute_df = self.api_client.get_minute_data(symbol, minutes=60)
            if not minute_df.empty and len(minute_df) >= 10:
                # 최근 10분간 상승 추세
                recent_prices = minute_df['stck_prpr'].tail(10).tolist()
                rising_count = sum(1 for i in range(1, len(recent_prices)) 
                                 if recent_prices[i] > recent_prices[i-1])
                
                if rising_count >= 6:  # 10분 중 6분 이상 상승
                    recovery_score += 1.5
                    reasons.append(f"분봉반등({rising_count}/10)")
                
                # 거래량 증가 확인
                if len(minute_df) >= 20:
                    recent_vol = minute_df['cntg_vol'].tail(10).mean()
                    past_vol = minute_df['cntg_vol'].head(10).mean()
                    
                    if recent_vol > past_vol * 1.5:  # 최근 거래량 50% 증가
                        recovery_score += 1.0
                        reasons.append("거래량증가")
            
            # 5. 시장 상황 고려 (KOSPI/KOSDAQ 상승시 가점)
            try:
                kospi_data = self.api_client.get_daily_data('000001', days=2)  # KOSPI
                if not kospi_data.empty and len(kospi_data) >= 2:
                    kospi_change = (kospi_data['stck_prpr'].iloc[-1] / kospi_data['stck_prpr'].iloc[-2] - 1) * 100
                    if kospi_change > 0.5:  # KOSPI 0.5% 이상 상승
                        recovery_score += 0.5
                        reasons.append(f"시장상승({kospi_change:.1f}%)")
            except:
                pass
            
            # 결론 도출
            should_hold = recovery_score >= 4.0  # 4점 이상이면 보유
            strong_recovery = recovery_score >= 6.0  # 6점 이상이면 강한 회복 신호
            
            reason_text = ', '.join(reasons) if reasons else '회복신호없음'
            
            self.logger.info(f"📊 {stock_name}({symbol}) 회복분석 완료: {recovery_score:.1f}점 - {reason_text}")
            
            return {
                'should_hold': should_hold,
                'strong_recovery_signal': strong_recovery,
                'recovery_score': recovery_score,
                'reason': reason_text,
                'analysis_details': reasons
            }
            
        except Exception as e:
            self.logger.error(f"회복 가능성 분석 오류: {e}")
            return {
                'should_hold': False,
                'strong_recovery_signal': False,
                'recovery_score': 0,
                'reason': f'분석오류: {e}',
                'analysis_details': []
            }
    
    
    def check_rapid_drop(self, symbol: str, current_price: float) -> Dict:
        """개선된 급락 감지 시스템 - 회복 가능성도 고려"""
        try:
            minute_df = self.api_client.get_minute_data(symbol, minutes=120)
            
            if minute_df.empty or len(minute_df) < 10:
                return {'should_sell': False, 'reason': '데이터부족'}
            
            # 급락 기준을 더 엄격하게 (진짜 위험한 상황만)
            
            # 1시간 내 7% 이상 급락 (기존 4%에서 상향)
            if len(minute_df) >= 60:
                hour_ago_price = minute_df['stck_prpr'].iloc[-60]
                hour_change = (current_price - hour_ago_price) / hour_ago_price
                
                if hour_change < -0.07:  # -7% 이상 급락
                    return {'should_sell': True, 'reason': f"심각한급락({hour_change:.1%})"}
            
            # 30분 내 최고가 대비 10% 이상 급락 (기존 6%에서 상향)
            recent_30min = minute_df.tail(30)
            if not recent_30min.empty:
                recent_high = recent_30min['stck_prpr'].max()
                drop_from_high = (current_price - recent_high) / recent_high
                
                if drop_from_high < -0.10:  # -10% 이상 급락
                    return {'should_sell': True, 'reason': f"단기폭락({drop_from_high:.1%})"}
            
            # 연속 하락도 더 엄격하게
            if len(minute_df) >= 15:
                recent_prices = minute_df['stck_prpr'].tail(15).tolist()
                declining_count = 0
                
                for i in range(1, len(recent_prices)):
                    if recent_prices[i] < recent_prices[i-1]:
                        declining_count += 1
                
                # 15분봉 중 12개 이상이 하락하고 -4% 이상 하락
                if declining_count >= 12:
                    total_decline = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
                    if total_decline < -0.04:
                        return {'should_sell': True, 'reason': f"장기연속하락({total_decline:.1%})"}
            
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
        """개선된 매도 실행 - 시장가 우선 사용"""
        stock_name = self.get_stock_name(symbol)
        
        # 🔥 긴급 매도는 시장가로 즉시 처리
        if reason in ['손절매', '급락감지', '연속하락'] or order_strategy == "urgent":
            result = self.order_manager.place_order_with_tracking(
                symbol, 'SELL', quantity, 'market', self.order_tracker  # 시장가로 변경
            )
        else:
            # 일반 매도는 기존 로직 유지
            result = self.order_manager.place_order_with_tracking(
                symbol, 'SELL', quantity, order_strategy, self.order_tracker
            )
        
        if result['success']:
            executed_price = result.get('limit_price', 0)
            if executed_price == 0:  # 시장가인 경우 현재가로 추정
                current_price_data = self.api_client.get_current_price(symbol)
                if current_price_data and current_price_data.get('output'):
                    executed_price = float(current_price_data['output'].get('stck_prpr', 0))
            
            order_no = result.get('order_no', 'Unknown')
            
            # 시장가는 즉시 포지션에서 제거
            if order_strategy == 'market':
                self.position_manager.record_sale(symbol, quantity, executed_price, reason)
                
                # 메모리에서도 즉시 제거
                if symbol in self.positions:
                    del self.positions[symbol]
                if symbol in self.all_positions:
                    del self.all_positions[symbol]
            
            self.logger.info(f"✅ {stock_name}({symbol}) 매도 완료: {quantity}주 @ {executed_price:,}원 - {reason}")
            
            # 강제 알림 전송
            if self.notifier.webhook_url:
                self.notifier.notify_trade_success('SELL', symbol, quantity, executed_price, order_no, stock_name)
            
            return True
        else:
            error_msg = result.get('error', 'Unknown error')
            self.logger.error(f"❌ {stock_name}({symbol}) 매도 실패: {error_msg}")
            return False

    
    def is_market_open(self, current_time=None):
        """한국 증시 개장 시간 확인 (KRX + NXT 통합)"""
        if current_time is None:
            current_time = datetime.now()
        
        weekday = current_time.weekday()
        if weekday >= 5:  # 토요일(5), 일요일(6)
            return False
        
        hour = current_time.hour
        minute = current_time.minute
        current_time_minutes = hour * 60 + minute
        
        # 새로운 거래시간: 오전 8시 ~ 오후 8시 (NXT 포함)
        market_open_minutes = 8 * 60      # 08:00
        market_close_minutes = 20 * 60    # 20:00 (오후 8시)
        
        return market_open_minutes <= current_time_minutes < market_close_minutes
    
    def get_market_status_info(self, current_time=None):
        """장 상태 정보 반환 (NXT 연장거래 포함)"""
        if current_time is None:
            current_time = datetime.now()
        
        is_open = self.is_market_open(current_time)
        
        if is_open:
            # 새로운 마감시간 (오후 8시)
            today_close = current_time.replace(hour=20, minute=0, second=0, microsecond=0)
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
                next_open = next_open.replace(hour=8, minute=0, second=0, microsecond=0)  # 새로운 시작시간
                message = f'주말 휴장 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            elif current_time.hour < 8:  # 새로운 시작시간
                next_open = current_time.replace(hour=8, minute=0, second=0, microsecond=0)
                time_to_open = next_open - current_time
                hours, remainder = divmod(time_to_open.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                message = f'장 시작 전 (개장까지 {int(hours)}시간 {int(minutes)}분)'
            else:
                next_day = current_time + timedelta(days=1)
                while next_day.weekday() >= 5:
                    next_day += timedelta(days=1)
                
                next_open = next_day.replace(hour=8, minute=0, second=0, microsecond=0)  # 새로운 시작시간
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

                        # 🆕 포트폴리오 최적화 매도 (주 2회)
                        self.execute_portfolio_optimization_sell()
                        
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
