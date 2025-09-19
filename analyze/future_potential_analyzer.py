"""
미래 상승 가능성 분석 클래스
trading_system의 calculate_future_potential 로직을 analyze 모듈에서 사용할 수 있도록 독립 클래스로 분리
"""

import os
import sys
from typing import Dict, List
from datetime import datetime
import logging

# trading_system 모듈 경로 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
trading_system_path = os.path.join(parent_dir, 'trading_system')

if os.path.exists(trading_system_path):
    sys.path.insert(0, trading_system_path)
    print(f"📁 trading_system 경로 추가: {trading_system_path}")

try:
    from data.kis_api_client import KISAPIClient
    from strategy.technical_indicators import TechnicalIndicators
    TRADING_SYSTEM_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ trading_system 모듈 로드 실패: {e}")
    TRADING_SYSTEM_AVAILABLE = False


class FuturePotentialAnalyzer:
    """
    미래 상승 가능성 분석 클래스
    trading_system의 calculate_future_potential 로직을 독립적으로 구현
    """
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = False
        
        if TRADING_SYSTEM_AVAILABLE:
            try:
                self.api_client = KISAPIClient(
                    app_key=os.getenv('KIS_APP_KEY'),
                    app_secret=os.getenv('KIS_APP_SECRET'),
                    base_url=os.getenv('KIS_BASE_URL', 'https://openapi.koreainvestment.com:9443'),
                    account_no=os.getenv('KIS_ACCOUNT_NO', ''))
                self.enabled = True
                self.logger.info("✅ 미래 상승 가능성 분석 모듈 초기화 성공")
            except Exception as e:
                self.logger.warning(f"⚠️ API 클라이언트 초기화 실패: {e}")
        else:
            self.logger.warning("⚠️ trading_system 모듈을 찾을 수 없음 - 미래 분석 비활성화")
    
    def is_enabled(self) -> bool:
        """미래 분석 기능 활성화 여부 확인"""
        return self.enabled
    
    def calculate_future_potential(self, symbol: str) -> Dict:
        """
        종목별 미래 상승 가능성 점수화 (0~100점)
        """
        if not self.enabled:
            return {
                'symbol': symbol,
                'total_score': 50,
                'grade': "B (분석불가)",
                'error': '모듈 비활성화'
            }
        
        try:
            stock_name = self.get_stock_name(symbol)
            self.logger.debug(f"🎯 {stock_name}({symbol}) 미래 상승 가능성 분석 시작")
            
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
            grade = self._get_grade(final_score)
            
            self.logger.debug(f"📊 {stock_name}({symbol}) 미래 상승 가능성: {final_score:.1f}점 ({grade})")
            
            return {
                'symbol': symbol,
                'stock_name': stock_name,
                'total_score': final_score,
                'grade': grade,
                'score_breakdown': score_details,
                'top_reasons': reasons[:5],
                'recommendation': self._get_recommendation(final_score),
                'analysis_time': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"미래 상승 가능성 분석 오류 ({symbol}): {e}")
            return {
                'symbol': symbol,
                'total_score': 50,
                'grade': "B (분석실패)",
                'error': str(e)
            }
    
    def _get_grade(self, score: float) -> str:
        """점수를 등급으로 변환"""
        if score >= 80:
            return "A+ (매우높음)"
        elif score >= 70:
            return "A (높음)"
        elif score >= 60:
            return "B (보통)"
        elif score >= 40:
            return "C (낮음)"
        else:
            return "D (매우낮음)"
    
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
    
    def get_stock_name(self, symbol: str) -> str:
        """종목명 조회"""
        try:
            basic_info = self.api_client.get_stock_basic_info(symbol)
            if basic_info and basic_info.get('output'):
                output = basic_info['output']
                if 'prdt_abrv_name' in output and output['prdt_abrv_name']:
                    return str(output['prdt_abrv_name']).strip()
        except Exception as e:
            self.logger.debug(f"종목명 조회 실패 ({symbol}): {e}")
        
        return symbol
    
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
            daily_df = self._calculate_daily_indicators(daily_df)
            latest = daily_df.iloc[-1]
            current_price = latest['stck_prpr']
            
            # 1) RSI 점수 (8점)
            rsi = latest['rsi']
            if 30 <= rsi <= 50:  # 매수 적정권
                score += 8
                reasons.append(f"RSI매수권({rsi:.1f})")
            elif 50 < rsi <= 60:
                score += 6
                reasons.append(f"RSI보통({rsi:.1f})")
            elif rsi < 30:  # 과매도
                score += 5
                reasons.append(f"RSI과매도({rsi:.1f})")
            elif rsi > 70:  # 과매수
                score += 2
                reasons.append(f"RSI과매수({rsi:.1f})")
            else:
                score += 4
            
            # 2) MACD 점수 (8점)
            macd_analysis = TechnicalIndicators.detect_macd_golden_cross(daily_df)
            if macd_analysis['golden_cross'] and macd_analysis['signal_age'] <= 10:
                score += 8
                reasons.append(f"MACD골든크로스({macd_analysis['signal_age']}일)")
            elif latest['macd'] > latest['macd_signal']:
                score += 6
                reasons.append("MACD상향")
            elif latest['macd'] > 0:
                score += 4
                reasons.append("MACD양수")
            else:
                score += 2
            
            # 3) 이동평균선 점수 (8점)
            if current_price > latest['ma60']:
                score += 4
                reasons.append("60일선위")
            if current_price > latest['ma20']:
                score += 4
                reasons.append("20일선위")
            
            # 4) 볼린저밴드 점수 (6점)
            bb_position = (current_price - latest['bb_lower']) / (latest['bb_upper'] - latest['bb_lower'])
            if bb_position <= 0.2:  # 하단 20%
                score += 6
                reasons.append("볼밴하단권")
            elif bb_position >= 0.8:  # 상단 20%
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
                daily_df = self._calculate_daily_indicators(daily_df)
                ma20 = daily_df['ma20'].iloc[-1]
                ma60 = daily_df['ma60'].iloc[-1]
                
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
            
            # 1) 단기 수익률 (10점)
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
            if short_returns.get('5d', 0) > 3:
                score += 3
                reasons.append(f"5일급등({short_returns['5d']:.1f}%)")
            elif short_returns.get('5d', 0) > 0:
                score += 2
            else:
                score += 1
            
            # 10일 수익률
            if short_returns.get('10d', 0) > 5:
                score += 3
                reasons.append(f"10일급등({short_returns['10d']:.1f}%)")
            elif short_returns.get('10d', 0) > 0:
                score += 2
            else:
                score += 1
            
            # 2) 연속 상승일 (5점)
            consecutive_up = 0
            for i in range(len(daily_df)-1, 0, -1):
                if daily_df['stck_prpr'].iloc[i] > daily_df['stck_prpr'].iloc[i-1]:
                    consecutive_up += 1
                else:
                    break
            
            if consecutive_up >= 5:
                score += 5
                reasons.append(f"연속상승{consecutive_up}일")
            elif consecutive_up >= 3:
                score += 3
                reasons.append(f"연속상승{consecutive_up}일")
            elif consecutive_up >= 1:
                score += 2
            else:
                score += 1
            
            # 3) 상승 추세 강도 (5점)
            if len(daily_df) >= 20:
                recent_trend = 0
                for days in [5, 10, 20]:
                    if len(daily_df) > days:
                        past_price = daily_df['stck_prpr'].iloc[-(days+1)]
                        if current_price > past_price:
                            recent_trend += 1
                
                if recent_trend == 3:
                    score += 5
                    reasons.append("전구간상승")
                elif recent_trend == 2:
                    score += 3
                    reasons.append("대부분상승")
                elif recent_trend == 1:
                    score += 2
                else:
                    score += 1
            
            return {'score': score, 'reasons': reasons}
            
        except Exception as e:
            return {'score': 10, 'reasons': [f'모멘텀분석오류: {e}']}
    
    def _calculate_volume_score(self, symbol: str) -> Dict:
        """거래량 분석 점수 (15점 만점)"""
        score = 0
        reasons = []
        
        try:
            daily_df = self.api_client.get_daily_data(symbol, days=60)
            if daily_df.empty or len(daily_df) < 20:
                return {'score': 7, 'reasons': ['데이터부족']}
            
            current_volume = daily_df['acml_vol'].iloc[-1]
            
            # 1) 거래량 급증 (8점)
            avg_volume_20 = daily_df['acml_vol'].rolling(20).mean().iloc[-1]
            volume_ratio = current_volume / avg_volume_20 if avg_volume_20 > 0 else 1
            
            if volume_ratio >= 3.0:
                score += 8
                reasons.append(f"거래량급증({volume_ratio:.1f}배)")
            elif volume_ratio >= 2.0:
                score += 6
                reasons.append(f"거래량증가({volume_ratio:.1f}배)")
            elif volume_ratio >= 1.5:
                score += 4
                reasons.append(f"거래량확대({volume_ratio:.1f}배)")
            elif volume_ratio >= 1.0:
                score += 3
            else:
                score += 2
                reasons.append("거래량감소")
            
            # 2) 거래량 지속성 (4점)
            recent_volumes = daily_df['acml_vol'].tail(5)
            avg_recent = recent_volumes.mean()
            
            if avg_recent > avg_volume_20 * 1.3:
                score += 4
                reasons.append("지속적거래량")
            elif avg_recent > avg_volume_20:
                score += 3
            else:
                score += 2
            
            # 3) 대형 거래 (3점)
            # 전체 시장 대비 거래량 순위 (근사치)
            if current_volume > 1000000:  # 100만주 이상
                score += 3
                reasons.append("대형거래")
            elif current_volume > 500000:  # 50만주 이상
                score += 2
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
            # 1) KOSPI 지수 동향 (6점)
            kospi_data = self.api_client.get_daily_data('0001', days=10)  # KOSPI
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
            
            # 2) 상대 강도 (4점)
            daily_df = self.api_client.get_daily_data(symbol, days=5)
            if not daily_df.empty and len(daily_df) >= 2 and not kospi_data.empty:
                stock_change = (daily_df['stck_prpr'].iloc[-1] / daily_df['stck_prpr'].iloc[-2] - 1) * 100
                
                # 시장 대비 상대 강도
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
    
    def _calculate_daily_indicators(self, df):
        """일봉 기술적 지표 계산"""
        try:
            # 이동평균선
            df['ma5'] = df['stck_prpr'].rolling(window=5).mean()
            df['ma20'] = df['stck_prpr'].rolling(window=20).mean()
            df['ma60'] = df['stck_prpr'].rolling(window=60).mean()
            
            # RSI
            delta = df['stck_prpr'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD
            exp1 = df['stck_prpr'].ewm(span=12).mean()
            exp2 = df['stck_prpr'].ewm(span=26).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            
            # 볼린저밴드
            df['bb_middle'] = df['stck_prpr'].rolling(window=20).mean()
            bb_std = df['stck_prpr'].rolling(window=20).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
            
            return df
        except Exception as e:
            self.logger.error(f"기술적 지표 계산 오류: {e}")
            return df
    
    def get_filtered_candidates(self, candidates: List[Dict], min_future_score: int = 60) -> List[Dict]:
        """
        기존 후보군에 미래 분석을 적용하여 필터링
        
        Args:
            candidates: 기존 분석으로 선별된 후보 리스트
            min_future_score: 미래 점수 최소 기준 (기본값: 60점, B등급)
        
        Returns:
            필터링된 후보 리스트
        """
        if not self.enabled:
            self.logger.warning("미래 분석 비활성화 - 원본 후보 반환")
            return candidates
        
        filtered_candidates = []
        
        for candidate in candidates:
            symbol = candidate.get('code')
            if not symbol:
                continue
            
            # 미래 분석 수행
            future_analysis = self.calculate_future_potential(symbol)
            future_score = future_analysis.get('total_score', 50)
            
            # 필터링 기준 적용
            if future_score >= min_future_score:
                # 기존 데이터에 미래 분석 결과 추가
                enhanced_candidate = candidate.copy()
                enhanced_candidate.update({
                    'future_score': future_score,
                    'future_grade': future_analysis.get('grade', 'B'),
                    'future_reasons': future_analysis.get('top_reasons', []),
                    'combined_score': candidate.get('score', 3) * 0.7 + (future_score / 20) * 0.3
                })
                filtered_candidates.append(enhanced_candidate)
            else:
                self.logger.debug(f"🚫 {candidate.get('name')}({symbol}) "
                                f"미래점수 부족으로 제외: {future_score:.1f}점")
        
        # 종합 점수 순으로 정렬
        filtered_candidates.sort(key=lambda x: x.get('combined_score', 0), reverse=True)
        
        self.logger.info(f"📊 미래 분석 필터링: {len(candidates)}개 → {len(filtered_candidates)}개 "
                        f"(기준: {min_future_score}점 이상)")
        
        return filtered_candidates
