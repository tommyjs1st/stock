"""다음 메서드 이름 확인"""
TARGET_FILE = "kiwoom_api_client.py"

with open(TARGET_FILE, "r", encoding="utf-8") as f:
    original = f.read()

start_marker = "    def get_access_token(self) -> str:"
start_idx = original.find(start_marker)
print(f"get_access_token 위치: {start_idx}")

# 이후 모든 def 찾기
import re
for m in re.finditer(r'\n    def (\w+)\(', original[start_idx+1:start_idx+3000]):
    print(f"  +{m.start():4d} : def {m.group(1)}")
