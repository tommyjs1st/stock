"""
유틸리티 모듈 - 강화된 JSON 직렬화
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
    """강화된 numpy 타입을 JSON 직렬화 가능한 타입으로 변환"""
    # 1. numpy scalar 처리 (가장 우선)
    if hasattr(obj, 'item'):
        try:
            return obj.item()
        except (ValueError, TypeError):
            pass
    
    # 2. numpy 정수형들
    if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8, np.uint64, np.uint32, np.uint16, np.uint8)):
        return int(obj)
    
    # 3. numpy 실수형들
    if isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        return float(obj)
    
    # 4. numpy bool
    if isinstance(obj, np.bool_):
        return bool(obj)
    
    # 5. numpy 배열
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    
    # 6. pandas 타입들
    if isinstance(obj, pd.Series):
        return obj.tolist()
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict('records')
    if hasattr(obj, 'dtype') and 'int' in str(obj.dtype):
        return int(obj) if not pd.isna(obj) else None
    if hasattr(obj, 'dtype') and 'float' in str(obj.dtype):
        return float(obj) if not pd.isna(obj) else None
    
    # 7. 컬렉션 타입들 (재귀 처리)
    if isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [convert_numpy_types(item) for item in obj]
    
    # 8. 날짜 타입
    if isinstance(obj, datetime):
        return obj.isoformat()
    
    # 9. 기타 Python 기본 타입들
    if isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    
    # 10. 알 수 없는 타입은 문자열로 변환
    try:
        # numpy 타입인지 한번 더 확인
        if hasattr(obj, 'dtype'):
            return obj.item() if hasattr(obj, 'item') else str(obj)
        return obj
    except:
        return str(obj)


def safe_json_save(data, filename):
    """강화된 안전한 JSON 저장 함수"""
    try:
        # 1단계: 강화된 numpy 타입 변환
        converted_data = convert_numpy_types(data)
        
        # 2단계: JSON 직렬화 테스트
        test_json = json.dumps(converted_data, ensure_ascii=False, default=str)
        
        # 3단계: 임시 파일에 먼저 저장
        temp_filename = f"{filename}.tmp"
        with open(temp_filename, "w", encoding="utf-8") as f:
            json.dump(converted_data, f, ensure_ascii=False, indent=2, default=str)
        
        # 4단계: 임시 파일이 정상적으로 생성되었는지 확인
        if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
            # 정상이면 원본 파일로 이동
            if os.path.exists(filename):
                os.remove(filename)
            os.rename(temp_filename, filename)
            return True, None
        else:
            return False, "임시 파일 생성 실패"
        
    except Exception as e:
        # 임시 파일 정리
        temp_filename = f"{filename}.tmp"
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except:
                pass
        return False, str(e)


def save_backtest_candidates(candidates, logger):
    """백테스트 후보 종목을 JSON 파일로 저장 - 강화된 버전"""
    try:
        if not candidates:
            logger.warning("⚠️ 저장할 후보 종목이 없습니다.")
            return
        
        # score 기준으로 내림차순 정렬 후 상위 10개만 선택
        sorted_candidates = sorted(candidates, key=lambda x: x.get('score', 0), reverse=True)[:10]
        
        logger.debug(f"저장할 데이터 개수: {len(sorted_candidates)}")
        
        # 데이터 타입 디버깅
        if logger.level <= logging.DEBUG:
            for i, candidate in enumerate(sorted_candidates[:2]):  # 처음 2개만
                logger.debug(f"후보 {i+1} 타입 분석:")
                for key, value in candidate.items():
                    logger.debug(f"  {key}: {type(value)} = {value}")
        
        # 강화된 안전한 JSON 저장
        success, error = safe_json_save(sorted_candidates, "trading_list.json")
        
        if success:
            logger.info(f"✅ trading_list.json 저장 완료: {len(sorted_candidates)}개 종목")
            
            # 저장된 파일 크기 확인
            if os.path.exists("trading_list.json"):
                file_size = os.path.getsize("trading_list.json")
                logger.debug(f"저장된 파일 크기: {file_size} bytes")
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
            
            # 추가 대안: 간단한 텍스트 파일로 저장
            try:
                with open("trading_list.txt", "w", encoding="utf-8") as f:
                    f.write("# 백테스트 후보 종목 리스트\n")
                    f.write(f"# 생성일시: {datetime.now()}\n\n")
                    for candidate in sorted_candidates:
                        f.write(f"{candidate.get('name', 'Unknown')} ({candidate.get('code', 'N/A')}) - {candidate.get('score', 0)}점\n")
                logger.info("✅ 대안으로 trading_list.txt에 저장 완료")
            except Exception as txt_error:
                logger.error(f"❌ 텍스트 파일 저장도 실패: {txt_error}")
                
    except Exception as e:
        logger.error(f"❌ 전체 저장 프로세스 실패: {e}")
        logger.error(f"오류 상세: {type(e).__name__}: {str(e)}")


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
    for stock in sorted(stocks, key=lambda x: x.get('score', 0), reverse=True):
        signals_text = ", ".join(stock.get('signals', []))
        
        line = f"- {stock.get('name', 'Unknown')} ({stock.get('code', 'N/A')}) - {stock.get('score', 0)}점\n"
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
