import requests
import time

webhook_url = 'https://discord.com/api/webhooks/1392715031149285420/cnDqqfbTc_dRrKSY2ZSlpznjXGVQLMBLn4cJ6CfriiGdkvX1Ly7WsjXLlPJJUdkcy1En'
webhook_url3 = 'https://discord.com/api/webhooks/1398285993458798592/vp7JtbavvOwduAgO4laIk8T2TOye_ZwkEtB59MPvqJmJJ7bjmpqxXmNVL_p8q65g4NKg'

message = (
    "📢 오늘의 여행 영어 회화가 업데이트됐습니다!\n"
    "🗓 2026-06-04 | 🍽️ 음식 알레르기 & 식이 제한 설명하기\n"
    "🔗 https://musi.co.kr/english-news/conv-2026-06-04.html\n\n"
    "💡 핵심 표현·어휘를 빠르게 두 번 탭하면 발음을 들을 수 있어요!"
)

def send_discord(msg, url):
    try:
        response = requests.post(url, json={"content": msg}, timeout=10)
        response.raise_for_status()
        print(f"✅ 전송 성공 ({url[-20:]}): {response.status_code}")
        return True
    except Exception as e:
        print(f"❌ 전송 실패: {e}")
        return False

r1 = send_discord(message, webhook_url)
time.sleep(0.5)
r2 = send_discord(message, webhook_url3)
print(f'Webhook1: {r1}, Webhook3: {r2}')
