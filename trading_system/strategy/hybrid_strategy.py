"""
하이브리드 전략 모듈 (일봉 분석 + 분봉 실행) - 종목명 로그 개선
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict
from .technical_indicators import TechnicalIndicators


class HybridStrategy:
    """일봉 전략 + 분봉 실행 하이브리드 시스템"""
    
    def __init__(self, api_client, order_manager, position_manager, notifier, logger, 
                       order_tracker=None, get_stock_name_func=None):
        self.api_client = api_client
        self.order_manager = order_manager
        self.position_manager = position_manager
        self.notifier = notifier
        self.logger = logger
        self.get_stock_name = get_stock_name_func or (lambda code: code)
        
        self.pending_signals = {}
        self.daily_analysis_cache = {}
        self.last_daily_analysis = {}

        self.order_tracker = order_tracker
        
    def evaluate_buy_timing(self, df: pd.DataFrame, latest: pd.Series, 
                           current_price: float, symbol: str = None) -> Dict:
        """
        개선된 매수 타이밍 평가 - 20일 평균선 기준으로 변경
        """
        timing_score = 0
        reasons = []
        stock_name = self.get_stock_name(symbol) if symbol else "Unknown"
        
        # 1. 개선된 고점 매수 방지 필터 (20일 평균선 기준)
        if len(df) >= 20:
            ma20 = df['stck_prpr'].rolling(20).mean().iloc[-1]
            #high_20 = df['stck_prpr'].rolling(20).max().iloc[-1]
            high_60 = df['stck_prpr'].rolling(60).max().iloc[-1]
            
            # 방법 A: 20일 평균선 기준 (추천)
            if current_price > ma20 * 1.05:  # 20일선 대비 5% 이상 위
                self.logger.info(f"❌ {stock_name} 평균선 상회 매수 위험: 현재가 {current_price:,} vs 20일선 {ma20:,}")
                return {
                    'execute': False,
                    'timing_score': 0,
                    'reasons': ['평균선상회위험'],
                    'current_price': current_price,
                    'ma20_ratio': current_price / ma20
                }
            
  
            # 방법 B: 60일 고점 기준으로 완화 (75%로 완화)
            price_position = current_price / high_60
            if price_position > 0.75:  # 85% → 75%로 완화, 60일 기준
                self.logger.info(f"❌ {stock_name} 고점 매수 위험: {price_position:.1%} (60일 기준)")
                return {
                    'execute': False,
                    'timing_score': 0,
                    'reasons': ['고점매수위험'],
                    'current_price': current_price,
                    'price_position': price_position
                }

        
        # 2. 과매수 상태 체크 (기존 유지)
        minute_rsi = latest.get('rsi', 50)
        if minute_rsi > 70:
            self.logger.info(f"❌ {stock_name} 과매수 상태: RSI {minute_rsi:.1f}")
            return {
                'execute': False,
                'timing_score': 0,
                'reasons': ['과매수상태'],
                'current_price': current_price,
                'minute_rsi': minute_rsi
            }
        
        # 3. 급등 직후 매수 금지 (기존 유지)
        if len(df) >= 5:
            price_change_5 = (current_price / df['stck_prpr'].iloc[-6] - 1) * 100
            if price_change_5 > 3:  # 5분봉 3% 이상 급등
                self.logger.info(f"❌ {stock_name} 급등 직후: {price_change_5:.1f}%")
                return {
                    'execute': False,
                    'timing_score': 0,
                    'reasons': ['급등직후'],
                    'current_price': current_price
                }
        
        # 4. 개선된 가격 위치 평가
        if len(df) >= 20:
            ma20 = df['stck_prpr'].rolling(20).mean().iloc[-1]
            ma20_ratio = current_price / ma20
            
            # 20일선 기준 점수
            if ma20_ratio <= 0.95:  # 20일선 5% 이하
                timing_score += 4
                reasons.append("평균선이하진입")
            elif ma20_ratio <= 0.98:  # 20일선 2% 이하
                timing_score += 3
                reasons.append("평균선근처")
            elif ma20_ratio <= 1.02:  # 20일선 2% 이내
                timing_score += 2
                reasons.append("평균선상하")
            else:
                timing_score += 1
                reasons.append("평균선상회")
        
        # 5. RSI 적정 수준 (기존 유지)
        if 30 <= minute_rsi <= 60:
            timing_score += 2
            reasons.append("RSI적정")
        elif minute_rsi < 30:
            timing_score += 3
            reasons.append("RSI과매도")
        
        # 6. 거래량 확인 (기존 유지)
        if len(df) >= 20:
            vol_avg = df['cntg_vol'].rolling(20).mean().iloc[-1]
            current_vol = df['cntg_vol'].iloc[-1]
            vol_ratio = current_vol / vol_avg if vol_avg > 0 else 1
            
            if vol_ratio > 5:
                timing_score -= 2
                reasons.append("거래량폭증위험")
            elif 1.5 <= vol_ratio <= 3:
                timing_score += 1
                reasons.append("거래량적정증가")
        
        # 실행 조건: 4점 이상
        execute = timing_score >= 4
        
        if execute:
            self.logger.info(f"✅ {stock_name} 매수 타이밍 적절: {timing_score}점")
        else:
            self.logger.info(f"⏰ {stock_name} 매수 타이밍 부적절: {timing_score}점")
        
        return {
            'execute': execute,
            'timing_score': timing_score,
            'reasons': reasons,
            'current_price': current_price,
            'minute_rsi': minute_rsi,
            'ma20_ratio': ma20_ratio if 'ma20_ratio' in locals() else 1.0
        }

    def analyze_daily_strategy(self, symbol: str) -> Dict:
        """
        개선된 일봉 전략 분석 - 조기 신호 중심
        """
        stock_name = self.get_stock_name(symbol)
        
        # 캐시 확인
        now = datetime.now()
        if symbol in self.last_daily_analysis:
            last_time = self.last_daily_analysis[symbol]
            if now - last_time < timedelta(hours=4):
                cached_result = self.daily_analysis_cache.get(symbol, {'signal': 'HOLD', 'strength': 0})
                return cached_result
        
        self.logger.info(f"📅 {stock_name}({symbol}) 개선된 일봉 분석 실행")
        
        # 일봉 데이터 조회 (더 긴 기간)
        df = self.api_client.get_daily_data(symbol, days=252)  # 1년
        
        if df.empty or len(df) < 100:
            self.logger.warning(f"⚠️ {stock_name}({symbol}) 일봉 데이터 부족: {len(df)}일")
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
        
        try:
            current_price = float(df['stck_prpr'].iloc[-1])
            
            # 기술 지표 계산
            df = self.calculate_daily_indicators(df)
            latest = df.iloc[-1]
            
            # 개선된 신호 생성
            signal_result = self.generate_daily_signal(df, latest, current_price)
            
            # 캐시 업데이트
            self.daily_analysis_cache[symbol] = signal_result
            self.last_daily_analysis[symbol] = now
            
            self.logger.info(f"📊 {stock_name}({symbol}) 개선된 분석 완료: {signal_result['signal']} "
                           f"(강도: {signal_result['strength']:.2f})")
            
            return signal_result
            
        except Exception as e:
            self.logger.error(f"❌ {stock_name}({symbol}) 개선된 분석 실패: {e}")
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
    
    

    def generate_daily_signal(self, df: pd.DataFrame, latest: pd.Series, current_price: float) -> Dict:
        """
        개선된 일봉 기반 신호 생성 - 가격 위치 우선
        """
        signal = 'HOLD'
        strength = 0
        reasons = []
        
        #다양한 기간 수익률 계산
        returns = {}
        for days in [5, 10, 20, 40, 60, 120]:
            if len(df) > days:
                past_price = df['stck_prpr'].iloc[-(days+1)]
                returns[f'{days}d'] = (current_price - past_price) / past_price
    
        # 추세 강도 계산
        trend_score = 0
        if returns.get('5d', 0) > 0.02:
            trend_score += 1
        if returns.get('10d', 0) > 0.05:
            trend_score += 1
        if returns.get('20d', 0) > 0.1:
            trend_score += 2
    
        # 매수 조건 평가
        buy_score = 0

        # 1. 가격 위치 체크 (최우선)
        high_52w = df['stck_prpr'].tail(252).max() if len(df) >= 252 else df['stck_prpr'].max()
        price_position_52w = current_price / high_52w
        
        # 52주 고점 90% 이상이면 매수 신호 차단
        if price_position_52w > 0.9:
            return {
                'signal': 'HOLD',
                'strength': 0,
                'current_price': current_price,
                'reasons': ['52주고점근처'],
                'price_position': price_position_52w
            }
        
        # 2. 매수 조건 평가 (가격 위치 우선)
        buy_score = 0
        
        # 가격 위치 점수 (가중치 높음)
        if price_position_52w <= 0.3:
            buy_score += 4.0
            reasons.append("52주저점권")
        elif price_position_52w <= 0.5:
            buy_score += 3.0
            reasons.append("52주중저점")
        elif price_position_52w <= 0.7:
            buy_score += 1.0
            reasons.append("52주중간권")
        
        # 추세 점수 (기존 로직 유지하되 가중치 축소)
        if trend_score >= 6:
            buy_score += 2.0
            reasons.append("강한상승추세")
        elif trend_score >= 4:
            buy_score += 1.5
            reasons.append("상승추세")
        elif trend_score >= 2:
            buy_score += 1.0
            reasons.append("약한상승추세")
        
        # MACD (가중치 축소)
        macd_analysis = TechnicalIndicators.detect_macd_golden_cross(df)
        if macd_analysis['golden_cross'] and macd_analysis['signal_age'] <= 10:
            buy_score += 1.5  # 기존 2.5 → 1.5
            reasons.append(f"MACD골든크로스({macd_analysis['signal_age']}일전)")
        
        # RSI
        rsi = latest['rsi']
        if 30 <= rsi <= 50:
            buy_score += 1.0
            reasons.append("RSI매수권")
        
        # 최종 신호 결정 (기준 상향)
        if buy_score >= 4.0:  # 기존 5.0 → 4.0이지만 가격위치 필터로 더 엄격
            signal = 'BUY'
            strength = min(buy_score, 5.0)
        
        # 매도 신호는 기존 로직 유지
        sell_score = 0
        if rsi > 75:
            sell_score += 2.0
        if current_price < latest['ma20']:
            sell_score += 2.0
        if returns.get('10d', 0) < -0.1:
            sell_score += 2.0
            reasons.append("급락추세")
        
        if sell_score >= 3.0:
            signal = 'SELL'
            strength = min(sell_score, 5.0)
        
        return {
            'signal': signal,
            'strength': strength,
            'current_price': current_price,
            'reasons': reasons,
            'trend_score': trend_score,
            'rsi': float(rsi),
            'buy_score': buy_score,
            'sell_score': sell_score,
            'price_position': price_position_52w
        }

    
    
    def analyze_price_position(self, df: pd.DataFrame, current_price: float) -> float:
        """
        고급 가격 위치 분석
        """
        score = 0
        
        # 52주 고저점 대비 위치
        high_52w = df['stck_prpr'].tail(252).max()
        low_52w = df['stck_prpr'].tail(252).min()
        
        if high_52w > low_52w:
            position_52w = (current_price - low_52w) / (high_52w - low_52w)
            
            if position_52w <= 0.2:      # 하위 20%
                score += 4
            elif position_52w <= 0.4:    # 하위 40%
                score += 3
            elif position_52w <= 0.6:    # 중간
                score += 1
            else:                        # 상위 40%
                score -= 1
        
        # 최근 조정 깊이
        high_20 = df['stck_prpr'].tail(20).max()
        correction = (high_20 - current_price) / high_20
        
        if 0.1 <= correction <= 0.3:    # 10-30% 조정
            score += 3
        elif 0.05 <= correction < 0.1:   # 5-10% 조정
            score += 2
        elif correction > 0.3:           # 30% 이상 조정
            score += 1
        
        # 지지선 근처 여부
        ma20 = df['stck_prpr'].rolling(20).mean().iloc[-1]
        ma60 = df['stck_prpr'].rolling(60).mean().iloc[-1]
        
        # 20일선 근처 (±3%)
        if abs(current_price - ma20) / ma20 <= 0.03:
            score += 1
        
        # 60일선 근처 (±5%)    
        if abs(current_price - ma60) / ma60 <= 0.05:
            score += 1
            
        return min(score, 5)
    
    
    def determine_order_strategy(self, timing_analysis: Dict) -> str:
        """
        개선된 주문 전략 결정
        """
        timing_score = timing_analysis['timing_score']
        price_position = timing_analysis.get('price_position', 1.0)
        minute_rsi = timing_analysis.get('minute_rsi', 50)
        
        # 저점권에서는 더 적극적으로
        if price_position <= 0.7 and minute_rsi < 40:
            return "aggressive_limit"
        elif timing_score >= 4:
            return "patient_limit"
        else:
            return "limit"

    
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
    
    def find_optimal_entry_timing(self, symbol: str, target_signal: str) -> Dict:
        """분봉 기반 최적 진입 타이밍 찾기"""
        stock_name = self.get_stock_name(symbol)
        
        self.logger.info(f"🎯 {stock_name}({symbol}) {target_signal} 최적 타이밍 분석")
        
        # 최근 4시간 분봉 데이터
        minute_df = self.api_client.get_minute_data(symbol, minutes=240)
        
        if minute_df.empty or len(minute_df) < 20:
            self.logger.warning(f"⚠️ {stock_name}({symbol}) 분봉 데이터 부족: {len(minute_df)}개")
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
                result = self.evaluate_buy_timing(minute_df, latest_minute, current_price, symbol)
            else:
                result = self.evaluate_sell_timing(minute_df, latest_minute, current_price, symbol)
            
            # 타이밍 결과 로그
            if result['execute']:
                self.logger.info(f"✅ {stock_name}({symbol}) 타이밍 적절: 점수 {result['timing_score']}/5 "
                               f"({', '.join(result.get('reasons', []))})")
            else:
                self.logger.info(f"⏰ {stock_name}({symbol}) 타이밍 부적절: 점수 {result.get('timing_score', 0)}/5")
            
            return result
                
        except Exception as e:
            self.logger.error(f"❌ {stock_name}({symbol}) 분봉 타이밍 분석 실패: {e}")
            return {'execute': False, 'reason': f'분석 오류: {str(e)}'}

    
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
        """
        간소화된 하이브리드 매매 실행 - trading_list.json에 이미 선별된 종목이므로 분봉 타이밍만 확인
        """
        stock_name = self.get_stock_name(symbol)
        
        # 🔥 재매수 금지 체크를 가장 먼저 실행
        current_position = positions.get(symbol, {})
        current_quantity = current_position.get('quantity', 0)
    
        total_holdings = len(positions)  # 전체 보유 종목 수
        can_buy, reason = self.position_manager.can_purchase_symbol(symbol, current_quantity, total_holdings)
        if not can_buy:
            self.logger.info(f"🚫 {stock_name}({symbol}) 매수 차단: {reason}")
            return False  # 여기서 바로 종료
    
        # trading_list.json에서 이미 선별된 종목이므로 일봉 분석 생략
        # 바로 분봉 타이밍 분석으로 진행
        self.logger.info(f"🎯 {stock_name}({symbol}) 분봉 타이밍 분석 (이미 선별된 종목)")
        
        # 분봉 타이밍 분석
        timing_analysis = self.find_optimal_entry_timing(symbol, 'BUY')
        
        if not timing_analysis['execute']:
            reason = timing_analysis.get('reason', '기준 미달')
            self.logger.info(f"⏰ {stock_name}({symbol}) 타이밍 부적절: {reason}")
            return False
        
        # 실제 매수 실행
        current_price = timing_analysis['current_price']
        return self.execute_smart_buy(symbol, timing_analysis, current_price, positions)
    
    
    def execute_smart_buy(self, symbol: str, timing_analysis: Dict, 
                                    current_price: float, positions: Dict) -> bool:
        """
        간소화된 스마트 매수 실행 - 일봉 분석 없이 분봉 타이밍만으로 매수
        """
        stock_name = self.get_stock_name(symbol)

        # 전체 보유 종목 수 확인
        total_holdings = len(positions)

        # 매수 가능 여부 확인
        current_position = positions.get(symbol, {})
        current_quantity = current_position.get('quantity', 0)
        
        can_buy, reason = self.position_manager.can_purchase_symbol(symbol, current_quantity, total_holdings)
        if not can_buy:
            self.logger.info(f"🚫 {stock_name}({symbol}) 매수 불가: {reason}")
            return False
        
        # 기본 리스크 체크 (시장 상황, 급락 등)
        basic_risk_check = self.perform_basic_risk_check(symbol, current_price)
        if not basic_risk_check['approved']:
            self.logger.warning(f"⚠️ {stock_name}({symbol}) 기본 리스크 체크 실패: {basic_risk_check['reason']}")
            return False
        
        # 변동성 계산
        volatility = self.calculate_volatility(symbol)
        
        # 포지션 크기 계산 (일봉 강도 대신 분봉 점수 사용)
        price_position = timing_analysis.get('price_position', 0.5)
        timing_score = timing_analysis.get('timing_score', 3)
        
        quantity = self.order_manager.calculate_position_size(
            current_price, timing_score, price_position, volatility, symbol
        )
        
        if quantity <= 0:
            self.logger.warning(f"⚠️ {stock_name}({symbol}) 매수 수량 0")
            return False
        
        # 주문 전략 결정
        order_strategy = self.determine_order_strategy(timing_analysis)
        
        # 상세 로그
        self.logger.info(f"💰 {stock_name}({symbol}) 간소화된 매수 실행:")
        self.logger.info(f"  분봉 점수: {timing_score}/5")
        self.logger.info(f"  가격위치: {price_position:.2%}")
        self.logger.info(f"  변동성: {volatility:.2%}")
        self.logger.info(f"  수량: {quantity}주, 전략: {order_strategy}")
        
        # 주문 실행
        result = self.order_manager.place_order_with_tracking(
            symbol, 'BUY', quantity, order_strategy, self.order_tracker
        )
        
        if result['success']:
            order_no = result.get('order_no', 'Unknown')
            executed_price = result.get('limit_price', current_price)
            
            # 시장가 주문인 경우 즉시 포지션에 기록
            if executed_price == 0:
                executed_price = current_price
                self.position_manager.record_purchase(symbol, quantity, executed_price, "timing_strategy")
            
            # 강제 알림 전송
            if self.notifier and self.notifier.webhook_url:
                self.notifier.notify_trade_success('BUY', symbol, quantity, executed_price, order_no, stock_name)
            
            # 간소화된 매매 알림
            self.notify_trade(symbol, 'BUY', timing_analysis, quantity, executed_price)
            
            return True
        else:
            error_msg = result.get('error', 'Unknown error')
            
            # 실패 알림
            if self.notifier and self.notifier.webhook_url:
                self.notifier.notify_trade_failure('BUY', symbol, error_msg, stock_name)
            
            return False
    
    
    def perform_basic_risk_check(self, symbol: str, current_price: float) -> Dict:
        """
        기본 리스크 체크 (일봉 분석 없이 기본적인 위험 요소만 확인)
        """
        risks = []
        
        try:
            # 1. 시장 급락 체크
            market_risk = self.check_market_conditions()
            if market_risk['risk_level'] > 3:
                risks.append(f"시장리스크: {market_risk['reason']}")
            
            # 2. 개별 종목 급락 체크 (간단한 버전)
            minute_df = self.api_client.get_minute_data(symbol, minutes=60)
            if not minute_df.empty and len(minute_df) >= 10:
                # 1시간 내 급락 체크
                hour_ago_price = minute_df['stck_prpr'].iloc[0]
                hour_change = (current_price - hour_ago_price) / hour_ago_price
                
                if hour_change < -0.05:  # 1시간 내 5% 급락
                    risks.append(f"급락위험: {hour_change:.1%}")
            
            approved = len(risks) == 0
            
            return {
                'approved': approved,
                'reason': '; '.join(risks) if risks else '기본 리스크 체크 통과'
            }
            
        except Exception as e:
            return {
                'approved': False,
                'reason': f'리스크 체크 오류: {e}'
            }
    
    
    def notify_trade(self, symbol: str, action: str, timing_analysis: Dict, 
                               quantity: int, price: float):
        """
        간소화된 매매 알림
        """
        if not self.notifier:
            return
        
        stock_name = self.get_stock_name(symbol)
        action_emoji = "🛒" if action == "BUY" else "💸"
        
        title = f"{action_emoji} 타이밍 매수!"
        
        # 위험도 표시
        price_position = timing_analysis.get('price_position', 0.5)
        risk_level = "🟢 저위험" if price_position <= 0.4 else "🟡 중위험" if price_position <= 0.7 else "🔴 고위험"
        
        message = f"""
    종목: {stock_name}({symbol})
    수량: {quantity}주 @ {price:,}원
    총액: {quantity * price:,}원
    
    📊 분석 결과:
    위험도: {risk_level}
    가격위치: {price_position:.1%} (20일고점 대비)
    
    ⏰ 분봉 타이밍:
    점수: {timing_analysis['timing_score']}/5
    근거: {', '.join(timing_analysis.get('reasons', []))}
    RSI: {timing_analysis.get('minute_rsi', 0):.1f}
    
    💡 이미 일봉으로 선별된 우량 종목
    
    시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
        
        color = 0x00ff00 if action == "BUY" else 0xff6600
        self.notifier.send_notification(title, message, color)
    
    def perform_risk_check(self, symbol: str, daily_analysis: Dict, timing_analysis: Dict, 
                          current_price: float) -> Dict:
        """
        종합적인 리스크 체크
        """
        # 1. 시장 상황 체크
        market_risk = self.check_market_conditions()
        
        # 2. 개별 종목 리스크
        stock_risk = self.check_individual_stock_risk(symbol, current_price)
        
        # 3. 포트폴리오 리스크
        portfolio_risk = self.check_portfolio_risk()
        
        # 4. 타이밍 리스크
        timing_risk = self.check_timing_risk(timing_analysis)
        
        risks = []
        
        if market_risk['risk_level'] > 3:
            risks.append(f"시장리스크: {market_risk['reason']}")
        
        if stock_risk['risk_level'] > 3:
            risks.append(f"종목리스크: {stock_risk['reason']}")
            
        if portfolio_risk['risk_level'] > 3:
            risks.append(f"포트폴리오리스크: {portfolio_risk['reason']}")
            
        if timing_risk['risk_level'] > 3:
            risks.append(f"타이밍리스크: {timing_risk['reason']}")
        
        approved = len(risks) == 0
        
        return {
            'approved': approved,
            'reason': '; '.join(risks) if risks else '리스크 체크 통과',
            'risk_count': len(risks)
        }
    
    
    def check_individual_stock_risk(self, symbol: str, current_price: float) -> Dict:
        """
        개별 종목 리스크 체크
        """
        risk_level = 0
        reason = ""
        
        try:
            # 최근 가격 변동성 체크
            df = self.api_client.get_daily_data(symbol, days=30)
            if not df.empty:
                # 30일 최대 일일 변동폭
                daily_changes = df['stck_prpr'].pct_change().abs()
                max_daily_change = daily_changes.max()
                avg_daily_change = daily_changes.mean()
                
                if max_daily_change > 0.15:  # 15% 이상 일일 변동
                    risk_level += 2
                    reason += f"고변동성(최대{max_daily_change:.1%}); "
                    
                if avg_daily_change > 0.05:  # 평균 5% 이상 변동
                    risk_level += 1
                    reason += f"높은평균변동성({avg_daily_change:.1%}); "
                
                # 연속 상승/하락 체크
                recent_changes = df['stck_prpr'].pct_change().tail(5)
                consecutive_up = sum(1 for x in recent_changes if x > 0.03)  # 3% 이상 상승
                
                if consecutive_up >= 4:  # 5일 중 4일 이상 3%+ 상승
                    risk_level += 2
                    reason += "연속급등위험; "
            
            # 현재가 vs 최근 고점
            if len(df) >= 20:
                recent_high = df['stck_prpr'].tail(20).max()
                if current_price > recent_high * 0.98:  # 최근 고점 98% 이상
                    risk_level += 1
                    reason += "고점근처; "
        
        except Exception as e:
            risk_level = 1
            reason = f"데이터조회실패: {e}"
        
        return {
            'risk_level': risk_level,
            'reason': reason.rstrip('; ') or '정상'
        }
    
    
    def check_market_conditions(self) -> Dict:
        """
        시장 상황 체크 - KOSPI/KOSDAQ 급락 시 매수 금지
        """
        risk_level = 0
        reason = ""
        
        try:
            # KOSPI 체크
            kospi_data = self.api_client.get_daily_data('000001', days=5)  # KOSPI 지수
            if not kospi_data.empty:
                kospi_change = kospi_data['stck_prpr'].pct_change().iloc[-1]
                
                if kospi_change < -0.03:  # 3% 이상 하락
                    risk_level += 2
                    reason += f"KOSPI급락({kospi_change:.1%}); "
                elif kospi_change < -0.015:  # 1.5% 이상 하락
                    risk_level += 1
                    reason += f"KOSPI하락({kospi_change:.1%}); "
            
            # 추가로 VIX나 다른 공포지수가 있다면 체크
            
        except Exception:
            risk_level = 0
            reason = "시장데이터없음"
        
        return {
            'risk_level': risk_level,
            'reason': reason.rstrip('; ') or '시장상황양호'
        }
    
    
    def calculate_volatility(self, symbol: str) -> float:
        """
        종목별 변동성 계산 (20일 기준)
        """
        try:
            df = self.api_client.get_daily_data(symbol, days=30)
            if df.empty or len(df) < 20:
                return 0.04  # 기본값 4%
            
            # 20일 일간 수익률의 표준편차
            daily_returns = df['stck_prpr'].pct_change().dropna()
            volatility = daily_returns.tail(20).std()
            
            return volatility if not pd.isna(volatility) else 0.04
            
        except Exception:
            return 0.04
    
    
    def notify_improved_trade(self, symbol: str, action: str, daily_analysis: Dict, 
                             timing_analysis: Dict, quantity: int, price: float):
        """
        개선된 매매 알림
        """
        if not self.notifier:
            return
        
        stock_name = self.get_stock_name(symbol)
        action_emoji = "🛒" if action == "BUY" else "💸"
        
        title = f"{action_emoji} 개선된 하이브리드 {action}!"
        
        # 위험도 표시
        price_position = timing_analysis.get('price_position', 0.5)
        risk_level = "🟢 저위험" if price_position <= 0.4 else "🟡 중위험" if price_position <= 0.7 else "🔴 고위험"
        
        message = f"""
    종목: {stock_name}({symbol})
    수량: {quantity}주 @ {price:,}원
    총액: {quantity * price:,}원
    
    📊 분석 결과:
    위험도: {risk_level}
    가격위치: {price_position:.1%} (20일고점 대비)
    
    📅 일봉 분석:
    신호: {daily_analysis['signal']} (강도: {daily_analysis['strength']:.1f})
    근거: {', '.join(daily_analysis.get('reasons', []))}
    
    ⏰ 분봉 타이밍:
    점수: {timing_analysis['timing_score']}/5
    근거: {', '.join(timing_analysis.get('reasons', []))}
    RSI: {timing_analysis.get('minute_rsi', 0):.1f}
    
    시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
        
        color = 0x00ff00 if action == "BUY" else 0xff6600
        self.notifier.send_notification(title, message, color)
    
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
        
        #result = self.order_manager.place_order_with_strategy(symbol, 'SELL', quantity, order_strategy)
        result = self.order_manager.place_order_with_tracking(
            symbol, 'SELL', quantity, order_strategy, self.order_tracker
        )

        if result['success']:
            limit_price = result.get('limit_price', 0)
        
            if limit_price > 0:
                # 지정가 주문 - 추적기가 체결 시 포지션에 자동 기록
                self.logger.info(f"⏳ {symbol}({stock_name}) 지정가 매도 주문 접수됨, 체결 대기 중")
            else:
                # 시장가 주문 - 즉시 포지션에 기록
                executed_price = result.get('limit_price', current_price)
                self.position_manager.record_sale(
                    symbol, quantity, executed_price, "hybrid_strategy"
                )
        
            self.notify_hybrid_trade(symbol, 'SELL', daily_analysis, timing_analysis, quantity, executed_price)
            
            return True
        
        return False
    
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


    def calculate_future_potential(self, symbol: str) -> Dict:
        """
        종목별 미래 상승 가능성 점수화 (0~100점)
        포트폴리오 최적화를 위한 종합 평가 시스템
        """
        try:
            stock_name = self.get_stock_name(symbol)
            self.logger.info(f"🎯 {stock_name}({symbol}) 미래 상승 가능성 분석 시작")
            
            # 초기화
            total_score = 0
            score_details = {}
            reasons = []
            
            # 1. 기술적 분석 점수 (30점 만점)
            tech_score = self._calculate_technical_score(symbol)
            total_score += tech_score['score']
            score_details['technical'] = tech_score
            reasons.extend(tech_score['reasons'])
            
            # 2. 가격 위치 점수 (25점 만점)
            price_score = self._calculate_price_position_score(symbol)
            total_score += price_score['score']
            score_details['price_position'] = price_score
            reasons.extend(price_score['reasons'])
            
            # 3. 모멘텀 점수 (20점 만점)
            momentum_score = self._calculate_momentum_score(symbol)
            total_score += momentum_score['score']
            score_details['momentum'] = momentum_score
            reasons.extend(momentum_score['reasons'])
            
            # 4. 거래량 분석 점수 (15점 만점)
            volume_score = self._calculate_volume_score(symbol)
            total_score += volume_score['score']
            score_details['volume'] = volume_score
            reasons.extend(volume_score['reasons'])
            
            # 5. 시장 환경 점수 (10점 만점)
            market_score = self._calculate_market_environment_score(symbol)
            total_score += market_score['score']
            score_details['market'] = market_score
            reasons.extend(market_score['reasons'])
            
            # 최종 점수 조정 (0~100 범위)
            final_score = min(max(total_score, 0), 100)
            
            # 등급 분류
            if final_score >= 80:
                grade = "A+ (매우높음)"
            elif final_score >= 70:
                grade = "A (높음)"
            elif final_score >= 60:
                grade = "B (보통)"
            elif final_score >= 40:
                grade = "C (낮음)"
            else:
                grade = "D (매우낮음)"
            
            self.logger.info(f"📊 {stock_name}({symbol}) 미래 상승 가능성: {final_score:.1f}점 ({grade})")
            
            return {
                'symbol': symbol,
                'stock_name': stock_name,
                'total_score': final_score,
                'grade': grade,
                'score_breakdown': score_details,
                'top_reasons': reasons[:5],  # 상위 5개 이유만
                'recommendation': self._get_recommendation(final_score),
                'analysis_time': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"미래 상승 가능성 분석 오류 ({symbol}): {e}")
            return {
                'symbol': symbol,
                'total_score': 50,  # 기본값
                'grade': "B (분석실패)",
                'error': str(e)
            }
    
    
    def _calculate_technical_score(self, symbol: str) -> Dict:
        """기술적 분석 점수 (30점 만점)"""
        score = 0
        reasons = []
        
        try:
            # 일봉 데이터 조회
            daily_df = self.api_client.get_daily_data(symbol, days=120)
            if daily_df.empty:
                return {'score': 15, 'reasons': ['데이터부족']}
            
            # 기술적 지표 계산
            daily_df = self.hybrid_strategy.calculate_daily_indicators(daily_df)
            latest = daily_df.iloc[-1]
            current_price = latest['stck_prpr']
            
            # 1) RSI 점수 (8점)
            rsi = latest['rsi']
            if 30 <= rsi <= 50:  # 매수 적정권
                score += 8
                reasons.append(f"RSI매수권({rsi:.1f})")
            elif 50 < rsi <= 65:  # 상승 중
                score += 6
                reasons.append(f"RSI상승권({rsi:.1f})")
            elif rsi < 30:  # 과매도
                score += 5
                reasons.append(f"RSI과매도({rsi:.1f})")
            elif rsi > 75:  # 과매수
                score += 1
                reasons.append(f"RSI과매수({rsi:.1f})")
            else:
                score += 3
            
            # 2) MACD 점수 (8점)
            macd_analysis = TechnicalIndicators.detect_macd_golden_cross(daily_df)
            if macd_analysis['golden_cross']:
                if macd_analysis['signal_age'] <= 5:  # 최근 골든크로스
                    score += 8
                    reasons.append(f"MACD최근골든크로스({macd_analysis['signal_age']}일)")
                elif macd_analysis['signal_age'] <= 15:
                    score += 6
                    reasons.append(f"MACD골든크로스({macd_analysis['signal_age']}일)")
                else:
                    score += 3
            elif latest['macd_line'] > latest['macd_signal']:  # 위에 있음
                score += 4
                reasons.append("MACD상승권")
            else:
                score += 1
            
            # 3) 이동평균 정배열 점수 (7점)
            ma_score = 0
            if current_price > latest['ma5']:
                ma_score += 1
            if current_price > latest['ma20']:
                ma_score += 2
            if current_price > latest['ma60']:
                ma_score += 2
            if latest['ma5'] > latest['ma20'] > latest['ma60']:  # 정배열
                ma_score += 2
                reasons.append("이동평균정배열")
            
            score += ma_score
            
            # 4) 볼린저밴드 점수 (7점)
            if 'bb_lower' in daily_df.columns and 'bb_upper' in daily_df.columns:
                bb_position = (current_price - latest['bb_lower']) / (latest['bb_upper'] - latest['bb_lower'])
                if 0.1 <= bb_position <= 0.4:  # 하단 근처
                    score += 7
                    reasons.append("볼밴하단진입")
                elif 0.4 < bb_position <= 0.7:  # 중간
                    score += 5
                    reasons.append("볼밴중간권")
                elif bb_position > 0.9:  # 상단
                    score += 2
                    reasons.append("볼밴상단권")
                else:
                    score += 4
            
            return {'score': score, 'reasons': reasons}
            
        except Exception as e:
            return {'score': 15, 'reasons': [f'기술적분석오류: {e}']}
    
    
    def _calculate_price_position_score(self, symbol: str) -> Dict:
        """가격 위치 점수 (25점 만점)"""
        score = 0
        reasons = []
        
        try:
            daily_df = self.api_client.get_daily_data(symbol, days=252)  # 1년
            if daily_df.empty:
                return {'score': 12, 'reasons': ['데이터부족']}
            
            current_price = daily_df['stck_prpr'].iloc[-1]
            
            # 1) 52주 고저점 대비 위치 (12점)
            high_52w = daily_df['stck_prpr'].max()
            low_52w = daily_df['stck_prpr'].min()
            
            if high_52w > low_52w:
                position_52w = (current_price - low_52w) / (high_52w - low_52w)
                
                if position_52w <= 0.2:  # 하위 20%
                    score += 12
                    reasons.append(f"52주저점권({position_52w:.1%})")
                elif position_52w <= 0.4:  # 하위 40%
                    score += 10
                    reasons.append(f"52주중저점({position_52w:.1%})")
                elif position_52w <= 0.6:  # 중간
                    score += 6
                    reasons.append(f"52주중간권({position_52w:.1%})")
                elif position_52w <= 0.8:  # 상위 40%
                    score += 3
                    reasons.append(f"52주중고점({position_52w:.1%})")
                else:  # 상위 20%
                    score += 1
                    reasons.append(f"52주고점권({position_52w:.1%})")
            
            # 2) 최근 조정 깊이 (8점)
            if len(daily_df) >= 20:
                high_20 = daily_df['stck_prpr'].tail(20).max()
                correction = (high_20 - current_price) / high_20
                
                if 0.1 <= correction <= 0.25:  # 10-25% 조정
                    score += 8
                    reasons.append(f"적정조정({correction:.1%})")
                elif 0.05 <= correction < 0.1:  # 5-10% 조정
                    score += 6
                    reasons.append(f"소폭조정({correction:.1%})")
                elif correction > 0.3:  # 30% 이상 조정
                    score += 5
                    reasons.append(f"대폭조정({correction:.1%})")
                elif correction < 0.02:  # 고점 근처
                    score += 2
                    reasons.append("고점근처")
                else:
                    score += 4
            
            # 3) 지지선 근처 여부 (5점)
            if len(daily_df) >= 60:
                ma20 = daily_df['stck_prpr'].rolling(20).mean().iloc[-1]
                ma60 = daily_df['stck_prpr'].rolling(60).mean().iloc[-1]
                
                # 20일선 근처 (±3%)
                if abs(current_price - ma20) / ma20 <= 0.03:
                    score += 3
                    reasons.append("20일선지지")
                
                # 60일선 근처 (±5%)
                if abs(current_price - ma60) / ma60 <= 0.05:
                    score += 2
                    reasons.append("60일선지지")
            
            return {'score': score, 'reasons': reasons}
            
        except Exception as e:
            return {'score': 12, 'reasons': [f'가격위치분석오류: {e}']}
    
    
    def _calculate_momentum_score(self, symbol: str) -> Dict:
        """모멘텀 점수 (20점 만점)"""
        score = 0
        reasons = []
        
        try:
            daily_df = self.api_client.get_daily_data(symbol, days=60)
            if daily_df.empty or len(daily_df) < 10:
                return {'score': 10, 'reasons': ['데이터부족']}
            
            current_price = daily_df['stck_prpr'].iloc[-1]
            
            # 1) 단기 모멘텀 (10점)
            short_returns = {}
            for days in [3, 5, 10]:
                if len(daily_df) > days:
                    past_price = daily_df['stck_prpr'].iloc[-(days+1)]
                    return_pct = (current_price - past_price) / past_price * 100
                    short_returns[f'{days}d'] = return_pct
            
            # 3일 수익률
            if short_returns.get('3d', 0) > 2:
                score += 4
                reasons.append(f"3일급등({short_returns['3d']:.1f}%)")
            elif short_returns.get('3d', 0) > 0:
                score += 3
                reasons.append(f"3일상승({short_returns['3d']:.1f}%)")
            elif short_returns.get('3d', 0) > -3:
                score += 2
            else:
                score += 1
            
            # 5일 수익률
            if short_returns.get('5d', 0) > 5:
                score += 3
                reasons.append(f"5일강세({short_returns['5d']:.1f}%)")
            elif short_returns.get('5d', 0) > 0:
                score += 2
            elif short_returns.get('5d', 0) > -5:
                score += 1
            
            # 10일 수익률
            if short_returns.get('10d', 0) > 10:
                score += 3
                reasons.append(f"10일강세({short_returns['10d']:.1f}%)")
            elif short_returns.get('10d', 0) > 0:
                score += 2
            elif short_returns.get('10d', 0) > -10:
                score += 1
            
            # 2) 연속 상승일 체크 (5점)
            recent_changes = daily_df['stck_prpr'].pct_change().tail(10)
            consecutive_up = 0
            for change in reversed(recent_changes.tolist()):
                if change > 0:
                    consecutive_up += 1
                else:
                    break
            
            if consecutive_up >= 3:
                score += 5
                reasons.append(f"연속상승({consecutive_up}일)")
            elif consecutive_up >= 2:
                score += 3
            elif consecutive_up >= 1:
                score += 2
            else:
                score += 1
            
            # 3) 변동성 안정성 (5점)
            if len(daily_df) >= 20:
                volatility = daily_df['stck_prpr'].pct_change().tail(20).std()
                if volatility < 0.02:  # 2% 미만
                    score += 5
                    reasons.append("변동성안정")
                elif volatility < 0.03:  # 3% 미만
                    score += 4
                elif volatility < 0.05:  # 5% 미만
                    score += 3
                else:
                    score += 1
                    reasons.append("변동성높음")
            
            return {'score': score, 'reasons': reasons}
            
        except Exception as e:
            return {'score': 10, 'reasons': [f'모멘텀분석오류: {e}']}
    
    
    def _calculate_volume_score(self, symbol: str) -> Dict:
        """거래량 분석 점수 (15점 만점)"""
        score = 0
        reasons = []
        
        try:
            # 일봉 거래량 분석
            daily_df = self.api_client.get_daily_data(symbol, days=30)
            if daily_df.empty or len(daily_df) < 10:
                return {'score': 7, 'reasons': ['거래량데이터부족']}
            
            current_volume = daily_df['cntg_vol'].iloc[-1]
            avg_volume_20 = daily_df['cntg_vol'].tail(20).mean()
            
            # 1) 거래량 증가율 (8점)
            volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 1
            
            if volume_ratio >= 2.0:  # 2배 이상
                score += 8
                reasons.append(f"거래량폭증({volume_ratio:.1f}배)")
            elif volume_ratio >= 1.5:  # 1.5배 이상
                score += 6
                reasons.append(f"거래량증가({volume_ratio:.1f}배)")
            elif volume_ratio >= 1.2:  # 1.2배 이상
                score += 4
                reasons.append(f"거래량늘어남({volume_ratio:.1f}배)")
            elif volume_ratio >= 0.8:  # 평균 수준
                score += 3
            else:  # 거래량 감소
                score += 1
                reasons.append("거래량부진")
            
            # 2) 분봉 거래량 확인 (7점)
            minute_df = self.api_client.get_minute_data(symbol, minutes=60)
            if not minute_df.empty and len(minute_df) >= 20:
                recent_vol = minute_df['cntg_vol'].tail(10).mean()
                past_vol = minute_df['cntg_vol'].head(10).mean()
                
                if recent_vol > past_vol * 1.5:  # 최근 거래량 50% 증가
                    score += 7
                    reasons.append("분봉거래량급증")
                elif recent_vol > past_vol * 1.2:
                    score += 5
                    reasons.append("분봉거래량증가")
                elif recent_vol > past_vol:
                    score += 3
                else:
                    score += 1
            
            return {'score': score, 'reasons': reasons}
            
        except Exception as e:
            return {'score': 7, 'reasons': [f'거래량분석오류: {e}']}
    
    
    def _calculate_market_environment_score(self, symbol: str) -> Dict:
        """시장 환경 점수 (10점 만점)"""
        score = 0
        reasons = []
        
        try:
            # 1) KOSPI/KOSDAQ 동조성 (6점)
            kospi_data = self.api_client.get_daily_data('000001', days=5)  # KOSPI
            if not kospi_data.empty and len(kospi_data) >= 2:
                kospi_change = (kospi_data['stck_prpr'].iloc[-1] / kospi_data['stck_prpr'].iloc[-2] - 1) * 100
                
                if kospi_change > 1.0:  # 1% 이상 상승
                    score += 6
                    reasons.append(f"시장강세({kospi_change:.1f}%)")
                elif kospi_change > 0.5:  # 0.5% 이상 상승
                    score += 4
                    reasons.append(f"시장상승({kospi_change:.1f}%)")
                elif kospi_change > -0.5:  # 보합권
                    score += 3
                elif kospi_change > -1.0:  # 소폭 하락
                    score += 2
                else:  # 1% 이상 하락
                    score += 1
                    reasons.append(f"시장약세({kospi_change:.1f}%)")
            
            # 2) 섹터 분석 (4점) - 단순화
            # 실제로는 동일 섹터 종목들과 비교해야 하지만, 
            # 여기서는 개별 종목의 상대적 강도로 대체
            daily_df = self.api_client.get_daily_data(symbol, days=5)
            if not daily_df.empty and len(daily_df) >= 2:
                stock_change = (daily_df['stck_prpr'].iloc[-1] / daily_df['stck_prpr'].iloc[-2] - 1) * 100
                
                # 시장 대비 상대 강도
                if not kospi_data.empty:
                    relative_strength = stock_change - kospi_change
                    if relative_strength > 2:  # 시장 대비 2%p 이상 강세
                        score += 4
                        reasons.append(f"시장대비강세({relative_strength:+.1f}%p)")
                    elif relative_strength > 0:  # 시장 대비 우위
                        score += 3
                    elif relative_strength > -2:  # 시장과 비슷
                        score += 2
                    else:  # 시장 대비 약세
                        score += 1
            
            return {'score': score, 'reasons': reasons}
            
        except Exception as e:
            return {'score': 5, 'reasons': [f'시장환경분석오류: {e}']}
    
    
    def _get_recommendation(self, score: float) -> str:
        """점수별 추천 의견"""
        if score >= 80:
            return "적극 보유 추천 - 높은 상승 가능성"
        elif score >= 70:
            return "보유 추천 - 상승 가능성 양호"
        elif score >= 60:
            return "보유 유지 - 보통 수준"
        elif score >= 40:
            return "매도 검토 - 상승 가능성 제한적"
        else:
            return "적극 매도 검토 - 낮은 상승 가능성"
    
    
