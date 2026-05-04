import sys
sys.path.insert(0, '/Users/jsshin/RESTAPI')
from analyze.utils import send_discord_message

webhook_url = 'https://discord.com/api/webhooks/1392715031149285420/cnDqqfbTc_dRrKSY2ZSlpznjXGVQLMBLn4cJ6CfriiGdkvX1Ly7WsjXLlPJJUdkcy1En'
webhook_url3 = 'https://discord.com/api/webhooks/1398285993458798592/vp7JtbavvOwduAgO4laIk8T2TOye_ZwkEtB59MPvqJmJJ7bjmpqxXmNVL_p8q65g4NKg'

message = (
    "\U0001f4f0 오늘의 영어 뉴스 학습 (2026년 05월 02일)\n\n"
    "\U0001f517 https://www.musi.co.kr/english-news/2026-05-02.html\n\n"
    "매일 아침 7시, 오늘의 시사 영어 기사로 하루를 시작하세요! \U0001f4d6"
)

result1 = send_discord_message(message, webhook_url)
result2 = send_discord_message(message, webhook_url3)
print(f'Webhook1: {result1}, Webhook3: {result2}')
