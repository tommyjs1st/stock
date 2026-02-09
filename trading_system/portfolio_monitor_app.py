"""
포트폴리오 통합 모니터링 웹앱 (Streamlit)
여러 증권사 보유종목 통합 조회 및 차트 표시
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import sys
import os
from pathlib import Path
import hashlib

# 현재 디렉토리를 Python 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# analyze 디렉토리 추가
analyze_dir = os.path.join(os.path.dirname(current_dir), 'analyze')
if analyze_dir not in sys.path:
    sys.path.insert(0, analyze_dir)

try:
    from config.config_manager import ConfigManager
    from data.kis_api_client import KISAPIClient
    from kiwoom_api_client import KiwoomAPIClient
    from data_fetcher import DataFetcher
except ImportError as e:
    st.error(f"❌ 모듈 임포트 실패: {e}")
    st.stop()


# 페이지 설정 (와이드 모드, 다크 테마)
st.set_page_config(
    page_title="포트폴리오 모니터링",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ========================================
# 비밀번호 인증 (보안)
# ========================================
def check_password():
    """비밀번호 확인"""

    def password_entered():
        """비밀번호 입력 후 확인"""
        # 환경변수 또는 Streamlit secrets에서 비밀번호 가져오기
        # 배포 시: Streamlit Cloud의 Secrets에 APP_PASSWORD 설정
        correct_password = os.getenv("APP_PASSWORD", "portfolio2026")  # 기본값 (변경 필수!)

        # SHA256 해시 비교 (보안 강화)
        entered_hash = hashlib.sha256(st.session_state["password"].encode()).hexdigest()
        correct_hash = hashlib.sha256(correct_password.encode()).hexdigest()

        if entered_hash == correct_hash:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # 비밀번호 삭제
        else:
            st.session_state["password_correct"] = False

    # 이미 인증된 경우
    if st.session_state.get("password_correct", False):
        return True

    # 인증 화면
    st.title("🔐 포트폴리오 모니터링")
    st.markdown("### 비밀번호를 입력하세요")

    st.text_input(
        "비밀번호",
        type="password",
        on_change=password_entered,
        key="password"
    )

    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error("❌ 비밀번호가 올바르지 않습니다.")

    st.info("💡 **배포 시 보안 설정:**\n"
            "1. Streamlit Cloud의 Settings → Secrets에서 `APP_PASSWORD` 설정\n"
            "2. 또는 환경변수로 설정: `export APP_PASSWORD='your_password'`")

    return False


# 커스텀 CSS (다크 테마, 모바일 최적화)
st.markdown("""
<style>
    /* 전체 배경 */
    .main {
        background-color: #0e1117;
    }

    /* 메트릭 카드 스타일 */
    [data-testid="stMetricValue"] {
        font-size: 2rem;
        font-weight: bold;
    }

    /* 테이블 스타일 */
    .dataframe {
        font-size: 0.9rem;
    }

    /* Streamlit dataframe 컬럼 정렬 (더 구체적인 선택자) */
    [data-testid="stDataFrame"] tbody tr td:nth-child(1),
    [data-testid="stDataFrame"] tbody tr td:nth-child(1) div {
        text-align: center !important;  /* 증권사 - 중앙 정렬 */
    }

    [data-testid="stDataFrame"] tbody tr td:nth-child(2),
    [data-testid="stDataFrame"] tbody tr td:nth-child(2) div {
        text-align: left !important;     /* 종목명 - 왼쪽 정렬 */
    }

    [data-testid="stDataFrame"] tbody tr td:nth-child(n+3),
    [data-testid="stDataFrame"] tbody tr td:nth-child(n+3) div {
        text-align: right !important;    /* 나머지 - 우측 정렬 */
    }

    /* 추가: 모든 셀의 내부 요소에도 적용 */
    [data-testid="stDataFrame"] td:nth-child(1) * {
        text-align: center !important;
    }
    [data-testid="stDataFrame"] td:nth-child(2) * {
        text-align: left !important;
    }
    [data-testid="stDataFrame"] td:nth-child(n+3) * {
        text-align: right !important;
    }

    /* 모바일 최적화 */
    @media (max-width: 768px) {
        [data-testid="stMetricValue"] {
            font-size: 1.5rem;
        }
        .dataframe {
            font-size: 0.8rem;
        }
    }

    /* 수익 색상 */
    .profit-positive {
        color: #ff4444;
    }
    .profit-negative {
        color: #4488ff;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def init_clients():
    """API 클라이언트 초기화 (캐싱)"""
    config_manager = ConfigManager("config.yaml")

    # 한국투자 클라이언트
    kis_config = config_manager.get_kis_config()
    kis_client = KISAPIClient(
        app_key=kis_config['app_key'],
        app_secret=kis_config['app_secret'],
        base_url=kis_config['base_url'],
        account_no=kis_config['account_no']
    )

    # 키움 클라이언트
    try:
        kiwoom_client = KiwoomAPIClient()
    except Exception as e:
        st.warning(f"⚠️ 키움 API 초기화 실패: {e}")
        kiwoom_client = None

    # 데이터 페처 (시세 조회용)
    data_fetcher = DataFetcher()

    return kis_client, kiwoom_client, data_fetcher


def get_kis_holdings(kis_client, data_fetcher):
    """한국투자 보유종목 조회"""
    try:
        holdings = kis_client.get_all_holdings()
        if not holdings:
            return pd.DataFrame()

        # DataFrame 변환
        data = []
        for code, info in holdings.items():
            quantity = info.get('quantity', 0)
            avg_price = info.get('avg_price', 0)

            # 현재가 및 전일종가 조회
            current_price = 0
            prev_close = 0
            price_diff = 0
            change_rate = 0

            try:
                price_result = data_fetcher.get_current_price(code)
                if price_result and len(price_result) >= 3:
                    current_price = int(price_result[0])
                    prev_close = int(price_result[2])

                    # 전일대비 계산
                    if prev_close > 0:
                        price_diff = current_price - prev_close
                        change_rate = (price_diff / prev_close) * 100
            except Exception as e:
                st.warning(f"⚠️ {code} 시세 조회 실패: {e}")

            # 평가금액 및 손익 계산
            eval_amount = current_price * quantity if current_price > 0 else 0
            profit_loss = eval_amount - (avg_price * quantity) if avg_price > 0 else 0
            profit_rate = (profit_loss / (avg_price * quantity) * 100) if avg_price > 0 and quantity > 0 else 0

            data.append({
                '증권사': '한국투자',
                '종목코드': code,
                '종목명': info.get('stock_name', code),
                '수량': quantity,
                '평단가': avg_price,
                '현재가': current_price,
                '전일종가': prev_close,
                '전일대비': price_diff,
                '등락률': change_rate,
                '평가금액': eval_amount,
                '손익': profit_loss,
                '수익률': profit_rate,
            })

        return pd.DataFrame(data)

    except Exception as e:
        st.error(f"❌ 한국투자 보유종목 조회 실패: {e}")
        return pd.DataFrame()


def get_kiwoom_holdings(kiwoom_client, data_fetcher):
    """키움 보유종목 조회"""
    try:
        if kiwoom_client is None:
            return pd.DataFrame()

        df = kiwoom_client.get_holdings_all()

        if df.empty:
            return pd.DataFrame()

        # 시세 정보 추가
        data = []
        for _, row in df.iterrows():
            code = row.get('stock_code')
            stock_name = row.get('stock_name', code)
            quantity = row.get('quantity', 0)
            avg_price = row.get('avg_price', 0)

            # 현재가 및 전일종가 조회
            current_price = 0
            prev_close = 0
            price_diff = 0
            change_rate = 0

            try:
                price_result = data_fetcher.get_current_price(code)
                if price_result and len(price_result) >= 3:
                    current_price = int(price_result[0])
                    prev_close = int(price_result[2])

                    # 전일대비 계산
                    if prev_close > 0:
                        price_diff = current_price - prev_close
                        change_rate = (price_diff / prev_close) * 100
            except Exception as e:
                st.warning(f"⚠️ {code} 시세 조회 실패: {e}")

            # 평가금액 및 손익 계산
            eval_amount = current_price * quantity if current_price > 0 else 0
            profit_loss = eval_amount - (avg_price * quantity) if avg_price > 0 else 0
            profit_rate = (profit_loss / (avg_price * quantity) * 100) if avg_price > 0 and quantity > 0 else 0

            data.append({
                '증권사': '키움',
                '종목코드': code,
                '종목명': stock_name,
                '수량': quantity,
                '평단가': avg_price,
                '현재가': current_price,
                '전일종가': prev_close,
                '전일대비': price_diff,
                '등락률': change_rate,
                '평가금액': eval_amount,
                '손익': profit_loss,
                '수익률': profit_rate,
            })

        return pd.DataFrame(data)

    except Exception as e:
        st.error(f"❌ 키움 보유종목 조회 실패: {e}")
        return pd.DataFrame()


def get_kiwoom_daily_profit(kiwoom_client, days=30):
    """키움 일별 수익률 조회"""
    try:
        if kiwoom_client is None:
            return pd.DataFrame()

        df = kiwoom_client.get_daily_profit_history(days=days)
        return df

    except Exception as e:
        st.error(f"❌ 일별 수익률 조회 실패: {e}")
        return pd.DataFrame()


def create_profit_chart(df):
    """일별 수익률 차트 생성 (Plotly)"""
    if df.empty:
        st.warning("📊 수익률 데이터가 없습니다.")
        return

    fig = go.Figure()

    # 라인 차트
    fig.add_trace(go.Scatter(
        x=df['date'],
        y=df['profit_rate'],
        mode='lines+markers',
        name='수익률',
        line=dict(color='#4a9eff', width=2),
        marker=dict(size=6),
        fill='tozeroy',
        fillcolor='rgba(74, 158, 255, 0.2)'
    ))

    # 0% 기준선
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

    # 레이아웃
    fig.update_layout(
        title=dict(
            text=f'📈 일별 수익률 추이 (최근 {len(df)}일)',
            font=dict(size=18, color='white')
        ),
        xaxis_title='날짜',
        yaxis_title='수익률 (%)',
        template='plotly_dark',
        height=350,
        hovermode='x unified',
        showlegend=False
    )

    # Y축 포맷 (%)
    fig.update_yaxes(ticksuffix='%')

    st.plotly_chart(fig, use_container_width=True)


def format_currency(value):
    """통화 포맷"""
    if pd.isna(value):
        return "-"
    return f"{int(value):,}원"


def format_percent(value):
    """퍼센트 포맷"""
    if pd.isna(value):
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def format_price_diff(value):
    """가격 차이 포맷 (전일대비)"""
    if pd.isna(value) or value == 0:
        return "0"
    sign = "+" if value > 0 else ""
    return f"{sign}{int(value):,}"


def create_html_table(df):
    """DataFrame을 HTML 테이블로 변환 (정렬 완벽 제어)"""
    if df.empty:
        return "<p>💡 보유 종목이 없습니다.</p>"

    # 표시할 컬럼만 선택
    display_columns = ['증권사', '종목명', '수량', '평단가', '현재가', '전일대비', '등락률', '평가금액', '손익', '수익률']
    df_display = df[[col for col in display_columns if col in df.columns]].copy()

    # HTML 시작
    html = """
    <style>
        .custom-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
            background-color: #1e1e1e;
            color: #e0e0e0;
        }
        .custom-table thead th {
            background-color: #1a4d6f;
            color: white;
            padding: 12px 8px;
            text-align: center;
            border: 1px solid #3a3a3a;
            font-weight: bold;
        }
        .custom-table tbody tr {
            border-bottom: 1px solid #3a3a3a;
        }
        .custom-table tbody tr:nth-child(even) {
            background-color: #2a2a2a;
        }
        .custom-table tbody tr:hover {
            background-color: #333333;
        }
        .custom-table tbody td {
            padding: 10px 8px;
            border: 1px solid #3a3a3a;
        }
        .text-center { text-align: center !important; }
        .text-left { text-align: left !important; }
        .text-right { text-align: right !important; }
        .text-red { color: #ff4444; }
        .text-blue { color: #4488ff; }
    </style>
    <table class="custom-table">
        <thead>
            <tr>
    """

    # 헤더 추가
    for col in df_display.columns:
        html += f"<th>{col}</th>"
    html += "</tr></thead><tbody>"

    # 데이터 행 추가
    for idx, row in df_display.iterrows():
        html += "<tr>"
        for i, (col, value) in enumerate(row.items()):
            # 정렬 클래스 결정
            if i == 0:  # 증권사
                align_class = "text-center"
            elif i == 1:  # 종목명
                align_class = "text-left"
            else:  # 나머지
                align_class = "text-right"

            # 값 포맷팅
            if col == '수량':
                formatted_value = f"{int(value):,}" if pd.notna(value) and value != 0 else "-"
            elif col in ['평단가', '현재가']:
                formatted_value = f"{int(value):,}" if pd.notna(value) and value != 0 else "-"
            elif col == '전일대비':
                formatted_value = format_price_diff(value)
                # 색상 추가
                if pd.notna(value) and value > 0:
                    align_class += " text-red"
                elif pd.notna(value) and value < 0:
                    align_class += " text-blue"
            elif col == '등락률':
                formatted_value = format_percent(value)
                # 색상 추가
                if pd.notna(value) and value > 0:
                    align_class += " text-red"
                elif pd.notna(value) and value < 0:
                    align_class += " text-blue"
            elif col == '평가금액':
                formatted_value = format_currency(value)
            elif col == '손익':
                formatted_value = format_currency(value)
                # 색상 추가
                if pd.notna(value) and value > 0:
                    align_class += " text-red"
                elif pd.notna(value) and value < 0:
                    align_class += " text-blue"
            elif col == '수익률':
                formatted_value = format_percent(value)
                # 색상 추가
                if pd.notna(value) and value > 0:
                    align_class += " text-red"
                elif pd.notna(value) and value < 0:
                    align_class += " text-blue"
            else:
                formatted_value = str(value) if pd.notna(value) else "-"

            html += f'<td class="{align_class}">{formatted_value}</td>'
        html += "</tr>"

    html += "</tbody></table>"
    return html


def main():
    """메인 함수"""

    # 비밀번호 확인
    if not check_password():
        st.stop()

    # 헤더
    st.title("📊 포트폴리오 통합 모니터링")
    st.markdown("---")

    # 사이드바 - 새로고침 설정
    with st.sidebar:
        st.header("⚙️ 설정")

        auto_refresh = st.checkbox("자동 새로고침", value=False)
        if auto_refresh:
            refresh_interval = st.slider("새로고침 간격 (초)", 10, 300, 60)
            st.info(f"🔄 {refresh_interval}초마다 자동 새로고침")

        st.markdown("---")

        if st.button("🔄 수동 새로고침", use_container_width=True):
            st.rerun()

        if st.button("🚪 로그아웃", use_container_width=True):
            st.session_state["password_correct"] = False
            st.rerun()

        st.markdown("---")
        st.caption(f"마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # API 클라이언트 초기화
    with st.spinner("🔌 API 연결 중..."):
        kis_client, kiwoom_client, data_fetcher = init_clients()

    # ========================================
    # 1. 일별 수익률 차트 (키움)
    # ========================================
    st.subheader("📈 일별 수익률 추이")

    with st.spinner("📊 수익률 데이터 로딩 중..."):
        profit_df = get_kiwoom_daily_profit(kiwoom_client, days=30)
        create_profit_chart(profit_df)

    st.markdown("---")

    # ========================================
    # 2. 통합 요약
    # ========================================
    st.subheader("💰 통합 요약")

    col1, col2, col3, col4 = st.columns(4)

    with st.spinner("💼 보유종목 조회 중..."):
        # 한국투자 보유종목
        kis_df = get_kis_holdings(kis_client, data_fetcher)

        # 키움 보유종목
        kiwoom_df = get_kiwoom_holdings(kiwoom_client, data_fetcher)

        # 통합
        all_holdings = pd.concat([kis_df, kiwoom_df], ignore_index=True)

    # 메트릭 계산
    total_stocks = len(all_holdings)
    total_eval = all_holdings['평가금액'].sum() if '평가금액' in all_holdings.columns else 0
    total_profit = all_holdings['손익'].sum() if '손익' in all_holdings.columns else 0
    total_profit_rate = (total_profit / (total_eval - total_profit) * 100) if total_eval > 0 else 0

    # 메트릭 표시
    with col1:
        st.metric("보유 종목수", f"{total_stocks}개")

    with col2:
        st.metric("총 평가금액", format_currency(total_eval))

    with col3:
        profit_color = "normal" if total_profit >= 0 else "inverse"
        st.metric(
            "총 손익",
            format_currency(total_profit),
            delta=format_percent(total_profit_rate),
            delta_color=profit_color
        )

    with col4:
        # 키움 수익률 (최신)
        if not profit_df.empty:
            latest_rate = profit_df.iloc[-1]['profit_rate']
            st.metric("키움 수익률", format_percent(latest_rate))
        else:
            st.metric("키움 수익률", "-")

    st.markdown("---")

    # ========================================
    # 3. 증권사별 보유종목
    # ========================================
    st.subheader("💼 보유 종목")

    # 탭으로 증권사 구분
    tab1, tab2, tab3 = st.tabs(["📊 전체", "🏦 한국투자", "🏦 키움"])

    with tab1:
        st.markdown("##### 전체 보유 종목")
        if not all_holdings.empty:
            html_table = create_html_table(all_holdings)
            st.markdown(html_table, unsafe_allow_html=True)
        else:
            st.info("💡 보유 종목이 없습니다.")

    with tab2:
        st.markdown("##### 한국투자증권 보유 종목")
        if not kis_df.empty:
            html_table = create_html_table(kis_df)
            st.markdown(html_table, unsafe_allow_html=True)

            # 요약 정보
            kis_eval = kis_df['평가금액'].sum() if '평가금액' in kis_df.columns else 0
            kis_profit = kis_df['손익'].sum() if '손익' in kis_df.columns else 0

            st.markdown("<br>", unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                st.info(f"📊 종목수: {len(kis_df)}개")
            with col2:
                st.info(f"💰 평가금액: {format_currency(kis_eval)}")
        else:
            st.info("💡 보유 종목이 없습니다.")

    with tab3:
        st.markdown("##### 키움증권 보유 종목")
        if not kiwoom_df.empty:
            html_table = create_html_table(kiwoom_df)
            st.markdown(html_table, unsafe_allow_html=True)

            # 요약 정보
            st.markdown("<br>", unsafe_allow_html=True)
            st.info(f"📊 종목수: {len(kiwoom_df)}개")
        else:
            st.info("💡 보유 종목이 없습니다.")

    # 자동 새로고침
    if auto_refresh:
        import time
        time.sleep(refresh_interval)
        st.rerun()


if __name__ == "__main__":
    main()
