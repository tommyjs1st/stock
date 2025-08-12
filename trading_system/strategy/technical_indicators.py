"""
기술적 지표 계산 모듈
"""
import pandas as pd
import numpy as np
from typing import Dict, Any


class TechnicalIndicators:
    """기술적 지표 계산 클래스"""
    
    @staticmethod
    def calculate_macd(df: pd.DataFrame, price_col: str = 'stck_prpr', 
                      fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        """MACD 지표 계산"""
        if len(df) < slow + signal:
            return df
        
        try:
            prices = df[price_col].astype(float)
            
            # EMA 계산
            ema_fast = prices.ewm(span=fast).mean()
            ema_slow = prices.ewm(span=slow).mean()
            
            # MACD 지표
            df['macd_line'] = ema_fast - ema_slow
            df['macd_signal'] = df['macd_line'].ewm(span=signal).mean()
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
            
        except Exception:
            return df
    
    @staticmethod
    def calculate_rsi(df: pd.DataFrame, price_col: str = 'stck_prpr', period: int = 14) -> pd.DataFrame:
        """RSI 계산"""
        try:
            delta = df[price_col].diff()
            gain = (delta.where(delta > 0, 0)).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            return df
        except Exception:
            return df
    
    @staticmethod
    def calculate_bollinger_bands(df: pd.DataFrame, price_col: str = 'stck_prpr', 
                                 period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
        """볼린저 밴드 계산"""
        try:
            df['bb_middle'] = df[price_col].rolling(period).mean()
            bb_std = df[price_col].rolling(period).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * std_dev)
            df['bb_lower'] = df['bb_middle'] - (bb_std * std_dev)
            return df
        except Exception:
            return df
    
    @staticmethod
    def calculate_moving_averages(df: pd.DataFrame, price_col: str = 'stck_prpr') -> pd.DataFrame:
        """이동평균선 계산"""
        try:
            df['ma5'] = df[price_col].rolling(5).mean()
            df['ma20'] = df[price_col].rolling(20).mean()
            df['ma60'] = df[price_col].rolling(60).mean()
            df['ma120'] = df[price_col].rolling(120).mean()
            return df
        except Exception:
            return df
    
    @staticmethod
    def calculate_stochastic(df: pd.DataFrame, high_col: str = 'stck_hgpr', 
                           low_col: str = 'stck_lwpr', close_col: str = 'stck_prpr',
                           k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
        """스토캐스틱 계산"""
        try:
            low_min = df[low_col].rolling(k_period).min()
            high_max = df[high_col].rolling(k_period).max()
            df['stoch_k'] = 100 * ((df[close_col] - low_min) / (high_max - low_min))
            df['stoch_d'] = df['stoch_k'].rolling(d_period).mean()
            return df
        except Exception:
            return df
    
    @staticmethod
    def detect_macd_golden_cross(df: pd.DataFrame, lookback: int = 3) -> Dict[str, Any]:
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
            recent_crosses = df['macd_cross'].tail(lookback)
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
            
        except Exception:
            return {
                'golden_cross': False,
                'cross_strength': 0,
                'signal_age': 999,
                'macd_above_zero': False
            }
    
    @staticmethod
    def is_golden_cross(df: pd.DataFrame) -> bool:
        """골든크로스 신호 감지"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            if 'stck_prpr' not in df.columns:
                return False
                
            df_copy = df.copy()
            df_copy["ma5"] = df_copy["stck_prpr"].rolling(window=5).mean()
            df_copy["ma20"] = df_copy["stck_prpr"].rolling(window=20).mean()
            
            if len(df_copy) < 2:
                return False
                
            today = df_copy.iloc[-1]
            yesterday = df_copy.iloc[-2]
            
            return (not pd.isna(today["ma5"]) and not pd.isna(today["ma20"]) and
                    not pd.isna(yesterday["ma5"]) and not pd.isna(yesterday["ma20"]) and
                    yesterday["ma5"] < yesterday["ma20"] and today["ma5"] > today["ma20"])
        except Exception:
            return False
    
    @staticmethod
    def is_bollinger_rebound(df: pd.DataFrame) -> bool:
        """볼린저밴드 반등 신호"""
        try:
            if df is None or df.empty or len(df) < 21:
                return False
            if 'stck_prpr' not in df.columns:
                return False
                
            df_copy = df.copy()
            df_copy["ma20"] = df_copy["stck_prpr"].rolling(window=20).mean()
            df_copy["stddev"] = df_copy["stck_prpr"].rolling(window=20).std()
            df_copy["lower_band"] = df_copy["ma20"] - 2 * df_copy["stddev"]

            if len(df_copy) < 2:
                return False
                
            today = df_copy.iloc[-1]
            yesterday = df_copy.iloc[-2]

            return (not pd.isna(yesterday["lower_band"]) and not pd.isna(today["lower_band"]) and
                    yesterday["stck_prpr"] < yesterday["lower_band"] and
                    today["stck_prpr"] > today["lower_band"])
        except Exception:
            return False
    
    @staticmethod
    def is_rsi_oversold_recovery(df: pd.DataFrame, period: int = 14, 
                               oversold_threshold: int = 30, recovery_threshold: int = 35) -> bool:
        """RSI 과매도 구간에서 회복 신호"""
        try:
            if df is None or df.empty or len(df) < period + 2:
                return False
            if 'stck_prpr' not in df.columns:
                return False
            
            df_with_rsi = TechnicalIndicators.calculate_rsi(df.copy())
            
            if 'rsi' not in df_with_rsi.columns or df_with_rsi['rsi'].isna().any() or len(df_with_rsi) < 2:
                return False
            
            # 전날 RSI가 과매도 구간이고, 오늘 회복 신호
            return (df_with_rsi['rsi'].iloc[-2] < oversold_threshold and 
                    df_with_rsi['rsi'].iloc[-1] > recovery_threshold)
        except Exception:
            return False
