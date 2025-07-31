import os
from dotenv import load_dotenv
import requests

load_dotenv()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
webhook_url =  DISCORD_WEBHOOK_URL
requests.post(webhook_url, json={'content':'메세지 알림'})
