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
    
    Args:
        df: 주가 데이터프레임
        period: 이동평균 기간 (기본 20일)
        envelope_ratio: 엔벨로프 비율 (기본 6%)
    
    Returns:
        bool: 엔벨로프 하단 반등 신호 여부
    """
    if len(df) < period + 2:
        return False
    
    # 이동평균선 계산
    df["ma"] = df["stck_clpr"].rolling(window=period).mean()
    
    # 엔벨로프 상단/하단 밴드 계산
    df["envelope_upper"] = df["ma"] * (1 + envelope_ratio)
    df["envelope_lower"] = df["ma"] * (1 - envelope_ratio)
    
    # 최근 3일 데이터
    recent_3days = df.tail(3)
    
    if len(recent_3days) < 3:
        return False
    
    # 조건 체크
    day_before_yesterday = recent_3days.iloc[0]  # 3일 전
    yesterday = recent_3days.iloc[1]             # 2일 전 (어제)
    today = recent_3days.iloc[2]                 # 1일 전 (오늘)
    
    # 1. 어제 종가가 엔벨로프 하단 밴드 근처 또는 아래에 있었음
    touched_lower_band = yesterday["stck_clpr"] <= yesterday["envelope_lower"] * 1.01  # 1% 여유
    
    # 2. 오늘 종가가 어제보다 상승하면서 엔벨로프 하단 밴드 위로 올라왔음
    price_recovery = (today["stck_clpr"] > yesterday["stck_clpr"] and 
                     today["stck_clpr"] > today["envelope_lower"])
    
    # 3. 추가 확인: 최저가도 엔벨로프 하단 근처에 터치했는지 확인
    low_touched_band = yesterday["stck_lwpr"] <= yesterday["envelope_lower"] * 1.005  # 0.5% 여유
    
    # 4. 반등폭이 의미있는 수준인지 확인 (최소 0.5% 이상 상승)
    meaningful_rebound = (today["stck_clpr"] / yesterday["stck_clpr"] - 1) >= 0.005
    
    return touched_lower_band and price_recovery and low_touched_band and meaningful_rebound


def is_envelope_squeeze_breakout(df, period=20, envelope_ratio=0.06, squeeze_threshold=0.015):
    """
    엔벨로프 스퀴즈(밴드 축소) 후 상향 돌파 신호
    
    Args:
        df: 주가 데이터프레임
        period: 이동평균 기간 (기본 20일)
        envelope_ratio: 엔벨로프 비율 (기본 6%)
        squeeze_threshold: 스퀴즈 판단 기준 (기본 1.5%)
    
    Returns:
        bool: 엔벨로프 스퀴즈 돌파 신호 여부
    """
    if len(df) < period + 10:
        return False
    
    # 이동평균선과 엔벨로프 계산
    df["ma"] = df["stck_clpr"].rolling(window=period).mean()
    df["envelope_upper"] = df["ma"] * (1 + envelope_ratio)
    df["envelope_lower"] = df["ma"] * (1 - envelope_ratio)
    
    # 엔벨로프 폭 계산 (상단-하단의 비율)
    df["envelope_width"] = (df["envelope_upper"] - df["envelope_lower"]) / df["ma"]
    
    # 최근 10일간 엔벨로프 폭의 평균
    recent_width = df["envelope_width"].tail(10).mean()
    
    # 과거 20일간 엔벨로프 폭의 평균
    past_width = df["envelope_width"].tail(30).head(20).mean()
    
    # 현재 상황
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    # 조건 체크
    # 1. 최근 엔벨로프 폭이 과거보다 축소됨 (스퀴즈 상태)
    is_squeezed = recent_width < past_width * 0.8
    
    # 2. 현재 가격이 엔벨로프 상단을 상향 돌파
    breakout_upper = (yesterday["stck_clpr"] <= yesterday["envelope_upper"] and 
                     today["stck_clpr"] > today["envelope_upper"])
    
    # 3. 거래량 증가 확인
    volume_surge = today["acml_vol"] > df["acml_vol"].tail(5).mean() * 1.2
    
    return is_squeezed and breakout_upper and volume_surge


def get_foreign_netbuy_trend_kis(stock_code, app_key, app_secret, access_token, days=3):
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



def is_institution_consecutive_buying(stock_code, app_key, app_secret, access_token, days=3):
    """
    기관이 N일 연속 순매수했는지 확인
    
    Args:
        stock_code: 종목코드
        app_key: KIS APP KEY
        app_secret: KIS APP SECRET
        access_token: KIS 액세스 토큰
        days: 연속 매수 확인 일수 (기본 3일)
    
    Returns:
        bool: N일 연속 기관 순매수 여부
    """
    netbuy_list, trend = get_institution_netbuy_trend_kis(
        stock_code, app_key, app_secret, access_token, days
    )
    
    # 3일 연속 모두 순매수인 경우
    return trend == "steady_buying" and len(netbuy_list) == days

def setup_logger(log_dir="logs", log_filename="analyze_buying_stocks_3.log", when="midnight", backup_count=7):
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
                if (cnt > 50):
                    stocks[name] = code
                else:
                    logger.info(f"{name}: 시가총액 상위 종목 제외({cnt})")

    return stocks


def get_daily_price_data(access_token, app_key, app_secret, stock_code):
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
    data = response.json().get("output", [])
    df = pd.DataFrame(data)
    df["stck_clpr"] = pd.to_numeric(df["stck_clpr"], errors="coerce")
    df["stck_hgpr"] = pd.to_numeric(df["stck_hgpr"], errors="coerce")  # 고가
    df["stck_lwpr"] = pd.to_numeric(df["stck_lwpr"], errors="coerce")  # 저가
    df["acml_vol"] = pd.to_numeric(df["acml_vol"], errors="coerce")    # 거래량
    df = df.dropna(subset=["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"])
    return df.sort_values(by="stck_bsop_date").reset_index(drop=True)

# 기존 지표들
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
    """종합 매수 신호 점수 계산"""
    signals = {
        "볼린저밴드복귀": is_bollinger_rebound(df),
        "엔벨로프반등": is_envelope_bottom_rebound(df),  
        "엔벨로프돌파": is_envelope_squeeze_breakout(df), 
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
        price_text = f"{stock['price']:,}원"
        volume_text = f"{stock['volume']:,}"
        
        line = f"- {stock['name']} ({stock['code']}) - {stock['score']}점\n"
        line += f"  📊 [{signals_text}]"
        #line += f"  💰 {price_text} | 📈 {volume_text}주"
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
    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")
    access_token = load_token()
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL3")
    logger = setup_logger()
    
    logger.info("📊 시가총액 상위 200개 종목 분석 시작...")
    stock_list = get_top_200_stocks()

    # 각 신호별 종목 리스트
    signal_lists = {
        "볼린저밴드복귀": [],
        "엔벨로프반등": [],
        "엔벨로프돌파": [],  
        "외국인기관매수": [] 
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
    
    # 현재 가격과 추가 정보
    stock_details = []

    for name, code in stock_list.items():
        try:
            # 기본적 분석 필터 적용
            netbuy_list, trend = get_foreign_netbuy_trend_kis(code, app_key, app_secret, access_token)

            df = get_daily_price_data(access_token, app_key, app_secret, code)
            if df is None or df.empty:
                continue

            # 종합 점수 계산
            score, active_signals = calculate_buy_signal_score(df, name, code, foreign_trend=trend)
            
            # 현재 가격 정보
            current_price = df.iloc[-1]["stck_clpr"]
            volume = df.iloc[-1]["acml_vol"]
            
            # 개별 신호 체크
            if is_bollinger_rebound(df):
                signal_lists["볼린저밴드복귀"].append(f"- {name} ({code})")
            if is_envelope_bottom_rebound(df):
                signal_lists["엔벨로프반등"].append(f"- {name} ({code})")
            if is_envelope_squeeze_breakout(df):
                signal_lists["엔벨로프돌파"].append(f"- {name} ({code})")
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

            #if score == 1:
                #multi_signal_stocks["single"].append({
                    #"name": name,
                    #"code": code,
                    #"score": score,
                    #"signals": active_signals,
                    #"price": current_price,
                    #"volume": volume,
                    ##"foreign": netbuy_list
                #})

        except Exception as e:
            logger.error(f"⚠️ {name} 분석 오류: {e}")
        
        time.sleep(0.5)

    # 결과 전송
    # 1. 다중신호 종목 우선순위별 전송
    priority_order = ["ultra_strong", "strong", "moderate", "weak", "single"]
    
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
    summary_msg += f"📊 **총 다중신호 종목: {total_multi_signals}개**"
    
    send_discord_message(summary_msg, webhook_url)

    # 4. 개별 신호 상세 (필요시)
    detail_mode = os.getenv("DETAIL_MODE", "false").lower() == "true"
    if detail_mode:
        for signal_type, signal_list in signal_lists.items():
            if signal_list:
                icons = {
                    "볼린저밴드복귀": "🔵", 
                    "엔벨로프반등": "📉", 
                    "엔벨로프돌파": "📈", 
                    "외국인기관매수": "🌍"
                }
                icon = icons.get(signal_type, "📊")
                msg = f"{icon} **[{signal_type} 발생 종목]**\n" + "\n".join(signal_list)
                send_discord_message(msg, webhook_url)
                logger.info(f"{signal_type}: {len(signal_list)}개")

    logger.info("분석 완료!")

