"""
일봉 데이터 수집 배치 프로그램
시가총액 상위 종목의 일봉 데이터를 DB에 저장 (코스피+코스닥 통합)

사용법:
  python daily_collector.py --daily         # 일일 배치 (300종목, 최근 7일) - 매일 실행 권장
  python daily_collector.py --test          # 테스트 모드 (5종목, 30일)
  python daily_collector.py --stocks 10     # 10종목
  python daily_collector.py --days 60       # 60일 데이터
  python daily_collector.py                 # 전체 실행 (300종목)
"""
import sys
import os
import time
import pandas as pd
import argparse
from datetime import datetime, timedelta
from typing import Dict, List
import logging

# 현재 디렉토리(analyze)의 모듈들 import
from data_fetcher import DataFetcher
from db_manager import DBManager

try:
    import yaml
except ImportError:
    print("❌ PyYAML 패키지가 필요합니다: pip install PyYAML")
    sys.exit(1)


class ConfigManager:
    """간단한 설정 관리 클래스"""
    
    def __init__(self, config_path="config.yaml"):
        self.config_path = config_path
        self.config = {}
        self.load_config()
    
    def load_config(self):
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
            
            # 설정 확인
            if not self.config:
                print(f"⚠️ {self.config_path} 파일이 비어있거나 형식이 잘못되었습니다.")
                sys.exit(1)
                
        except FileNotFoundError:
            print(f"❌ 설정 파일 {self.config_path}을 찾을 수 없습니다.")
            print("💡 config.yaml 파일을 생성해주세요.")
            sys.exit(1)
    
    def get_kis_config(self):
        kis_config = self.config.get('kis', {})
        if not kis_config:
            print("❌ config.yaml에 'kis' 섹션이 없습니다.")
            sys.exit(1)
        return kis_config
    
    def get_database_config(self):
        db_config = self.config.get('database', {})
        if not db_config:
            print("❌ config.yaml에 'database' 섹션이 없습니다.")
            print("💡 다음 형식으로 추가해주세요:")
            print("""
database:
  host: localhost
  port: 3306
  user: stock_user
  password: stock2026!
  database: stock_trading
  charset: utf8mb4
""")
            sys.exit(1)
        return db_config
    
    def get_batch_config(self):
        return self.config.get('batch', {
            'data_days': 365,
            'retry_count': 3,
            'api_delay': 0.2,
            'bulk_insert_size': 100
        })


class DailyDataCollector:
    """일봉 데이터 수집 클래스"""
    
    def __init__(self, max_stocks: int = None, data_days: int = None, test_mode: bool = False):
        """
        초기화
        
        Args:
            max_stocks: 수집할 최대 종목 수 (None이면 전체)
            data_days: 수집할 일수 (None이면 config 값 사용)
            test_mode: 테스트 모드 (True면 5종목, 30일)
        """
        # 로거 설정
        self.setup_logger()
        
        # 테스트 모드 설정
        if test_mode:
            self.max_stocks = 5
            self.data_days = 30
            self.logger.info("🧪 테스트 모드 활성화: 5종목, 30일 데이터 수집")
        else:
            self.max_stocks = max_stocks
            self.data_days = data_days
        
        # 설정 로드
        self.config_manager = ConfigManager()
        self.kis_config = self.config_manager.get_kis_config()
        self.db_config = self.config_manager.get_database_config()
        self.batch_config = self.config_manager.get_batch_config()
        
        # 디버그: 설정 확인
        self.logger.info(f"🔍 DB 설정 확인: host={self.db_config.get('host')}, "
                        f"user={self.db_config.get('user')}, "
                        f"database={self.db_config.get('database')}")
        
        # data_days가 지정되지 않았으면 config에서 가져오기
        if self.data_days is None:
            self.data_days = self.batch_config.get('data_days', 365)
        
        # DataFetcher 초기화 (analyze 방식)
        self.data_fetcher = DataFetcher()
        
        # DB 매니저 초기화
        self.db_manager = DBManager(self.db_config, self.logger)
        
        # 통계
        self.stats = {
            'total_stocks': 0,
            'success_stocks': 0,
            'fail_stocks': 0,
            'total_records': 0,
            'success_records': 0,
            'fail_records': 0
        }
    
    def setup_logger(self):
        """로거 설정"""
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, f"daily_batch_{datetime.now().strftime('%Y%m%d')}.log")
        
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
        """시가총액 상위 종목 조회 (코스피+코스닥 통합)"""
        max_stocks = self.max_stocks if self.max_stocks else 300
        self.logger.info(f"📊 시가총액 상위 {max_stocks}개 종목 조회 시작 (코스피+코스닥)...")

        all_stocks = []  # (종목코드, 종목명, 시가총액, 시장구분)
        exclude_keywords = ["KODEX", "TIGER", "PLUS", "ACE", "ETF", "ETN", "리츠", "우", "스팩", "커버드"]

        try:
            import requests
            from bs4 import BeautifulSoup

            # 코스피(sosok=0)와 코스닥(sosok=1) 모두 수집
            for market_type in [0, 1]:
                market_name = "코스피" if market_type == 0 else "코스닥"
                self.logger.info(f"  📋 {market_name} 종목 수집 중...")

                for page in range(1, 15):  # 각 시장당 최대 15페이지
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

                            # 시가총액 파싱 (억원 단위)
                            market_cap = 0
                            cols = row.select("td")
                            if len(cols) >= 7:
                                market_cap_text = cols[6].text.strip().replace(",", "")
                                try:
                                    market_cap = int(market_cap_text) if market_cap_text else 0
                                except:
                                    market_cap = 0

                            all_stocks.append({
                                'code': code,
                                'name': name,
                                'market_cap': market_cap,
                                'market': market_name
                            })

                    time.sleep(0.3)

                    # 충분히 수집했으면 중단
                    if len(all_stocks) >= max_stocks * 2:
                        break

            # 시가총액 기준으로 정렬 (내림차순)
            all_stocks.sort(key=lambda x: x['market_cap'], reverse=True)

            # 상위 N개 선택
            top_stocks = all_stocks[:max_stocks]

            # 딕셔너리로 변환 (code: name)
            result = {stock['code']: stock['name'] for stock in top_stocks}

            # 통계 출력
            kospi_count = sum(1 for s in top_stocks if s['market'] == '코스피')
            kosdaq_count = sum(1 for s in top_stocks if s['market'] == '코스닥')

            self.logger.info(f"✅ {len(result)}개 종목 조회 완료")
            self.logger.info(f"   - 코스피: {kospi_count}개, 코스닥: {kosdaq_count}개")

            return result

        except Exception as e:
            self.logger.error(f"❌ 종목 리스트 조회 실패: {e}")
            return {}
    
    def collect_daily_data(self, stock_code: str, stock_name: str) -> List[Dict]:
        """종목별 일봉 데이터 수집 (365일 이상 대응 + 투자자별 매매)"""
        try:
            all_records = []
            
            # API는 한 번에 최대 100일치만 반환
            # 365일 수집 시 여러 번 호출 필요
            if self.data_days > 100:
                self.logger.debug(f"📅 {stock_name}: {self.data_days}일 데이터를 여러 번 나눠서 조회")
                
                # 오늘부터 과거로 100일씩 조회
                from datetime import datetime, timedelta
                
                end_date = datetime.now()
                total_collected = 0
                
                # 100일씩 나눠서 조회 (최대 4번)
                for chunk_idx in range((self.data_days // 100) + 1):
                    if total_collected >= self.data_days:
                        break
                    
                    # 이번 청크의 날짜 범위 계산
                    chunk_end = end_date - timedelta(days=chunk_idx * 100)
                    chunk_start = chunk_end - timedelta(days=99)  # 100일
                    
                    self.logger.debug(f"  청크 {chunk_idx+1}: {chunk_start.strftime('%Y-%m-%d')} ~ {chunk_end.strftime('%Y-%m-%d')}")
                    
                    # API 호출 (직접 날짜 지정)
                    df = self._fetch_data_by_date_range(stock_code, chunk_start, chunk_end)
                    
                    if df is not None and not df.empty:
                        # 데이터 변환
                        chunk_records = self._convert_df_to_records(stock_code, df)
                        all_records.extend(chunk_records)
                        total_collected += len(chunk_records)
                        
                        self.logger.debug(f"  ✅ 청크 {chunk_idx+1}: {len(chunk_records)}건 수집 (누적: {total_collected}건)")
                    
                    # API 호출 간격
                    if chunk_idx < (self.data_days // 100):
                        time.sleep(0.3)
                
            else:
                # 100일 이하는 한 번에 조회
                df = self.data_fetcher.get_period_price_data(stock_code, days=self.data_days)
                
                if df is not None and not df.empty:
                    all_records = self._convert_df_to_records(stock_code, df)
            
            if not all_records:
                self.logger.warning(f"⚠️ {stock_name}({stock_code}): 데이터 없음")
                return []
            
            # 투자자별 매매 데이터 추가 수집
            all_records = self._enrich_with_investor_data(stock_code, stock_name, all_records)
            
            # 날짜순 정렬 및 중복 제거
            unique_records = {}
            for record in all_records:
                key = (record['stock_code'], record['trade_date'])
                if key not in unique_records:
                    unique_records[key] = record
            
            final_records = list(unique_records.values())
            final_records.sort(key=lambda x: x['trade_date'])
            
            self.logger.info(f"✅ {stock_name}({stock_code}): {len(final_records)}건 수집 (투자자 데이터 포함)")
            return final_records
            
        except Exception as e:
            self.logger.error(f"❌ {stock_name}({stock_code}) 데이터 수집 실패: {e}")
            return []
    
    def _enrich_with_investor_data(self, stock_code: str, stock_name: str, records: List[Dict]) -> List[Dict]:
        """투자자별 매매 데이터로 레코드 보강"""
        try:
            # 투자자별 매매 데이터 조회 (최근 100일)
            investor_data = self._fetch_investor_data(stock_code)
            
            if not investor_data:
                self.logger.debug(f"  ⚠️ {stock_name}: 투자자 데이터 없음")
                return records
            
            # 날짜별 매핑
            investor_map = {data['trade_date']: data for data in investor_data}
            
            # 기존 레코드에 투자자 데이터 추가
            enriched_count = 0
            for record in records:
                trade_date = record['trade_date']
                if trade_date in investor_map:
                    inv_data = investor_map[trade_date]
                    record.update({
                        'foreign_buy_qty': inv_data.get('foreign_buy_qty'),
                        'foreign_sell_qty': inv_data.get('foreign_sell_qty'),
                        'foreign_net_qty': inv_data.get('foreign_net_qty'),
                        'institution_buy_qty': inv_data.get('institution_buy_qty'),
                        'institution_sell_qty': inv_data.get('institution_sell_qty'),
                        'institution_net_qty': inv_data.get('institution_net_qty'),
                        'individual_buy_qty': inv_data.get('individual_buy_qty'),
                        'individual_sell_qty': inv_data.get('individual_sell_qty'),
                        'individual_net_qty': inv_data.get('individual_net_qty')
                    })
                    enriched_count += 1
            
            if enriched_count > 0:
                self.logger.debug(f"  💰 {stock_name}: 투자자 데이터 {enriched_count}건 추가")
            
            return records
            
        except Exception as e:
            self.logger.warning(f"  ⚠️ {stock_name}: 투자자 데이터 추가 실패: {e}")
            return records
    
    def _fetch_investor_data(self, stock_code: str) -> List[Dict]:
        """투자자별 매매 데이터 조회"""
        try:
            url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.data_fetcher.load_token()}",
                "appkey": self.data_fetcher.app_key,
                "appsecret": self.data_fetcher.app_secret,
                "tr_id": "FHKST01010900"
            }
            
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": stock_code
            }
            
            time.sleep(0.15)
            
            import requests
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get('output'):
                return []
            
            investor_records = []
            for row in data['output']:
                try:
                    trade_date_str = row.get('stck_bsop_date', '')
                    if len(trade_date_str) == 8:
                        trade_date = datetime.strptime(trade_date_str, '%Y%m%d').date()
                    else:
                        continue
                    
                    def safe_int(value):
                        try:
                            if isinstance(value, str):
                                return int(value.replace(',', '').strip())
                            return int(value) if value else 0
                        except:
                            return 0
                    
                    investor_records.append({
                        'trade_date': trade_date,
                        # 외국인
                        'foreign_buy_qty': safe_int(row.get('frgn_ntby_qty', 0)),  # 실제로는 순매수량
                        'foreign_sell_qty': 0,  # API에서 제공 안함
                        'foreign_net_qty': safe_int(row.get('frgn_ntby_qty', 0)),
                        # 기관
                        'institution_buy_qty': safe_int(row.get('orgn_ntby_qty', 0)),
                        'institution_sell_qty': 0,
                        'institution_net_qty': safe_int(row.get('orgn_ntby_qty', 0)),
                        # 개인
                        'individual_buy_qty': safe_int(row.get('prsn_ntby_qty', 0)),
                        'individual_sell_qty': 0,
                        'individual_net_qty': safe_int(row.get('prsn_ntby_qty', 0))
                    })
                except Exception as e:
                    continue
            
            return investor_records
            
        except Exception as e:
            self.logger.debug(f"투자자 데이터 조회 오류: {e}")
            return []
    
    def _fetch_data_by_date_range(self, stock_code: str, start_date, end_date):
        """날짜 범위로 데이터 조회 (직접 API 호출)"""
        try:
            url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.data_fetcher.load_token()}",
                "appkey": self.data_fetcher.app_key,
                "appsecret": self.data_fetcher.app_secret,
                "tr_id": "FHKST03010100"
            }
            
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": stock_code,
                "fid_input_date_1": start_date.strftime("%Y%m%d"),
                "fid_input_date_2": end_date.strftime("%Y%m%d"),
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "0"
            }
            
            time.sleep(0.1)
            
            import requests
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                
                # 데이터 타입 변환
                numeric_cols = ["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"]
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                
                df = df.dropna(subset=numeric_cols)
                df = df.sort_values(by="stck_bsop_date").reset_index(drop=True)
                
                return df
            
            return pd.DataFrame()

        except Exception as e:
            self.logger.error(f"❌ 날짜 범위 조회 실패 ({stock_code}): {e}")
            return pd.DataFrame()
    
    def _convert_df_to_records(self, stock_code: str, df: pd.DataFrame) -> List[Dict]:
        """DataFrame을 레코드 리스트로 변환"""
        records = []
        
        for _, row in df.iterrows():
            try:
                # 날짜 변환
                trade_date = None
                if 'stck_bsop_date' in row:
                    date_str = str(row['stck_bsop_date'])
                    if len(date_str) == 8:
                        trade_date = datetime.strptime(date_str, '%Y%m%d').date()
                
                if not trade_date:
                    continue
                
                # 컬럼명 확인
                close_col = 'stck_clpr' if 'stck_clpr' in row else 'stck_prpr'
                volume_col = 'acml_vol' if 'acml_vol' in row else 'cntg_vol'
                
                # 가격 데이터 변환
                record = {
                    'stock_code': stock_code,
                    'trade_date': trade_date,
                    'open_price': int(float(row.get('stck_oprc', 0))) if pd.notna(row.get('stck_oprc')) else None,
                    'high_price': int(float(row.get('stck_hgpr', 0))) if pd.notna(row.get('stck_hgpr')) else None,
                    'low_price': int(float(row.get('stck_lwpr', 0))) if pd.notna(row.get('stck_lwpr')) else None,
                    'close_price': int(float(row.get(close_col, 0))) if pd.notna(row.get(close_col)) else None,
                    'volume': int(float(row.get(volume_col, 0))) if pd.notna(row.get(volume_col)) else None,
                    'trading_value': int(float(row.get('acml_tr_pbmn', 0))) if pd.notna(row.get('acml_tr_pbmn')) else None
                }
                
                records.append(record)
                
            except Exception as e:
                self.logger.debug(f"⚠️ 레코드 변환 오류: {e}")
                continue
        
        return records
    
    def save_to_db(self, stock_code: str, stock_name: str, records: List[Dict]) -> bool:
        """DB에 데이터 저장"""
        try:
            if not records:
                return False
            
            # 종목 정보 저장
            if not self.db_manager.upsert_stock_info(stock_code, stock_name):
                return False
            
            # 일봉 데이터 저장 (bulk insert)
            bulk_size = self.batch_config.get('bulk_insert_size', 100)
            
            for i in range(0, len(records), bulk_size):
                batch = records[i:i+bulk_size]
                success, fail = self.db_manager.bulk_insert_daily_prices(batch)
                
                self.stats['success_records'] += success
                self.stats['fail_records'] += fail
            
            self.db_manager.commit()
            return True
            
        except Exception as e:
            self.logger.error(f"❌ DB 저장 실패 ({stock_code}): {e}")
            self.db_manager.rollback()
            return False
    
    def run(self):
        """배치 실행"""
        start_time = datetime.now()
        batch_id = 0
        
        try:
            self.logger.info("="*70)
            self.logger.info("🚀 일봉 데이터 수집 배치 시작")
            self.logger.info("="*70)
            
            # DB 연결
            if not self.db_manager.connect():
                raise Exception("데이터베이스 연결 실패")
            
            # 테이블 생성
            self.db_manager.create_tables()
            
            # 배치 시작 기록
            batch_id = self.db_manager.start_batch('DAILY_COLLECTION')
            
            # 종목 리스트 조회
            stock_list = self.get_top_stocks()
            if not stock_list:
                raise Exception("종목 리스트 조회 실패")
            
            self.stats['total_stocks'] = len(stock_list)
            
            # 각 종목별 데이터 수집
            api_delay = self.batch_config.get('api_delay', 0.2)
            
            self.logger.info(f"📈 수집 설정: {len(stock_list)}개 종목 × {self.data_days}일")
            
            for idx, (stock_code, stock_name) in enumerate(stock_list.items(), 1):
                try:
                    self.logger.info(f"\n[{idx}/{len(stock_list)}] {stock_name}({stock_code}) 처리 중...")
                    
                    # 일봉 데이터 수집
                    records = self.collect_daily_data(stock_code, stock_name)
                    
                    if records:
                        # DB 저장
                        if self.save_to_db(stock_code, stock_name, records):
                            self.stats['success_stocks'] += 1
                            self.stats['total_records'] += len(records)
                        else:
                            self.stats['fail_stocks'] += 1
                    else:
                        self.stats['fail_stocks'] += 1
                    
                    # API 호출 제한
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
                self.stats['success_stocks'],
                self.stats['fail_stocks']
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 배치 실행 실패: {e}")
            
            if batch_id:
                self.db_manager.end_batch(
                    batch_id, 'FAIL',
                    self.stats['total_stocks'],
                    self.stats['success_stocks'],
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
        self.logger.info(f"📋 수집 설정: {self.stats['total_stocks']}개 종목 × {self.data_days}일")
        self.logger.info(f"⏱️  소요 시간: {elapsed}")
        self.logger.info(f"📈 전체 종목: {self.stats['total_stocks']}개")
        self.logger.info(f"✅ 성공: {self.stats['success_stocks']}개")
        self.logger.info(f"❌ 실패: {self.stats['fail_stocks']}개")
        self.logger.info(f"📝 총 레코드: {self.stats['total_records']}건")
        self.logger.info(f"✅ 저장 성공: {self.stats['success_records']}건")
        self.logger.info(f"❌ 저장 실패: {self.stats['fail_records']}건")
        
        if self.stats['total_stocks'] > 0:
            success_rate = self.stats['success_stocks'] / self.stats['total_stocks'] * 100
            self.logger.info(f"📊 성공률: {success_rate:.1f}%")
        
        # 예상 시간 계산 (테스트 모드일 때 유용)
        if self.max_stocks and self.max_stocks < 200:
            estimated_full = elapsed.total_seconds() * (200 / self.stats['total_stocks'])
            estimated_minutes = int(estimated_full / 60)
            self.logger.info(f"💡 전체(200종목) 예상 시간: 약 {estimated_minutes}분")
        
        self.logger.info("="*70)


def main():
    """메인 실행 함수"""
    # 명령행 인자 파싱
    parser = argparse.ArgumentParser(
        description='일봉 데이터 수집 배치 프로그램',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 일일 배치 (300종목, 최근 7일) - 매일 실행 권장
  python daily_collector.py --daily

  # 테스트 모드 (5종목, 30일)
  python daily_collector.py --test

  # 10종목, 60일 수집
  python daily_collector.py --stocks 10 --days 60

  # 전체 실행 (300종목, config.yaml 설정값)
  python daily_collector.py
        """
    )
    
    parser.add_argument(
        '--test',
        action='store_true',
        help='테스트 모드 (5종목, 30일만 수집)'
    )
    
    parser.add_argument(
        '--stocks',
        type=int,
        metavar='N',
        help='수집할 종목 수 (기본값: 300, 코스피+코스닥 통합)'
    )
    
    parser.add_argument(
        '--days',
        type=int,
        metavar='N',
        help='수집할 일수 (기본값: config.yaml의 data_days)'
    )
    
    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='확인 프롬프트 건너뛰기'
    )

    parser.add_argument(
        '--daily',
        action='store_true',
        help='일일 배치 모드 (300종목, 최근 7일만 수집, 투자자 데이터 포함)'
    )

    args = parser.parse_args()
    
    try:
        # 일일 배치 모드 처리
        if args.daily:
            print("\n📅 일일 배치 모드로 실행합니다.")
            print("   - 종목 수: 300개 (코스피+코스닥)")
            print("   - 데이터 기간: 최근 7일")
            print("   - 투자자 데이터 포함")
            args.stocks = None  # 전체 종목
            args.days = 7  # 최근 7일
            args.yes = True  # 자동 실행

        # 설정 출력
        if args.test:
            print("\n🧪 테스트 모드로 실행합니다.")
            print("   - 종목 수: 5개")
            print("   - 데이터 기간: 30일")
        elif not args.daily:
            stocks_msg = f"{args.stocks}개" if args.stocks else "300개 (코스피+코스닥)"
            days_msg = f"{args.days}일" if args.days else "config.yaml 설정값"
            print(f"\n📊 배치 실행 설정:")
            print(f"   - 종목 수: {stocks_msg}")
            print(f"   - 데이터 기간: {days_msg}")

        # 확인 프롬프트 (테스트 모드나 --yes 옵션이 아닐 때만)
        if not args.test and not args.yes:
            print("\n시작하려면 Enter를 누르세요 (취소: Ctrl+C)...")
            input()

        # Collector 생성 및 실행
        collector = DailyDataCollector(
            max_stocks=args.stocks,
            data_days=args.days,
            test_mode=args.test
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
