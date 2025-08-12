"""
하이브리드 전략 모듈 (일봉 분석 + 분봉 실행)
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict
from .technical_indicators import TechnicalIndicators


class HybridStrategy:
    """일봉 전략 + 분봉 실행 하이브리드 시스템"""
    
    def __init__(self, api_client, order_manager, position_manager, notifier, logger):
        self.api_client = api_client
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.notifier = notifier
        self.logger = logger
        
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
        
        self.logger.info(f"📅 {symbol} 일봉 전략 분석 실행")
        
        # 일봉 데이터 조회 (6개월)
        df = self.api_client.get_daily_data(symbol, days=180)
        
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
            
            self.logger.info(f"📊 {symbol} 일봉 분석 완료: {signal_result['signal']} (강도: {signal_result['strength']:.2f})")
            
            return signal_result
            
        except Exception as e:
            self.logger.error(f"일봉 분석 실패 ({symbol}): {e}")
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
    
    def calculate_daily_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """일봉 기술 지표 계산"""
        
        # 이동평균선
        df = TechnicalIndicators.calculate_moving_averages(df)
        
        # MACD
        df = TechnicalIndicators.calculate_macd(df)
        
        # RSI
        df = TechnicalIndicators.calculate_rsi(df)
        
        # 볼린저 밴드
        df = TechnicalIndicators.calculate_bollinger_bands(df)
        
        # 스토캐스틱
        df = TechnicalIndicators.calculate_stochastic(df)
        
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
        macd_analysis = TechnicalIndicators.detect_macd_golden_cross(df)
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
        
        self.logger.info(f"🎯 {symbol} {target_signal} 최적 타이밍 분석")
        
        # 최근 4시간 분봉 데이터
        minute_df = self.api_client.get_minute_data(symbol, minutes=240)
        
        if minute_df.empty or len(minute_df) < 20:
            return {'execute': False, 'reason': '분봉 데이터 부족'}
        
        try:
            current_price = float(minute_df['stck_prpr'].iloc[-1])
            
            # 분봉 기술지표
            minute_df['ma5'] = minute_df['stck_prpr'].rolling(5).mean()
            minute_df['ma20'] = minute_df['stck_prpr'].rolling(20).mean()
            
            # 분봉 RSI
            minute_df = TechnicalIndicators.calculate_rsi(minute_df, period=14)
            
            latest_minute = minute_df.iloc[-1]
            
            if target_signal == 'BUY':
                return self.evaluate_buy_timing(minute_df, latest_minute, current_price, symbol)
            else:
                return self.evaluate_sell_timing(minute_df, latest_minute, current_price, symbol)
                
        except Exception as e:
            self.logger.error(f"분봉 타이밍 분석 실패 ({symbol}): {e}")
            return {'execute': False, 'reason': f'분석 오류: {str(e)}'}

    def evaluate_buy_timing(self, df: pd.DataFrame, latest: pd.Series, 
                           current_price: float, symbol: str = None) -> Dict:
        """매수 타이밍 평가"""
        
        timing_score = 0
        reasons = []
        
        # 1. 분봉 추세
        if latest['ma5'] > latest['ma20']:
            timing_score += 2
            reasons.append("분봉상승추세")
        
        # 2. 분봉 RSI
        minute_rsi = latest['rsi']
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
            bid_ask = self.api_client.get_current_bid_ask(symbol)
            if bid_ask and bid_ask.get('spread', 1000) <= 500:
                timing_score += 1
                reasons.append("스프레드양호")
        except Exception:
            pass

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
    
    def evaluate_sell_timing(self, df: pd.DataFrame, latest: pd.Series, 
                           current_price: float, symbol: str = None) -> Dict:
        """매도 타이밍 평가"""
        
        timing_score = 0
        reasons = []
        
        # 1. 분봉 추세 약화
        if latest['ma5'] < latest['ma20']:
            timing_score += 2
            reasons.append("분봉하락추세")
        
        # 2. 분봉 RSI
        minute_rsi = latest['rsi']
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
    
    def execute_hybrid_trade(self, symbol: str, positions: Dict) -> bool:
        """하이브리드 매매 실행"""
        
        # 1. 일봉 전략 분석
        daily_analysis = self.analyze_daily_strategy(symbol)
        
        if daily_analysis['signal'] == 'HOLD' or daily_analysis['strength'] < 3.0:
            return False
        
        # 2. 분봉 타이밍 분석
        timing_analysis = self.find_optimal_entry_timing(symbol, daily_analysis['signal'])
        
        if not timing_analysis['execute']:
            self.logger.info(f"⏰ {symbol} 타이밍 부적절: {timing_analysis.get('reason', '기준 미달')}")
            return False
        
        # 3. 실제 매매 실행
        current_price = timing_analysis['current_price']
        
        if daily_analysis['signal'] == 'BUY':
            return self.execute_smart_buy(symbol, daily_analysis, timing_analysis, current_price, positions)
        else:
            return self.execute_smart_sell(symbol, daily_analysis, timing_analysis, current_price, positions)
    
    def execute_smart_buy(self, symbol: str, daily_analysis: Dict, timing_analysis: Dict, 
                         current_price: float, positions: Dict) -> bool:
        """스마트 매수 실행"""
        
        # 매수 가능 여부 확인
        current_position = positions.get(symbol, {})
        current_quantity = current_position.get('quantity', 0)
        
        can_buy, reason = self.position_manager.can_purchase_symbol(symbol, current_quantity)
        if not can_buy:
            self.logger.info(f"🚫 {symbol} 매수 불가: {reason}")
            return False
        
        # 포지션 크기 계산
        quantity = self.order_manager.calculate_position_size(current_price, daily_analysis['strength'])
        
        if quantity <= 0:
            self.logger.warning(f"⚠️ {symbol} 매수 수량 0")
            return False
        
        # 분봉 기반 주문 전략 결정
        order_strategy = self.determine_order_strategy(timing_analysis)
        
        self.logger.info(f"💰 {symbol} 하이브리드 매수 실행:")
        self.logger.info(f"  일봉 신호: {daily_analysis['signal']} (강도: {daily_analysis['strength']:.2f})")
        self.logger.info(f"  일봉 사유: {', '.join(daily_analysis.get('reasons', []))}")
        self.logger.info(f"  분봉 타이밍: {timing_analysis['timing_score']}/5")
        self.logger.info(f"  분봉 사유: {', '.join(timing_analysis.get('reasons', []))}")
        self.logger.info(f"  수량: {quantity}주, 전략: {order_strategy}")
        
        # 주문 실행
        result = self.order_manager.place_order_with_strategy(symbol, 'BUY', quantity, order_strategy)
        
        if result['success']:
            executed_price = result.get('limit_price', current_price)
            self.position_manager.record_purchase(
                symbol, quantity, executed_price, "hybrid_strategy"
            )
            
            # 하이브리드 매수 알림
            self.notify_hybrid_trade(symbol, 'BUY', daily_analysis, timing_analysis, quantity, executed_price)
            
            return True
        
        return False
    
    def execute_smart_sell(self, symbol: str, daily_analysis: Dict, timing_analysis: Dict, 
                          current_price: float, positions: Dict) -> bool:
        """스마트 매도 실행"""
        
        current_position = positions.get(symbol, {})
        if not current_position or current_position.get('quantity', 0) <= 0:
            return False
        
        current_quantity = current_position.get('quantity', 0)
        can_sell, reason = self.position_manager.can_sell_symbol(symbol, current_quantity)
        if not can_sell:
            self.logger.info(f"🚫 {symbol} 매도 불가: {reason}")
            return False
        
        quantity = current_quantity
        order_strategy = "aggressive_limit"
        
        self.logger.info(f"💸 {symbol} 하이브리드 매도 실행:")
        self.logger.info(f"  일봉 신호: {daily_analysis['signal']} (강도: {daily_analysis['strength']:.2f})")
        self.logger.info(f"  분봉 타이밍: {timing_analysis['timing_score']}")
        
        result = self.order_manager.place_order_with_strategy(symbol, 'SELL', quantity, order_strategy)
        
        if result['success']:
            executed_price = result.get('limit_price', current_price)
            self.position_manager.record_sale(
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
        
        if not self.notifier or not hasattr(self.notifier, 'notify_on_trade') or not self.notifier.notify_on_trade:
            return
        
        action_emoji = "🛒" if action == "BUY" else "💸"
        
        title = f"{action_emoji} 하이브리드 {action}!"
        
        daily_reasons = ', '.join(daily_analysis.get('reasons', []))
        timing_reasons = ', '.join(timing_analysis.get('reasons', []))
        
        message = f"""
종목: {symbol}
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
        self.notifier.send_notification(title, message, color)
