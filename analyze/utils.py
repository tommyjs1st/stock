"""
강화된 유틸리티 모듈 - 절대조건 필터링 지원
JSON 직렬화 및 메시지 포맷팅 개선
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
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_filename)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    # 콘솔 핸들러 추가
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러 추가
    file_handler = TimedRotatingFileHandler(
        log_path, when=when, interval=1, backupCount=backup_count, encoding='utf-8'
    )
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler.setFormatter(file_formatter)
    #file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)

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
        if hasattr(obj, 'dtype'):
            return obj.item() if hasattr(obj, 'item') else str(obj)
        return obj
    except:
        return str(obj)

def safe_json_save(data, filename):
    """강화된 안전한 JSON 저장 함수"""
    try:
        # 1단계: numpy 타입 변환
        converted_data = convert_numpy_types(data)
        
        # 2단계: JSON 직렬화 테스트
        test_json = json.dumps(converted_data, ensure_ascii=False, default=str)
        
        # 3단계: 임시 파일에 먼저 저장
        temp_filename = f"{filename}.tmp"
        with open(temp_filename, "w", encoding="utf-8") as f:
            json.dump(converted_data, f, ensure_ascii=False, indent=2, default=str)
        
        # 4단계: 임시 파일 검증 후 원본으로 이동
        if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
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

def save_enhanced_backtest_candidates(candidates, logger, include_filter_info=True):
    """
    강화된 백테스트 후보 저장 - 절대조건 정보 포함
    
    Args:
        candidates: 후보 종목 리스트
        logger: 로거 객체
        include_filter_info: 필터링 정보 포함 여부
    """
    try:
        if not candidates:
            logger.warning("⚠️ 저장할 후보 종목이 없습니다.")

            # 기존 파일들 삭제
            files_to_delete = [
                "trading_list.json",
                "trading_list_summary.txt"
            ]
            
            deleted_files = []
            for filename in files_to_delete:
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                        deleted_files.append(filename)
                        logger.info(f"🗑️ 기존 파일 삭제: {filename}")
                    except Exception as e:
                        logger.warning(f"⚠️ 파일 삭제 실패 ({filename}): {e}")
            
            if deleted_files:
                logger.info(f"✅ 총 {len(deleted_files)}개 기존 파일 삭제 완료")
            else:
                logger.info("📝 삭제할 기존 파일이 없습니다.")
            
            return

            return
        
        # score 기준으로 내림차순 정렬
        sorted_candidates = sorted(candidates, key=lambda x: x.get('score', 0), reverse=True)
        
        # 절대조건 통과 종목만 필터링 (이미 필터링되어 있지만 확실히)
        if include_filter_info:
            filtered_candidates = [c for c in sorted_candidates if c.get('filter_status') == '절대조건통과']
        else:
            filtered_candidates = sorted_candidates
        
        # 상위 5개만 저장 (절대조건 통과 종목이 많을 경우 대비)
        final_candidates = filtered_candidates[:5]
        
        # 추가 정보 포함
        for candidate in final_candidates:
            candidate.update({
                'saved_at': datetime.now().isoformat(),
                'absolute_filter_applied': True,
                'ma5_below_ma20_confirmed': True,
                'foreign_selling_excluded': True
            })
        
        success, error = safe_json_save(final_candidates, "trading_list.json")
        
        if success:
            logger.info(f"✅ trading_list.json 저장 완료: {len(final_candidates)}개 종목 (절대조건 통과)")
            
            # 저장된 파일 정보 로깅
            if os.path.exists("trading_list.json"):
                file_size = os.path.getsize("trading_list.json")
                logger.info(f"📄 파일 크기: {file_size} bytes")
                
                # 간단 통계
                if final_candidates:
                    avg_score = sum(c.get('score', 0) for c in final_candidates) / len(final_candidates)
                    max_score = max(c.get('score', 0) for c in final_candidates)
                    logger.info(f"📊 점수 통계: 평균 {avg_score:.1f}점, 최고 {max_score}점")
        else:
            logger.error(f"❌ trading_list.json 저장 실패: {error}")
            
            # 대안 저장 방법들
            try:
                import pickle
                with open("trading_list.pkl", "wb") as f:
                    pickle.dump(final_candidates, f)
                logger.info("✅ 대안으로 trading_list.pkl에 저장 완료")
            except Exception as pickle_error:
                logger.error(f"❌ pickle 저장 실패: {pickle_error}")
            
            # 텍스트 파일로 요약 저장
            try:
                with open("trading_list_summary.txt", "w", encoding="utf-8") as f:
                    f.write("# 절대조건 필터링 적용 백테스트 후보 종목 리스트\n")
                    f.write(f"# 생성일시: {datetime.now()}\n")
                    f.write(f"# 절대조건: 5일선<20일선 + 외국인매수추세\n\n")
                    
                    for i, candidate in enumerate(final_candidates, 1):
                        signals = ", ".join(candidate.get('signals', []))
                        f.write(f"{i:2d}. {candidate.get('name', 'Unknown')} ({candidate.get('code', 'N/A')})\n")
                        f.write(f"    점수: {candidate.get('score', 0)}점, 가격: {candidate.get('price', 0):,}원\n")
                        f.write(f"    신호: [{signals}]\n")
                        f.write(f"    필터: {candidate.get('filter_reason', '통과')}\n\n")
                        
                logger.info("✅ 대안으로 trading_list_summary.txt에 저장 완료")
            except Exception as txt_error:
                logger.error(f"❌ 텍스트 요약 저장 실패: {txt_error}")
                
    except Exception as e:
        logger.error(f"❌ 강화된 백테스트 후보 저장 실패: {e}")
        logger.error(f"오류 상세: {type(e).__name__}: {str(e)}")

def send_discord_message(message, webhook_url, max_retries=3):
    """강화된 디스코드 메시지 전송 (재시도 로직 포함)"""
    if not webhook_url:
        print("❌ Discord webhook URL이 설정되지 않았습니다.")
        return False
    
    print(message)  # 콘솔에도 출력
    
    MAX_LENGTH = 2000
    chunks = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]
    
    success_count = 0
    for i, chunk in enumerate(chunks):
        data = {"content": chunk}
        
        for attempt in range(max_retries):
            try:
                response = requests.post(webhook_url, json=data, timeout=10)
                response.raise_for_status()
                success_count += 1
                break
                
            except requests.exceptions.RequestException as e:
                print(f"❌ 디스코드 전송 실패 (청크 {i+1}/{len(chunks)}, 시도 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))  # 점진적 지연
                else:
                    print(f"❌ 청크 {i+1} 전송 완전 실패")
            except Exception as e:
                print(f"❌ 예상치 못한 오류 (청크 {i+1}, 시도 {attempt+1}): {e}")
                break
        
        time.sleep(0.5)  # 청크 간 간격
    
    return success_count == len(chunks)

def format_enhanced_multi_signal_message(grade, stocks):
    """강화된 다중신호 종목 메시지 포맷팅 (절대조건 정보 포함)"""
    if not stocks:
        return ""
    
    grade_info = {
        "ultra_strong": {"icon": "🚀", "name": "초강력 매수신호", "desc": "5점 이상", "color": "**"},
        "strong": {"icon": "🔥", "name": "강력 매수신호", "desc": "4점", "color": "**"},
        "moderate": {"icon": "⭐", "name": "보통 매수신호", "desc": "3점", "color": "**"},
        "weak": {"icon": "⚡", "name": "약한 매수신호", "desc": "2점", "color": ""},
        "single": {"icon": "💡", "name": "단일 매수신호", "desc": "1점", "color": ""}
    }
    
    info = grade_info[grade]
    header = f"{info['icon']} {info['color']}[✅절대조건통과 {info['name']} ({info['desc']})]**\n"
    header += "🔒 *현재가<20일선 + 거래량≥1000주 + 볼린저밴드내 + 외국인2~3일연속매수*\n"  # 🆕 변경

    
    stock_lines = []
    for i, stock in enumerate(sorted(stocks, key=lambda x: x.get('score', 0), reverse=True), 1):
        signals_text = ", ".join(stock.get('signals', []))
        
        # 기본 정보
        line = f"{i:2d}. **{stock.get('name', 'Unknown')} ({stock.get('code', 'N/A')})**"
        line += f" - {stock.get('score', 0)}점\n"
        
        # 신호 정보
        line += f"     📊 신호: [{signals_text}]\n"
        
        # 가격 정보
        price = stock.get('price', 0)
        volume = stock.get('volume', 0)
        if price > 0:
            line += f"     💰 현재가: {price:,}원, 거래량: {volume:,}주\n"
        
        # 외국인 정보 (간소화)
        foreign = stock.get('foreign', [])
        if foreign and len(foreign) >= 2:
            recent_foreign = sum(foreign[:2])  # 최근 2일 합계
            if abs(recent_foreign) > 1000:  # 1천주 이상일 때만 표시
                direction = "매수" if recent_foreign > 0 else "매도"
                line += f"     🌍 외국인 2일간: {direction} {abs(recent_foreign):,}주\n"
        
        # 필터 통과 정보
        filter_reason = stock.get('filter_reason', '절대조건통과')
        #if filter_reason != '절대조건통과':
        #    line += f"     ✅ 사유: {filter_reason}\n"
        
        stock_lines.append(line)
    
    return header + "\n" + "\n".join(stock_lines)

def format_enhanced_signal_combination_message(combinations):
    """강화된 신호 조합 패턴 메시지 포맷팅"""
    if not combinations:
        return ""
    
    header = "🔍 **[✅절대조건통과 인기 신호 조합 패턴]**\n"
    header += "🔒 *현재가<20일선 + 외국인매수추세 적용*\n"  # 변경
    combo_lines = []
    
    # 조합별 종목 수로 정렬
    sorted_combos = sorted(combinations.items(), key=lambda x: len(x[1]), reverse=True)
    
    for i, (combo, stocks) in enumerate(sorted_combos[:10], 1):  # 상위 10개
        if len(stocks) >= 2:  # 2개 이상 종목에서 나타나는 조합만
            combo_lines.append(f"{i:2d}. **{combo}** ({len(stocks)}개 종목)")
            
            # 종목명을 점수순으로 정렬 (가능한 경우)
            display_stocks = stocks[:5]  # 최대 5개만 표시
            combo_lines.append(f"     → {', '.join(display_stocks)}")
            
            if len(stocks) > 5:
                combo_lines.append(f"     → *외 {len(stocks)-5}개 종목*")
            combo_lines.append("")  # 빈 줄 추가
    
    if combo_lines:
        # 마지막 빈 줄 제거
        if combo_lines[-1] == "":
            combo_lines.pop()
        return header + "\n" + "\n".join(combo_lines)
    
    return ""

def format_absolute_filter_summary(filter_passed_count, filter_failed_count, total_analyzed):
    """절대조건 필터링 요약 포맷팅"""
    summary_lines = []
    
    summary_lines.append("📊 **[절대조건 필터링 요약]**")
    summary_lines.append("🔒 **적용된 절대조건:**")
    summary_lines.append("   ① 현재가가 20일 이동평균선 아래 위치")  # 변경
    summary_lines.append("   ② 거래량 1000주 이상") 
    summary_lines.append("   ③ 볼린저밴드 하단선 위에 위치")
    summary_lines.append("   ④ 외국인 매수추세")
    summary_lines.append("")
    
    summary_lines.append("📈 **필터링 결과:**")
    summary_lines.append(f"   ✅ 절대조건 통과: **{filter_passed_count}개**")
    summary_lines.append(f"   🚫 절대조건 미통과: {filter_failed_count}개")
    summary_lines.append(f"   📊 전체 분석 대상: {total_analyzed}개")
    
    if filter_passed_count + filter_failed_count > 0:
        pass_rate = (filter_passed_count / (filter_passed_count + filter_failed_count)) * 100
        summary_lines.append(f"   📈 절대조건 통과율: **{pass_rate:.1f}%**")
    
    summary_lines.append("")
    summary_lines.append("💡 **의미:**")
    summary_lines.append("   • 모든 후보는 20일선 아래 조정 구간에서 선별")  # 변경
    summary_lines.append("   • 외국인 매수추세 종목으로 한정")
    
    return "\n".join(summary_lines)

def load_stock_codes_from_file(file_path):
    """파일에서 종목 코드와 종목명을 읽어오는 강화된 함수"""
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
                    # 강화된 JSON 구조 처리
                    for item in data:
                        if 'code' in item:
                            code = str(item['code']).zfill(6)
                            name = item.get('name', code)
                            
                            # 절대조건 관련 정보 확인
                            filter_status = item.get('filter_status', '')
                            if filter_status == '절대조건통과' or not filter_status:
                                stock_codes.append(code)
                                stock_names[code] = name
                                
                        elif 'symbol' in item:  # 다른 형식 지원
                            code = str(item['symbol']).zfill(6)
                            name = item.get('stock_name', item.get('name', code))
                            stock_codes.append(code)
                            stock_names[code] = name
                    
                    print(f"✅ JSON 객체 배열에서 {len(stock_codes)}개 종목 로드")
                else:
                    # 단순 배열 형태
                    stock_codes = [str(code).zfill(6) for code in data]
                    stock_names = {code: code for code in stock_codes}
                    print(f"✅ JSON 배열에서 {len(stock_codes)}개 종목 로드")
        
        elif file_extension == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):  # 주석 제외
                    parts = line.split()
                    if len(parts) >= 1:
                        code = parts[0].zfill(6)
                        name = parts[1] if len(parts) > 1 else code
                        stock_codes.append(code)
                        stock_names[code] = name
            
            print(f"✅ TXT 파일에서 {len(stock_codes)}개 종목 로드")
        
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

class EnhancedProgressTracker:
    """강화된 진행상황 추적 클래스 (절대조건 통계 포함)"""
    
    def __init__(self, total_count):
        self.total_count = total_count
        self.analyzed_count = 0
        self.error_count = 0
        self.filter_passed_count = 0
        self.filter_failed_count = 0
        self.start_time = datetime.now()
        self.last_report_time = self.start_time
    
    def update(self, success=True, filter_passed=False):
        """진행상황 업데이트 (절대조건 통과 여부 포함)"""
        if success:
            self.analyzed_count += 1
            if filter_passed:
                self.filter_passed_count += 1
            else:
                self.filter_failed_count += 1
        else:
            self.error_count += 1
        
        # 50개마다 또는 5분마다 진행상황 출력
        total_processed = self.analyzed_count + self.error_count
        current_time = datetime.now()
        time_since_last_report = (current_time - self.last_report_time).total_seconds()
        
        if total_processed % 50 == 0 or time_since_last_report >= 300:  # 5분
            elapsed = current_time - self.start_time
            rate = total_processed / elapsed.total_seconds() * 60  # 분당 처리율
            
            print(f"📊 진행: {total_processed}/{self.total_count} "
                  f"(성공: {self.analyzed_count}, 오류: {self.error_count}) "
                  f"✅통과: {self.filter_passed_count}, 🚫미통과: {self.filter_failed_count} "
                  f"처리율: {rate:.1f}개/분")
            
            self.last_report_time = current_time
    
    def get_summary(self):
        """최종 요약 반환 (절대조건 통계 포함)"""
        elapsed = datetime.now() - self.start_time
        return {
            "analyzed_count": self.analyzed_count,
            "error_count": self.error_count,
            "filter_passed_count": self.filter_passed_count,
            "filter_failed_count": self.filter_failed_count,
            "total_processed": self.analyzed_count + self.error_count,
            "elapsed_time": elapsed.total_seconds(),
            "success_rate": self.analyzed_count / (self.analyzed_count + self.error_count) * 100 if (self.analyzed_count + self.error_count) > 0 else 0,
            "filter_pass_rate": self.filter_passed_count / (self.filter_passed_count + self.filter_failed_count) * 100 if (self.filter_passed_count + self.filter_failed_count) > 0 else 0
        }

def validate_absolute_conditions_in_file(file_path, logger):
    """
    저장된 파일의 종목들이 실제로 절대조건을 만족하는지 검증
    
    Args:
        file_path: 검증할 JSON 파일 경로
        logger: 로거 객체
    """
    try:
        if not os.path.exists(file_path):
            logger.warning(f"검증할 파일이 없습니다: {file_path}")
            return
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data:
            logger.warning("검증할 데이터가 없습니다.")
            return
        
        logger.info(f"📋 {file_path} 파일의 {len(data)}개 종목 절대조건 검증 시작")
        
        valid_count = 0
        invalid_count = 0
        
        for item in data:
            code = item.get('code', 'Unknown')
            name = item.get('name', 'Unknown')
            signals = item.get('signals', [])
            
            # 절대조건 확인
            has_ma5_below_ma20 = "5일선20일선아래" in signals
            filter_status = item.get('filter_status', '')
            
            if has_ma5_below_ma20 and filter_status == '절대조건통과':
                valid_count += 1
                logger.debug(f"✅ {name}({code}): 절대조건 확인")
            else:
                invalid_count += 1
                logger.warning(f"⚠️ {name}({code}): 절대조건 의심")
                if not has_ma5_below_ma20:
                    logger.warning(f"   - 5일선20일선아래 신호 없음")
                if filter_status != '절대조건통과':
                    logger.warning(f"   - 필터 상태: {filter_status}")
        
        logger.info(f"📊 검증 완료: 유효 {valid_count}개, 의심 {invalid_count}개")
        
        if invalid_count > 0:
            logger.warning(f"⚠️ {invalid_count}개 종목이 절대조건을 만족하지 않을 수 있습니다.")
        else:
            logger.info("✅ 모든 종목이 절대조건을 만족합니다.")
            
    except Exception as e:
        logger.error(f"❌ 파일 검증 중 오류: {e}")

# 기존 함수들을 새로운 이름으로 호출하는 래퍼 (하위 호환성)
def save_backtest_candidates(candidates, logger):
    """기존 함수명 지원"""
    return save_enhanced_backtest_candidates(candidates, logger, include_filter_info=True)

def format_multi_signal_message(grade, stocks):
    """기존 함수명 지원"""
    return format_enhanced_multi_signal_message(grade, stocks)

def format_signal_combination_message(combinations):
    """기존 함수명 지원"""
    return format_enhanced_signal_combination_message(combinations)

# 새로운 Progress Tracker 클래스 (기존 호환성)
ProgressTracker = EnhancedProgressTracker
