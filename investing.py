import requests
from bs4 import BeautifulSoup

def fetch_strong_buy_kr():
    url = "https://kr.investing.com/technical/stocks-indicators"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    results = []
    sections = soup.select("div.js-technicalSummary")  # 각 종목 요약 블록

    for sec in sections:
        name_tag = sec.select_one("a.instrument")  # 종목명 요소 (예: NICE, PLNT)
        summary = sec.select_one("div.summary")    # 요약 텍스트 (예: '적극 매수')
        if not name_tag or not summary:
            continue
        name = name_tag.get_text(strip=True)
        signal = summary.get_text(strip=True)
        # '적극 매수' or English 'Strong buy' 포함 여부
        if "적극 매수" in signal or "Strong buy" in signal:
            results.append((name, signal))
    return results

if __name__ == "__main__":
    sb = fetch_strong_buy_kr()
    print("✅ 한국어 '강력 매수' 종목:")
    for name, sig in sb:
        print(f"- {name}: {sig}")
