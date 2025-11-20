"""
기술적 지표 분석 모듈 (이동평균선 함수 추가) - 수정 버전
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
    def is_volume_sufficient(df, min_volume=1000):
        """
        최근 거래량이 최소 기준 이상인지 확인 (절대조건용)
        
        Args:
            df: 주가 데이터프레임
            min_volume: 최소 거래량 (기본 1000주)
        
        Returns:
            bool: 거래량 충분 여부
        """
        try:
            if df is None or df.empty or len(df) < 1:
                return False
            
            # 거래량 컬럼 통일 처리
            volume_col = None
            if 'acml_vol' in df.columns:
                volume_col = 'acml_vol'
            elif 'cntg_vol' in df.columns:
                volume_col = 'cntg_vol'
            else:
                return False
            
            # 최신 거래량
            current_volume = df.iloc[-1][volume_col]
            
            # NaN 체크
            if pd.isna(current_volume):
                return False
            
            # 거래량 검증
            is_sufficient = current_volume >= min_volume
            logger.debug(f"{current_volume}, {is_sufficient}")
            
            return is_sufficient
            
        except Exception as e:
            logger.error(f"❌ 거래량 확인 오류: {e}")
            return False

    @staticmethod
    def is_price_above_bollinger_lower(df, period=20, num_std=2):
        """
        현재가가 볼린저밴드 하단선 위에 있는지 확인 (절대조건용)
        - 볼린저밴드 하단을 이탈한 과도한 하락 종목 제외
        """
        try:
            if df is None or df.empty or len(df) < period + 1:
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
            
            # 볼린저밴드 계산
            df["ma20"] = df[price_col].rolling(window=period).mean()
            df["stddev"] = df[price_col].rolling(window=period).std()
            df["lower_band"] = df["ma20"] - num_std * df["stddev"]
            
            # 최신 데이터
            current = df.iloc[-1]
            
            # NaN 값 체크
            if pd.isna(current["lower_band"]):
                return False
            
            current_price = current[price_col]
            lower_band = current["lower_band"]
            
            # 현재가가 볼린저밴드 하단선 위에 있는지 확인
            above_lower_band = current_price >= lower_band
            
            # 디버깅 로그
            if not above_lower_band:
                distance_ratio = (lower_band - current_price) / lower_band * 100
                logger.debug(f"볼린저밴드 하단 이탈: 현재가 {current_price:,}원, 하단선 {lower_band:.0f}원 (이탈률 {distance_ratio:.1f}%)")
            
            return above_lower_band
            
        except Exception as e:
            logger.error(f"❌ 볼린저밴드 확인 오류: {e}")
            return False

    @staticmethod
    def is_rsi_buy_signal(df, period=14, oversold_threshold=30, recovery_threshold=50):
        """
        RSI 매수 신호 감지
        - RSI가 과매도 구간(30 이하)에서 회복 중이거나
        - RSI가 매수 적정권(30~50)에 있을 때
        
        Args:
            df: 주가 데이터프레임
            period: RSI 계산 기간 (기본 14일)
            oversold_threshold: 과매도 기준 (기본 30)
            recovery_threshold: 회복 기준 (기본 50)
        
        Returns:
            bool: RSI 매수 신호 여부
        """
        try:
            if df is None or df.empty or len(df) < period + 5:
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
            
            # RSI 계산
            delta = df[price_col].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            
            # 0으로 나누기 방지
            rs = gain / loss.replace(0, 0.0001)
            rsi = 100 - (100 / (1 + rs))
            
            if len(rsi) < 2:
                return False
            
            current_rsi = rsi.iloc[-1]
            previous_rsi = rsi.iloc[-2]
            
            # NaN 체크
            if pd.isna(current_rsi) or pd.isna(previous_rsi):
                return False
            
            # 매수 신호 조건들
            # 1. 과매도에서 회복 중 (RSI가 30 아래였다가 상승)
            oversold_recovery = (previous_rsi <= oversold_threshold and 
                                current_rsi > oversold_threshold and 
                                current_rsi < recovery_threshold)
            
            # 2. 매수 적정권 (RSI 30~50)
            buy_zone = (oversold_threshold <= current_rsi <= recovery_threshold)
            
            # 3. RSI 상승 추세 확인
            rsi_uptrend = current_rsi > previous_rsi
            
            # 조건: (과매도 회복 또는 매수 적정권) + RSI 상승 추세
            return (oversold_recovery or buy_zone) and rsi_uptrend
            
        except Exception as e:
            logger.error(f"❌ RSI 매수 신호 계산 오류: {e}")
            return False

    @staticmethod
    def is_macd_golden_cross(df, fast=12, slow=26, signal=9):
        """
        MACD 골든크로스 신호 감지
        - MACD 라인이 Signal 라인을 상향 돌파
        
        Args:
            df: 주가 데이터프레임
            fast: 단기 EMA 기간 (기본 12)
            slow: 장기 EMA 기간 (기본 26)
            signal: Signal 라인 기간 (기본 9)
        
        Returns:
            bool: MACD 골든크로스 여부
        """
        try:
            if df is None or df.empty or len(df) < slow + signal + 5:
                return False
            
            # 컬럼명 통일 처리
            price_col = None
            if 'stck_clpr' in df.columns:
                price_col = 'stck_clpr'
            elif 'stck_prpr' in df.columns:
                price_col = 'stck_prpr'
            else:
                return False
            
            close_prices = df[price_col].copy()
            
            # NaN 체크
            if close_prices.isnull().any():
                return False
            
            # MACD 계산
            ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
            ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
            
            # MACD Line = 단기 EMA - 장기 EMA
            macd_line = ema_fast - ema_slow
            
            # Signal Line = MACD의 EMA
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            
            if len(macd_line) < 2 or len(signal_line) < 2:
                return False
            
            # 오늘과 어제의 MACD, Signal 값
            today_macd = macd_line.iloc[-1]
            today_signal = signal_line.iloc[-1]
            yesterday_macd = macd_line.iloc[-2]
            yesterday_signal = signal_line.iloc[-2]
            
            # NaN 체크
            if (pd.isna(today_macd) or pd.isna(today_signal) or 
                pd.isna(yesterday_macd) or pd.isna(yesterday_signal)):
                return False
            
            # 골든크로스 조건
            # 1. 어제는 MACD가 Signal 아래
            # 2. 오늘은 MACD가 Signal 위로 돌파
            # 3. MACD가 상승 추세
            golden_cross = (
                yesterday_macd <= yesterday_signal and  # 어제는 아래
                today_macd > today_signal and           # 오늘은 위로 돌파
                today_macd > yesterday_macd             # MACD 상승 추세
            )
            
            # 추가 필터: 매수 시점 검증 (0선 근처 이하에서만 유효)
            # 너무 높은 곳에서의 골든크로스는 제외
            valid_position = today_signal <= 1000  # 적절한 임계값 설정
            
            # 거래량 확인 (선택사항)
            volume_col = 'acml_vol' if 'acml_vol' in df.columns else 'cntg_vol'
            if volume_col in df.columns and len(df) >= 10:
                avg_volume = df[volume_col].rolling(window=10).mean().iloc[-1]
                current_volume = df[volume_col].iloc[-1]
                volume_surge = current_volume > avg_volume * 1.1
                
                return golden_cross and valid_position and volume_surge
            else:
                return golden_cross and valid_position
            
        except Exception as e:
            logger.error(f"❌ MACD 골든크로스 계산 오류: {e}")
            return False

    @staticmethod
    def is_macd_near_golden_cross(df, fast=12, slow=26, signal=9, threshold=0.05):
        """
        MACD 골든크로스 근접 신호 감지
        - MACD 라인이 Signal 라인에 근접하면서 상승 중
        
        Args:
            df: 주가 데이터프레임
            threshold: 근접 판단 기준 (기본 5%)
        
        Returns:
            bool: MACD 골든크로스 근접 여부
        """
        try:
            if df is None or df.empty or len(df) < slow + signal + 5:
                return False
            
            # 컬럼명 통일 처리
            price_col = None
            if 'stck_clpr' in df.columns:
                price_col = 'stck_clpr'
            elif 'stck_prpr' in df.columns:
                price_col = 'stck_prpr'
            else:
                return False
            
            close_prices = df[price_col].copy()
            
            if close_prices.isnull().any():
                return False
            
            # MACD 계산
            ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
            ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            
            if len(macd_line) < 3:
                return False
            
            current_macd = macd_line.iloc[-1]
            current_signal = signal_line.iloc[-1]
            
            # NaN 체크
            if pd.isna(current_macd) or pd.isna(current_signal):
                return False
            
            # 1. MACD가 Signal 아래에 있어야 함
            if current_macd >= current_signal:
                return False
            
            # 2. 차이가 매우 작음 (근접 상태)
            diff = abs(current_macd - current_signal)
            signal_abs = abs(current_signal)
            is_close = (diff / max(signal_abs, 0.01) <= threshold) or (diff <= 50)
            
            # 3. MACD 상승 추세 확인
            macd_trend_up = False
            if len(macd_line) >= 3:
                macd_trend_up = (
                    macd_line.iloc[-1] > macd_line.iloc[-2] and 
                    macd_line.iloc[-2] >= macd_line.iloc[-3]
                )
            
            # 4. 히스토그램 개선 추세
            histogram_improving = False
            if len(macd_line) >= 3:
                hist_today = current_macd - current_signal
                hist_yesterday = macd_line.iloc[-2] - signal_line.iloc[-2]
                hist_2days_ago = macd_line.iloc[-3] - signal_line.iloc[-3]
                
                histogram_improving = (
                    hist_today > hist_yesterday and 
                    hist_yesterday > hist_2days_ago
                )
            
            return is_close and (macd_trend_up or histogram_improving)
            
        except Exception as e:
            logger.error(f"❌ MACD 근접 계산 오류: {e}")
            return False

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
    def is_price_below_ma20(df, name):
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
            
            logger.debug(f"{name}: {current_price}, {ma20_value}, {round(current_price/ma20_value*100,2)}% {distance_ratio}")
            logger.debug(f"{below_ma20}: {meaningful_distance}")
            return below_ma20 and meaningful_distance
            
        except Exception as e:
            logger.error(f"❌ 20일선 아래 위치 확인 오류: {e}")
            return False

    # 기존 다른 지표들 (변경 없음, 길이 제한으로 생략)
    @staticmethod
    def is_bollinger_rebound(df):
        """볼린저밴드 하한선 반등 신호"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            
            price_col = 'stck_clpr' if 'stck_clpr' in df.columns else 'stck_prpr'
            if price_col not in df.columns:
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
            
            volume_col = 'acml_vol' if 'acml_vol' in df.columns else 'cntg_vol'
            if volume_col not in df.columns:
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


def check_foreign_consecutive_buying(foreign_netbuy_list):
    """
    외국인 최근 연속 매수 확인 (절대조건용)
    - 최근 3일 연속 순매수 또는
    - 최근 2일 연속 순매수
    
    Args:
        foreign_netbuy_list: 외국인 순매수 리스트 (최신순, 즉 [오늘, 어제, 그제, ...])
        
    Returns:
        dict: {
            'meets_condition': bool - 절대조건 만족 여부,
            'consecutive_days': int - 연속 매수 일수,
            'reason': str - 판단 근거,
            'volumes': list - 해당 기간 거래량
        }
    """
    try:
        if not foreign_netbuy_list or len(foreign_netbuy_list) < 2:
            return {
                'meets_condition': False,
                'consecutive_days': 0,
                'reason': '데이터 부족 (최소 2일 필요)',
                'volumes': []
            }
        
        # 최근 3일 데이터 확인
        recent_3days = foreign_netbuy_list[:3] if len(foreign_netbuy_list) >= 3 else foreign_netbuy_list[:2]
        
        # 연속 매수일 카운트
        consecutive_buying = 0
        for volume in recent_3days:
            if volume > 0:
                consecutive_buying += 1
            else:
                break
        
        logger.debug(f"🌍 외국인 최근 데이터: {recent_3days[:3]}, 연속매수일: {consecutive_buying}")
        
        # 절대조건 판단
        if consecutive_buying >= 3:
            total_buy_volume = sum(recent_3days[:consecutive_buying])
            return {
                'meets_condition': True,
                'consecutive_days': consecutive_buying,
                'reason': f'최근 {consecutive_buying}일 연속 순매수 (총 {total_buy_volume:,}주)',
                'volumes': recent_3days[:consecutive_buying]
            }
        elif consecutive_buying >= 2:
            total_buy_volume = sum(recent_3days[:consecutive_buying])
            return {
                'meets_condition': True,
                'consecutive_days': consecutive_buying,
                'reason': f'최근 {consecutive_buying}일 연속 순매수 (총 {total_buy_volume:,}주)',
                'volumes': recent_3days[:consecutive_buying]
            }
        else:
            if len(recent_3days) > 0 and recent_3days[0] <= 0:
                return {
                    'meets_condition': False,
                    'consecutive_days': 0,
                    'reason': f'오늘 순매도 ({recent_3days[0]:,}주)',
                    'volumes': recent_3days
                }
            else:
                return {
                    'meets_condition': False,
                    'consecutive_days': 1,
                    'reason': f'연속성 없음 (오늘만 매수: {recent_3days[0]:,}주)',
                    'volumes': recent_3days
                }
                
    except Exception as e:
        logger.error(f"❌ 외국인 연속 매수 확인 오류: {e}")
        return {
            'meets_condition': False,
            'consecutive_days': 0,
            'reason': f'분석 오류: {e}',
            'volumes': []
        }


def get_comprehensive_analysis(df, foreign_netbuy_list=None, name=""):
    """
    종합 기술적 분석 (개선된 외국인 절대조건 포함)
    
    Returns:
        dict: 종합 분석 결과
    """
    try:
        analysis = {
            'meets_absolute_conditions': False,
            'price_below_ma20': False,
            'volume_sufficient': False,
            'foreign_consecutive_buying': None,
            'technical_signals': {},
            'recommendation': 'HOLD'
        }
        
        # 1. 절대조건 체크
        analysis['price_below_ma20'] = TechnicalIndicators.is_price_below_ma20(df, name)
        analysis['volume_sufficient'] = TechnicalIndicators.is_volume_sufficient(df, min_volume=1000)
        analysis['above_bollinger_lower'] = TechnicalIndicators.is_price_above_bollinger_lower(df)
        
        # 2. 외국인 연속 매수 체크
        if foreign_netbuy_list:
            foreign_check = check_foreign_consecutive_buying(foreign_netbuy_list)
            analysis['foreign_consecutive_buying'] = foreign_check
        
        # 3. 절대조건 종합 판단
        foreign_ok = True
        if analysis['foreign_consecutive_buying']:
            foreign_ok = analysis['foreign_consecutive_buying']['meets_condition']
        
        analysis['meets_absolute_conditions'] = (
            analysis['price_below_ma20'] and 
            analysis['volume_sufficient'] and
            analysis['above_bollinger_lower'] and
            foreign_ok
        )
        
        # 4. 기술적 신호들 (절대조건 통과시에만)
        if analysis['meets_absolute_conditions']:
            analysis['technical_signals'] = {
                'golden_cross': TechnicalIndicators.is_golden_cross(df),
                'bollinger_rebound': TechnicalIndicators.is_bollinger_rebound(df),
                'volume_breakout': TechnicalIndicators.is_volume_breakout(df),
                'ma5_crossing_above': TechnicalIndicators.is_ma5_crossing_above_ma20(df)
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
        logger.error(f"❌ 종합 기술적 분석 오류: {e}")
        return {
            'meets_absolute_conditions': False,
            'error': str(e)
        }


class SignalAnalyzer:
    """강화된 매수 신호 종합 분석 클래스"""
    
    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher
        self.ti = TechnicalIndicators()
    
    @staticmethod
    def calculate_buy_signal_score(df, name, code, foreign_trend=None, foreign_netbuy_list=None):
        """
        절대조건 필터링이 적용된 종합 매수 신호 점수 계산 (정적 메서드로 수정)
        
        Returns:
            tuple: (점수, 활성신호리스트, 절대조건통과여부, 제외사유)
        """
        try:
            if df is None or df.empty:
                return 0, [], False, "데이터 없음"
            
            # 1. 절대조건 체크
            absolute_check = get_comprehensive_analysis(df, foreign_netbuy_list, name)
            
            if not absolute_check['meets_absolute_conditions']:
                reasons = []
                if not absolute_check['price_below_ma20']:
                    reasons.append("현재가가 20일선 위")
                if not absolute_check.get('volume_sufficient', True):
                    reasons.append("거래량 1000주 미만")
                if not absolute_check.get('above_bollinger_lower', True):
                    reasons.append("볼린저밴드 하단 이탈")
                
                foreign_check = absolute_check.get('foreign_consecutive_buying')
                if foreign_check and not foreign_check['meets_condition']:
                    reasons.append(f"외국인({foreign_check['reason']})")
                
                return 0, [], False, " + ".join(reasons)
            
            # 2. 절대조건 통과시 상세 신호 분석
            foreign_check = absolute_check.get('foreign_consecutive_buying', {})
            consecutive_days = foreign_check.get('consecutive_days', 0)
            
            signals = {
                "골든크로스": TechnicalIndicators.is_golden_cross(df),
                "볼린저밴드복귀": TechnicalIndicators.is_bollinger_rebound(df),
                "거래량급증": TechnicalIndicators.is_volume_breakout(df),
                "5일선20일선돌파": TechnicalIndicators.is_ma5_crossing_above_ma20(df),
                "RSI매수신호": TechnicalIndicators.is_rsi_buy_signal(df),
                "MACD골든크로스": TechnicalIndicators.is_macd_golden_cross(df),
                "MACD돌파직전": TechnicalIndicators.is_macd_near_golden_cross(df),
                "볼린저밴드내위치": TechnicalIndicators.is_price_above_bollinger_lower(df)
            }
            
            if consecutive_days >= 3:
                signals["외국인강력매수"] = True
            
            score = sum(signals.values())
            active_signals = [key for key, value in signals.items() if value]
    
            return score, active_signals, True, "절대조건 모두 통과"
            
        except Exception as e:
            logger.error(f"❌ {name}: 매수 신호 점수 계산 오류: {e}")
            return 0, [], False, f"계산 오류: {e}"
    
    def get_individual_signals(self, df):
        """개별 기술적 신호들을 딕셔너리로 반환"""
        try:
            signals = {
                "골든크로스": self.ti.is_golden_cross(df),
                "볼린저밴드복귀": self.ti.is_bollinger_rebound(df),
                "거래량급증": self.ti.is_volume_breakout(df),
                "5일선20일선돌파": self.ti.is_ma5_crossing_above_ma20(df),
                "RSI매수신호": self.ti.is_rsi_buy_signal(df),
                "MACD골든크로스": self.ti.is_macd_golden_cross(df),
                "볼린저밴드내위치": self.ti.is_price_above_bollinger_lower(df),
                "MACD돌파직전": self.ti.is_macd_near_golden_cross(df), 
                "기관매수추세": False,
            }
            
            return signals
            
        except Exception as e:
            logger.error(f"개별 신호 분석 오류: {e}")
            return {key: False for key in signals.keys()}
