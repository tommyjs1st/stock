import sys
import random # 가상 데이터를 만들기 위해 추가
from PyQt6.QtWidgets import QApplication, QMainWindow, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PyQt6.QtCore import QTimer # 실시간 타이머 추가

class RealTimeGrid(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KAS v1.0.0 실시간 그리드")
        self.resize(600, 400)

        # 1. 그리드 설정
        self.table = QTableWidget(5, 4)
        self.table.setHorizontalHeaderLabels(["종목명", "현재가", "수익률", "상태"])
        
        # 종목명 고정
        self.stocks = ["삼성전자", "기아", "SK하이닉스", "카카오", "NAVER"]
        for i, name in enumerate(self.stocks):
            self.table.setItem(i, 0, QTableWidgetItem(name))

        # 2. 타이머 설정 (실시간 엔진)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data) # 시간이 다 되면 update_data 함수 실행
        self.timer.start(1000) # 1000ms = 1초마다 갱신

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.setStyleSheet("QMainWindow { background-color: #2b2b2b; } QTableWidget { background-color: #333333; color: white; }")

    def update_data(self):
        """1초마다 호출되어 데이터를 갱신하는 함수"""
        for i in range(len(self.stocks)):
            # 가상의 주가 생성
            price = random.randint(50000, 150000)
            rate = random.uniform(-3, 3)
            
            # 표 갱신
            self.table.setItem(i, 1, QTableWidgetItem(f"{price:,}"))
            self.table.setItem(i, 2, QTableWidgetItem(f"{rate:+.2f}%"))
            
            # 수익률에 따라 색상 변경 (안티그래비티 스타일)
            item = self.table.item(i, 2)
            if rate > 0:
                item.setForeground(sys.modules['PyQt6.QtGui'].QColor("red"))
            else:
                item.setForeground(sys.modules['PyQt6.QtGui'].QColor("dodgerblue"))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RealTimeGrid()
    window.show()
    sys.exit(app.exec())
