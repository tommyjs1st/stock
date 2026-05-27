import sys
sys.path.insert(0, '/Users/jsshin/RESTAPI')
from analyze.utils import send_discord_message

webhook_url = 'https://discord.com/api/webhooks/1392715031149285420/cnDqqfbTc_dRrKSY2ZSlpznjXGVQLMBLn4cJ6CfriiGdkvX1Ly7WsjXLlPJJUdkcy1En'
webhook_url3 = 'https://discord.com/api/webhooks/1398285993458798592/vp7JtbavvOwduAgO4laIk8T2TOye_ZwkEtB59MPvqJmJJ7bjmpqxXmNVL_p8q65g4NKg'

message = (
    "\U0001f4e2 \uc624\ub298\uc758 \uc5ec\ud589 \uc601\uc5b4 \ud68c\ud654\uac00 \uc5c5\ub370\uc774\ud2b8\ub428\uc2b5\ub2c8\ub2e4!\n"
    "\U0001f5d3 2026-05-23 | \U0001f3e8 \ud638\ud154 \uccb4\ud06c\uc544\uc6c3 & \ubd88\ud3b8\uc0ac\ud56d \ubb38\uc758\n"
    "\U0001f517 https://musi.co.kr/english-news/conv-2026-05-23.html\n\n"
    "\U0001f4a1 \ud575\uc2ec \ud45c\ud604\u00b7\uc5b4\ud718\ub97c \ube60\ub974\uac8c \ub450 \ubc88 \ud0ed\ud558\uba74 \ubc1c\uc74c\uc744 \ub4e4\uc744 \uc218 \uc788\uc5b4\uc694!"
)

result1 = send_discord_message(message, webhook_url)
result2 = send_discord_message(message, webhook_url3)
print(f'Webhook1: {result1}, Webhook3: {result2}')
