"""
실시간 주식 가격 모니터링 GUI 프로그램 (PyQt6)
상단: 키움 보유종목 모니터링
하단: trading_list.json 종목 모니터링
"""
import sys
import json
import logging
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel, QSpinBox, 
    QHeaderView, QCheckBox, QSplitter
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont
from data_fetcher import DataFetcher

# 키움 API 추가
try:
    from kiwoom_api_client import KiwoomAPIClient
    KIWOOM_AVAILABLE = True
except ImportError:
    KIWOOM_AVAILABLE = False
    logging.warning("⚠️ 키움 API를 불러올 수 없습니다. 보유종목 모니터링 비활성화")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RealTimeMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KAS v1.0.1 - 실시간 주식 모니터링 (보유종목 + 관심종목)")
        self.resize(1800, 1000)

        # 데이터 초기화
        self.data_fetcher = DataFetcher()
        self.stocks = []  # trading_list.json 종목
        self.holdings = []  # 키움 보유종목
        self.stock_data = {}
        
        # 키움 API 클라이언트 초기화
        self.kiwoom_client = None
        if KIWOOM_AVAILABLE:
            try:
                self.kiwoom_client = KiwoomAPIClient()
                logger.info("✅ 키움 API 클라이언트 초기화 완료")
            except Exception as e:
                logger.error(f"❌ 키움 API 초기화 실패: {e}")

        # UI 생성
        self.init_ui()

        # 종목 로드
        self.load_stocks()
        if self.kiwoom_client:
            self.load_holdings()

        # 타이머 설정 (60초)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(60000)

        # 초기 데이터 로드
        self.update_data()

        # 어두운 테마 적용
        self.apply_dark_theme()

    def init_ui(self):
        """UI 초기화"""
        # 메인 위젯
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)

        # 상단 컨트롤 패널
        control_layout = QHBoxLayout()

        # Start Trading 버튼
        self.start_btn = QPushButton("⏵ Start Trading")
        self.start_btn.setFixedHeight(30)
        self.start_btn.clicked.connect(self.toggle_auto_update)
        control_layout.addWidget(self.start_btn)

        # 수동 업데이트 버튼
        manual_update_btn = QPushButton("🔄 수동 업데이트")
        manual_update_btn.setFixedHeight(30)
        manual_update_btn.clicked.connect(self.update_data)
        control_layout.addWidget(manual_update_btn)
        
        # 키움 보유종목 새로고침 버튼
        if KIWOOM_AVAILABLE:
            refresh_holdings_btn = QPushButton("💼 보유종목 새로고침")
            refresh_holdings_btn.setFixedHeight(30)
            refresh_holdings_btn.clicked.connect(self.load_holdings)
            control_layout.addWidget(refresh_holdings_btn)

        # 업데이트 간격 설정
        control_layout.addWidget(QLabel("업데이트 간격(초):"))
        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setMinimum(10)
        self.interval_spinbox.setMaximum(600)
        self.interval_spinbox.setValue(60)
        self.interval_spinbox.valueChanged.connect(self.update_interval_changed)
        control_layout.addWidget(self.interval_spinbox)

        # 마지막 업데이트 시간
        self.last_update_label = QLabel("마지막 업데이트: -")
        control_layout.addWidget(self.last_update_label)
        control_layout.addStretch()

        main_layout.addLayout(control_layout)

        # =================================================================
        # 상단: 키움 보유종목 테이블
        # =================================================================
        holdings_label = QLabel("💼 키움 보유종목")
        holdings_label.setFont(QFont("맑은 고딕", 12, QFont.Weight.Bold))
        main_layout.addWidget(holdings_label)
        
        self.holdings_table = QTableWidget()
        holdings_columns = [
            "계좌", "종목코드", "종목명", "보유수량", "평단가",
            "현재가", "전일종가", "전일대비", "등락률", "평가금액", "손익", "수익률", "20일평균", "상태"
        ]
        self.holdings_table.setColumnCount(len(holdings_columns))
        self.holdings_table.setHorizontalHeaderLabels(holdings_columns)
        
        # 컬럼 너비 설정
        self.holdings_table.setColumnWidth(0, 80)   # 계좌
        self.holdings_table.setColumnWidth(1, 80)   # 종목코드
        self.holdings_table.setColumnWidth(2, 250)  # 종목명 (넓게)
        self.holdings_table.setColumnWidth(3, 80)   # 보유수량
        self.holdings_table.setColumnWidth(4, 100)  # 평단가
        self.holdings_table.setColumnWidth(5, 100)  # 현재가
        self.holdings_table.setColumnWidth(6, 100)  # 전일종가
        self.holdings_table.setColumnWidth(7, 100)  # 전일대비
        self.holdings_table.setColumnWidth(8, 80)   # 등락률
        self.holdings_table.setColumnWidth(9, 120)  # 평가금액
        self.holdings_table.setColumnWidth(10, 120) # 손익
        self.holdings_table.setColumnWidth(11, 80)  # 수익률
        self.holdings_table.setColumnWidth(12, 100) # 20일평균
        self.holdings_table.setColumnWidth(13, 80)  # 상태
        
        self.holdings_table.setAlternatingRowColors(True)
        self.holdings_table.verticalHeader().setDefaultSectionSize(35)
        self.holdings_table.verticalHeader().setVisible(False)
        self.holdings_table.setMaximumHeight(300)  # 최대 높이 제한
        
        main_layout.addWidget(self.holdings_table)
        
        # 보유종목 상태바
        holdings_status_layout = QHBoxLayout()
        self.holdings_status_label = QLabel("보유종목: 0개 | 총평가금액: 0원 | 총손익: 0원")
        holdings_status_layout.addWidget(self.holdings_status_label)
        holdings_status_layout.addStretch()
        main_layout.addLayout(holdings_status_layout)

        # =================================================================
        # 하단: trading_list.json 관심종목 테이블 (기존 테이블)
        # =================================================================
        watchlist_label = QLabel("📋 관심종목 (trading_list.json)")
        watchlist_label.setFont(QFont("맑은 고딕", 12, QFont.Weight.Bold))
        main_layout.addWidget(watchlist_label)
        
        self.table = QTableWidget()
        columns = [
            "선택", "종목코드", "종목명", "현재가", "20일평균", 
            "전일종가", "전일대비", "등락률", "거래량", "점수", "신호", "상태"
        ]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        
        # 컬럼 너비 설정 (기존과 동일)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 100)
        self.table.setColumnWidth(6, 100)
        self.table.setColumnWidth(7, 80)
        self.table.setColumnWidth(8, 100)
        self.table.setColumnWidth(9, 50)
        self.table.setColumnWidth(10, 200)
        self.table.setColumnWidth(11, 80)

        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(35)
        self.table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.table)

        # 하단 상태바 (관심종목)
        status_layout = QHBoxLayout()
        self.status_label = QLabel("종목 수: 0 | 상승: 0 | 하락: 0 | 보합: 0")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        main_layout.addLayout(status_layout)

    def apply_dark_theme(self):
        """어두운 테마 적용"""
        dark_stylesheet = """
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #e0e0e0;
                font-family: "맑은 고딕", Arial;
                font-size: 14pt;
            }
            QPushButton {
                background-color: #3a7ca5;
                color: white;
                border: none;
                padding: 5px 15px;
                border-radius: 3px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4a8cb5;
            }
            QPushButton:pressed {
                background-color: #2a6c95;
            }
            QTableWidget {
                background-color: #252525;
                alternate-background-color: #2a2a2a;
                gridline-color: #3a3a3a;
                color: #e0e0e0;
                border: 1px solid #3a3a3a;
            }
            QTableWidget::item {
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #3a5a7a;
            }
            QHeaderView::section {
                background-color: #1a4d6f;
                color: white;
                padding: 5px;
                border: 1px solid #3a3a3a;
                font-weight: bold;
            }
            QLabel {
                color: #e0e0e0;
            }
            QSpinBox {
                background-color: #333333;
                color: #e0e0e0;
                border: 1px solid #555555;
                padding: 3px;
            }
        """
        self.setStyleSheet(dark_stylesheet)

    def load_stocks(self):
        """trading_list.json에서 종목 로드"""
        try:
            with open("trading_list.json", "r", encoding="utf-8") as f:
                self.stocks = json.load(f)

            logger.info(f"✅ {len(self.stocks)}개 종목 로드 완료")

            # 테이블 행 수 설정
            self.table.setRowCount(len(self.stocks))

            # 종목 기본 정보 설정
            for i, stock in enumerate(self.stocks):
                # 체크박스
                checkbox = QCheckBox()
                checkbox.setChecked(True)
                checkbox_widget = QWidget()
                checkbox_layout = QHBoxLayout(checkbox_widget)
                checkbox_layout.addWidget(checkbox)
                checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                self.table.setCellWidget(i, 0, checkbox_widget)

                # 종목코드
                self.table.setItem(i, 1, QTableWidgetItem(stock.get("code", "")))

                # 종목명
                item_name = QTableWidgetItem(stock.get("name", ""))
                item_name.setFont(QFont("맑은 고딕", 14, QFont.Weight.Bold))
                self.table.setItem(i, 2, item_name)

                # 전일종가 (저장된 가격)
                saved_price = stock.get("price", 0)
                item_saved = QTableWidgetItem(f"{saved_price:,}")
                item_saved.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(i, 5, item_saved)

                # 점수
                item_score = QTableWidgetItem(str(stock.get("score", 0)))
                item_score.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, 9, item_score)

                # 신호
                signals = ", ".join(stock.get("signals", []))
                item_signal = QTableWidgetItem(signals)
                self.table.setItem(i, 10, item_signal)

                # 나머지 셀 초기화
                for col in [3, 4, 6, 7, 8, 11]:
                    item = QTableWidgetItem("-")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(i, col, item)

        except FileNotFoundError:
            logger.error("❌ trading_list.json 파일을 찾을 수 없습니다.")
            self.stocks = []
        except json.JSONDecodeError as e:
            logger.error(f"❌ trading_list.json 파일 형식이 올바르지 않습니다: {e}")
            self.stocks = []
    
    def load_holdings(self):
        """키움 보유종목 로드"""
        if not self.kiwoom_client:
            return
        
        try:
            logger.info("📊 키움 보유종목 조회 중...")
            
            # 전체 활성 계좌의 보유종목 조회
            df = self.kiwoom_client.get_holdings_all()
            
            if df.empty:
                logger.info("💡 보유종목이 없습니다.")
                self.holdings = []
                self.holdings_table.setRowCount(0)
                return
            
            # DataFrame을 딕셔너리 리스트로 변환
            self.holdings = df.to_dict('records')
            
            logger.info(f"✅ 키움 보유종목 {len(self.holdings)}개 로드 완료")
            
            # 테이블 행 수 설정
            self.holdings_table.setRowCount(len(self.holdings))
            
            # 보유종목 기본 정보 설정
            for i, holding in enumerate(self.holdings):
                # 계좌 (description 표시)
                account_description = holding.get('account_description', holding.get('account_alias', ''))
                item_account = QTableWidgetItem(account_description)
                item_account.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.holdings_table.setItem(i, 0, item_account)
                
                # 종목코드
                self.holdings_table.setItem(i, 1, QTableWidgetItem(holding.get("stock_code", "")))

                # 종목명
                item_name = QTableWidgetItem(holding.get("stock_name", ""))
                item_name.setFont(QFont("맑은 고딕", 14, QFont.Weight.Bold))
                self.holdings_table.setItem(i, 2, item_name)
                
                # 보유수량
                quantity = holding.get("quantity", 0)
                item_qty = QTableWidgetItem(f"{quantity:,}")
                item_qty.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.holdings_table.setItem(i, 3, item_qty)
                
                # 평단가
                avg_price = holding.get("avg_price", 0)
                item_avg = QTableWidgetItem(f"{avg_price:,.0f}")
                item_avg.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.holdings_table.setItem(i, 4, item_avg)
                
                # 나머지 셀 초기화
                for col in [5, 6, 7, 8, 9, 10, 11, 12, 13]:
                    item = QTableWidgetItem("-")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.holdings_table.setItem(i, col, item)
                    
        except Exception as e:
            logger.error(f"❌ 보유종목 로드 실패: {e}")
            self.holdings = []

    def update_data(self):
        """실시간 데이터 업데이트 (보유종목 + 관심종목)"""
        logger.info("📊 가격 업데이트 시작...")
        
        # 1. 보유종목 업데이트
        self.update_holdings_data()
        
        # 2. 관심종목 업데이트 (기존 로직)
        self.update_watchlist_data()
        
        # 마지막 업데이트 시간
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_update_label.setText(f"마지막 업데이트: {current_time}")
        
        logger.info("✅ 가격 업데이트 완료")
    
    def update_holdings_data(self):
        """보유종목 데이터 업데이트"""
        if not self.holdings:
            return
        
        total_eval_amount = 0
        total_profit_loss = 0
        
        for i, holding in enumerate(self.holdings):
            code = holding.get("stock_code")
            avg_price = holding.get("avg_price", 0)
            quantity = holding.get("quantity", 0)
            
            # 현재가 및 전일종가 조회
            result = self.data_fetcher.get_current_price(code)
            if result and len(result) >= 3:
                current_price, _, prev_close = result
            else:
                current_price = None
                prev_close = None
            
            # 20일 평균가 계산
            ma20_price = None
            try:
                df_20d = self.data_fetcher.get_period_price_data(code, days=20)
                if df_20d is not None and not df_20d.empty and len(df_20d) >= 20:
                    ma20_price = df_20d['stck_clpr'].tail(20).mean()
            except Exception as e:
                logger.debug(f"⚠️ {code}: 20일평균 계산 오류: {e}")
            
            if current_price:
                # 현재가
                item_price = QTableWidgetItem(f"{int(current_price):,}")
                item_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item_price.setFont(QFont("맑은 고딕", 14, QFont.Weight.Bold))

                # 전일 대비 계산
                if prev_close and prev_close > 0:
                    price_diff = int(current_price - prev_close)
                    price_change_pct = (price_diff / prev_close * 100)

                    # 전일종가
                    item_prev = QTableWidgetItem(f"{int(prev_close):,}")
                    item_prev.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.holdings_table.setItem(i, 6, item_prev)

                    # 전일대비 색상 설정
                    if price_diff > 0:
                        day_color = QColor("#ff4444")  # 빨간색
                        diff_str = f"+{price_diff:,}"
                        pct_str = f"+{price_change_pct:.2f}%"
                    elif price_diff < 0:
                        day_color = QColor("#4488ff")  # 파란색
                        diff_str = f"{price_diff:,}"
                        pct_str = f"{price_change_pct:.2f}%"
                    else:
                        day_color = QColor("#e0e0e0")
                        diff_str = "0"
                        pct_str = "0.00%"

                    # 전일대비
                    item_diff = QTableWidgetItem(diff_str)
                    item_diff.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    item_diff.setForeground(day_color)
                    self.holdings_table.setItem(i, 7, item_diff)

                    # 등락률
                    item_pct = QTableWidgetItem(pct_str)
                    item_pct.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    item_pct.setForeground(day_color)
                    self.holdings_table.setItem(i, 8, item_pct)

                    # 현재가에도 색상 적용
                    item_price.setForeground(day_color)

                self.holdings_table.setItem(i, 5, item_price)

                # 평가금액
                eval_amount = current_price * quantity
                item_eval = QTableWidgetItem(f"{int(eval_amount):,}")
                item_eval.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.holdings_table.setItem(i, 9, item_eval)

                # 손익 (평단가 대비)
                profit_loss = eval_amount - (avg_price * quantity)
                profit_rate = (profit_loss / (avg_price * quantity) * 100) if avg_price > 0 else 0

                # 손익 색상 설정
                if profit_loss > 0:
                    pl_color = QColor("#ff4444")  # 빨간색 (수익)
                    pl_str = f"+{int(profit_loss):,}"
                    pr_str = f"+{profit_rate:.2f}%"
                    status = "수익"
                elif profit_loss < 0:
                    pl_color = QColor("#4488ff")  # 파란색 (손실)
                    pl_str = f"{int(profit_loss):,}"
                    pr_str = f"{profit_rate:.2f}%"
                    status = "손실"
                else:
                    pl_color = QColor("#e0e0e0")
                    pl_str = "0"
                    pr_str = "0.00%"
                    status = "보합"

                # 손익
                item_pl = QTableWidgetItem(pl_str)
                item_pl.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item_pl.setForeground(pl_color)
                self.holdings_table.setItem(i, 10, item_pl)

                # 수익률
                item_pr = QTableWidgetItem(pr_str)
                item_pr.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item_pr.setForeground(pl_color)
                self.holdings_table.setItem(i, 11, item_pr)

                # 20일평균
                if ma20_price:
                    item_ma20 = QTableWidgetItem(f"{ma20_price:,.0f}")
                    item_ma20.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    item_ma20.setForeground(QColor("#ffa500"))
                    self.holdings_table.setItem(i, 12, item_ma20)

                # 상태
                item_status = QTableWidgetItem(status)
                item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.holdings_table.setItem(i, 13, item_status)

                # 합계 계산
                total_eval_amount += eval_amount
                total_profit_loss += profit_loss
            else:
                # 조회 실패
                item_status = QTableWidgetItem("대기중")
                item_status.setForeground(QColor("#888888"))
                self.holdings_table.setItem(i, 13, item_status)
        
        # 보유종목 상태 업데이트
        total_profit_rate = (total_profit_loss / (total_eval_amount - total_profit_loss) * 100) if (total_eval_amount - total_profit_loss) > 0 else 0
        self.holdings_status_label.setText(
            f"보유종목: {len(self.holdings)}개 | "
            f"총평가금액: {int(total_eval_amount):,}원 | "
            f"총손익: {int(total_profit_loss):+,}원 ({total_profit_rate:+.2f}%)"
        )

    def update_watchlist_data(self):
        """관심종목 데이터 업데이트 (기존 로직)"""
        if not self.stocks:
            return

        up_count = 0
        down_count = 0
        same_count = 0

        for i, stock in enumerate(self.stocks):
            code = stock.get("code")
            saved_price = stock.get("price", 0)

            # 실시간 가격 조회
            result = self.data_fetcher.get_current_price(code)
            if result and len(result) >= 2:
                current_price = result[0]
                current_volume = result[1]
            else:
                current_price = None
                current_volume = None

            # 20일 평균가 계산
            ma20_price = None
            try:
                df_20d = self.data_fetcher.get_period_price_data(code, days=20)
                if df_20d is not None and not df_20d.empty and len(df_20d) >= 20:
                    ma20_price = df_20d['stck_clpr'].tail(20).mean()
            except Exception as e:
                logger.debug(f"⚠️ {code}: 20일평균 계산 오류: {e}")

            if current_price and current_volume:
                # 현재가
                item_price = QTableWidgetItem(f"{int(current_price):,}")
                item_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item_price.setFont(QFont("맑은 고딕", 14, QFont.Weight.Bold))

                # 전일대비
                price_diff = int(current_price - saved_price)
                price_change_pct = (price_diff / saved_price * 100) if saved_price > 0 else 0

                # 색상 설정
                if price_diff > 0:
                    color = QColor("#ff4444")
                    diff_str = f"+{price_diff:,}"
                    pct_str = f"+{price_change_pct:.2f}%"
                    status = "Active"
                    up_count += 1
                elif price_diff < 0:
                    color = QColor("#4488ff")
                    diff_str = f"{price_diff:,}"
                    pct_str = f"{price_change_pct:.2f}%"
                    status = "Active"
                    down_count += 1
                else:
                    color = QColor("#e0e0e0")
                    diff_str = "0"
                    pct_str = "0.00%"
                    status = "Waiting"
                    same_count += 1

                item_price.setForeground(color)
                self.table.setItem(i, 3, item_price)

                # 20일평균
                if ma20_price:
                    item_ma20 = QTableWidgetItem(f"{ma20_price:,.0f}")
                    item_ma20.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    item_ma20.setForeground(QColor("#ffa500"))
                    self.table.setItem(i, 4, item_ma20)

                # 전일대비
                item_diff = QTableWidgetItem(diff_str)
                item_diff.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item_diff.setForeground(color)
                self.table.setItem(i, 6, item_diff)

                # 등락률
                item_pct = QTableWidgetItem(pct_str)
                item_pct.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item_pct.setForeground(color)
                self.table.setItem(i, 7, item_pct)

                # 거래량
                item_vol = QTableWidgetItem(f"{current_volume:,}")
                item_vol.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(i, 8, item_vol)

                # 상태
                item_status = QTableWidgetItem(status)
                item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(i, 11, item_status)

            else:
                # API 조회 실패
                item_status = QTableWidgetItem("Waiting...")
                item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item_status.setForeground(QColor("#888888"))
                self.table.setItem(i, 11, item_status)

        # 상태 요약
        self.status_label.setText(
            f"종목 수: {len(self.stocks)} | 상승: {up_count} | 하락: {down_count} | 보합: {same_count}"
        )

    def toggle_auto_update(self):
        """자동 업데이트 토글"""
        if self.timer.isActive():
            self.timer.stop()
            self.start_btn.setText("⏵ Start Trading")
            logger.info("⏸️ 자동 업데이트 중지")
        else:
            self.timer.start()
            self.start_btn.setText("⏸ Stop Trading")
            logger.info("▶️ 자동 업데이트 시작")

    def update_interval_changed(self, value):
        """업데이트 간격 변경"""
        self.timer.setInterval(value * 1000)
        logger.info(f"✅ 업데이트 간격 변경: {value}초")


def main():
    app = QApplication(sys.argv)
    window = RealTimeMonitor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
