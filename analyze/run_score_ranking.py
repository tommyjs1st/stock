"""
시가총액 상위 종목 단기/중기/장기 종합 점수화 프로그램

흐름:
  1. DataFetcher.get_top_200_stocks() 로 시가총액 상위 종목(코스피+코스닥) 유니버스 확보
  2. 종목별 일봉 데이터 조회 (로컬 DB 우선, 없거나 부족하면 API 자동 전환) - 기존 main.py 패턴과 동일
  3. StockScorer로 단기30+중기30+장기40=100점 산출
  4. 240일치 데이터가 부족한 종목은 스코어링 대상에서 제외
  5. 총점 상위 N개 종목을 항목별 점수와 함께 디스코드로 전송

설정(config.yaml) 사용 섹션:
  - database: 로컬 DB 접속 정보 (없으면 API로 자동 전환)
  - notification.discord_webhook: 디스코드 웹훅 URL
    (다른 웹훅을 쓰려면 --webhook-key discord_webhook_auto 처럼 지정)

실행:
  python run_score_ranking.py                        # 기본값: 상위 200종목 분석, 상위 20종목 전송
  python run_score_ranking.py --universe 300          # 300종목 분석
  python run_score_ranking.py --top-n 10              # 상위 10종목만 전송
  python run_score_ranking.py --webhook-key discord_webhook_auto
"""
import os
import sys
import argparse

import yaml

from data_fetcher import DataFetcher
from stock_scorer import StockScorer, MIN_REQUIRED_DAYS
from utils import setup_logger, send_discord_message

CONFIG_PATH = "config.yaml"

# 로컬 DB 조회는 "캘린더 기준" 일수이므로 거래일 241일 확보를 위해 넉넉하게 설정
DB_LOOKBACK_CALENDAR_DAYS = 400
# API 조회는 "거래일 기준" 일수
API_LOOKBACK_TRADING_DAYS = 300


def load_config():
    """config.yaml 로드. 없으면 빈 dict 반환 (API 전용 모드로 동작)"""
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class ScoreRankingRunner:
    def __init__(self, universe_size=200, top_n=20, webhook_key="discord_webhook"):
        self.logger = setup_logger()
        self.data_fetcher = DataFetcher()
        self.scorer = StockScorer()
        self.universe_size = universe_size
        self.top_n = top_n

        self.config = load_config()
        self.webhook_url = self.config.get("notification", {}).get(webhook_key)
        if not self.webhook_url:
            self.logger.warning(
                f"⚠️ config.yaml > notification.{webhook_key} 값이 없습니다. "
                "결과는 콘솔에만 출력됩니다."
            )

        self.db_manager = None
        self.use_local_db = False
        self._setup_local_db()

    def _setup_local_db(self):
        """로컬 DB 설정 (config.yaml에 database 섹션이 있을 경우)"""
        try:
            from db_manager import DBManager

            db_config = self.config.get("database", {})
            if not db_config:
                self.logger.info("💡 config.yaml에 database 설정 없음 - API로 일봉 데이터 조회")
                return

            self.db_manager = DBManager(db_config, self.logger)
            if self.db_manager.connect():
                self.data_fetcher.set_db_manager(self.db_manager)
                self.use_local_db = True
                self.logger.info("💾 일봉 데이터: 로컬 DB 우선 사용")
            else:
                self.logger.warning("⚠️ DB 연결 실패 - API로 일봉 데이터 조회")
        except Exception as e:
            self.logger.info(f"💡 로컬 DB 설정 스킵: {e}")

    def _get_daily_data(self, code):
        """일봉 데이터 조회 (로컬 DB 우선, 데이터가 없거나 부족하면 API로 자동 전환)"""
        df = None

        if self.use_local_db:
            try:
                df = self.data_fetcher.get_daily_data_from_db(
                    code, days=DB_LOOKBACK_CALENDAR_DAYS
                )
            except Exception as e:
                self.logger.debug(f"⚠️ {code}: DB 조회 실패, API로 전환: {e}")
                df = None

        if df is None or df.empty or len(df) < MIN_REQUIRED_DAYS:
            try:
                df = self.data_fetcher.get_period_price_data(
                    code, days=API_LOOKBACK_TRADING_DAYS
                )
            except Exception as e:
                self.logger.error(f"❌ {code}: API 조회 실패: {e}")

        return df

    def run(self):
        self.logger.info(f"📊 시가총액 상위 {self.universe_size}개 종목 점수화 시작...")
        stock_list = self.data_fetcher.get_top_200_stocks(top_n=self.universe_size)
        if not stock_list:
            self.logger.error("❌ 종목 리스트를 가져올 수 없습니다.")
            return False

        results = []
        skipped_data = 0
        failed = 0

        for idx, (name, code) in enumerate(stock_list.items(), 1):
            try:
                df = self._get_daily_data(code)
                if df is None or df.empty:
                    failed += 1
                    continue

                score_result = self.scorer.score_stock(df)
                if score_result is None:
                    skipped_data += 1
                    continue

                score_result["name"] = name
                score_result["code"] = code
                results.append(score_result)

                if idx % 20 == 0:
                    self.logger.info(f"📈 진행률: {idx}/{len(stock_list)}")

            except Exception as e:
                self.logger.error(f"❌ {name}({code}) 처리 실패: {e}")
                failed += 1
                continue

        self.logger.info(
            f"✅ 점수화 완료: {len(results)}개 종목 "
            f"(240일 데이터부족 제외 {skipped_data}개, 조회실패 {failed}개)"
        )

        if not results:
            self.logger.warning("⚠️ 점수화된 종목이 없습니다.")
            return False

        results.sort(key=lambda x: x["total_score"], reverse=True)
        top_results = results[: self.top_n]

        self._send_to_discord(top_results, total_analyzed=len(results))
        return True

    def _format_stock_block(self, rank, r):
        s, m, l = r["short"], r["mid"], r["long"]
        lines = [
            f"**{rank}. {r['name']}({r['code']}) - {r['total_score']}점 [{r['grade']}]**",
            f"   현재가: {r['current_price']:,.0f}원",
            f"   🔴단기 {s['score']}/{s['max']}점 "
            f"(5>20일선:{s['ma5_gt_ma20']} RSI:{s['rsi']}[{s['rsi_value']}] 거래량:{s['volume']})",
            f"   🟡중기 {m['score']}/{m['max']}점 "
            f"(20>60일선:{m['ma20_gt_ma60']} MACD>Signal:{m['macd_gt_signal']})",
            f"   🟢장기 {l['score']}/{l['max']}점 "
            f"(현재가>120일선:{l['price_gt_ma120']} 120>240일선:{l['ma120_gt_ma240']})",
        ]
        return "\n".join(lines)

    def _send_to_discord(self, top_results, total_analyzed):
        header = (
            f"📊 **[종목 종합 점수 랭킹 - 상위 {len(top_results)}개]**\n"
            f"🔍 전체 분석 대상: {total_analyzed}개 (시가총액 상위 {self.universe_size}종목 중)\n"
            f"점수 = 🔴단기30 + 🟡중기30 + 🟢장기40 = 100점 만점\n"
            + "─" * 30
        )
        blocks = [header] + [
            self._format_stock_block(i, r) for i, r in enumerate(top_results, 1)
        ]
        message = "\n\n".join(blocks)

        if self.webhook_url:
            send_discord_message(message, self.webhook_url)
            self.logger.info("📱 디스코드 전송 완료")
        else:
            self.logger.warning("⚠️ DISCORD_WEBHOOK_URL 환경변수가 없어 콘솔에만 출력합니다.")
            print(message)


def main():
    parser = argparse.ArgumentParser(description="종목 종합 점수 랭킹 & 디스코드 알림")
    parser.add_argument(
        "--universe", type=int, default=200, help="스코어링 대상 종목 수 (기본 200)"
    )
    parser.add_argument(
        "--top-n", type=int, default=20, help="디스코드로 보낼 상위 종목 수 (기본 20)"
    )
    parser.add_argument(
        "--webhook-key",
        type=str,
        default="discord_webhook",
        help="config.yaml > notification 아래에서 사용할 웹훅 키 이름 "
        "(기본: discord_webhook, 예: discord_webhook_auto)",
    )
    args = parser.parse_args()

    runner = None
    try:
        runner = ScoreRankingRunner(
            universe_size=args.universe, top_n=args.top_n, webhook_key=args.webhook_key
        )
        success = runner.run()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ 심각한 오류 발생: {e}")
        try:
            webhook_url = load_config().get("notification", {}).get(args.webhook_key)
            if webhook_url:
                send_discord_message(
                    f"❌ **[점수 랭킹 시스템 오류]**\n{str(e)}", webhook_url
                )
        except Exception:
            pass
        sys.exit(1)
    finally:
        if runner and runner.db_manager:
            runner.db_manager.disconnect()


if __name__ == "__main__":
    main()
