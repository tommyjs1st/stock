"""
미래 상승 가능성 분석 클래스
strategy/hybrid_strategy.py에서 분리된 독립 모듈
"""

import pandas as pd
from datetime import datetime
from typing import Dict, List 
import logging

class FuturePotentialAnalyzer:
    """미래 상승 가능성 분석 전담 클래스"""
    
    def __init__(self, api_client, logger=None):
        self.api_client = api_client
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = True
        
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

    def calculate_future_potential(self, symbol: str) -> Dict:
        """
        종목별 미래 상승 가능성 점수화 (0~100점)
        포트폴리오 최적화를 위한 종합 평가 시스템
        """
        try:
            stock_name = self.get_stock_name(symbol)
            #self.logger.info(f"🎯 {stock_name}({symbol}) 미래 상승 가능성 분석 시작")
            
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

    def _calculate_daily_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """일봉 기술적 지표 계산 (기본 지표만)"""
        try:
            # RSI 계산
            delta = df['stck_prpr'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # 이동평균선
            df['ma20'] = df['stck_prpr'].rolling(20).mean()
            df['ma60'] = df['stck_prpr'].rolling(60).mean()
            
            # MACD (간단 버전)
            ema12 = df['stck_prpr'].ewm(span=12).mean()
            ema26 = df['stck_prpr'].ewm(span=26).mean()
            df['macd'] = ema12 - ema26
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            
            # 볼린저밴드
            df['bb_middle'] = df['stck_prpr'].rolling(20).mean()
            bb_std = df['stck_prpr'].rolling(20).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
            
            return df
            
        except Exception as e:
            self.logger.error(f"기술적 지표 계산 오류: {e}")
            return df

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
            if latest['macd'] > latest['macd_signal'] and latest['macd'] > 0:
                score += 8
                reasons.append("MACD골든크로스")
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
                reasons.append("볼밴하단매수")
            elif bb_position <= 0.4:  # 하단 40%
                score += 5
                reasons.append("볼밴하단권")
            elif bb_position >= 0.8:  # 상단 80%
                score += 2
                reasons.append("볼밴상단권")
            else:
                score += 4
            
            return {'score': score, 'reasons': reasons}
            
        except Exception as e:
            return {'score': 15, 'reasons': [f'기술분석오류: {e}']}

    def _calculate_price_position_score(self, symbol: str) -> Dict:
        """가격 위치 점수 (25점 만점)"""
        score = 0
        reasons = []
        
        try:
            daily_df = self.api_client.get_daily_data(symbol, days=120)
            if daily_df.empty or len(daily_df) < 60:
                return {'score': 12, 'reasons': ['데이터부족']}
            
            current_price = daily_df['stck_prpr'].iloc[-1]
            
            # 1) 52주 고점 대비 위치 (15점)
            high_52w = daily_df['stck_prpr'].max()
            correction = (high_52w - current_price) / high_52w
            
            if correction >= 0.4:  # 40% 이상 조정
                score += 15
                reasons.append(f"대폭조정({correction:.1%})")
            elif correction >= 0.3:  # 30% 이상 조정
                score += 12
                reasons.append(f"조정충분({correction:.1%})")
            elif correction >= 0.2:  # 20% 이상 조정
                score += 10
                reasons.append(f"적정조정({correction:.1%})")
            elif correction >= 0.1:  # 10% 이상 조정
                score += 7
                reasons.append(f"소폭조정({correction:.1%})")
            else:  # 고점 근처
                score += 3
                reasons.append("고점근처")
            
            # 2) 60일 저점 대비 위치 (10점)
            low_60 = daily_df['stck_prpr'].tail(60).min()
            upside = (current_price - low_60) / low_60
            
            if upside <= 0.1:  # 저점 근처
                score += 10
                reasons.append("저점근처")
            elif upside <= 0.2:  # 10-20% 상승
                score += 8
                reasons.append("저점권탈출")
            elif upside <= 0.3:  # 20-30% 상승
                score += 6
            else:  # 30% 이상 상승
                score += 4
            
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
            
            # 1) 단기 수익률 (12점)
            returns = {}
            for days in [3, 5, 10]:
                if len(daily_df) > days:
                    past_price = daily_df['stck_prpr'].iloc[-(days+1)]
                    return_pct = (current_price - past_price) / past_price * 100
                    returns[f'{days}d'] = return_pct
            
            # 3일 수익률 (4점)
            if returns.get('3d', 0) > 5:
                score += 4
                reasons.append(f"3일급등({returns['3d']:.1f}%)")
            elif returns.get('3d', 0) > 2:
                score += 3
                reasons.append(f"3일상승({returns['3d']:.1f}%)")
            elif returns.get('3d', 0) > 0:
                score += 2
            else:
                score += 1
            
            # 5일 수익률 (4점)
            if returns.get('5d', 0) > 8:
                score += 4
                reasons.append(f"5일급등({returns['5d']:.1f}%)")
            elif returns.get('5d', 0) > 3:
                score += 3
                reasons.append(f"5일상승({returns['5d']:.1f}%)")
            elif returns.get('5d', 0) > 0:
                score += 2
            else:
                score += 1
            
            # 10일 수익률 (4점)
            if returns.get('10d', 0) > 15:
                score += 4
                reasons.append(f"10일급등({returns['10d']:.1f}%)")
            elif returns.get('10d', 0) > 5:
                score += 3
                reasons.append(f"10일상승({returns['10d']:.1f}%)")
            elif returns.get('10d', 0) > 0:
                score += 2
            else:
                score += 1
            
            # 2) 연속 상승일 (8점)
            consecutive_up = 0
            for i in range(len(daily_df)-1, 0, -1):
                if daily_df['stck_prpr'].iloc[i] > daily_df['stck_prpr'].iloc[i-1]:
                    consecutive_up += 1
                else:
                    break
            
            if consecutive_up >= 5:
                score += 8
                reasons.append(f"연속상승({consecutive_up}일)")
            elif consecutive_up >= 3:
                score += 6
                reasons.append(f"연속상승({consecutive_up}일)")
            elif consecutive_up >= 2:
                score += 4
            elif consecutive_up >= 1:
                score += 2
            
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
            
            # 2) 섹터 상대 강도 (4점) - 단순화
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
                
                try:
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
                except Exception as e:
                    self.logger.error(f"❌ {candidate.get('name')}({symbol}) 미래 분석 오류: {e}")
                    # 오류 발생시에도 기존 후보는 유지 (보수적 접근)
                    candidate_copy = candidate.copy()
                    candidate_copy.update({
                        'future_score': 50,  # 기본값
                        'future_grade': 'B (분석실패)',
                        'future_reasons': ['분석 실패'],
                        'combined_score': candidate.get('score', 3)
                    })
                    filtered_candidates.append(candidate_copy)
            
            # 종합 점수 순으로 정렬
            filtered_candidates.sort(key=lambda x: x.get('combined_score', 0), reverse=True)
            
            self.logger.info(f"📊 미래 분석 필터링: {len(candidates)}개 → {len(filtered_candidates)}개 "
                            f"(기준: {min_future_score}점 이상)")
            
            return filtered_candidates
