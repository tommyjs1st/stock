"""
분봉 차트 뷰어
특정 날짜의 모든 종목 분봉 종가를 시가 기준 등락률(%)로 정규화하여
하나의 차트에 오버레이로 표시

사용법:
    python minute_chart_viewer.py
"""
import sys
import os
import yaml
import logging
from datetime import datetime, date
from typing import Dict, List, Optional

import pymysql
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QDateEdit, QLabel, QStatusBar, QSizePolicy
)
from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt6.QtGui import QFont

import matplotlib
matplotlib.use('QtAgg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.ticker as mticker

# 한글 폰트 설정
plt.rcParams['font.family'] = ['AppleGothic', 'Malgun Gothic', 'NanumGothic', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


# ────────────────────────────────────────────
# 색상 팔레트 (종목 수에 따라 순환 사용)
# ────────────────────────────────────────────
COLORS = [
    '#E74C3C', '#3498DB', '#2ECC71', '#F39C12', '#9B59B6',
    '#1ABC9C', '#E67E22', '#2980B9', '#27AE60', '#8E44AD',
    '#16A085', '#D35400', '#C0392B', '#2471A3', '#1E8449',
    '#6C3483', '#117A65', '#A04000', '#78281F', '#1A5276',
    '#F0B27A', '#82E0AA', '#85C1E9', '#C39BD3', '#F9E79F',
]


# ────────────────────────────────────────────
# DB 로더 (별도 스레드)
# ────────────────────────────────────────────
class DataLoader(QThread):
    """백그라운드 DB 조회 스레드"""
    # {stock_code: {'name': str, 'prev_close': int|None, 'data': [{'dt': datetime, 'close': int}]}}
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, db_config: dict, trade_date: date):
        super().__init__()
        self.db_config = db_config
        self.trade_date = trade_date

    def run(self):
        conn = None
        try:
            conn = pymysql.connect(
                host=self.db_config.get('host', 'localhost'),
                port=self.db_config.get('port', 3306),
                user=self.db_config['user'],
                password=self.db_config['password'],
                database=self.db_config['database'],
                charset=self.db_config.get('charset', 'utf8mb4'),
                cursorclass=pymysql.cursors.DictCursor,
            )
            cursor = conn.cursor()

            # 1) 종목명 조회
            cursor.execute("SELECT stock_code, stock_name FROM stock_info")
            name_map = {r['stock_code']: r['stock_name'] for r in cursor.fetchall()}

            # 2) 전날 종가 조회 (daily_stock_prices에서 조회일 직전 거래일)
            prev_close_sql = """
                SELECT stock_code, close_price
                FROM daily_stock_prices
                WHERE trade_date = (
                    SELECT MAX(trade_date)
                    FROM daily_stock_prices
                    WHERE trade_date < %s
                )
            """
            cursor.execute(prev_close_sql, (self.trade_date,))
            prev_close_map = {r['stock_code']: int(r['close_price'])
                              for r in cursor.fetchall() if r['close_price']}

            # 3) 분봉 데이터 조회
            sql = """
                SELECT
                    stock_code,
                    trade_datetime,
                    close_price
                FROM minute_stock_prices
                WHERE DATE(trade_datetime) = %s
                  AND close_price IS NOT NULL
                  AND close_price > 0
                ORDER BY stock_code, trade_datetime ASC
            """
            cursor.execute(sql, (self.trade_date,))
            rows = cursor.fetchall()

            # 종목별로 그룹핑
            result: Dict[str, dict] = {}
            for row in rows:
                code = row['stock_code']
                if code not in result:
                    result[code] = {
                        'name': name_map.get(code, code),
                        'prev_close': prev_close_map.get(code),  # 전날 종가 (없으면 None)
                        'data': []
                    }
                result[code]['data'].append({
                    'dt': row['trade_datetime'],
                    'close': int(row['close_price'])
                })

            self.finished.emit(result)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            if conn:
                conn.close()


# ────────────────────────────────────────────
# matplotlib 캔버스
# ────────────────────────────────────────────
class ChartCanvas(FigureCanvas):
    """분봉 오버레이 차트 캔버스"""

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(14, 8), facecolor='#1C1C2E')
        super().__init__(self.fig)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._setup_axes()
        self._annotation = None   # 호버 툴팁 (set_visible 방식으로 관리)

    def _setup_axes(self):
        self.fig.clear()
        self._annotation = None   # 차트 재생성 시 annotation 초기화
        self.fig.subplots_adjust(left=0.07, right=0.75, top=0.93, bottom=0.08)
        self.ax = self.fig.add_subplot(111, facecolor='#1C1C2E')
        self.ax.set_facecolor('#1C1C2E')
        self.ax.tick_params(colors='#CCCCCC', labelsize=9)
        for spine in self.ax.spines.values():
            spine.set_edgecolor('#444444')
        self.ax.grid(True, color='#2E2E42', linewidth=0.5, alpha=0.7)
        self.ax.axhline(y=0, color='#888888', linewidth=1.0, linestyle='--', alpha=0.8)
        self.ax.set_ylabel('등락률 (%)', color='#CCCCCC', fontsize=10)
        self.ax.set_title('분봉 등락률 비교', color='#FFFFFF', fontsize=13, pad=12)

    def plot(self, stock_data: Dict[str, dict], trade_date: date):
        """
        stock_data: {code: {'name': str, 'prev_close': int|None,
                             'data': [{'dt': datetime, 'close': int}]}}
        등락률 기준: 전날 종가 (없으면 당일 첫 번째 종가로 대체)
        """
        self._setup_axes()

        if not stock_data:
            self.ax.set_title('데이터 없음', color='#FF6B6B', fontsize=13)
            self.draw()
            return

        self._lines = {}
        self._stock_data = stock_data

        date_str = trade_date.strftime('%Y년 %m월 %d일')
        self.ax.set_title(f'{date_str}  분봉 등락률 비교  ({len(stock_data)}개 종목)',
                          color='#FFFFFF', fontsize=13, pad=12)

        all_dts = []  # x축 범위 계산용

        for idx, (code, info) in enumerate(stock_data.items()):
            data = info['data']
            if len(data) < 2:
                continue

            dts = [d['dt'] for d in data]
            closes = [d['close'] for d in data]
            all_dts.extend(dts)

            # ── 전날 종가 기준 등락률 계산 ──
            # 전날 종가가 있으면 사용, 없으면 당일 첫 번째 종가로 대체
            base = info.get('prev_close') or closes[0]
            if base == 0:
                continue
            pcts = [(c - base) / base * 100 for c in closes]

            color = COLORS[idx % len(COLORS)]
            name = info['name']

            line, = self.ax.plot(
                dts, pcts,
                color=color,
                linewidth=1.4,
                label=f"{name}({code})",
                alpha=0.85,
                picker=5
            )
            self._lines[code] = (line, name, dts, pcts)

            # 마지막 값 레이블
            last_pct = pcts[-1]
            self.ax.annotate(
                f"{last_pct:+.2f}%",
                xy=(dts[-1], last_pct),
                xytext=(4, 0),
                textcoords='offset points',
                color=color,
                fontsize=7,
                va='center',
                alpha=0.9
            )

        # ── X축 범위: 데이터 실제 범위 기준, 양쪽 여백 추가 ──
        if all_dts:
            import matplotlib.dates as mdates_mod
            from datetime import timedelta
            x_min = min(all_dts) - timedelta(minutes=5)
            x_max = max(all_dts) + timedelta(minutes=20)  # 오른쪽 레이블 여백
            self.ax.set_xlim(x_min, x_max)

        # X축 시간 포맷 (1시간 단위 눈금)
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        self.ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        # 30분 단위 보조 눈금
        self.ax.xaxis.set_minor_locator(mdates.MinuteLocator(byminute=[30]))
        plt.setp(self.ax.xaxis.get_majorticklabels(), rotation=0, ha='center')

        # Y축 % 단위
        self.ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f%%'))

        # 범례: 오른쪽 외부 배치 → 차트 영역 최대 활용
        handles, labels = self.ax.get_legend_handles_labels()
        if handles:
            ncol = 1 if len(handles) <= 20 else 2
            self.ax.legend(
                handles, labels,
                loc='upper left',
                bbox_to_anchor=(1.01, 1.0),
                fontsize=7,
                framealpha=0.5,
                facecolor='#2A2A3E',
                edgecolor='#555555',
                labelcolor='#CCCCCC',
                ncol=ncol,
                handlelength=1.2,
                handletextpad=0.4,
                borderpad=0.6,
                columnspacing=0.8,
            )
            # 범례가 오른쪽 외부에 있으므로 여백 조정
            n = len(handles)
            legend_width = 0.18 if n <= 15 else 0.28
            self.fig.subplots_adjust(left=0.06, right=1.0 - legend_width,
                                     top=0.93, bottom=0.08)
        else:
            self.fig.subplots_adjust(left=0.06, right=0.97, top=0.93, bottom=0.08)

        # 호버 이벤트 연결
        self.fig.canvas.mpl_connect('motion_notify_event', self._on_hover)

        self.draw()

    def _on_hover(self, event):
        """마우스 호버 시 해당 시점 툴팁 표시"""
        if event.inaxes != self.ax or not hasattr(self, '_lines'):
            if self._annotation:
                self._annotation.set_visible(False)
                self.draw_idle()
            return

        # 가장 가까운 라인 찾기
        min_dist = float('inf')
        closest = None
        for code, (line, name, dts, pcts) in self._lines.items():
            if not dts:
                continue
            # x 위치에서 가장 가까운 인덱스
            x_num = mdates.date2num(dts)
            if len(x_num) == 0:
                continue
            diffs = [abs(x_num[i] - event.xdata) for i in range(len(x_num))]
            i_min = diffs.index(min(diffs))
            dist = abs(pcts[i_min] - event.ydata) if event.ydata is not None else float('inf')
            if dist < min_dist:
                min_dist = dist
                closest = (name, code, dts[i_min], pcts[i_min])

        if closest and min_dist < 1.5:
            name, code, dt, pct = closest
            text = f"{name}({code})\n{dt.strftime('%H:%M')}  {pct:+.2f}%"
            if self._annotation is None:
                # 최초 생성 (숨김 상태)
                self._annotation = self.ax.annotate(
                    text,
                    xy=(dt, pct),
                    xytext=(10, 10),
                    textcoords='offset points',
                    fontsize=8,
                    color='white',
                    bbox=dict(boxstyle='round,pad=0.4', fc='#2A2A3E', ec='#888888', alpha=0.9),
                    zorder=10,
                    visible=False,
                )
            # 위치·텍스트 갱신 후 표시
            self._annotation.set_text(text)
            self._annotation.xy = (dt, pct)
            self._annotation.set_visible(True)
            self.draw_idle()
        else:
            if self._annotation and self._annotation.get_visible():
                self._annotation.set_visible(False)
                self.draw_idle()


# ────────────────────────────────────────────
# 메인 윈도우
# ────────────────────────────────────────────
class MinuteChartViewer(QMainWindow):

    def __init__(self):
        super().__init__()
        self.db_config = self._load_db_config()
        self._loader = None
        self._setup_ui()

    # ── 설정 로드 ──────────────────────────────
    def _load_db_config(self) -> dict:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"config.yaml을 찾을 수 없습니다: {config_path}")
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        db_config = config.get('database', {})
        if not db_config:
            raise ValueError("config.yaml에 'database' 섹션이 없습니다.")
        return db_config

    # ── UI 구성 ───────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle('분봉 차트 뷰어')
        self.setMinimumSize(1200, 750)
        self.resize(1400, 850)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 6)
        layout.setSpacing(6)

        # ── 상단 컨트롤바 ──
        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)

        lbl_date = QLabel('날짜:')
        lbl_date.setFont(QFont('', 11))

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat('yyyy-MM-dd')
        self.date_edit.setFixedWidth(130)
        self.date_edit.setFont(QFont('', 11))

        self.btn_query = QPushButton('조회')
        self.btn_query.setFixedWidth(70)
        self.btn_query.setFont(QFont('', 11))
        self.btn_query.clicked.connect(self._on_query)

        self.lbl_info = QLabel('')
        self.lbl_info.setFont(QFont('', 10))
        self.lbl_info.setStyleSheet('color: #888888;')

        ctrl.addWidget(lbl_date)
        ctrl.addWidget(self.date_edit)
        ctrl.addWidget(self.btn_query)
        ctrl.addSpacing(20)
        ctrl.addWidget(self.lbl_info)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # ── 차트 ──
        self.canvas = ChartCanvas(self)
        toolbar = NavigationToolbar(self.canvas, self)
        toolbar.setStyleSheet('background: #1C1C2E; color: #CCCCCC;')
        layout.addWidget(toolbar)
        layout.addWidget(self.canvas)

        # ── 상태바 ──
        self.statusBar().showMessage('날짜를 선택하고 [조회] 버튼을 클릭하세요.')

        # 다크 스타일
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #1C1C2E; color: #EEEEEE; }
            QDateEdit, QLabel { color: #EEEEEE; background: transparent; }
            QDateEdit { background: #2A2A3E; border: 1px solid #444; border-radius: 4px; padding: 3px 6px; }
            QPushButton {
                background: #3B82F6; color: white; border: none;
                border-radius: 4px; padding: 5px 14px;
            }
            QPushButton:hover { background: #2563EB; }
            QPushButton:disabled { background: #555; color: #999; }
            QStatusBar { color: #888888; }
        """)

    # ── 조회 버튼 클릭 ─────────────────────────
    def _on_query(self):
        qdate = self.date_edit.date()
        trade_date = date(qdate.year(), qdate.month(), qdate.day())

        self.btn_query.setEnabled(False)
        self.statusBar().showMessage(f'{trade_date} 데이터 조회 중...')
        self.lbl_info.setText('')

        # 이전 로더 정리
        if self._loader and self._loader.isRunning():
            self._loader.quit()
            self._loader.wait()

        self._loader = DataLoader(self.db_config, trade_date)
        self._loader.finished.connect(lambda d: self._on_data_loaded(d, trade_date))
        self._loader.error.connect(self._on_error)
        self._loader.start()

    # ── 데이터 로드 완료 ───────────────────────
    def _on_data_loaded(self, stock_data: dict, trade_date: date):
        self.btn_query.setEnabled(True)

        if not stock_data:
            self.statusBar().showMessage(f'{trade_date} — 저장된 분봉 데이터가 없습니다.')
            self.canvas._setup_axes()
            self.canvas.ax.set_title(f'{trade_date} 데이터 없음', color='#FF6B6B', fontsize=13)
            self.canvas.draw()
            return

        # 데이터 포인트 수 계산
        total_pts = sum(len(v['data']) for v in stock_data.values())
        time_range = ''
        for info in stock_data.values():
            if info['data']:
                start = info['data'][0]['dt'].strftime('%H:%M')
                end = info['data'][-1]['dt'].strftime('%H:%M')
                time_range = f' | {start} ~ {end}'
                break

        self.lbl_info.setText(
            f"{len(stock_data)}개 종목 | 총 {total_pts:,}건{time_range}"
        )
        self.statusBar().showMessage(f'{trade_date} 조회 완료')
        self.canvas.plot(stock_data, trade_date)

    # ── 에러 처리 ──────────────────────────────
    def _on_error(self, msg: str):
        self.btn_query.setEnabled(True)
        self.statusBar().showMessage(f'오류: {msg}')
        self.lbl_info.setText('')


# ────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    try:
        viewer = MinuteChartViewer()
        viewer.show()
        # 앱 시작 시 오늘 날짜로 자동 조회
        viewer._on_query()
    except FileNotFoundError as e:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(None, '설정 오류', str(e))
        sys.exit(1)
    except Exception as e:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(None, '오류', str(e))
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
