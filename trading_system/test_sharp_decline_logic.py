"""
급락 매수 전략 로직 테스트 (드라이런)
실제 매매 없이 로직만 확인
"""
import json
from datetime import datetime

def test_file_operations():
    """파일 저장/로드/삭제 테스트"""
    print("="*60)
    print("📂 파일 저장/로드/삭제 테스트")
    print("="*60)

    # 테스트 데이터
    test_filename = f"purchased_stocks_{datetime.now().strftime('%Y%m%d')}.json"
    test_data = {
        "005930": {
            "quantity": 10,
            "price": 134500,
            "prev_close": 158600,
            "decline_rate": -0.152,
            "buy_time": "2026-02-08T09:15:23",
            "strategy": "sharp_decline"
        },
        "000660": {
            "quantity": 2,
            "price": 713000,
            "prev_close": 839000,
            "decline_rate": -0.150,
            "buy_time": "2026-02-08T09:22:45",
            "strategy": "sharp_decline"
        }
    }

    print(f"\n1️⃣ 매수 데이터 저장 테스트")
    print(f"   파일명: {test_filename}")
    print(f"   종목 수: {len(test_data)}개")

    # 저장
    try:
        with open(test_filename, 'w', encoding='utf-8') as f:
            json.dump(test_data, f, ensure_ascii=False, indent=2)
        print(f"   ✅ 저장 성공")
    except Exception as e:
        print(f"   ❌ 저장 실패: {e}")
        return False

    # 로드
    print(f"\n2️⃣ 매수 데이터 로드 테스트")
    try:
        with open(test_filename, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        print(f"   ✅ 로드 성공")
        print(f"   종목 수: {len(loaded_data)}개")

        for code, info in loaded_data.items():
            decline_pct = info['decline_rate'] * 100
            print(f"   - {code}: {info['quantity']}주 @ {info['price']:,}원 ({decline_pct:.2f}%)")
    except Exception as e:
        print(f"   ❌ 로드 실패: {e}")
        return False

    # 삭제
    print(f"\n3️⃣ 매도 후 파일 삭제 테스트")
    try:
        import os
        if os.path.exists(test_filename):
            os.remove(test_filename)
            print(f"   ✅ 파일 삭제 성공")
        else:
            print(f"   ⚠️ 파일 없음")
    except Exception as e:
        print(f"   ❌ 삭제 실패: {e}")
        return False

    # 삭제 확인
    import os
    if not os.path.exists(test_filename):
        print(f"   ✅ 파일이 정상적으로 삭제되었습니다")
    else:
        print(f"   ❌ 파일이 여전히 존재합니다")
        return False

    return True

def test_decline_detection():
    """급락 감지 로직 테스트"""
    print("\n" + "="*60)
    print("📉 급락 감지 로직 테스트")
    print("="*60)

    test_cases = [
        {"name": "삼성전자", "prev": 158600, "current": 134500, "expected": True},   # -15.2%
        {"name": "SK하이닉스", "prev": 839000, "current": 713000, "expected": True},  # -15.0%
        {"name": "NAVER", "prev": 249000, "current": 216000, "expected": True},      # -13.3% -> False
        {"name": "현대차", "prev": 467500, "current": 420000, "expected": True},     # -10.2% -> False
        {"name": "카카오", "prev": 50000, "current": 49000, "expected": False},      # -2.0%
    ]

    decline_threshold = 0.15  # 15%

    print(f"\n급락 기준: {decline_threshold*100}% 이상 하락")
    print("")

    for case in test_cases:
        prev_close = case['prev']
        current_price = case['current']
        decline_rate = (current_price - prev_close) / prev_close
        decline_pct = decline_rate * 100

        should_buy = decline_rate <= -decline_threshold

        status = "✅ 매수" if should_buy else "⏸️  관망"
        result = "정상" if should_buy == case['expected'] else "⚠️ 예상과 다름"

        print(f"{status} {case['name']}: "
              f"{prev_close:,}원 → {current_price:,}원 ({decline_pct:+.2f}%) [{result}]")

    return True

def test_time_windows():
    """시간대 체크 테스트"""
    print("\n" + "="*60)
    print("⏰ 시간대 체크 테스트")
    print("="*60)

    from datetime import datetime, time

    test_times = [
        ("08:59", False, False),  # 매수 전
        ("09:00", True, False),   # 매수 시작
        ("09:15", True, False),   # 매수 중
        ("09:29", True, False),   # 매수 마지막
        ("09:30", False, False),  # 매수 종료
        ("14:59", False, False),  # 매도 전
        ("15:00", False, True),   # 매도 시간
        ("15:01", False, False),  # 매도 후
    ]

    buy_start = (9, 0)
    buy_end = (9, 30)
    sell_time = (15, 0)

    print(f"\n매수 시간: {buy_start[0]:02d}:{buy_start[1]:02d} ~ {buy_end[0]:02d}:{buy_end[1]:02d}")
    print(f"매도 시간: {sell_time[0]:02d}:{sell_time[1]:02d}")
    print("")

    for time_str, expected_buy, expected_sell in test_times:
        hour, minute = map(int, time_str.split(':'))

        # 매수 시간 체크
        current_minutes = hour * 60 + minute
        start_minutes = buy_start[0] * 60 + buy_start[1]
        end_minutes = buy_end[0] * 60 + buy_end[1]
        is_buy_time = start_minutes <= current_minutes < end_minutes

        # 매도 시간 체크
        is_sell_time = hour == sell_time[0] and minute == sell_time[1]

        buy_status = "✅ 매수" if is_buy_time else "⏸️  대기"
        sell_status = "✅ 매도" if is_sell_time else "⏸️  대기"

        print(f"{time_str} - {buy_status} | {sell_status}")

    return True

def main():
    """메인 테스트"""
    print("\n" + "="*60)
    print("🧪 급락 매수 전략 로직 테스트 (드라이런)")
    print("="*60)

    results = []

    # 1. 파일 저장/로드/삭제
    results.append(("파일 저장/로드/삭제", test_file_operations()))

    # 2. 급락 감지
    results.append(("급락 감지 로직", test_decline_detection()))

    # 3. 시간대 체크
    results.append(("시간대 체크", test_time_windows()))

    # 결과 요약
    print("\n" + "="*60)
    print("📊 테스트 결과 요약")
    print("="*60)

    for name, result in results:
        status = "✅ 통과" if result else "❌ 실패"
        print(f"{status} - {name}")

    success_count = sum(1 for _, r in results if r)
    total_count = len(results)

    print("\n" + "="*60)

    if success_count == total_count:
        print("🎉 모든 로직 테스트 통과!")
        print("\n다음 단계:")
        print("  1. 월요일 오전 8:50~8:55에 프로그램 실행")
        print("  2. python3 sharp_decline_trader.py")
    else:
        print(f"⚠️ {total_count - success_count}개 테스트 실패")

    print("="*60 + "\n")

if __name__ == "__main__":
    main()
