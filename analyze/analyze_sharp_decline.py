"""
시가총액 상위 200개 종목의 일 하락폭 15% 이상 케이스 분석

DB에 저장된 일봉 데이터를 기반으로 급락 케이스를 분석합니다.
"""
import pymysql
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List
import yaml


def load_config():
    """config.yaml에서 DB 설정 로드"""
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config.get('database', {})
    except Exception as e:
        print(f"❌ 설정 파일 로드 실패: {e}")
        return None


def get_db_connection(db_config):
    """DB 연결 생성"""
    try:
        conn = pymysql.connect(
            host=db_config.get('host', 'localhost'),
            port=db_config.get('port', 3306),
            user=db_config.get('user'),
            password=db_config.get('password'),
            database=db_config.get('database'),
            charset=db_config.get('charset', 'utf8mb4'),
            cursorclass=pymysql.cursors.DictCursor
        )
        print("✅ 데이터베이스 연결 성공")
        return conn
    except Exception as e:
        print(f"❌ 데이터베이스 연결 실패: {e}")
        return None


def get_kospi_stock_codes():
    """네이버 금융에서 코스피 종목 코드 리스트 가져오기"""
    try:
        import requests
        from bs4 import BeautifulSoup

        print("\n📋 코스피 종목 리스트 조회 중...")
        kospi_codes = set()

        for page in range(1, 50):  # 충분한 페이지 수
            url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok=0&page={page}"
            headers = {"User-Agent": "Mozilla/5.0"}

            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("table.type_2 tr")

            if not rows:
                break

            for row in rows:
                link = row.select_one("a.tltle")
                if link:
                    href = link["href"]
                    code = href.split("=")[-1]
                    kospi_codes.add(code)

            import time
            time.sleep(0.2)

        print(f"✅ 코스피 종목 {len(kospi_codes)}개 조회 완료")
        return kospi_codes

    except Exception as e:
        print(f"❌ 코스피 종목 리스트 조회 실패: {e}")
        return set()


def analyze_sharp_declines(conn, top_n=200, decline_threshold=-15.0, market_filter='ALL'):
    """
    시가총액 상위 N개 종목의 급락 케이스 분석

    Args:
        conn: DB 연결 객체
        top_n: 상위 몇 개 종목을 분석할지 (기본 200)
        decline_threshold: 하락 임계값 (기본 -15.0%)
        market_filter: 시장 필터 ('ALL', 'KOSPI', 'KOSDAQ')

    Returns:
        DataFrame: 급락 케이스 분석 결과
    """
    try:
        cursor = conn.cursor()

        # 코스피 필터링이 필요한 경우
        kospi_codes = None
        if market_filter == 'KOSPI':
            kospi_codes = get_kospi_stock_codes()
            if not kospi_codes:
                print("⚠️ 코스피 종목 리스트를 가져올 수 없습니다.")
                return None

        # 1. 시가총액 상위 종목 조회
        # stock_info의 market_cap과 최근 거래대금을 조합해서 상위 종목 선정
        market_name = "코스피 " if market_filter == 'KOSPI' else ""
        print(f"\n📊 {market_name}시가총액 상위 {top_n}개 종목 조회 중...")

        # 코스피 필터링을 위한 조건 추가
        kospi_filter = ""
        if kospi_codes:
            placeholders = ','.join([f"'{code}'" for code in kospi_codes])
            kospi_filter = f"AND si.stock_code IN ({placeholders})"

        sql_top_stocks = f"""
        SELECT
            stock_code,
            stock_name,
            market_cap,
            avg_trading_value
        FROM (
            SELECT
                si.stock_code,
                si.stock_name,
                si.market_cap,
                AVG(dsp.trading_value) as avg_trading_value,
                COUNT(dsp.trade_date) as data_count
            FROM stock_info si
            INNER JOIN daily_stock_prices dsp ON si.stock_code = dsp.stock_code
            WHERE dsp.trade_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
              AND dsp.close_price IS NOT NULL
              {kospi_filter}
            GROUP BY si.stock_code, si.stock_name, si.market_cap
            HAVING data_count >= 10
        ) as stock_stats
        ORDER BY
            COALESCE(market_cap, avg_trading_value, 0) DESC
        LIMIT %s
        """

        cursor.execute(sql_top_stocks, (top_n,))
        top_stocks = cursor.fetchall()

        if not top_stocks:
            print("⚠️ 데이터가 있는 종목이 없습니다.")
            return None

        stock_codes = [stock['stock_code'] for stock in top_stocks]
        stock_info = {stock['stock_code']: stock['stock_name'] for stock in top_stocks}

        print(f"✅ {len(stock_codes)}개 종목 조회 완료")

        # 2. 일봉 데이터 조회 및 변동률 계산
        print(f"\n📈 일봉 데이터 조회 및 변동률 계산 중...")

        placeholders = ','.join(['%s'] * len(stock_codes))
        sql_daily_data = f"""
        SELECT
            stock_code,
            trade_date,
            close_price,
            volume,
            trading_value
        FROM daily_stock_prices
        WHERE stock_code IN ({placeholders})
          AND close_price IS NOT NULL
        ORDER BY stock_code, trade_date
        """

        cursor.execute(sql_daily_data, stock_codes)
        daily_data = cursor.fetchall()

        if not daily_data:
            print("⚠️ 일봉 데이터가 없습니다.")
            return None

        print(f"✅ {len(daily_data)}건의 일봉 데이터 조회 완료")

        # 3. DataFrame 변환 및 변동률 계산
        df = pd.DataFrame(daily_data)

        # change_rate가 없는 경우 직접 계산
        print(f"\n🔍 일별 변동률 계산 중...")

        decline_cases = []

        for stock_code in stock_codes:
            stock_df = df[df['stock_code'] == stock_code].sort_values('trade_date').reset_index(drop=True)

            if len(stock_df) < 2:
                continue

            # 전일 대비 변동률 계산
            for i in range(1, len(stock_df)):
                prev_close = stock_df.loc[i-1, 'close_price']
                curr_close = stock_df.loc[i, 'close_price']

                if prev_close and curr_close and prev_close > 0:
                    # 변동률 = (당일 종가 - 전일 종가) / 전일 종가 * 100
                    change_pct = ((curr_close - prev_close) / prev_close) * 100

                    # 15% 이상 하락한 경우
                    if change_pct <= decline_threshold:
                        decline_cases.append({
                            'stock_code': stock_code,
                            'stock_name': stock_info.get(stock_code, 'Unknown'),
                            'trade_date': stock_df.loc[i, 'trade_date'],
                            'prev_close': prev_close,
                            'curr_close': curr_close,
                            'change_pct': round(change_pct, 2),
                            'volume': stock_df.loc[i, 'volume'],
                            'trading_value': stock_df.loc[i, 'trading_value']
                        })

        # 4. 결과 DataFrame 생성
        if not decline_cases:
            print(f"\n✅ {decline_threshold}% 이상 하락한 케이스가 없습니다.")
            return pd.DataFrame()

        result_df = pd.DataFrame(decline_cases)
        result_df = result_df.sort_values(['change_pct', 'trade_date'], ascending=[True, False]).reset_index(drop=True)

        return result_df

    except Exception as e:
        print(f"❌ 분석 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        cursor.close()


def print_analysis_result(df, decline_threshold=-15.0):
    """분석 결과 출력"""
    if df is None or df.empty:
        print(f"\n📊 분석 결과: {decline_threshold}% 이상 하락한 케이스가 없습니다.")
        return

    print("\n" + "="*100)
    print(f"📊 일 하락폭 {decline_threshold}% 이상 케이스 분석 결과")
    print("="*100)

    # 전체 통계
    total_cases = len(df)
    unique_stocks = df['stock_code'].nunique()
    avg_decline = df['change_pct'].mean()
    max_decline = df['change_pct'].min()

    print(f"\n📈 전체 통계:")
    print(f"  - 총 급락 케이스: {total_cases}건")
    print(f"  - 해당 종목 수: {unique_stocks}개")
    print(f"  - 평균 하락률: {avg_decline:.2f}%")
    print(f"  - 최대 하락률: {max_decline:.2f}%")

    # 기간별 분석
    if 'trade_date' in df.columns:
        df['year'] = pd.to_datetime(df['trade_date']).dt.year
        yearly_counts = df.groupby('year').size()

        print(f"\n📅 연도별 급락 케이스:")
        for year, count in yearly_counts.items():
            print(f"  - {year}년: {count}건")

    # 종목별 급락 횟수
    stock_counts = df.groupby(['stock_code', 'stock_name']).size().reset_index(name='count')
    stock_counts = stock_counts.sort_values('count', ascending=False)

    print(f"\n🏢 종목별 급락 횟수 (상위 10개):")
    for idx, row in stock_counts.head(10).iterrows():
        print(f"  {idx+1}. {row['stock_name']}({row['stock_code']}): {row['count']}회")

    # 최근 급락 케이스 (상위 10개)
    print(f"\n🔥 최근 급락 케이스 (상위 10개):")
    print(f"{'날짜':<12} {'종목명':<15} {'코드':<8} {'전일종가':>10} {'당일종가':>10} {'하락률':>8} {'거래량':>15}")
    print("-" * 100)

    for idx, row in df.head(10).iterrows():
        trade_date = row['trade_date'].strftime('%Y-%m-%d') if isinstance(row['trade_date'], datetime) else str(row['trade_date'])
        volume_str = f"{row['volume']:,}" if row['volume'] else 'N/A'

        print(f"{trade_date:<12} {row['stock_name']:<15} {row['stock_code']:<8} "
              f"{row['prev_close']:>10,} {row['curr_close']:>10,} "
              f"{row['change_pct']:>7.2f}% {volume_str:>15}")

    print("\n" + "="*100)

    # CSV 저장
    output_file = f"sharp_decline_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n💾 전체 결과가 '{output_file}' 파일로 저장되었습니다.")


def main():
    """메인 실행 함수"""
    print("="*100)
    print("📊 코스피 시가총액 상위 200개 종목의 급락 케이스 분석")
    print("="*100)

    # 설정 로드
    db_config = load_config()
    if not db_config:
        return

    # DB 연결
    conn = get_db_connection(db_config)
    if not conn:
        return

    try:
        # 분석 실행
        decline_threshold = -15.0  # 15% 하락
        top_n = 200  # 상위 200개 종목
        market_filter = 'KOSPI'  # 코스피만

        result_df = analyze_sharp_declines(
            conn,
            top_n=top_n,
            decline_threshold=decline_threshold,
            market_filter=market_filter
        )

        # 결과 출력
        print_analysis_result(result_df, decline_threshold=decline_threshold)

    finally:
        conn.close()
        print("\n✅ 데이터베이스 연결 종료")


if __name__ == "__main__":
    main()
