"""
강화된 주식 분석 메인 클래스
절대조건: 5일선이 20일선 아래 + 외국인 연속매수
"""
import os
import time
from datetime import datetime
from dotenv import load_dotenv

# 모듈 import (기존과 동일)
from data_fetcher import DataFetcher
from technical_indicators import SignalAnalyzer
from utils import (
    setup_logger, send_discord_message, format_multi_signal_message,
    format_signal_combination_message, save_backtest_candidates, ProgressTracker
)
# 기존 import에 추가
from enhanced_technical_indicators import (
    check_investor_condition,
    calculate_ma20_divergence,
    get_divergence_bonus,
    check_trading_value
)

load_dotenv()

class EnhancedStockAnalyzer:
    """강화된 주식 분석 메인 클래스 - 절대조건 필터링"""

    def __init__(self):
        self.logger = setup_logger()
        self.data_fetcher = DataFetcher()
        self.signal_analyzer = SignalAnalyzer(self.data_fetcher)
        self.webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

        # 로컬 DB 사용 여부 확인 및 설정
        self.db_manager = None
        self.use_local_db = False
        self._setup_local_db()
        
        # 결과 저장용
        self.backtest_candidates = []
        self.signal_lists = self._init_signal_lists()
        self.multi_signal_stocks = self._init_multi_signal_stocks()
        self.signal_combinations = {}
        
        # 필터링 설정
        self.min_score_for_messaging = 3
        self.min_score_for_detail = 3

    def _setup_local_db(self):
        """로컬 DB 설정 (config.yaml이 있을 경우)"""
        try:
            import yaml
            from db_manager import DBManager

            config_path = "config.yaml"
            if not os.path.exists(config_path):
                self.logger.info("💡 config.yaml 없음 - API로 일봉 데이터 조회")
                return

            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            db_config = config.get('database', {})
            if not db_config:
                self.logger.info("💡 config.yaml에 database 설정 없음 - API로 일봉 데이터 조회")
                return

            # DB 매니저 생성 및 연결
            self.db_manager = DBManager(db_config, self.logger)
            if self.db_manager.connect():
                self.data_fetcher.set_db_manager(self.db_manager)
                self.use_local_db = True
                self.logger.info("✅ 로컬 DB 연결 성공 - 일봉 데이터는 로컬 DB 사용")
            else:
                self.logger.warning("⚠️ 로컬 DB 연결 실패 - API로 일봉 데이터 조회")

        except ImportError:
            self.logger.info("💡 PyYAML 미설치 - API로 일봉 데이터 조회")
        except Exception as e:
            self.logger.warning(f"⚠️ 로컬 DB 설정 실패: {e} - API로 일봉 데이터 조회")

    def _init_signal_lists(self):
        """개별 신호별 종목 리스트 초기화"""
        return {
            "골든크로스": [],
            "볼린저밴드복귀": [],
            "거래량급증": [],
            "Williams%R회복": [],
            "이중바닥": [],
            "일목균형표": [],
            "컵앤핸들": [],
            "5일선20일선돌파": [],
            "RSI매수신호": [],  # 🆕 추가
            "MACD골든크로스": [],  # 🆕 추가
            "MACD돌파직전": [],  # 🆕 추가
            "외국인매수추세": [],
            "기관매수추세": []
        }
    
    def _init_multi_signal_stocks(self):
        """다중신호 종목 분류 초기화"""
        return {
            "ultra_strong": [],
            "strong": [],
            "moderate": [],
            "weak_internal": [],
            "single_internal": []
        }

    """
    EnhancedStockAnalyzer의 analyze_stock 메서드 최종 수정본
    모든 버그 수정:
    1. _record_individual_signals에 score 인자 추가 ✅
    2. _record_signal_combination 호출을 인라인 코드로 교체 ✅
    """ 
    
    def analyze_stock(self, name, code):
        """
        개별 종목 분석 (절대조건 필터링 적용)
        버그 수정 완료 버전
        """
        try:
            # 외국인 순매수 추세 확인 (로컬 DB 우선, 없으면 API)
            try:
                if self.use_local_db:
                    foreign_netbuy_list, foreign_trend = self.data_fetcher.get_foreign_netbuy_trend_from_db(code)
                    # DB에서 데이터가 없거나 불충분하면 API 사용
                    if not foreign_netbuy_list or foreign_trend == "unknown":
                        self.logger.debug(f"🌐 {name}({code}): 외국인 데이터 API 사용")
                        foreign_netbuy_list, foreign_trend = self.data_fetcher.get_foreign_netbuy_trend(code)
                    else:
                        self.logger.debug(f"💾 {name}({code}): 외국인 데이터 DB 사용")
                else:
                    foreign_netbuy_list, foreign_trend = self.data_fetcher.get_foreign_netbuy_trend(code)
            except Exception as e:
                self.logger.warning(f"⚠️ {name}({code}) 외국인 데이터 조회 실패: {e}")
                foreign_netbuy_list, foreign_trend = [], "unknown"
            
            # 주가 데이터 조회 (로컬 DB 우선, 없으면 API)
            df = None
            try:
                # 로컬 DB 사용 시도
                if self.use_local_db:
                    df = self.data_fetcher.get_daily_data_from_db(code)
                    if df is not None and not df.empty:
                        self.logger.debug(f"💾 {name}({code}): 로컬 DB 데이터 사용")

                # 로컬 DB에 데이터가 없거나 DB 미사용 시 API 사용
                if df is None or df.empty:
                    self.logger.debug(f"🌐 {name}({code}): API 데이터 사용")
                    df = self.data_fetcher.get_daily_price_data_with_realtime(code)

            except Exception as e:
                self.logger.warning(f"⚠️ {name}({code}) 실시간 데이터 실패, 기본 API 시도: {e}")
                try:
                    df = self.data_fetcher.get_period_price_data(code)
                except Exception as e2:
                    self.logger.error(f"❌ {name}({code}) 모든 데이터 조회 실패: {e2}")
                    return False
            
            if df is None or df.empty:
                self.logger.warning(f"⚠️ {name}: 가격 데이터를 가져올 수 없습니다.")
                return False
            
            # SignalAnalyzer에서 절대조건 체크 및 점수 계산
            try:
                score, active_signals, passes_absolute, filter_reason = self.signal_analyzer.calculate_buy_signal_score(
                    df, name, code, foreign_trend=foreign_trend, foreign_netbuy_list=foreign_netbuy_list
                )
                
                # 절대조건 미통과시 로깅 후 종료
                if not passes_absolute:
                    self.logger.debug(f"🚫 {name}({code}) 절대조건 미통과: {filter_reason}")
                    return True  # 분석은 성공했으나 조건 미통과
                    
            except Exception as score_error:
                self.logger.error(f"❌ {name}({code}) 점수 계산 실패: {score_error}")
                return False
            
            # 현재 가격 정보 안전하게 추출
            try:
                # 컬럼명 통일 처리
                if 'stck_clpr' in df.columns:
                    current_price = df.iloc[-1]["stck_clpr"]
                elif 'stck_prpr' in df.columns:
                    current_price = df.iloc[-1]["stck_prpr"]
                else:
                    current_price = 0
            
                if current_price > 400000:
                    self.logger.debug(f"🚫 {name}({code}) 구매가격이 너무 높음: {current_price/10000:.1f}만원")
                    return True
                    
                if 'acml_vol' in df.columns:
                    volume = df.iloc[-1]["acml_vol"]
                elif 'cntg_vol' in df.columns:
                    volume = df.iloc[-1]["cntg_vol"]
                else:
                    volume = 0
                    
            except Exception as price_error:
                self.logger.warning(f"⚠️ {name}({code}) 가격정보 추출 실패: {price_error}")
                current_price = 0
                volume = 0
    
            
            # 점수별 처리 - 개별 신호 기록
            if score >= self.min_score_for_detail:
                try:
                    individual_signals = self.signal_analyzer.get_individual_signals(df)
                    # 🔥 버그 수정 1: score 인자 추가
                    self._record_individual_signals(individual_signals, name, code, foreign_trend, score)
                except Exception as signal_error:
                    self.logger.warning(f"⚠️ {name}({code}) 개별신호 분석 실패: {signal_error}")
            
            # 다중신호 등급 분류 (절대조건 통과 종목만)
            stock_info = {
                "name": name, "code": code, "score": score,
                "signals": active_signals, "price": current_price, "volume": volume,
                "foreign": foreign_netbuy_list,
                "filter_status": "절대조건통과",
                "filter_reason": filter_reason
            }
            self._classify_multi_signal_stock_filtered(stock_info)
            
            # 🔥 버그 수정 2: _record_signal_combination을 인라인 코드로 교체
            # 신호 조합 패턴 분석 (3점 이상)
            if score >= self.min_score_for_messaging and active_signals:
                combo_key = " + ".join(sorted(active_signals))
                if combo_key not in self.signal_combinations:
                    self.signal_combinations[combo_key] = []
                self.signal_combinations[combo_key].append(f"{name}({code})")
            
            # 백테스트 후보 (3점 이상, 절대조건 통과)
            if score >= self.min_score_for_messaging:
                self.backtest_candidates.append({
                    "code": code,
                    "name": name,
                    "score": score,
                    "signals": active_signals,
                    "price": current_price,
                    "volume": volume,
                    "foreign_netbuy": foreign_netbuy_list,
                    "filter_status": "절대조건통과",
                    "filter_reason": filter_reason,
                    "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ {name}({code}) 분석 실패: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _record_individual_signals(self, signals, name, code, foreign_trend, score):
        """개별 신호 기록 (점수별 필터링 적용)"""
        if score >= self.min_score_for_messaging:
            stock_info = f"- {name} ({code}) - {score}점 ✅"
            
            for signal_name, is_active in signals.items():
                if is_active and signal_name in self.signal_lists:
                    self.signal_lists[signal_name].append(stock_info)
            
            if foreign_trend == "steady_buying":
                self.signal_lists["외국인매수추세"].append(stock_info)
        
        # 내부 로깅 - INFO 레벨로 변경하여 파일에 기록되도록 수정
        if score >= self.min_score_for_detail:
            active_signal_names = [name for name, is_active in signals.items() if is_active]
            # DEBUG → INFO로 변경
            self.logger.info(f"📊 {name}({code}) {score}점 ✅: {', '.join(active_signal_names)}")

    def _classify_multi_signal_stock_filtered(self, stock_info):
        """다중신호 등급별 분류 (절대조건 통과 종목만)"""
        score = stock_info["score"]
        
        if score >= 5:
            self.multi_signal_stocks["ultra_strong"].append(stock_info)
        elif score == 4:
            self.multi_signal_stocks["strong"].append(stock_info)
        elif score == 3:
            self.multi_signal_stocks["moderate"].append(stock_info)
        elif score == 2:
            self.multi_signal_stocks["weak_internal"].append(stock_info)
            self.logger.debug(f"📝 절대조건통과: {stock_info['name']}({stock_info['code']}) 2점")
        elif score == 1:
            self.multi_signal_stocks["single_internal"].append(stock_info)
            self.logger.debug(f"📝 절대조건통과: {stock_info['name']}({stock_info['code']}) 1점")

    def run_analysis(self):
        """전체 분석 실행 (절대조건 필터링 적용)"""
        self.logger.info("📊 절대조건 필터링 적용 - 시가총액 상위 200개 종목 분석 시작 (코스피+코스닥)...")
        self.logger.info("🔒 절대조건: ①현재가<20일선 ②거래량≥1000주 ③볼린저밴드내 ④외국인최근2~3일연속매수")

        # 로컬 DB 사용 여부 알림
        if self.use_local_db:
            self.logger.info("💾 일봉 데이터: 로컬 DB 사용 (daily_collector.py로 수집된 데이터)")
        else:
            self.logger.info("🌐 일봉 데이터: API 직접 조회")

        # 종목 리스트 조회
        stock_list = self.data_fetcher.get_top_200_stocks(top_n=300)
        if not stock_list:
            self.logger.error("❌ 종목 리스트를 가져올 수 없습니다.")
            return False
        
        # 진행상황 추적
        progress = ProgressTracker(len(stock_list))
        
        # 각 종목 분석
        for name, code in stock_list.items():
            success = self.analyze_stock(name, code)

            # 절대조건 통과 여부 확인 (multi_signal_stocks에 추가되었는지로 판단)
            filter_passed = any(
                stock['code'] == code
                for grade_stocks in self.multi_signal_stocks.values()
                for stock in grade_stocks
            )

            progress.update(success, filter_passed)

            # API 호출 제한 (로컬 DB 사용 시에는 대기 시간 불필요)
            if not self.use_local_db:
                time.sleep(0.2)
            else:
                # 로컬 DB 사용 시에도 실시간 현재가 조회를 위한 최소 대기
                time.sleep(0.05)
        
        # 결과 처리 - ProgressTracker의 카운트 사용
        summary = progress.get_summary()
        self._process_results(
            progress, 
            summary['filter_passed_count'],  # ProgressTracker에서 가져옴
            summary['filter_failed_count']    # ProgressTracker에서 가져옴
        )
        return True

    def _process_results(self, progress, filter_passed_count, filter_failed_count):
        """분석 결과 처리 및 전송 (절대조건 통계 포함)"""
        summary = progress.get_summary()
        self.logger.info(f"분석 완료: 성공 {summary['analyzed_count']}개, "
                        f"오류 {summary['error_count']}개, "
                        f"절대조건 통과 {filter_passed_count}개, "
                        f"절대조건 미통과 {filter_failed_count}개")
        
        # 다중신호 종목 전송 (절대조건 통과만)
        self._send_filtered_multi_signal_results()
        
        # 신호 조합 패턴 분석 결과 전송
        self._send_combination_results()
        
        # 강화된 요약 통계 전송
        self._send_enhanced_summary_results(summary, filter_passed_count, filter_failed_count)
        
        # 상세 신호 (환경변수로 제어)
        detail_mode = os.getenv("DETAIL_MODE", "false").lower() == "true"
        if detail_mode:
            self._send_filtered_detailed_signals()
        
        # 백테스트 후보 저장
        save_backtest_candidates(self.backtest_candidates, self.logger)
        
        # 절대조건 관련 내부 통계
        self._log_absolute_filter_statistics(filter_passed_count, filter_failed_count)

    def _send_enhanced_summary_results(self, summary, filter_passed_count, filter_failed_count):
        """강화된 요약 통계 전송 (절대조건 정보 포함)"""
        messenger_count = (len(self.multi_signal_stocks["ultra_strong"]) + 
                          len(self.multi_signal_stocks["strong"]) + 
                          len(self.multi_signal_stocks["moderate"]))
        
        total_signals = (messenger_count + 
                        len(self.multi_signal_stocks["weak_internal"]) + 
                        len(self.multi_signal_stocks["single_internal"]))
        
        summary_msg = f"📈 **[절대조건 필터링 적용 매수신호 요약]**\n"
        summary_msg += f"🔒 **절대조건**: 현재가<20일선 + 거래량≥1000주 + 볼린저밴드내 + 외국인 연속매수\n\n"
        
        summary_msg += f"🚀 초강력 신호: {len(self.multi_signal_stocks['ultra_strong'])}개\n"
        summary_msg += f"🔥 강력 신호: {len(self.multi_signal_stocks['strong'])}개\n"
        summary_msg += f"⭐ 보통 신호: {len(self.multi_signal_stocks['moderate'])}개\n"
        
        summary_msg += f"\n📊 **절대조건 통과: {filter_passed_count}개**\n"
        summary_msg += f"🚫 절대조건 미통과: {filter_failed_count}개\n"
        summary_msg += f"📝 전체 신호 발생: {total_signals}개\n"
        
        if filter_passed_count > 0:
            pass_rate = (filter_passed_count / (filter_passed_count + filter_failed_count)) * 100
            summary_msg += f"✅ 절대조건 통과율: {pass_rate:.1f}%\n"
        
        summary_msg += f"\n⏱️ 분석시간: {summary['elapsed_time']/60:.1f}분"
        
        send_discord_message(summary_msg, self.webhook_url)

        # 골든크로스 / MACD골든크로스 발생 종목 별도 전송
        all_stocks = []
        for grade_stocks in self.multi_signal_stocks.values():
            if isinstance(grade_stocks, list):
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

        if len(self.backtest_candidates) > 0:
            self.logger.info(f"🎯 절대조건 + 고점수 종목: {len(self.backtest_candidates)}개")

    def _log_absolute_filter_statistics(self, filter_passed_count, filter_failed_count):
        """절대조건 필터링 통계 로깅"""
        self.logger.info("📊 === 절대조건 필터링 통계 ===")
        self.logger.info(f"✅ 절대조건 통과: {filter_passed_count}개")
        self.logger.info(f"🚫 절대조건 미통과: {filter_failed_count}개")
    
        if filter_passed_count + filter_failed_count > 0:
            pass_rate = (filter_passed_count / (filter_passed_count + filter_failed_count)) * 100
            self.logger.info(f"📈 절대조건 통과율: {pass_rate:.1f}%")
    
        self.logger.info("🔒 적용된 절대조건:")
        self.logger.info("   ① 현재가가 20일선 아래에 위치") 
        self.logger.info("   ② 거래량 1000주 이상") 
        self.logger.info("   ③ 볼린저밴드 하단선 위에 위치") 
        self.logger.info("   ④ 외국인 최근 2~3일 연속 순매수")

    def _send_filtered_multi_signal_results(self):
        """절대조건 통과 다중신호 종목만 메신저 전송"""
        messenger_grades = ["ultra_strong", "strong", "moderate"]
        
        for grade in messenger_grades:
            if self.multi_signal_stocks[grade]:
                msg = format_multi_signal_message(grade, self.multi_signal_stocks[grade])
                if msg:
                    # 절대조건 통과 표시 추가
                    enhanced_msg = msg.replace("**[", "**[✅절대조건통과 ")
                    send_discord_message(enhanced_msg, self.webhook_url)
                    self.logger.info(f"📱 메신저전송 - {grade}: {len(self.multi_signal_stocks[grade])}개 (절대조건통과)")

    def _send_combination_results(self):
        """신호 조합 패턴 결과 전송"""
        if self.signal_combinations:
            combo_msg = format_signal_combination_message(self.signal_combinations)
            if combo_msg:
                enhanced_combo_msg = combo_msg.replace("**[인기 신호 조합 패턴]**", 
                                                     "**[✅절대조건통과 인기 신호 조합 패턴]**")
                send_discord_message(enhanced_combo_msg, self.webhook_url)
                self.logger.info(f"신호 조합 패턴: {len(self.signal_combinations)}개 (절대조건통과)")

    def _send_filtered_detailed_signals(self):
        """절대조건 통과 개별 신호만 상세 전송"""
        icons = {
            "골든크로스": "🟡", 
            "볼린저밴드복귀": "🔵", 
            "거래량급증": "🔴",
            "Williams%R회복": "🟤", 
            "이중바닥": "⚫", 
            "일목균형표": "🔘", 
            "컵앤핸들": "🎯", 
            "5일선20일선돌파": "📈", 
            "RSI매수신호": "🟢",  # 🆕 추가
            "MACD골든크로스": "⚡",  # 🆕 추가
            "MACD돌파직전": "🔆",  # 🆕 추가
            "외국인매수추세": "🌍", 
            "기관매수추세": "🏛️"
        }
        
        for signal_type, signal_list in self.signal_lists.items():
            if signal_list:
                icon = icons.get(signal_type, "📊")
                msg = f"{icon} **[✅{signal_type} 발생 종목 (절대조건통과)]**\n" + "\n".join(signal_list)
                send_discord_message(msg, self.webhook_url)
                self.logger.info(f"📱 상세전송 - {signal_type}: {len(signal_list)}개 (절대조건통과)")


def main():
    """메인 실행 함수 (절대조건 필터링 적용)"""
    analyzer = None
    try:
        # 환경변수 체크
        required_env_vars = ["KIS_APP_KEY", "KIS_APP_SECRET"]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]

        if missing_vars:
            print(f"❌ 필수 환경변수가 설정되지 않았습니다: {missing_vars}")
            return

        # 강화된 분석기 생성 및 실행
        analyzer = EnhancedStockAnalyzer()
        analyzer.logger.info("🚀 절대조건 필터링 주식 분석 시작")

        success = analyzer.run_analysis()

        if success:
            analyzer.logger.info("✅ 절대조건 필터링 분석 완료!")
            analyzer.logger.info("📱 메신저에는 절대조건 통과 종목만 전송되었습니다.")
        else:
            analyzer.logger.error("❌ 분석 실행 중 오류 발생")

    except Exception as e:
        print(f"❌ 심각한 오류 발생: {e}")

        # 에러 메시지 전송
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if webhook_url:
            error_msg = f"❌ **[절대조건 필터링 시스템 오류]**\n주식 분석 중 오류가 발생했습니다: {str(e)}"
            send_discord_message(error_msg, webhook_url)

    finally:
        # DB 연결 해제
        if analyzer and analyzer.db_manager:
            analyzer.db_manager.disconnect()


if __name__ == "__main__":
    main()