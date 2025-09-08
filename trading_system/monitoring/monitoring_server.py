"""
주식 포트폴리오 모니터링 웹 서버
trading_system/monitoring/monitoring_server.py
"""
import os
import sys
import json
import threading
import time
from datetime import datetime
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
            
            if is_market_hours:
                update_portfolio_data()
                time.sleep(10)  # 1분마다 업데이트
            else:
                print(f"📴 장외시간 - 업데이트 대기 중... ({now.strftime('%H:%M')})")
                time.sleep(300)  # 5분마다 체크
                
        except Exception as e:
            print(f"❌ 백그라운드 업데이트 오류: {e}")
            time.sleep(60)

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
    """포트폴리오 데이터 API"""
    global portfolio_cache
    
    try:
        # 캐시된 데이터가 없거나 너무 오래된 경우 즉시 업데이트
        if not portfolio_cache or not last_update_time:
            update_portfolio_data()
        elif (datetime.now() - last_update_time).total_seconds() > 300:  # 5분 이상
            update_portfolio_data()
        
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
    """강제 새로고침 API"""
    try:
        update_portfolio_data()
        return jsonify({
            'success': True,
            'message': '데이터가 성공적으로 업데이트되었습니다.',
            'lastUpdate': last_update_time.isoformat() if last_update_time else None
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'업데이트 실패: {str(e)}'
        }), 500

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
