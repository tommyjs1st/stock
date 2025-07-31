import requests
import json
import yaml
from datetime import datetime

def test_discord_webhook():
    """디스코드 웹훅 테스트"""
    
    # config.yaml에서 웹훅 URL 로드
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        webhook_url = config.get('notification', {}).get('discord_webhook', '')
        
        if not webhook_url:
            print("❌ config.yaml에 discord_webhook이 설정되지 않았습니다.")
            print("설정 방법:")
            print("1. 디스코드 서버 → 설정 → 연동 → 웹후크")
            print("2. '새 웹후크' 클릭")
            print("3. 웹후크 URL 복사")
            print("4. config.yaml의 discord_webhook에 붙여넣기")
            return False
        
        print(f"웹훅 URL: {webhook_url[:50]}...")
        
    except Exception as e:
        print(f"❌ config.yaml 로드 실패: {e}")
        return False
    
    # 테스트 메시지 전송
    try:
        embed = {
            "title": "🧪 웹훅 테스트",
            "description": "KIS 자동매매 시스템 디스코드 알림 테스트입니다.",
            "color": 0x00ff00,
            "timestamp": datetime.now().isoformat(),
            "fields": [
                {
                    "name": "테스트 항목",
                    "value": "웹훅 연결 상태",
                    "inline": True
                },
                {
                    "name": "상태",
                    "value": "✅ 정상",
                    "inline": True
                }
            ],
            "footer": {
                "text": "KIS 자동매매 시스템"
            }
        }
        
        data = {
            "content": "🎉 자동매매 시스템 알림 테스트!",
            "embeds": [embed]
        }
        
        print("디스코드로 테스트 메시지 전송 중...")
        response = requests.post(webhook_url, json=data, timeout=10)
        
        print(f"HTTP 상태코드: {response.status_code}")
        
        if response.status_code == 204:
            print("✅ 디스코드 알림 테스트 성공!")
            print("디스코드 채널에서 메시지를 확인하세요.")
            return True
        elif response.status_code == 401:
            print("❌ 401 Unauthorized - 웹훅 URL이 잘못되었습니다.")
            print("해결방법:")
            print("1. 웹훅이 삭제되지 않았는지 확인")
            print("2. 전체 URL이 올바른지 확인 (토큰 포함)")
            print("3. 새 웹훅을 생성해서 다시 시도")
            return False
        elif response.status_code == 404:
            print("❌ 404 Not Found - 웹훅을 찾을 수 없습니다.")
            print("웹훅이 삭제되었거나 URL이 잘못되었습니다.")
            return False
        else:
            print(f"❌ 알 수 없는 오류: {response.status_code}")
            print(f"응답: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ 타임아웃 - 네트워크 연결을 확인하세요.")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ 연결 오류 - 인터넷 연결을 확인하세요.")
        return False
    except Exception as e:
        print(f"❌ 예상치 못한 오류: {e}")
        return False

def create_sample_webhook():
    """샘플 웹훅 설정 가이드"""
    print("\n📋 디스코드 웹훅 설정 가이드")
    print("=" * 40)
    print("1. 디스코드 앱/웹사이트에서 서버 선택")
    print("2. 채널 설정(톱니바퀴) → 연동 → 웹후크")
    print("3. '새 웹후크' 클릭")
    print("4. 웹후크 이름 설정 (예: '자동매매 알림')")
    print("5. '웹후크 URL 복사' 클릭")
    print("6. config.yaml 파일에서 아래와 같이 설정:")
    print()
    print("notification:")
    print('  discord_webhook: "복사한_웹훅_URL_여기에_붙여넣기"')
    print("  notify_on_trade: true")
    print("  notify_on_error: true")
    print("  notify_on_daily_summary: true")
    print()
    print("⚠️ 주의: 웹훅 URL은 외부에 노출하지 마세요!")

if __name__ == "__main__":
    print("🔔 디스코드 웹훅 테스트 프로그램")
    print("=" * 50)
    
    success = test_discord_webhook()
    
    if not success:
        create_sample_webhook()
        
        print(f"\n🔄 웹훅 설정 후 다시 실행하세요:")
        print("python discord_test.py")
