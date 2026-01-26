#!/usr/bin/env python3
"""
업종 모멘텀 전략 V2 실행 스크립트
- 네이버 금융 + KIS API 조합
- 개별 종목 기반 업종 모멘텀 계산
"""
import os
import sys
import json
import logging
import argparse
from datetime import datetime
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()

# 현재 디렉토리를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 간단한 KIS API 클라이언트
import requests
import time

class SimpleKISAPIClient:
    def __init__(self):
        self.app_key = os.getenv("KIS_APP_KEY")
        self.app_secret = os.getenv("KIS_APP_SECRET")
        self.token_file = "token.json"
        self.access_token = None
        
    def load_token(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, "r") as f:
                    token_data = json.load(f)
                
                now = int(time.time())
                issued_at = token_data.get("requested_at", 0)
                expires_in = int(token_data.get("expires_in", 0))
                
                if now - issued_at < expires_in - 3600:
                    self.access_token = token_data["access_token"]
                    return self.access_token
            except:
                pass
        
        return self.request_new_token()
    
    def request_new_token(self):
        url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        headers = {"Content-Type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        res = requests.post(url, headers=headers, data=json.dumps(data))
        res.raise_for_status()
        token_data = res.json()
        token_data["requested_at"] = int(time.time())
        
        with open(self.token_file, "w") as f:
            json.dump(token_data, f)
        
        self.access_token = token_data["access_token"]
        return self.access_token
    
    def get_access_token(self):
        if not self.access_token:
            self.load_token()
        return self.access_token


def send_discord_message(message, webhook_url):
    """디스코드 메시지 전송"""
    if not webhook_url:
        return False
    
    try:
        chunks = [message[i:i+2000] for i in range(0, len(message), 2000)]
        
        for chunk in chunks:
            data = {"content": chunk}
            response = requests.post(webhook_url, json=data, timeout=10)
            response.raise_for_status()
            time.sleep(0.5)
        
        return True
    except Exception as e:
        print(f"⚠️ 디스코드 전송 실패: {e}")
        return False


def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(description='업종 모멘텀 전략 V2 실행')
    parser.add_argument('--consecutive-days', type=int, default=2, 
                       help='최소 연속 상승 일수 (기본: 2)')
    parser.add_argument('--top-sectors', type=int, default=5,
                       help='선정할 상위 업종 수 (기본: 5)')
    parser.add_argument('--top-stocks', type=int, default=2,
                       help='업종당 선정할 종목 수 (기본: 2)')
    parser.add_argument('--discord', action='store_true',
                       help='디스코드 알림 전송 여부')
    parser.add_argument('--save-json', action='store_true',
                       help='JSON 파일 저장 여부')
    
    args = parser.parse_args()
    
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('sector_momentum_v2.log', encoding='utf-8')
        ]
    )
    logger = logging.getLogger(__name__)
    
    try:
        print("=" * 70)
        print("🚀 업종 모멘텀 전략 V2 실행")
        print("=" * 70)
        print(f"📊 설정:")
        print(f"  • 연속 상승: 최소 {args.consecutive_days}일")
        print(f"  • 상위 업종: {args.top_sectors}개")
        print(f"  • 종목 수: 업종당 {args.top_stocks}개")
        print(f"  • 방식: 개별 종목 기반 분석")
        print("=" * 70)
        
        # API 클라이언트 초기화
        logger.info("🔧 KIS API 클라이언트 초기화 중...")
        api_client = SimpleKISAPIClient()
        logger.info("✅ API 클라이언트 초기화 완료")
        
        # V2 분석기 로드
        try:
            from sector_momentum_analyzer_v2 import SectorMomentumAnalyzerV2
        except ImportError as e:
            logger.error(f"❌ V2 분석기를 찾을 수 없습니다: {e}")
            print("\n📝 sector_momentum_analyzer_v2.py 파일이 필요합니다.")
            print("현재 디렉토리에 파일이 있는지 확인하세요.")
            return 1
        
        # 분석기 생성
        analyzer = SectorMomentumAnalyzerV2(api_client)
        
        # 추천 종목 추출
        logger.info(f"\n📈 {args.consecutive_days}일 모멘텀 업종 분석 시작...")
        recommendations = analyzer.get_top_stocks_from_rising_sectors(
            min_consecutive_days=args.consecutive_days,
            top_n_sectors=args.top_sectors,
            top_n_stocks=args.top_stocks
        )
        
        if not recommendations:
            logger.warning("⚠️ 조건에 맞는 종목이 없습니다.")
            print(f"\n📭 현재 모멘텀 상승 업종이 없습니다.")
            return 0
        
        # 결과 메시지 생성
        message = analyzer.format_recommendations_message(recommendations)
        
        print("\n" + "=" * 70)
        print("🎯 추천 종목:")
        print("=" * 70)
        print(message)
        
        # JSON 파일 저장
        if args.save_json:
            output_file = f"sector_momentum_v2_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
            
            output_data = {
                'timestamp': datetime.now().isoformat(),
                'version': 'v2',
                'method': 'individual_stock_based',
                'parameters': {
                    'consecutive_days': args.consecutive_days,
                    'top_sectors': args.top_sectors,
                    'top_stocks': args.top_stocks
                },
                'recommendations': recommendations
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"💾 결과 저장: {output_file}")
            print(f"\n💾 결과가 {output_file}에 저장되었습니다.")
        
        # 디스코드 전송
        if args.discord:
            webhook_url = os.getenv("DISCORD_WEBHOOK_URL3")
            if webhook_url:
                logger.info("📱 디스코드 전송 중...")
                if send_discord_message(message, webhook_url):
                    logger.info("✅ 디스코드 전송 완료")
                    print("\n✅ 디스코드 알림이 전송되었습니다.")
                else:
                    logger.warning("⚠️ 디스코드 전송 실패")
            else:
                logger.warning("⚠️ DISCORD_WEBHOOK_URL3 환경변수가 설정되지 않았습니다.")
        
        print("\n" + "=" * 70)
        print("✅ 실행 완료!")
        print("=" * 70)
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ 오류 발생: {e}", exc_info=True)
        print(f"\n❌ 오류: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
