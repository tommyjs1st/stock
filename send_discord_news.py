import urllib.request, json, os
from dotenv import load_dotenv

load_dotenv('/Users/jsshin/RESTAPI/.env')

webhook_url = os.getenv('DISCORD_WEBHOOK_URL3')
message = (
    "\U0001f4f0 오늘의 영어 뉴스 학습 (2026년 05월 02일)\n\n"
    "\U0001f517 https://www.musi.co.kr/english-news/2026-05-02.html\n\n"
    "매일 아침 7시, 오늘의 시사 영어 기사로 하루를 시작하세요! \U0001f4d6"
)

data = json.dumps({'content': message}).encode('utf-8')
req = urllib.request.Request(
    webhook_url,
    data=data,
    headers={'Content-Type': 'application/json'},
    method='POST'
)
try:
    with urllib.request.urlopen(req) as resp:
        print('Discord 전송 성공, Status:', resp.status)
except Exception as e:
    print('Discord 전송 실패:', e)
