"""
실시간 주식 가격 모니터링 GUI 프로그램 (PyQt6)
trading_list.json 파일의 종목을 그리드 형태로 실시간 모니터링
"""
import sys
import json
import logging
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QHBoxLayout, QWidget, QPushButton, QLabel, QSpinBox, QHeaderView, QCheckBox
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont
from data_fetcher import DataFetcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RealTimeMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KAS v1.0.0 - 실시간 주식 모니터링")
        self.resize(1600, 800)

        # 데이터 초기화
        self.data_fetcher = DataFetcher()
        self.stocks = []
        self.stock_data = {}  # 종목별 데이터 캐시

        # UI 생성
        self.init_ui()

        # 종목 로드
        self.load_stocks()

        # 타이머 설정 (분단위 업데이트 - 60초)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(60000)  # 60000ms = 1분

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

        # 업데이트 간격 설정
        control_layout.addWidget(QLabel("업데이트 간격(초):"))
        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setMinimum(10)
        self.interval_spinbox.setMaximum(600)
        self.interval_spinbox.setValue(60)
        self.interval_spinbox.setSingleStep(10)
        self.interval_spinbox.valueChanged.connect(self.update_interval_changed)
        control_layout.addWidget(self.interval_spinbox)

        # 마지막 업데이트 시간
        control_layout.addStretch()
        self.last_update_label = QLabel("마지막 업데이트: -")
        control_layout.addWidget(self.last_update_label)

        main_layout.addLayout(control_layout)

        # 테이블 위젯
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "선택", "종목코드", "종목명", "현재가", "20일평균", "전일종가",
            "전일대비", "등락률", "거래량", "점수", "신호", "상태"
        ])

        # 헤더 설정
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # 선택
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # 종목코드
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)  # 종목명
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # 현재가
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # 20일평균
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)  # 전일종가
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # 전일대비
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)  # 등락률
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)  # 거래량
        header.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)  # 점수
        header.setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)  # 신호
        header.setSectionResizeMode(11, QHeaderView.ResizeMode.Fixed)  # 상태

        # 컬럼 너비 설정
        self.table.setColumnWidth(0, 50)   # 선택
        self.table.setColumnWidth(1, 80)   # 종목코드
        self.table.setColumnWidth(2, 150)  # 종목명
        self.table.setColumnWidth(3, 100)  # 현재가
        self.table.setColumnWidth(4, 100)  # 20일평균
        self.table.setColumnWidth(5, 100)  # 전일종가
        self.table.setColumnWidth(6, 100)  # 전일대비
        self.table.setColumnWidth(7, 80)   # 등락률
        self.table.setColumnWidth(8, 120)  # 거래량
        self.table.setColumnWidth(9, 50)   # 점수
        self.table.setColumnWidth(11, 80)  # 상태

        # 행 높이 설정
        self.table.verticalHeader().setDefaultSectionSize(35)
        self.table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.table)

        # 하단 상태바
        status_layout = QHBoxLayout()
        self.status_label = QLabel("종목 수: 0 | 상승: 0 | 하락: 0 | 보합: 0")
        status_layout.addWidget(self.status_label)
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

                # 나머지 셀 초기화 (현재가, 20일평균, 전일대비, 등락률, 거래량, 상태)
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

    def update_data(self):
        """실시간 데이터 업데이트"""
        if not self.stocks:
            return

        logger.info("📊 가격 업데이트 시작...")

        up_count = 0
        down_count = 0
        same_count = 0

        for i, stock in enumerate(self.stocks):
            code = stock.get("code")
            saved_price = stock.get("price", 0)

            # 실시간 가격 조회
            current_price, current_volume = self.data_fetcher.get_current_price(code)

            # 20일 평균가 계산
            ma20_price = None
            try:
                df_20d = self.data_fetcher.get_period_price_data(code, days=20)
                if df_20d is not None and not df_20d.empty and len(df_20d) >= 20:
                    ma20_price = df_20d['stck_clpr'].tail(20).mean()
            except Exception as e:
                logger.debug(f"⚠️ {code}: 20일평균 계산 오류: {e}")

            if current_price and current_volume:
                # 현재가 (소수점 제거)
                item_price = QTableWidgetItem(f"{int(current_price):,}")
                item_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item_price.setFont(QFont("맑은 고딕", 14, QFont.Weight.Bold))

                # 전일대비
                price_diff = int(current_price - saved_price)
                price_change_pct = (price_diff / saved_price * 100) if saved_price > 0 else 0

                # 색상 설정
                if price_diff > 0:
                    color = QColor("#ff4444")  # 빨간색 (상승)
                    diff_str = f"+{price_diff:,}"
                    pct_str = f"+{price_change_pct:.2f}%"
                    status = "Active"
                    up_count += 1
                elif price_diff < 0:
                    color = QColor("#4488ff")  # 파란색 (하락)
                    diff_str = f"{price_diff:,}"
                    pct_str = f"{price_change_pct:.2f}%"
                    status = "Active"
                    down_count += 1
                else:
                    color = QColor("#e0e0e0")  # 회색 (보합)
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
                    item_ma20.setForeground(QColor("#ffa500"))  # 주황색
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
                # API 조회 실패 시
                item_status = QTableWidgetItem("Waiting...")
                item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item_status.setForeground(QColor("#888888"))
                self.table.setItem(i, 11, item_status)

        # 마지막 업데이트 시간
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.last_update_label.setText(f"마지막 업데이트: {current_time}")

        # 상태 요약
        self.status_label.setText(
            f"종목 수: {len(self.stocks)} | 상승: {up_count} | 하락: {down_count} | 보합: {same_count}"
        )

        logger.info("✅ 가격 업데이트 완료")

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
        self.timer.setInterval(value * 1000)  # 초를 밀리초로 변환
        logger.info(f"✅ 업데이트 간격 변경: {value}초")


def main():
    app = QApplication(sys.argv)
    window = RealTimeMonitor()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
