"""
데이터 조회 모듈
주가 데이터, 투자자별 매매 데이터 등 조회
"""
import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import logging
from datetime import datetime, timedelta
from kis_api_client import KISAPIClient

logger = logging.getLogger(__name__)

class DataFetcher(KISAPIClient):
    def __init__(self):
        super().__init__()
        self.db_manager = None  # DB 매니저는 필요시 외부에서 설정

    def set_db_manager(self, db_manager):
        """DB 매니저 설정"""
        self.db_manager = db_manager

    def get_current_price(self, stock_code):
        """실시간 현재가 조회 (전일 종가 포함)"""
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code
        }

        try:
            data = self.api_request(url, params, "FHKST01010100")
            if data and "output" in data:
                output = data["output"]
                current_price = float(output.get("stck_prpr", 0))  # 현재가
                current_volume = int(output.get("acml_vol", 0))    # 거래량
                prev_close = float(output.get("stck_sdpr", 0))     # 전일종가
                return current_price, current_volume, prev_close
        except Exception as e:
            logger.error(f"❌ {stock_code}: 현재가 조회 오류: {e}")

        return None, None, None

    def get_period_price_data(self, stock_code, days=90, period="D"):
        """기간별 주가 데이터 조회"""
        end_date = datetime.now()
        # 주말/공휴일 고려하여 넉넉하게 조회 (요청 일수의 1.5배 정도)
        start_date = end_date - timedelta(days=int(days * 1.5) + 10)

        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
            "fid_input_date_1": start_date.strftime("%Y%m%d"),
            "fid_input_date_2": end_date.strftime("%Y%m%d"),
            "fid_period_div_code": period,
            "fid_org_adj_prc": "0"
        }

        try:
            data = self.api_request(url, params, "FHKST03010100")
            if not data or "output2" not in data or not data["output2"]:
                return None

            df = pd.DataFrame(data["output2"])

            # 컬럼명 표준화
            df = df.rename(columns={
                'stck_bsop_date': 'stck_bsop_date',
                'stck_clpr': 'stck_clpr',
                'stck_oprc': 'stck_oprc',
                'stck_hgpr': 'stck_hgpr',
                'stck_lwpr': 'stck_lwpr',
                'acml_vol': 'acml_vol'
            })

            # 데이터 타입 변환
            numeric_cols = ["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"]
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            # 결측치 제거 및 정렬
            df = df.dropna(subset=numeric_cols)
            df = df.sort_values(by="stck_bsop_date").reset_index(drop=True)

            # 요청한 거래일 수만큼만 반환 (최근 데이터)
            if len(df) > days:
                df = df.tail(days).reset_index(drop=True)

            logger.debug(f"✅ {stock_code}: {len(df)}일 데이터 조회 완료 (요청: {days}일)")
            return df

        except Exception as e:
            logger.error(f"❌ {stock_code}: 기간별 데이터 조회 오류: {e}")
            return None

    def get_daily_price_data_with_realtime(self, stock_code, days=90):
        """실시간 현재가가 포함된 일봉 데이터 조회"""
        # 기간별 데이터 조회
        df = self.get_period_price_data(stock_code, days)

        if df is None or df.empty:
            logger.error(f"❌ {stock_code}: 기간별 데이터 조회 실패")
            return None

        # 실시간 현재가 추가
        current_price, current_volume, prev_close = self.get_current_price(stock_code)

        if current_price and current_volume:
            today = datetime.now().strftime("%Y%m%d")

            # 오늘 데이터가 있으면 업데이트, 없으면 추가
            if len(df) > 0 and df.iloc[-1]["stck_bsop_date"] == today:
                df.loc[df.index[-1], "stck_clpr"] = current_price
                df.loc[df.index[-1], "acml_vol"] = current_volume
                logger.debug(f"📈 {stock_code}: 오늘 데이터 업데이트")
            else:
                new_row = {
                    "stck_bsop_date": today,
                    "stck_clpr": current_price,
                    "stck_hgpr": current_price,
                    "stck_lwpr": current_price,
                    "acml_vol": current_volume
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                logger.debug(f"📈 {stock_code}: 오늘 데이터 추가")

        return df

    def get_daily_data_from_db(self, stock_code, days=90):
        """로컬 DB에서 일봉 데이터 조회 (실시간 현재가 포함)

        Args:
            stock_code: 종목코드
            days: 조회 일수 (기본 90일)

        Returns:
            DataFrame: 일봉 데이터 또는 None
        """
        if not self.db_manager:
            logger.warning(f"⚠️ {stock_code}: DB 매니저가 설정되지 않음")
            return None

        try:
            # DB에서 일봉 데이터 조회
            data_list = self.db_manager.get_daily_prices(stock_code, days)

            if not data_list:
                logger.debug(f"⚠️ {stock_code}: DB에 데이터 없음")
                return None

            # DataFrame으로 변환
            df = pd.DataFrame(data_list)

            # 데이터 타입 변환
            numeric_cols = ["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"]
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            # 실시간 현재가 추가
            current_price, current_volume, prev_close = self.get_current_price(stock_code)

            if current_price and current_volume:
                today = datetime.now().strftime("%Y%m%d")

                # 오늘 데이터가 있으면 업데이트, 없으면 추가
                if len(df) > 0 and df.iloc[-1]["stck_bsop_date"] == today:
                    df.loc[df.index[-1], "stck_clpr"] = current_price
                    df.loc[df.index[-1], "acml_vol"] = current_volume
                    logger.debug(f"💾 {stock_code}: DB 데이터 + 오늘 실시간 업데이트")
                else:
                    new_row = {
                        "stck_bsop_date": today,
                        "stck_clpr": current_price,
                        "stck_hgpr": current_price,
                        "stck_lwpr": current_price,
                        "acml_vol": current_volume,
                        "stck_oprc": current_price
                    }
                    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                    logger.debug(f"💾 {stock_code}: DB 데이터 + 오늘 실시간 추가")
            else:
                logger.debug(f"💾 {stock_code}: DB 데이터 사용 ({len(df)}일)")

            return df

        except Exception as e:
            logger.error(f"❌ {stock_code}: DB 데이터 조회 오류: {e}")
            return None

    def get_foreign_netbuy_trend(self, stock_code, days=5):
        """외국인 순매수 추세 분석 (API 사용)"""
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code
        }

        try:
            data = self.api_request(url, params, "FHKST01010900")
            if not data or "output" not in data:
                return [], "unknown"

            netbuy_list = []
            for row in data["output"][:days]:
                qty = row.get("frgn_ntby_qty", "").replace(",", "").strip()
                if qty:
                    netbuy_list.append(int(qty))

            # 추세 분석
            if len(netbuy_list) >= 3:
                pos_days = sum(1 for x in netbuy_list if x > 0)
                if pos_days == days:
                    trend = "steady_buying"
                elif pos_days >= days * 0.6:
                    trend = "accumulating"
                elif pos_days <= days * 0.2:
                    trend = "distributing"
                else:
                    trend = "mixed"
            else:
                trend = "neutral"

            return netbuy_list, trend

        except Exception as e:
            logger.error(f"❌ {stock_code}: 외국인 추세 분석 오류: {e}")
            return [], "unknown"

    def get_foreign_netbuy_trend_from_db(self, stock_code, days=5):
        """외국인 순매수 추세 분석 (로컬 DB 사용)

        Args:
            stock_code: 종목코드
            days: 분석 일수 (기본 5일)

        Returns:
            tuple: (netbuy_list, trend)
        """
        if not self.db_manager:
            logger.warning(f"⚠️ {stock_code}: DB 매니저가 설정되지 않음")
            return [], "unknown"

        try:
            # DB에서 최근 일봉 데이터 조회
            data_list = self.db_manager.get_daily_prices(stock_code, days=days)

            if not data_list or len(data_list) < 3:
                logger.debug(f"⚠️ {stock_code}: DB에 외국인 데이터 부족 (최소 3일 필요)")
                return [], "unknown"

            # 최근 데이터부터 역순으로 정렬 (최신이 앞)
            data_list = sorted(data_list, key=lambda x: x['stck_bsop_date'], reverse=True)

            # 외국인 순매수량 추출
            netbuy_list = []
            for data in data_list[:days]:
                foreign_net_qty = data.get('foreign_net_qty')
                if foreign_net_qty is not None:
                    netbuy_list.append(int(foreign_net_qty))

            if len(netbuy_list) < 3:
                logger.debug(f"⚠️ {stock_code}: 외국인 데이터 부족")
                return [], "unknown"

            # 추세 분석
            pos_days = sum(1 for x in netbuy_list if x > 0)
            actual_days = len(netbuy_list)

            if pos_days == actual_days:
                trend = "steady_buying"
            elif pos_days >= actual_days * 0.6:
                trend = "accumulating"
            elif pos_days <= actual_days * 0.2:
                trend = "distributing"
            else:
                trend = "mixed"

            logger.debug(f"💾 {stock_code}: DB에서 외국인 추세 분석 - {trend}")
            return netbuy_list, trend

        except Exception as e:
            logger.error(f"❌ {stock_code}: DB 외국인 추세 분석 오류: {e}")
            return [], "unknown"

    def get_institution_netbuy_trend(self, stock_code, days=3):
        """기관 순매수 추세 분석"""
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code
        }
        
        try:
            data = self.api_request(url, params, "FHKST01010900")
            if not data or "output" not in data:
                return [], "unknown"
            
            netbuy_list = []
            for row in data["output"][:days]:
                qty = row.get("orgn_ntby_qty", "").replace(",", "").strip()
                if qty:
                    netbuy_list.append(int(qty))
            
            # 추세 분석
            if len(netbuy_list) >= 3:
                pos_days = sum(1 for x in netbuy_list if x > 0)
                if pos_days == days:
                    trend = "steady_buying"
                elif pos_days >= days * 0.6:
                    trend = "accumulating"
                else:
                    trend = "mixed"
            else:
                trend = "neutral"
            
            return netbuy_list, trend
            
        except Exception as e:
            logger.error(f"❌ {stock_code}: 기관 추세 분석 오류: {e}")
            return [], "unknown"

    def get_top_200_stocks(self, top_n=200):
        """네이버에서 시가총액 상위 N개 종목 조회 (코스피+코스닥 통합)"""
        all_stocks = []  # (종목명, 종목코드, 시가총액, 시장구분)
        exclude_keywords = ["KODEX", "TIGER", "PLUS", "ACE", "TIMEFOLIO", "ETF", "ETN", "리츠", "우", "스팩","채권", "국채", "레버리지"]
    
        try:
            # 코스피(sosok=0)와 코스닥(sosok=1) 모두 수집
            for market_type in [0, 1]:
                market_name = "코스피" if market_type == 0 else "코스닥"
                logger.info(f"📋 {market_name} 종목 수집 중...")
    
                for page in range(1, 12):  # 각 시장당 최대 12페이지
                    url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok={market_type}&page={page}"
                    headers = {"User-Agent": "Mozilla/5.0"}
                    res = requests.get(url, headers=headers, timeout=10)
                    res.raise_for_status()
                    soup = BeautifulSoup(res.text, "html.parser")
                    rows = soup.select("table.type_2 tr")
    
                    for row in rows:
                        try:
                            link = row.select_one("a.tltle")
                            if link:
                                name = link.text.strip()
                                href = link["href"]
                                code = href.split("=")[-1]
    
                                # ETF 등 제외
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
                                    'name': name,
                                    'code': code,
                                    'market_cap': market_cap,
                                    'market': market_name
                                })
                        except Exception:
                            continue
    
                    time.sleep(0.2)  # 요청 간격 조절
    
                    # 충분히 수집했으면 중단
                    if len(all_stocks) >= 400:
                        break
    
            # 시가총액 기준으로 정렬 (내림차순)
            all_stocks.sort(key=lambda x: x['market_cap'], reverse=True)
    
            # 상위 top_n개 선택
            top_stocks = all_stocks[:top_n]
    
            # 딕셔너리로 변환 (name: code)
            result = {stock['name']: stock['code'] for stock in top_stocks}
    
            # 통계 출력
            kospi_count = sum(1 for s in top_stocks if s['market'] == '코스피')
            kosdaq_count = sum(1 for s in top_stocks if s['market'] == '코스닥')
    
            logger.info(f"📊 총 {len(result)}개 종목 조회 완료 (코스피: {kospi_count}개, 코스닥: {kosdaq_count}개)")
            return result
    
        except Exception as e:
            logger.error(f"❌ 종목 리스트 조회 오류: {e}")
            return {}

    def get_minute_price_data(self, stock_code: str, time_unit: int = 1) -> pd.DataFrame:
        """분봉 데이터 조회

        Args:
            stock_code: 종목코드 (6자리)
            time_unit: 분 단위 (1, 3, 5, 10, 15, 30, 60)

        Returns:
            DataFrame: 분봉 데이터 (최대 30건)
        """
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"

        params = {
            "FID_ETC_CLS_CODE": "",
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_HOUR_1": "",  # 빈값: 전체 시간 조회
            "FID_PW_DATA_INCU_YN": "N"
        }

        try:
            data = self.api_request(url, params, "FHKST03010200")
            if not data or "output2" not in data or not data["output2"]:
                logger.warning(f"⚠️ {stock_code}: 분봉 데이터 없음")
                return pd.DataFrame()

            df = pd.DataFrame(data["output2"])

            # 컬럼 매핑
            column_mapping = {
                'stck_bsop_date': 'trade_date',      # 거래일자
                'stck_cntg_hour': 'trade_time',      # 체결시간
                'stck_prpr': 'close_price',          # 현재가(종가)
                'stck_oprc': 'open_price',           # 시가
                'stck_hgpr': 'high_price',           # 고가
                'stck_lwpr': 'low_price',            # 저가
                'cntg_vol': 'volume',                # 체결량
                'acml_tr_pbmn': 'trading_value'      # 누적거래대금
            }

            # 필요한 컬럼만 선택하고 이름 변경
            available_cols = [col for col in column_mapping.keys() if col in df.columns]
            df = df[available_cols].rename(columns=column_mapping)

            # 데이터 타입 변환
            numeric_cols = ['close_price', 'open_price', 'high_price', 'low_price', 'volume', 'trading_value']
            for col in numeric_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # trade_datetime 생성 (날짜 + 시간)
            if 'trade_date' in df.columns and 'trade_time' in df.columns:
                df['trade_datetime'] = pd.to_datetime(
                    df['trade_date'] + df['trade_time'],
                    format='%Y%m%d%H%M%S'
                )

            # 시간순 정렬
            if 'trade_datetime' in df.columns:
                df = df.sort_values('trade_datetime').reset_index(drop=True)

            logger.debug(f"✅ {stock_code}: 분봉 {len(df)}건 조회 완료")
            return df

        except Exception as e:
            logger.error(f"❌ {stock_code}: 분봉 데이터 조회 오류: {e}")
            return pd.DataFrame()

    def get_minute_price_data_extended(self, stock_code: str, count: int = 120) -> pd.DataFrame:
        """분봉 데이터 확장 조회 (여러 번 호출하여 더 많은 데이터 수집)

        Args:
            stock_code: 종목코드
            count: 수집할 분봉 개수 (최대 약 400개까지)

        Returns:
            DataFrame: 분봉 데이터
        """
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"

        all_data = []
        last_time = ""  # 빈값: 현재 시간부터 조회

        # 한 번에 30건씩 조회, 필요한 만큼 반복
        for i in range(max(1, count // 30)):
            params = {
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
                "FID_INPUT_HOUR_1": last_time,
                "FID_PW_DATA_INCU_YN": "Y"  # 과거 데이터 포함
            }

            try:
                data = self.api_request(url, params, "FHKST03010200")
                if not data or "output2" not in data or not data["output2"]:
                    break

                records = data["output2"]
                if not records:
                    break

                all_data.extend(records)

                # 다음 조회를 위해 마지막 시간 갱신
                last_record = records[-1]
                last_time = last_record.get('stck_cntg_hour', '090000')

                # 장 시작 시간 이전이면 중단
                if last_time < '090000':
                    break

                time.sleep(0.15)  # API 호출 제한 고려

            except Exception as e:
                logger.error(f"❌ {stock_code}: 분봉 확장 조회 오류: {e}")
                break

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)

        # 컬럼 매핑 및 변환
        column_mapping = {
            'stck_bsop_date': 'trade_date',
            'stck_cntg_hour': 'trade_time',
            'stck_prpr': 'close_price',
            'stck_oprc': 'open_price',
            'stck_hgpr': 'high_price',
            'stck_lwpr': 'low_price',
            'cntg_vol': 'volume',
            'acml_tr_pbmn': 'trading_value'
        }

        available_cols = [col for col in column_mapping.keys() if col in df.columns]
        df = df[available_cols].rename(columns=column_mapping)

        # 데이터 타입 변환
        numeric_cols = ['close_price', 'open_price', 'high_price', 'low_price', 'volume', 'trading_value']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # trade_datetime 생성
        if 'trade_date' in df.columns and 'trade_time' in df.columns:
            df['trade_datetime'] = pd.to_datetime(
                df['trade_date'] + df['trade_time'],
                format='%Y%m%d%H%M%S'
            )

        # 중복 제거 및 정렬
        if 'trade_datetime' in df.columns:
            df = df.drop_duplicates(subset=['trade_datetime'])
            df = df.sort_values('trade_datetime').reset_index(drop=True)

        logger.info(f"✅ {stock_code}: 분봉 {len(df)}건 확장 조회 완료")
        return df

    def get_fundamental_data_from_naver(self, stock_code):
        """네이버에서 기본적 분석 데이터 추출"""
        try:
            url = f"https://finance.naver.com/item/main.nhn?code={stock_code}"
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")

            def extract_number(label):
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

            return {
                "PER": extract_number("PER"),
                "PBR": extract_number("PBR"),
                "ROE": extract_number("ROE"),
                "부채비율": extract_number("부채비율")
            }
        except Exception as e:
            logger.error(f"❌ {stock_code}: 기본적 분석 데이터 조회 오류: {e}")
            return {"PER": None, "PBR": None, "ROE": None, "부채비율": None}
