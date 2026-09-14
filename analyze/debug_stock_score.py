"""
특정 종목 1개의 점수 계산 과정을 검증하기 위한 디버그 스크립트
- 로그 파일 없이 화면(print)에만 출력
- 최근 5거래일치 raw 지표값 테이블 출력 (직접 검산용)
- 최종 점수의 각 조건별 통과/실패 상세 출력

사용법:
  python debug_stock_score.py 105560
  python debug_stock_score.py 105560 --recent-days 10   # 최근 몇 일치 테이블을 보여줄지
"""
import os
import sys
import argparse

import yaml
import pandas as pd

from data_fetcher import DataFetcher
from scoring_indicators import enrich_all_indicators, PRICE_COL_CANDIDATES, VOLUME_COL_CANDIDATES, _get_col
from stock_scorer import StockScorer, MIN_REQUIRED_DAYS, classify_grade

CONFIG_PATH = "config.yaml"
DB_LOOKBACK_CALENDAR_DAYS = 400
API_LOOKBACK_TRADING_DAYS = 300


class PrintLogger:
    """DBManager 등이 요구하는 logger 인터페이스를 print로만 구현 (로그파일 없음)"""

    def info(self, msg):
        print(msg)

    def warning(self, msg):
        print(msg)

    def error(self, msg):
        print(msg)

    def debug(self, msg):
        pass


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_daily_data(data_fetcher, code, use_local_db):
    df = None
    if use_local_db:
        try:
            df = data_fetcher.get_daily_data_from_db(code, days=DB_LOOKBACK_CALENDAR_DAYS)
        except Exception as e:
            print(f"⚠️ DB 조회 실패, API로 전환: {e}")
            df = None

    if df is None or df.empty or len(df) < MIN_REQUIRED_DAYS:
        try:
            df = data_fetcher.get_period_price_data(code, days=API_LOOKBACK_TRADING_DAYS)
        except Exception as e:
            print(f"❌ API 조회 실패: {e}")

    return df


def print_recent_table(df, recent_days):
    price_col = _get_col(df, PRICE_COL_CANDIDATES)
    volume_col = _get_col(df, VOLUME_COL_CANDIDATES)

    cols = [
        "stck_bsop_date", price_col,
        "ma5", "ma20", "ma60", "ma120", "ma240",
        "rsi", "macd", "macd_signal",
        volume_col, "vol_ma20",
    ]
    table = df[cols].tail(recent_days).copy()

    # 보기 좋게 반올림
    for c in ["ma5", "ma20", "ma60", "ma120", "ma240", price_col]:
        table[c] = table[c].round(0)
    for c in ["rsi", "macd", "macd_signal"]:
        table[c] = table[c].round(2)
    table[volume_col] = table[volume_col].round(0)
    table["vol_ma20"] = table["vol_ma20"].round(0)

    table = table.rename(columns={
        "stck_bsop_date": "날짜",
        price_col: "종가",
        volume_col: "거래량",
    })

    print(f"\n📅 최근 {recent_days}거래일 지표 원본값")
    print("=" * 120)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(table.to_string(index=False))
    print("=" * 120)


def print_score_breakdown(current, price_col, volume_col):
    print("\n🔍 최종 점수 계산 상세 (기준일: 최신 거래일)")
    print("-" * 70)

    # 단기
    ma5, ma20 = current["ma5"], current["ma20"]
    ok = ma5 > ma20
    print(f"🔴 [단기] 5일선({ma5:,.0f}) > 20일선({ma20:,.0f}) "
          f"→ {'✅ 10점' if ok else '❌ 0점'}")

    rsi = current["rsi"]
    if rsi >= 50:
        pts, cond = 10, "RSI≥50"
    elif rsi >= 30:
        pts, cond = 5, "30≤RSI<50"
    else:
        pts, cond = 0, "RSI<30"
    print(f"🔴 [단기] RSI({rsi:.1f}) → {cond} → ✅ {pts}점")

    vol, vol_ma20 = current[volume_col], current["vol_ma20"]
    ok = vol > vol_ma20
    print(f"🔴 [단기] 거래량({vol:,.0f}) > 20일평균({vol_ma20:,.0f}) "
          f"→ {'✅ 10점' if ok else '❌ 0점'}")

    # 중기
    ma60 = current["ma60"]
    ok = ma20 > ma60
    print(f"🟡 [중기] 20일선({ma20:,.0f}) > 60일선({ma60:,.0f}) "
          f"→ {'✅ 15점' if ok else '❌ 0점'}")

    macd, macd_signal = current["macd"], current["macd_signal"]
    ok = macd > macd_signal
    print(f"🟡 [중기] MACD({macd:.2f}) > Signal({macd_signal:.2f}) "
          f"→ {'✅ 15점' if ok else '❌ 0점'}")

    # 장기
    price, ma120, ma240 = current[price_col], current["ma120"], current["ma240"]
    ok = price > ma120
    print(f"🟢 [장기] 현재가({price:,.0f}) > 120일선({ma120:,.0f}) "
          f"→ {'✅ 20점' if ok else '❌ 0점'}")

    ok = ma120 > ma240
    print(f"🟢 [장기] 120일선({ma120:,.0f}) > 240일선({ma240:,.0f}) "
          f"→ {'✅ 20점' if ok else '❌ 0점'}")

    print("-" * 70)


def main():
    parser = argparse.ArgumentParser(description="종목 1개 점수 계산 검증용 디버그 스크립트")
    parser.add_argument("code", type=str, help="검증할 종목코드 (예: 105560)")
    parser.add_argument("--recent-days", type=int, default=5, help="출력할 최근 거래일 수 (기본 5)")
    args = parser.parse_args()

    config = load_config()
    data_fetcher = DataFetcher()

    use_local_db = False
    db_manager = None
    db_config = config.get("database", {})
    if db_config:
        try:
            from db_manager import DBManager
            db_manager = DBManager(db_config, PrintLogger())
            if db_manager.connect():
                data_fetcher.set_db_manager(db_manager)
                use_local_db = True
                print("💾 일봉 데이터: 로컬 DB 사용")
            else:
                print("⚠️ DB 연결 실패 - API로 조회")
        except Exception as e:
            print(f"💡 로컬 DB 설정 스킵: {e}")

    print(f"\n🎯 검증 대상 종목코드: {args.code}")
    df = get_daily_data(data_fetcher, args.code, use_local_db)

    if df is None or df.empty:
        print("❌ 일봉 데이터를 가져올 수 없습니다.")
        sys.exit(1)

    print(f"📦 조회된 거래일 수: {len(df)}일 (필요: {MIN_REQUIRED_DAYS}일 이상)")

    if len(df) < MIN_REQUIRED_DAYS:
        print("❌ 데이터가 부족하여 스코어링 대상에서 제외되는 종목입니다.")
        sys.exit(1)

    df = enrich_all_indicators(df)
    price_col = _get_col(df, PRICE_COL_CANDIDATES)
    volume_col = _get_col(df, VOLUME_COL_CANDIDATES)

    print_recent_table(df, args.recent_days)

    current = df.iloc[-1]
    print_score_breakdown(current, price_col, volume_col)

    scorer = StockScorer()
    result = scorer.score_stock(df)

    if result is None:
        print("\n❌ 최신 행에 NaN 지표가 있어 최종 점수를 계산할 수 없습니다.")
        sys.exit(1)

    print(f"\n🏁 총점: {result['total_score']}점 / 100점  [{result['grade']}]")
    print(f"   🔴 단기 {result['short']['score']}/{result['short']['max']}"
          f"  🟡 중기 {result['mid']['score']}/{result['mid']['max']}"
          f"  🟢 장기 {result['long']['score']}/{result['long']['max']}")

    if db_manager:
        db_manager.disconnect()


if __name__ == "__main__":
    main()
