import pandas as pd
import pathlib
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm

# AppleSDGothicNeo 폰트 경로 직접 지정
font_path = '/System/Library/Fonts/AppleSDGothicNeo.ttc'
font = fm.FontProperties(fname=font_path)
matplotlib.rc('font', family=font.get_name())
matplotlib.rc('axes', unicode_minus=False)  # 마이너스 부호 문제 해결

def generate_profit_charts():
    results_dir = pathlib.Path("results")
    charts_dir = pathlib.Path("charts")
    charts_dir.mkdir(parents=True, exist_ok=True)

    for file_path in results_dir.glob("*.csv"):
        try:
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            df['날짜'] = pd.to_datetime(df['날짜'])
            df['순이익(원)'] = pd.to_numeric(df['순이익(원)'].astype(str).str.replace(',', '', regex=False), errors='coerce')

            if df['순이익(원)'].isnull().all():
                continue

            plt.figure(figsize=(12, 6))
            plt.plot(df['날짜'], df['순이익(원)'], marker='o', linestyle='-', color='b')
            
            stock_code = file_path.stem.replace('_result', '')
            plt.title(f"{stock_code} 날짜별 순이익")
            plt.xlabel('날짜')
            plt.ylabel('순이익 (원)')
            plt.grid(True, linestyle='--', alpha=0.7)
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.gcf().autofmt_xdate()
            
            max_profit = df['순이익(원)'].max()
            min_profit = df['순이익(원)'].min()
            plt.axhline(y=max_profit, color='r', linestyle='--', linewidth=1, 
                       label=f'최대: {max_profit:,.0f}원')
            plt.axhline(y=min_profit, color='g', linestyle='--', linewidth=1, 
                       label=f'최소: {min_profit:,.0f}원')
            plt.legend()
            
            chart_path = charts_dir / f"{stock_code}_profit_chart.png"
            plt.savefig(chart_path, bbox_inches='tight', dpi=300)
            plt.close()
            print(f"차트 생성 완료: {chart_path.name}")
            
        except Exception as e:
            print(f"차트 생성 실패 ({file_path.name}): {str(e)}")

if __name__ == "__main__":
    generate_profit_charts()
