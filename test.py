import pandas as pd
import numpy as np
import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()

def load_token():
    # 기존 토큰 로드 로직 (간단히)
    with open("token.json", "r") as f:
        token_data = json.load(f)
    return token_data["access_token"]

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
        data = response.json().get("output", {})
        
        current_price = float(data.get("stck_prpr", 0))  # 현재가
        current_volume = int(data.get("acml_vol", 0))    # 누적거래량
        
        return current_price, current_volume
    except Exception as e:
        print(f"현재가 조회 오류: {e}")
        return None, None


def get_daily_price_data(access_token, app_key, app_secret, stock_code):
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
    data = response.json().get("output", [])
    df = pd.DataFrame(data)
    
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
        # 오늘 날짜
        from datetime import datetime
        today = datetime.now().strftime("%Y%m%d")
        
        # 최신 데이터가 오늘 데이터인지 확인
        if len(df) > 0 and df.iloc[-1]["stck_bsop_date"] == today:
            # 오늘 데이터가 있으면 실시간 가격으로 업데이트
            df.loc[df.index[-1], "stck_clpr"] = current_price
            df.loc[df.index[-1], "acml_vol"] = current_volume
            print(f"📈 실시간 가격 업데이트: {current_price:,}원")
        else:
            # 오늘 데이터가 없으면 새로 추가
            new_row = {
                "stck_bsop_date": today,
                "stck_clpr": current_price,
                "stck_hgpr": current_price,  # 실시간에서는 현재가로 임시 설정
                "stck_lwpr": current_price,  # 실시간에서는 현재가로 임시 설정
                "acml_vol": current_volume
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            print(f"📈 오늘 실시간 데이터 추가: {current_price:,}원")
    
    return df

def debug_macd_golden_cross(df, stock_name):
    """
    MACD 골든크로스 디버깅 함수 (30일 확장)
    """
    print(f"\n=== {stock_name} MACD 분석 ===")
    print(f"데이터 길이: {len(df)}일")
    
    if len(df) < 30:
        print("❌ 데이터 부족 (30일 미만)")
        return False
    
    # 최근 15일 데이터 출력
    print("\n📊 최근 15일 종가:")
    recent_prices = df['stck_clpr'].tail(15)
    for i, (idx, price) in enumerate(recent_prices.items()):
        date = df.loc[idx, 'stck_bsop_date']
        print(f"  {date}: {price:,}원")
    
    # MACD 계산
    close_prices = df['stck_clpr'].copy()
    
    # EMA 계산
    ema_12 = close_prices.ewm(span=12, adjust=False).mean()
    ema_26 = close_prices.ewm(span=26, adjust=False).mean()
    
    # MACD Line
    macd_line = ema_12 - ema_26
    
    # Signal Line
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    
    print("\n📈 최근 15일 MACD 데이터:")
    recent_macd = macd_line.tail(15)
    recent_signal = signal_line.tail(15)
    
    for i in range(len(recent_macd)):
        idx = recent_macd.index[i]
        date = df.loc[idx, 'stck_bsop_date']
        macd_val = recent_macd.iloc[i]
        signal_val = recent_signal.iloc[i]
        cross_status = "🟢" if macd_val > signal_val else "🔴"
        diff = macd_val - signal_val
        print(f"  {date}: MACD={macd_val:.4f}, Signal={signal_val:.4f}, 차이={diff:.4f} {cross_status}")
    
    # 골든크로스 검사 (30일로 확장)
    print("\n🔍 골든크로스 검사 (최근 30일):")
    golden_cross_found = False
    cross_dates = []
    
    for i in range(1, min(31, len(macd_line))):
        prev_idx = len(macd_line) - i - 1
        curr_idx = len(macd_line) - i
        
        if prev_idx >= 0:
            prev_macd = macd_line.iloc[prev_idx]
            prev_signal = signal_line.iloc[prev_idx]
            curr_macd = macd_line.iloc[curr_idx]
            curr_signal = signal_line.iloc[curr_idx]
            
            date = df.loc[macd_line.index[curr_idx], 'stck_bsop_date']
            
            if prev_macd <= prev_signal and curr_macd > curr_signal:
                print(f"  ✅ 골든크로스 발견! {date}")
                print(f"     이전: MACD={prev_macd:.4f} ≤ Signal={prev_signal:.4f}")
                print(f"     현재: MACD={curr_macd:.4f} > Signal={curr_signal:.4f}")
                golden_cross_found = True
                cross_dates.append(date)
    
    if not golden_cross_found:
        print("  ❌ 최근 30일 내 골든크로스 없음")
        
        # 가장 가까운 크로스 포인트 찾기
        print("\n🔍 가장 가까운 크로스 상황:")
        for i in range(1, min(31, len(macd_line))):
            prev_idx = len(macd_line) - i - 1
            curr_idx = len(macd_line) - i
            
            if prev_idx >= 0:
                prev_macd = macd_line.iloc[prev_idx]
                prev_signal = signal_line.iloc[prev_idx]
                curr_macd = macd_line.iloc[curr_idx]
                curr_signal = signal_line.iloc[curr_idx]
                
                date = df.loc[macd_line.index[curr_idx], 'stck_bsop_date']
                
                # 크로스에 가까운 상황 찾기
                prev_diff = abs(prev_macd - prev_signal)
                curr_diff = abs(curr_macd - curr_signal)
                
                if prev_diff < 0.1 or curr_diff < 0.1:  # 차이가 0.1 미만인 경우
                    status = "골든" if curr_macd > curr_signal else "데드"
                    print(f"  {date}: {status}크로스 근접 - MACD={curr_macd:.4f}, Signal={curr_signal:.4f}")
    
    # 현재 상태
    current_macd = macd_line.iloc[-1]
    current_signal = signal_line.iloc[-1]
    current_above = current_macd > current_signal
    
    current_macd = recent_macd.iloc[-1]
    current_signal = recent_signal.iloc[-1]
    current_above = current_macd > current_signal
    
    print(f"\n📊 현재 상태:")
    print(f"  MACD: {current_macd:.4f}")
    print(f"  Signal: {current_signal:.4f}")
    print(f"  차이: {current_macd - current_signal:.4f}")
    print(f"  MACD가 Signal보다 위에 있음: {'✅' if current_above else '❌'}")
    print(f"  🔆 돌파 직전 상태: {'✅' if near_cross else '❌'}")
    print(f"  ⚡ 오늘 골든크로스: {'✅' if golden_cross_today else '❌'}")
    
    if recent_crosses:
        print(f"  📅 최근 골든크로스: {', '.join(recent_crosses)}")
    
    print(f"\n🎯 골든크로스 결과: {'✅ 오늘 골든크로스 발생!' if golden_cross_today else '❌ 오늘 골든크로스 없음'}")
    print(f"🔆 돌파직전 결과: {'✅ 돌파 직전 신호!' if near_result else '❌ 돌파 직전 아님'}")
    
    return golden_cross_today

# 테스트 실행
if __name__ == "__main__":
    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")
    access_token = load_token()
    
    # 한화오션 테스트 (종목코드 확인 필요)
    test_stocks = {
        "한화오션": "042660",  # 한화오션 종목코드
        "삼성전자": "005930",  # 비교용
        "SK하이닉스": "000660"  # 비교용
    }
    
    for name, code in test_stocks.items():
        try:
            df = get_daily_price_data(access_token, app_key, app_secret, code)
            debug_macd_golden_cross(df, name)
            print("\n" + "="*50)
        except Exception as e:
            print(f"❌ {name} 오류: {e}")
