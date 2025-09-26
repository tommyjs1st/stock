"""
기술적 지표 분석 모듈 (이동평균선 함수 추가)
각종 매수 신호 감지 함수들
"""
import pandas as pd
import numpy as np
import logging

# pandas_ta 모듈이 없는 경우를 대비한 조건부 import
try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False
    print("⚠️ pandas_ta 모듈이 없습니다. 일부 기술적 지표는 수동으로 계산됩니다.")

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    

    @staticmethod
    def is_ma5_below_ma20(df):
        """
        5일 이동평균선이 20일 이동평균선 아래에 있는지 확인 (절대조건용)
        
        Args:
            df: 주가 데이터프레임 (stck_clpr 또는 stck_prpr 컬럼 필요)
        
        Returns:
            bool: 5일선이 20일선 아래 있으면 True
        """
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            
            # 컬럼명 통일 처리
            price_col = None
            if 'stck_clpr' in df.columns:
                price_col = 'stck_clpr'
            elif 'stck_prpr' in df.columns:
                price_col = 'stck_prpr'
            else:
                return False
                
            df = df.copy()
            
            # 이동평균선 계산
            df["ma5"] = df[price_col].rolling(window=5).mean()
            df["ma20"] = df[price_col].rolling(window=20).mean()
            
            # 최신 데이터
            current = df.iloc[-1]
            
            # NaN 값 체크
            if pd.isna(current["ma5"]) or pd.isna(current["ma20"]):
                return False
            
            # 5일선이 20일선 아래 있는지 확인
            is_below = current["ma5"] < current["ma20"]
            
            # 추가 검증: 의미있는 차이가 있는지 (0.5% 이상)
            if is_below:
                distance_ratio = (current["ma20"] - current["ma5"]) / current["ma20"]
                meaningful_gap = distance_ratio >= 0.005  # 0.5% 이상 차이
                
                logger.debug(f"5일선<20일선 검증: 차이 {distance_ratio:.2%}, 의미있는 차이: {meaningful_gap}")
                return meaningful_gap
            
            return False
            
        except Exception as e:
            logger.error(f"❌ 5일선 20일선 아래 위치 확인 오류: {e}")
            return False

    @staticmethod
    def analyze_foreign_selling_pressure(foreign_netbuy_list, days=5):
        """
        외국인 매도 압력 분석 (개선된 버전)
        
        Args:
            foreign_netbuy_list: 외국인 순매수 리스트 (최신순)
            days: 분석할 일수
            
        Returns:
            dict: 매도 압력 분석 결과
        """
        try:
            if not foreign_netbuy_list or len(foreign_netbuy_list) < 3:
                return {
                    'is_selling_pressure': False,
                    'pressure_level': 'unknown',
                    'reason': '데이터 부족'
                }
            
            # 최근 N일 데이터 분석
            recent_data = foreign_netbuy_list[:days]
            
            # 매도일 계산
            selling_days = sum(1 for x in recent_data if x < 0)
            total_volume = sum(abs(x) for x in recent_data)
            net_volume = sum(recent_data)
            
            # 평균 일일 거래량
            avg_daily_volume = total_volume / len(recent_data) if recent_data else 0
            
            # 매도 압력 수준 판단
            selling_ratio = selling_days / len(recent_data)
            
            analysis_result = {
                'selling_days': selling_days,
                'total_days': len(recent_data),
                'selling_ratio': selling_ratio,
                'net_volume': net_volume,
                'avg_daily_volume': avg_daily_volume,
                'recent_data': recent_data
            }
            
            # 매도 압력 수준 분류
            if selling_ratio >= 0.8 and avg_daily_volume > 10000:  # 80% 이상 매도일 + 대량거래
                analysis_result.update({
                    'is_selling_pressure': True,
                    'pressure_level': 'very_high',
                    'reason': f'{days}일중 {selling_days}일 매도 + 대량거래'
                })
            elif selling_ratio >= 0.6 and net_volume < -50000:  # 60% 이상 매도일 + 순매도 5만주 이상
                analysis_result.update({
                    'is_selling_pressure': True,
                    'pressure_level': 'high',
                    'reason': f'{days}일중 {selling_days}일 매도 + 순매도 {abs(net_volume):,}주'
                })
            elif selling_ratio >= 0.6 or (net_volume < -20000 and avg_daily_volume > 5000):
                analysis_result.update({
                    'is_selling_pressure': True,
                    'pressure_level': 'moderate',
                    'reason': f'매도비율 {selling_ratio:.1%} 또는 순매도 {abs(net_volume):,}주'
                })
            else:
                analysis_result.update({
                    'is_selling_pressure': False,
                    'pressure_level': 'low',
                    'reason': '매도 압력 낮음'
                })
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"외국인 매도 압력 분석 오류: {e}")
            return {
                'is_selling_pressure': False,
                'pressure_level': 'error',
                'reason': f'분석 오류: {e}'
            }

    @staticmethod
    def is_golden_cross(df):
        """골든크로스 신호 감지 (5일선이 20일선을 상향 돌파)"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            
            # 컬럼명 통일 처리
            price_col = None
            if 'stck_clpr' in df.columns:
                price_col = 'stck_clpr'
            elif 'stck_prpr' in df.columns:
                price_col = 'stck_prpr'
            else:
                return False
                
            df = df.copy()
            df["ma5"] = df[price_col].rolling(window=5).mean()
            df["ma20"] = df[price_col].rolling(window=20).mean()
            
            if len(df) < 2:
                return False
                
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            
            return (not pd.isna(today["ma5"]) and not pd.isna(today["ma20"]) and
                    not pd.isna(yesterday["ma5"]) and not pd.isna(yesterday["ma20"]) and
                    yesterday["ma5"] < yesterday["ma20"] and today["ma5"] > today["ma20"])
        except Exception as e:
            logger.error(f"❌ 골든크로스 계산 오류: {e}")
            return False

    @staticmethod
    def is_ma5_crossing_above_ma20(df):
        """
        5일 이동평균선이 20일 이동평균선을 상향 돌파하는 시점 감지 (골든크로스)
        """
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            
            # 컬럼명 통일 처리
            price_col = None
            if 'stck_clpr' in df.columns:
                price_col = 'stck_clpr'
            elif 'stck_prpr' in df.columns:
                price_col = 'stck_prpr'
            else:
                return False
                
            df = df.copy()
            
            # 이동평균선 계산
            df["ma5"] = df[price_col].rolling(window=5).mean()
            df["ma20"] = df[price_col].rolling(window=20).mean()
            
            if len(df) < 2:
                return False
                
            # 오늘과 어제 데이터
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            
            # NaN 값 체크
            if (pd.isna(today["ma5"]) or pd.isna(today["ma20"]) or
                pd.isna(yesterday["ma5"]) or pd.isna(yesterday["ma20"])):
                return False
            
            # 골든크로스 조건
            cross_condition = (yesterday["ma5"] <= yesterday["ma20"] and 
                              today["ma5"] > today["ma20"])
            
            # 추가 확인: 5일선이 상승 추세인지
            upward_trend = today["ma5"] > yesterday["ma5"]
            
            # 거래량 확인 (선택사항)
            volume_col = 'acml_vol' if 'acml_vol' in df.columns else 'cntg_vol'
            if volume_col in df.columns and len(df) >= 10:
                avg_volume = df[volume_col].rolling(window=10).mean().iloc[-1]
                current_volume = df[volume_col].iloc[-1]
                volume_surge = current_volume > avg_volume * 1.2
                
                return cross_condition and upward_trend and volume_surge
            else:
                return cross_condition and upward_trend
                
        except Exception as e:
            logger.error(f"❌ 5일선 20일선 상향돌파 계산 오류: {e}")
            return False

    @staticmethod
    def is_ma5_crossing_below_ma20(df):
        """5일 이동평균선이 20일 이동평균선을 하향 돌파하는 시점 감지 (데드크로스)"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            
            # 컬럼명 통일 처리
            price_col = None
            if 'stck_clpr' in df.columns:
                price_col = 'stck_clpr'
            elif 'stck_prpr' in df.columns:
                price_col = 'stck_prpr'
            else:
                return False
                
            df = df.copy()
            
            # 이동평균선 계산
            df["ma5"] = df[price_col].rolling(window=5).mean()
            df["ma20"] = df[price_col].rolling(window=20).mean()
            
            if len(df) < 2:
                return False
                
            # 오늘과 어제 데이터
            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            
            # NaN 값 체크
            if (pd.isna(today["ma5"]) or pd.isna(today["ma20"]) or
                pd.isna(yesterday["ma5"]) or pd.isna(yesterday["ma20"])):
                return False
            
            # 데드크로스 조건
            cross_condition = (yesterday["ma5"] >= yesterday["ma20"] and 
                              today["ma5"] < today["ma20"])
            
            # 추가 확인: 5일선이 하락 추세인지
            downward_trend = today["ma5"] < yesterday["ma5"]
            
            return cross_condition and downward_trend
            
        except Exception as e:
            logger.error(f"❌ 5일선 20일선 하향돌파 계산 오류: {e}")
            return False

    @staticmethod
    def is_price_below_ma20(df):
        """현재 주가가 20일 이동평균선 아래에 있는지 확인"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            
            # 컬럼명 통일 처리
            price_col = None
            if 'stck_clpr' in df.columns:
                price_col = 'stck_clpr'
            elif 'stck_prpr' in df.columns:
                price_col = 'stck_prpr'
            else:
                return False
                
            df = df.copy()
            
            # 20일 이동평균선 계산
            df["ma20"] = df[price_col].rolling(window=20).mean()
            
            # 최신 데이터
            current = df.iloc[-1]
            
            # NaN 값 체크
            if pd.isna(current["ma20"]):
                return False
            
            current_price = current[price_col]
            ma20_value = current["ma20"]
            
            # 현재가가 20일선 아래 있는지 확인
            below_ma20 = current_price < ma20_value
            
            # 추가 조건: 20일선과의 거리 (1% 이상)
            distance_ratio = (ma20_value - current_price) / ma20_value
            meaningful_distance = distance_ratio >= 0.01
            
            return below_ma20 and meaningful_distance
            
        except Exception as e:
            logger.error(f"❌ 20일선 아래 위치 확인 오류: {e}")
            return False

    # 기존 다른 지표들도 동일하게 컬럼명 통일 처리
    @staticmethod
    def is_bollinger_rebound(df):
        """볼린저밴드 하한선 반등 신호"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            
            # 컬럼명 통일 처리
            price_col = None
            if 'stck_clpr' in df.columns:
                price_col = 'stck_clpr'
            elif 'stck_prpr' in df.columns:
                price_col = 'stck_prpr'
            else:
                return False
                
            df = df.copy()
            df["ma20"] = df[price_col].rolling(window=20).mean()
            df["stddev"] = df[price_col].rolling(window=20).std()
            df["lower_band"] = df["ma20"] - 2 * df["stddev"]

            if len(df) < 2:
                return False
                
            today = df.iloc[-1]
            yesterday = df.iloc[-2]

            return (not pd.isna(yesterday["lower_band"]) and not pd.isna(today["lower_band"]) and
                    yesterday[price_col] < yesterday["lower_band"] and
                    today[price_col] > today["lower_band"])
        except Exception as e:
            logger.error(f"❌ 볼린저밴드 계산 오류: {e}")
            return False

    @staticmethod
    def is_volume_breakout(df, volume_period=20, volume_multiplier=2.0):
        """거래량 급증 신호"""
        try:
            if df is None or df.empty or len(df) < volume_period + 1:
                return False
            
            # 거래량 컬럼 통일 처리
            volume_col = None
            if 'acml_vol' in df.columns:
                volume_col = 'acml_vol'
            elif 'cntg_vol' in df.columns:
                volume_col = 'cntg_vol'
            else:
                return False
            
            avg_volume = df[volume_col].rolling(window=volume_period).mean()
            today_volume = df[volume_col].iloc[-1]
            avg_volume_today = avg_volume.iloc[-1]
            
            if pd.isna(avg_volume_today) or avg_volume_today == 0:
                return False
            
            return today_volume > avg_volume_today * volume_multiplier
        except Exception as e:
            logger.error(f"❌ 거래량 계산 오류: {e}")
            return False

    @staticmethod
    def is_williams_r_oversold_recovery(df, period=14, oversold_threshold=-80, recovery_threshold=-70):
        """Williams %R 과매도 구간에서 회복 신호"""
        try:
            if df is None or df.empty or len(df) < period + 2:
                return False
            required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
            if not all(col in df.columns for col in required_cols):
                return False
            
            if HAS_PANDAS_TA:
                willr = ta.willr(df["stck_hgpr"], df["stck_lwpr"], df["stck_clpr"], length=period)
            else:
                # 수동 Williams %R 계산
                high = df["stck_hgpr"]
                low = df["stck_lwpr"]
                close = df["stck_clpr"]
                
                highest_high = high.rolling(window=period).max()
                lowest_low = low.rolling(window=period).min()
                
                willr = -100 * (highest_high - close) / (highest_high - lowest_low)
            
            if willr is None or willr.isna().any() or len(willr) < 2:
                return False
            
            return (willr.iloc[-2] < oversold_threshold and 
                    willr.iloc[-1] > recovery_threshold)
        except Exception as e:
            logger.error(f"❌ Williams %R 계산 오류: {e}")
            return False

    @staticmethod
    def is_double_bottom_pattern(df, lookback=20, tolerance=0.02):
        """이중바닥 패턴 감지"""
        try:
            if df is None or df.empty or len(df) < lookback * 2:
                return False
            if 'stck_lwpr' not in df.columns or 'stck_clpr' not in df.columns:
                return False
            
            # 최근 구간에서 저점 찾기
            recent_data = df.tail(lookback * 2)
            
            # 저점들 찾기 (local minima)
            lows = []
            for i in range(1, len(recent_data) - 1):
                if (recent_data.iloc[i]["stck_lwpr"] < recent_data.iloc[i-1]["stck_lwpr"] and 
                    recent_data.iloc[i]["stck_lwpr"] < recent_data.iloc[i+1]["stck_lwpr"]):
                    lows.append((i, recent_data.iloc[i]["stck_lwpr"]))
            
            if len(lows) < 2:
                return False
            
            # 마지막 두 저점 비교
            last_two_lows = lows[-2:]
            low1_price = last_two_lows[0][1]
            low2_price = last_two_lows[1][1]
            
            # 두 저점이 비슷한 수준이고, 현재 가격이 상승 중
            price_diff = abs(low1_price - low2_price) / low1_price
            current_price = df.iloc[-1]["stck_clpr"]
            
            return (price_diff < tolerance and 
                    current_price > max(low1_price, low2_price) * 1.02)
        except Exception as e:
            logger.error(f"❌ 이중바닥 패턴 계산 오류: {e}")
            return False

    @staticmethod
    def is_ichimoku_bullish_signal(df):
        """일목균형표 매수 신호"""
        try:
            if df is None or df.empty or len(df) < 52:
                return False
            required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
            if not all(col in df.columns for col in required_cols):
                return False
            
            high = df["stck_hgpr"]
            low = df["stck_lwpr"]
            close = df["stck_clpr"]
            
            # 전환선 (9일)
            conversion_line = (high.rolling(9).max() + low.rolling(9).min()) / 2
            
            # 기준선 (26일)
            base_line = (high.rolling(26).max() + low.rolling(26).min()) / 2
            
            # 선행스팬A
            span_a = ((conversion_line + base_line) / 2).shift(26)
            
            # 선행스팬B
            span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
            
            current_price = close.iloc[-1]
            current_conversion = conversion_line.iloc[-1]
            current_base = base_line.iloc[-1]
            
            if pd.isna(current_conversion) or pd.isna(current_base):
                return False
            
            # 구름 위에 있고, 전환선이 기준선을 상향 돌파
            cloud_top = max(span_a.iloc[-1], span_b.iloc[-1]) if not pd.isna(span_a.iloc[-1]) and not pd.isna(span_b.iloc[-1]) else None
            
            if cloud_top is None or pd.isna(cloud_top):
                return False
            
            return (current_price > cloud_top and 
                    len(conversion_line) >= 2 and len(base_line) >= 2 and
                    conversion_line.iloc[-2] < base_line.iloc[-2] and 
                    current_conversion > current_base)
        except Exception as e:
            logger.error(f"❌ 일목균형표 계산 오류: {e}")
            return False

    @staticmethod
    def is_cup_handle_pattern(df, cup_depth=0.1, handle_depth=0.05, min_periods=30):
        """컵앤핸들 패턴 감지"""
        try:
            if df is None or df.empty or len(df) < min_periods:
                return False
            required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
            if not all(col in df.columns for col in required_cols):
                return False
            
            # 최근 30일 데이터
            recent_data = df.tail(min_periods)
            
            # 컵 패턴: 고점 -> 저점 -> 고점 형태
            max_price = recent_data["stck_hgpr"].max()
            min_price = recent_data["stck_lwpr"].min()
            current_price = recent_data["stck_clpr"].iloc[-1]
            
            if max_price == 0:
                return False
            
            # 컵의 깊이 체크
            cup_depth_actual = (max_price - min_price) / max_price
            
            # 현재 고점 근처까지 회복했는지 체크
            recovery_ratio = current_price / max_price
            
            return (cup_depth_actual > cup_depth and 
                    recovery_ratio > 0.90 and 
                    len(recent_data) >= 6 and
                    current_price > recent_data["stck_clpr"].iloc[-5])
        except Exception as e:
            logger.error(f"❌ 컵앤핸들 패턴 계산 오류: {e}")
            return False

    @staticmethod
    def get_comprehensive_analysis(df, foreign_netbuy_list=None):
        """
        종합 기술적 분석 (절대조건 포함)
        
        Returns:
            dict: 종합 분석 결과
        """
        try:
            analysis = {
                'meets_absolute_conditions': False,
                'ma5_below_ma20': False,
                'foreign_selling_pressure': None,
                'technical_signals': {},
                'recommendation': 'HOLD'
            }
            
            # 1. 절대조건 체크
            analysis['ma5_below_ma20'] = TechnicalIndicators.is_ma5_below_ma20(df)
            
            # 2. 외국인 매도 압력 분석
            if foreign_netbuy_list:
                foreign_analysis = TechnicalIndicators.analyze_foreign_selling_pressure(foreign_netbuy_list)
                analysis['foreign_selling_pressure'] = foreign_analysis
            
            # 3. 절대조건 종합 판단
            foreign_ok = True
            if analysis['foreign_selling_pressure']:
                foreign_ok = not analysis['foreign_selling_pressure']['is_selling_pressure']
            
            analysis['meets_absolute_conditions'] = (
                analysis['ma5_below_ma20'] and foreign_ok
            )
            
            # 4. 기술적 신호들
            if analysis['meets_absolute_conditions']:
                analysis['technical_signals'] = {
                    'golden_cross': TechnicalIndicators.is_golden_cross(df),
                    'bollinger_rebound': TechnicalIndicators.is_bollinger_rebound(df),
                    'volume_breakout': TechnicalIndicators.is_volume_breakout(df),
                    'price_below_ma20': TechnicalIndicators.is_price_below_ma20(df)
                }
                
                # 5. 매수 추천 여부
                signal_count = sum(analysis['technical_signals'].values())
                if signal_count >= 3:
                    analysis['recommendation'] = 'STRONG_BUY'
                elif signal_count >= 2:
                    analysis['recommendation'] = 'BUY'
                elif signal_count >= 1:
                    analysis['recommendation'] = 'WEAK_BUY'
            
            return analysis
            
        except Exception as e:
            logger.error(f"종합 기술적 분석 오류: {e}")
            return {
                'meets_absolute_conditions': False,
                'error': str(e)
            }




class SignalAnalyzer:
    """강화된 매수 신호 종합 분석 클래스"""
    
    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher
        self.ti = TechnicalIndicators()
    
    def calculate_buy_signal_score(self, df, name, code, foreign_trend=None, foreign_netbuy_list=None):
        """
        절대조건 필터링이 적용된 종합 매수 신호 점수 계산
        
        Returns:
            tuple: (점수, 활성신호리스트, 절대조건통과여부, 제외사유)
        """
        try:
            if df is None or df.empty:
                return 0, [], False, "데이터 없음"
            
            # 1. 절대조건 체크 먼저 수행
            absolute_check = self.ti.get_comprehensive_analysis(df, foreign_netbuy_list)
            
            if not absolute_check['meets_absolute_conditions']:
                reasons = []
                if not absolute_check['ma5_below_ma20']:
                    reasons.append("5일선이 20일선 위")
                if absolute_check['foreign_selling_pressure'] and absolute_check['foreign_selling_pressure']['is_selling_pressure']:
                    reasons.append(f"외국인매도압력({absolute_check['foreign_selling_pressure']['pressure_level']})")
                
                return 0, [], False, " + ".join(reasons)
            
            # 2. 절대조건 통과시에만 상세 신호 분석
            signals = {
                "골든크로스": self.ti.is_golden_cross(df),
                "볼린저밴드복귀": self.ti.is_bollinger_rebound(df),
                "거래량급증": self.ti.is_volume_breakout(df),
                "현재가20일선아래": self.ti.is_price_below_ma20(df),
                "5일선20일선아래": self.ti.is_ma5_below_ma20(df),  # 이미 통과 확인됨
                "외국인매수추세": foreign_trend == "steady_buying"
            }

            score = sum(signals.values())
            active_signals = [key for key, value in signals.items() if value]

            return score, active_signals, True, "절대조건 모두 통과"
            
        except Exception as e:
            logger.error(f"❌ {name}: 매수 신호 점수 계산 오류: {e}")
            return 0, [], False, f"계산 오류: {e}"

