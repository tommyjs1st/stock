"""
메인 실행 파일
주식 분석 프로그램의 진입점
"""
import os
import time
from datetime import datetime
from dotenv import load_dotenv

# 모듈 import
from data_fetcher import DataFetcher
from technical_indicators import SignalAnalyzer
from utils import (
    setup_logger, send_discord_message, format_multi_signal_message,
    format_signal_combination_message, save_backtest_candidates, ProgressTracker
)

load_dotenv()

class StockAnalyzer:
    """주식 분석 메인 클래스"""
    
    def __init__(self):
        self.logger = setup_logger()
        self.data_fetcher = DataFetcher()
        self.signal_analyzer = SignalAnalyzer(self.data_fetcher)
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        
        # 결과 저장용
        self.backtest_candidates = []
        self.signal_lists = self._init_signal_lists()
        self.multi_signal_stocks = self._init_multi_signal_stocks()
        self.signal_combinations = {}
    
        # 메신저 전송 필터링 기준 설정
        self.min_score_for_messaging = 3  # 메신저 전송 최소 점수
        self.min_score_for_detail = 2     # 상세 분석 최소 점수 (내부 로깅용)

    def _init_signal_lists(self):
        """개별 신호별 종목 리스트 초기화 (새로운 신호 추가)"""
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
            "기관매수추세": [],
            # 새로운 이동평균선 신호들
            "5일선20일선돌파": [],
            "현재가20일선아래": [],
            "5일선20일선아래": []
        }
    
    def _init_multi_signal_stocks(self):
        """다중신호 종목 분류 초기화"""
        return {
            "ultra_strong": [],    # 5점 이상
            "strong": [],          # 4점
            "moderate": [],        # 3점
            "weak_internal": [],   # 2점 (내부용, 메신저 제외)
            "single_internal": []  # 1점 (내부용, 메신저 제외)
        }
    
 
    def analyze_stock(self, name, code):
        """개별 종목 분석 (메신저 필터링 적용)"""
        try:
            # 외국인 순매수 추세 확인
            foreign_netbuy_list, foreign_trend = self.data_fetcher.get_foreign_netbuy_trend(code)
            
            # 주가 데이터 조회 (실시간 포함)
            df = self.data_fetcher.get_daily_price_data_with_realtime(code)
            if df is None or df.empty:
                self.logger.warning(f"⚠️ {name}: 가격 데이터를 가져올 수 없습니다.")
                return False
            
            # 종합 점수 계산
            score, active_signals = self.signal_analyzer.calculate_buy_signal_score(
                df, name, code, foreign_trend=foreign_trend
            )
            
            # 현재 가격 정보
            current_price = df.iloc[-1]["stck_clpr"]
            volume = df.iloc[-1]["acml_vol"]
            
            # 2점 이상만 개별 신호 기록 (메모리 절약)
            if score >= self.min_score_for_detail:
                individual_signals = self.signal_analyzer.get_individual_signals(df)
                self._record_individual_signals(individual_signals, name, code, foreign_trend, score)
            
            # 다중신호 등급 분류
            stock_info = {
                "name": name, "code": code, "score": score,
                "signals": active_signals, "price": current_price, "volume": volume,
                "foreign": foreign_netbuy_list
            }
            self._classify_multi_signal_stock_filtered(stock_info)
            
            # 3점 이상만 신호 조합 패턴 분석 (메신저 전송용)
            if score >= self.min_score_for_messaging:
                combo_key = " + ".join(sorted(active_signals))
                if combo_key not in self.signal_combinations:
                    self.signal_combinations[combo_key] = []
                self.signal_combinations[combo_key].append(f"{name}({code})")
            
            # 백테스트 후보 (3점 이상)
            if score >= self.min_score_for_messaging:
                self.backtest_candidates.append({
                    "code": code,
                    "name": name,
                    "score": score,
                    "signals": active_signals,
                    "price": current_price,
                    "volume": volume,
                    "foreign_netbuy": foreign_netbuy_list,
                    "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
            
            return True
            
        except Exception as e:
            self.logger.error(f"⚠️ {name} 분석 오류: {e}")
            return False
    
    
    def run_analysis(self):
        """전체 분석 실행"""
        self.logger.info("📊 시가총액 상위 200개 종목 분석 시작...")
        
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
    
    

    def _record_individual_signals(self, signals, name, code, foreign_trend, score):
        """개별 신호 기록 (점수별 필터링 적용)"""
        # 3점 이상만 메신저용 신호 리스트에 추가
        if score >= self.min_score_for_messaging:
            stock_info = f"- {name} ({code}) - {score}점"
            
            for signal_name, is_active in signals.items():
                if is_active and signal_name in self.signal_lists:
                    self.signal_lists[signal_name].append(stock_info)
            
            # 외국인/기관 추세 신호
            if foreign_trend == "steady_buying":
                self.signal_lists["외국인매수추세"].append(stock_info)
        
        # 내부 로깅은 2점 이상
        if score >= self.min_score_for_detail:
            active_signal_names = [name for name, is_active in signals.items() if is_active]
            self.logger.debug(f"📊 {name}({code}) {score}점: {', '.join(active_signal_names)}")
    
    def _classify_multi_signal_stock_filtered(self, stock_info):
        """다중신호 등급별 분류 (메신저 필터링 적용)"""
        score = stock_info["score"]
        
        if score >= 5:
            self.multi_signal_stocks["ultra_strong"].append(stock_info)
        elif score == 4:
            self.multi_signal_stocks["strong"].append(stock_info)
        elif score == 3:
            self.multi_signal_stocks["moderate"].append(stock_info)
        elif score == 2:
            # 2점은 내부용으로만 저장 (메신저 전송 안함)
            self.multi_signal_stocks["weak_internal"].append(stock_info)
            self.logger.debug(f"📝 내부기록: {stock_info['name']}({stock_info['code']}) 2점")
        elif score == 1:
            # 1점은 내부용으로만 저장 (메신저 전송 안함)
            self.multi_signal_stocks["single_internal"].append(stock_info)
            self.logger.debug(f"📝 내부기록: {stock_info['name']}({stock_info['code']}) 1점")
    
    def _process_results(self, progress):
        """분석 결과 처리 및 전송 (3점 이상만 메신저 전송)"""
        summary = progress.get_summary()
        self.logger.info(f"분석 완료: 성공 {summary['analyzed_count']}개, "
                        f"오류 {summary['error_count']}개, "
                        f"성공률 {summary['success_rate']:.1f}%")
        
        # 1. 다중신호 종목 우선순위별 전송 (3점 이상만)
        self._send_filtered_multi_signal_results()
        
        # 2. 신호 조합 패턴 분석 결과 전송 (3점 이상만)
        self._send_combination_results()
        
        # 3. 요약 통계 전송 (전체 vs 메신저 전송)
        self._send_filtered_summary_results(summary)
        
        # 4. 개별 신호 상세 (환경변수로 제어, 3점 이상만)
        detail_mode = os.getenv("DETAIL_MODE", "false").lower() == "true"
        if detail_mode:
            self._send_filtered_detailed_signals()
        
        # 5. 백테스트 후보 저장 (3점 이상)
        save_backtest_candidates(self.backtest_candidates, self.logger)
        
        # 6. 내부 통계 로깅 (모든 점수 포함)
        self._log_internal_statistics()
    
    def _send_filtered_multi_signal_results(self):
        """3점 이상 다중신호 종목만 메신저 전송"""
        # 메신저 전송 대상: ultra_strong, strong, moderate (3점 이상)
        messenger_grades = ["ultra_strong", "strong", "moderate"]
        
        for grade in messenger_grades:
            if self.multi_signal_stocks[grade]:
                msg = format_multi_signal_message(grade, self.multi_signal_stocks[grade])
                if msg:
                    send_discord_message(msg, self.webhook_url)
                    self.logger.info(f"📱 메신저전송 - {grade}: {len(self.multi_signal_stocks[grade])}개")
    
        
    def _send_combination_results(self):
        """신호 조합 패턴 결과 전송"""
        if self.signal_combinations:
            combo_msg = format_signal_combination_message(self.signal_combinations)
            if combo_msg:
                send_discord_message(combo_msg, self.webhook_url)
                self.logger.info(f"신호 조합 패턴: {len(self.signal_combinations)}개")

    def _send_filtered_summary_results(self, summary):
        """필터링된 요약 통계 전송"""
        # 메신저 전송 대상만 집계
        messenger_count = (len(self.multi_signal_stocks["ultra_strong"]) + 
                          len(self.multi_signal_stocks["strong"]) + 
                          len(self.multi_signal_stocks["moderate"]))
        
        # 내부 기록 대상 집계 (전체)
        total_signals = (messenger_count + 
                        len(self.multi_signal_stocks["weak_internal"]) + 
                        len(self.multi_signal_stocks["single_internal"]))
        
        summary_msg = f"📈 **[매수신호 종목 요약 (3점 이상)]**\n"
        summary_msg += f"🚀 초강력 신호: {len(self.multi_signal_stocks['ultra_strong'])}개\n"
        summary_msg += f"🔥 강력 신호: {len(self.multi_signal_stocks['strong'])}개\n"
        summary_msg += f"⭐ 보통 신호: {len(self.multi_signal_stocks['moderate'])}개\n"
        summary_msg += f"📊 **메신저 전송 대상: {messenger_count}개**\n"
        summary_msg += f"📝 전체 신호 발생: {total_signals}개 (2점 이하 {total_signals - messenger_count}개 제외)\n"
        summary_msg += f"✅ 분석 성공: {summary['analyzed_count']}개 | ❌ 오류: {summary['error_count']}개\n"
        summary_msg += f"⏱️ 처리시간: {summary['elapsed_time']/60:.1f}분"
        
        send_discord_message(summary_msg, self.webhook_url)
        
        # 고잠재력 종목 수 로깅
        high_potential_count = len(self.backtest_candidates)
        if high_potential_count > 0:
            self.logger.info(f"🎯 고잠재력 종목 (3점 이상): {high_potential_count}개")
    
    def _send_filtered_detailed_signals(self):
        """3점 이상 개별 신호만 상세 전송"""
        icons = {
            "골든크로스": "🟡", "볼린저밴드복귀": "🔵", "MACD상향돌파": "🟢",
            "RSI과매도회복": "🟠", "스토캐스틱회복": "🟣", "거래량급증": "🔴",
            "Williams%R회복": "🟤", "이중바닥": "⚫", "일목균형표": "🔘", 
            "컵앤핸들": "🎯", "MACD골든크로스": "⚡", "외국인매수추세": "🌍", 
            "기관매수추세": "🏛️", "5일선20일선돌파": "📈", "현재가20일선아래": "📉", 
            "5일선20일선아래": "🔻"
        }
        
        for signal_type, signal_list in self.signal_lists.items():
            if signal_list:  # 이미 3점 이상만 포함되어 있음
                icon = icons.get(signal_type, "📊")
                msg = f"{icon} **[{signal_type} 발생 종목 (3점 이상)]**\n" + "\n".join(signal_list)
                send_discord_message(msg, self.webhook_url)
                self.logger.info(f"📱 상세전송 - {signal_type}: {len(signal_list)}개")
    
    def _log_internal_statistics(self):
        """내부 통계 로깅 (모든 점수 포함)"""
        self.logger.info("📊 === 내부 통계 (전체 점수별 분포) ===")
        self.logger.info(f"🚀 5점 이상: {len(self.multi_signal_stocks['ultra_strong'])}개")
        self.logger.info(f"🔥 4점: {len(self.multi_signal_stocks['strong'])}개")
        self.logger.info(f"⭐ 3점: {len(self.multi_signal_stocks['moderate'])}개")
        self.logger.info(f"⚡ 2점: {len(self.multi_signal_stocks['weak_internal'])}개 (메신저 제외)")
        self.logger.info(f"💡 1점: {len(self.multi_signal_stocks['single_internal'])}개 (메신저 제외)")
        
        total_messenger = (len(self.multi_signal_stocks["ultra_strong"]) + 
                          len(self.multi_signal_stocks["strong"]) + 
                          len(self.multi_signal_stocks["moderate"]))
        
        total_all = (total_messenger + 
                    len(self.multi_signal_stocks["weak_internal"]) + 
                    len(self.multi_signal_stocks["single_internal"]))
        
        self.logger.info(f"📱 메신저 전송: {total_messenger}개 / 📝 전체 발굴: {total_all}개")
        
        if total_all > 0:
            messaging_ratio = (total_messenger / total_all) * 100
            self.logger.info(f"📈 메신저 전송 비율: {messaging_ratio:.1f}%")


# 추가적인 필터링 옵션들
class FilteringOptions:
    """메신저 전송 필터링 옵션 클래스"""
    
    def __init__(self):
        # 환경변수로 설정 가능한 옵션들
        self.min_score_for_messaging = int(os.getenv("MIN_SCORE_MESSAGING", "3"))
        self.min_score_for_detail = int(os.getenv("MIN_SCORE_DETAIL", "2"))
        self.max_stocks_per_grade = int(os.getenv("MAX_STOCKS_PER_GRADE", "10"))
        self.enable_low_score_logging = os.getenv("ENABLE_LOW_SCORE_LOGGING", "true").lower() == "true"
    
    def should_send_to_messenger(self, score):
        """메신저 전송 여부 판단"""
        return score >= self.min_score_for_messaging
    
    def should_log_internally(self, score):
        """내부 로깅 여부 판단"""
        return score >= self.min_score_for_detail
    
    def get_display_message(self):
        """현재 필터링 설정 표시"""
        return (f"📊 필터링 설정: 메신저 {self.min_score_for_messaging}점 이상, "
                f"내부로깅 {self.min_score_for_detail}점 이상, "
                f"등급별 최대 {self.max_stocks_per_grade}개")


def main():
    """메인 실행 함수 (필터링 적용)"""
    try:
        # 환경변수 체크
        required_env_vars = ["KIS_APP_KEY", "KIS_APP_SECRET"]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        
        if missing_vars:
            print(f"❌ 필수 환경변수가 설정되지 않았습니다: {missing_vars}")
            return
        
        # 필터링 옵션 초기화
        filter_options = FilteringOptions()
        print(filter_options.get_display_message())
        
        # 분석기 생성 및 실행
        analyzer = StockAnalyzer()
        analyzer.logger.info("🚀 주식 분석 시작 (3점 이상만 메신저 전송)")
        
        success = analyzer.run_analysis()
        
        if success:
            analyzer.logger.info("✅ 모든 분석 및 전송 완료!")
            analyzer.logger.info("📱 메신저에는 3점 이상 종목만 전송되었습니다.")
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
