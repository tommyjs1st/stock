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

def get_period_price_data_alternative(access_token, app_key, app_secret, stock_code, days=60, max_retries=3):
    """
    대안 API: 주식현재가 일자별 API를 사용한 데이터 조회
    더 안정적일 수 있음
    """
    from datetime import datetime, timedelta
    
    # 오늘부터 역산해서 영업일 기준으로 계산
    end_date = datetime.now()
    # 주말과 공휴일을 고려해 실제 달력일로는 더 많이 빼기
    start_date = end_date - timedelta(days=int(days * 1.4))  # 영업일 고려해 1.4배
    
    start_date_str = start_date.strftime("%Y%m%d")
    end_date_str = end_date.strftime("%Y%m%d")
    
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-price"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": app_key,
        "appSecret": app_secret,
        "tr_id": "FHKST01010400"
    }
    
    # 여러 번에 나누어 조회 (API 제한 때문)
    all_data = []
    current_end = end_date
    
    for i in range(3):  # 최대 3번 나누어 조회 (각각 30일씩)
        current_start = current_end - timedelta(days=30)
        if current_start < start_date:
            current_start = start_date
            
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
            "fid_input_date_1": current_start.strftime("%Y%m%d"),
            "fid_input_date_2": current_end.strftime("%Y%m%d"),
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0"
        }
        
        for attempt in range(max_retries):
            try:
                time.sleep(0.2)  # API 호출 간격
                response = requests.get(url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                data = response.json().get("output", [])
                
                if data:
                    all_data.extend(data)
                    print(f"📊 {stock_code}: {current_start.strftime('%Y%m%d')}~{current_end.strftime('%Y%m%d')} {len(data)}건 조회")
                break
                
            except Exception as e:
                print(f"❌ 구간 조회 오류 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                continue
        
        current_end = current_start - timedelta(days=1)
        if current_end <= start_date:
            break
    
    if not all_data:
        print(f"❌ {stock_code} 대안 API 데이터 조회 실패")
        return None
    
    # DataFrame 생성 및 중복 제거
    df = pd.DataFrame(all_data)
    df = df.drop_duplicates(subset=['stck_bsop_date']).reset_index(drop=True)
    
    # 데이터 타입 변환
    df["stck_clpr"] = pd.to_numeric(df["stck_clpr"], errors="coerce")
    df["stck_hgpr"] = pd.to_numeric(df["stck_hgpr"], errors="coerce") 
    df["stck_lwpr"] = pd.to_numeric(df["stck_lwpr"], errors="coerce")
    df["acml_vol"] = pd.to_numeric(df["acml_vol"], errors="coerce")
    
    df = df.dropna(subset=["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"])
    df = df.sort_values(by="stck_bsop_date").reset_index(drop=True)
    
    print(f"✅ {stock_code}: 대안 API로 총 {len(df)}일 데이터 조회 완료")
    return df


def get_period_price_data(access_token, app_key, app_secret, stock_code, days=60, period="D", max_retries=3):
    """
    국내주식기간별시세 API를 사용해 더 긴 기간 데이터 조회
    days: 조회할 일수 (기본 60일)
    period: "D"(일), "W"(주), "M"(월), "Y"(년)
    """
    from datetime import datetime, timedelta
    
    # 시작일과 종료일 계산
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days + 20)  # 여유분 20일 추가 (휴장일 고려)
    
    start_date_str = start_date.strftime("%Y%m%d")
    end_date_str = end_date.strftime("%Y%m%d")
    
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": app_key,
        "appSecret": app_secret,
        "tr_id": "FHKST03010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code,
        "fid_input_date_1": start_date_str,  # 시작일 명시
        "fid_input_date_2": end_date_str,    # 종료일 명시
        "fid_period_div_code": period,       # "D":일, "W":주, "M":월, "Y":년
        "fid_org_adj_prc": "0"              # 0:수정주가, 1:원주가
    }
    
    logger.debug("📅 {stock_code}: {start_date_str} ~ {end_date_str} 데이터 조회 시작")
    
    # 데이터 조회 (재시도)
    df = None
    for attempt in range(max_retries):
        try:
            time.sleep(0.1)
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get("output2", [])  # output2가 실제 데이터
            df = pd.DataFrame(data)
            break
        except requests.exceptions.ConnectionError as e:
            print(f"❌ 기간별 데이터 연결 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
        except Exception as e:
            print(f"❌ 기간별 데이터 조회 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
    
    if df is None or df.empty:
        print(f"❌ {stock_code} 기간별 데이터 조회 실패")
        return None
    
    # 데이터 타입 변환 및 컬럼명 통일
    df = df.rename(columns={
        'stck_bsop_date': 'stck_bsop_date',  # 영업일자
        'stck_clpr': 'stck_clpr',           # 종가
        'stck_oprc': 'stck_oprc',           # 시가
        'stck_hgpr': 'stck_hgpr',           # 고가
        'stck_lwpr': 'stck_lwpr',           # 저가
        'acml_vol': 'acml_vol'              # 누적거래량
    })
    
    # 숫자 변환
    df["stck_clpr"] = pd.to_numeric(df["stck_clpr"], errors="coerce")
    df["stck_hgpr"] = pd.to_numeric(df["stck_hgpr"], errors="coerce")
    df["stck_lwpr"] = pd.to_numeric(df["stck_lwpr"], errors="coerce")
    df["acml_vol"] = pd.to_numeric(df["acml_vol"], errors="coerce")
    
    # 결측치 제거
    df = df.dropna(subset=["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"])
    
    # 날짜순 정렬 (과거 → 현재)
    df = df.sort_values(by="stck_bsop_date").reset_index(drop=True)
    
    #print(f"✅ {stock_code}: {len(df)}일 데이터 조회 완료")
    return df


def get_daily_price_data_with_realtime(access_token, app_key, app_secret, stock_code, days=60, max_retries=3):
    """
    개선된 일봉 데이터 + 실시간 현재가 결합
    기간별시세 API를 사용해 지정한 일수만큼 데이터 확보
    days: 조회할 일수 (기본 60일, MACD용으로 충분)
    """
    # 먼저 기간별시세 API로 충분한 과거 데이터 조회
    df = get_period_price_data(access_token, app_key, app_secret, stock_code, days=days, period="D", max_retries=max_retries)
    
    # 기본 API가 실패하면 대안 API 시도
    if df is None or len(df) < 30:
        print(f"⚠️ {stock_code}: 기본 API 실패, 대안 API 시도...")
        df = get_period_price_data_alternative(access_token, app_key, app_secret, stock_code, days=days, max_retries=max_retries)
    
    if df is None or df.empty:
        print(f"❌ {stock_code} 기간별 데이터 조회 실패")
        return None
    
    # MACD 계산 가능 여부 확인
    if len(df) < 35:
        logger.info("⚠️ {stock_code}: 데이터 부족 ({len(df)}일) - MACD 분석에는 최소 35일 필요")
    elif len(df) < 50:
        logger.info("⚠️ {stock_code}: 데이터 부족 ({len(df)}일) - MACD 정확도를 위해 50일 이상 권장")
    else:
        logger.debug("✅ {stock_code}: {len(df)}일 데이터로 MACD 분석 가능")
    
    # 실시간 현재가 조회해서 최신 데이터 업데이트
    current_price, current_volume = get_current_price(access_token, app_key, app_secret, stock_code)
    
    if current_price and current_volume:
        today = datetime.now().strftime("%Y%m%d")
        
        # 최신 데이터가 오늘 데이터인지 확인
        if len(df) > 0 and df.iloc[-1]["stck_bsop_date"] == today:
            # 오늘 데이터를 실시간 가격으로 업데이트
            df.loc[df.index[-1], "stck_clpr"] = current_price
            df.loc[df.index[-1], "acml_vol"] = current_volume
            logger.debug("📈 {stock_code}: 오늘 데이터를 실시간 가격으로 업데이트")
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
            logger.debug("📈 {stock_code}: 오늘 실시간 데이터 추가")
    
    return df


def is_macd_golden_cross(df):
    """
    개선된 MACD 골든크로스 신호 감지 (충분한 데이터로 정확도 향상)
    """
    if len(df) < 35:  # 최소 35일 필요
        return False
    
    try:
        close_prices = df['stck_clpr'].copy()
        
        if close_prices.isnull().any():
            return False
        
        # 표준 MACD 계산 (12일 EMA - 26일 EMA)
        ema_12 = close_prices.ewm(span=12, adjust=False).mean()
        ema_26 = close_prices.ewm(span=26, adjust=False).mean()
        ema_05 = close_prices.ewm(span=5, adjust=False).mean()
        
        # MACD Line 계산
        #macd_line = ema_12 - ema_26
        macd_line = ema_05 - ema_12
        
        # Signal Line 계산 (MACD의 9일 EMA)
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        if len(macd_line) < 2:
            return False
        
        # 오늘과 어제의 MACD, Signal 값
        today_macd = macd_line.iloc[-1]
        today_signal = signal_line.iloc[-1]
        yesterday_macd = macd_line.iloc[-2]
        yesterday_signal = signal_line.iloc[-2]
        
        # 골든크로스 조건 (매수 신호만)
        # 1. 어제는 MACD가 Signal 아래에 있었음
        # 2. 오늘은 MACD가 Signal 위로 돌파
        # 3. MACD가 상승 추세
        golden_cross_today = (
            yesterday_macd <= yesterday_signal and  # 어제는 아래
            today_macd > today_signal and          # 오늘은 위로 돌파
            today_macd > yesterday_macd            # MACD가 상승 추세
        )
        
        # 추가 필터: 매수 시점만 감지 (0선 근처 이하에서만 유효)
        valid_cross = today_signal <= 0.2  # Signal이 0선 근처 또는 아래
        
        # 충분한 데이터가 있을 때만 추가 검증
        if len(df) >= 50:
            # 거래량 증가 확인 (선택사항)
            volume_surge = df.iloc[-1]["acml_vol"] > df["acml_vol"].tail(10).mean() * 1.1
            return golden_cross_today and valid_cross and volume_surge
        else:
            return golden_cross_today and valid_cross
        
    except Exception as e:
        print(f"MACD 계산 오류: {e}")
        return False


def is_macd_near_golden_cross(df):
    """
    개선된 MACD 골든크로스 근접 신호 감지
    """
    if len(df) < 35:
        return False
    
    try:
        close_prices = df['stck_clpr'].copy()
        
        if close_prices.isnull().any():
            return False
        
        # 표준 MACD 계산
        ema_12 = close_prices.ewm(span=12, adjust=False).mean()
        ema_26 = close_prices.ewm(span=26, adjust=False).mean()
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        if len(macd_line) < 5:
            return False
        
        current_macd = macd_line.iloc[-1]
        current_signal = signal_line.iloc[-1]
        
        # 1. MACD가 Signal 아래에 있어야 함
        if current_macd >= current_signal:
            return False
        
        # 2. 차이가 매우 작음 (근접 상태)
        diff = abs(current_macd - current_signal)
        signal_abs = abs(current_signal)
        is_close = (diff / max(signal_abs, 0.01) <= 0.05) or (diff <= 0.03)
        
        # 3. MACD 상승 추세 확인
        macd_trend_up = False
        if len(macd_line) >= 3:
            macd_trend_up = (
                macd_line.iloc[-1] > macd_line.iloc[-2] and 
                macd_line.iloc[-2] >= macd_line.iloc[-3]
            )
        
        # 4. 히스토그램 개선 추세
        histogram_improving = False
        if len(macd_line) >= 3:
            hist_today = current_macd - current_signal
            hist_yesterday = macd_line.iloc[-2] - signal_line.iloc[-2]
            hist_2days_ago = macd_line.iloc[-3] - signal_line.iloc[-3]
            
            histogram_improving = (
                hist_today > hist_yesterday and 
                hist_yesterday > hist_2days_ago
            )
        
        # 5. 매수 구간에서만 유효
        valid_position = current_signal <= 0.3
        
        return (is_close and 
                (macd_trend_up or histogram_improving) and 
                valid_position)
        
    except Exception as e:
        print(f"MACD 근접 계산 오류: {e}")
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
                logger.debug(f"{name}: 분석 대상 포함({cnt})")

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
