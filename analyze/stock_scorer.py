"""
단기(30점) + 중기(30점) + 장기(40점) = 100점 만점 종목 종합 점수화 모듈

점수 구성
  🔴 단기 30점: 5일선>20일선(10) + RSI구간(10) + 거래량20일평균대비 증가(10)
  🟡 중기 30점: 20일선>60일선(15) + MACD>Signal(15)
  🟢 장기 40점: 현재가>120일선(20) + 120일선>240일선(20)
"""
import logging

from scoring_indicators import (
    enrich_all_indicators,
    PRICE_COL_CANDIDATES,
    VOLUME_COL_CANDIDATES,
    _get_col,
)

logger = logging.getLogger(__name__)

# MA240 계산 및 전일 대비 비교를 위해 필요한 최소 거래일 수
MIN_REQUIRED_DAYS = 241

GRADE_TABLE = [
    (80, 100, "🟢 강한 상승 추세"),
    (65, 79, "🟢 긍정적"),
    (50, 64, "🟡 관망"),
    (35, 49, "🟠 주의"),
    (0, 34, "🔴 하락 추세"),
]


def classify_grade(total_score):
    for low, high, label in GRADE_TABLE:
        if low <= total_score <= high:
            return label
    return "🔴 하락 추세"


class StockScorer:
    """개별 종목의 단기/중기/장기 지표를 계산해 100점 만점으로 점수화"""

    def score_stock(self, df):
        """
        Args:
            df: 일봉 데이터프레임 (날짜 오름차순 정렬, 최소 MIN_REQUIRED_DAYS 이상)

        Returns:
            dict: 점수 상세 결과. 데이터가 부족하거나 계산 불가능하면 None
                  (→ 호출부에서 "스코어링 대상에서 제외" 처리)
        """
        if df is None or df.empty:
            return None

        if len(df) < MIN_REQUIRED_DAYS:
            logger.debug(
                f"데이터 부족으로 스코어링 제외: {len(df)}일 (필요: {MIN_REQUIRED_DAYS}일)"
            )
            return None

        try:
            df = enrich_all_indicators(df)
        except ValueError as e:
            logger.debug(f"지표 계산 실패: {e}")
            return None

        price_col = _get_col(df, PRICE_COL_CANDIDATES)
        volume_col = _get_col(df, VOLUME_COL_CANDIDATES)

        current = df.iloc[-1]

        required_fields = [
            "ma5", "ma20", "ma60", "ma120", "ma240",
            "rsi", "macd", "macd_signal", "vol_ma20",
        ]
        if current[required_fields].isnull().any():
            logger.debug("최신 행에 NaN 지표가 있어 스코어링 제외")
            return None

        # ---------- 🔴 단기 (30점) ----------
        ma5_gt_ma20 = bool(current["ma5"] > current["ma20"])
        short_trend_score = 10 if ma5_gt_ma20 else 0

        rsi_value = float(current["rsi"])
        if rsi_value >= 50:
            rsi_score = 10
        elif rsi_value >= 30:
            rsi_score = 5
        else:
            rsi_score = 0

        volume_up = bool(current[volume_col] > current["vol_ma20"])
        volume_score = 10 if volume_up else 0

        short_total = short_trend_score + rsi_score + volume_score

        # ---------- 🟡 중기 (30점) ----------
        ma20_gt_ma60 = bool(current["ma20"] > current["ma60"])
        mid_trend_score = 15 if ma20_gt_ma60 else 0

        macd_gt_signal = bool(current["macd"] > current["macd_signal"])
        macd_score = 15 if macd_gt_signal else 0

        mid_total = mid_trend_score + macd_score

        # ---------- 🟢 장기 (40점) ----------
        price_gt_ma120 = bool(current[price_col] > current["ma120"])
        price_score = 20 if price_gt_ma120 else 0

        ma120_gt_ma240 = bool(current["ma120"] > current["ma240"])
        long_trend_score = 20 if ma120_gt_ma240 else 0

        long_total = price_score + long_trend_score

        total_score = short_total + mid_total + long_total

        return {
            "total_score": total_score,
            "grade": classify_grade(total_score),
            "current_price": float(current[price_col]),
            "short": {
                "score": short_total,
                "max": 30,
                "ma5_gt_ma20": short_trend_score,
                "rsi": rsi_score,
                "rsi_value": round(rsi_value, 1),
                "volume": volume_score,
            },
            "mid": {
                "score": mid_total,
                "max": 30,
                "ma20_gt_ma60": mid_trend_score,
                "macd_gt_signal": macd_score,
            },
            "long": {
                "score": long_total,
                "max": 40,
                "price_gt_ma120": price_score,
                "ma120_gt_ma240": long_trend_score,
            },
        }
