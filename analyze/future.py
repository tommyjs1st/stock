"""
메인 실행 파일 - 미래 상승 가능성 분석 클래스 분리 적용
주식 분석 프로그램의 진입점
"""
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

# trading_system 모듈 경로 추가 (analyze 폴더에서 사용시)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
trading_system_path = os.path.join(parent_dir, 'trading_system')

if os.path.exists(trading_system_path) and trading_system_path not in sys.path:
    sys.path.insert(0, trading_system_path)

# 모듈 import
from data_fetcher import DataFetcher
from technical_indicators import SignalAnalyzer
from strategy.future_potential_analyzer import FuturePotentialAnalyzer
from config.config_manager import ConfigManager
from data.kis_api_client import KISAPIClient
from utils import (
    setup_logger, send_discord_message, format_multi_signal_message,
    format_signal_combination_message, save_backtest_candidates, ProgressTracker
)

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
trading_system_path = os.path.join(parent_dir, 'trading_system')
if os.path.exists(trading_system_path):
    sys.path.insert(0, trading_system_path)
    from data.kis_api_client import KISAPIClient
    from strategy.technical_indicators import TechnicalIndicators
    TRADING_SYSTEM_AVAILABLE = True

load_dotenv()

class StockAnalyzer:
    """미래 상승 가능성 분석이 반영된 주식 분석 클래스"""
    
    def __init__(self, config_path: str = "../trading_system/config.yaml"):
        self.config_manager = ConfigManager(config_path)
        kis_config = self.config_manager.get_kis_config()
        self.api_client = KISAPIClient(
            app_key=kis_config['app_key'],
            app_secret=kis_config['app_secret'],
            base_url=kis_config['base_url'],
            account_no=kis_config['account_no']
        )

        self.logger = setup_logger()
        self.data_fetcher = DataFetcher()
        self.signal_analyzer = SignalAnalyzer(self.data_fetcher)
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        
        # 미래 상승 가능성 분석 모듈
        self.future_analyzer = FuturePotentialAnalyzer(self.api_client, self.logger)
        
        # 결과 저장용
        self.backtest_candidates = []
        self.signal_lists = self._init_signal_lists()
        self.multi_signal_stocks = self._init_multi_signal_stocks()
        self.signal_combinations = {}
        
        # 필터링 기준
        self.min_future_score = int(os.getenv("MIN_FUTURE_SCORE", "60"))  # 환경변수로 설정 가능
        self.min_signal_score = int(os.getenv("MIN_SIGNAL_SCORE", "3"))
    
    def _init_signal_lists(self):
        """개별 신호별 종목 리스트 초기화"""
        return {
            "골든크로스": [],
            "볼린저밴드복귀": [],
            "MACD상향돌파": [],
            "RSI과매도회복": [],
            "스토캐스틱회복": [],
            "거래량급증": [],
            "Williams%R회복": [],
            "이중바닥": [],
            "일목균형표": [],
            "컵앤핸들": [],
            "MACD골든크로스": [],
            "외국인매수추세": [],
            "기관매수추세": []
        }
    
    def _init_multi_signal_stocks(self):
        """다중신호 종목 분류 초기화"""
        return {
            "ultra_strong": [],    # 5점 이상 + A등급
            "strong": [],          # 4점 + B등급 이상
            "moderate": [],        # 3점 + C등급 이상
            "weak": [],           # 2점
            "single": []          # 1점
        }
    
    def analyze_stock(self, name, code):
        """개별 종목 분석 - 미래 상승 가능성 반영"""
        try:
            # 외국인 순매수 추세 확인
            foreign_netbuy_list, foreign_trend = self.data_fetcher.get_foreign_netbuy_trend(code)
            
            # 주가 데이터 조회 (실시간 포함)
            df = self.data_fetcher.get_daily_price_data_with_realtime(code)
            if df is None or df.empty:
                self.logger.warning(f"⚠️ {name}: 가격 데이터를 가져올 수 없습니다.")
                return False
            
            # 1. 기존 기술적 신호 점수 계산
            signal_score, active_signals, passes_absolute, exclude_reason = self.signal_analyzer.calculate_buy_signal_score(
                df, name, code, foreign_trend=foreign_trend
            )
            if not passes_absolute:
                self.logger.debug(f"🚫 {name}({code}) 절대조건 미통과: {exclude_reason}")
                return True
            
            # 2. 미래 상승 가능성 분석 (활성화된 경우에만)
            future_analysis = self.future_analyzer.calculate_future_potential(code)
            future_score = future_analysis["total_score"]
            future_grade = future_analysis["grade"]
            
            # 3. 종합 평가 점수 계산
            # 미래 점수를 0-5점 스케일로 변환
            future_normalized = min(future_score / 20, 5)  # 100점 -> 5점으로 변환
            combined_score = signal_score * 0.7 + future_normalized * 0.3
                
            # D등급 필터링 (40점 미만)
            if future_score < 40:
                self.logger.debug(f"🚫 {name}({code}) D등급으로 제외: {future_score:.1f}점")
                return True
            
            # 4. 최종 점수가 기준 미달이면 제외
            if combined_score < self.min_signal_score:
                self.logger.debug(f"🚫 {name}({code}) 기준미달로 제외: {future_score:.1f}점")
                return True
            
            # 현재 가격 정보
            current_price = df.iloc[-1]["stck_clpr"]
            volume = df.iloc[-1]["acml_vol"]
            
            # 개별 신호 체크 및 기록
            individual_signals = self.signal_analyzer.get_individual_signals(df)
            self._record_individual_signals(individual_signals, name, code, foreign_trend)
            
            # 종목 정보 구성 (미래 분석 정보 추가)
            stock_info = {
                "name": name, 
                "code": code, 
                "score": int(combined_score),  # 종합 점수
                "signal_score": signal_score,  # 기존 신호 점수
                "future_score": future_score,  # 미래 점수
                "future_grade": future_grade,  # 미래 등급
                "signals": active_signals, 
                "price": current_price, 
                "volume": volume,
                "foreign_netbuy": foreign_netbuy_list,
                "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # 다중신호 등급 분류 (미래 분석 반영)
            self._classify_enhanced_multi_signal_stock(stock_info)
            
            # 신호 조합 패턴 분석
            if combined_score >= 2:
                combo_key = " + ".join(sorted(active_signals))
                if combo_key not in self.signal_combinations:
                    self.signal_combinations[combo_key] = []
                self.signal_combinations[combo_key].append(f"{name}({code})")
            
            # 백테스트 후보 (종합 점수 3점 이상)
            if combined_score >= 3:
                self.backtest_candidates.append(stock_info)
            
            return True
            
        except Exception as e:
            self.logger.error(f"⚠️ {name} 분석 오류: {e}")
            return False
    
    def _classify_enhanced_multi_signal_stock(self, stock_info):
        """미래 분석이 반영된 다중신호 등급별 분류"""
        score = stock_info["score"]
        future_score = stock_info["future_score"]
        future_grade = stock_info["future_grade"]
        
        # 미래 등급별 가중치 적용
        if future_grade.startswith("A"):  # A+ 또는 A
            grade_bonus = 1
        elif future_grade.startswith("B"):  # B
            grade_bonus = 0.5
        elif future_grade.startswith("C"):  # C
            grade_bonus = 0
        else:  # D등급은 이미 필터링됨
            grade_bonus = -0.5
        
        effective_score = score + grade_bonus
        
        if effective_score >= 5:
            self.multi_signal_stocks["ultra_strong"].append(stock_info)
        elif effective_score >= 4:
            self.multi_signal_stocks["strong"].append(stock_info)
        elif effective_score >= 3:
            self.multi_signal_stocks["moderate"].append(stock_info)
        elif effective_score >= 2:
            self.multi_signal_stocks["weak"].append(stock_info)
        else:
            self.multi_signal_stocks["single"].append(stock_info)
    
    def _record_individual_signals(self, signals, name, code, foreign_trend):
        """개별 신호 기록"""
        stock_info = f"- {name} ({code})"
        
        for signal_name, is_active in signals.items():
            if is_active and signal_name in self.signal_lists:
                self.signal_lists[signal_name].append(stock_info)
        
        # 외국인/기관 추세 신호
        if foreign_trend == "steady_buying":
            self.signal_lists["외국인매수추세"].append(stock_info)
    
    def run_analysis(self):
        """전체 분석 실행"""
        self.logger.info("📊 시가총액 상위 200개 종목 분석 시작...")
        
        self.logger.info(f"🎯 미래 상승 가능성 분석 활성화 (최소 기준: {self.min_future_score}점)")
        
        # 종목 리스트 조회
        stock_list = self.data_fetcher.get_top_200_stocks()
        if not stock_list:
            self.logger.error("❌ 종목 리스트를 가져올 수 없습니다.")
            return False
        
        # 진행상황 추적
        progress = ProgressTracker(len(stock_list))
        
        # 각 종목 분석
        for name, code in stock_list.items():
            success = self.analyze_stock(name, code)
            progress.update(success)
            time.sleep(0.5)  # API 호출 제한 고려
        
        # 결과 처리
        self._process_results(progress)
        return True
    
    def _process_results(self, progress):
        """분석 결과 처리 및 전송"""
        summary = progress.get_summary()
        self.logger.info(f"분석 완료: 성공 {summary['analyzed_count']}개, "
                        f"오류 {summary['error_count']}개, "
                        f"성공률 {summary['success_rate']:.1f}%")
        
        # 백테스트 후보에 미래 분석 추가 적용 (2차 필터링)
        self.backtest_candidates = self.future_analyzer.get_filtered_candidates(
            self.backtest_candidates, self.min_future_score
        )
        
        # 1. 다중신호 종목 우선순위별 전송
        self._send_enhanced_multi_signal_results()
        
        # 2. 신호 조합 패턴 분석 결과 전송
        self._send_combination_results()
        
        # 3. 요약 통계 전송
        self._send_enhanced_summary_results(summary)
        
        # 4. 개별 신호 상세 (환경변수로 제어)
        detail_mode = os.getenv("DETAIL_MODE", "false").lower() == "true"
        if detail_mode:
            self._send_detailed_signals()
        
        # 5. 백테스트 후보 저장 (미래 분석 정보 포함)
        save_backtest_candidates(self.backtest_candidates, self.logger)
    
    def _send_enhanced_multi_signal_results(self):
        """미래 분석이 반영된 다중신호 종목 결과 전송"""
        priority_order = ["ultra_strong", "strong", "moderate", "weak"]
        
        for grade in priority_order:
            if self.multi_signal_stocks[grade]:
                msg = self._format_enhanced_signal_message(grade, self.multi_signal_stocks[grade])
                if msg:
                    send_discord_message(msg, self.webhook_url)
                    self.logger.info(f"{grade} 종목: {len(self.multi_signal_stocks[grade])}개")
    
    def _format_enhanced_signal_message(self, grade, stocks):
        """미래 분석 정보가 포함된 메시지 포맷"""
        if not stocks:
            return ""
        
        grade_names = {
            "ultra_strong": "🚀 초강력 신호 (5점+A등급)",
            "strong": "🔥 강력 신호 (4점+B등급)",
            "moderate": "⭐ 보통 신호 (3점+C등급)",
            "weak": "⚡ 약한 신호 (2점)"
        }
        
        msg = f"**[{grade_names[grade]}]**\n"
        
        for stock in stocks[:10]:  # 상위 10개만
            signals_text = " + ".join(stock["signals"][:3])  # 주요 신호 3개만
            if len(stock["signals"]) > 3:
                signals_text += f" 외 {len(stock['signals'])-3}개"
            
            future_info = ""
            future_info = f" | 미래:{stock['future_score']:.0f}점({stock['future_grade'][:1]})"
            
            msg += f"- **{stock['name']}** ({stock['code']}) "
            msg += f"종합:{stock['score']}점{future_info}\n"
            msg += f"  신호: {signals_text}\n"
            msg += f"  가격: {stock['price']:,}원\n\n"
        
        if len(stocks) > 10:
            msg += f"... 외 {len(stocks)-10}개 종목\n"
        
        return msg
    
    def _send_combination_results(self):
        """신호 조합 패턴 결과 전송"""
        if self.signal_combinations:
            combo_msg = format_signal_combination_message(self.signal_combinations)
            if combo_msg:
                send_discord_message(combo_msg, self.webhook_url)
                self.logger.info(f"신호 조합 패턴: {len(self.signal_combinations)}개")
    
    def _send_enhanced_summary_results(self, summary):
        """미래 분석이 반영된 요약 통계 전송"""
        total_multi_signals = sum(len(stocks) for grade, stocks in self.multi_signal_stocks.items() 
                                 if grade != "single")
        
        analysis_mode = "🎯 미래분석모드" 
        summary_msg = f"📈 **[{analysis_mode} 종목 요약]**\n"
        summary_msg += f"🚀 초강력 신호: {len(self.multi_signal_stocks['ultra_strong'])}개\n"
        summary_msg += f"🔥 강력 신호: {len(self.multi_signal_stocks['strong'])}개\n"
        summary_msg += f"⭐ 보통 신호: {len(self.multi_signal_stocks['moderate'])}개\n"
        summary_msg += f"⚡ 약한 신호: {len(self.multi_signal_stocks['weak'])}개\n"
        summary_msg += f"💡 단일 신호: {len(self.multi_signal_stocks['single'])}개\n"
        summary_msg += f"📊 **총 다중신호 종목: {total_multi_signals}개**\n"
        
        # 미래 등급 분포 추가
        future_grades = {}
        for grade_stocks in self.multi_signal_stocks.values():
            for stock in grade_stocks:
                grade_key = stock['future_grade'][:1]  # A, B, C, D
                future_grades[grade_key] = future_grades.get(grade_key, 0) + 1
            
        summary_msg += f"🎯 미래등급 분포: "
        for grade in ['A', 'B', 'C']:
            count = future_grades.get(grade, 0)
            summary_msg += f"{grade}등급 {count}개, "
        summary_msg = summary_msg.rstrip(", ") + "\n"
        
        summary_msg += f"✅ 분석 성공: {summary['analyzed_count']}개 | ❌ 오류: {summary['error_count']}개\n"
        summary_msg += f"⏱️ 처리시간: {summary['elapsed_time']/60:.1f}분"
        
        send_discord_message(summary_msg, self.webhook_url)

        # 골든크로스 / MACD골든크로스 발생 종목 별도 전송
        all_stocks = []
        for grade_stocks in self.multi_signal_stocks.values():
            all_stocks.extend(grade_stocks)

        golden_cross_stocks = [s for s in all_stocks
                               if '골든크로스' in s.get('signals', [])
                               and 'MACD골든크로스' not in s.get('signals', [])]
        macd_golden_stocks  = [s for s in all_stocks
                               if 'MACD골든크로스' in s.get('signals', [])]

        cross_msg = ""
        if golden_cross_stocks:
            cross_msg += "🟡 **[골든크로스 발생 종목]**\n"
            for s in sorted(golden_cross_stocks, key=lambda x: x.get('score', 0), reverse=True):
                cross_msg += f"  · {s['name']} ({s['code']}) - {s['score']}점\n"
            cross_msg += "\n"

        if macd_golden_stocks:
            cross_msg += "⚡ **[MACD골든크로스 발생 종목]**\n"
            for s in sorted(macd_golden_stocks, key=lambda x: x.get('score', 0), reverse=True):
                cross_msg += f"  · {s['name']} ({s['code']}) - {s['score']}점\n"

        if cross_msg:
            send_discord_message(cross_msg, self.webhook_url)
            self.logger.info("✅ 골든크로스/MACD골든크로스 종목 전송 완료")

        # 고잠재력 종목 수 로깅
        high_potential_count = len(self.backtest_candidates)
        if high_potential_count > 0:
            self.logger.info(f"🎯 고잠재력 종목: {high_potential_count}개 발굴")
    
    def _send_detailed_signals(self):
        """개별 신호 상세 결과 전송"""
        icons = {
            "골든크로스": "🟡", "볼린저밴드복귀": "🔵", "MACD상향돌파": "🟢",
            "RSI과매도회복": "🟠", "스토캐스틱회복": "🟣", "거래량급증": "🔴",
            "Williams%R회복": "🟤", "이중바닥": "⚫", "일목균형표": "🔘", 
            "컵앤핸들": "🎯", "MACD골든크로스": "⚡", "외국인매수추세": "🌍", 
            "기관매수추세": "🏛️"
        }
        
        for signal_type, signal_list in self.signal_lists.items():
            if signal_list:
                icon = icons.get(signal_type, "📊")
                msg = f"{icon} **[{signal_type} 발생 종목]**\n" + "\n".join(signal_list)
                send_discord_message(msg, self.webhook_url)
                self.logger.info(f"{signal_type}: {len(signal_list)}개")


def main():
    """메인 실행 함수"""
    try:
        # 환경변수 체크
        required_env_vars = ["KIS_APP_KEY", "KIS_APP_SECRET"]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        
        if missing_vars:
            print(f"❌ 필수 환경변수가 설정되지 않았습니다: {missing_vars}")
            return
        
        # 분석기 생성 및 실행
        analyzer = StockAnalyzer()
        success = analyzer.run_analysis()
        
        if success:
            analyzer.logger.info("✅ 모든 분석 및 전송 완료!")
        else:
            analyzer.logger.error("❌ 분석 실행 중 오류 발생")
            
    except Exception as e:
        print(f"❌ 심각한 오류 발생: {e}")
        
        # 에러 메시지 전송
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if webhook_url:
            error_msg = f"❌ **[시스템 오류]**\n주식 분석 중 오류가 발생했습니다: {str(e)}"
            send_discord_message(error_msg, webhook_url)


if __name__ == "__main__":
    main()
