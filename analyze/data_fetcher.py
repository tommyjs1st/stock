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

    def get_current_price(self, stock_code):
        """실시간 현재가 조회"""
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code
        }
        
        try:
            data = self.api_request(url, params, "FHKST01010100")
            if data and "output" in data:
                output = data["output"]
                current_price = float(output.get("stck_prpr", 0))
                current_volume = int(output.get("acml_vol", 0))
                return current_price, current_volume
        except Exception as e:
            logger.error(f"❌ {stock_code}: 현재가 조회 오류: {e}")
        
        return None, None

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
        current_price, current_volume = self.get_current_price(stock_code)
        
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

    def get_foreign_netbuy_trend(self, stock_code, days=5):
        """외국인 순매수 추세 분석"""
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
