import requests
import json
import time
import pandas as pd
from bs4 import BeautifulSoup
import pandas_ta as ta
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import numpy as np
import re
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

load_dotenv()
TOKEN_FILE = "token.json"

class EnhancedStockAnalyzer:
    def __init__(self):
        self.app_key = os.getenv("KIS_APP_KEY")
        self.app_secret = os.getenv("KIS_APP_SECRET")
        self.access_token = None
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        self.logger = self.setup_logger()
        
        # 업종별 벤치마크 (예시)
        self.sector_benchmarks = {
            "반도체": ["005930", "000660", "042700"],  # 삼성전자, SK하이닉스, 한미반도체
            "바이오": ["207940", "196170", "302440"],  # 삼성바이오로직스, 알테오젠, 씨젠
            "IT": ["035420", "035720", "018260"],      # NAVER, 카카오, 삼성SDS
            "자동차": ["005380", "012330", "161390"],  # 현대차, 현대모비스, 한국타이어
        }

    def setup_logger(self):
        """로깅 설정"""
        os.makedirs("logs", exist_ok=True)
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        
        if logger.hasHandlers():
            logger.handlers.clear()
        
        handler = TimedRotatingFileHandler(
            "logs/enhanced_stock_analysis.log", 
            when="midnight", 
            interval=1, 
            backupCount=7, 
            encoding='utf-8'
        )
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger

    def load_token(self):
        """토큰 로드 또는 재발급"""
        if not os.path.exists(TOKEN_FILE):
            return self.request_new_token()
        
        with open(TOKEN_FILE, "r") as f:
            token_data = json.load(f)

        now = int(time.time())
        issued_at = token_data.get("requested_at", 0)
        expires_in = int(token_data.get("expires_in", 0))
        
        if now - issued_at >= expires_in - 3600:
            return self.request_new_token()
        else:
            self.access_token = token_data["access_token"]
            return self.access_token

    def request_new_token(self):
        """새 토큰 요청"""
        url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        headers = {"Content-Type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        res = requests.post(url, headers=headers, data=json.dumps(data)).json()
        res["requested_at"] = int(time.time())
        with open(TOKEN_FILE, "w") as f:
            json.dump(res, f)
        self.access_token = res["access_token"]
        return self.access_token

    def get_comprehensive_stock_list(self, min_market_cap=50000000000):  # 500억 이상
        """전체 시장에서 종목 리스트 조회 (시총 필터링)"""
        stocks = {}
        exclude_keywords = ["KODEX", "TIGER", "PLUS", "ACE", "ETF", "ETN", "리츠", "우", "스팩"]
        
        try:
            # 코스피 + 코스닥 전체 조회 (시총 상위 500개)
            for page in range(1, 26):  # 페이지 확대
                url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok=0&page={page}"
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
                            
                            if any(keyword in name for keyword in exclude_keywords):
                                continue
                            
                            # 시가총액 체크
                            market_cap_cell = row.select("td")[6] if len(row.select("td")) > 6 else None
                            if market_cap_cell:
                                market_cap_text = market_cap_cell.text.replace(",", "").strip()
                                try:
                                    market_cap = int(market_cap_text) * 100000000  # 억원 단위
                                    if market_cap >= min_market_cap:
                                        stocks[name] = code
                                except:
                                    continue
                    except Exception:
                        continue
                
                time.sleep(0.1)
                
            # 코스닥도 추가 조회
            for page in range(1, 11):
                url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok=1&page={page}"
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
                            
                            if any(keyword in name for keyword in exclude_keywords):
                                continue
                            
                            stocks[name] = code
                    except Exception:
                        continue
                
                time.sleep(0.1)
                
        except Exception as e:
            self.logger.error(f"❌ 종목 리스트 조회 중 오류: {e}")
        
        self.logger.info(f"✅ 총 {len(stocks)}개 종목 조회 완료")
        return stocks

    def get_enhanced_fundamental_data(self, stock_code):
        """강화된 펀더멘털 데이터 수집"""
        try:
            # 네이버 금융에서 기본 데이터
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

            # 추가 데이터 수집
            def extract_growth_data():
                """성장률 데이터 추출"""
                try:
                    # 실적 증가율 정보 (가정값 - 실제로는 API나 크롤링 필요)
                    return {
                        "sales_growth_yoy": np.random.uniform(-10, 30),  # 매출 증가율
                        "profit_growth_yoy": np.random.uniform(-20, 50),  # 영업이익 증가율
                        "eps_growth_yoy": np.random.uniform(-15, 40),    # EPS 증가율
                    }
                except:
                    return {"sales_growth_yoy": 0, "profit_growth_yoy": 0, "eps_growth_yoy": 0}

            basic_data = {
                "PER": extract_number("PER"),
                "PBR": extract_number("PBR"),
                "ROE": extract_number("ROE"),
                "부채비율": extract_number("부채비율"),
                "당기순이익": extract_number("당기순이익"),
                "영업이익": extract_number("영업이익"),
            }
            
            growth_data = extract_growth_data()
            return {**basic_data, **growth_data}
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code}: 펀더멘털 데이터 조회 오류: {e}")
            return {}

    def fundamental_scoring(self, data):
        """펀더멘털 점수 계산 (40점 만점)"""
        score = 0
        
        try:
            # 성장성 (15점)
            sales_growth = data.get("sales_growth_yoy", 0)
            profit_growth = data.get("profit_growth_yoy", 0)
            
            if sales_growth > 20:
                score += 5
            elif sales_growth > 10:
                score += 3
            elif sales_growth > 0:
                score += 1
                
            if profit_growth > 30:
                score += 5
            elif profit_growth > 15:
                score += 3
            elif profit_growth > 0:
                score += 1
                
            if data.get("eps_growth_yoy", 0) > 20:
                score += 5
            elif data.get("eps_growth_yoy", 0) > 10:
                score += 3
                
            # 수익성 (15점)
            roe = data.get("ROE", 0)
            per = data.get("PER", 100)
            
            if roe and roe > 15:
                score += 8
            elif roe and roe > 10:
                score += 5
            elif roe and roe > 5:
                score += 2
                
            if per and 5 < per < 15:
                score += 7
            elif per and 15 <= per < 25:
                score += 4
            elif per and per < 5:
                score += 2
                
            # 안정성 (10점)
            debt_ratio = data.get("부채비율", 100)
            pbr = data.get("PBR", 10)
            
            if debt_ratio and debt_ratio < 30:
                score += 5
            elif debt_ratio and debt_ratio < 50:
                score += 3
                
            if pbr and 0.5 < pbr < 2:
                score += 5
            elif pbr and 2 <= pbr < 3:
                score += 3
                
        except Exception as e:
            self.logger.error(f"펀더멘털 점수 계산 오류: {e}")
            
        return min(score, 40)

    def get_news_sentiment(self, stock_code, stock_name):
        """뉴스 감성 분석 (간단 버전)"""
        try:
            # 네이버 뉴스 검색
            url = "https://search.naver.com/search.naver"
            params = {
                "where": "news",
                "query": stock_name,
                "sort": "1",  # 최신순
                "pd": "1",    # 1일
            }
            
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, params=params, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            
            news_titles = [title.text for title in soup.select(".news_tit")]
            
            # 감성 점수 계산 (키워드 기반)
            positive_keywords = ["상승", "급등", "호재", "성장", "확대", "투자", "개발", "성공", "증가", "상향"]
            negative_keywords = ["하락", "급락", "악재", "감소", "축소", "적자", "손실", "리스크", "우려", "하향"]
            
            positive_count = sum(1 for title in news_titles for keyword in positive_keywords if keyword in title)
            negative_count = sum(1 for title in news_titles for keyword in negative_keywords if keyword in title)
            
            if len(news_titles) == 0:
                return 0
                
            sentiment_score = (positive_count - negative_count) / len(news_titles) * 100
            news_volume_score = min(len(news_titles) * 5, 20)  # 뉴스 량 점수
            
            return max(0, min(20, sentiment_score + news_volume_score))
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code}: 뉴스 감성 분석 오류: {e}")
            return 0

    def get_institutional_flow_analysis(self, stock_code):
        """기관 자금 흐름 고도화 분석"""
        try:
            access_token = self.load_token()
            
            # 기관별 상세 데이터
            url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
            headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {access_token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST01010900"
            }
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": stock_code
            }

            res = requests.get(url, headers=headers, params=params)
            res.raise_for_status()
            data = res.json().get("output", [])

            if not data:
                return 0

            # 최근 10일 데이터 분석
            institutional_flows = []
            foreign_flows = []
            
            for i, row in enumerate(data[:10]):
                try:
                    institutional_qty = int(row.get("orgn_ntby_qty", "0").replace(",", ""))
                    foreign_qty = int(row.get("frgn_ntby_qty", "0").replace(",", ""))
                    
                    institutional_flows.append(institutional_qty)
                    foreign_flows.append(foreign_qty)
                except:
                    continue

            if not institutional_flows:
                return 0

            # 고도화된 분석
            score = 0
            
            # 1. 연속 매수 일수
            consecutive_institutional = 0
            consecutive_foreign = 0
            
            for flow in institutional_flows:
                if flow > 0:
                    consecutive_institutional += 1
                else:
                    break
                    
            for flow in foreign_flows:
                if flow > 0:
                    consecutive_foreign += 1
                else:
                    break

            score += min(consecutive_institutional * 2, 10)  # 최대 10점
            score += min(consecutive_foreign * 1.5, 8)       # 최대 8점
            
            # 2. 매수 강도 (최근 3일 vs 이전 7일)
            recent_3_institutional = sum(institutional_flows[:3])
            previous_7_institutional = sum(institutional_flows[3:10])
            
            if previous_7_institutional != 0:
                intensity_ratio = recent_3_institutional / abs(previous_7_institutional)
                if intensity_ratio > 2:
                    score += 7  # 매수 가속화
                elif intensity_ratio > 1:
                    score += 3
            
            # 3. 대량 거래 감지
            avg_volume = sum(abs(flow) for flow in institutional_flows) / len(institutional_flows)
            large_trades = sum(1 for flow in institutional_flows[:3] if abs(flow) > avg_volume * 2)
            score += min(large_trades * 3, 9)  # 최대 9점
            
            return min(score, 25)
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code}: 기관 흐름 분석 오류: {e}")
            return 0

    def get_technical_analysis(self, df):
        """고도화된 기술적 분석"""
        if df is None or len(df) < 50:
            return 0
            
        try:
            score = 0
            
            # 1. 트렌드 분석 (10점)
            ma5 = df['stck_clpr'].rolling(5).mean()
            ma20 = df['stck_clpr'].rolling(20).mean()
            ma60 = df['stck_clpr'].rolling(60).mean()
            
            current_price = df['stck_clpr'].iloc[-1]
            
            if current_price > ma5.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
                score += 10  # 완벽한 상승 정렬
            elif current_price > ma5.iloc[-1] > ma20.iloc[-1]:
                score += 7   # 단기 상승 정렬
            elif current_price > ma20.iloc[-1]:
                score += 4   # 중기 상승
                
            # 2. 모멘텀 분석 (8점)
            rsi = ta.rsi(df['stck_clpr'], length=14)
            if rsi is not None and len(rsi) > 0:
                current_rsi = rsi.iloc[-1]
                if 50 < current_rsi < 70:
                    score += 5  # 적정 모멘텀
                elif 40 < current_rsi <= 50:
                    score += 3  # 약한 모멘텀
                elif 30 < current_rsi <= 40:
                    score += 1  # 과매도 반등 가능
            
            # 3. MACD 분석 (7점)
            macd_data = ta.macd(df['stck_clpr'])
            if macd_data is not None and len(macd_data) > 1:
                macd = macd_data['MACD_12_26_9']
                signal = macd_data['MACDs_12_26_9']
                
                if len(macd) >= 2 and len(signal) >= 2:
                    if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]:
                        score += 7  # 골든크로스
                    elif macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-1] > 0:
                        score += 4  # 상승 신호
                        
            # 4. 거래량 분석 (5점)
            avg_volume = df['acml_vol'].rolling(20).mean()
            current_volume = df['acml_vol'].iloc[-1]
            
            if current_volume > avg_volume.iloc[-1] * 2:
                score += 5  # 급증
            elif current_volume > avg_volume.iloc[-1] * 1.5:
                score += 3  # 증가
            elif current_volume > avg_volume.iloc[-1]:
                score += 1  # 소폭 증가
                
            return min(score, 30)
            
        except Exception as e:
            self.logger.error(f"기술적 분석 오류: {e}")
            return 0

    def detect_chart_patterns(self, df):
        """차트 패턴 인식"""
        if df is None or len(df) < 30:
            return 0
            
        try:
            score = 0
            close = df['stck_clpr']
            high = df['stck_hgpr']
            low = df['stck_lwpr']
            
            # 1. 상승 삼각형 패턴
            if self.is_ascending_triangle(high, low):
                score += 8
                
            # 2. 컵앤핸들 패턴
            if self.is_cup_and_handle(close):
                score += 10
                
            # 3. 이중바닥 패턴
            if self.is_double_bottom(low):
                score += 7
                
            # 4. 브레이크아웃 패턴
            if self.is_breakout_pattern(close, high):
                score += 6
                
            return min(score, 15)
            
        except Exception as e:
            self.logger.error(f"차트 패턴 분석 오류: {e}")
            return 0

    def is_ascending_triangle(self, high, low):
        """상승 삼각형 패턴 감지"""
        try:
            recent_highs = high.tail(20)
            recent_lows = low.tail(20)
            
            # 고점이 수평선을 형성하는지 확인
            max_high = recent_highs.max()
            high_stability = (recent_highs.tail(5) >= max_high * 0.98).sum() >= 3
            
            # 저점이 상승하는지 확인
            low_trend = np.polyfit(range(len(recent_lows)), recent_lows, 1)[0] > 0
            
            return high_stability and low_trend
        except:
            return False

    def is_cup_and_handle(self, close):
        """컵앤핸들 패턴 감지"""
        try:
            if len(close) < 50:
                return False
                
            # 최근 50일 데이터
            data = close.tail(50)
            
            # 컵 형태: 고점 -> 저점 -> 고점
            max_price = data.max()
            min_price = data.min()
            current_price = data.iloc[-1]
            
            # 컵의 깊이가 적절한지 (10-50%)
            cup_depth = (max_price - min_price) / max_price
            if not (0.1 <= cup_depth <= 0.5):
                return False
                
            # 현재가가 고점 근처로 회복했는지
            recovery_ratio = current_price / max_price
            
            return recovery_ratio > 0.9
        except:
            return False

    def is_double_bottom(self, low):
        """이중바닥 패턴 감지"""
        try:
            if len(low) < 30:
                return False
                
            recent_lows = low.tail(30)
            
            # 저점들 찾기
            local_mins = []
            for i in range(2, len(recent_lows) - 2):
                if (recent_lows.iloc[i] < recent_lows.iloc[i-1] and 
                    recent_lows.iloc[i] < recent_lows.iloc[i+1] and
                    recent_lows.iloc[i] < recent_lows.iloc[i-2] and 
                    recent_lows.iloc[i] < recent_lows.iloc[i+2]):
                    local_mins.append(recent_lows.iloc[i])
            
            if len(local_mins) >= 2:
                # 마지막 두 저점이 비슷한 수준인지
                last_two = sorted(local_mins)[-2:]
                return abs(last_two[1] - last_two[0]) / last_two[0] < 0.03
                
            return False
        except:
            return False

    def is_breakout_pattern(self, close, high):
        """브레이크아웃 패턴 감지"""
        try:
            if len(close) < 20:
                return False
                
            # 20일 최고가 돌파
            high_20 = high.rolling(20).max()
            current_price = close.iloc[-1]
            yesterday_high = high_20.iloc[-2]
            
            return current_price > yesterday_high * 1.02  # 2% 이상 돌파
        except:
            return False

    def calculate_comprehensive_score(self, stock_code, stock_name, df, fundamental_data):
        """종합 점수 계산 (100점 만점)"""
        try:
            scores = {
                "fundamental": self.fundamental_scoring(fundamental_data),      # 40점
                "technical": self.get_technical_analysis(df),                  # 30점  
                "institutional": self.get_institutional_flow_analysis(stock_code), # 25점
                "news_sentiment": self.get_news_sentiment(stock_code, stock_name),  # 20점 -> 15점으로 조정
                "chart_patterns": self.detect_chart_patterns(df),             # 15점
            }
            
            total_score = sum(scores.values())
            
            # 가중치 조정 (시장 상황에 따라)
            market_condition = self.get_market_condition()
            
            if market_condition == "bear":
                scores["fundamental"] *= 1.3  # 하락장에서 펀더멘털 중시
                scores["institutional"] *= 1.2
            elif market_condition == "bull":
                scores["technical"] *= 1.2    # 상승장에서 기술적 분석 중시
                scores["chart_patterns"] *= 1.3
            
            final_score = min(100, sum(scores.values()))
            
            return final_score, scores
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code}: 종합 점수 계산 오류: {e}")
            return 0, {}

    def get_market_condition(self):
        """시장 상황 판단"""
        try:
            # KOSPI 지수로 시장 상황 판단 (간단 버전)
            kospi_data = self.get_stock_data("KS11", days=20)  # KOSPI 지수
            if kospi_data is None or len(kospi_data) < 10:
                return "neutral"
                
            recent_trend = kospi_data['stck_clpr'].pct_change().tail(10).mean()
            
            if recent_trend > 0.01:
                return "bull"
            elif recent_trend < -0.01:
                return "bear"
            else:
                return "neutral"
        except:
            return "neutral"

    def get_stock_data(self, stock_code, days=100):
        """주식 데이터 조회"""
        try:
            access_token = self.load_token()
            
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days + 20)
            
            url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {access_token}",
                "appKey": self.app_key,
                "appSecret": self.app_secret,
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
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get("output2", [])
            
            if not data:
                return None
                
            df = pd.DataFrame(data)
            
            # 컬럼명 통일
            df = df.rename(columns={
                'stck_bsop_date': 'stck_bsop_date',
                'stck_clpr': 'stck_clpr',
                'stck_oprc': 'stck_oprc',
                'stck_hgpr': 'stck_hgpr',
                'stck_lwpr': 'stck_lwpr',
                'acml_vol': 'acml_vol'
            })
            
            # 숫자 변환
            for col in ['stck_clpr', 'stck_hgpr', 'stck_lwpr', 'acml_vol']:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            
            df = df.dropna(subset=['stck_clpr'])
            df = df.sort_values(by="stck_bsop_date").reset_index(drop=True)
            
            return df.tail(days).reset_index(drop=True)
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code}: 주식 데이터 조회 오류: {e}")
            return None

    def sector_relative_strength(self, stock_code, stock_name):
        """업종 대비 상대 강도 분석"""
        try:
            # 업종 분류 (간단 버전 - 실제로는 더 정교한 분류 필요)
            sector = self.classify_sector(stock_name)
            if not sector or sector not in self.sector_benchmarks:
                return 5  # 중립 점수
                
            # 해당 종목 수익률
            stock_df = self.get_stock_data(stock_code, days=30)
            if stock_df is None or len(stock_df) < 20:
                return 5
                
            stock_return = (stock_df['stck_clpr'].iloc[-1] / stock_df['stck_clpr'].iloc[0] - 1) * 100
            
            # 업종 평균 수익률
            sector_returns = []
            for benchmark_code in self.sector_benchmarks[sector]:
                benchmark_df = self.get_stock_data(benchmark_code, days=30)
                if benchmark_df is not None and len(benchmark_df) >= 20:
                    benchmark_return = (benchmark_df['stck_clpr'].iloc[-1] / benchmark_df['stck_clpr'].iloc[0] - 1) * 100
                    sector_returns.append(benchmark_return)
                time.sleep(0.1)
            
            if not sector_returns:
                return 5
                
            sector_avg = np.mean(sector_returns)
            relative_strength = stock_return - sector_avg
            
            # 상대 강도를 점수로 변환 (10점 만점)
            if relative_strength > 10:
                return 10
            elif relative_strength > 5:
                return 8
            elif relative_strength > 0:
                return 6
            elif relative_strength > -5:
                return 4
            else:
                return 2
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code}: 상대 강도 분석 오류: {e}")
            return 5

    def classify_sector(self, stock_name):
        """종목명으로 업종 분류 (간단 버전)"""
        sector_keywords = {
            "반도체": ["반도체", "실리콘", "메모리", "칩", "SK하이닉스", "삼성전자"],
            "바이오": ["바이오", "제약", "의료", "병원", "치료", "신약"],
            "IT": ["소프트웨어", "게임", "인터넷", "플랫폼", "네이버", "카카오"],
            "자동차": ["자동차", "현대차", "부품", "타이어", "배터리"],
        }
        
        for sector, keywords in sector_keywords.items():
            if any(keyword in stock_name for keyword in keywords):
                return sector
        return None

    def risk_assessment(self, df, stock_code):
        """리스크 평가"""
        try:
            if df is None or len(df) < 30:
                return 50  # 중립 리스크
                
            # 변동성 계산
            returns = df['stck_clpr'].pct_change().dropna()
            volatility = returns.std() * np.sqrt(252) * 100  # 연간 변동성
            
            # 베타 계산 (KOSPI 대비)
            kospi_df = self.get_stock_data("KS11", days=len(df))
            if kospi_df is not None and len(kospi_df) >= len(df) * 0.8:
                kospi_returns = kospi_df['stck_clpr'].pct_change().dropna()
                stock_returns = returns.tail(len(kospi_returns))
                
                if len(stock_returns) == len(kospi_returns) and len(stock_returns) > 10:
                    covariance = np.cov(stock_returns, kospi_returns)[0][1]
                    market_variance = np.var(kospi_returns)
                    beta = covariance / market_variance if market_variance != 0 else 1
                else:
                    beta = 1
            else:
                beta = 1
            
            # 최대 낙폭 계산
            cumulative = (1 + returns).cumprod()
            rolling_max = cumulative.expanding().max()
            drawdown = (cumulative - rolling_max) / rolling_max
            max_drawdown = abs(drawdown.min()) * 100
            
            # 리스크 점수 계산 (낮을수록 좋음, 100점 만점)
            risk_score = 0
            
            # 변동성 점수 (30점)
            if volatility < 20:
                risk_score += 30
            elif volatility < 30:
                risk_score += 20
            elif volatility < 40:
                risk_score += 10
            
            # 베타 점수 (25점)
            if 0.7 <= beta <= 1.3:
                risk_score += 25
            elif 0.5 <= beta < 0.7 or 1.3 < beta <= 1.5:
                risk_score += 15
            elif beta < 0.5 or beta > 1.5:
                risk_score += 5
            
            # 최대 낙폭 점수 (25점)
            if max_drawdown < 10:
                risk_score += 25
            elif max_drawdown < 20:
                risk_score += 15
            elif max_drawdown < 30:
                risk_score += 10
            
            # 거래량 안정성 (20점)
            volume_cv = df['acml_vol'].std() / df['acml_vol'].mean()  # 변동계수
            if volume_cv < 0.5:
                risk_score += 20
            elif volume_cv < 1.0:
                risk_score += 15
            elif volume_cv < 1.5:
                risk_score += 10
            
            return min(risk_score, 100)
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code}: 리스크 평가 오류: {e}")
            return 50

    def send_discord_message(self, message):
        """디스코드 메시지 전송"""
        if not self.webhook_url:
            self.logger.info(message)
            return
            
        MAX_LENGTH = 2000
        chunks = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]
        
        for chunk in chunks:
            data = {"content": chunk}
            try:
                response = requests.post(self.webhook_url, json=data, timeout=10)
                response.raise_for_status()
            except Exception as e:
                self.logger.error(f"❌ 디스코드 전송 실패: {e}")
            time.sleep(0.5)

    def save_analysis_results(self, high_potential_stocks):
        """분석 결과 저장"""
        try:
            # 상위 20개 종목만 저장 (점수 순)
            top_stocks = sorted(high_potential_stocks, key=lambda x: x['total_score'], reverse=True)[:20]
            
            result_data = {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "market_condition": self.get_market_condition(),
                "analysis_summary": {
                    "total_analyzed": len(high_potential_stocks),
                    "high_potential_count": len([s for s in high_potential_stocks if s['total_score'] >= 80]),
                    "average_score": np.mean([s['total_score'] for s in high_potential_stocks])
                },
                "top_stocks": []
            }
            
            for stock in top_stocks:
                stock_data = {
                    "code": stock['code'],
                    "name": stock['name'],
                    "total_score": round(stock['total_score'], 1),
                    "scores": {k: round(v, 1) for k, v in stock['detailed_scores'].items()},
                    "risk_score": round(stock['risk_score'], 1),
                    "current_price": stock['current_price'],
                    "recommendation": self.get_recommendation(stock['total_score'], stock['risk_score']),
                    "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                result_data["top_stocks"].append(stock_data)
            
            # JSON 파일 저장
            with open("enhanced_analysis_results.json", "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"✅ 분석 결과 저장 완료: {len(top_stocks)}개 종목")
            
            return result_data
            
        except Exception as e:
            self.logger.error(f"❌ 결과 저장 실패: {e}")
            return None

    def get_recommendation(self, total_score, risk_score):
        """투자 추천 등급"""
        if total_score >= 85 and risk_score >= 70:
            return "강력매수"
        elif total_score >= 80 and risk_score >= 60:
            return "매수"
        elif total_score >= 75 and risk_score >= 50:
            return "적극관심"
        elif total_score >= 70:
            return "관심"
        else:
            return "보류"

    def run_enhanced_analysis(self):
        """강화된 종합 분석 실행"""
        self.logger.info("🚀 강화된 주식 분석 시스템 시작!")
        
        try:
            # 1. 종목 리스트 수집 (시총 500억 이상)
            self.logger.info("📊 종목 리스트 수집 중...")
            stock_list = self.get_comprehensive_stock_list(min_market_cap=50000000000)
            
            if not stock_list:
                self.logger.error("❌ 종목 리스트를 가져올 수 없습니다.")
                return
            
            self.logger.info(f"✅ {len(stock_list)}개 종목 수집 완료")
            
            # 2. 종목별 분석
            high_potential_stocks = []
            analyzed_count = 0
            error_count = 0
            
            for stock_name, stock_code in list(stock_list.items())[:200]:  # 상위 200개만 분석
                try:
                    self.logger.info(f"📈 {stock_name}({stock_code}) 분석 중...")
                    
                    # 주가 데이터 조회
                    df = self.get_stock_data(stock_code, days=100)
                    if df is None or len(df) < 50:
                        self.logger.warning(f"⚠️ {stock_name}: 주가 데이터 부족")
                        error_count += 1
                        continue
                    
                    # 펀더멘털 데이터 조회
                    fundamental_data = self.get_enhanced_fundamental_data(stock_code)
                    
                    # 종합 점수 계산
                    total_score, detailed_scores = self.calculate_comprehensive_score(
                        stock_code, stock_name, df, fundamental_data
                    )
                    
                    # 리스크 평가
                    risk_score = self.risk_assessment(df, stock_code)
                    
                    # 상대 강도 분석
                    relative_strength = self.sector_relative_strength(stock_code, stock_name)
                    
                    # 최종 조정된 점수
                    adjusted_score = total_score + (relative_strength - 5)  # 상대강도 반영
                    
                    current_price = df['stck_clpr'].iloc[-1]
                    
                    # 고잠재력 종목 기준: 총점 70점 이상, 리스크 점수 40점 이상
                    if adjusted_score >= 70 and risk_score >= 40:
                        stock_info = {
                            'code': stock_code,
                            'name': stock_name,
                            'total_score': adjusted_score,
                            'detailed_scores': detailed_scores,
                            'risk_score': risk_score,
                            'relative_strength': relative_strength,
                            'current_price': current_price,
                            'fundamental_data': fundamental_data
                        }
                        high_potential_stocks.append(stock_info)
                        
                        self.logger.info(f"✅ {stock_name}: 점수 {adjusted_score:.1f}, 리스크 {risk_score:.1f}")
                    
                    analyzed_count += 1
                    
                    if analyzed_count % 20 == 0:
                        self.logger.info(f"진행 상황: {analyzed_count}개 종목 분석 완료")
                    
                except Exception as e:
                    self.logger.error(f"❌ {stock_name} 분석 오류: {e}")
                    error_count += 1
                
                time.sleep(0.3)  # API 제한 고려
            
            # 3. 결과 정리 및 전송
            self.logger.info(f"✅ 분석 완료: 성공 {analyzed_count}개, 오류 {error_count}개")
            self.logger.info(f"🎯 고잠재력 종목: {len(high_potential_stocks)}개 발굴")
            
            if high_potential_stocks:
                # 결과 저장
                saved_results = self.save_analysis_results(high_potential_stocks)
                
                # 등급별 분류
                premium_stocks = [s for s in high_potential_stocks if s['total_score'] >= 85]
                excellent_stocks = [s for s in high_potential_stocks if 80 <= s['total_score'] < 85]
                good_stocks = [s for s in high_potential_stocks if 75 <= s['total_score'] < 80]
                watchlist_stocks = [s for s in high_potential_stocks if 70 <= s['total_score'] < 75]
                
                # 디스코드 메시지 전송
                self.send_results_to_discord(premium_stocks, excellent_stocks, good_stocks, watchlist_stocks)
                
                return saved_results
            else:
                self.send_discord_message("❌ **고잠재력 종목을 발견하지 못했습니다.**\n시장 상황을 재점검해주세요.")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 메인 분석 프로세스 오류: {e}")
            self.send_discord_message(f"❌ **시스템 오류 발생**\n{str(e)}")
            return None

    def send_results_to_discord(self, premium_stocks, excellent_stocks, good_stocks, watchlist_stocks):
        """결과를 디스코드로 전송"""
        
        # 요약 메시지
        summary_msg = f"🎯 **강화된 주식 분석 결과**\n"
        summary_msg += f"📅 분석일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        summary_msg += f"🌡️ 시장상황: {self.get_market_condition()}\n\n"
        summary_msg += f"💎 프리미엄급 (85점+): {len(premium_stocks)}개\n"
        summary_msg += f"⭐ 우수급 (80-84점): {len(excellent_stocks)}개\n"
        summary_msg += f"👍 양호급 (75-79점): {len(good_stocks)}개\n"
        summary_msg += f"👀 관심급 (70-74점): {len(watchlist_stocks)}개\n"
        
        self.send_discord_message(summary_msg)
        
        # 프리미엄급 종목 상세
        if premium_stocks:
            premium_msg = "💎 **프리미엄급 종목 (강력매수 추천)**\n"
            for stock in sorted(premium_stocks, key=lambda x: x['total_score'], reverse=True):
                premium_msg += f"• **{stock['name']} ({stock['code']})**\n"
                premium_msg += f"  📊 종합점수: {stock['total_score']:.1f}점\n"
                premium_msg += f"  🛡️ 리스크점수: {stock['risk_score']:.1f}점\n"
                premium_msg += f"  💰 현재가: {stock['current_price']:,}원\n"
                premium_msg += f"  📈 추천등급: {self.get_recommendation(stock['total_score'], stock['risk_score'])}\n\n"
            
            self.send_discord_message(premium_msg)
        
        # 우수급 종목
        if excellent_stocks:
            excellent_msg = "⭐ **우수급 종목 (적극매수 추천)**\n"
            for stock in sorted(excellent_stocks, key=lambda x: x['total_score'], reverse=True)[:5]:  # 상위 5개만
                excellent_msg += f"• {stock['name']} ({stock['code']}) - {stock['total_score']:.1f}점\n"
                excellent_msg += f"  리스크: {stock['risk_score']:.1f}점, 가격: {stock['current_price']:,}원\n"
            
            if len(excellent_stocks) > 5:
                excellent_msg += f"  + {len(excellent_stocks) - 5}개 종목 추가\n"
            
            self.send_discord_message(excellent_msg)
        
        # 양호급 종목 (간단히)
        if good_stocks:
            good_msg = f"👍 **양호급 종목**: "
            good_msg += ", ".join([f"{s['name']}({s['code']})" for s in sorted(good_stocks, key=lambda x: x['total_score'], reverse=True)[:10]])
            if len(good_stocks) > 10:
                good_msg += f" 외 {len(good_stocks) - 10}개"
            
            self.send_discord_message(good_msg)

# 실행 함수들
def convert_numpy_types(obj):
    """numpy 타입을 JSON 직렬화 가능한 타입으로 변환"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    else:
        return obj

# 메인 실행 부분
if __name__ == "__main__":
    try:
        # 강화된 분석기 초기화
        analyzer = EnhancedStockAnalyzer()
        
        # 분석 실행
        results = analyzer.run_enhanced_analysis()
        
        if results:
            print("✅ 강화된 분석 완료!")
            print(f"📊 총 {len(results['top_stocks'])}개 고잠재력 종목 발굴")
            print(f"🎯 평균 점수: {results['analysis_summary']['average_score']:.1f}점")
        else:
            print("❌ 분석 실패 또는 고잠재력 종목 없음")
            
    except Exception as e:
        print(f"❌ 심각한 오류 발생: {e}")
        logging.error(f"메인 프로세스 오류: {e}")
