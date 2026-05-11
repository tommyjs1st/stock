import sys
sys.path.insert(0, '/Users/jsshin/RESTAPI')
from analyze.utils import send_discord_message

webhook_url = 'https://discord.com/api/webhooks/1392715031149285420/cnDqqfbTc_dRrKSY2ZSlpznjXGVQLMBLn4cJ6CfriiGdkvX1Ly7WsjXLlPJJUdkcy1En'
webhook_url3 = 'https://discord.com/api/webhooks/1398285993458798592/vp7JtbavvOwduAgO4laIk8T2TOye_ZwkEtB59MPvqJmJJ7bjmpqxXmNVL_p8q65g4NKg'

message = (
    "\uc624\ub298\uc758 \uc5ec\ud589 \uc601\uc5b4 \u2708\ufe0f\n"
    "\uc8fc\uc81c: \uc57c\uc2dc\uc7a5/\ud478\ub4dc\ucf54\ud2b8\uc5d0\uc11c \uc606 \ud14c\uc774\ube14 \uc5ec\ud589\uc790\uc640 \uc74c\uc2dd \ucd94\ucc9c\n"
    "\U0001f517 https://www.musi.co.kr/english-news/conv-2026-05-07.html"
)

result1 = send_discord_message(message, webhook_url)
result2 = send_discord_message(message, webhook_url3)
print(f'Webhook1: {result1}, Webhook3: {result2}')
