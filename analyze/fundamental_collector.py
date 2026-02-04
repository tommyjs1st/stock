"""
펀더멘털 데이터 수집 배치 프로그램
네이버 금융에서 PER, PBR, ROE, 부채비율 등을 수집하여 DB에 저장

사용법:
  python fundamental_collector.py --daily         # 일일 배치 (300종목) - 주 1회 실행 권장
  python fundamental_collector.py --test          # 테스트 모드 (5종목)
  python fundamental_collector.py --stocks 50     # 50종목만
"""
import sys
import os
import time
import argparse
from datetime import datetime
from typing import Dict, List, Optional
import logging

# analyze 디렉토리의 모듈들 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'analyze'))

from data_fetcher import DataFetcher
from db_manager import DBManager

try:
    import yaml
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"❌ 필수 패키지가 없습니다: {e}")
    print("💡 설치: pip install PyYAML requests beautifulsoup4")
    sys.exit(1)


class ConfigManager:
    """설정 관리 클래스"""
    
    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self.config = {}
        self.load_config()
    
    def load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
            
            if not self.config:
                print(f"⚠️ {self.config_path} 파일이 비어있거나 형식이 잘못되었습니다.")
                sys.exit(1)
                
        except FileNotFoundError:
            print(f"❌ 설정 파일 {self.config_path}을 찾을 수 없습니다.")
            sys.exit(1)
    
    def get_database_config(self):
        db_config = self.config.get('database', {})
        if not db_config:
            print("❌ config.yaml에 'database' 섹션이 없습니다.")
            sys.exit(1)
        return db_config
    
    def get_batch_config(self):
        return self.config.get('batch', {
            'retry_count': 3,
            'api_delay': 0.5,  # 네이버 크롤링은 좀 더 여유있게
        })


class FundamentalCollector:
    """펀더멘털 데이터 수집 클래스"""
    
    def __init__(self, max_stocks: int = None, test_mode: bool = False, historical_mode: bool = False):
        """
        초기화
        
        Args:
            max_stocks: 수집할 최대 종목 수 (None이면 전체)
            test_mode: 테스트 모드 (True면 5종목)
            historical_mode: 과거 데이터 수집 모드 (True면 8분기 데이터 수집)
        """
        # 로거 설정
        self.setup_logger()
        
        # 모드 설정
        self.historical_mode = historical_mode
        
        # 테스트 모드 설정
        if test_mode:
            self.max_stocks = 5
            mode_msg = "과거 8분기 데이터" if historical_mode else "당일 데이터"
            self.logger.info(f"🧪 테스트 모드 활성화: 5종목만 수집 ({mode_msg})")
        else:
            self.max_stocks = max_stocks
        
        # 설정 로드
        self.config_manager = ConfigManager()
        self.db_config = self.config_manager.get_database_config()
        self.batch_config = self.config_manager.get_batch_config()
        
        # DataFetcher 초기화 (종목 리스트 조회용)
        self.data_fetcher = DataFetcher()
        
        # DB 매니저 초기화
        self.db_manager = DBManager(self.db_config, self.logger)
        
        # 통계
        self.stats = {
            'total_stocks': 0,
            'success_stocks': 0,
            'fail_stocks': 0,
            'partial_stocks': 0,  # 일부 데이터만 수집된 종목
        }
    
    def setup_logger(self):
        """로거 설정"""
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, f"fundamental_batch_{datetime.now().strftime('%Y%m%d')}.log")
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # 기존 핸들러 제거
        if self.logger.hasHandlers():
            self.logger.handlers.clear()
        
        # 파일 핸들러
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # 콘솔 핸들러
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # 포맷 설정
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def get_top_stocks(self) -> Dict[str, str]:
        """시가총액 상위 종목 조회 (DataFetcher 활용)"""
        max_stocks = self.max_stocks if self.max_stocks else 300
        self.logger.info(f"📊 시가총액 상위 {max_stocks}개 종목 조회 시작...")
        
        try:
            # DataFetcher의 메서드 활용
            all_stocks = {}
            exclude_keywords = ["KODEX", "TIGER", "PLUS", "ACE", "ETF", "ETN", "리츠", "우", "스팩", "커버드"]
            
            import requests
            from bs4 import BeautifulSoup
            
            # 코스피(sosok=0)와 코스닥(sosok=1) 모두 수집
            for market_type in [0, 1]:
                market_name = "코스피" if market_type == 0 else "코스닥"
                self.logger.info(f"  📋 {market_name} 종목 수집 중...")
                
                for page in range(1, 15):
                    url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok={market_type}&page={page}"
                    headers = {"User-Agent": "Mozilla/5.0"}
                    
                    response = requests.get(url, headers=headers, timeout=10)
                    soup = BeautifulSoup(response.text, "html.parser")
                    rows = soup.select("table.type_2 tr")
                    
                    for row in rows:
                        link = row.select_one("a.tltle")
                        if link:
                            name = link.text.strip()
                            href = link["href"]
                            code = href.split("=")[-1]
                            
                            # 제외 키워드 체크
                            if any(keyword in name for keyword in exclude_keywords):
                                continue
                            
                            all_stocks[code] = name
                    
                    time.sleep(0.3)
                    
                    # 충분히 수집했으면 중단
                    if len(all_stocks) >= max_stocks * 2:
                        break
            
            # 상위 N개만 선택 (딕셔너리는 삽입 순서 유지)
            result = dict(list(all_stocks.items())[:max_stocks])
            
            self.logger.info(f"✅ {len(result)}개 종목 조회 완료")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ 종목 리스트 조회 실패: {e}")
            return {}
    
    def collect_fundamental_data(self, stock_code: str, stock_name: str) -> Optional[Dict]:
        """네이버 금융에서 펀더멘털 데이터 크롤링"""
        try:
            url = f"https://finance.naver.com/item/main.nhn?code={stock_code}"
            headers = {"User-Agent": "Mozilla/5.0"}
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            def extract_number(label):
                """특정 라벨의 숫자 추출"""
                try:
                    element = soup.find(string=lambda s: s and label in s)
                    if not element:
                        return None
                    td = element.find_next("td")
                    if not td:
                        return None
                    text = td.text.replace(",", "").replace("%", "").replace("배", "").strip()
                    return float(text) if text else None
                except:
                    return None
            
            # 시가총액 추출 (별도 처리)
            market_cap = None
            try:
                market_cap_elem = soup.select_one("em#_market_sum")
                if market_cap_elem:
                    market_cap_text = market_cap_elem.text.replace(",", "").strip()
                    # "억" 단위로 표시되므로 100,000,000 곱해서 원 단위로 변환
                    market_cap = int(float(market_cap_text) * 100000000) if market_cap_text else None
            except:
                pass
            
            # 상장주식수 추출
            listed_shares = None
            try:
                shares_elem = soup.find(string=lambda s: s and "상장주식수" in s)
                if shares_elem:
                    td = shares_elem.find_next("td")
                    if td:
                        shares_text = td.text.replace(",", "").replace("주", "").strip()
                        # "억주" 단위면 100,000,000 곱하기
                        if "억" in td.text:
                            listed_shares = int(float(shares_text) * 100000000)
                        else:
                            listed_shares = int(float(shares_text)) if shares_text else None
            except:
                pass
            
            data = {
                "stock_code": stock_code,
                "trade_date": datetime.now().date(),
                "per": extract_number("PER"),
                "pbr": extract_number("PBR"),
                "roe": extract_number("ROE"),
                "debt_ratio": extract_number("부채비율"),
                "market_cap": market_cap,
                "listed_shares": listed_shares
            }
            
            # 최소 하나의 데이터라도 있으면 반환
            if any(v is not None for k, v in data.items() if k not in ['stock_code', 'trade_date']):
                # 수집된 데이터 개수 확인
                collected_count = sum(1 for k, v in data.items() 
                                     if k not in ['stock_code', 'trade_date'] and v is not None)
                self.logger.debug(f"  📊 {stock_name}: {collected_count}/6개 데이터 수집")
                return data
            else:
                self.logger.warning(f"  ⚠️ {stock_name}: 데이터 없음")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ {stock_name}({stock_code}) 크롤링 실패: {e}")
            return None
    
    def collect_historical_fundamental_data(self, stock_code: str, stock_name: str) -> List[Dict]:
        """네이버 투자지표에서 과거 8분기 펀더멘털 데이터 수집
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            
        Returns:
            List[Dict]: 분기별 펀더멘털 데이터 리스트
        """
        try:
            # 네이버 투자지표 페이지
            url = f"https://finance.naver.com/item/main.nhn?code={stock_code}"
            headers = {"User-Agent": "Mozilla/5.0"}
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            
            historical_data = []
            
            # 주요 투자지표 테이블 찾기
            tables = soup.select("table.tb_type1")
            
            for table in tables:
                # 테이블 헤더에서 날짜 추출 (예: 2024.12, 2024.09)
                date_headers = table.select("thead th")
                dates = []
                
                for th in date_headers:
                    date_text = th.text.strip()
                    # "2024.12" 형식 찾기
                    if "." in date_text and len(date_text) <= 7:
                        try:
                            year, month = date_text.split(".")
                            # 분기 종료일로 변환 (3,6,9,12월 말일)
                            if month in ["03", "3"]:
                                trade_date = f"{year}-03-31"
                            elif month in ["06", "6"]:
                                trade_date = f"{year}-06-30"
                            elif month in ["09", "9"]:
                                trade_date = f"{year}-09-30"
                            elif month in ["12"]:
                                trade_date = f"{year}-12-31"
                            else:
                                continue
                            dates.append(trade_date)
                        except:
                            continue
                
                if not dates:
                    continue
                
                # 각 행에서 데이터 추출
                rows = table.select("tbody tr")
                
                per_values = []
                pbr_values = []
                roe_values = []
                debt_values = []
                
                for row in rows:
                    label_td = row.select_one("th")
                    if not label_td:
                        continue
                    
                    label = label_td.text.strip()
                    value_tds = row.select("td")
                    
                    if "PER" in label and "PER" == label:
                        per_values = [self._extract_float(td.text) for td in value_tds]
                    elif "PBR" in label and "PBR" == label:
                        pbr_values = [self._extract_float(td.text) for td in value_tds]
                    elif "ROE" in label:
                        roe_values = [self._extract_float(td.text) for td in value_tds]
                    elif "부채비율" in label:
                        debt_values = [self._extract_float(td.text) for td in value_tds]
                
                # 분기별 데이터 조합
                for idx, trade_date in enumerate(dates):
                    if idx >= 8:  # 최대 8분기
                        break
                    
                    data = {
                        "stock_code": stock_code,
                        "trade_date": trade_date,
                        "per": per_values[idx] if idx < len(per_values) else None,
                        "pbr": pbr_values[idx] if idx < len(pbr_values) else None,
                        "roe": roe_values[idx] if idx < len(roe_values) else None,
                        "debt_ratio": debt_values[idx] if idx < len(debt_values) else None,
                        "market_cap": None,  # 과거 시가총액은 별도 페이지 필요
                        "listed_shares": None
                    }
                    
                    # 최소 하나의 데이터라도 있으면 추가
                    if any(v is not None for k, v in data.items() if k not in ['stock_code', 'trade_date', 'market_cap', 'listed_shares']):
                        historical_data.append(data)
            
            if historical_data:
                self.logger.debug(f"  📊 {stock_name}: {len(historical_data)}개 분기 데이터 수집")
                return historical_data
            else:
                self.logger.warning(f"  ⚠️ {stock_name}: 과거 데이터 없음")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ {stock_name}({stock_code}) 과거 데이터 수집 실패: {e}")
            return []
    
    def _extract_float(self, text: str) -> Optional[float]:
        """텍스트에서 숫자 추출"""
        try:
            cleaned = text.replace(",", "").replace("%", "").replace("배", "").strip()
            if cleaned and cleaned != "N/A" and cleaned != "-":
                return float(cleaned)
            return None
        except:
            return None
    
    def save_to_db(self, data: Dict) -> bool:
        """DB에 펀더멘털 데이터 저장"""
        try:
            if not data:
                return False
            
            # 🆕 추가: stock_info 테이블에 종목 정보 먼저 저장
            stock_code = data.get('stock_code')
            stock_name = self.current_stock_name  # 클래스 변수로 저장된 종목명
            
            if not self.db_manager.upsert_stock_info(stock_code, stock_name):
                self.logger.warning(f"⚠️ {stock_name}({stock_code}): stock_info 저장 실패")
            
            # fundamental_data 테이블에 INSERT/UPDATE
            success = self.db_manager.upsert_fundamental_data(data)
            
            if success:
                self.db_manager.commit()
                return True
            else:
                self.db_manager.rollback()
                return False
                
        except Exception as e:
            self.logger.error(f"❌ DB 저장 실패 ({data.get('stock_code')}): {e}")
            self.db_manager.rollback()
            return False
    
    def run(self):
        """배치 실행"""
        start_time = datetime.now()
        batch_id = 0
        
        try:
            mode_name = "과거 8분기 데이터" if self.historical_mode else "당일 데이터"
            self.logger.info("="*70)
            self.logger.info(f"🚀 펀더멘털 데이터 수집 배치 시작 ({mode_name})")
            self.logger.info("="*70)
            
            # DB 연결
            if not self.db_manager.connect():
                raise Exception("데이터베이스 연결 실패")
            
            # 테이블 생성 (fundamental_data 테이블 포함)
            self.db_manager.create_tables()
            
            # 배치 시작 기록
            batch_type = 'FUNDAMENTAL_HISTORICAL' if self.historical_mode else 'FUNDAMENTAL_COLLECTION'
            batch_id = self.db_manager.start_batch(batch_type)
            
            # 종목 리스트 조회
            stock_list = self.get_top_stocks()
            if not stock_list:
                raise Exception("종목 리스트 조회 실패")
            
            self.stats['total_stocks'] = len(stock_list)
            
            # 각 종목별 데이터 수집
            api_delay = self.batch_config.get('api_delay', 0.5)
            
            self.logger.info(f"📈 수집 대상: {len(stock_list)}개 종목 ({mode_name})")
            
            for idx, (stock_code, stock_name) in enumerate(stock_list.items(), 1):
                try:
                    self.logger.info(f"\n[{idx}/{len(stock_list)}] {stock_name}({stock_code}) 처리 중...")
                    
                    # 현재 종목명 저장 (save_to_db에서 사용)
                    self.current_stock_name = stock_name

                    if self.historical_mode:
                        # 과거 8분기 데이터 수집
                        data_list = self.collect_historical_fundamental_data(stock_code, stock_name)
                        
                        if data_list:
                            success_count = 0
                            for data in data_list:
                                if self.save_to_db(data):
                                    success_count += 1
                            
                            if success_count == len(data_list):
                                self.stats['success_stocks'] += 1
                                self.logger.info(f"✅ {stock_name}: {success_count}개 분기 저장 완료")
                            elif success_count > 0:
                                self.stats['partial_stocks'] += 1
                                self.logger.info(f"⚠️ {stock_name}: {success_count}/{len(data_list)}개 분기 저장")
                            else:
                                self.stats['fail_stocks'] += 1
                        else:
                            self.stats['fail_stocks'] += 1
                    else:
                        # 당일 데이터 수집
                        data = self.collect_fundamental_data(stock_code, stock_name)
                        
                        if data:
                            # 수집된 데이터 항목 수 확인
                            collected_count = sum(1 for k, v in data.items() 
                                                 if k not in ['stock_code', 'trade_date'] and v is not None)
                            
                            # DB 저장
                            if self.save_to_db(data):
                                if collected_count == 6:  # 모든 데이터 수집
                                    self.stats['success_stocks'] += 1
                                    self.logger.info(f"✅ {stock_name}: 완전 수집 ({collected_count}/6)")
                                else:  # 일부만 수집
                                    self.stats['partial_stocks'] += 1
                                    self.logger.info(f"⚠️ {stock_name}: 부분 수집 ({collected_count}/6)")
                            else:
                                self.stats['fail_stocks'] += 1
                        else:
                            self.stats['fail_stocks'] += 1
                    
                    # 크롤링 간격 (네이버 서버 부하 방지)
                    time.sleep(api_delay)
                    
                    # 진행상황 출력
                    if idx % 10 == 0:
                        self.logger.info(f"📊 진행률: {idx}/{len(stock_list)} ({idx/len(stock_list)*100:.1f}%)")
                    
                except Exception as e:
                    self.logger.error(f"❌ {stock_name}({stock_code}) 처리 실패: {e}")
                    self.stats['fail_stocks'] += 1
                    continue
            
            # 결과 출력
            self.print_summary(start_time)
            
            # 배치 종료 기록
            self.db_manager.end_batch(
                batch_id, 'SUCCESS',
                self.stats['total_stocks'],
                self.stats['success_stocks'] + self.stats['partial_stocks'],
                self.stats['fail_stocks']
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 배치 실행 실패: {e}")
            
            if batch_id:
                self.db_manager.end_batch(
                    batch_id, 'FAIL',
                    self.stats['total_stocks'],
                    self.stats['success_stocks'] + self.stats['partial_stocks'],
                    self.stats['fail_stocks'],
                    str(e)
                )
            
            return False
            
        finally:
            self.db_manager.disconnect()
    
    def print_summary(self, start_time: datetime):
        """결과 요약 출력"""
        elapsed = datetime.now() - start_time
        
        self.logger.info("\n" + "="*70)
        self.logger.info("📊 배치 실행 결과")
        self.logger.info("="*70)
        self.logger.info(f"📋 수집 대상: {self.stats['total_stocks']}개 종목")
        self.logger.info(f"⏱️  소요 시간: {elapsed}")
        self.logger.info(f"✅ 완전 수집: {self.stats['success_stocks']}개 (6/6)")
        self.logger.info(f"⚠️ 부분 수집: {self.stats['partial_stocks']}개 (일부만)")
        self.logger.info(f"❌ 실패: {self.stats['fail_stocks']}개")
        
        if self.stats['total_stocks'] > 0:
            total_success = self.stats['success_stocks'] + self.stats['partial_stocks']
            success_rate = total_success / self.stats['total_stocks'] * 100
            self.logger.info(f"📊 성공률: {success_rate:.1f}% (부분 수집 포함)")
        
        self.logger.info("="*70)


def main():
    """메인 실행 함수"""
    parser = argparse.ArgumentParser(
        description='펀더멘털 데이터 수집 배치 프로그램',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 일일 배치 (300종목, 당일 데이터) - 주 1회 실행 권장
  python fundamental_collector.py --daily

  # 과거 데이터 수집 (300종목, 8분기) - 초기 구축 시 1회만
  python fundamental_collector.py --historical --stocks 300

  # 테스트 모드 (5종목, 당일 데이터)
  python fundamental_collector.py --test

  # 테스트 모드 (5종목, 8분기 데이터)
  python fundamental_collector.py --historical --test

  # 50종목만 수집
  python fundamental_collector.py --stocks 50

  # 전체 실행 (300종목, 당일 데이터)
  python fundamental_collector.py
        """
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='테스트 모드 (5종목만 수집)'
    )
    
    parser.add_argument(
        '--stocks',
        type=int,
        metavar='N',
        help='수집할 종목 수 (기본값: 300)'
    )
    
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='확인 프롬프트 건너뛰기'
    )
    
    parser.add_argument(
        '--daily',
        action='store_true',
        help='일일 배치 모드 (300종목, 당일 시점 데이터)'
    )
    
    parser.add_argument(
        '--historical',
        action='store_true',
        help='과거 데이터 수집 모드 (8분기 데이터 수집, 초기 구축용)'
    )
    
    args = parser.parse_args()
    
    try:
        # 일일 배치 모드 처리
        if args.daily:
            print("\n📅 일일 배치 모드로 실행합니다.")
            print("   - 종목 수: 300개 (코스피+코스닥)")
            print("   - 수집 항목: PER, PBR, ROE, 부채비율, 시가총액, 상장주식수")
            print("   - 수집 기간: 당일 1일치")
            args.stocks = None  # 전체 종목
            args.yes = True  # 자동 실행
        
        # 설정 출력
        if args.historical:
            mode_msg = "과거 8분기 데이터"
            print(f"\n🕒 과거 데이터 수집 모드 ({mode_msg})")
            if args.test:
                print("   - 종목 수: 5개 (테스트)")
            else:
                stocks_msg = f"{args.stocks}개" if args.stocks else "300개 (코스피+코스닥)"
                print(f"   - 종목 수: {stocks_msg}")
            print("   - 수집 항목: PER, PBR, ROE, 부채비율 (분기별)")
            print("   ⚠️  주의: 초기 구축 시에만 1회 실행하세요")
        elif args.test:
            print("\n🧪 테스트 모드로 실행합니다.")
            print("   - 종목 수: 5개")
            print("   - 수집 기간: 당일 1일치")
        elif not args.daily:
            stocks_msg = f"{args.stocks}개" if args.stocks else "300개 (코스피+코스닥)"
            print(f"\n📊 배치 실행 설정:")
            print(f"   - 종목 수: {stocks_msg}")
            print("   - 수집 기간: 당일 1일치")
        
        # 확인 프롬프트 (테스트 모드나 --yes 옵션이 아닐 때만)
        if not args.test and not args.yes:
            print("\n시작하려면 Enter를 누르세요 (취소: Ctrl+C)...")
            input()
        
        # Collector 생성 및 실행
        collector = FundamentalCollector(
            max_stocks=args.stocks,
            test_mode=args.test,
            historical_mode=args.historical
        )
        
        success = collector.run()
        
        if success:
            print("\n✅ 배치 실행 완료!")
            return 0
        else:
            print("\n❌ 배치 실행 실패!")
            return 1
            
    except KeyboardInterrupt:
        print("\n⚠️ 사용자에 의해 중단되었습니다.")
        return 1
    except Exception as e:
        print(f"\n❌ 심각한 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

