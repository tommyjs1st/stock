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
                'foreign_consecutive_buying': None,  # 🆕 변경
                'technical_signals': {},
                'recommendation': 'HOLD'
            }
            
            # 1. 절대조건 체크
            from technical_indicators import TechnicalIndicators
            analysis['price_below_ma20'] = TechnicalIndicators.is_price_below_ma20(df, name)
            analysis['volume_sufficient'] = TechnicalIndicators.is_volume_sufficient(df, min_volume=1000)
            analysis['above_bollinger_lower'] = TechnicalIndicators.is_price_above_bollinger_lower(df)
            
            # 2. 외국인 연속 매수 체크 (🆕 개선)
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
            print(f"❌ 종합 기술적 분석 오류: {e}")
            return {
                'meets_absolute_conditions': False,
                'error': str(e)
            }
    
    @staticmethod
    def analyze_foreign_buying_trend(foreign_netbuy_list, days=5):
        """
        외국인 매수 추세 분석 (절대조건용)
        
        Args:
            foreign_netbuy_list: 외국인 순매수 리스트 (최신순)
            days: 분석할 일수
            
        Returns:
            dict: 매수 추세 분석 결과
        """
        try:
            if not foreign_netbuy_list or len(foreign_netbuy_list) < 3:
                return {
                    'has_buying_trend': True,  # 데이터 없으면 통과 (보수적)
                    'trend_level': 'unknown',
                    'reason': '데이터 부족'
                }
            
            # 최근 N일 데이터 분석
            recent_data = foreign_netbuy_list[:days]
            
            # 매수일 계산
            buying_days = sum(1 for x in recent_data if x > 0)
            total_volume = sum(abs(x) for x in recent_data)
            net_volume = sum(recent_data)
            
            # 평균 일일 거래량
            avg_daily_volume = total_volume / len(recent_data) if recent_data else 0
            
            # 매수 비율
            buying_ratio = buying_days / len(recent_data)
            logger.debug(f"외국인 매수일: {buying_days}/{len(recent_data)}, 순매수: {net_volume:,}주")
            
            analysis_result = {
                'buying_days': buying_days,
                'total_days': len(recent_data),
                'buying_ratio': buying_ratio,
                'net_volume': net_volume,
                'avg_daily_volume': avg_daily_volume,
                'recent_data': recent_data
            }
            
            # 매수 추세 수준 분류
            if buying_ratio >= 0.6 and net_volume > 20000:  # 60% 이상 매수일 + 순매수 2만주 이상
                analysis_result.update({
                    'has_buying_trend': True,
                    'trend_level': 'strong',
                    'reason': f'{days}일중 {buying_days}일 매수 + 순매수 {net_volume:,}주'
                })
            elif buying_ratio >= 0.6 or net_volume > 10000:  # 60% 이상 매수일 또는 순매수 1만주 이상
                analysis_result.update({
                    'has_buying_trend': True,
                    'trend_level': 'moderate',
                    'reason': f'매수비율 {buying_ratio:.1%} 또는 순매수 {net_volume:,}주'
                })
            else:
                analysis_result.update({
                    'has_buying_trend': False,
                    'trend_level': 'weak',
                    'reason': f'매수 추세 약함 (매수일 {buying_days}/{days}일, 순매수 {net_volume:,}주)'
                })
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"외국인 매수 추세 분석 오류: {e}")
            return {
                'has_buying_trend': False,
                'trend_level': 'error',
                'reason': f'분석 오류: {e}'
            }

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
            
            # 최근 3일 데이터 확인 (리스트는 최신순: [오늘, 어제, 그제])
            recent_3days = foreign_netbuy_list[:3] if len(foreign_netbuy_list) >= 3 else foreign_netbuy_list[:2]
            
            # 연속 매수일 카운트 (최신일부터 역순으로 체크)
            consecutive_buying = 0
            for volume in recent_3days:
                if volume > 0:  # 순매수 (양수)
                    consecutive_buying += 1
                else:
                    break  # 매도일이 나오면 중단
            
            print(f"🌍 외국인 최근 데이터: {recent_3days[:3]}, 연속매수일: {consecutive_buying}")
            
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
                # 연속 매수가 아닌 경우
                if len(recent_3days) > 0 and recent_3days[0] <= 0:  # 오늘이 매도
                    return {
                        'meets_condition': False,
                        'consecutive_days': 0,
                        'reason': f'오늘 순매도 ({recent_3days[0]:,}주)',
                        'volumes': recent_3days
                    }
                else:  # 오늘은 매수지만 어제가 매도
                    return {
                        'meets_condition': False,
                        'consecutive_days': 1,
                        'reason': f'연속성 없음 (오늘만 매수: {recent_3days[0]:,}주, 어제 매도: {recent_3days[1]:,}주)',
                        'volumes': recent_3days
                    }
                    
        except Exception as e:
            print(f"❌ 외국인 연속 매수 확인 오류: {e}")
            return {
                'meets_condition': False,
                'consecutive_days': 0,
                'reason': f'분석 오류: {e}',
                'volumes': []
            }


class SignalAnalyzer:
    """강화된 매수 신호 종합 분석 클래스"""
    
    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher
        self.ti = TechnicalIndicators()
    
    def calculate_buy_signal_score(df, name, code, foreign_trend=None, foreign_netbuy_list=None):
        """
        절대조건 필터링이 적용된 종합 매수 신호 점수 계산 (개선된 외국인 조건)
        
        Returns:
            tuple: (점수, 활성신호리스트, 절대조건통과여부, 제외사유)
        """
        try:
            if df is None or df.empty:
                return 0, [], False, "데이터 없음"
            
            # 1. 절대조건 체크 먼저 수행
            absolute_check = get_comprehensive_analysis(df, foreign_netbuy_list, name)
            
            if not absolute_check['meets_absolute_conditions']:
                reasons = []
                if not absolute_check['price_below_ma20']:
                    reasons.append("현재가가 20일선 위")
                if not absolute_check.get('volume_sufficient', True):
                    reasons.append("거래량 1000주 미만")
                if not absolute_check.get('above_bollinger_lower', True):
                    reasons.append("볼린저밴드 하단 이탈")
                
                # 외국인 조건 체크 (🆕 개선)
                foreign_check = absolute_check.get('foreign_consecutive_buying')
                if foreign_check and not foreign_check['meets_condition']:
                    reasons.append(f"외국인({foreign_check['reason']})")
                
                return 0, [], False, " + ".join(reasons)
            
            # 2. 절대조건 통과시에만 상세 신호 분석
            from technical_indicators import TechnicalIndicators
            
            # 외국인 연속 매수 정보 추출
            foreign_check = absolute_check.get('foreign_consecutive_buying', {})
            consecutive_days = foreign_check.get('consecutive_days', 0)
            
            signals = {
                "골든크로스": TechnicalIndicators.is_golden_cross(df),
                "볼린저밴드복귀": TechnicalIndicators.is_bollinger_rebound(df),
                "거래량급증": TechnicalIndicators.is_volume_breakout(df),
                "현재가20일선아래": TechnicalIndicators.is_price_below_ma20(df, name),
                "5일선20일선돌파": TechnicalIndicators.is_ma5_crossing_above_ma20(df),
                "RSI매수신호": TechnicalIndicators.is_rsi_buy_signal(df),
                "MACD골든크로스": TechnicalIndicators.is_macd_golden_cross(df),
                "MACD돌파직전": TechnicalIndicators.is_macd_near_golden_cross(df),
                "볼린저밴드내위치": TechnicalIndicators.is_price_above_bollinger_lower(df),
                "외국인연속매수": consecutive_days >= 2  # 🆕 2일 이상 연속 매수
            }
            
            # 연속 매수 일수에 따른 추가 점수 (선택사항)
            if consecutive_days >= 3:
                signals["외국인강력매수"] = True  # 보너스 신호
            
            score = sum(signals.values())
            active_signals = [key for key, value in signals.items() if value]
    
            return score, active_signals, True, "절대조건 모두 통과"
            
        except Exception as e:
            print(f"❌ {name}: 매수 신호 점수 계산 오류: {e}")
            return 0, [], False, f"계산 오류: {e}"
    

    def get_individual_signals(self, df):
        """
        개별 기술적 신호들을 딕셔너리로 반환
        
        Args:
            df: 주가 데이터프레임
            
        Returns:
            dict: 각 신호의 활성화 여부
        """
        try:
            signals = {
                "골든크로스": self.ti.is_golden_cross(df),
                "볼린저밴드복귀": self.ti.is_bollinger_rebound(df),
                "거래량급증": self.ti.is_volume_breakout(df),
                "Williams%R회복": self.ti.is_williams_r_oversold_recovery(df),
                "이중바닥": self.ti.is_double_bottom_pattern(df),
                "일목균형표": self.ti.is_ichimoku_bullish_signal(df),
                "컵앤핸들": self.ti.is_cup_handle_pattern(df),
                "5일선20일선돌파": self.ti.is_ma5_crossing_above_ma20(df),
                "현재가20일선아래": self.ti.is_price_below_ma20(df,""),
                "RSI매수신호": self.ti.is_rsi_buy_signal(df),
                "MACD골든크로스": self.ti.is_macd_golden_cross(df),
                "볼린저밴드내위치": self.ti.is_price_above_bollinger_lower(df),
                "MACD돌파직전": self.ti.is_macd_near_golden_cross(df), 
                "외국인매수추세": False,  # 별도 처리 필요
                "기관매수추세": False,  # 별도 처리 필요
            }
            
            return signals
            
        except Exception as e:
            logger.error(f"개별 신호 분석 오류: {e}")
            return {key: False for key in [
                "골든크로스", "볼린저밴드복귀", "거래량급증", "Williams%R회복",
                "이중바닥", "일목균형표", "컵앤핸들", "5일선20일선돌파",
                "현재가20일선아래", "RSI매수신호", "MACD골든크로스", "MACD돌파직전",
                "볼린저밴드내위치", "외국인매수추세", "기관매수추세"
            ]}

