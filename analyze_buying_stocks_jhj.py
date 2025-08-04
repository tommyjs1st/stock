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


def is_envelope_bottom_rebound(df, period=20, envelope_ratio=0.10):
    """
    엔벨로프 하단 터치 후 반등 신호
    """
    if len(df) < period + 2:
        return False
    
    df["ma"] = df["stck_clpr"].rolling(window=period).mean()
    df["envelope_upper"] = df["ma"] * (1 + envelope_ratio)
    df["envelope_lower"] = df["ma"] * (1 - envelope_ratio)
    
    recent_3days = df.tail(3)
    
    if len(recent_3days) < 3:
        return False
    
    day_before_yesterday = recent_3days.iloc[0]
    yesterday = recent_3days.iloc[1]
    today = recent_3days.iloc[2]
    
    touched_lower_band = yesterday["stck_clpr"] <= yesterday["envelope_lower"] * 1.01
    price_recovery = (today["stck_clpr"] > yesterday["stck_clpr"] and 
                     today["stck_clpr"] > today["envelope_lower"])
    low_touched_band = yesterday["stck_lwpr"] <= yesterday["envelope_lower"] * 1.005
    meaningful_rebound = (today["stck_clpr"] / yesterday["stck_clpr"] - 1) >= 0.005
    
    return touched_lower_band and price_recovery and low_touched_band and meaningful_rebound


def is_envelope_squeeze_breakout(df, period=20, envelope_ratio=0.06, squeeze_threshold=0.015):
    """
    엔벨로프 스퀴즈(밴드 축소) 후 상향 돌파 신호
    """
    if len(df) < period + 10:
        return False
    
    df["ma"] = df["stck_clpr"].rolling(window=period).mean()
    df["envelope_upper"] = df["ma"] * (1 + envelope_ratio)
    df["envelope_lower"] = df["ma"] * (1 - envelope_ratio)
    df["envelope_width"] = (df["envelope_upper"] - df["envelope_lower"]) / df["ma"]
    
    recent_width = df["envelope_width"].tail(10).mean()
    past_width = df["envelope_width"].tail(30).head(20).mean()
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    is_squeezed = recent_width < past_width * 0.8
    breakout_upper = (yesterday["stck_clpr"] <= yesterday["envelope_upper"] and 
                     today["stck_clpr"] > today["envelope_upper"])
    volume_surge = today["acml_vol"] > df["acml_vol"].tail(5).mean() * 1.2
    
    return is_squeezed and breakout_upper and volume_surge


def is_macd_golden_cross(df):
    """
    MACD 골든크로스 신호 감지 (오늘 돌파한 경우만)
    """
    if len(df) < 30:
        return False
    
    try:
        close_prices = df['stck_clpr'].copy()
        
        if close_prices.isnull().any():
            return False
        
        # EMA 계산
        ema_12 = close_prices.ewm(span=12, adjust=False).mean()
        ema_26 = close_prices.ewm(span=26, adjust=False).mean()
        ema_05 = close_prices.ewm(span=5, adjust=False).mean()
        
        # MACD Line 계산
        #macd_line = ema_12 - ema_26
        macd_line = ema_12 - ema_05
        
        # Signal Line 계산
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        if len(macd_line) < 2:
            return False
        
        # 오늘과 어제의 MACD, Signal 값
        today_macd = macd_line.iloc[-1]
        today_signal = signal_line.iloc[-1]
        yesterday_macd = macd_line.iloc[-2]
        yesterday_signal = signal_line.iloc[-2]
        
        # 골든크로스 조건: 어제는 MACD ≤ Signal, 오늘은 MACD > Signal
        golden_cross_today = (yesterday_macd <= yesterday_signal and 
                             today_macd > today_signal)
        
        return golden_cross_today
        
    except Exception as e:
        return False


def is_macd_near_golden_cross(df):
    """
    MACD가 골든크로스에 근접한 상태 감지 (돌파 직전)
    """
    if len(df) < 30:
        return False
    
    try:
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
        
        # 현재 상태
        current_macd = macd_line.iloc[-1]
        current_signal = signal_line.iloc[-1]
        
        # MACD가 Signal 아래에 있어야 함 (아직 크로스 전)
        if current_macd >= current_signal:
            return False
        
        # 차이가 매우 작음 (근접 상태)
        diff = abs(current_macd - current_signal)
        signal_value = abs(current_signal)
        
        # 차이가 Signal 값의 5% 이내이거나 절대값 0.05 이내
        is_close = (diff / max(signal_value, 0.01) <= 0.05) or (diff <= 0.05)
        
        # MACD 상승 추세 확인 (최근 3일)
        if len(macd_line) >= 3:
            macd_trend_up = (macd_line.iloc[-1] > macd_line.iloc[-2] and 
                           macd_line.iloc[-2] > macd_line.iloc[-3])
        else:
            macd_trend_up = False
        
        # 히스토그램 개선 추세 (MACD - Signal이 점점 작아짐)
        histogram_improving = False
        if len(macd_line) >= 3:
            hist_today = current_macd - current_signal
            hist_yesterday = macd_line.iloc[-2] - signal_line.iloc[-2]
            hist_2days_ago = macd_line.iloc[-3] - signal_line.iloc[-3]
            
            # 히스토그램이 0에 가까워지는 추세 (음수에서 덜 음수로)
            histogram_improving = (hist_today > hist_yesterday and 
                                 hist_yesterday > hist_2days_ago)
        
        return is_close and (macd_trend_up or histogram_improving)
        
    except Exception as e:
        return False


def get_current_price(access_token, app_key, app_secret, stock_code, max_retries=3):
    """
    실시간 현재가 조회 (재시도 로직 포함)
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
    
    for attempt in range(max_retries):
        try:
            time.sleep(0.1)  # API 호출 간격 조절
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get("output", {})
            
            current_price = float(data.get("stck_prpr", 0))
            current_volume = int(data.get("acml_vol", 0))
            
            return current_price, current_volume
            
        except requests.exceptions.ConnectionError as e:
            print(f"❌ 현재가 조회 연결 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
        except Exception as e:
            print(f"❌ 현재가 조회 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
    
    print(f"❌ {stock_code} 현재가 조회 실패")
    return None, None


def get_daily_price_data_with_realtime(access_token, app_key, app_secret, stock_code, max_retries=3):
    """
    일봉 데이터 + 실시간 현재가 결합 (재시도 로직 포함)
    """
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
    
    # 일봉 데이터 조회 (재시도)
    df = None
    for attempt in range(max_retries):
        try:
            time.sleep(0.1)
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get("output", [])
            df = pd.DataFrame(data)
            break
        except requests.exceptions.ConnectionError as e:
            print(f"❌ 일봉 데이터 연결 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
        except Exception as e:
            print(f"❌ 일봉 데이터 조회 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
    
    if df is None:
        print(f"❌ {stock_code} 일봉 데이터 조회 실패")
        return None
    
    # 데이터 타입 변환
    df["stck_clpr"] = pd.to_numeric(df["stck_clpr"], errors="coerce")
    df["stck_hgpr"] = pd.to_numeric(df["stck_hgpr"], errors="coerce")
    df["stck_lwpr"] = pd.to_numeric(df["stck_lwpr"], errors="coerce")
    df["acml_vol"] = pd.to_numeric(df["acml_vol"], errors="coerce")
    df = df.dropna(subset=["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"])
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


def get_foreign_netbuy_trend_kis(stock_code, app_key, app_secret, access_token, days=3, max_retries=3):
    """
    최근 N일 외국인 순매수량 리스트와 추세 판단 결과 반환 (개선된 버전)
    """
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,        # 일관성 있게 소문자 사용
        "appsecret": app_secret,  # 일관성 있게 소문자 사용
        "tr_id": "FHKST01010900"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }

    for attempt in range(max_retries):
        try:
            # API 호출 간격을 더 길게 조정
            time.sleep(0.5 + (attempt * 0.2))  # 0.5초, 0.7초, 0.9초
            
            res = requests.get(url, headers=headers, params=params, timeout=15)
            
            # 상태 코드별 세분화된 처리
            if res.status_code == 429:
                print(f"⚠️ Rate limit exceeded (시도 {attempt + 1}/{max_retries})")
                time.sleep(5)  # Rate limit의 경우 더 오래 대기
                continue
            elif res.status_code == 500:
                print(f"⚠️ Server error 500 (시도 {attempt + 1}/{max_retries})")
                time.sleep(2)  # 서버 오류의 경우 2초 대기
                continue
            elif res.status_code == 503:
                print(f"⚠️ Service unavailable (시도 {attempt + 1}/{max_retries})")
                time.sleep(3)  # 서비스 불가의 경우 3초 대기
                continue
            
            res.raise_for_status()
            
            # 응답 데이터 검증
            response_data = res.json()
            if 'output' not in response_data:
                print(f"⚠️ Invalid response format (시도 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                else:
                    return [], "unknown"
            
            data = response_data.get("output", [])
            
            # 데이터가 비어있는 경우 처리
            if not data:
                print(f"⚠️ Empty data received for {stock_code}")
                return [], "no_data"

            netbuy_list = []
            for row in data[:days]:
                qty = row.get("frgn_ntby_qty", "").replace(",", "").strip()
                if qty and qty != "0":  # 빈 문자열과 0 모두 체크
                    try:
                        netbuy_list.append(int(qty))
                    except ValueError:
                        print(f"⚠️ Invalid quantity format: {qty}")
                        continue

            # 추세 분석
            trend = "neutral"
            if len(netbuy_list) >= days:
                pos_days = sum(1 for x in netbuy_list if x > 0)
                total_volume = sum(abs(x) for x in netbuy_list)
                avg_volume = total_volume / len(netbuy_list) if netbuy_list else 0
                
                # 더 정교한 추세 분석
                if pos_days == days and avg_volume > 10000:  # 모든 날 양수이고 평균 거래량이 충분
                    trend = "steady_buying"
                elif pos_days >= days * 0.7 and avg_volume > 5000:
                    trend = "accumulating"
                elif pos_days <= days * 0.3:
                    trend = "distributing"
                else:
                    trend = "mixed"

            return netbuy_list, trend

        except requests.exceptions.ConnectionError as e:
            print(f"❌ 연결 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 지수 백오프: 1초, 2초, 4초
            continue
        except requests.exceptions.Timeout as e:
            print(f"❌ 타임아웃 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1.5)
            continue
        except requests.exceptions.HTTPError as e:
            print(f"❌ HTTP 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1.5)
            continue
        except json.JSONDecodeError as e:
            print(f"❌ JSON 파싱 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
        except Exception as e:
            print(f"❌ 예상치 못한 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue

    print(f"❌ {stock_code} 외국인 데이터 조회 실패 (모든 재시도 소진)")
    return [], "unknown"



def get_institution_netbuy_trend_kis(stock_code, app_key, app_secret, access_token, days=3, max_retries=3):
    """
    최근 N일 기관 순매수량 리스트와 추세 판단 결과 반환 (개선된 버전)
    """
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,        # 일관성 있게 소문자 사용
        "appsecret": app_secret,  # 일관성 있게 소문자 사용
        "tr_id": "FHKST01010900"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }

    for attempt in range(max_retries):
        try:
            # API 호출 간격 조정
            time.sleep(0.5 + (attempt * 0.2))
            
            res = requests.get(url, headers=headers, params=params, timeout=15)
            
            # 상태 코드별 처리
            if res.status_code == 429:
                print(f"⚠️ Rate limit exceeded (시도 {attempt + 1}/{max_retries})")
                time.sleep(5)
                continue
            elif res.status_code == 500:
                print(f"⚠️ Server error 500 (시도 {attempt + 1}/{max_retries})")
                time.sleep(2)
                continue
            elif res.status_code == 503:
                print(f"⚠️ Service unavailable (시도 {attempt + 1}/{max_retries})")
                time.sleep(3)
                continue
            
            res.raise_for_status()
            
            # 응답 데이터 검증
            response_data = res.json()
            if 'output' not in response_data:
                print(f"⚠️ Invalid response format (시도 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                else:
                    return [], "unknown"
            
            data = response_data.get("output", [])
            
            if not data:
                print(f"⚠️ Empty data received for {stock_code}")
                return [], "no_data"

            netbuy_list = []
            for row in data[:days]:
                qty = row.get("orgn_ntby_qty", "").replace(",", "").strip()
                if qty and qty != "0":
                    try:
                        netbuy_list.append(int(qty))
                    except ValueError:
                        print(f"⚠️ Invalid quantity format: {qty}")
                        continue

            # 추세 분석 (외국인과 동일한 로직)
            trend = "neutral"
            if len(netbuy_list) >= days:
                pos_days = sum(1 for x in netbuy_list if x > 0)
                total_volume = sum(abs(x) for x in netbuy_list)
                avg_volume = total_volume / len(netbuy_list) if netbuy_list else 0
                
                if pos_days == days and avg_volume > 10000:
                    trend = "steady_buying"
                elif pos_days >= days * 0.7 and avg_volume > 5000:
                    trend = "accumulating"
                elif pos_days <= days * 0.3:
                    trend = "distributing"
                else:
                    trend = "mixed"

            return netbuy_list, trend

        except requests.exceptions.ConnectionError as e:
            print(f"❌ 연결 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            continue
        except requests.exceptions.Timeout as e:
            print(f"❌ 타임아웃 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1.5)
            continue
        except requests.exceptions.HTTPError as e:
            print(f"❌ HTTP 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1.5)
            continue
        except json.JSONDecodeError as e:
            print(f"❌ JSON 파싱 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
        except Exception as e:
            print(f"❌ 예상치 못한 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue

    print(f"❌ {stock_code} 기관 데이터 조회 실패 (모든 재시도 소진)")
    return [], "unknown"


def is_institution_consecutive_buying(stock_code, app_key, app_secret, access_token, days=3):
    """
    기관이 N일 연속 순매수했는지 확인 (개선된 버전)
    """
    try:
        netbuy_list, trend = get_institution_netbuy_trend_kis(
            stock_code, app_key, app_secret, access_token, days
        )
        
        # 더 엄격한 조건 적용
        if trend == "steady_buying" and len(netbuy_list) == days:
            # 모든 날의 순매수량이 양수이고 의미있는 크기인지 확인
            return all(qty > 1000 for qty in netbuy_list)  # 최소 1000주 이상
        
        return False
        
    except Exception as e:
        print(f"❌ 기관 연속매수 확인 오류 ({stock_code}): {e}")
        return False


def setup_logger(log_dir="logs", log_filename="buying_stocks_jhj.log", when="midnight", backup_count=7):
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
    stocks = {}
    exclude_keywords = ["KODEX","TIGER", "PLUS", "ACE", "ETF", "ETN", "리츠", "우", "스팩", "커버드"]
    cnt = 0

    for page in range(1, 11):
        url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok=0&page={page}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        rows = soup.select("table.type_2 tr")

        for row in rows:
            link = row.select_one("a.tltle")
            if link:
                name = link.text.strip()
                href = link["href"]
                code = href.split("=")[-1]
                
                if any(keyword in name for keyword in exclude_keywords):
                    continue
                
                cnt += 1
                stocks[name] = code
                logger.info(f"{name}: 분석 대상 포함({cnt})")

    return stocks


def is_bollinger_rebound(df):
    if len(df) < 21:
        return False
    df["ma20"] = df["stck_clpr"].rolling(window=20).mean()
    df["stddev"] = df["stck_clpr"].rolling(window=20).std()
    df["lower_band"] = df["ma20"] - 2 * df["stddev"]

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    return (
        yesterday["stck_clpr"] < yesterday["lower_band"]
        and today["stck_clpr"] > today["lower_band"]
    )


def calculate_buy_signal_score(df, name, code, foreign_trend=None):
    """종합 매수 신호 점수 계산 - MACD 골든크로스와 근접 신호 추가"""
    signals = {
        #"볼린저밴드복귀": is_bollinger_rebound(df),
        "엔벨로프반등": is_envelope_bottom_rebound(df),  
        "엔벨로프돌파": is_envelope_squeeze_breakout(df),
        "MACD골든크로스": is_macd_golden_cross(df),
        "MACD돌파직전": is_macd_near_golden_cross(df),  # 새로 추가
        "외국인기관매수": foreign_trend == "steady_buying" and is_institution_consecutive_buying(code, app_key, app_secret, access_token) if app_key else False 
    }

    score = sum(signals.values())
    active_signals = [key for key, value in signals.items() if value]

    return score, active_signals


def send_discord_message(message, webhook_url):
    logger.info(message)
    MAX_LENGTH = 2000
    chunks = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]
    
    for chunk in chunks:
        data = {"content": chunk}
        try:
            response = requests.post(webhook_url, json=data)
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
        stock_lines.append(line)
    
    return header + "\n".join(stock_lines)


def format_signal_combination_message(combinations):
    """신호 조합 패턴 메시지 포맷팅"""
    if not combinations:
        return ""
    
    header = "🔍 **[인기 신호 조합 패턴]**\n"
    combo_lines = []
    
    sorted_combos = sorted(combinations.items(), key=lambda x: len(x[1]), reverse=True)
    
    for combo, stocks in sorted_combos[:10]:
        if len(stocks) >= 2:
            combo_lines.append(f"• **{combo}** ({len(stocks)}개 종목)")
            combo_lines.append(f"  → {', '.join(stocks[:5])}")
            if len(stocks) > 5:
                combo_lines.append(f"  → 외 {len(stocks)-5}개 종목")
    
    return header + "\n".join(combo_lines) if combo_lines else ""


if __name__ == "__main__":
    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")
    access_token = load_token()
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL3")
    logger = setup_logger()
    
    logger.info("📊 시가총액 상위 200개 종목 분석 시작...")
    stock_list = get_top_200_stocks()

    # 각 신호별 종목 리스트
    signal_lists = {
        #"볼린저밴드복귀": [],
        "엔벨로프반등": [],
        "엔벨로프돌파": [],
        "MACD골든크로스": [],
        "MACD돌파직전": [],  # 새로 추가
        "외국인기관매수": [] 
    }
    
    # 다중신호 종목 분류
    multi_signal_stocks = {
        "ultra_strong": [],
        "strong": [],
        "moderate": [],
        "weak": [],
        "single": []
    }
    
    # 신호 조합 분석
    signal_combinations = {}

    for name, code in stock_list.items():
        try:
            # 실시간 데이터 포함한 분석
            netbuy_list, trend = get_foreign_netbuy_trend_kis(code, app_key, app_secret, access_token)

            df = get_daily_price_data_with_realtime(access_token, app_key, app_secret, code)
            if df is None or df.empty:
                continue

            # 종합 점수 계산
            score, active_signals = calculate_buy_signal_score(df, name, code, foreign_trend=trend)
            
            # 현재 가격 정보
            current_price = df.iloc[-1]["stck_clpr"]
            volume = df.iloc[-1]["acml_vol"]
            
            # 개별 신호 체크
            #if is_bollinger_rebound(df):
            #    signal_lists["볼린저밴드복귀"].append(f"- {name} ({code})")
            if is_envelope_bottom_rebound(df):
                signal_lists["엔벨로프반등"].append(f"- {name} ({code})")
            if is_envelope_squeeze_breakout(df):
                signal_lists["엔벨로프돌파"].append(f"- {name} ({code})")
            if is_macd_golden_cross(df):
                signal_lists["MACD골든크로스"].append(f"- {name} ({code})")
            if is_macd_near_golden_cross(df):
                signal_lists["MACD돌파직전"].append(f"- {name} ({code})")
            if trend == "steady_buying" and is_institution_consecutive_buying(code, app_key, app_secret, access_token):
                signal_lists["외국인기관매수"].append(f"- {name} ({code})") 
            
            # 다중신호 등급 분류
            if score >= 5:
                multi_signal_stocks["ultra_strong"].append({
                    "name": name, "code": code, "score": score, 
                    "signals": active_signals, "price": current_price, "volume": volume,
                    "foreign": netbuy_list 
                })
            elif score == 4:
                multi_signal_stocks["strong"].append({
                    "name": name, "code": code, "score": score, 
                    "signals": active_signals, "price": current_price, "volume": volume,
                    "foreign": netbuy_list
                })
            elif score == 3:
                multi_signal_stocks["moderate"].append({
                    "name": name, "code": code, "score": score, 
                    "signals": active_signals, "price": current_price, "volume": volume,
                    "foreign": netbuy_list
                })
            elif score == 2:
                multi_signal_stocks["weak"].append({
                    "name": name, "code": code, "score": score, 
                    "signals": active_signals, "price": current_price, "volume": volume,
                    "foreign": netbuy_list
                })
            elif score == 1:
                multi_signal_stocks["single"].append({
                    "name": name, "code": code, "score": score, 
                    "signals": active_signals, "price": current_price, "volume": volume,
                    "foreign": netbuy_list
                })
            
            # 신호 조합 패턴 분석
            if score >= 2:
                combo_key = " + ".join(sorted(active_signals))
                if combo_key not in signal_combinations:
                    signal_combinations[combo_key] = []
                signal_combinations[combo_key].append(f"{name}({code})")

        except Exception as e:
            logger.error(f"⚠️ {name} 분석 오류: {e}")
        
        time.sleep(1.0)  # API 호출 간격을 1초로 증가

    # 결과 전송
    priority_order = ["ultra_strong", "strong", "moderate", "weak", "single"]
    
    for grade in priority_order:
        if multi_signal_stocks[grade]:
            msg = format_multi_signal_message(grade, multi_signal_stocks[grade])
            if msg:
                send_discord_message(msg, webhook_url)
                logger.info(f"{grade} 종목: {len(multi_signal_stocks[grade])}개")
    
    # 신호 조합 패턴 분석 결과 전송
    if signal_combinations:
        combo_msg = format_signal_combination_message(signal_combinations)
        if combo_msg:
            send_discord_message(combo_msg, webhook_url)
            logger.info(f"신호 조합 패턴: {len(signal_combinations)}개")
    
    # 요약 통계 전송
    total_multi_signals = sum(len(stocks) for grade, stocks in multi_signal_stocks.items() if grade != "single")
    summary_msg = f"📈 **[다중신호 종목 요약]**\n"
    summary_msg += f"🚀 초강력 신호: {len(multi_signal_stocks['ultra_strong'])}개\n"
    summary_msg += f"🔥 강력 신호: {len(multi_signal_stocks['strong'])}개\n"
    summary_msg += f"⭐ 보통 신호: {len(multi_signal_stocks['moderate'])}개\n"
    summary_msg += f"⚡ 약한 신호: {len(multi_signal_stocks['weak'])}개\n"
    summary_msg += f"💡 단일 신호: {len(multi_signal_stocks['single'])}개\n"
    summary_msg += f"📊 **총 다중신호 종목: {total_multi_signals}개**"
    
    send_discord_message(summary_msg, webhook_url)

    # 개별 신호 상세
    detail_mode = os.getenv("DETAIL_MODE", "false").lower() == "true"
    if detail_mode:
        for signal_type, signal_list in signal_lists.items():
            if signal_list:
                icons = {
                    #"볼린저밴드복귀": "🔵", 
                    "엔벨로프반등": "📉", 
                    "엔벨로프돌파": "📈",
                    "MACD골든크로스": "⚡",
                    "MACD돌파직전": "🔆",  # 새로 추가
                    "외국인기관매수": "🌍"
                }
                icon = icons.get(signal_type, "📊")
                msg = f"{icon} **[{signal_type} 발생 종목]**\n" + "\n".join(signal_list)
                send_discord_message(msg, webhook_url)
                logger.info(f"{signal_type}: {len(signal_list)}개")

    logger.info("분석 완료!")
