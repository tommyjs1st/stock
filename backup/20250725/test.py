import requests
from bs4 import BeautifulSoup
import pandas as pd

def get_top_market_cap_stocks(kosdaq=False, pages=1):
    """
    네이버 금융에서 시가총액 상위 종목을 가져옵니다.
    :param kosdaq: 코스닥이면 True, 코스피면 False
    :param pages: 몇 페이지까지 가져올지 (한 페이지에 50종목)
    :return: DataFrame
    """
    stocks = []
    market_type = 1 if kosdaq else 0  # 코스피=0, 코스닥=1

    for page in range(1, pages + 1):
        url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok={market_type}&page={page}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")

        table = soup.select_one("table.type_2")
        rows = table.select("tr")[2:]  # skip header rows

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 10:
                continue

            rank = len(stocks) + 1
            name = cols[1].text.strip()
            current_price = cols[2].text.strip()
            market_cap = cols[6].text.strip()

            stocks.append({
                "순위": rank,
                "종목명": name,
                "현재가": current_price,
                "시가총액(억원)": market_cap
            })

    return pd.DataFrame(stocks)

# 사용 예시
if __name__ == "__main__":
    df = get_top_market_cap_stocks(kosdaq=False, pages=6)  # 코스피 상위 100개
    print(df.head(10))  #

