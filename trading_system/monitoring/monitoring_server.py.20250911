
"""
주식 포트폴리오 모니터링 웹 서버
trading_system/monitoring/monitoring_server.py
"""
import os
import sys
import json
import threading
import time
import pandas as pd  # 추가
from datetime import datetime, timedelta  # timedelta 추가
from typing import Dict, List

# 상위 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from flask import Flask, jsonify, render_template_string, send_from_directory
except ImportError:
    print("❌ Flask가 설치되지 않았습니다.")
    print("다음 명령어로 설치하세요:")
    print("pip install flask")
    sys.exit(1)

try:
    from config.config_manager import ConfigManager
    from data.kis_api_client import KISAPIClient
    import logging
except ImportError as e:
    print(f"❌ 모듈 임포트 실패: {e}")
    print("trading_system 디렉토리에서 실행해주세요.")
    sys.exit(1)

app = Flask(__name__)

# 전역 변수
api_client = None
stock_names_cache = {}
portfolio_cache = {}
last_update_time = None

def load_stock_names():
    """종목명 캐시 로드"""
    global stock_names_cache
    try:
        stock_names_file = os.path.join(parent_dir, 'stock_names.json')
        if os.path.exists(stock_names_file):
            with open(stock_names_file, 'r', encoding='utf-8') as f:
                stock_names_cache = json.load(f)
                print(f"📋 종목명 {len(stock_names_cache)}개 로드")
    except Exception as e:
        print(f"⚠️ 종목명 로드 실패: {e}")

def get_stock_name(symbol: str) -> str:
    """종목명 조회"""
    if symbol in stock_names_cache:
        return stock_names_cache[symbol]
    
    # API로 조회 시도
    try:
        basic_info = api_client.get_stock_basic_info(symbol)
        if basic_info and basic_info.get('output'):
            output = basic_info['output']
            if 'prdt_abrv_name' in output and output['prdt_abrv_name']:
                stock_name = str(output['prdt_abrv_name']).strip()
                if stock_name:
                    stock_names_cache[symbol] = stock_name
                    return stock_name
    except Exception:
        pass
    
    return symbol

def update_portfolio_data():
    """포트폴리오 데이터 업데이트"""
    global portfolio_cache, last_update_time
    
    try:
        print("📊 포트폴리오 데이터 업데이트 중...")
        
        # 계좌 보유 종목 조회
        holdings_data = api_client.get_all_holdings()
        
        if not holdings_data:
            print("⚠️ 보유 종목 데이터가 없습니다.")
            portfolio_cache = {'holdings': [], 'error': '보유 종목이 없습니다.'}
            return
        
        portfolio_list = []
        
        for symbol, position in holdings_data.items():
            try:
                # 현재가 조회 (전일대비 정보 포함)
                current_price_data = api_client.get_current_price(symbol)
                current_price = 0
                daily_change = 0
                daily_change_amount = 0
                
                if current_price_data and current_price_data.get('output'):
                    output = current_price_data['output']
                    current_price = float(output.get('stck_prpr', 0))
                    
                    # 현재가 API에서 전일대비 정보 직접 추출
                    prdy_ctrt = output.get('prdy_ctrt', '0')  # 전일대비율
                    prdy_vrss = output.get('prdy_vrss', '0')  # 전일대비 가격
                    
                    try:
                        daily_change = float(prdy_ctrt) if prdy_ctrt else 0
                        daily_change_amount = int(float(prdy_vrss)) if prdy_vrss else 0
                        print(f"📈 {symbol} 현재가API 전일대비: {daily_change}%, {daily_change_amount}원")
                    except (ValueError, TypeError):
                        print(f"⚠️ {symbol} 현재가API 전일대비 파싱 실패")
                        daily_change = 0
                        daily_change_amount = 0
                
                # 현재가 API 실패 시 기존 방식으로 폴백
                if current_price == 0:
                    current_price = position['current_price']
                    print(f"⚠️ {symbol} 현재가 API 실패, 계좌정보 사용: {current_price}")
                
                # 현재가 API에서 전일대비를 못 가져온 경우 일봉으로 계산
                if daily_change == 0 and daily_change_amount == 0:
                    try:
                        daily_df = api_client.get_daily_data(symbol, days=10)
                        if not daily_df.empty and len(daily_df) >= 2:
                            # 가장 최근 거래일의 종가 (전일 종가)
                            yesterday_close = float(daily_df['stck_prpr'].iloc[-2])
                            
                            if yesterday_close > 0 and current_price > 0:
                                daily_change = ((current_price - yesterday_close) / yesterday_close) * 100
                                daily_change_amount = int(current_price - yesterday_close)
                                print(f"📊 {symbol} 일봉계산 전일대비: {daily_change:.2f}%, {daily_change_amount}원")
                    except Exception as e:
                        print(f"❌ {symbol} 일봉 전일대비 계산 실패: {e}")
                
                stock_info = {
                    'symbol': symbol,
                    'name': get_stock_name(symbol),
                    'quantity': position['quantity'],
                    'avgPrice': int(position['avg_price']),
                    'currentPrice': int(current_price),
                    'totalValue': position['total_value'],
                    'purchaseAmount': position['purchase_amount'],
                    'profitLoss': position['total_value'] - position['purchase_amount'],
                    'profitRate': position['profit_loss'],
                    'dailyChange': round(daily_change, 2),
                    'dailyChangeAmount': daily_change_amount
                }
                
                portfolio_list.append(stock_info)
                print(f"✅ {stock_info['name']}({symbol}) 완료 - 현재가: {int(current_price):,}원, 전일대비: {daily_change:+.2f}%")
                
                # API 호출 간격
                time.sleep(0.2)
                
            except Exception as e:
                print(f"❌ {symbol} 데이터 처리 실패: {e}")
                continue
        
        portfolio_cache = {
            'holdings': portfolio_list,
            'lastUpdate': datetime.now().isoformat(),
            'error': None
        }
        
        last_update_time = datetime.now()
        print(f"✅ 포트폴리오 데이터 업데이트 완료 ({len(portfolio_list)}개 종목)")
        
    except Exception as e:
        print(f"❌ 포트폴리오 데이터 업데이트 실패: {e}")
        portfolio_cache = {
            'holdings': [],
            'error': f'데이터 조회 실패: {str(e)}',
            'lastUpdate': datetime.now().isoformat()
        }
        
def background_updater():
    """백그라운드에서 주기적으로 데이터 업데이트"""
    while True:
        try:
            # 장 시간에만 업데이트 (평일 9:00-15:30)
            now = datetime.now()
            weekday = now.weekday()
            hour = now.hour
            minute = now.minute
            
            is_market_hours = (
                weekday < 5 and  # 평일
                (hour > 9 or (hour == 9 and minute >= 0)) and  # 9시 이후
                (hour < 15 or (hour == 15 and minute <= 30))   # 15:30 이전
            )
            

            # 장 시간 확인 (평일 9:00-15:30)
            is_market_hours = (
                weekday < 5 and  # 평일
                (hour > 9 or (hour == 9 and minute >= 0)) and  # 9시 이후
                (hour < 15 or (hour == 15 and minute <= 30))   # 15:30 이전
            )
            
            if is_market_hours:
                # 🔥 장 시간 중: 2분마다 업데이트 (기존 10초 → 2분)
                print(f"📊 장중 포트폴리오 업데이트: {now.strftime('%H:%M:%S')}")
                update_portfolio_data()
                time.sleep(120)  # 2분 = 120초
                
            elif weekday < 5:  
                # 🔥 평일 장외시간: 30분마다 체크 (기존 5분 → 30분)
                print(f"📴 평일 장외시간 - 대기 중... ({now.strftime('%H:%M')})")
                time.sleep(1800)  # 30분 = 1800초
                
            else:
                # 🔥 주말: 1시간마다 체크 (기존 5분 → 1시간)
                print(f"🛌 주말 휴장 - 대기 중... ({now.strftime('%m/%d %H:%M')})")
                time.sleep(3600)  # 1시간 = 3600초
                
        except Exception as e:
            print(f"❌ 백그라운드 업데이트 오류: {e}")
            time.sleep(300)

@app.route('/')
def index():
    """메인 페이지"""
    # HTML 파일이 있으면 그것을 사용, 없으면 기본 HTML 반환
    html_file = os.path.join(current_dir, 'index.html')
    if os.path.exists(html_file):
        with open(html_file, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>주식 모니터링</title>
            <meta charset="UTF-8">
        </head>
        <body>
            <h1>주식 포트폴리오 모니터링</h1>
            <p>HTML 파일을 찾을 수 없습니다.</p>
            <p>monitoring/index.html 파일을 생성해주세요.</p>
            <a href="/api/portfolio">API 테스트</a>
        </body>
        </html>
        """


@app.route('/api/portfolio')
def get_portfolio():
    """포트폴리오 데이터 API (캐시 최적화)"""
    global portfolio_cache, last_update_time
    
    try:
        now = datetime.now()
        
        # 🔥 캐시 유효기간 설정 (장중: 2분, 장외: 10분)
        weekday = now.weekday()
        hour = now.hour
        minute = now.minute
        
        is_market_hours = (
            weekday < 5 and
            (hour > 9 or (hour == 9 and minute >= 0)) and
            (hour < 15 or (hour == 15 and minute <= 30))
        )
        
        # 캐시 만료 시간 설정
        if is_market_hours:
            cache_expire_seconds = 120  # 장중: 2분
        else:
            cache_expire_seconds = 600  # 장외: 10분
        
        # 캐시 확인 및 업데이트
        should_update = (
            not portfolio_cache or 
            not last_update_time or
            (now - last_update_time).total_seconds() > cache_expire_seconds
        )
        
        if should_update:
            print(f"📊 API 요청으로 포트폴리오 즉시 업데이트 (캐시 만료: {cache_expire_seconds}초)")
            update_portfolio_data()
        else:
            remaining_seconds = cache_expire_seconds - (now - last_update_time).total_seconds()
            print(f"📋 캐시된 데이터 사용 (다음 업데이트까지: {remaining_seconds:.0f}초)")
        
        return jsonify(portfolio_cache)
        
    except Exception as e:
        return jsonify({
            'holdings': [],
            'error': f'API 오류: {str(e)}',
            'lastUpdate': datetime.now().isoformat()
        }), 500

@app.route('/api/market-status')
def get_market_status():
    """시장 상태 API"""
    now = datetime.now()
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    
    if weekday >= 5:  # 주말
        status = "주말 휴장"
        is_open = False
    elif hour < 9:
        status = "장 시작 전"
        is_open = False
    elif hour > 15 or (hour == 15 and minute >= 30):
        status = "장 마감"
        is_open = False
    else:
        status = "정규장 운영 중"
        is_open = True
    
    return jsonify({
        'status': status,
        'isOpen': is_open,
        'currentTime': now.strftime('%Y-%m-%d %H:%M:%S'),
        'weekday': weekday
    })


@app.route('/api/refresh')
def force_refresh():
    """강제 새로고침 API (쿨다운 적용)"""
    global last_update_time
    
    try:
        now = datetime.now()
        
        # 🔥 쿨다운: 최근 30초 이내 업데이트가 있었으면 거부
        if last_update_time:
            seconds_since_last = (now - last_update_time).total_seconds()
            if seconds_since_last < 30:
                remaining_cooldown = 30 - seconds_since_last
                return jsonify({
                    'success': False,
                    'message': f'너무 빈번한 새로고침입니다. {remaining_cooldown:.0f}초 후 다시 시도하세요.',
                    'cooldown_remaining': remaining_cooldown
                }), 429  # Too Many Requests
        
        # 강제 업데이트 실행
        print("🔄 사용자 강제 새로고침 요청")
        update_portfolio_data()
        
        return jsonify({
            'success': True,
            'message': '데이터가 성공적으로 업데이트되었습니다.',
            'lastUpdate': last_update_time.isoformat() if last_update_time else None
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/system-status')
def get_system_status():
    """시스템 상태 및 캐시 정보 API"""
    global last_update_time, portfolio_cache
    
    now = datetime.now()
    
    # 장 시간 확인
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    
    is_market_hours = (
        weekday < 5 and
        (hour > 9 or (hour == 9 and minute >= 0)) and
        (hour < 15 or (hour == 15 and minute <= 30))
    )
    
    # 캐시 상태
    cache_age_seconds = 0
    if last_update_time:
        cache_age_seconds = (now - last_update_time).total_seconds()
    
    cache_expire_seconds = 120 if is_market_hours else 600
    cache_remaining = max(0, cache_expire_seconds - cache_age_seconds)
    
    return jsonify({
        'current_time': now.strftime('%Y-%m-%d %H:%M:%S'),
        'is_market_hours': is_market_hours,
        'last_update': last_update_time.isoformat() if last_update_time else None,
        'cache_age_seconds': int(cache_age_seconds),
        'cache_expire_seconds': cache_expire_seconds,
        'cache_remaining_seconds': int(cache_remaining),
        'portfolio_count': len(portfolio_cache.get('holdings', [])) if portfolio_cache else 0,
        'has_error': bool(portfolio_cache.get('error')) if portfolio_cache else False,
        'update_interval': {
            'market_hours': '2분',
            'off_hours_weekday': '30분', 
            'weekend': '1시간'
        }
    })

@app.route('/api/performance')
def get_performance():
    """수익금 중심 수익 추이 API"""
    try:
        # 🔥 경로 수정: 상위 디렉토리의 daily_performance.json 찾기
        performance_file = os.path.join(parent_dir, 'daily_performance.json')
        
        if os.path.exists(performance_file):
            with open(performance_file, 'r', encoding='utf-8') as f:
                all_performance = json.load(f)
            
            # 최근 14일 데이터만 사용
            recent_performance = all_performance[-14:] if len(all_performance) > 14 else all_performance
            
            # 🔥 수익금 중심으로 데이터 변환
            validated_performance = []
            for item in recent_performance:
                try:
                    profit_loss = float(item.get('total_profit_loss', 0))
                    return_pct = float(item.get('total_return_pct', 0))
                    
                    validated_item = {
                        'date': item.get('date', ''),
                        'total_assets': float(item.get('total_assets', 0)),
                        'total_profit_loss': profit_loss,
                        'total_return_pct': return_pct,
                        'position_count': int(item.get('position_count', 0)),
                        'profit_loss_krw': round(profit_loss / 10000, 1)  # 만원 단위
                    }
                    validated_performance.append(validated_item)
                except (ValueError, TypeError) as e:
                    print(f"⚠️ 데이터 검증 실패: {item} - {e}")
                    continue
            
            print(f"✅ 수익금 추이 데이터 조회 성공: {len(validated_performance)}개")
            
            return jsonify({
                'performance': validated_performance,
                'count': len(validated_performance),
                'period': f'{len(validated_performance)}일',
                'data_type': 'profit_loss'
            })
        else:
            print(f"⚠️ 성과 파일 없음: {performance_file}")
            sample_data = create_profit_sample_data()
            return jsonify({
                'performance': sample_data,
                'count': len(sample_data),
                'period': f'{len(sample_data)}일 (샘플)',
                'data_type': 'profit_loss'
            })
            
    except Exception as e:
        print(f"❌ 수익금 추이 조회 오류: {e}")
        import traceback
        print(f"상세 오류: {traceback.format_exc()}")
        
        sample_data = create_profit_sample_data()
        return jsonify({
            'performance': sample_data,
            'count': len(sample_data),
            'period': f'{len(sample_data)}일 (샘플)',
            'data_type': 'profit_loss',
            'error': str(e)
        })


def create_profit_sample_data():
    """수익금 중심 샘플 데이터 생성"""
    from datetime import datetime, timedelta
    import random
    
    data = []
    
    for i in range(7):
        date = datetime.now() - timedelta(days=6-i)
        
        # 실제와 비슷한 수익금 패턴 생성
        if i == 0:
            profit_loss = random.uniform(-25000, 5000)  # 첫날
        else:
            # 이전 수익에서 변동
            prev_profit = data[i-1]['total_profit_loss']
            daily_change = random.uniform(-15000, 20000)
            profit_loss = prev_profit + daily_change
            
        # 수익률 계산 (85만원 기준)
        base_assets = 850000
        return_pct = (profit_loss / base_assets) * 100
        total_assets = base_assets + profit_loss
        
        data.append({
            'date': date.strftime('%Y-%m-%d'),
            'total_assets': round(total_assets),
            'total_profit_loss': round(profit_loss),
            'total_return_pct': round(return_pct, 2),
            'position_count': random.randint(3, 7),
            'profit_loss_krw': round(profit_loss / 10000, 1)
        })
    
    return data

@app.route('/api/backfill-portfolio-history')
def backfill_portfolio_history():
    """과거 포트폴리오 일별 수익률 백필 (최대 30일)"""
    try:
        print("🔄 과거 포트폴리오 데이터 백필 시작...")
        
        # 1. 현재 보유 종목 정보 확인
        holdings_data = api_client.get_all_holdings()
        if not holdings_data:
            return jsonify({
                'backfilled_data': [],
                'error': '현재 보유 종목이 없습니다',
                'count': 0
            })
        
        # 2. 백필할 기간 설정 (최대 30일)
        backfill_days = 30
        end_date = datetime.now()
        start_date = end_date - timedelta(days=backfill_days)
        
        print(f"📅 백필 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
        
        # 3. 각 종목별 과거 일봉 데이터 수집
        symbols_daily_data = {}
        for symbol in holdings_data.keys():
            try:
                stock_name = get_stock_name(symbol)
                print(f"📊 {stock_name}({symbol}) 과거 일봉 데이터 조회 중...")
                
                daily_df = api_client.get_daily_data(symbol, days=backfill_days + 5)
                if not daily_df.empty:
                    # 날짜 컬럼 정리
                    if 'stck_bsop_date' in daily_df.columns:
                        daily_df['date'] = pd.to_datetime(daily_df['stck_bsop_date'], format='%Y%m%d')
                    else:
                        continue
                    
                    # 기간 필터링
                    daily_df = daily_df[
                        (daily_df['date'] >= start_date) & 
                        (daily_df['date'] <= end_date)
                    ].sort_values('date')
                    
                    symbols_daily_data[symbol] = daily_df
                    print(f"  ✅ {len(daily_df)}일치 데이터 수집")
                
                time.sleep(0.2)  # API 호출 간격
                
            except Exception as e:
                print(f"  ❌ {symbol} 일봉 데이터 수집 실패: {e}")
                continue
        
        if not symbols_daily_data:
            return jsonify({
                'backfilled_data': [],
                'error': '과거 일봉 데이터를 가져올 수 없습니다',
                'count': 0
            })
        
        # 4. 일별 포트폴리오 수익률 계산
        backfilled_returns = []
        
        # 날짜별로 정렬된 공통 날짜 추출
        all_dates = set()
        for df in symbols_daily_data.values():
            all_dates.update(df['date'].dt.date)
        
        sorted_dates = sorted(all_dates)
        print(f"📊 총 {len(sorted_dates)}일 데이터 처리 예정")
        
        for i, current_date in enumerate(sorted_dates):
            if i == 0:  # 첫날은 전일 대비 계산 불가
                continue
            
            previous_date = sorted_dates[i-1]
            
            try:
                daily_portfolio_change = calculate_daily_portfolio_return(
                    symbols_daily_data, holdings_data, current_date, previous_date
                )
                
                if daily_portfolio_change:
                    backfilled_returns.append(daily_portfolio_change)
                    
            except Exception as e:
                print(f"❌ {current_date} 일별 수익률 계산 실패: {e}")
                continue
        
        print(f"✅ {len(backfilled_returns)}일의 과거 일별 수익률 계산 완료")
        
        # 5. 기존 데이터와 병합 (옵션)
        try:
            performance_file = os.path.join(parent_dir, 'daily_performance.json')
            if os.path.exists(performance_file):
                with open(performance_file, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                
                # 기존 데이터에서 같은 날짜 제거 후 병합
                existing_dates = {item.get('date') for item in existing_data}
                new_data = [item for item in backfilled_returns 
                           if item.get('date') not in existing_dates]
                
                combined_data = existing_data + new_data
                combined_data.sort(key=lambda x: x.get('date', ''))
                
                print(f"📝 기존 {len(existing_data)}일 + 신규 {len(new_data)}일 = 총 {len(combined_data)}일")
                
        except Exception as e:
            print(f"⚠️ 기존 데이터 병합 실패: {e}")
            combined_data = backfilled_returns
        
        return jsonify({
            'backfilled_data': backfilled_returns,
            'count': len(backfilled_returns),
            'period': f'{len(backfilled_returns)}일 (백필)',
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d')
        })
        
    except Exception as e:
        print(f"❌ 과거 데이터 백필 실패: {e}")
        return jsonify({
            'backfilled_data': [],
            'error': str(e),
            'count': 0
        })

def calculate_daily_portfolio_return(symbols_data, current_holdings, current_date, previous_date):
    """특정 날짜의 포트폴리오 일별 수익률 계산"""
    try:
        total_current_value = 0
        total_previous_value = 0
        daily_change_amount = 0
        
        for symbol, position in current_holdings.items():
            if symbol not in symbols_data:
                continue
            
            df = symbols_data[symbol]
            
            # 해당 날짜의 종가 찾기
            current_day_data = df[df['date'].dt.date == current_date]
            previous_day_data = df[df['date'].dt.date == previous_date]
            
            if current_day_data.empty or previous_day_data.empty:
                continue
            
            current_price = float(current_day_data['stck_prpr'].iloc[0])
            previous_price = float(previous_day_data['stck_prpr'].iloc[0])
            
            # 현재 보유수량 기준으로 계산 (과거 거래 정보가 없으므로)
            quantity = position['quantity']
            
            current_value = current_price * quantity
            previous_value = previous_price * quantity
            change_amount = current_value - previous_value
            
            total_current_value += current_value
            total_previous_value += previous_value
            daily_change_amount += change_amount
        
        if total_previous_value > 0:
            daily_return_pct = (daily_change_amount / total_previous_value) * 100
            
            return {
                'date': current_date.strftime('%Y-%m-%d'),
                'daily_return_pct': round(daily_return_pct, 2),
                'daily_return_amount': round(daily_change_amount),
                'total_current_value': round(total_current_value),
                'total_previous_value': round(total_previous_value),
                'method': 'backfilled',
                'note': '현재 보유수량 기준 역산'
            }
        
        return None
        
    except Exception as e:
        print(f"❌ {current_date} 포트폴리오 수익률 계산 실패: {e}")
        return None


@app.route('/api/accurate-daily-returns')
def get_accurate_daily_returns():
    """거래기록을 반영한 정확한 포트폴리오 일별 수익률 계산"""
    try:
        print("📊 정확한 포트폴리오 일별 수익률 계산 시작...")
        
        # 1. 현재 포트폴리오 상태 조회
        holdings_data = api_client.get_all_holdings()
        account_data = api_client.get_account_balance()
        
        if not holdings_data or not account_data:
            return jsonify({
                'accurate_daily_returns': [],
                'error': '포트폴리오 데이터 조회 실패',
                'count': 0
            })
        
        # 2. 당일 거래 기록 조회
        today_trades = get_today_trades()
        print(f"📝 당일 거래기록: {len(today_trades)}건")
        
        # 3. 각 종목별 정확한 전일대비 계산
        accurate_returns = []
        total_daily_change_amount = 0
        total_current_value = 0
        total_yesterday_value = 0
        
        current_cash = float(account_data.get('output', {}).get('ord_psbl_cash', 0))
        
        for symbol, position in holdings_data.items():
            try:
                stock_name = get_stock_name(symbol)
                current_price = position['current_price']
                quantity = position['quantity']
                current_stock_value = position['total_value']
                
                # 4. 당일 거래 여부 확인
                today_symbol_trades = [t for t in today_trades if t['symbol'] == symbol]
                
                if today_symbol_trades:
                    # 매수/매도가 있는 경우: 거래가격 기준으로 계산
                    print(f"💱 {stock_name}({symbol}) 당일 거래 {len(today_symbol_trades)}건 발견")
                    
                    # 전일 마감 후 보유수량과 가격 역산
                    total_buy_qty = sum(t['quantity'] for t in today_symbol_trades if t['action'] == 'BUY')
                    total_sell_qty = sum(t['quantity'] for t in today_symbol_trades if t['action'] == 'SELL')
                    
                    # 전일 보유수량 = 현재수량 - 순매수수량
                    net_buy_qty = total_buy_qty - total_sell_qty
                    yesterday_quantity = quantity - net_buy_qty
                    
                    if yesterday_quantity > 0:
                        # 전일 보유분의 가치 변화 계산
                        yesterday_price = get_yesterday_close_price(symbol, current_price)
                        yesterday_value = yesterday_price * yesterday_quantity
                        current_value_of_yesterday_holdings = current_price * yesterday_quantity
                        
                        # 당일 거래분의 손익 계산
                        trade_pnl = 0
                        for trade in today_symbol_trades:
                            if trade['action'] == 'BUY':
                                # 매수: (현재가 - 매수가) × 수량
                                trade_pnl += (current_price - trade['price']) * trade['quantity']
                            elif trade['action'] == 'SELL':
                                # 매도: (매도가 - 전일종가) × 수량  
                                trade_pnl += (trade['price'] - yesterday_price) * trade['quantity']
                        
                        daily_change_amount = (current_value_of_yesterday_holdings - yesterday_value) + trade_pnl
                        
                    else:
                        # 전일 보유 없음, 당일 신규매수만
                        yesterday_value = 0
                        daily_change_amount = sum(
                            (current_price - t['price']) * t['quantity'] 
                            for t in today_symbol_trades if t['action'] == 'BUY'
                        )
                    
                    print(f"  📊 거래반영 손익: {daily_change_amount:+,}원")
                    
                else:
                    # 거래가 없는 경우: 기존 방식 (전일종가 대비)
                    yesterday_price = get_yesterday_close_price(symbol, current_price)
                    yesterday_value = yesterday_price * quantity
                    daily_change_amount = current_stock_value - yesterday_value
                    
                    print(f"  📊 전일대비: {current_price:,}원 vs {yesterday_price:,}원 = {daily_change_amount:+,}원")
                
                accurate_returns.append({
                    'symbol': symbol,
                    'name': stock_name,
                    'quantity': quantity,
                    'current_price': current_price,
                    'yesterday_value': yesterday_value,
                    'current_value': current_stock_value,
                    'daily_change_amount': daily_change_amount,
                    'has_trades': len(today_symbol_trades) > 0,
                    'trades_count': len(today_symbol_trades)
                })
                
                total_daily_change_amount += daily_change_amount
                total_current_value += current_stock_value
                total_yesterday_value += yesterday_value
                
            except Exception as e:
                print(f"❌ {symbol} 일별 수익률 계산 실패: {e}")
                continue
        
        # 5. 포트폴리오 전체 일별 수익률
        current_total_assets = current_cash + total_current_value
        yesterday_total_assets = current_cash + total_yesterday_value  # 현금은 변동 없다고 가정
        
        if yesterday_total_assets > 0:
            portfolio_daily_return_pct = (total_daily_change_amount / yesterday_total_assets) * 100
        else:
            portfolio_daily_return_pct = 0
        
        result = {
            'accurate_daily_returns': [{
                'date': datetime.now().strftime('%Y-%m-%d'),
                'daily_return_pct': round(portfolio_daily_return_pct, 2),
                'daily_return_amount': total_daily_change_amount,
                'current_total_assets': current_total_assets,
                'yesterday_total_assets': yesterday_total_assets,
                'stock_contributions': accurate_returns,
                'today_trades_count': len(today_trades),
                'method': 'trade_adjusted'
            }],
            'count': 1,
            'period': '정확한 실시간 계산'
        }
        
        print(f"📊 정확한 포트폴리오 일별 수익률: {portfolio_daily_return_pct:+.2f}% ({total_daily_change_amount:+,}원)")
        print(f"💰 어제: {yesterday_total_assets:,}원 → 오늘: {current_total_assets:,}원")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ 정확한 포트폴리오 일별 수익률 계산 실패: {e}")
        import traceback
        print(f"상세 오류: {traceback.format_exc()}")
        return jsonify({
            'accurate_daily_returns': [],
            'error': str(e),
            'count': 0,
            'period': '계산 실패'
        })

def get_today_trades():
    """당일 거래 기록 조회"""
    try:
        trades_file = os.path.join(parent_dir, 'daily_trades.json')
        if not os.path.exists(trades_file):
            return []
        
        with open(trades_file, 'r', encoding='utf-8') as f:
            all_trades = json.load(f)
        
        today = datetime.now().strftime('%Y-%m-%d')
        today_trades = [trade for trade in all_trades 
                       if trade.get('timestamp', '').startswith(today)]
        
        return today_trades
        
    except Exception as e:
        print(f"❌ 당일 거래 기록 조회 실패: {e}")
        return []

def get_yesterday_close_price(symbol: str, current_price: float) -> float:
    """전일 종가 조회 (API 또는 계산)"""
    try:
        # 1. 현재가 API에서 전일대비 정보로 역산
        current_price_data = api_client.get_current_price(symbol)
        if current_price_data and current_price_data.get('output'):
            output = current_price_data['output']
            prdy_vrss = output.get('prdy_vrss', '0')  # 전일대비 가격변동
            
            try:
                daily_change_per_share = float(prdy_vrss) if prdy_vrss else 0
                yesterday_price = current_price - daily_change_per_share
                if yesterday_price > 0:
                    return yesterday_price
            except:
                pass
        
        # 2. 일봉 데이터에서 전일 종가 조회
        daily_df = api_client.get_daily_data(symbol, days=5)
        if not daily_df.empty and len(daily_df) >= 2:
            yesterday_price = float(daily_df['stck_prpr'].iloc[-2])
            if yesterday_price > 0:
                return yesterday_price
        
        # 3. 모든 방법 실패 시 현재가의 98~102% 범위로 추정
        return current_price * 0.99  # 보수적 추정
        
    except Exception as e:
        print(f"⚠️ {symbol} 전일 종가 조회 실패: {e}")
        return current_price * 0.99

@app.route('/api/complete-daily-returns')
def get_complete_daily_returns():
    """완전한 일별 수익률 (실시간 + 백필 데이터)"""
    try:
        print("📊 완전한 일별 수익률 데이터 준비 중...")
        
        # 1. 백필 데이터 가져오기
        backfill_response = backfill_portfolio_history()
        backfill_data = backfill_response.get_json()
        
        if backfill_data.get('error'):
            print(f"⚠️ 백필 실패: {backfill_data['error']}")
            historical_returns = []
        else:
            historical_returns = backfill_data.get('backfilled_data', [])
        
        # 2. 오늘 실시간 데이터 가져오기 (기존 API 활용)
        today_response = get_accurate_daily_returns()
        today_data = today_response.get_json()
        
        if today_data.get('error'):
            print(f"⚠️ 실시간 데이터 실패: {today_data['error']}")
            today_returns = []
        else:
            today_returns = today_data.get('accurate_daily_returns', [])
        
        # 3. 데이터 병합 및 정렬
        all_returns = historical_returns + today_returns
        
        # 중복 날짜 제거 (오늘 데이터 우선)
        unique_returns = {}
        for item in all_returns:
            date = item.get('date')
            if date:
                unique_returns[date] = item
        
        # 날짜순 정렬
        sorted_returns = sorted(unique_returns.values(), key=lambda x: x.get('date', ''))
        
        # 최근 30일만 반환
        final_returns = sorted_returns[-30:] if len(sorted_returns) > 30 else sorted_returns
        
        result = {
            'complete_daily_returns': final_returns,
            'count': len(final_returns),
            'period': f'최근 {len(final_returns)}일 (백필+실시간)',
            'historical_count': len(historical_returns),
            'realtime_count': len(today_returns)
        }
        
        print(f"✅ 완전한 일별 수익률 준비 완료: {len(final_returns)}일")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ 완전한 일별 수익률 조회 실패: {e}")
        return jsonify({
            'complete_daily_returns': [],
            'error': str(e),
            'count': 0
        })


def get_today_trades():
    """당일 거래 기록 조회"""
    try:
        trades_file = os.path.join(parent_dir, 'daily_trades.json')
        if not os.path.exists(trades_file):
            return []
        
        with open(trades_file, 'r', encoding='utf-8') as f:
            all_trades = json.load(f)
        
        today = datetime.now().strftime('%Y-%m-%d')
        today_trades = [trade for trade in all_trades 
                       if trade.get('timestamp', '').startswith(today)]
        
        return today_trades
        
    except Exception as e:
        print(f"❌ 당일 거래 기록 조회 실패: {e}")
        return []

def get_yesterday_close_price(symbol: str, current_price: float) -> float:
    """전일 종가 조회 (API 또는 계산)"""
    try:
        # 1. 현재가 API에서 전일대비 정보로 역산
        current_price_data = api_client.get_current_price(symbol)
        if current_price_data and current_price_data.get('output'):
            output = current_price_data['output']
            prdy_vrss = output.get('prdy_vrss', '0')  # 전일대비 가격변동
            
            try:
                daily_change_per_share = float(prdy_vrss) if prdy_vrss else 0
                yesterday_price = current_price - daily_change_per_share
                if yesterday_price > 0:
                    return yesterday_price
            except:
                pass
        
        # 2. 일봉 데이터에서 전일 종가 조회
        daily_df = api_client.get_daily_data(symbol, days=5)
        if not daily_df.empty and len(daily_df) >= 2:
            yesterday_price = float(daily_df['stck_prpr'].iloc[-2])
            if yesterday_price > 0:
                return yesterday_price
        
        # 3. 모든 방법 실패 시 현재가의 98~102% 범위로 추정
        return current_price * 0.99  # 보수적 추정
        
    except Exception as e:
        print(f"⚠️ {symbol} 전일 종가 조회 실패: {e}")
        return current_price * 0.99


@app.route('/api/portfolio-daily-returns')
def get_portfolio_daily_returns():
    """포트폴리오 일별 수익률 실시간 계산"""
    try:
        print("📊 포트폴리오 일별 수익률 실시간 계산 시작...")
        
        # 1. 현재 포트폴리오 상태 조회
        holdings_data = api_client.get_all_holdings()
        account_data = api_client.get_account_balance()
        
        if not holdings_data or not account_data:
            return jsonify({
                'portfolio_daily_returns': [],
                'error': '포트폴리오 데이터 조회 실패',
                'count': 0
            })
        
        # 2. 현재 총 자산 계산
        current_cash = float(account_data.get('output', {}).get('ord_psbl_cash', 0))
        current_stock_value = sum(pos['total_value'] for pos in holdings_data.values())
        current_total_assets = current_cash + current_stock_value
        
        print(f"💰 현재 총 자산: {current_total_assets:,.0f}원 (현금: {current_cash:,.0f}, 주식: {current_stock_value:,.0f})")
        
        # 3. 각 종목별 전일대비 수익률 계산
        daily_returns = []
        total_yesterday_value = 0
        total_daily_change_amount = 0
        
        for symbol, position in holdings_data.items():
            try:
                # 현재가 API에서 전일대비 정보 조회
                current_price_data = api_client.get_current_price(symbol)
                
                if current_price_data and current_price_data.get('output'):
                    output = current_price_data['output']
                    current_price = float(output.get('stck_prpr', 0))
                    prdy_vrss = output.get('prdy_vrss', '0')  # 전일대비 가격변동
                    
                    try:
                        daily_change_per_share = int(float(prdy_vrss)) if prdy_vrss else 0
                    except:
                        daily_change_per_share = 0
                    
                    quantity = position['quantity']
                    
                    # 종목별 일일 손익 = 전일대비 가격변동 × 보유수량
                    stock_daily_change = daily_change_per_share * quantity
                    
                    # 전일 종가 계산
                    yesterday_price = current_price - daily_change_per_share
                    yesterday_stock_value = yesterday_price * quantity
                    
                    daily_returns.append({
                        'symbol': symbol,
                        'name': get_stock_name(symbol),
                        'quantity': quantity,
                        'current_price': current_price,
                        'yesterday_price': yesterday_price,
                        'daily_change_per_share': daily_change_per_share,
                        'daily_change_amount': stock_daily_change,
                        'current_value': position['total_value'],
                        'yesterday_value': yesterday_stock_value
                    })
                    
                    total_yesterday_value += yesterday_stock_value
                    total_daily_change_amount += stock_daily_change
                    
                    print(f"📈 {get_stock_name(symbol)}({symbol}): {daily_change_per_share:+,}원/주 × {quantity}주 = {stock_daily_change:+,}원")
                
                time.sleep(0.1)  # API 호출 간격
                
            except Exception as e:
                print(f"❌ {symbol} 일별 수익률 계산 실패: {e}")
                continue
        
        # 4. 포트폴리오 전체 일별 수익률 계산
        if total_yesterday_value > 0:
            # 전일 총 자산 = 전일 주식가치 + 현재 현금 (현금은 변동 없다고 가정)
            yesterday_total_assets = total_yesterday_value + current_cash
            
            # 포트폴리오 일별 수익률
            portfolio_daily_return_pct = (total_daily_change_amount / yesterday_total_assets) * 100
            portfolio_daily_return_amount = total_daily_change_amount
            
            result = {
                'portfolio_daily_returns': [{
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'daily_return_pct': round(portfolio_daily_return_pct, 2),
                    'daily_return_amount': portfolio_daily_return_amount,
                    'current_total_assets': current_total_assets,
                    'yesterday_total_assets': yesterday_total_assets,
                    'stock_contributions': daily_returns
                }],
                'count': 1,
                'period': '실시간 계산'
            }
            
            print(f"📊 포트폴리오 일별 수익률: {portfolio_daily_return_pct:+.2f}% ({portfolio_daily_return_amount:+,}원)")
            
        else:
            result = {
                'portfolio_daily_returns': [],
                'error': '전일 기준가 계산 실패',
                'count': 0
            }
        
        # 5. 과거 데이터와 결합 (옵션)
        try:
            performance_file = os.path.join(parent_dir, 'daily_performance.json')
            if os.path.exists(performance_file):
                with open(performance_file, 'r', encoding='utf-8') as f:
                    past_performances = json.load(f)
                
                # 과거 데이터에서 일별 수익률 계산
                past_daily_returns = []
                for i in range(1, min(len(past_performances), 8)):  # 최근 7일
                    prev_data = past_performances[i-1]
                    curr_data = past_performances[i]
                    
                    prev_assets = prev_data.get('total_assets', 0)
                    curr_assets = curr_data.get('total_assets', 0)
                    
                    if prev_assets > 0:
                        daily_return_pct = ((curr_assets - prev_assets) / prev_assets) * 100
                        daily_return_amount = curr_assets - prev_assets
                        
                        past_daily_returns.append({
                            'date': curr_data.get('date', ''),
                            'daily_return_pct': round(daily_return_pct, 2),
                            'daily_return_amount': round(daily_return_amount),
                            'current_total_assets': curr_assets,
                            'yesterday_total_assets': prev_assets
                        })
                
                # 과거 데이터와 오늘 데이터 결합
                result['portfolio_daily_returns'] = past_daily_returns + result['portfolio_daily_returns']
                result['count'] = len(result['portfolio_daily_returns'])
                result['period'] = f'최근 {len(result["portfolio_daily_returns"])}일'
        
        except Exception as e:
            print(f"⚠️ 과거 데이터 결합 실패: {e}")
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ 포트폴리오 일별 수익률 계산 실패: {e}")
        return jsonify({
            'portfolio_daily_returns': [],
            'error': str(e),
            'count': 0,
            'period': '계산 실패'
        })


@app.route('/api/daily-returns')
def get_daily_returns():
    """일별 수익률 데이터 API (누적→일별 변환)"""
    try:
        performance_file = os.path.join(parent_dir, 'daily_performance.json')
        
        if os.path.exists(performance_file):
            with open(performance_file, 'r', encoding='utf-8') as f:
                performances = json.load(f)
                
            if len(performances) < 2:
                print("⚠️ 일별 수익률 계산을 위한 충분한 데이터 없음")
                return jsonify({'daily_returns': [], 'count': 0, 'period': '0일'})
            
            daily_returns = []
            
            for i in range(1, len(performances)):  # 첫 번째 다음부터 계산
                prev_data = performances[i-1]
                curr_data = performances[i]
                
                prev_assets = prev_data.get('total_assets', 0)
                curr_assets = curr_data.get('total_assets', 0)
                
                # 일별 수익률 = (당일 자산 - 전일 자산) / 전일 자산 * 100
                if prev_assets > 0:
                    daily_return_pct = ((curr_assets - prev_assets) / prev_assets) * 100
                    daily_return_amount = curr_assets - prev_assets
                else:
                    daily_return_pct = 0
                    daily_return_amount = 0
                
                daily_returns.append({
                    'date': curr_data.get('date', ''),
                    'daily_return_pct': round(daily_return_pct, 2),
                    'daily_return_amount': round(daily_return_amount),
                    'total_assets': curr_assets,
                    'prev_assets': prev_assets
                })
            
            print(f"✅ 일별 수익률 데이터 계산 완료: {len(daily_returns)}개")
            
            return jsonify({
                'daily_returns': daily_returns[-20:],  # 최근 20일만
                'count': len(daily_returns),
                'period': f'{len(daily_returns)}일'
            })
        else:
            # 샘플 일별 수익률 데이터 생성
            sample_returns = create_sample_daily_returns()
            return jsonify({
                'daily_returns': sample_returns,
                'count': len(sample_returns),
                'period': f'{len(sample_returns)}일 (샘플)'
            })
            
    except Exception as e:
        print(f"❌ 일별 수익률 조회 오류: {e}")
        return jsonify({
            'daily_returns': [],
            'error': str(e),
            'count': 0,
            'period': '0일'
        })

def create_sample_daily_returns():
    """샘플 일별 수익률 데이터 생성"""
    from datetime import datetime, timedelta
    import random
    
    sample_returns = []
    
    for i in range(14):  # 최근 2주
        date = datetime.now() - timedelta(days=13-i)
        
        # 일별 수익률: -2% ~ +3% 범위에서 랜덤
        daily_return_pct = round(random.uniform(-2.0, 3.0), 2)
        daily_return_amount = round(daily_return_pct * 8500)  # 85만원 기준
        
        sample_returns.append({
            'date': date.strftime('%Y-%m-%d'),
            'daily_return_pct': daily_return_pct,
            'daily_return_amount': daily_return_amount,
            'total_assets': 850000 + random.randint(-20000, 50000),  # 샘플 총 자산
            'prev_assets': 850000
        })
    
    return sample_returns

def initialize_system():
    """시스템 초기화"""
    global api_client
    
    try:
        print("🚀 주식 모니터링 서버 초기화 중...")
        
        # 설정 로드
        config_path = os.path.join(parent_dir, 'config.yaml')
        config_manager = ConfigManager(config_path)
        kis_config = config_manager.get_kis_config()
        
        # API 클라이언트 초기화 (토큰 파일 경로를 상위 디렉토리로 설정)
        api_client = KISAPIClient(
            app_key=kis_config['app_key'],
            app_secret=kis_config['app_secret'],
            base_url=kis_config['base_url'],
            account_no=kis_config['account_no']
        )
        
        # 토큰 파일 경로를 상위 디렉토리로 변경
        api_client.token_file = os.path.join(parent_dir, 'token.json')
        
        # 종목명 로드
        load_stock_names()
        
        # 초기 데이터 로드
        update_portfolio_data()
        
        print("✅ 시스템 초기화 완료")
        return True
        
    except Exception as e:
        print(f"❌ 시스템 초기화 실패: {e}")
        return False

if __name__ == '__main__':
    # 로깅 설정
    logging.basicConfig(level=logging.WARNING)
    
    # 시스템 초기화
    if not initialize_system():
        print("❌ 시스템 초기화에 실패했습니다.")
        sys.exit(1)
    
    # 백그라운드 업데이터 시작
    updater_thread = threading.Thread(target=background_updater, daemon=True)
    updater_thread.start()
    
    print("🌐 웹 서버 시작 중...")
    print("📱 브라우저에서 https://localhost:35359 접속")
    print("⏹️  Ctrl+C로 종료")
    
    ssl_cert = os.path.join(current_dir, 'ssl/www.musi.co.kr_20241019A3207.crt.pem')
    ssl_key = os.path.join(current_dir,  'ssl/www.musi.co.kr_20241019A3207.key.pem')

    # Flask 서버 실행
    try:
        if os.path.exists(ssl_cert) and os.path.exists(ssl_key):
            app.run(
                host='0.0.0.0', 
                port=35359,
                ssl_context=(ssl_cert, ssl_key), 
                debug=False, 
                threaded=True
            )
        else:
            print("cert, key 파일이 존재하지 않습니다.")
    except KeyboardInterrupt:
        print("\n🛑 서버를 종료합니다.")
    except Exception as e:
        print(f"❌ 서버 실행 오류: {e}")
