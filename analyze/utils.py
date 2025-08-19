"""
유틸리티 모듈
JSON 처리, 로깅, 메시지 포맷팅 등
"""
import json
import logging
import os
import requests
import time
import numpy as np
import pandas as pd
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

def setup_logger(log_dir="logs", log_filename="buying_stocks.log", when="midnight", backup_count=7):
    """로깅 설정"""
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

    return logger


def convert_numpy_types(obj):
    """numpy 타입을 JSON 직렬화 가능한 타입으로 변환"""
    if hasattr(obj, 'item'):  # numpy scalar이면 Python 기본 타입으로 변환
        return obj.item()
    elif isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Series):
        return obj.tolist()
    elif isinstance(obj, pd.DataFrame):
        return obj.to_dict('records')
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_types(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj


def safe_json_save(data, filename):
    """안전한 JSON 저장 함수"""
    try:
        # 1단계: numpy 타입 변환
        converted_data = convert_numpy_types(data)
        
        # 2단계: JSON 직렬화 테스트
        json.dumps(converted_data, ensure_ascii=False)
        
        # 3단계: 파일 저장
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(converted_data, f, ensure_ascii=False, indent=2)
        
        return True, None
        
    except Exception as e:
        return False, str(e)


def send_discord_message(message, webhook_url):
    """디스코드 메시지 전송"""
    if not webhook_url:
        print("❌ Discord webhook URL이 설정되지 않았습니다.")
        return
        
    print(message)
    MAX_LENGTH = 2000
    chunks = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]
    
    for chunk in chunks:
        data = {"content": chunk}
        try:
            response = requests.post(webhook_url, json=data, timeout=10)
            response.raise_for_status()
        except Exception as e:
            print(f"❌ 디스코드 전송 실패: {e}")
        time.sleep(0.5)


def format_multi_signal_message(grade, stocks):
    """다중신호 종목 메시지 포맷팅"""
    if not stocks:
        return ""
    
    grade_info = {
        "ultra_strong": {"icon": "🚀", "name": "초강력 매수신호", "desc": "5점 이상"},
        "strong": {"icon": "🔥", "name": "강력 매수신호", "desc": "4점"},
        "moderate": {"icon": "⭐", "name": "보통 매수신호", "desc": "3점"},
        "weak": {"icon": "⚡", "name": "약한 매수신호", "desc": "2점"},
        "single": {"icon": "💡", "name": "단일 매수신호", "desc": "1점"}
    }
    
    info = grade_info[grade]
    header = f"{info['icon']} **[{info['name']} ({info['desc']})]**\n"
    
    stock_lines = []
    for stock in sorted(stocks, key=lambda x: x['score'], reverse=True):
        signals_text = ", ".join(stock['signals'])
        
        line = f"- {stock['name']} ({stock['code']}) - {stock['score']}점\n"
        line += f"  📊 [{signals_text}]"
        if 'foreign' in stock and stock['foreign']:
            line += f"\n  💰 외국인: {stock['foreign']}"
        stock_lines.append(line)
    
    return header + "\n".join(stock_lines)


def format_signal_combination_message(combinations):
    """신호 조합 패턴 메시지 포맷팅"""
    if not combinations:
        return ""
    
    header = "🔍 **[인기 신호 조합 패턴]**\n"
    combo_lines = []
    
    # 조합별 종목 수로 정렬
    sorted_combos = sorted(combinations.items(), key=lambda x: len(x[1]), reverse=True)
    
    for combo, stocks in sorted_combos[:10]:  # 상위 10개 조합만
        if len(stocks) >= 2:  # 2개 이상 종목에서 나타나는 조합만
            combo_lines.append(f"• **{combo}** ({len(stocks)}개 종목)")
            combo_lines.append(f"  → {', '.join(stocks[:5])}")  # 최대 5개 종목만 표시
            if len(stocks) > 5:
                combo_lines.append(f"  → 외 {len(stocks)-5}개 종목")
    
    return header + "\n".join(combo_lines) if combo_lines else ""


def save_backtest_candidates(candidates, logger):
    """백테스트 후보 종목을 JSON 파일로 저장"""
    try:
        # score 기준으로 내림차순 정렬 후 상위 10개만 선택
        sorted_candidates = sorted(candidates, key=lambda x: x['score'], reverse=True)[:10]
        
        logger.debug(f"저장할 데이터 개수: {len(sorted_candidates)}")
        
        # 안전한 JSON 저장
        success, error = safe_json_save(sorted_candidates, "trading_list.json")
        
        if success:
            logger.info(f"✅ trading_list.json 저장 완료: {len(sorted_candidates)}개 종목")
        else:
            logger.error(f"❌ trading_list.json 저장 실패: {error}")
            
            # 실패 시 대안: pickle로 저장
            try:
                import pickle
                with open("trading_list.pkl", "wb") as f:
                    pickle.dump(sorted_candidates, f)
                logger.info("✅ 대안으로 trading_list.pkl에 저장 완료")
            except Exception as pickle_error:
                logger.error(f"❌ pickle 저장도 실패: {pickle_error}")
                
    except Exception as e:
        logger.error(f"❌ 전체 저장 프로세스 실패: {e}")


def load_stock_codes_from_file(file_path):
    """파일에서 종목 코드와 종목명을 읽어오는 함수"""
    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return [], {}
    
    file_extension = os.path.splitext(file_path)[1].lower()
    stock_codes = []
    stock_names = {}
    
    try:
        if file_extension == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                if data and isinstance(data[0], dict):
                    # [{"code": "034020", "name": "두산에너빌리티", ...}, ...] 형태
                    if 'code' in data[0]:
                        for item in data:
                            if 'code' in item:
                                code = str(item['code']).zfill(6)
                                name = item.get('name', code)
                                stock_codes.append(code)
                                stock_names[code] = name
                        print(f"✅ JSON 객체 배열에서 {len(stock_codes)}개 종목 로드")
                    else:
                        print(f"❌ 객체에 'code' 필드가 없습니다.")
                        return [], {}
                else:
                    # ["062040", "278470", ...] 형태
                    stock_codes = [str(code).zfill(6) for code in data]
                    stock_names = {code: code for code in stock_codes}
                    print(f"✅ JSON 배열에서 {len(stock_codes)}개 종목 로드")
                    
        # 중복 제거 및 유효성 검사
        unique_codes = []
        unique_names = {}
        for code in stock_codes:
            if code and len(code) == 6 and code.isdigit():
                if code not in unique_codes:
                    unique_codes.append(code)
                    unique_names[code] = stock_names.get(code, code)
            else:
                print(f"⚠️ 유효하지 않은 종목코드 제외: {code}")
        
        print(f"📊 최종 {len(unique_codes)}개 종목 로드 완료")
        return unique_codes, unique_names
        
    except Exception as e:
        print(f"❌ 파일 읽기 오류 ({file_path}): {e}")
        return [], {}


class ProgressTracker:
    """진행상황 추적 클래스"""
    
    def __init__(self, total_count):
        self.total_count = total_count
        self.analyzed_count = 0
        self.error_count = 0
        self.start_time = datetime.now()
    
    def update(self, success=True):
        """진행상황 업데이트"""
        if success:
            self.analyzed_count += 1
        else:
            self.error_count += 1
        
        # 50개마다 진행상황 출력
        total_processed = self.analyzed_count + self.error_count
        if total_processed % 50 == 0:
            elapsed = datetime.now() - self.start_time
            rate = total_processed / elapsed.total_seconds() * 60  # 분당 처리율
            print(f"진행 상황: {total_processed}/{self.total_count} "
                  f"(성공: {self.analyzed_count}, 오류: {self.error_count}) "
                  f"처리율: {rate:.1f}개/분")
    
    def get_summary(self):
        """최종 요약 반환"""
        elapsed = datetime.now() - self.start_time
        return {
            "analyzed_count": self.analyzed_count,
            "error_count": self.error_count,
            "total_processed": self.analyzed_count + self.error_count,
            "elapsed_time": elapsed.total_seconds(),
            "success_rate": self.analyzed_count / (self.analyzed_count + self.error_count) * 100 if (self.analyzed_count + self.error_count) > 0 else 0
        }
