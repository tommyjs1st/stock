import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional
import yaml
import os
from pathlib import Path
import sys



class PositionManager:
    """종목별 포지션 관리 클래스"""
    def __init__(self, trader):
        self.trader = trader
        self.position_history_file = "position_history.json"
        self.position_history = {}
        self.load_position_history()
    
    def load_position_history(self):
        """포지션 이력 로드"""
        try:
            if os.path.exists(self.position_history_file):
                with open(self.position_history_file, 'r', encoding='utf-8') as f:
                    self.position_history = json.load(f)
                self.trader.logger.info(f"📋 포지션 이력 로드: {len(self.position_history)}개 종목")
        except Exception as e:
            self.trader.logger.error(f"포지션 이력 로드 실패: {e}")
            self.position_history = {}
    
    def save_position_history(self):
        """포지션 이력 저장"""
        try:
            with open(self.position_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.position_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.trader.logger.error(f"포지션 이력 저장 실패: {e}")
    
    def record_purchase(self, symbol: str, quantity: int, price: float, strategy: str):
        """매수 기록"""
        now = datetime.now()
        
        if symbol not in self.position_history:
            self.position_history[symbol] = {
                'total_quantity': 0,
                'purchase_count': 0,
                'purchases': [],
                'last_purchase_time': None,
                'first_purchase_time': None
            }
        
        purchase_record = {
            'timestamp': now.isoformat(),
            'quantity': quantity,
            'price': price,
            'strategy': strategy,
            'order_type': 'BUY'
        }
        
        self.position_history[symbol]['purchases'].append(purchase_record)
        self.position_history[symbol]['total_quantity'] += quantity
        self.position_history[symbol]['purchase_count'] += 1
        self.position_history[symbol]['last_purchase_time'] = now.isoformat()
        
        if not self.position_history[symbol]['first_purchase_time']:
            self.position_history[symbol]['first_purchase_time'] = now.isoformat()
        
        self.save_position_history()
        
        self.trader.logger.info(f"📝 매수 기록: {symbol} {quantity}주 @ {price:,}원 "
                               f"(누적: {self.position_history[symbol]['total_quantity']}주)")
    
    def record_sale(self, symbol: str, quantity: int, price: float, reason: str):
        """매도 기록"""
        now = datetime.now()
        
        if symbol in self.position_history:
            sale_record = {
                'timestamp': now.isoformat(),
                'quantity': quantity,
                'price': price,
                'reason': reason,
                'order_type': 'SELL'
            }
            
            self.position_history[symbol]['purchases'].append(sale_record)
            self.position_history[symbol]['total_quantity'] -= quantity
            
            if self.position_history[symbol]['total_quantity'] <= 0:
                self.position_history[symbol]['total_quantity'] = 0
                self.position_history[symbol]['position_closed_time'] = now.isoformat()
            
            self.save_position_history()
            
            self.trader.logger.info(f"📝 매도 기록: {symbol} {quantity}주 @ {price:,}원 "
                                   f"사유: {reason} (잔여: {self.position_history[symbol]['total_quantity']}주)")

class HybridTradingStrategy:
    """일봉 전략 + 분봉 실행 하이브리드 시스템"""
    def __init__(self, trader):
        self.trader = trader
        self.pending_signals = {}
        self.daily_analysis_cache = {}
        self.last_daily_analysis = {}
        
    def analyze_daily_strategy(self, symbol: str) -> Dict:
        """일봉 기반 전략 분석 (하루 1-2회만 실행)"""
        
        # 캐시 확인 (4시간 이내면 재사용)
        now = datetime.now()
        if symbol in self.last_daily_analysis:
            last_time = self.last_daily_analysis[symbol]
            if now - last_time < timedelta(hours=4):
                return self.daily_analysis_cache.get(symbol, {'signal': 'HOLD', 'strength': 0})
        
        self.trader.logger.info(f"📅 {symbol} 일봉 전략 분석 실행")
        
        # 일봉 데이터 조회 (6개월)
        df = self.trader.get_daily_data(symbol, days=180)
        
        if df.empty or len(df) < 60:
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
        
        try:
            current_price = float(df['stck_prpr'].iloc[-1])
            
            # 일봉 기술 지표 계산
            df = self.calculate_daily_indicators(df)
            latest = df.iloc[-1]
            
            # 장기 추세 분석
            trend_analysis = self.analyze_long_term_trend(df)
            
            # 신호 생성
            signal_result = self.generate_daily_signal(df, latest, trend_analysis)
            
            # 캐시 업데이트
            self.daily_analysis_cache[symbol] = signal_result
            self.last_daily_analysis[symbol] = now
            
            self.trader.logger.info(f"📊 {symbol} 일봉 분석 완료: {signal_result['signal']} (강도: {signal_result['strength']:.2f})")
            
            return signal_result
            
        except Exception as e:
            self.trader.logger.error(f"일봉 분석 실패 ({symbol}): {e}")
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
    
    def calculate_daily_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """일봉 기술 지표 계산"""
        
        # 이동평균선
        df['ma5'] = df['stck_prpr'].rolling(5).mean()
        df['ma20'] = df['stck_prpr'].rolling(20).mean()
        df['ma60'] = df['stck_prpr'].rolling(60).mean()
        df['ma120'] = df['stck_prpr'].rolling(120).mean()
        
        # MACD
        df = self.trader.calculate_macd(df)
        
        # RSI
        delta = df['stck_prpr'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 볼린저 밴드
        df['bb_middle'] = df['stck_prpr'].rolling(20).mean()
        bb_std = df['stck_prpr'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        
        # 스토캐스틱
        low_14 = df['stck_lwpr'].rolling(14).min()
        high_14 = df['stck_hgpr'].rolling(14).max()
        df['stoch_k'] = 100 * ((df['stck_prpr'] - low_14) / (high_14 - low_14))
        df['stoch_d'] = df['stoch_k'].rolling(3).mean()
        
        return df
    
    def analyze_long_term_trend(self, df: pd.DataFrame) -> Dict:
        """장기 추세 분석"""
        
        current_price = df['stck_prpr'].iloc[-1]
        
        # 다양한 기간 수익률
        returns = {}
        for days in [5, 10, 20, 40, 60, 120]:
            if len(df) > days:
                past_price = df['stck_prpr'].iloc[-(days+1)]
                returns[f'{days}d'] = (current_price - past_price) / past_price
        
        # 추세 강도 계산
        trend_score = 0
        
        # 단기 추세 (5-20일)
        if returns.get('5d', 0) > 0.02:
            trend_score += 1
        if returns.get('10d', 0) > 0.05:
            trend_score += 1
        if returns.get('20d', 0) > 0.1:
            trend_score += 2
        
        # 중장기 추세 (40-120일)
        if returns.get('60d', 0) > 0.2:
            trend_score += 2
        if returns.get('120d', 0) > 0.3:
            trend_score += 1
        
        # 이동평균 정배열 체크
        latest = df.iloc[-1]
        ma_alignment = (latest['ma5'] > latest['ma20'] > 
                       latest['ma60'] > latest['ma120'])
        
        if ma_alignment:
            trend_score += 2
        
        return {
            'trend_score': trend_score,
            'returns': returns,
            'ma_alignment': ma_alignment,
            'current_price': current_price
        }
    
    def generate_daily_signal(self, df: pd.DataFrame, latest: pd.Series, trend_analysis: Dict) -> Dict:
        """일봉 기반 신호 생성"""
        
        signal = 'HOLD'
        strength = 0
        reasons = []
        
        current_price = trend_analysis['current_price']
        trend_score = trend_analysis['trend_score']
        
        # 매수 조건 평가
        buy_score = 0
        
        # 1. 장기 추세 (가중치 높음)
        if trend_score >= 6:
            buy_score += 3.0
            reasons.append("강한상승추세")
        elif trend_score >= 4:
            buy_score += 2.0
            reasons.append("상승추세")
        elif trend_score >= 2:
            buy_score += 1.0
            reasons.append("약한상승추세")
        
        # 2. MACD
        macd_analysis = self.trader.detect_macd_golden_cross(df)
        if macd_analysis['golden_cross'] and macd_analysis['signal_age'] <= 10:
            buy_score += 2.5
            reasons.append(f"MACD골든크로스({macd_analysis['signal_age']}일전)")
        elif macd_analysis.get('macd_above_zero', False):
            buy_score += 1.0
            reasons.append("MACD상승권")
        
        # 3. RSI
        rsi = latest['rsi']
        if 30 <= rsi <= 50:
            buy_score += 1.5
            reasons.append("RSI매수권")
        elif 50 < rsi <= 65:
            buy_score += 0.5
            reasons.append("RSI중립")
        
        # 4. 스토캐스틱
        if latest['stoch_k'] < 30 and latest['stoch_d'] < 30:
            buy_score += 1.0
            reasons.append("스토캐스틱과매도")
        
        # 5. 볼린저 밴드
        bb_position = ((current_price - latest['bb_lower']) / 
                      (latest['bb_upper'] - latest['bb_lower']))
        if bb_position < 0.3:
            buy_score += 1.0
            reasons.append("볼린저하단")
        
        # 6. 이동평균 돌파
        if current_price > latest['ma20'] > latest['ma60']:
            buy_score += 1.0
            reasons.append("이평선돌파")
        
        # 매도 조건 평가
        sell_score = 0
        
        if rsi > 75:
            sell_score += 2.0
            reasons.append("RSI과매수")
        
        if bb_position > 0.8:
            sell_score += 1.5
            reasons.append("볼린저상단")
        
        if current_price < latest['ma20']:
            sell_score += 2.0
            reasons.append("20일선이탈")
        
        if trend_analysis['returns'].get('10d', 0) < -0.1:
            sell_score += 2.0
            reasons.append("급락추세")
        
        # 최종 신호 결정
        if buy_score >= 5.0:
            signal = 'BUY'
            strength = min(buy_score, 5.0)
        elif sell_score >= 3.0:
            signal = 'SELL'
            strength = min(sell_score, 5.0)
        
        return {
            'signal': signal,
            'strength': strength,
            'current_price': current_price,
            'reasons': reasons,
            'trend_score': trend_score,
            'rsi': float(rsi),
            'bb_position': bb_position,
            'buy_score': buy_score,
            'sell_score': sell_score,
            'macd_analysis': macd_analysis
        }
    
    def find_optimal_entry_timing(self, symbol: str, target_signal: str) -> Dict:
        """분봉 기반 최적 진입 타이밍 찾기"""
        
        self.trader.logger.info(f"🎯 {symbol} {target_signal} 최적 타이밍 분석")
        
        # 최근 4시간 분봉 데이터
        minute_df = self.trader.get_minute_data(symbol, minutes=240)
        
        if minute_df.empty or len(minute_df) < 20:
            return {'execute': False, 'reason': '분봉 데이터 부족'}
        
        try:
            current_price = float(minute_df['stck_prpr'].iloc[-1])
            
            # 분봉 기술지표
            minute_df['ma5'] = minute_df['stck_prpr'].rolling(5).mean()
            minute_df['ma20'] = minute_df['stck_prpr'].rolling(20).mean()
            
            # 분봉 RSI
            delta = minute_df['stck_prpr'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            minute_df['minute_rsi'] = 100 - (100 / (1 + rs))
            
            latest_minute = minute_df.iloc[-1]
            
            if target_signal == 'BUY':
                return self.evaluate_buy_timing(minute_df, latest_minute, current_price, symbol)
            else:
                return self.evaluate_sell_timing(minute_df, latest_minute, current_price, symbol)
                
        except Exception as e:
            self.trader.logger.error(f"분봉 타이밍 분석 실패 ({symbol}): {e}")
            return {'execute': False, 'reason': f'분석 오류: {str(e)}'}

    def evaluate_buy_timing(self, df: pd.DataFrame, latest: pd.Series, current_price: float, symbol: str = None) -> Dict:
        """매수 타이밍 평가"""
        
        timing_score = 0
        reasons = []
        
        # 1. 분봉 추세
        if latest['ma5'] > latest['ma20']:
            timing_score += 2
            reasons.append("분봉상승추세")
        
        # 2. 분봉 RSI
        minute_rsi = latest['minute_rsi']
        if minute_rsi < 40:
            timing_score += 2
            reasons.append("분봉RSI과매도")
        elif 40 <= minute_rsi <= 60:
            timing_score += 1
            reasons.append("분봉RSI적정")
        
        # 3. 최근 가격 움직임
        recent_change = (current_price - df['stck_prpr'].iloc[-10]) / df['stck_prpr'].iloc[-10]
        if -0.02 <= recent_change <= 0.01:
            timing_score += 1
            reasons.append("적정변동폭")
        
        # 4. 거래량 확인
        avg_volume = df['cntg_vol'].rolling(20).mean().iloc[-1]
        current_volume = df['cntg_vol'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        if volume_ratio > 1.5:
            timing_score += 1
            reasons.append("거래량증가")
        
        # 5. 호가 스프레드 확인
        try:
            bid_ask = self.trader.get_current_bid_ask(symbol)
            if bid_ask and bid_ask.get('spread', 1000) <= 500:
                timing_score += 1
                reasons.append("스프레드양호")
        except Exception as bid_ask_error:
            self.trader.logger.warning(f"호가 조회 실패 ({symbol}): {bid_ask_error}")
            # 호가 조회 실패해도 계속 진행

        execute = timing_score >= 4
        
        return {
            'execute': execute,
            'timing_score': timing_score,
            'reasons': reasons,
            'current_price': current_price,
            'minute_rsi': minute_rsi,
            'volume_ratio': volume_ratio,
            'recent_change': recent_change
        }
    
    def evaluate_sell_timing(self, df: pd.DataFrame, latest: pd.Series, current_price: float, symbol: str = None) -> Dict:
        """매도 타이밍 평가"""
        
        timing_score = 0
        reasons = []
        
        # 1. 분봉 추세 약화
        if latest['ma5'] < latest['ma20']:
            timing_score += 2
            reasons.append("분봉하락추세")
        
        # 2. 분봉 RSI
        minute_rsi = latest['minute_rsi']
        if minute_rsi > 65:
            timing_score += 2
            reasons.append("분봉RSI과매수")
        
        # 3. 급락 신호
        recent_change = (current_price - df['stck_prpr'].iloc[-5]) / df['stck_prpr'].iloc[-5]
        if recent_change < -0.015:
            timing_score += 3
            reasons.append("급락감지")
        
        # 4. 거래량 급증
        avg_volume = df['cntg_vol'].rolling(10).mean().iloc[-1]
        current_volume = df['cntg_vol'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        if volume_ratio > 3.0:
            timing_score += 2
            reasons.append("거래량급증")
        
        execute = timing_score >= 3
        
        return {
            'execute': execute,
            'timing_score': timing_score,
            'reasons': reasons,
            'current_price': current_price,
            'minute_rsi': minute_rsi,
            'volume_ratio': volume_ratio,
            'recent_change': recent_change
        }
    
    def execute_hybrid_trade(self, symbol: str) -> bool:
        """하이브리드 매매 실행"""
        
        # 1. 일봉 전략 분석
        daily_analysis = self.analyze_daily_strategy(symbol)
        
        if daily_analysis['signal'] == 'HOLD' or daily_analysis['strength'] < 3.0:
            return False
        
        # 2. 분봉 타이밍 분석
        timing_analysis = self.find_optimal_entry_timing(symbol, daily_analysis['signal'])
        
        if not timing_analysis['execute']:
            self.trader.logger.info(f"⏰ {symbol} 타이밍 부적절: {timing_analysis.get('reason', '기준 미달')}")
            return False
        
        # 3. 실제 매매 실행
        current_price = timing_analysis['current_price']
        
        if daily_analysis['signal'] == 'BUY':
            return self.execute_smart_buy(symbol, daily_analysis, timing_analysis, current_price)
        else:
            return self.execute_smart_sell(symbol, daily_analysis, timing_analysis, current_price)
    
    def execute_smart_buy(self, symbol: str, daily_analysis: Dict, timing_analysis: Dict, current_price: float) -> bool:
        """스마트 매수 실행"""
        
        # 매수 가능 여부 확인
        can_buy, reason = self.trader.can_purchase_symbol(symbol)
        if not can_buy:
            self.trader.logger.info(f"🚫 {symbol} 매수 불가: {reason}")
            return False
        
        # 포지션 크기 계산
        quantity = self.trader.calculate_position_size(symbol, current_price, daily_analysis['strength'])
        
        if quantity <= 0:
            self.trader.logger.warning(f"⚠️ {symbol} 매수 수량 0")
            return False
        
        # 분봉 기반 주문 전략 결정
        order_strategy = self.determine_order_strategy(timing_analysis)
        
        self.trader.logger.info(f"💰 {symbol} 하이브리드 매수 실행:")
        self.trader.logger.info(f"  일봉 신호: {daily_analysis['signal']} (강도: {daily_analysis['strength']:.2f})")
        self.trader.logger.info(f"  일봉 사유: {', '.join(daily_analysis.get('reasons', []))}")
        self.trader.logger.info(f"  분봉 타이밍: {timing_analysis['timing_score']}/5")
        self.trader.logger.info(f"  분봉 사유: {', '.join(timing_analysis.get('reasons', []))}")
        self.trader.logger.info(f"  수량: {quantity}주, 전략: {order_strategy}")
        
        # 주문 실행
        result = self.trader.place_order_with_strategy(symbol, 'BUY', quantity, order_strategy)
        
        if result['success']:
            executed_price = result.get('limit_price', current_price)
            self.trader.position_manager.record_purchase(
                symbol, quantity, executed_price, "hybrid_strategy"
            )
            
            # 하이브리드 매수 알림
            self.notify_hybrid_trade(symbol, 'BUY', daily_analysis, timing_analysis, quantity, executed_price)
            
            return True
        
        return False
    
    def execute_smart_sell(self, symbol: str, daily_analysis: Dict, timing_analysis: Dict, current_price: float) -> bool:
        """스마트 매도 실행"""
        
        current_position = self.trader.positions.get(symbol, {})
        if not current_position or current_position.get('quantity', 0) <= 0:
            return False
        
        can_sell, reason = self.trader.can_sell_symbol(symbol)
        if not can_sell:
            self.trader.logger.info(f"🚫 {symbol} 매도 불가: {reason}")
            return False
        
        quantity = current_position['quantity']
        order_strategy = "aggressive_limit"
        
        self.trader.logger.info(f"💸 {symbol} 하이브리드 매도 실행:")
        self.trader.logger.info(f"  일봉 신호: {daily_analysis['signal']} (강도: {daily_analysis['strength']:.2f})")
        self.trader.logger.info(f"  분봉 타이밍: {timing_analysis['timing_score']}")
        
        result = self.trader.place_order_with_strategy(symbol, 'SELL', quantity, order_strategy)
        
        if result['success']:
            executed_price = result.get('limit_price', current_price)
            self.trader.position_manager.record_sale(
                symbol, quantity, executed_price, "hybrid_strategy"
            )
            
            self.notify_hybrid_trade(symbol, 'SELL', daily_analysis, timing_analysis, quantity, executed_price)
            
            return True
        
        return False
    
    def determine_order_strategy(self, timing_analysis: Dict) -> str:
        """분봉 분석 기반 주문 전략 결정"""
        
        timing_score = timing_analysis['timing_score']
        minute_rsi = timing_analysis.get('minute_rsi', 50)
        volume_ratio = timing_analysis.get('volume_ratio', 1)
        
        if timing_score >= 4 and minute_rsi < 35:
            return "urgent"
        elif timing_score >= 3 and volume_ratio > 2.0:
            return "aggressive_limit"
        else:
            return "patient_limit"
    
    def notify_hybrid_trade(self, symbol: str, action: str, daily_analysis: Dict, 
                           timing_analysis: Dict, quantity: int, price: float):
        """하이브리드 매매 알림"""
        
        if not self.trader.notify_on_trade:
            return
        
        stock_name = self.trader.get_stock_name(symbol)
        action_emoji = "🛒" if action == "BUY" else "💸"
        
        title = f"{action_emoji} 하이브리드 {action}!"
        
        daily_reasons = ', '.join(daily_analysis.get('reasons', []))
        timing_reasons = ', '.join(timing_analysis.get('reasons', []))
        
        message = f"""
종목: {symbol} ({stock_name})
수량: {quantity}주 @ {price:,}원
📅 일봉 분석:

신호 강도: {daily_analysis['strength']:.2f}
사유: {daily_reasons}
RSI: {daily_analysis.get('rsi', 0):.1f}

⏰ 분봉 타이밍:

타이밍 점수: {timing_analysis['timing_score']}/5
사유: {timing_reasons}
분봉 RSI: {timing_analysis.get('minute_rsi', 0):.1f}

시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        color = 0x00ff00 if action == "BUY" else 0xff6600
        self.trader.send_discord_notification(title, message, color)

class KISAutoTrader:
    """KIS API 기반 하이브리드 자동매매 시스템"""

    def __init__(self, config_path: str = "config.yaml"):
        
        # 필수 속성들을 먼저 초기화
        self.token_file = "token.json"
        self.access_token = None
        self.positions = {}
        self.all_positions = {}
        self.daily_pnl = 0
        self.trade_count = 0
        self.last_token_time = None
        self.strategy_map = {}
        
        # API 관련 설정
        self.skip_stock_name_api = False
        self.api_error_count = 0
        
        # MACD 설정
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        self.macd_cross_lookback = 3
        self.macd_trend_confirmation = 5
        
        # 종목명 캐시 초기화
        self.stock_names = {}
        self.stock_names_file = "stock_names.json"
        
        # 로깅 설정
        self.setup_logging()
        
        # 저장된 종목명 로드
        self.load_stock_names()
        
        # 설정 파일 로드
        self.load_config(config_path)
        
        # 토큰 로드
        self.load_saved_token()
        
        # 종목명 업데이트
        self.update_all_stock_names()
        
        # 포지션 관리자 초기화
        self.position_manager = PositionManager(self)
        
        # 포지션 설정 로드
        self.load_position_settings()
        
        # API 세션 설정
        self.session = self.create_robust_session()
        self.api_timeout = 30
        self.api_retry_count = 3
        self.api_retry_delay = 2
        self.last_api_call = None
        self.min_api_interval = 0.5
        
        self.logger.info("✅ 하이브리드 자동매매 시스템 초기화 완료")
    
    def load_config(self, config_path: str):
        """설정 파일 로드"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
    
            # API 설정
            self.app_key = config['kis']['app_key']
            self.app_secret = config['kis']['app_secret']
            self.base_url = config['kis']['base_url']
            self.account_no = config['kis']['account_no']
    
            # 거래 설정
            trading_config = config['trading']
            self.max_symbols = trading_config.get('max_symbols', 3)
            self.max_position_ratio = trading_config['max_position_ratio']
            self.daily_loss_limit = trading_config['daily_loss_limit']
            self.stop_loss_pct = trading_config['stop_loss_pct']
            self.take_profit_pct = trading_config['take_profit_pct']
    
            # 주문 전략 설정
            self.order_strategy = trading_config.get('order_strategy', 'patient_limit')
            self.price_offset_pct = trading_config.get('price_offset_pct', 0.003)
            self.order_timeout_minutes = trading_config.get('order_timeout_minutes', 5)
            self.partial_fill_allowed = trading_config.get('partial_fill_allowed', True)
    
            # 모멘텀 설정
            momentum_config = config.get('momentum', {})
            self.momentum_period = momentum_config.get('period', 20)
            self.momentum_threshold = momentum_config.get('threshold', 0.02)
            self.volume_threshold = momentum_config.get('volume_threshold', 1.5)
            self.ma_short = momentum_config.get('ma_short', 5)
            self.ma_long = momentum_config.get('ma_long', 20)
    
            # 알림 설정
            notification = config.get('notification', {})
            self.discord_webhook = notification.get('discord_webhook', '')
            self.notify_on_trade = notification.get('notify_on_trade', True)
            self.notify_on_error = notification.get('notify_on_error', True)
            self.notify_on_daily_summary = notification.get('notify_on_daily_summary', True)
    
            # 백테스트 설정
            backtest = config.get('backtest', {})
            self.backtest_results_file = backtest.get('results_file', 'backtest_results.json')
            self.min_return_threshold = backtest.get('min_return_threshold', 5.0)
            self.performance_tracking = backtest.get('performance_tracking', True)
            
            # 종목 설정
            self.symbols = self.load_symbols_from_backtest(config)
    
        except FileNotFoundError:
            self.create_sample_config(config_path)
            raise Exception(f"설정 파일이 없습니다. {config_path} 파일을 생성했으니 설정을 입력해주세요.")
        except Exception as e:
            self.logger.error(f"설정 파일 로드 중 오류: {e}")
            raise
    
    def setup_logging(self):
        """로깅 설정"""
        os.makedirs('logs', exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/autotrader.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def load_stock_names(self):
        """저장된 종목명 매핑 로드"""
        try:
            if os.path.exists(self.stock_names_file):
                with open(self.stock_names_file, 'r', encoding='utf-8') as f:
                    self.stock_names = json.load(f)
                self.logger.info(f"📚 종목명 {len(self.stock_names)}개 로드 완료")
            else:
                self.stock_names = {}
        except Exception as e:
            self.logger.warning(f"종목명 파일 로드 실패: {e}")
            self.stock_names = {}
    
    def save_stock_names(self):
        """종목명 매핑을 파일로 저장"""
        try:
            with open(self.stock_names_file, 'w', encoding='utf-8') as f:
                json.dump(self.stock_names, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"종목명 저장 실패: {e}")
    
    def get_stock_name(self, code: str) -> str:
        """안전한 종목명 조회"""
        if code in self.stock_names and self.stock_names[code]:
            return self.stock_names[code]
        
        # 하드코딩된 사전
        hardcoded_stocks = {
            '005930': '삼성전자',
            '035720': '카카오', 
            '000660': 'SK하이닉스',
            '042660': '한화오션',
            '062040': '산일전기',
            '272210': '한화시스템',
            '161580': '필옵틱스',
            '281820': '케이씨텍',
            '014620': '성광밴드',
            '278470': '에이피알'
        }
        
        if code in hardcoded_stocks:
            name = hardcoded_stocks[code]
            self.stock_names[code] = name
            self.save_stock_names()
            return name
        
        return code
    
    def update_all_stock_names(self):
        """종목명 업데이트"""
        self.logger.info("🔄 종목명 업데이트 시작...")
        
        for symbol in getattr(self, 'symbols', []):
            if symbol not in self.stock_names:
                self.stock_names[symbol] = self.get_stock_name(symbol)
                time.sleep(0.1)
        
        self.logger.info("✅ 종목명 업데이트 완료")
    
    def load_position_settings(self):
        """포지션 관리 설정 로드"""
        try:
            with open('config.yaml', 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            position_config = config.get('position_management', {})
            
            self.max_purchases_per_symbol = position_config.get('max_purchases_per_symbol', 2)
            self.max_quantity_per_symbol = position_config.get('max_quantity_per_symbol', 300)
            self.min_holding_period_hours = position_config.get('min_holding_period_hours', 72)
            self.purchase_cooldown_hours = position_config.get('purchase_cooldown_hours', 48)
            
            self.logger.info(f"📊 포지션 관리 설정 로드 완료")
            
        except Exception as e:
            self.logger.warning(f"포지션 설정 로드 실패, 기본값 사용: {e}")
            self.max_purchases_per_symbol = 2
            self.max_quantity_per_symbol = 300
            self.min_holding_period_hours = 72
            self.purchase_cooldown_hours = 48
    
    def create_robust_session(self):
        """견고한 HTTP 세션 생성"""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def load_symbols_from_backtest(self, config: dict) -> List[str]:
        """백테스트 결과에서 종목 로드"""
        symbols = []
        
        # 1. config에 직접 지정된 symbols 확인
        if 'symbols' in config.get('trading', {}):
            symbols = config['trading']['symbols']
            self.logger.info(f"설정 파일에서 종목 로드: {symbols}")
            return symbols
        
        # 2. 백테스트 결과 파일에서 로드
        try:
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
                symbols = [item['symbol'] for item in selected]
                
                # 종목별 전략 매핑 저장
                for item in selected:
                    self.strategy_map[item['symbol']] = item['strategy']
                
                self.logger.info(f"백테스트 결과에서 종목 로드: {symbols}")
                
            else:
                self.logger.warning(f"백테스트 결과 파일을 찾을 수 없음: {self.backtest_results_file}")
                symbols = ['005930', '035720', '042660']  # 기본 종목
                
        except Exception as e:
            self.logger.error(f"백테스트 결과 로드 실패: {e}")
            symbols = ['005930', '035720', '042660']
        
        return symbols
    
    def create_sample_config(self, config_path: str):
        """샘플 설정 파일 생성"""
        sample_config = {
            'kis': {
                'app_key': 'YOUR_APP_KEY',
                'app_secret': 'YOUR_APP_SECRET',
                'base_url': 'https://openapi.koreainvestment.com:9443',
                'account_no': 'YOUR_ACCOUNT_NO'
            },
            'trading': {
                'max_symbols': 3,
                'max_position_ratio': 0.4,
                'daily_loss_limit': 0.05,
                'stop_loss_pct': 0.08,
                'take_profit_pct': 0.25,
                'strategy_type': 'hybrid',
                'symbols': ['005930', '035720', '042660']  # 기본 종목
            },
            'position_management': {
                'max_purchases_per_symbol': 2,
                'max_quantity_per_symbol': 300,
                'min_holding_period_hours': 72,
                'purchase_cooldown_hours': 48
            },
            'momentum': {
                'period': 20,
                'threshold': 0.02,
                'volume_threshold': 1.5,
                'ma_short': 5,
                'ma_long': 20
            },
            'daily_strategy': {
                'trend_analysis_days': 180,
                'min_buy_score': 5.0,
                'min_sell_score': 3.0
            },
            'minute_timing': {
                'min_timing_score': 4,
                'sell_timing_score': 3,
                'rsi_period': 14,
                'volume_lookback': 20,
                'max_spread': 500
            },
            'backtest': {
                'results_file': 'backtest_results.json',
                'min_return_threshold': 5.0,
                'performance_tracking': True
            },
            'notification': {
                'discord_webhook': '',
                'notify_on_trade': True,
                'notify_on_error': True,
                'notify_on_daily_summary': True
            }
        }
    
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(sample_config, f, default_flow_style=False, allow_unicode=True)

    def load_saved_token(self):
        """저장된 토큰 파일에서 토큰 로드"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    token_data = json.load(f)
            expire_time_str = token_data.get('access_token_token_expired', '')
            if expire_time_str:
                expire_time = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')
    
                if datetime.now() < expire_time - timedelta(minutes=10):
                    self.access_token = token_data.get('access_token')
                    self.last_token_time = datetime.fromtimestamp(token_data.get('requested_at', 0))
                    self.logger.info(f"기존 토큰을 재사용합니다. (만료: {expire_time_str})")
                    return True
                else:
                    self.logger.info(f"저장된 토큰이 만료되었습니다.")
    
        except Exception as e:
            self.logger.warning(f"토큰 파일 로드 실패: {e}")
    
        return False
    
    def save_token(self, token_response: dict):
        """토큰을 파일에 저장"""
        try:
            current_time = int(time.time())
            expires_in = token_response.get('expires_in', 86400)
            expire_datetime = datetime.fromtimestamp(current_time + expires_in)
    
            token_data = {
                'access_token': token_response.get('access_token'),
                'access_token_token_expired': expire_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'token_type': token_response.get('token_type', 'Bearer'),
                'expires_in': expires_in,
                'requested_at': current_time
            }
    
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, ensure_ascii=False, indent=2)
    
            self.logger.info(f"토큰이 저장되었습니다.")
    
        except Exception as e:
            self.logger.error(f"토큰 저장 실패: {e}")
    
    def get_access_token(self) -> str:
        """KIS API 액세스 토큰 발급 또는 재사용"""
        if self.access_token and self.last_token_time:
            if datetime.now() - self.last_token_time < timedelta(hours=23):
                return self.access_token
    
        if self.load_saved_token():
            return self.access_token
    
        self.logger.info("새로운 액세스 토큰을 발급받습니다...")
    
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
    
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
    
            token_response = response.json()
            access_token = token_response.get("access_token")
            
            if access_token:
                self.access_token = access_token
                self.last_token_time = datetime.now()
                self.save_token(token_response)
                self.logger.info("✅ 새로운 액세스 토큰 발급 완료")
                return self.access_token
            else:
                error_msg = token_response.get('msg1', 'Unknown error')
                raise Exception(f"토큰 발급 실패: {error_msg}")
    
        except Exception as e:
            self.logger.error(f"❌ 토큰 발급 실패: {e}")
            raise
    
    def get_daily_data(self, symbol: str, days: int = 180) -> pd.DataFrame:
        """일봉 데이터 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010100"
        }
    
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
            "fid_input_date_1": start_date,
            "fid_input_date_2": end_date,
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0"
        }
    
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
    
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                
                # 날짜순 정렬
                if 'stck_bsop_date' in df.columns:
                    df = df.sort_values('stck_bsop_date').reset_index(drop=True)
                
                # 컬럼명 매핑
                column_mapping = {
                    'stck_clpr': 'stck_prpr',
                    'stck_oprc': 'stck_oprc',
                    'stck_hgpr': 'stck_hgpr',
                    'stck_lwpr': 'stck_lwpr',
                    'acml_vol': 'cntg_vol'
                }
                
                for old_col, new_col in column_mapping.items():
                    if old_col in df.columns:
                        df[new_col] = df[old_col]
                
                # 숫자형 변환
                numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                df = df.dropna(subset=['stck_prpr'])
                
                self.logger.info(f"✅ {symbol} 일봉 데이터 {len(df)}개 조회 완료")
                return df
                
        except Exception as e:
            self.logger.error(f"일봉 데이터 조회 실패 ({symbol}): {e}")
    
        return pd.DataFrame()
    
    def get_minute_data(self, symbol: str, minutes: int = 240) -> pd.DataFrame:
        """분봉 데이터 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010200"
        }
    
        end_time = datetime.now().strftime("%H%M%S")
        params = {
            "fid_etc_cls_code": "",
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
            "fid_input_hour_1": end_time,
            "fid_pw_data_incu_yn": "Y"
        }
    
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
    
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                if not df.empty and 'stck_cntg_hour' in df.columns:
                    df['stck_cntg_hour'] = pd.to_datetime(df['stck_cntg_hour'], format='%H%M%S', errors='coerce')
                    numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # NaN 제거
                    df = df.dropna(subset=['stck_prpr'])
                    
                    if not df.empty:
                        self.logger.info(f"✅ {symbol} 분봉 데이터 {len(df)}개 조회 완료")
                        return df.sort_values('stck_cntg_hour').reset_index(drop=True)
                    else:
                        self.logger.warning(f"⚠️ {symbol} 분봉 데이터가 비어있음")
                else:
                    self.logger.warning(f"⚠️ {symbol} 분봉 데이터 구조 이상")
    
        except Exception as e:
            self.logger.error(f"분봉 데이터 조회 실패 ({symbol}): {e}")
    
        return pd.DataFrame()
    
    def calculate_macd(self, df: pd.DataFrame, price_col: str = 'stck_prpr') -> pd.DataFrame:
        """MACD 지표 계산"""
        if len(df) < self.macd_slow + self.macd_signal:
            return df
        
        try:
            prices = df[price_col].astype(float)
            
            # EMA 계산
            ema_fast = prices.ewm(span=self.macd_fast).mean()
            ema_slow = prices.ewm(span=self.macd_slow).mean()
            
            # MACD 지표
            df['macd_line'] = ema_fast - ema_slow
            df['macd_signal'] = df['macd_line'].ewm(span=self.macd_signal).mean()
            df['macd_histogram'] = df['macd_line'] - df['macd_signal']
            
            # 골든크로스/데드크로스 감지
            df['macd_cross'] = 0
            for i in range(1, len(df)):
                if (df['macd_line'].iloc[i] > df['macd_signal'].iloc[i] and 
                    df['macd_line'].iloc[i-1] <= df['macd_signal'].iloc[i-1]):
                    df.iloc[i, df.columns.get_loc('macd_cross')] = 1
                elif (df['macd_line'].iloc[i] < df['macd_signal'].iloc[i] and 
                      df['macd_line'].iloc[i-1] >= df['macd_signal'].iloc[i-1]):
                    df.iloc[i, df.columns.get_loc('macd_cross')] = -1
            
            return df
            
        except Exception as e:
            self.logger.error(f"MACD 계산 실패: {e}")
            return df
    
    def detect_macd_golden_cross(self, df: pd.DataFrame) -> Dict:
        """MACD 골든크로스 감지"""
        if 'macd_cross' not in df.columns or len(df) < 10:
            return {
                'golden_cross': False,
                'cross_strength': 0,
                'signal_age': 999,
                'macd_above_zero': False
            }
        
        try:
            # 최근 몇 봉에서 골든크로스 발생했는지 확인
            recent_crosses = df['macd_cross'].tail(self.macd_cross_lookback)
            golden_cross_occurred = any(recent_crosses == 1)
            
            # 골든크로스 발생 시점 찾기
            signal_age = 999
            if golden_cross_occurred:
                cross_indices = df[df['macd_cross'] == 1].index
                if len(cross_indices) > 0:
                    last_cross_idx = cross_indices[-1]
                    signal_age = len(df) - df.index.get_loc(last_cross_idx) - 1
            
            # MACD 신호 강도 계산
            latest = df.iloc[-1]
            macd_gap = abs(latest['macd_line'] - latest['macd_signal'])
            
            # 히스토그램 추세
            histogram_trend = 'neutral'
            if len(df) >= 3:
                recent_hist = df['macd_histogram'].tail(3).tolist()
                if all(recent_hist[i] < recent_hist[i+1] for i in range(len(recent_hist)-1)):
                    histogram_trend = 'rising'
                elif all(recent_hist[i] > recent_hist[i+1] for i in range(len(recent_hist)-1)):
                    histogram_trend = 'falling'
            
            macd_above_zero = latest['macd_line'] > 0
            
            # 신호 강도 종합 계산
            cross_strength = 0
            if golden_cross_occurred:
                cross_strength = 2.0
                
                if macd_above_zero:
                    cross_strength += 0.5
                if histogram_trend == 'rising':
                    cross_strength += 0.5
                if signal_age <= 2:
                    cross_strength += 0.5
                if macd_gap > df['macd_line'].std() * 0.5:
                    cross_strength += 0.5
            
            return {
                'golden_cross': golden_cross_occurred,
                'cross_strength': min(cross_strength, 5.0),
                'histogram_trend': histogram_trend,
                'signal_age': signal_age,
                'macd_line': latest['macd_line'],
                'macd_signal': latest['macd_signal'],
                'macd_histogram': latest['macd_histogram'],
                'macd_above_zero': macd_above_zero
            }
            
        except Exception as e:
            self.logger.error(f"MACD 골든크로스 감지 실패: {e}")
            return {
                'golden_cross': False,
                'cross_strength': 0,
                'signal_age': 999,
                'macd_above_zero': False
            }
    
    def get_current_bid_ask(self, symbol: str) -> Dict:
        """현재 호가 정보 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010200"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('rt_cd') == '0' and data.get('output1'):
                    output = data['output1']
                    
                    bid_ask_info = {
                        'current_price': int(output.get('stck_prpr', 0)),
                        'bid_price': int(output.get('bidp1', 0)),
                        'ask_price': int(output.get('askp1', 0)),
                        'bid_quantity': int(output.get('bidp_rsqn1', 0)),
                        'ask_quantity': int(output.get('askp_rsqn1', 0)),
                        'spread': int(output.get('askp1', 0)) - int(output.get('bidp1', 0))
                    }
                    
                    return bid_ask_info
                    
        except Exception as e:
            self.logger.error(f"호가 조회 실패 ({symbol}): {e}")
        
        return {}
    
    def get_account_balance(self) -> Dict:
        """계좌 잔고 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        
        is_mock = "vts" in self.base_url.lower()
        tr_id = "VTTC8908R" if is_mock else "TTTC8908R"
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id
        }
        
        params = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": "005930",
            "ORD_UNPR": "0",
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N"
        }
    
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('rt_cd') != '0':
                self.logger.error(f"계좌 조회 실패: {data.get('msg1', 'Unknown error')}")
                return {}
                
            output = data.get('output', {})
            if output:
                available_cash = float(output.get('ord_psbl_cash', 0))
                self.logger.info(f"💵 가용자금: {available_cash:,}원")
                output['ord_psbl_cash'] = str(int(available_cash))
            
            return data
            
        except Exception as e:
            self.logger.error(f"계좌 조회 실패: {e}")
            return {}
    
    def calculate_position_size(self, symbol: str, current_price: float, signal_strength: float) -> int:
        """포지션 크기 계산"""
        try:
            account_data = self.get_account_balance()
            if not account_data:
                return 0
    
            output = account_data.get('output', {})
            available_cash = float(output.get('ord_psbl_cash', 0))
            
            if available_cash == 0:
                return 0
                
            # 최대 투자 가능 금액
            max_investment = available_cash * self.max_position_ratio
            
            # 신호 강도에 따른 조정
            if signal_strength < 0.5:
                return 0
            elif signal_strength < 1.0:
                position_ratio = 0.2
            elif signal_strength < 2.0:
                position_ratio = 0.4
            elif signal_strength < 3.0:
                position_ratio = 0.6
            elif signal_strength < 4.0:
                position_ratio = 0.8
            else:
                position_ratio = 1.0
    
            adjusted_investment = max_investment * position_ratio
            
            # 최소 투자 금액 체크
            min_investment = 100000
            if adjusted_investment < min_investment:
                if available_cash >= min_investment:
                    adjusted_investment = min_investment
                else:
                    return 0
    
            quantity = int(adjusted_investment / current_price)
            
            self.logger.info(f"📊 {symbol} 포지션 계산: {quantity}주 (투자금액: {adjusted_investment:,}원)")
            
            return max(quantity, 0)
    
        except Exception as e:
            self.logger.error(f"포지션 크기 계산 실패: {e}")
            return 0
    
    def can_purchase_symbol(self, symbol: str) -> tuple[bool, str]:
        """종목 매수 가능 여부 확인"""
        
        # 현재 보유 수량 확인
        current_position = self.positions.get(symbol, {})
        current_quantity = current_position.get('quantity', 0)
        
        if current_quantity >= self.max_quantity_per_symbol:
            return False, f"최대 보유 수량 초과 ({current_quantity}/{self.max_quantity_per_symbol}주)"
        
        # 매수 횟수 제한 확인
        history = self.position_manager.position_history.get(symbol, {})
        purchase_count = history.get('purchase_count', 0)
        
        if purchase_count >= self.max_purchases_per_symbol:
            return False, f"최대 매수 횟수 초과 ({purchase_count}/{self.max_purchases_per_symbol}회)"
        
        # 재매수 금지 기간 확인
        last_purchase_time = history.get('last_purchase_time')
        if last_purchase_time:
            last_time = datetime.fromisoformat(last_purchase_time)
            time_since_last = datetime.now() - last_time
            
            if time_since_last < timedelta(hours=self.purchase_cooldown_hours):
                remaining_hours = self.purchase_cooldown_hours - time_since_last.total_seconds() / 3600
                return False, f"재매수 금지 기간 중 (남은 시간: {remaining_hours:.1f}시간)"
        
        return True, "매수 가능"
    
    def can_sell_symbol(self, symbol: str) -> tuple[bool, str]:
        """종목 매도 가능 여부 확인"""
        
        # 보유 여부 확인
        current_position = self.positions.get(symbol, {})
        if not current_position or current_position.get('quantity', 0) <= 0:
            return False, "보유 포지션 없음"
        
        # 최소 보유 기간 확인
        history = self.position_manager.position_history.get(symbol, {})
        first_purchase_time = history.get('first_purchase_time')
        
        if first_purchase_time:
            first_time = datetime.fromisoformat(first_purchase_time)
            holding_time = datetime.now() - first_time
            
            if holding_time < timedelta(hours=self.min_holding_period_hours):
                remaining_hours = self.min_holding_period_hours - holding_time.total_seconds() / 3600
                return False, f"최소 보유 기간 미충족 (남은 시간: {remaining_hours:.1f}시간)"
        
        return True, "매도 가능"
    
    def adjust_to_price_unit(self, price: float) -> int:
        """한국 주식 호가단위에 맞게 가격 조정"""
        
        if price <= 0:
            return 1
        
        if price < 1000:
            return int(price)
        elif price < 5000:
            return int(price // 5) * 5
        elif price < 10000:
            return int(price // 10) * 10
        elif price < 50000:
            return int(price // 50) * 50
        elif price < 100000:
            return int(price // 100) * 100
        elif price < 500000:
            return int(price // 500) * 500
        else:
            return int(price // 1000) * 1000
    
    def calculate_smart_limit_price(self, symbol: str, side: str, urgency: str = "normal") -> int:
        """스마트 지정가 계산"""
        
        # 호가 정보 조회
        bid_ask = self.get_current_bid_ask(symbol)
        
        if not bid_ask:
            # 호가 조회 실패 시 현재가 기반
            try:
                current_price_data = self.get_current_price(symbol)
                if current_price_data and current_price_data.get('output'):
                    current_price = float(current_price_data['output'].get('stck_prpr', 0))
                    
                    if current_price > 0:
                        if side == "BUY":
                            raw_price = current_price * 1.003
                        else:
                            raw_price = current_price * 0.997
                        
                        return self.adjust_to_price_unit(raw_price)
            except:
                pass
            
            raise Exception("현재가 정보를 가져올 수 없습니다")
        
        current_price = bid_ask['current_price']
        bid_price = bid_ask['bid_price']
        ask_price = bid_ask['ask_price']
        spread = bid_ask['spread']
        
        if side == "BUY":
            if urgency == "urgent":
                raw_price = ask_price
            elif urgency == "aggressive":
                raw_price = ask_price + max(spread // 4, self.get_min_price_unit(ask_price))
            else:
                if spread <= self.get_min_price_unit(current_price) * 5:
                    raw_price = ask_price
                else:
                    raw_price = (current_price + ask_price) / 2
        else:
            if urgency == "urgent":
                raw_price = bid_price
            elif urgency == "aggressive":
                raw_price = bid_price - max(spread // 4, self.get_min_price_unit(bid_price))
            else:
                if spread <= self.get_min_price_unit(current_price) * 5:
                    raw_price = bid_price
                else:
                    raw_price = (current_price + bid_price) / 2
        
        limit_price = self.adjust_to_price_unit(raw_price)
        limit_price = max(limit_price, 1)
        
        self.logger.info(f"💰 {symbol} {side} 지정가: {limit_price:,}원 (긴급도: {urgency})")
        
        return limit_price
    
    def get_min_price_unit(self, price: float) -> int:
        """가격대별 최소 호가단위"""
        if price < 1000:
            return 1
        elif price < 5000:
            return 5
        elif price < 10000:
            return 10
        elif price < 50000:
            return 50
        elif price < 100000:
            return 100
        elif price < 500000:
            return 500
        else:
            return 1000
    
    def get_current_price(self, symbol: str) -> Dict:
        """현재가 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100"
        }
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol}
    
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"현재가 조회 실패 ({symbol}): {e}")
            return {}
    
    def place_order_with_strategy(self, symbol: str, side: str, quantity: int, strategy: str = "limit") -> Dict:
        """전략적 주문 실행"""
        
        if strategy == "market":
            return self.place_order(symbol, side, quantity, price=0)
        
        elif strategy in ["limit", "aggressive_limit", "patient_limit", "urgent"]:
            urgency_map = {
                "limit": "normal",
                "aggressive_limit": "aggressive", 
                "patient_limit": "normal",
                "urgent": "urgent"
            }
            urgency = urgency_map.get(strategy, "normal")
            
            try:
                limit_price = self.calculate_smart_limit_price(symbol, side, urgency)
                return self.place_order(symbol, side, quantity, price=limit_price)
            except Exception as e:
                self.logger.warning(f"지정가 계산 실패, 시장가로 변경: {e}")
                return self.place_order(symbol, side, quantity, price=0)
        
        else:
            return self.place_order(symbol, side, quantity, price=0)
    
    def place_order(self, symbol: str, side: str, quantity: int, price: int = 0) -> Dict:
        """주문 실행"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        is_mock = "vts" in self.base_url.lower()
        
        if is_mock:
            tr_id = "VTTC0802U" if side == "BUY" else "VTTC0801U"
        else:
            tr_id = "TTTC0802U" if side == "BUY" else "TTTC0801U"
        
        if price == 0:
            ord_dvsn = "01"
            ord_unpr = "0"
        else:
            ord_dvsn = "00"
            ord_unpr = str(price)
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id
        }
    
        data = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": ord_unpr
        }
    
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=30)
            response.raise_for_status()
            result = response.json()
    
            if result.get('rt_cd') == '0':
                order_no = result.get('output', {}).get('odno', 'Unknown')
                self.logger.info(f"✅ 주문 성공: {symbol} {side} {quantity}주 (주문번호: {order_no})")
                self.trade_count += 1
                self.notify_trade_success(side, symbol, quantity, price if price > 0 else 0, order_no)
                return {'success': True, 'order_no': order_no, 'limit_price': price}
            else:
                error_msg = result.get('msg1', 'Unknown error')
                self.logger.error(f"주문 실패: {error_msg}")
                self.notify_trade_failure(side, symbol, error_msg)
                return {'success': False, 'error': error_msg}
    
        except Exception as e:
            self.logger.error(f"주문 실행 실패 ({symbol} {side}): {e}")
            self.notify_trade_failure(side, symbol, str(e))
            return {'success': False, 'error': str(e)}
    
    def update_all_positions(self):
        """모든 보유 종목 포지션 업데이트"""
        try:
            all_holdings = self.get_all_holdings()
            
            self.positions = {}
            for symbol in getattr(self, 'symbols', []):
                if symbol in all_holdings:
                    self.positions[symbol] = all_holdings[symbol]
            
            self.all_positions = all_holdings
            
            self.logger.info(f"💼 포지션 업데이트: 거래대상 {len(self.positions)}개, 전체 {len(self.all_positions)}개")
            
        except Exception as e:
            self.logger.error(f"포지션 업데이트 실패: {e}")
    
    def get_all_holdings(self) -> Dict:
        """실제 계좌의 모든 보유 종목 조회"""
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
            
            is_mock = "vts" in self.base_url.lower()
            tr_id = "VTTC8434R" if is_mock else "TTTC8434R"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": tr_id
            }
            
            params = {
                "CANO": self.account_no.split('-')[0],
                "ACNT_PRDT_CD": self.account_no.split('-')[1],
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('rt_cd') == '0':
                    all_holdings = {}
                    holdings = data.get('output1', [])
                    
                    if isinstance(holdings, list):
                        for holding in holdings:
                            symbol = holding.get('pdno', '')
                            quantity = int(holding.get('hldg_qty', 0))
                            
                            if quantity > 0 and symbol:
                                all_holdings[symbol] = {
                                    'quantity': quantity,
                                    'avg_price': float(holding.get('pchs_avg_pric', 0)),
                                    'current_price': float(holding.get('prpr', 0)),
                                    'profit_loss': float(holding.get('evlu_pfls_rt', 0)),
                                    'stock_name': holding.get('prdt_name', symbol),
                                    'total_value': float(holding.get('evlu_amt', 0)),
                                    'purchase_amount': float(holding.get('pchs_amt', 0))
                                }
                    
                    return all_holdings
                    
        except Exception as e:
            self.logger.error(f"전체 보유 종목 조회 실패: {e}")
        
        return {}
    
    def process_sell_signals(self):
        """매도 신호 처리"""
        if not hasattr(self, 'all_positions') or not self.all_positions:
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
    
    def process_sell_for_symbol(self, symbol: str, position: Dict):
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
                can_sell, sell_reason = self.can_sell_symbol(symbol)
                
                if can_sell:
                    self.logger.info(f"🎯 {symbol} 익절 조건 충족! ({profit_loss_pct:+.2f}%)")
                    self.execute_sell(symbol, quantity, "patient_limit", "익절매")
                    return
                else:
                    self.logger.info(f"💎 {symbol} 익절 조건이지만 보유 지속: {sell_reason}")
            
            # 3순위: 매도 신호 확인 (거래 대상 종목만)
            if symbol in getattr(self, 'symbols', []):
                if hasattr(self, 'hybrid_strategy'):
                    daily_analysis = self.hybrid_strategy.analyze_daily_strategy(symbol)
                    
                    if daily_analysis['signal'] == 'SELL' and daily_analysis['strength'] >= 3.0:
                        can_sell, sell_reason = self.can_sell_symbol(symbol)
                        
                        if can_sell:
                            self.logger.info(f"📉 {symbol} 일봉 매도 신호 감지")
                            self.execute_sell(symbol, quantity, "aggressive_limit", "일봉 매도신호")
                            return
            
        except Exception as e:
            self.logger.error(f"{symbol} 매도 처리 중 오류: {e}")
    
    def execute_sell(self, symbol: str, quantity: int, order_strategy: str, reason: str):
        """매도 실행"""
        result = self.place_order_with_strategy(symbol, 'SELL', quantity, order_strategy)
        
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
    
    def check_risk_management(self) -> bool:
        """리스크 관리 체크"""
        if abs(self.daily_pnl) > self.daily_loss_limit:
            self.logger.warning(f"일일 손실 한도 초과: {self.daily_pnl:.2%}")
            return False
    
        if self.trade_count > 100:
            self.logger.warning("일일 최대 거래 횟수 초과")
            return False
    
        return True
    
    def is_market_open(self, current_time=None):
        """한국 증시 개장 시간 확인"""
        if current_time is None:
            current_time = datetime.now()
        
        weekday = current_time.weekday()
        if weekday >= 5:
            return False
        
        hour = current_time.hour
        minute = current_time.minute
        
        if hour < 9:
            return False
        
        if hour > 15 or (hour == 15 and minute > 30):
            return False
        
        return True
    
    def get_market_status_info(self, current_time=None):
        """장 상태 정보 반환"""
        if current_time is None:
            current_time = datetime.now()
        
        is_open = self.is_market_open(current_time)
        
        if is_open:
            today_close = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            time_to_close = today_close - current_time
            
            return {
                'status': 'OPEN',
                'message': f'장 시간 중 (마감까지 {str(time_to_close).split(".")[0]})',
                'next_change': today_close,
                'is_trading_time': True
            }
        else:
            # 다음 개장 시간 계산
            next_day = current_time + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            
            next_open = next_day.replace(hour=9, minute=0, second=0, microsecond=0)
            
            if current_time.weekday() >= 5:
                message = f'주말 휴장 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            elif current_time.hour < 9:
                message = f'장 시작 전 (개장: 09:00)'
            else:
                message = f'장 마감 후 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            
            return {
                'status': 'CLOSED',
                'message': message,
                'next_change': next_open,
                'is_trading_time': False
            }
    
    def send_discord_notification(self, title: str, message: str, color: int = 0x00ff00):
        """디스코드 웹훅으로 알림 전송"""
        if not self.discord_webhook:
            return False
    
        try:
            korea_now = datetime.now()
            utc_time = korea_now - timedelta(hours=9)
            embed = {
                "title": title,
                "description": message,
                "color": color,
                "timestamp": utc_time.isoformat() + "Z",
                "footer": {
                    "text": "하이브리드 자동매매 시스템"
                }
            }
    
            data = {"embeds": [embed]}
    
            response = requests.post(
                self.discord_webhook,
                json=data,
                timeout=10
            )
    
            return response.status_code == 204
    
        except Exception as e:
            self.logger.error(f"디스코드 알림 오류: {e}")
            return False
    
    def notify_trade_success(self, action: str, symbol: str, quantity: int, price: int, order_no: str):
        """매매 성공 알림"""
        if not self.notify_on_trade:
            return
    
        action_emoji = "🛒" if action == "매수" else "💸"
        color = 0x00ff00 if action == "매수" else 0xff6600
    
        stock_name = self.get_stock_name(symbol)
        title = f"{action_emoji} {action} 주문 체결!"
        message = f"""
종목: {symbol} ({stock_name})
수량: {quantity}주
가격: {price:,}원
총액: {quantity * price:,}원
주문번호: {order_no}
시간: {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_discord_notification(title, message, color)
    
    def notify_trade_failure(self, action: str, symbol: str, error_msg: str):
        """매매 실패 알림"""
        if not self.notify_on_error:
            return
    
        title = f"❌ {action} 주문 실패"
        message = f"""
종목: {symbol}
오류: {error_msg}
시간: {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_discord_notification(title, message, 0xff0000)
    
    def notify_daily_summary(self, total_trades: int, profit_loss: float, successful_trades: int):
        """일일 요약 알림"""
        if not self.notify_on_daily_summary:
            return
    
        title = "📊 일일 거래 요약"
        color = 0x00ff00 if profit_loss >= 0 else 0xff0000
    
        message = f"""
총 거래 횟수: {total_trades}회
성공한 거래: {successful_trades}회
일일 수익률: {profit_loss:.2%}
거래 종목: {', '.join(getattr(self, 'symbols', []))}
날짜: {datetime.now().strftime('%Y-%m-%d')}
"""
        self.send_discord_notification(title, message, color)
    
    def notify_error(self, error_type: str, error_msg: str):
        """오류 알림"""
        if not self.notify_on_error:
            return
    
        title = f"⚠️ 시스템 오류: {error_type}"
        message = f"""
오류 내용: {error_msg}
시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_discord_notification(title, message, 0xff0000)
    
    def run_hybrid_strategy(self, check_interval_minutes=30):
        """하이브리드 전략 실행"""
        self.logger.info("🚀 하이브리드 전략 시작")
        self.logger.info(f"📊 일봉 분석 + 분봉 실행 시스템")
        self.logger.info(f"⏰ 체크 간격: {check_interval_minutes}분")
        
        # 하이브리드 전략 초기화
        if not hasattr(self, 'hybrid_strategy'):
            self.hybrid_strategy = HybridTradingStrategy(self)
        
        # 시작 알림
        if self.discord_webhook:
            self.send_discord_notification(
                "🚀 하이브리드 전략 시작",
                f"일봉 분석 + 분봉 실행\n체크 간격: {check_interval_minutes}분\n대상 종목: {', '.join(getattr(self, 'symbols', []))}",
                0x00ff00
            )
        
        daily_trades = 0
        last_daily_summary = datetime.now().date()
        last_position_update = datetime.now()
        
        try:
            while True:
                current_time = datetime.now()
                market_info = self.get_market_status_info(current_time)
                
                if market_info['is_trading_time']:
                    self.logger.info(f"📊 하이브리드 사이클 - {current_time.strftime('%H:%M:%S')}")
                    
                    cycle_start_trades = self.trade_count
                    
                    try:
                        # 포지션 업데이트 (10분마다)
                        if current_time - last_position_update > timedelta(minutes=10):
                            self.update_all_positions()
                            last_position_update = current_time
                        
                        # 각 종목별 하이브리드 매매 실행
                        for i, symbol in enumerate(getattr(self, 'symbols', []), 1):
                            self.logger.info(f"🔍 [{i}/{len(self.symbols)}] {symbol} 하이브리드 분석")
                            
                            try:
                                if self.hybrid_strategy.execute_hybrid_trade(symbol):
                                    daily_trades += 1
                                    self.logger.info(f"✅ {symbol} 하이브리드 매매 실행됨")
                                else:
                                    self.logger.debug(f"⏸️ {symbol} 매매 조건 미충족")
                                    
                                time.sleep(2)
                                
                            except Exception as e:
                                self.logger.error(f"❌ {symbol} 하이브리드 실행 오류: {e}")
                        
                        # 기존 포지션 손익 관리
                        self.process_sell_signals()
                        
                        # 이번 사이클
                        self.logger.info("✅ 하이브리드 사이클 완료")
                        
                    except Exception as e:
                        self.logger.error(f"❌ 하이브리드 실행 오류: {e}")
                        self.notify_error("하이브리드 실행 오류", str(e))
                
                else:
                    self.logger.info(f"⏰ 장 외 시간: {market_info['message']}")
                    
                    # 장 외 시간에는 체크 간격 연장
                    if current_time.weekday() >= 5:  # 주말
                        sleep_minutes = 120  # 2시간
                    else:
                        sleep_minutes = 60   # 1시간
                
                # 일일 요약 (장 마감 후)
                if (current_time.date() != last_daily_summary and 
                    current_time.hour >= 16):
                    
                    self.notify_daily_summary(daily_trades, self.daily_pnl, daily_trades)
                    daily_trades = 0
                    self.daily_pnl = 0
                    last_daily_summary = current_time.date()
                
                # 대기 시간 계산
                if market_info['is_trading_time']:
                    sleep_time = check_interval_minutes * 60
                    next_run = current_time + timedelta(minutes=check_interval_minutes)
                    self.logger.info(f"다음 하이브리드 체크: {next_run.strftime('%H:%M:%S')}")
                else:
                    sleep_time = sleep_minutes * 60
                    next_run = current_time + timedelta(minutes=sleep_minutes)
                    self.logger.info(f"다음 상태 체크: {next_run.strftime('%H:%M:%S')}")
                
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            self.logger.info("🛑 사용자가 하이브리드 전략을 종료했습니다.")
            if self.discord_webhook:
                self.send_discord_notification("⏹️ 하이브리드 전략 종료", "사용자가 프로그램을 종료했습니다.", 0xff6600)
        except Exception as e:
            self.logger.error(f"❌ 하이브리드 전략 실행 중 오류: {e}")
            self.notify_error("하이브리드 전략 오류", str(e))
        finally:
            self.logger.info("하이브리드 전략 프로그램 종료")
    
    def integrate_hybrid_strategy(self):
        """하이브리드 전략을 기존 트레이더에 통합"""
        self.hybrid_strategy = HybridTradingStrategy(self)

	#END of class ====================
    
def check_dependencies():
    """필수 라이브러리 확인"""
    required_modules = ['requests', 'pandas', 'numpy', 'yaml']
    missing_modules = []
    
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing_modules.append(module)
    
    if missing_modules:
        print(f"❌ 필수 라이브러리가 설치되지 않았습니다: {', '.join(missing_modules)}")
        print("다음 명령어로 설치하세요:")
        print(f"pip install {' '.join(missing_modules)}")
        return False
    
    return True
    
def check_config_file():
    """설정 파일 존재 확인"""
    if not os.path.exists('config.yaml'):
        print("❌ config.yaml 파일이 없습니다.")
        print("샘플 설정 파일을 생성하시겠습니까? (y/n): ", end="")
    
    try:
        response = input().lower()
        if response in ['y', 'yes', '예']:
            trader = KISAutoTrader.__new__(KISAutoTrader)
            trader.create_sample_config('config.yaml')
            print("✅ config.yaml 파일이 생성되었습니다. 설정을 입력한 후 다시 실행하세요.")
        return False
    except KeyboardInterrupt:
        print("\n프로그램을 종료합니다.")
        return False
    
    return True
    
def create_logs_directory():
    os.makedirs('logs', exist_ok=True)
    
def test_hybrid_strategy():
    print("🧪 하이브리드 전략 테스트")
    print("="*60)

    try:
        trader = KISAutoTrader()
    
        # 테스트 종목으로 분석
        test_symbol = trader.symbols[0] if hasattr(trader, 'symbols') and trader.symbols else "005930"
        
        print(f"📊 {test_symbol} 하이브리드 분석 테스트:")
        
        # 1. 일봉 분석
        print("\n1️⃣ 일봉 전략 분석:")
        daily_analysis = trader.hybrid_strategy.analyze_daily_strategy(test_symbol)
    
        for key, value in daily_analysis.items():
            if key != 'macd_analysis':
                print(f"  {key}: {value}")
    
        # 2. 분봉 타이밍 분석
        if daily_analysis['signal'] in ['BUY', 'SELL']:
            print(f"\n2️⃣ 분봉 타이밍 분석 ({daily_analysis['signal']}):")
            timing_analysis = trader.hybrid_strategy.find_optimal_entry_timing(test_symbol, daily_analysis['signal'])
        
            for key, value in timing_analysis.items():
                print(f"  {key}: {value}")
            
            # 3. 종합 판단
            print(f"\n3️⃣ 종합 판단:")
            if daily_analysis['strength'] >= 4.0 and timing_analysis.get('execute', False):
                print("  ✅ 매매 실행 권장")
            else:
                print("  ⏸️ 매매 보류 권장")
                if daily_analysis['strength'] < 4.0:
                    print(f"    - 일봉 신호 부족: {daily_analysis['strength']:.2f} < 4.0")
                    if not timing_analysis.get('execute', False):
                        print(f"    - 분봉 타이밍 부적절: {timing_analysis.get('reason', '기준 미달')}")
        else:
            print("\n2️⃣ 일봉에서 HOLD 신호 - 분봉 분석 생략")
            
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    
def main():
    """업데이트된 메인 함수"""

    # 의존성 확인
    if not check_dependencies():
        sys.exit(1)
    
    # 로그 디렉토리 생성
    create_logs_directory()
    
    # 설정 파일 확인
    if not check_config_file():
        sys.exit(1)
    
    try:
        trader = KISAutoTrader()
        
        # 연결 테스트
        token = trader.get_access_token()
        if not token:
            trader.logger.error("❌ KIS API 연결 실패")
            return
            
        trader.logger.info("✅ KIS API 연결 테스트 성공")
            
        # 실행 모드 결정
        hybrid_mode = '--hybrid' in sys.argv
        test_mode = '--test' in sys.argv
        debug_mode = '--debug' in sys.argv
            
        if test_mode:
            # 테스트 모드
            test_hybrid_strategy()
                
        elif hybrid_mode:
            # 하이브리드 전략 실행
            interval = 15 if debug_mode else 30  # 디버그 모드는 15분
            trader.logger.info(f"🚀 하이브리드 전략 모드 (체크 간격: {interval}분)")
                
            trader.run_hybrid_strategy(check_interval_minutes=interval)
                
        else:
            # 기본 실행 (하이브리드 전략)
            trader.logger.info("🚀 기본 하이브리드 전략 실행")
            trader.run_hybrid_strategy(check_interval_minutes=30)
                
    except FileNotFoundError as e:
        print(f"❌ 필수 파일이 없습니다: {e}")
    except KeyboardInterrupt:
        print("\n🛑 사용자가 프로그램을 종료했습니다.")
    except Exception as e:
        print(f"❌ 프로그램 실행 중 오류: {e}")
        import traceback
        print(f"상세 오류:\n{traceback.format_exc()}")

def run_hybrid_strategy(trader, check_interval_minutes=30):
    """하이브리드 전략 실행"""
    trader.logger.info("🚀 하이브리드 전략 시작")
    trader.logger.info(f"📊 일봉 분석 + 분봉 실행 시스템")
    trader.logger.info(f"⏰ 체크 간격: {check_interval_minutes}분")
    
    # 하이브리드 전략 초기화
    if not hasattr(trader, 'hybrid_strategy'):
        trader.hybrid_strategy = HybridTradingStrategy(trader)
    
    # 시작 알림
    if trader.discord_webhook:
        trader.send_discord_notification(
            "🚀 하이브리드 전략 시작",
            f"일봉 분석 + 분봉 실행\n체크 간격: {check_interval_minutes}분\n대상 종목: {', '.join(getattr(trader, 'symbols', []))}",
            0x00ff00
        )
    
    daily_trades = 0
    last_daily_summary = datetime.now().date()
    last_position_update = datetime.now()
    
    try:
        while True:
            current_time = datetime.now()
            market_info = trader.get_market_status_info(current_time)
            
            if market_info['is_trading_time']:
                trader.logger.info(f"📊 하이브리드 사이클 - {current_time.strftime('%H:%M:%S')}")
                
                cycle_start_trades = trader.trade_count
                
                try:
                    # 포지션 업데이트 (10분마다)
                    if current_time - last_position_update > timedelta(minutes=10):
                        trader.update_all_positions()
                        last_position_update = current_time
                    
                    # 각 종목별 하이브리드 매매 실행
                    for i, symbol in enumerate(getattr(trader, 'symbols', []), 1):
                        trader.logger.info(f"🔍 [{i}/{len(trader.symbols)}] {symbol} 하이브리드 분석")
                        
                        try:
                            if trader.hybrid_strategy.execute_hybrid_trade(symbol):
                                daily_trades += 1
                                trader.logger.info(f"✅ {symbol} 하이브리드 매매 실행됨")
                            else:
                                trader.logger.debug(f"⏸️ {symbol} 매매 조건 미충족")
                                
                            time.sleep(2)
                            
                        except Exception as e:
                            trader.logger.error(f"❌ {symbol} 하이브리드 실행 오류: {e}")
                    
                    # 기존 포지션 손익 관리
                    trader.process_sell_signals()
                    
                    # 이번 사이클 거래 결과
                    cycle_trades = trader.trade_count - cycle_start_trades
                    if cycle_trades > 0:
                        trader.logger.info(f"📈 이번 사이클 거래: {cycle_trades}건")
                    
                    trader.logger.info("✅ 하이브리드 사이클 완료")
                    
                except Exception as e:
                    trader.logger.error(f"❌ 하이브리드 실행 오류: {e}")
                    trader.notify_error("하이브리드 실행 오류", str(e))
            
            else:
                trader.logger.info(f"⏰ 장 외 시간: {market_info['message']}")
                
                # 장 외 시간에는 체크 간격 연장
                if current_time.weekday() >= 5:  # 주말
                    sleep_minutes = 120  # 2시간
                else:
                    sleep_minutes = 60   # 1시간
            
            # 일일 요약 (장 마감 후)
            if (current_time.date() != last_daily_summary and 
                current_time.hour >= 16):
                
                trader.notify_daily_summary(daily_trades, trader.daily_pnl, daily_trades)
                daily_trades = 0
                trader.daily_pnl = 0
                last_daily_summary = current_time.date()
            
            # 대기 시간 계산
            if market_info['is_trading_time']:
                sleep_time = check_interval_minutes * 60
                next_run = current_time + timedelta(minutes=check_interval_minutes)
                trader.logger.info(f"다음 하이브리드 체크: {next_run.strftime('%H:%M:%S')}")
            else:
                sleep_time = sleep_minutes * 60
                next_run = current_time + timedelta(minutes=sleep_minutes)
                trader.logger.info(f"다음 상태 체크: {next_run.strftime('%H:%M:%S')}")
            
            time.sleep(sleep_time)
            
    except KeyboardInterrupt:
        trader.logger.info("🛑 사용자가 하이브리드 전략을 종료했습니다.")
        if trader.discord_webhook:
            trader.send_discord_notification("⏹️ 하이브리드 전략 종료", "사용자가 프로그램을 종료했습니다.", 0xff6600)
    except Exception as e:
        trader.logger.error(f"❌ 하이브리드 전략 실행 중 오류: {e}")
        trader.notify_error("하이브리드 전략 오류", str(e))
    finally:
        trader.logger.info("하이브리드 전략 프로그램 종료")

def main_hybrid():
    """하이브리드 전략으로 실행"""

    # 의존성 확인
    required_modules = ['requests', 'pandas', 'numpy', 'yaml']
    missing_modules = []
    
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing_modules.append(module)
    
    if missing_modules:
        print(f"❌ 필수 라이브러리가 설치되지 않았습니다: {', '.join(missing_modules)}")
        print("다음 명령어로 설치하세요:")
        print(f"pip install {' '.join(missing_modules)}")
        return
    
    # 로그 디렉토리 생성
    os.makedirs('logs', exist_ok=True)
    
    # 설정 파일 확인
    if not os.path.exists('config.yaml'):
        print("❌ config.yaml 파일이 없습니다.")
        print("샘플 설정 파일을 생성하시겠습니까? (y/n): ", end="")
        
        try:
            response = input().lower()
            if response in ['y', 'yes', '예']:
                trader = KISAutoTrader.__new__(KISAutoTrader)
                trader.create_sample_config('config.yaml')
                print("✅ config.yaml 파일이 생성되었습니다. 설정을 입력한 후 다시 실행하세요.")
            return
        except KeyboardInterrupt:
            print("\n프로그램을 종료합니다.")
            return
    
    try:
        trader = KISAutoTrader()
        
        # 연결 테스트
        token = trader.get_access_token()
        if not token:
            trader.logger.error("❌ KIS API 연결 실패")
            return
            
        trader.logger.info("✅ KIS API 연결 테스트 성공")
        
        # 실행 모드 결정
        debug_mode = '--debug' in sys.argv
        
        # 하이브리드 전략 실행
        interval = 15 if debug_mode else 30  # 디버그 모드는 15분
        trader.logger.info(f"🚀 하이브리드 전략 모드 (체크 간격: {interval}분)")
        
        run_hybrid_strategy(trader, check_interval_minutes=interval)
        
    except FileNotFoundError as e:
        print(f"❌ 필수 파일이 없습니다: {e}")
    except KeyboardInterrupt:
        print("\n🛑 사용자가 프로그램을 종료했습니다.")
    except Exception as e:
        print(f"❌ 프로그램 실행 중 오류: {e}")
        import traceback
        print(f"상세 오류:\n{traceback.format_exc()}")



if __name__ == "__main__":
    # 명령어 인수 처리
    if '--hybrid' in sys.argv:
        main_hybrid()
    elif '--test' in sys.argv or '--test-hybrid' in sys.argv:
        test_hybrid_strategy()
    else:
        main()
