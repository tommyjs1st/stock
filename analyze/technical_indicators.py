"""
기술적 지표 분석 모듈
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
    def is_golden_cross(df):
        """골든크로스 신호 감지 (5일선이 20일선을 상향 돌파)"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            if 'stck_clpr' not in df.columns:
                return False
                
            df = df.copy()
            df["ma5"] = df["stck_clpr"].rolling(window=5).mean()
            df["ma20"] = df["stck_clpr"].rolling(window=20).mean()
            
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
    def is_bollinger_rebound(df):
        """볼린저밴드 하한선 반등 신호"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            if 'stck_clpr' not in df.columns:
                return False
                
            df = df.copy()
            df["ma20"] = df["stck_clpr"].rolling(window=20).mean()
            df["stddev"] = df["stck_clpr"].rolling(window=20).std()
            df["lower_band"] = df["ma20"] - 2 * df["stddev"]

            if len(df) < 2:
                return False
                
            today = df.iloc[-1]
            yesterday = df.iloc[-2]

            return (not pd.isna(yesterday["lower_band"]) and not pd.isna(today["lower_band"]) and
                    yesterday["stck_clpr"] < yesterday["lower_band"] and
                    today["stck_clpr"] > today["lower_band"])
        except Exception as e:
            logger.error(f"❌ 볼린저밴드 계산 오류: {e}")
            return False

    @staticmethod
    def is_macd_signal_cross(df):
        """MACD 신호선 상향 교차"""
        try:
            if df is None or df.empty or len(df) < 35:
                return False
            if 'stck_clpr' not in df.columns:
                return False
            
            close = df["stck_clpr"]
            
            # pandas_ta가 있으면 사용, 없으면 수동 계산
            if HAS_PANDAS_TA:
                macd_result = ta.macd(close, fast=12, slow=26, signal=9)
                
                if macd_result is None or macd_result.isna().any().any():
                    return False
                
                macd = macd_result["MACD_12_26_9"]
                signal = macd_result["MACDs_12_26_9"]
            else:
                # 수동 MACD 계산
                ema12 = close.ewm(span=12).mean()
                ema26 = close.ewm(span=26).mean()
                macd = ema12 - ema26
                signal = macd.ewm(span=9).mean()

            if len(macd) < 2:
                return False
                
            return (macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1])
        except Exception as e:
            logger.error(f"❌ MACD 계산 오류: {e}")
            return False

    @staticmethod
    def is_macd_golden_cross(df):
        """MACD 골든크로스 신호 감지 (개선된 버전)"""
        try:
            if df is None or df.empty or len(df) < 35:
                return False
            if 'stck_clpr' not in df.columns:
                return False
            
            close_prices = df['stck_clpr'].copy()
            
            if close_prices.isnull().any():
                return False
            
            # 표준 MACD 계산 (12일 EMA - 26일 EMA)
            ema_12 = close_prices.ewm(span=8, adjust=False).mean()
            ema_26 = close_prices.ewm(span=18, adjust=False).mean()
            macd_line = ema_12 - ema_26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            
            if len(macd_line) < 2:
                return False
            
            # 오늘과 어제의 MACD, Signal 값
            today_macd = macd_line.iloc[-1]
            today_signal = signal_line.iloc[-1]
            yesterday_macd = macd_line.iloc[-2]
            yesterday_signal = signal_line.iloc[-2]
            
            # 골든크로스 조건
            golden_cross_today = (
                yesterday_macd <= yesterday_signal and  # 어제는 아래
                today_macd > today_signal and          # 오늘은 위로 돌파
                today_macd > yesterday_macd            # MACD가 상승 추세
            )
            
            # 매수 구간에서만 유효 (0선 근처 이하)
            valid_cross = today_signal <= 0.2
            
            # 거래량 증가 확인 (데이터 충분할 때)
            if len(df) >= 50:
                volume_surge = df.iloc[-1]["acml_vol"] > df["acml_vol"].tail(10).mean() * 1.1
                return golden_cross_today and valid_cross and volume_surge
            else:
                return golden_cross_today and valid_cross
                
        except Exception as e:
            logger.error(f"❌ MACD 골든크로스 계산 오류: {e}")
            return False

    @staticmethod
    def is_rsi_oversold_recovery(df, period=14, oversold_threshold=30, recovery_threshold=35):
        """RSI 과매도 구간에서 회복 신호"""
        try:
            if df is None or df.empty or len(df) < period + 2:
                return False
            if 'stck_clpr' not in df.columns:
                return False
            
            if HAS_PANDAS_TA:
                rsi = ta.rsi(df["stck_clpr"], length=period)
            else:
                # 수동 RSI 계산
                delta = df["stck_clpr"].diff()
                gain = delta.where(delta > 0, 0).rolling(window=period).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
            
            if rsi is None or rsi.isna().any() or len(rsi) < 2:
                return False
            
            return (rsi.iloc[-2] < oversold_threshold and 
                    rsi.iloc[-1] > recovery_threshold)
        except Exception as e:
            logger.error(f"❌ RSI 계산 오류: {e}")
            return False

    @staticmethod
    def is_stochastic_oversold_recovery(df, k_period=14, d_period=3, oversold_threshold=20):
        """스토캐스틱 과매도 구간에서 회복 신호"""
        try:
            if df is None or df.empty or len(df) < k_period + d_period + 2:
                return False
            required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
            if not all(col in df.columns for col in required_cols):
                return False
            
            if HAS_PANDAS_TA:
                stoch = ta.stoch(df["stck_hgpr"], df["stck_lwpr"], df["stck_clpr"], 
                                 k=k_period, d=d_period)
                
                if stoch is None or stoch.isna().any().any():
                    return False
                
                stoch_k = stoch[f"STOCHk_{k_period}_{d_period}_3"]
                stoch_d = stoch[f"STOCHd_{k_period}_{d_period}_3"]
            else:
                # 수동 스토캐스틱 계산
                high = df["stck_hgpr"]
                low = df["stck_lwpr"]
                close = df["stck_clpr"]
                
                lowest_low = low.rolling(window=k_period).min()
                highest_high = high.rolling(window=k_period).max()
                
                stoch_k = 100 * (close - lowest_low) / (highest_high - lowest_low)
                stoch_d = stoch_k.rolling(window=d_period).mean()
            
            if len(stoch_k) < 2:
                return False
            
            # %K가 %D를 상향 돌파하면서 과매도 구간에서 벗어날 때
            return (stoch_k.iloc[-2] < stoch_d.iloc[-2] and 
                    stoch_k.iloc[-1] > stoch_d.iloc[-1] and
                    stoch_k.iloc[-1] < oversold_threshold + 10)
        except Exception as e:
            logger.error(f"❌ 스토캐스틱 계산 오류: {e}")
            return False

    @staticmethod
    def is_volume_breakout(df, volume_period=20, volume_multiplier=2.0):
        """거래량 급증 신호"""
        try:
            if df is None or df.empty or len(df) < volume_period + 1:
                return False
            if 'acml_vol' not in df.columns:
                return False
            
            avg_volume = df["acml_vol"].rolling(window=volume_period).mean()
            today_volume = df["acml_vol"].iloc[-1]
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


class SignalAnalyzer:
    """매수 신호 종합 분석 클래스"""
    
    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher
        self.ti = TechnicalIndicators()
    
    def calculate_buy_signal_score(self, df, name, code, foreign_trend=None):
        """종합 매수 신호 점수 계산"""
        try:
            if df is None or df.empty:
                return 0, []
            
            # 기관 매수 추세 확인
            institution_netbuy, institution_trend = self.data_fetcher.get_institution_netbuy_trend(code)
            is_institution_positive = institution_trend in ("steady_buying", "accumulating")
            
            signals = {
                "골든크로스": self.ti.is_golden_cross(df),
                "볼린저밴드복귀": self.ti.is_bollinger_rebound(df),
                "MACD상향돌파": self.ti.is_macd_signal_cross(df),
                "RSI과매도회복": self.ti.is_rsi_oversold_recovery(df),
                "스토캐스틱회복": self.ti.is_stochastic_oversold_recovery(df),
                "거래량급증": self.ti.is_volume_breakout(df),
                "Williams%R회복": self.ti.is_williams_r_oversold_recovery(df),
                "이중바닥": self.ti.is_double_bottom_pattern(df),
                "일목균형표": self.ti.is_ichimoku_bullish_signal(df),
                "컵앤핸들": self.ti.is_cup_handle_pattern(df),
                "MACD골든크로스": self.ti.is_macd_golden_cross(df),
                "외국인매수추세": foreign_trend == "steady_buying",
                "기관매수추세": is_institution_positive
            }

            score = sum(signals.values())
            active_signals = [key for key, value in signals.items() if value]

            return score, active_signals
        except Exception as e:
            logger.error(f"❌ {name}: 매수 신호 점수 계산 오류: {e}")
            return 0, []
    
    def get_individual_signals(self, df):
        """개별 신호 체크 결과 반환"""
        signals = {}
        if df is None or df.empty:
            return signals
        
        signals["골든크로스"] = self.ti.is_golden_cross(df)
        signals["볼린저밴드복귀"] = self.ti.is_bollinger_rebound(df)
        signals["MACD상향돌파"] = self.ti.is_macd_signal_cross(df)
        signals["RSI과매도회복"] = self.ti.is_rsi_oversold_recovery(df)
        signals["스토캐스틱회복"] = self.ti.is_stochastic_oversold_recovery(df)
        signals["거래량급증"] = self.ti.is_volume_breakout(df)
        signals["Williams%R회복"] = self.ti.is_williams_r_oversold_recovery(df)
        signals["이중바닥"] = self.ti.is_double_bottom_pattern(df)
        signals["일목균형표"] = self.ti.is_ichimoku_bullish_signal(df)
        signals["컵앤핸들"] = self.ti.is_cup_handle_pattern(df)
        signals["MACD골든크로스"] = self.ti.is_macd_golden_cross(df)
        
        return signals


def passes_fundamental_filters(data):
    """기본적 분석 필터 통과 여부"""
    try:
        per = data.get("PER")
        roe = data.get("ROE")
        debt_ratio = data.get("부채비율")
        
        # None 값이 있으면 해당 조건은 무시
        conditions = []
        if per is not None:
            conditions.append(per < 80)
        if roe is not None:
            conditions.append(roe > 1)
        if debt_ratio is not None:
            conditions.append(debt_ratio < 500)
        
        # 최소 하나 이상의 조건이 있고 모두 통과해야 함
        return len(conditions) > 0 and all(conditions)
    except Exception:
        return False
