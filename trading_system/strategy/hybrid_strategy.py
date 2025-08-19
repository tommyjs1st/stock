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
        개선된 매수 타이밍 평가 - 고점 매수 방지
        """
        timing_score = 0
        reasons = []
        stock_name = self.get_stock_name(symbol) if symbol else "Unknown"
        
        # 1. 고점 매수 방지 필터 (가장 중요)
        if len(df) >= 20:
            high_20 = df['stck_prpr'].rolling(20).max().iloc[-1]
            price_position = current_price / high_20
            
            if price_position > 0.95:  # 20일 고점 95% 이상
                self.logger.info(f"❌ {stock_name} 고점 매수 위험: {price_position:.1%}")
                return {
                    'execute': False,
                    'timing_score': 0,
                    'reasons': ['고점매수위험'],
                    'current_price': current_price,
                    'price_position': price_position
                }
        
        # 2. 과매수 상태 체크
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
        
        # 3. 급등 직후 매수 금지
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
        
        # 4. 적절한 가격 위치에서 가점
        if 'price_position' in locals():
            if price_position <= 0.7:  # 20일 고점 대비 70% 이하
                timing_score += 3
                reasons.append("저점권진입")
            elif price_position <= 0.85:
                timing_score += 2
                reasons.append("적정가격대")
        
        # 5. RSI 적정 수준
        if 30 <= minute_rsi <= 60:
            timing_score += 2
            reasons.append("RSI적정")
        elif minute_rsi < 30:
            timing_score += 3
            reasons.append("RSI과매도")
        
        # 6. 거래량 확인
        if len(df) >= 20:
            vol_avg = df['cntg_vol'].rolling(20).mean().iloc[-1]
            current_vol = df['cntg_vol'].iloc[-1]
            vol_ratio = current_vol / vol_avg if vol_avg > 0 else 1
            
            if vol_ratio > 5:  # 5배 이상 거래량 폭증은 위험
                timing_score -= 2
                reasons.append("거래량폭증위험")
            elif 1.5 <= vol_ratio <= 3:  # 적정 거래량 증가
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
            'price_position': price_position if 'price_position' in locals() else 1.0
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
        개선된 하이브리드 매매 실행
        """
        stock_name = self.get_stock_name(symbol)
        
        # 1. 일봉 전략 분석
        daily_analysis = self.analyze_daily_strategy(symbol)
        
        # 매수 신호 강도 기준 상향 조정
        if daily_analysis['signal'] == 'HOLD' or daily_analysis['strength'] < 3.0:  
            self.logger.debug(f"📊 {stock_name}({symbol}) 일봉 신호 미충족: {daily_analysis['signal']} "
                            f"(강도: {daily_analysis['strength']:.2f})")
            return False
        
        # 2. 분봉 타이밍 분석
        timing_analysis = self.find_optimal_entry_timing(symbol, daily_analysis['signal'])
        
        if not timing_analysis['execute']:
            reason = timing_analysis.get('reason', '기준 미달')
            self.logger.info(f"⏰ {stock_name}({symbol}) 타이밍 부적절: {reason}")
            return False
        
        # 3. 실제 매매 실행
        current_price = timing_analysis['current_price']
        
        if daily_analysis['signal'] == 'BUY':
            return self.execute_smart_buy(symbol, daily_analysis, timing_analysis, current_price, positions)
        else:
            return self.execute_smart_sell(symbol, daily_analysis, timing_analysis, current_price, positions)

    
    def execute_smart_buy(self, symbol: str, daily_analysis: Dict, timing_analysis: Dict, 
                                  current_price: float, positions: Dict) -> bool:
        """
        개선된 스마트 매수 실행
        """
        stock_name = self.get_stock_name(symbol)
        
        # 매수 가능 여부 확인
        current_position = positions.get(symbol, {})
        current_quantity = current_position.get('quantity', 0)
        
        can_buy, reason = self.position_manager.can_purchase_symbol(symbol, current_quantity)
        if not can_buy:
            self.logger.info(f"🚫 {stock_name}({symbol}) 매수 불가: {reason}")
            return False
        
        # 추가 리스크 체크
        risk_check = self.perform_risk_check(symbol, daily_analysis, timing_analysis, current_price)
        if not risk_check['approved']:
            self.logger.warning(f"⚠️ {stock_name}({symbol}) 리스크 체크 실패: {risk_check['reason']}")
            return False
        
        # 변동성 계산
        volatility = self.calculate_volatility(symbol)
        
        # 개선된 포지션 크기 계산
        price_position = timing_analysis.get('price_position', 0.5)
        quantity = self.order_manager.calculate_position_size_improved(
            current_price, daily_analysis['strength'], price_position, volatility, symbol
        )
        
        if quantity <= 0:
            self.logger.warning(f"⚠️ {stock_name}({symbol}) 매수 수량 0")
            return False
        
        # 주문 전략 결정
        order_strategy = self.determine_order_strategy_improved(timing_analysis)
        
        # 상세 로그
        self.logger.info(f"💰 {stock_name}({symbol}) 개선된 매수 실행:")
        self.logger.info(f"  일봉: {daily_analysis['signal']} (강도: {daily_analysis['strength']:.2f})")
        self.logger.info(f"  분봉: 타이밍 {timing_analysis['timing_score']}/5")
        self.logger.info(f"  가격위치: {price_position:.2%} (20일고점 대비)")
        self.logger.info(f"  변동성: {volatility:.2%}")
        self.logger.info(f"  수량: {quantity}주, 전략: {order_strategy}")
        
        # 주문 실행
        result = self.order_manager.place_order_with_tracking(
            symbol, 'BUY', quantity, order_strategy, self.order_tracker
        )
        
        if result['success']:
            order_no = result.get('order_no', 'Unknown')
            executed_price = result.get('limit_price', current_price)
            stock_name = self.get_stock_name(symbol)
        
            # 시장가 주문인 경우 즉시 포지션에 기록
            if executed_price == 0:
                executed_price = current_price
                self.position_manager.record_purchase(symbol, quantity, executed_price, "hybrid_strategy")
        
            # 강제 알림 전송
            if self.notifier and self.notifier.webhook_url:
                self.notifier.notify_trade_success('BUY', symbol, quantity, executed_price, order_no, stock_name)
        
            # 개선된 매매 알림도 전송
            self.notify_improved_trade(symbol, 'BUY', daily_analysis, timing_analysis, quantity, executed_price)
        
            return True
        else:
            error_msg = result.get('error', 'Unknown error')
            stock_name = self.get_stock_name(symbol)
        
            # 실패 알림
            if self.notifier and self.notifier.webhook_url:
                self.notifier.notify_trade_failure('BUY', symbol, error_msg, stock_name)
  
        
        return False
    
    
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
