import requests
import json
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from datetime import datetime
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import re

# 환경 변수 로드
load_dotenv()

def setup_logger(log_dir="logs", log_filename="bike_monitor.log", when="midnight", backup_count=7):
    """로거 설정"""
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_filename)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    handler = TimedRotatingFileHandler(
        log_path, when=when, interval=1, backupCount=backup_count, encoding='utf-8'
    )
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # 콘솔 출력도 추가
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

def send_discord_message(message, webhook_url):
    """디스코드 웹훅으로 메시지 전송"""
    MAX_LENGTH = 2000
    chunks = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]
    
    for chunk in chunks:
        data = {"content": chunk}
        try:
            response = requests.post(webhook_url, json=data)
            response.raise_for_status()
            print(f"✅ 디스코드 메시지 전송 성공")
            return True
        except Exception as e:
            print(f"❌ 디스코드 전송 실패: {e}")
            return False
        time.sleep(0.5)

def load_previous_products(filename="previous_products.json"):
    """이전 상품 리스트 로드"""
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_current_products(products, filename="previous_products.json"):
    """현재 상품 리스트 저장"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ 상품 리스트 저장 실패: {e}")

def get_product_list(url, keywords):
    """사이트에서 상품 리스트 가져오기"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        products = {}
        
        # 게시글 리스트 찾기 (사이트 구조에 따라 수정 필요)
        # 일반적인 게시판 구조 예상
        post_rows = soup.find_all('tr')  # 테이블 행
        if not post_rows:
            # div 기반 레이아웃일 경우
            post_rows = soup.find_all('div', class_=['list-item', 'post-item', 'board-item'])
        
        for row in post_rows:
            try:
                print(f"{row}")
                # 제목 링크 찾기
                title_link = row.find('a')
                if not title_link:
                    continue
                    
                title = title_link.get_text(strip=True)
                link = title_link.get('href', '')
                
                # 상대 링크를 절대 링크로 변환
                if link and not link.startswith('http'):
                    base_url = 'https://corearoadbike.com'
                    if not link.startswith('/'):
                        link = '/' + link
                    link = base_url + link
                
                # 키워드 검색
                for keyword in keywords:
                    if keyword.lower() in title.lower():
                        # 가격 정보 추출 시도
                        price_text = ""
                        price_match = re.search(r'[\d,]+만?원?', title)
                        if price_match:
                            price_text = price_match.group()
                        
                        # 상품 정보 저장
                        product_key = f"{title}_{link}"  # 중복 방지용 키
                        products[product_key] = {
                            'title': title,
                            'link': link,
                            'price': price_text,
                            'keyword': keyword,
                            'found_at': datetime.now().isoformat()
                        }
                        print(f"🎯 키워드 '{keyword}' 매칭: {title}")
                        break
                        
            except Exception as e:
                continue
                
        return products
        
    except Exception as e:
        print(f"❌ 사이트 접근 오류: {e}")
        return {}

def format_product_message(new_products):
    """새로운 상품 알림 메시지 포맷팅"""
    if not new_products:
        return ""
    
    message = "🚴‍♂️ **[코어아로드바이크 새상품 알림]**\n\n"
    
    for product_key, product in new_products.items():
        message += f"🔥 **{product['title']}**\n"
        if product['price']:
            message += f"💰 가격: {product['price']}\n"
        message += f"🏷️ 키워드: {product['keyword']}\n"
        message += f"🔗 링크: {product['link']}\n"
        message += f"⏰ 발견시간: {product['found_at'][:19].replace('T', ' ')}\n"
        message += "─" * 50 + "\n\n"
    
    return message

def main():
    """메인 실행 함수"""
    logger = setup_logger()
    
    # 환경 변수에서 설정값 읽기
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.error("❌ DISCORD_WEBHOOK_URL 환경변수가 설정되지 않았습니다.")
        return
    
    # 모니터링할 사이트 URL과 키워드
    target_url = "https://corearoadbike.com/board/board.php?t_id=Menu01Top6&category=%25ED%258C%2590%25EB%25A7%25A4&category2=%25EB%2594%2594%25EC%258A%25A4%25ED%2581%25AC&sort=wr_2+desc"
    keywords = ["와스프로", "에어로드", "AEROAD", "WASP", "Aeroad", "wasp"]  # 검색할 키워드들
    
    logger.info(f"🔍 모니터링 시작 - 키워드: {', '.join(keywords)}")
    
    try:
        # 현재 상품 리스트 가져오기
        current_products = get_product_list(target_url, keywords)
        logger.info(f"📊 현재 발견된 상품: {len(current_products)}개")
        
        # 이전 상품 리스트 로드
        previous_products = load_previous_products()
        
        # 새로운 상품 찾기
        new_products = {}
        for product_key, product in current_products.items():
            if product_key not in previous_products:
                new_products[product_key] = product
        
        logger.info(f"🆕 새로운 상품: {len(new_products)}개")
        
        # 새로운 상품이 있으면 디스코드로 알림 전송
        if new_products:
            message = format_product_message(new_products)
            if message:
                success = send_discord_message(message, webhook_url)
                if success:
                    logger.info(f"✅ {len(new_products)}개 새상품 알림 전송 완료")
                else:
                    logger.error("❌ 디스코드 알림 전송 실패")
        else:
            logger.info("📭 새로운 상품이 없습니다.")
        
        # 현재 상품 리스트 저장 (다음 실행시 비교용)
        save_current_products(current_products)
        
        # 테스트용 - 첫 실행시 현재 상품들 보여주기
        if not previous_products and current_products:
            test_message = f"🎯 **[모니터링 시작]**\n현재 발견된 관련 상품: {len(current_products)}개\n"
            test_message += "다음 실행부터 새로운 상품만 알려드립니다!"
            send_discord_message(test_message, webhook_url)
        
    except Exception as e:
        error_message = f"❌ **[모니터링 오류]**\n{str(e)}"
        logger.error(error_message)
        send_discord_message(error_message, webhook_url)

if __name__ == "__main__":
    main()
