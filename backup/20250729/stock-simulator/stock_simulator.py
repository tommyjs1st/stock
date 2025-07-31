import pandas as pd
import pathlib
from datetime import datetime
import os

def read_stock_data(file_path, date_format="%Y-%m-%d"):
    """CSV 파일에서 주가 데이터 읽기"""
    df = pd.read_csv(file_path)
    df['date'] = pd.to_datetime(df['date'], format=date_format)
    df = df.sort_values('date').reset_index(drop=True)
    return df[['date', 'close']].rename(columns={'close': 'close_price'})

def find_closest_purchase_price(df, target_date):
    """가장 가까운 이전 거래일의 매입 가격 찾기 (타임스탬프로 변환)"""
    # target_date를 pd.Timestamp로 변환
    target_ts = pd.Timestamp(target_date)
    filtered_df = df[df['date'] <= target_ts]  # 타입 일치 비교
    if filtered_df.empty:
        raise ValueError(f"지정된 날짜({target_date}) 이전의 거래 데이터가 없습니다.")
    
    closest_row = filtered_df.iloc[-1]  # 가장 마지막(가장 가까운) 행
    actual_purchase_date = closest_row['date'].date()  # date 객체로 반환
    purchase_price = closest_row['close_price']
    
    if actual_purchase_date != target_date:
        print(f"  ※ 실제 사용된 매입 날짜: {actual_purchase_date} (지정된 날짜: {target_date})")
    
    return purchase_price, actual_purchase_date

def simulate_profits(stock_code, df, target_date, purchase_price, actual_purchase_date, quantity=100):
    """날짜별 순이익 시뮬레이션 (타임스탬프로 변환)"""
    # actual_purchase_date를 pd.Timestamp로 변환
    actual_ts = pd.Timestamp(actual_purchase_date)
    filtered_df = df[df['date'] >= actual_ts]  # 타입 일치 비교
    
    # 순이익 계산
    filtered_df['profit'] = (filtered_df['close_price'] - purchase_price) * quantity
    filtered_df['profit'] = filtered_df['profit'].round(2)
    
    # 종목 코드 추가
    filtered_df['stock_code'] = stock_code
    
    # 컬럼 순서 조정
    result_df = filtered_df[['stock_code', 'date', 'profit']]
    result_df = result_df.rename(columns={'date': '날짜', 'profit': '순이익(원)'})
    return result_df

def main():
    try:
        # 1. 디렉토리 설정
        input_dir = pathlib.Path("data")
        if not input_dir.exists():
            raise FileNotFoundError(f"데이터 디렉토리가 존재하지 않습니다: {input_dir}")

        # 2. 매입 정보 설정
        target_date = datetime(2025, 2, 24).date()  # date 객체
        quantity = 100  # 매수 수량

        # 3. 결과 저장 디렉토리
        output_dir = pathlib.Path("results")
        output_dir.mkdir(parents=True, exist_ok=True)

        # 4. 모든 CSV 파일 처리
        for file_path in input_dir.glob("*.csv"):
            try:
                # 종목 코드 추출
                stock_code = file_path.stem  # 파일명에서 확장자 제거
                
                # 주가 데이터 읽기
                df = read_stock_data(file_path)
                
                # 매입 가격 및 실제 매입 날짜 확인
                purchase_price, actual_purchase_date = find_closest_purchase_price(df, target_date)
                
                # 시뮬레이션 실행
                result_df = simulate_profits(stock_code, df, target_date, purchase_price, actual_purchase_date, quantity)
                
                # 결과 저장
                output_file = output_dir / f"{stock_code}_result.csv"
                result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
                print(f"시뮬레이션 완료: {stock_code}")
                
            except Exception as e:
                print(f"처리 실패 ({file_path.name}): {str(e)}")
                
    except Exception as e:
        print(f"오류 발생: {str(e)}")

if __name__ == "__main__":
    main()
