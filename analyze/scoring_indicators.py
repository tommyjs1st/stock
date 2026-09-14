"""
단기/중기/장기 종합 점수화를 위한 기술적 지표 계산 모듈
- 5/20/60/120/240일 이동평균
- RSI(14)
- MACD(12,26,9)
- 거래량 20일 이동평균

기존 analyze/technical_indicators.py 의 컬럼 처리 방식(stck_clpr/stck_prpr,
acml_vol/cntg_vol 컬럼명 통일 처리)을 그대로 따릅니다.
"""
import logging

logger = logging.getLogger(__name__)

PRICE_COL_CANDIDATES = ["stck_clpr", "stck_prpr"]
VOLUME_COL_CANDIDATES = ["acml_vol", "cntg_vol"]


def _get_col(df, candidates):
    """df 컬럼 중 candidates에 해당하는 첫 번째 컬럼명을 반환"""
    for col in candidates:
        if col in df.columns:
            return col
    return None


def calculate_moving_averages(df, periods=(5, 20, 60, 120, 240)):
    """종가 기준 이동평균선 계산 (df에 ma{N} 컬럼 추가)"""
    price_col = _get_col(df, PRICE_COL_CANDIDATES)
    if price_col is None:
        raise ValueError("종가 컬럼(stck_clpr/stck_prpr)을 찾을 수 없습니다.")

    df = df.copy()
    for period in periods:
        df[f"ma{period}"] = df[price_col].rolling(window=period).mean()
    return df


def calculate_rsi(df, period=14):
    """RSI(period) 계산 (df에 rsi 컬럼 추가)"""
    price_col = _get_col(df, PRICE_COL_CANDIDATES)
    if price_col is None:
        raise ValueError("종가 컬럼(stck_clpr/stck_prpr)을 찾을 수 없습니다.")

    df = df.copy()
    delta = df[price_col].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    # 0으로 나누기 방지 (기존 technical_indicators.py 방식과 동일)
    rs = gain / loss.replace(0, 0.0001)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def calculate_macd(df, fast=12, slow=26, signal=9):
    """MACD Line / Signal Line 계산 (df에 macd, macd_signal 컬럼 추가)"""
    price_col = _get_col(df, PRICE_COL_CANDIDATES)
    if price_col is None:
        raise ValueError("종가 컬럼(stck_clpr/stck_prpr)을 찾을 수 없습니다.")

    df = df.copy()
    ema_fast = df[price_col].ewm(span=fast, adjust=False).mean()
    ema_slow = df[price_col].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    return df


def calculate_volume_ma(df, period=20):
    """거래량 이동평균 계산 (df에 vol_ma{N} 컬럼 추가)"""
    volume_col = _get_col(df, VOLUME_COL_CANDIDATES)
    if volume_col is None:
        raise ValueError("거래량 컬럼(acml_vol/cntg_vol)을 찾을 수 없습니다.")

    df = df.copy()
    df[f"vol_ma{period}"] = df[volume_col].rolling(window=period).mean()
    return df


def enrich_all_indicators(df):
    """단기/중기/장기 점수화에 필요한 모든 지표를 한 번에 계산해서 반환"""
    df = calculate_moving_averages(df)
    df = calculate_rsi(df)
    df = calculate_macd(df)
    df = calculate_volume_ma(df, period=20)
    return df
