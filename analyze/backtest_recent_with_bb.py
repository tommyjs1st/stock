"""
외국인 데이터가 있는 기간만 백테스팅
2025-12-23 ~ 2026-02-04
"""
import sys
import yaml
import pandas as pd
from datetime import datetime, timedelta
from data_fetcher import DataFetcher
from technical_indicators import SignalAnalyzer, TechnicalIndicators, check_foreign_consecutive_buying
from db_manager import DBManager
from utils import setup_logger

def backtest_with_foreign_data():
    """외국인 데이터 있는 기간 백테스팅"""
    logger = setup_logger("backtest_recent")
    
    print("="*70)
    print("🚀 외국인 데이터 있는 기간 백테스팅 (4가지 조건)")
    print("   기간: 2025-12-23 ~ 2026-02-04")
    print("="*70)
    print("✅ 적용 조건:")
    print("   1. 현재가 < 20일선")
    print("   2. 거래량 ≥ 1,000주")
    print("   3. 볼린저밴드 하단선 위")
    print("   4. 외국인 2일 연속 순매수")
    print("="*70)
    
    # 설정
    with open("../trading_system/config.yaml", 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        db_config = config.get('database', {})
    
    # 초기화
    db_manager = DBManager(db_config, logger)
    data_fetcher = DataFetcher()
    ti = TechnicalIndicators()
    
    # 테스트할 날짜들 (매주)
    test_dates = [
        datetime(2025, 12, 24),
        datetime(2025, 12, 30),
        datetime(2026, 1, 6),
        datetime(2026, 1, 13),
        datetime(2026, 1, 20),
        datetime(2026, 1, 27),
        datetime(2026, 2, 3),
    ]
    
    all_discoveries = []
    
    for test_date in test_dates:
        print(f"\n{'='*70}")
        print(f"📅 분석일: {test_date.strftime('%Y-%m-%d')}")
        print('='*70)
        
        # 종목 리스트
        stock_list = data_fetcher.get_top_200_stocks()
        test_stocks = list(stock_list.items())[:100]  # 100개 테스트
        
        discoveries = []
        stats = {
            'total': 0,
            'data_ok': 0,
            'pass_ma20': 0,
            'pass_volume': 0,
            'pass_bollinger': 0,
            'pass_foreign': 0,
            'pass_all': 0
        }
        
        for name, code in test_stocks:
            try:
                stats['total'] += 1
                
                # DB에서 데이터 조회
                db_manager.connect()
                cursor = db_manager.connection.cursor()
                
                query = """
                    SELECT trade_date, close_price, high_price, low_price, volume
                    FROM daily_stock_prices
                    WHERE stock_code = %s AND trade_date <= %s
                    ORDER BY trade_date DESC
                    LIMIT 100
                """
                
                cursor.execute(query, (code, test_date.strftime('%Y-%m-%d')))
                rows = cursor.fetchall()
                
                if not rows or len(rows) < 30:
                    continue
                
                stats['data_ok'] += 1
                
                # DataFrame 변환
                if isinstance(rows[0], dict):
                    df = pd.DataFrame(rows)
                else:
                    df = pd.DataFrame(rows, columns=['trade_date', 'close_price', 'high_price', 'low_price', 'volume'])
                
                df = df.rename(columns={
                    'close_price': 'stck_clpr',
                    'high_price': 'stck_hgpr',
                    'low_price': 'stck_lwpr',
                    'volume': 'acml_vol'
                })
                
                for col in ['stck_clpr', 'stck_hgpr', 'stck_lwpr', 'acml_vol']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                df['stck_bsop_date'] = pd.to_datetime(df['trade_date']).dt.strftime('%Y%m%d')
                df = df.drop('trade_date', axis=1)
                df = df.sort_values('stck_bsop_date').reset_index(drop=True)
                
                # 외국인 데이터
                query2 = """
                    SELECT foreign_net_qty
                    FROM daily_stock_prices
                    WHERE stock_code = %s AND trade_date <= %s
                    ORDER BY trade_date DESC
                    LIMIT 5
                """
                cursor.execute(query2, (code, test_date.strftime('%Y-%m-%d')))
                foreign_rows = cursor.fetchall()
                
                if isinstance(foreign_rows[0], dict):
                    foreign_netbuy = [int(r['foreign_net_qty']) if r['foreign_net_qty'] else 0 for r in foreign_rows]
                else:
                    foreign_netbuy = [int(r[0]) if r[0] else 0 for r in foreign_rows]
                
                # 절대조건 체크 (4가지 모두!)
                check_ma20 = ti.is_price_below_ma20(df, name)
                if check_ma20:
                    stats['pass_ma20'] += 1
                
                check_volume = ti.is_volume_sufficient(df, min_volume=1000)
                if check_volume:
                    stats['pass_volume'] += 1
                
                # 🔥 볼린저밴드 조건 추가!
                check_bollinger = ti.is_price_above_bollinger_lower(df)
                if check_bollinger:
                    stats['pass_bollinger'] = stats.get('pass_bollinger', 0) + 1
                
                foreign_check = check_foreign_consecutive_buying(foreign_netbuy)
                check_foreign = foreign_check['meets_condition'] if foreign_check else False
                if check_foreign:
                    stats['pass_foreign'] += 1
                
                # 🔥 4가지 조건 모두 체크!
                passes_absolute = check_ma20 and check_volume and check_bollinger and check_foreign
                
                if passes_absolute:
                    stats['pass_all'] += 1
                    
                    # 기술적 신호
                    signals = []
                    score = 3
                    
                    if ti.is_golden_cross(df):
                        signals.append('골든크로스')
                        score += 1
                    
                    if ti.is_volume_breakout(df):
                        signals.append('거래량급증')
                        score += 1
                    
                    discoveries.append({
                        'name': name,
                        'code': code,
                        'score': score,
                        'signals': signals,
                        'price': df.iloc[-1]['stck_clpr'],
                        'foreign': foreign_netbuy[:3]
                    })
                    
                    print(f"   ✅ {name}({code}) - {score}점 {signals}")
                
            except Exception as e:
                logger.debug(f"   ⚠️ {name}({code}) 오류: {e}")
            finally:
                db_manager.disconnect()
        
        # 통계
        print(f"\n   📊 통계:")
        print(f"      전체: {stats['total']}개")
        print(f"      데이터 충분: {stats['data_ok']}개")
        print(f"      20일선 아래: {stats['pass_ma20']}개")
        print(f"      거래량 충족: {stats['pass_volume']}개")
        print(f"      볼린저밴드 하단 위: {stats.get('pass_bollinger', 0)}개 ⭐")
        print(f"      외국인 연속매수: {stats['pass_foreign']}개")
        print(f"      ✅ 절대조건 통과(4개): {stats['pass_all']}개")
        print(f"      🎯 발굴: {len(discoveries)}개")
        
        if discoveries:
            all_discoveries.extend(discoveries)
    
    print("\n" + "="*70)
    print(f"📊 전체 백테스팅 결과")
    print("="*70)
    print(f"   테스트 날짜: {len(test_dates)}개")
    print(f"   총 발굴: {len(all_discoveries)}개")
    print("="*70)
    
    if all_discoveries:
        print("\n🎯 발굴 종목 상세:")
        sorted_discoveries = sorted(all_discoveries, key=lambda x: x['score'], reverse=True)
        for i, d in enumerate(sorted_discoveries[:20], 1):
            print(f"   {i}. {d['name']}({d['code']}) - {d['score']}점")
            print(f"      신호: {d['signals']}")
            print(f"      가격: {d['price']:,}원")
            print(f"      외국인(최근3일): {d['foreign']}")
    else:
        print("\n❌ 발굴 종목 없음")
        print("💡 이유:")
        print("   - 2025년 12월~2026년 1월은 강한 상승장")
        print("   - 대부분 종목이 20일선 위")
        print("   - 외국인 연속 매수 조건도 여전히 엄격")


if __name__ == "__main__":
    backtest_with_foreign_data()
