import requests
import json
import time
import pandas as pd
from bs4 import BeautifulSoup
import pandas_ta as ta
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from datetime import datetime
from dotenv import load_dotenv
import numpy as np


load_dotenv()
TOKEN_FILE = "token.json"


def get_institution_netbuy_trend_kis(stock_code, app_key, app_secret, access_token, days=3):
    """
    최근 N일 기관 순매수량 리스트와 추세 판단 결과 반환
    """
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010900"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json().get("output", [])

        netbuy_list = []
        for row in data[:days]:
            # 기관 순매수량 (기관계)
            qty = row.get("orgn_ntby_qty", "").replace(",", "").strip()
            if qty != "":
                netbuy_list.append(int(qty))

        # 추세 분석
        trend = "neutral"
        if len(netbuy_list) >= 3:
            pos_days = sum(1 for x in netbuy_list if x > 0)
            if pos_days == days:
                trend = "steady_buying"  # ✅ 전일 모두 순매수
            elif pos_days >= days * 0.6:
                trend = "accumulating"  # 순매수 우세
            elif pos_days <= days * 0.2:
                trend = "distributing"  # 순매도 우세
            else:
                trend = "mixed"

        return netbuy_list, trend

    except Exception as e:
        print(f"❌ KIS API 기관 추세 분석 오류: {e}")
        return [], "unknown"

def is_macd_golden_cross(df):
    """
    MACD 골든크로스 신호 감지 (30일 기간)
    """
    if len(df) < 30:
        return False
   
    try:
        # DataFrame 컬럼 존재 여부 확인
        if 'stck_clpr' not in df.columns:
            print(f"❌ DataFrame에 'stck_clpr' 컬럼이 없습니다. 사용 가능한 컬럼: {df.columns.tolist()}")
            return False
            
        close_prices = df['stck_clpr'].copy()
    
        if close_prices.isnull().any():
            return False
    
        # EMA 계산
        ema_12 = close_prices.ewm(span=12, adjust=False).mean()
        ema_26 = close_prices.ewm(span=26, adjust=False).mean()
    
        # MACD Line 계산
        macd_line = ema_12 - ema_26
    
        # Signal Line 계산
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
    
        if len(macd_line) < 5:
            return False
    
        # 현재 MACD가 Signal보다 위에 있음
        current_above = macd_line.iloc[-1] > signal_line.iloc[-1]
    
        # 최근 30일 내 골든크로스 발생
        recent_cross = False
        for i in range(1, min(31, len(macd_line))):
            if (macd_line.iloc[-i-1] <= signal_line.iloc[-i-1] and
                macd_line.iloc[-i] > signal_line.iloc[-i]):
                recent_cross = True
                break

        return current_above and recent_cross

    except Exception as e:
        print(f"❌ MACD 골든크로스 계산 오류: {e}")
        return False


def get_current_price(access_token, app_key, app_secret, stock_code):
    """
    실시간 현재가 조회
    """
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": app_key,
        "appSecret": app_secret,
        "tr_id": "FHKST01010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json().get("output", {})
        
        current_price = float(data.get("stck_prpr", 0))
        current_volume = int(data.get("acml_vol", 0))
        
        return current_price, current_volume
    except Exception as e:
        print(f"현재가 조회 오류: {e}")
        return None, None


def get_daily_price_data_with_realtime(access_token, app_key, app_secret, stock_code):
    """
    일봉 데이터 + 실시간 현재가 결합 (개선된 버전)
    """
    try:
        # 기존 일봉 데이터 조회
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appKey": app_key,
            "appSecret": app_secret,
            "tr_id": "FHKST01010400"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0"
        }
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json().get("output", [])
        
        if not data:
            print(f"❌ {stock_code}: API에서 데이터를 받지 못했습니다.")
            return None
            
        df = pd.DataFrame(data)
        
        # 필수 컬럼 존재 여부 확인
        required_columns = ["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol", "stck_bsop_date"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            print(f"❌ {stock_code}: 필수 컬럼 누락: {missing_columns}")
            print(f"사용 가능한 컬럼: {df.columns.tolist()}")
            return None
        
        # 데이터 타입 변환 (에러 처리 강화)
        for col in ["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        
        # 유효하지 않은 데이터 제거
        df = df.dropna(subset=["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"])
        
        if df.empty:
            print(f"❌ {stock_code}: 유효한 데이터가 없습니다.")
            return None
            
        df = df.sort_values(by="stck_bsop_date").reset_index(drop=True)
        
        # 실시간 현재가 조회
        current_price, current_volume = get_current_price(access_token, app_key, app_secret, stock_code)
        
        if current_price and current_volume:
            today = datetime.now().strftime("%Y%m%d")
            
            # 최신 데이터가 오늘 데이터인지 확인
            if len(df) > 0 and df.iloc[-1]["stck_bsop_date"] == today:
                # 오늘 데이터를 실시간 가격으로 업데이트
                df.loc[df.index[-1], "stck_clpr"] = current_price
                df.loc[df.index[-1], "acml_vol"] = current_volume
            else:
                # 오늘 데이터 새로 추가
                new_row = {
                    "stck_bsop_date": today,
                    "stck_clpr": current_price,
                    "stck_hgpr": current_price,
                    "stck_lwpr": current_price,
                    "acml_vol": current_volume
                }
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        
        return df
        
    except Exception as e:
        print(f"❌ {stock_code}: 일봉 데이터 조회 중 오류 발생: {e}")
        return None


def is_institution_consecutive_buying(stock_code, app_key, app_secret, access_token, days=3):
    """
    기관이 N일 연속 순매수했는지 확인
    """
    try:
        netbuy_list, trend = get_institution_netbuy_trend_kis(
            stock_code, app_key, app_secret, access_token, days
        )
        
        # 3일 연속 모두 순매수인 경우
        return trend == "steady_buying" and len(netbuy_list) == days
    except Exception as e:
        print(f"❌ {stock_code}: 기관 연속 매수 확인 중 오류: {e}")
        return False


def get_foreign_netbuy_trend_kis(stock_code, app_key, app_secret, access_token, days=5):
    """
    최근 N일 외국인 순매수량 리스트와 추세 판단 결과 반환
    """
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010900"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json().get("output", [])

        netbuy_list = []
        for row in data[:days]:
            qty = row.get("frgn_ntby_qty", "").replace(",", "").strip()
            if qty != "":
                netbuy_list.append(int(qty))

        # 추세 분석
        trend = "neutral"
        if len(netbuy_list) >= 3:
            pos_days = sum(1 for x in netbuy_list if x > 0)
            if pos_days == days:
                trend = "steady_buying"  # ✅ 전일 모두 순매수
            elif pos_days >= days * 0.6:
                trend = "accumulating"  # 순매수 우세
            elif pos_days <= days * 0.2:
                trend = "distributing"  # 순매도 우세
            else:
                trend = "mixed"

        return netbuy_list, trend

    except Exception as e:
        print(f"❌ KIS API 외국인 추세 분석 오류: {e}")
        return [], "unknown"


def get_foreign_net_buy_kis(stock_code, app_key, app_secret, access_token, days=3):
    """
    KIS API를 사용해 최근 N일간 외국인 순매수량 합계 반환
    """
    try:
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST01010900"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",        # 'J' = 코스피, 'Q' = 코스닥
            "fid_input_iscd": stock_code
        }

        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json().get("output", [])

        total_net_buy = 0
        count = 0

        for row in data:
            qty_str = row.get("frgn_ntby_qty", "").replace(",", "").strip()
            if qty_str == "":
                continue

            total_net_buy += int(qty_str)
            count += 1
            if count >= days:
                break

        return total_net_buy

    except Exception as e:
        print(f"❌ KIS API 외국인 순매수 조회 오류: {e}")
        return 0


def get_fundamental_data_from_naver(stock_code):
    """
    네이버에서 기본적 분석 데이터 추출 (에러 처리 강화)
    """
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
        print(f"❌ {stock_code}: 기본적 분석 데이터 조회 오류: {e}")
        return {"PER": None, "PBR": None, "ROE": None, "부채비율": None}


def passes_fundamental_filters(data):
    """
    기본적 분석 필터 통과 여부 (None 값 처리 강화)
    """
    try:
        per = data.get("PER")
        roe = data.get("ROE")
        debt_ratio = data.get("부채비율")
        
        # None 값이 있으면 해당 조건은 무시
        conditions = []
        if per is not None:
            conditions.append(per < 80)
        if roe is not None:
            conditions.append(roe > 1)
        if debt_ratio is not None:
            conditions.append(debt_ratio < 500)
        
        # 최소 하나 이상의 조건이 있고 모두 통과해야 함
        return len(conditions) > 0 and all(conditions)
    except Exception:
        return False


def setup_logger(log_dir="logs", log_filename="buying_stocks.log", when="midnight", backup_count=7):
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

def load_keys():
    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")
    if not app_key or not app_secret:
        raise ValueError("환경변수 KIS_APP_KEY 또는 KIS_APP_SECRET이 설정되지 않았습니다.")
    return app_key, app_secret

def request_new_token():
    app_key, app_secret = load_keys()
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    data = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    res = requests.post(url, headers=headers, data=json.dumps(data)).json()
    res["requested_at"] = int(time.time())
    with open(TOKEN_FILE, "w") as f:
        json.dump(res, f)
    return res["access_token"]

def load_token():
    if not os.path.exists(TOKEN_FILE):
        return request_new_token()
    
    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)

    now = int(time.time())
    issued_at = token_data.get("requested_at", 0)
    expires_in = int(token_data.get("expires_in", 0))
    
    if now - issued_at >= expires_in - 3600:
        return request_new_token()
    else:
        return token_data["access_token"]

def get_top_200_stocks():
    """
    시가총액 상위 200개 종목 조회 (에러 처리 강화)
    """
    stocks = {}
    exclude_keywords = ["KODEX","TIGER", "PLUS", "ACE", "ETF", "ETN", "리츠", "우", "스팩"]

    try:
        for page in range(1, 11):
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
                        
                        stocks[name] = code
                except Exception as e:
                    continue  # 개별 행 파싱 오류는 건너뛰기
            
            time.sleep(0.1)  # 요청 간격 조절
    except Exception as e:
        print(f"❌ 종목 리스트 조회 중 오류: {e}")
    
    return stocks


def get_daily_price_data(access_token, app_key, app_secret, stock_code):
    """
    일봉 데이터 조회 (에러 처리 강화)
    """
    try:
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appKey": app_key,
            "appSecret": app_secret,
            "tr_id": "FHKST01010400"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0"
        }
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json().get("output", [])
        
        if not data:
            return None
            
        df = pd.DataFrame(data)
        
        # 필수 컬럼 확인
        required_cols = ["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"]
        if not all(col in df.columns for col in required_cols):
            return None
            
        # 데이터 타입 변환
        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
        df = df.dropna(subset=required_cols)
        
        if df.empty:
            return None
            
        return df.sort_values(by="stck_bsop_date").reset_index(drop=True)
    except Exception as e:
        print(f"❌ {stock_code}: 일봉 데이터 조회 오류: {e}")
        return None

# 기존 지표들 (에러 처리 강화)
def is_golden_cross(df):
    """골든크로스 신호 감지"""
    try:
        if df is None or df.empty or len(df) < 21:
            return False
        if 'stck_clpr' not in df.columns:
            return False
            
        df = df.copy()
        df["ma5"] = df["stck_clpr"].rolling(window=5).mean()
        df["ma20"] = df["stck_clpr"].rolling(window=20).mean()
        
        if len(df) < 2:
            return False
            
        today = df.iloc[-1]
        yesterday = df.iloc[-2]
        
        return (not pd.isna(today["ma5"]) and not pd.isna(today["ma20"]) and
                not pd.isna(yesterday["ma5"]) and not pd.isna(yesterday["ma20"]) and
                yesterday["ma5"] < yesterday["ma20"] and today["ma5"] > today["ma20"])
    except Exception as e:
        print(f"❌ 골든크로스 계산 오류: {e}")
        return False

def is_bollinger_rebound(df):
    """볼린저밴드 반등 신호"""
    try:
        if df is None or df.empty or len(df) < 21:
            return False
        if 'stck_clpr' not in df.columns:
            return False
            
        df = df.copy()
        df["ma20"] = df["stck_clpr"].rolling(window=20).mean()
        df["stddev"] = df["stck_clpr"].rolling(window=20).std()
        df["lower_band"] = df["ma20"] - 2 * df["stddev"]

        if len(df) < 2:
            return False
            
        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        return (not pd.isna(yesterday["lower_band"]) and not pd.isna(today["lower_band"]) and
                yesterday["stck_clpr"] < yesterday["lower_band"] and
                today["stck_clpr"] > today["lower_band"])
    except Exception as e:
        print(f"❌ 볼린저밴드 계산 오류: {e}")
        return False

def is_macd_signal_cross(df):
    """MACD 신호선 교차"""
    try:
        if df is None or df.empty or len(df) < 35:
            return False
        if 'stck_clpr' not in df.columns:
            return False
        
        close = df["stck_clpr"]
        macd_result = ta.macd(close, fast=12, slow=26, signal=9)
        
        if macd_result is None or macd_result.isna().any().any():
            return False
        
        macd = macd_result["MACD_12_26_9"]
        signal = macd_result["MACDs_12_26_9"]

        if len(macd) < 2:
            return False
            
        return (macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1])
    except Exception as e:
        print(f"❌ MACD 계산 오류: {e}")
        return False

# 🆕 추가 기술적 지표들 (에러 처리 강화)
def is_rsi_oversold_recovery(df, period=14, oversold_threshold=30, recovery_threshold=35):
    """RSI 과매도 구간에서 회복 신호"""
    try:
        if df is None or df.empty or len(df) < period + 2:
            return False
        if 'stck_clpr' not in df.columns:
            return False
        
        rsi = ta.rsi(df["stck_clpr"], length=period)
        
        if rsi is None or rsi.isna().any() or len(rsi) < 2:
            return False
        
        # 전날 RSI가 과매도 구간이고, 오늘 회복 신호
        return (rsi.iloc[-2] < oversold_threshold and 
                rsi.iloc[-1] > recovery_threshold)
    except Exception as e:
        print(f"❌ RSI 계산 오류: {e}")
        return False

def is_stochastic_oversold_recovery(df, k_period=14, d_period=3, oversold_threshold=20):
    """스토캐스틱 과매도 구간에서 회복 신호"""
    try:
        if df is None or df.empty or len(df) < k_period + d_period + 2:
            return False
        required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
        if not all(col in df.columns for col in required_cols):
            return False
        
        stoch = ta.stoch(df["stck_hgpr"], df["stck_lwpr"], df["stck_clpr"], 
                         k=k_period, d=d_period)
        
        if stoch is None or stoch.isna().any().any():
            return False
        
        stoch_k = stoch[f"STOCHk_{k_period}_{d_period}_3"]
        stoch_d = stoch[f"STOCHd_{k_period}_{d_period}_3"]
        
        if len(stoch_k) < 2:
            return False
        
        # %K가 %D를 상향 돌파하면서 과매도 구간에서 벗어날 때
        return (stoch_k.iloc[-2] < stoch_d.iloc[-2] and 
                stoch_k.iloc[-1] > stoch_d.iloc[-1] and
                stoch_k.iloc[-1] < oversold_threshold + 10)
    except Exception as e:
        print(f"❌ 스토캐스틱 계산 오류: {e}")
        return False

def is_volume_breakout(df, volume_period=20, volume_multiplier=2.0):
    """거래량 급증 신호"""
    try:
        if df is None or df.empty or len(df) < volume_period + 1:
            return False
        if 'acml_vol' not in df.columns:
            return False
        
        avg_volume = df["acml_vol"].rolling(window=volume_period).mean()
        today_volume = df["acml_vol"].iloc[-1]
        avg_volume_today = avg_volume.iloc[-1]
        
        if pd.isna(avg_volume_today) or avg_volume_today == 0:
            return False
        
        # 오늘 거래량이 평균의 2배 이상
        return today_volume > avg_volume_today * volume_multiplier
    except Exception as e:
        print(f"❌ 거래량 계산 오류: {e}")
        return False

def is_williams_r_oversold_recovery(df, period=14, oversold_threshold=-80, recovery_threshold=-70):
    """Williams %R 과매도 구간에서 회복 신호"""
    try:
        if df is None or df.empty or len(df) < period + 2:
            return False
        required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
        if not all(col in df.columns for col in required_cols):
            return False
        
        willr = ta.willr(df["stck_hgpr"], df["stck_lwpr"], df["stck_clpr"], length=period)
        
        if willr is None or willr.isna().any() or len(willr) < 2:
            return False
        
        # 전날 과매도 구간이고 오늘 회복 신호
        return (willr.iloc[-2] < oversold_threshold and 
                willr.iloc[-1] > recovery_threshold)
    except Exception as e:
        print(f"❌ Williams %R 계산 오류: {e}")
        return False

def is_double_bottom_pattern(df, lookback=20, tolerance=0.02):
    """이중바닥 패턴 감지"""
    try:
        if df is None or df.empty or len(df) < lookback * 2:
            return False
        if 'stck_lwpr' not in df.columns or 'stck_clpr' not in df.columns:
            return False
        
        # 최근 구간에서 저점 찾기
        recent_data = df.tail(lookback * 2)
        
        # 저점들 찾기 (local minima)
        lows = []
        for i in range(1, len(recent_data) - 1):
            if (recent_data.iloc[i]["stck_lwpr"] < recent_data.iloc[i-1]["stck_lwpr"] and 
                recent_data.iloc[i]["stck_lwpr"] < recent_data.iloc[i+1]["stck_lwpr"]):
                lows.append((i, recent_data.iloc[i]["stck_lwpr"]))
        
        if len(lows) < 2:
            return False
        
        # 마지막 두 저점 비교
        last_two_lows = lows[-2:]
        low1_price = last_two_lows[0][1]
        low2_price = last_two_lows[1][1]
        
        # 두 저점이 비슷한 수준이고, 현재 가격이 상승 중
        price_diff = abs(low1_price - low2_price) / low1_price
        current_price = df.iloc[-1]["stck_clpr"]
        
        return (price_diff < tolerance and 
                current_price > max(low1_price, low2_price) * 1.02)
    except Exception as e:
        print(f"❌ 이중바닥 패턴 계산 오류: {e}")
        return False

def is_ichimoku_bullish_signal(df):
    """일목균형표 매수 신호"""
    try:
        if df is None or df.empty or len(df) < 52:
            return False
        required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
        if not all(col in df.columns for col in required_cols):
            return False
        
        # 일목균형표 계산
        high = df["stck_hgpr"]
        low = df["stck_lwpr"]
        close = df["stck_clpr"]
        
        # 전환선 (9일)
        conversion_line = (high.rolling(9).max() + low.rolling(9).min()) / 2
        
        # 기준선 (26일)
        base_line = (high.rolling(26).max() + low.rolling(26).min()) / 2
        
        # 선행스팬A
        span_a = ((conversion_line + base_line) / 2).shift(26)
        
        # 선행스팬B
        span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        
        # 후행스팬
        lagging_span = close.shift(-26)
        
        current_price = close.iloc[-1]
        current_conversion = conversion_line.iloc[-1]
        current_base = base_line.iloc[-1]
        
        if pd.isna(current_conversion) or pd.isna(current_base):
            return False
        
        # 구름 위에 있고, 전환선이 기준선을 상향 돌파
        cloud_top = max(span_a.iloc[-1], span_b.iloc[-1]) if not pd.isna(span_a.iloc[-1]) and not pd.isna(span_b.iloc[-1]) else None
        
        if cloud_top is None or pd.isna(cloud_top):
            return False
        
        return (current_price > cloud_top and 
                len(conversion_line) >= 2 and len(base_line) >= 2 and
                conversion_line.iloc[-2] < base_line.iloc[-2] and 
                current_conversion > current_base)
    except Exception as e:
        print(f"❌ 일목균형표 계산 오류: {e}")
        return False

def is_cup_handle_pattern(df, cup_depth=0.1, handle_depth=0.05, min_periods=30):
    """컵앤핸들 패턴 감지 (간단한 버전)"""
    try:
        if df is None or df.empty or len(df) < min_periods:
            return False
        required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
        if not all(col in df.columns for col in required_cols):
            return False
        
        # 최근 30일 데이터
        recent_data = df.tail(min_periods)
        
        # 컵 패턴: 고점 -> 저점 -> 고점 형태
        max_price = recent_data["stck_hgpr"].max()
        min_price = recent_data["stck_lwpr"].min()
        current_price = recent_data["stck_clpr"].iloc[-1]
        
        if max_price == 0:
            return False
        
        # 컵의 깊이 체크
        cup_depth_actual = (max_price - min_price) / max_price
        
        # 현재 고점 근처까지 회복했는지 체크
        recovery_ratio = current_price / max_price
        
        return (cup_depth_actual > cup_depth and 
                recovery_ratio > 0.90 and 
                len(recent_data) >= 6 and
                current_price > recent_data["stck_clpr"].iloc[-5])  # 최근 5일 상승
    except Exception as e:
        print(f"❌ 컵앤핸들 패턴 계산 오류: {e}")
        return False

def calculate_buy_signal_score(df, name, code, app_key, app_secret, access_token, foreign_trend=None):
    """종합 매수 신호 점수 계산 (에러 처리 강화)"""
    try:
        if df is None or df.empty:
            return 0, []
            
        signals = {
            "골든크로스": is_golden_cross(df),
            "볼린저밴드복귀": is_bollinger_rebound(df),
            "MACD상향돌파": is_macd_signal_cross(df),
            "RSI과매도회복": is_rsi_oversold_recovery(df),
            "스토캐스틱회복": is_stochastic_oversold_recovery(df),
            "거래량급증": is_volume_breakout(df),
            "Williams%R회복": is_williams_r_oversold_recovery(df),
            "이중바닥": is_double_bottom_pattern(df),
            "일목균형표": is_ichimoku_bullish_signal(df),
            "컵앤핸들": is_cup_handle_pattern(df),
            "MACD골든크로스": is_macd_golden_cross(df),
            "외국인매수추세": foreign_trend == "steady_buying",
            "기관연속매수": is_institution_consecutive_buying(code, app_key, app_secret, access_token) if app_key else False 
        }

        score = sum(signals.values())
        active_signals = [key for key, value in signals.items() if value]

        return score, active_signals
    except Exception as e:
        print(f"❌ {name}: 매수 신호 점수 계산 오류: {e}")
        return 0, []

def send_discord_message(message, webhook_url):
    """디스코드 메시지 전송 (에러 처리 강화)"""
    if not webhook_url:
        print("❌ Discord webhook URL이 설정되지 않았습니다.")
        return
        
    logger.info(message)
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
        price_text = f"{stock['price']:,}원"
        volume_text = f"{stock['volume']:,}"
        
        line = f"- {stock['name']} ({stock['code']}) - {stock['score']}점\n"
        line += f"  📊 [{signals_text}]"
        #line += f"  💰 {price_text} | 📈 {volume_text}주"
        if ('외국인매수추세' in stock['signals']):
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

if __name__ == "__main__":
    try:
        app_key = os.getenv("KIS_APP_KEY")
        app_secret = os.getenv("KIS_APP_SECRET")
        access_token = load_token()
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        logger = setup_logger()
        
        logger.info("📊 시가총액 상위 200개 종목 분석 시작...")
        stock_list = get_top_200_stocks()
        
        if not stock_list:
            logger.error("❌ 종목 리스트를 가져올 수 없습니다.")
            exit(1)

        # 각 신호별 종목 리스트
        signal_lists = {
            "골든크로스": [],
            "볼린저밴드복귀": [],
            "MACD상향돌파": [],
            "RSI과매도회복": [],
            "스토캐스틱회복": [],
            "거래량급증": [],
            "Williams%R회복": [],
            "이중바닥": [],
            "일목균형표": [],
            "컵앤핸들": [],
            "MACD골든크로스": [],
            "외국인매수추세": [] ,
            "기관연속매수": []   
        }
        
        # 다중신호 종목 분류
        multi_signal_stocks = {
            "ultra_strong": [],    # 5점 이상 - 매우 강한 신호
            "strong": [],          # 4점 - 강한 신호
            "moderate": [],        # 3점 - 보통 신호
            "weak": [],           # 2점 - 약한 신호
            "single": []          # 1점 - 단일 신호
        }
        
        # 신호 조합 분석
        signal_combinations = {}
        
        # 성공적으로 분석된 종목 수 추적
        analyzed_count = 0
        error_count = 0

        for name, code in stock_list.items():
            try:
                # 외국인 순매수 확인
                foreign_net_buy = get_foreign_net_buy_kis(code, app_key, app_secret, access_token, days=3)
                netbuy_list, trend = get_foreign_netbuy_trend_kis(code, app_key, app_secret, access_token)
                
                if trend == "distributing":
                    logger.info(f"❌ {name}: 외국인 매수 추세 아님:{netbuy_list}:{trend}")
                    continue

                # 실시간 데이터 포함한 분석
                df = get_daily_price_data_with_realtime(access_token, app_key, app_secret, code)
                if df is None or df.empty:
                    logger.warning(f"⚠️ {name}: 가격 데이터를 가져올 수 없습니다.")
                    error_count += 1
                    continue

                # 종합 점수 계산
                score, active_signals = calculate_buy_signal_score(
                    df, name, code, app_key, app_secret, access_token, foreign_trend=trend
                )
                
                # 현재 가격 정보
                current_price = df.iloc[-1]["stck_clpr"]
                volume = df.iloc[-1]["acml_vol"]
                
                # 개별 신호 체크
                if is_golden_cross(df):
                    signal_lists["골든크로스"].append(f"- {name} ({code})")
                if is_bollinger_rebound(df):
                    signal_lists["볼린저밴드복귀"].append(f"- {name} ({code})")
                if is_macd_signal_cross(df):
                    signal_lists["MACD상향돌파"].append(f"- {name} ({code})")
                if is_rsi_oversold_recovery(df):
                    signal_lists["RSI과매도회복"].append(f"- {name} ({code})")
                if is_stochastic_oversold_recovery(df):
                    signal_lists["스토캐스틱회복"].append(f"- {name} ({code})")
                if is_volume_breakout(df):
                    signal_lists["거래량급증"].append(f"- {name} ({code})")
                if is_williams_r_oversold_recovery(df):
                    signal_lists["Williams%R회복"].append(f"- {name} ({code})")
                if is_double_bottom_pattern(df):
                    signal_lists["이중바닥"].append(f"- {name} ({code})")
                if is_ichimoku_bullish_signal(df):
                    signal_lists["일목균형표"].append(f"- {name} ({code})")
                if is_cup_handle_pattern(df):
                    signal_lists["컵앤핸들"].append(f"- {name} ({code})")
                if is_macd_golden_cross(df):
                    signal_lists["MACD골든크로스"].append(f"- {name} ({code})")
                if trend == "steady_buying":
                    signal_lists["외국인매수추세"].append(f"- {name} ({code})")
                if is_institution_consecutive_buying(code, app_key, app_secret, access_token):
                    signal_lists["기관연속매수"].append(f"- {name} ({code})") 
                
                # 다중신호 등급 분류
                stock_info = {
                    "name": name, "code": code, "score": score, 
                    "signals": active_signals, "price": current_price, "volume": volume,
                    "foreign": netbuy_list 
                }
                
                if score >= 5:
                    multi_signal_stocks["ultra_strong"].append(stock_info)
                elif score == 4:
                    multi_signal_stocks["strong"].append(stock_info)
                elif score == 3:
                    multi_signal_stocks["moderate"].append(stock_info)
                elif score == 2:
                    multi_signal_stocks["weak"].append(stock_info)
                elif score == 1:
                    multi_signal_stocks["single"].append(stock_info)
                
                # 신호 조합 패턴 분석
                if score >= 2:
                    combo_key = " + ".join(sorted(active_signals))
                    if combo_key not in signal_combinations:
                        signal_combinations[combo_key] = []
                    signal_combinations[combo_key].append(f"{name}({code})")

                analyzed_count += 1
                if analyzed_count % 50 == 0:
                    logger.info(f"진행 상황: {analyzed_count}개 종목 분석 완료")

            except Exception as e:
                logger.error(f"⚠️ {name} 분석 오류: {e}")
                error_count += 1
            
            time.sleep(0.5)  # API 호출 제한 고려

        logger.info(f"분석 완료: 성공 {analyzed_count}개, 오류 {error_count}개")

        # 결과 전송
        # 1. 다중신호 종목 우선순위별 전송
        priority_order = ["ultra_strong", "strong", "moderate", "weak"]
        
        for grade in priority_order:
            if multi_signal_stocks[grade]:
                msg = format_multi_signal_message(grade, multi_signal_stocks[grade])
                if msg:
                    send_discord_message(msg, webhook_url)
                    logger.info(f"{grade} 종목: {len(multi_signal_stocks[grade])}개")
        
        # 2. 신호 조합 패턴 분석 결과 전송
        if signal_combinations:
            combo_msg = format_signal_combination_message(signal_combinations)
            if combo_msg:
                send_discord_message(combo_msg, webhook_url)
                logger.info(f"신호 조합 패턴: {len(signal_combinations)}개")
        
        # 3. 요약 통계 전송
        total_multi_signals = sum(len(stocks) for grade, stocks in multi_signal_stocks.items() if grade != "single")
        summary_msg = f"📈 **[다중신호 종목 요약]**\n"
        summary_msg += f"🚀 초강력 신호: {len(multi_signal_stocks['ultra_strong'])}개\n"
        summary_msg += f"🔥 강력 신호: {len(multi_signal_stocks['strong'])}개\n"
        summary_msg += f"⭐ 보통 신호: {len(multi_signal_stocks['moderate'])}개\n"
        summary_msg += f"⚡ 약한 신호: {len(multi_signal_stocks['weak'])}개\n"
        summary_msg += f"💡 단일 신호: {len(multi_signal_stocks['single'])}개\n"
        summary_msg += f"📊 **총 다중신호 종목: {total_multi_signals}개**\n"
        summary_msg += f"✅ 분석 성공: {analyzed_count}개 | ❌ 오류: {error_count}개"
        
        send_discord_message(summary_msg, webhook_url)

        # 4. 개별 신호 상세 (필요시)
        detail_mode = os.getenv("DETAIL_MODE", "false").lower() == "true"
        if detail_mode:
            for signal_type, signal_list in signal_lists.items():
                if signal_list:
                    icons = {
                        "골든크로스": "🟡", "볼린저밴드복귀": "🔵", "MACD상향돌파": "🟢",
                        "RSI과매도회복": "🟠", "스토캐스틱회복": "🟣", "거래량급증": "🔴",
                        "Williams%R회복": "🟤", "이중바닥": "⚫", "일목균형표": "🔘", "컵앤핸들": "🎯",
                        "MACD골든크로스": "⚡", "외국인매수추세": "🌍", "기관연속매수": "🏛️" 
                    }
                    icon = icons.get(signal_type, "📊")
                    msg = f"{icon} **[{signal_type} 발생 종목]**\n" + "\n".join(signal_list)
                    send_discord_message(msg, webhook_url)
                    logger.info(f"{signal_type}: {len(signal_list)}개")

        logger.info("✅ 모든 분석 및 전송 완료!")

    except Exception as e:
        logger.error(f"❌ 메인 프로세스 오류: {e}")
        print(f"❌ 심각한 오류 발생: {e}")
        if webhook_url:
            error_msg = f"❌ **[시스템 오류]**\n주식 분석 중 오류가 발생했습니다: {str(e)}"
            send_discord_message(error_msg, webhook_url)
