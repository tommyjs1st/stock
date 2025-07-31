import requests
from bs4 import BeautifulSoup

# 대상 URL
URL = "https://corearoadbike.com/board/board.php?t_id=Menu01Top6&category=%25ED%258C%2590%25EB%25A7%25A4&category2=%25EB%2594%2594%25EC%258A%25A4%25ED%2581%25AC&sort=wr_2+desc"

# 키워드 목록
KEYWORDS = ["와스프로", "에어로드", "에어로드 cf", "waspro", "aeroad"]

# User-Agent 설정 (403 방지)
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def fetch_and_parse():
    response = requests.get(URL, headers=HEADERS)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, "html.parser")

    # 게시물 리스트 시작 지점: <form name="form_list">
    form = soup.find("form", {"name": "form_list"})
    if not form:
        print("게시물 리스트를 찾을 수 없습니다.")
        return

    rows = form.find_all("tr")
    results = []

    for row in rows:
        print(f"{row}")
        cols = row.find_all("td")
        if not cols or len(cols) < 2:
            continue

        # 제목 추출
        title_tag = cols[1].find("a")
        if title_tag:
            title = title_tag.get_text(strip=True)
            link = title_tag.get("href")
            for kw in KEYWORDS:
                if kw.lower() in title.lower():
                    results.append((title, link))
                    break

    # 결과 출력
    if results:
        print("🔍 키워드가 포함된 게시물:")
        for title, link in results:
            print(f"- {title}\n  ➤ 링크: https://corearoadbike.com{link}")
    else:
        print("키워드가 포함된 게시물을 찾지 못했습니다.")

if __name__ == "__main__":
    fetch_and_parse()
