"""
일별 포트폴리오 스냅샷 저장 스크립트
- account_balance 테이블: 전 계좌 합산 잔고 저장
- portfolio_history 테이블: 종목별 스냅샷 저장

cron 등록 예시 (평일 15:35):
  35 15 * * 1-5 cd /path/to/analyze && /path/to/venv/bin/python save_daily_snapshot.py

수동 실행:
  python save_daily_snapshot.py
  python save_daily_snapshot.py --date 20250510   # 특정 날짜 지정
  python save_daily_snapshot.py --dry-run         # DB 저장 없이 조회만
"""

import os
import sys
import yaml
import logging
import argparse
from datetime import datetime, date
from typing import Dict, Optional

# analyze 디렉토리 기준으로 실행 (cron에서도 동일하게 동작)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db_manager import DBManager
from kiwoom_api_client import KiwoomAPIClient


# ──────────────────────────────────────────
# 로거 설정
# ──────────────────────────────────────────

def setup_logger(log_date: str) -> logging.Logger:
    log_dir = os.path.join(BASE_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"snapshot_{log_date}.log")

    logger = logging.getLogger('save_daily_snapshot')
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    # 파일 핸들러
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(fh)

    # 콘솔 핸들러
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(ch)

    return logger


# ──────────────────────────────────────────
# 설정 로드
# ──────────────────────────────────────────

def load_config() -> Dict:
    config_path = os.path.join(BASE_DIR, 'config.yaml')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config.yaml을 찾을 수 없습니다: {config_path}")
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────
# account_balance 저장
# ──────────────────────────────────────────

def save_account_balance(
    kiwoom_client: KiwoomAPIClient,
    db_manager: DBManager,
    target_date: date,
    logger: logging.Logger,
    dry_run: bool = False
) -> bool:
    """전 계좌 합산 잔고를 account_balance 테이블에 저장"""

    logger.info("💰 계좌 잔고 조회 시작...")

    enabled_accounts = kiwoom_client.config.get_enabled_accounts()
    if not enabled_accounts:
        logger.warning("⚠️ 활성화된 계좌가 없습니다.")
        return False

    total_eval_amount    = 0.0
    total_purchase_amount = 0.0
    total_profit_loss    = 0.0
    total_deposit        = 0.0
    total_holdings_count = 0

    for alias, account_info in enabled_accounts.items():
        try:
            token = kiwoom_client.get_account_token(
                alias,
                account_info['app_key'],
                account_info['app_secret']
            )

            # ka01690: 일별잔고수익률 (보유종목 + 손익)
            bal_data = kiwoom_client._request_with_token(
                token,
                params={'qry_dt': target_date.strftime('%Y%m%d')},
                api_id='ka01690'
            )

            # kt00001: 예수금상세현황 (100% 주문가능금액 = 실질 예수금)
            dep_data = kiwoom_client._request_with_token(
                token,
                params={'qry_tp': '2'},
                api_id='kt00001'
            )

            if bal_data:
                eval_amt    = float(bal_data.get('tot_evlt_amt', 0))
                pur_amt     = float(bal_data.get('tot_buy_amt', 0))
                profit      = float(bal_data.get('tot_evltv_prft', 0))
                hcount      = len(bal_data.get('day_bal_rt', []))

                total_eval_amount     += eval_amt
                total_purchase_amount += pur_amt
                total_profit_loss     += profit
                total_holdings_count  += hcount

                logger.info(
                    f"  📊 {alias}: 평가 {eval_amt:,.0f}원 / "
                    f"손익 {profit:+,.0f}원 / 종목수 {hcount}개"
                )
            else:
                logger.warning(f"  ⚠️ {alias} 잔고 조회 응답 없음")

            if dep_data:
                deposit = float(dep_data.get('100stk_ord_alow_amt', 0))
                total_deposit += deposit
                logger.info(f"  💵 {alias} 예수금(100%주문가능): {deposit:,.0f}원")
            else:
                logger.warning(f"  ⚠️ {alias} 예수금 조회 응답 없음")

        except Exception as e:
            logger.error(f"  ❌ {alias} 잔고 조회 실패: {e}")

    # 합산 수익률
    profit_loss_rate = (
        total_profit_loss / total_purchase_amount * 100
        if total_purchase_amount > 0 else 0.0
    )
    total_assets = total_eval_amount + total_deposit

    logger.info(
        f"📈 합산 결과: 총자산 {total_assets:,.0f}원 "
        f"(주식 {total_eval_amount:,.0f} + 예수금 {total_deposit:,.0f}) | "
        f"손익 {total_profit_loss:+,.0f}원 ({profit_loss_rate:+.2f}%)"
    )

    if dry_run:
        logger.info("🔍 [DRY-RUN] account_balance 저장 스킵")
        return True

    # UPSERT — account_no='ALL'로 합산 1건 저장
    query = """
        INSERT INTO account_balance
            (account_no, account_alias, date,
             total_eval_amount, total_purchase_amount, total_profit_loss,
             profit_loss_rate, deposit, holdings_count, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            total_eval_amount     = VALUES(total_eval_amount),
            total_purchase_amount = VALUES(total_purchase_amount),
            total_profit_loss     = VALUES(total_profit_loss),
            profit_loss_rate      = VALUES(profit_loss_rate),
            deposit               = VALUES(deposit),
            holdings_count        = VALUES(holdings_count),
            created_at            = NOW()
    """
    params = (
        'ALL',
        'all_accounts',
        target_date,
        total_eval_amount,
        total_purchase_amount,
        total_profit_loss,
        profit_loss_rate,
        total_deposit,
        total_holdings_count,
    )

    try:
        db_manager.cursor.execute(query, params)
        db_manager.commit()
        logger.info(f"✅ account_balance 저장 완료 ({target_date})")
        return True
    except Exception as e:
        logger.error(f"❌ account_balance 저장 실패: {e}")
        db_manager.rollback()
        return False


# ──────────────────────────────────────────
# portfolio_history 저장
# ──────────────────────────────────────────

def save_portfolio_history(
    kiwoom_client: KiwoomAPIClient,
    db_manager: DBManager,
    target_date: date,
    logger: logging.Logger,
    dry_run: bool = False
) -> bool:
    """전 계좌 보유종목을 portfolio_history 테이블에 저장"""

    logger.info("📋 보유종목 조회 시작...")

    try:
        df = kiwoom_client.get_holdings_all()
    except Exception as e:
        logger.error(f"❌ 보유종목 조회 실패: {e}")
        return False

    if df.empty:
        logger.info("💡 보유종목이 없습니다.")
        return True

    logger.info(f"  총 {len(df)}개 종목 조회 완료")

    if dry_run:
        logger.info("🔍 [DRY-RUN] portfolio_history 저장 스킵")
        for _, row in df.iterrows():
            logger.info(
                f"  {row['account_alias']} | {row['stock_code']} {row['stock_name']} | "
                f"수량 {row['quantity']} | 평단 {row['avg_price']:,.0f} | "
                f"평가 {row['eval_amount']:,.0f} | 손익 {row['profit_loss']:+,.0f}"
            )
        return True

    query = """
        INSERT INTO portfolio_history
            (account_no, account_alias, stock_code, stock_name, date,
             quantity, avg_price, close_price, eval_amount,
             profit_loss, profit_rate, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            stock_name   = VALUES(stock_name),
            quantity     = VALUES(quantity),
            avg_price    = VALUES(avg_price),
            close_price  = VALUES(close_price),
            eval_amount  = VALUES(eval_amount),
            profit_loss  = VALUES(profit_loss),
            profit_rate  = VALUES(profit_rate),
            created_at   = NOW()
    """

    success_count = 0
    fail_count = 0

    for _, row in df.iterrows():
        try:
            params = (
                row['account_no'],
                row['account_alias'],
                row['stock_code'],
                row['stock_name'],
                target_date,
                int(row['quantity']),
                float(row['avg_price']),
                float(row['current_price']),   # close_price = 당일 현재가
                float(row['eval_amount']),
                float(row['profit_loss']),
                float(row['profit_rate']),
            )
            db_manager.cursor.execute(query, params)
            success_count += 1
        except Exception as e:
            logger.error(f"  ❌ {row['stock_code']} 저장 실패: {e}")
            fail_count += 1

    try:
        db_manager.commit()
        logger.info(
            f"✅ portfolio_history 저장 완료: 성공 {success_count}건 / 실패 {fail_count}건"
        )
        return fail_count == 0
    except Exception as e:
        logger.error(f"❌ portfolio_history 커밋 실패: {e}")
        db_manager.rollback()
        return False


# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='일별 포트폴리오 스냅샷 저장')
    parser.add_argument(
        '--date', type=str, default=None,
        help='기준일 (YYYYMMDD, 기본값: 오늘)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='DB 저장 없이 조회만 실행'
    )
    args = parser.parse_args()

    # 기준일 설정
    if args.date:
        try:
            target_date = datetime.strptime(args.date, '%Y%m%d').date()
        except ValueError:
            print(f"❌ 날짜 형식이 잘못되었습니다: {args.date} (YYYYMMDD 형식 사용)")
            sys.exit(1)
    else:
        target_date = date.today()

    today_str = target_date.strftime('%Y%m%d')
    logger = setup_logger(today_str)

    logger.info("=" * 60)
    logger.info(f"📅 일별 스냅샷 저장 시작: {target_date}")
    if args.dry_run:
        logger.info("🔍 DRY-RUN 모드 (DB 저장 없음)")
    logger.info("=" * 60)

    # 주말 체크
    if target_date.weekday() >= 5:
        logger.info(f"⏭️ 주말({target_date.strftime('%A')})이므로 스킵합니다.")
        sys.exit(0)

    # 설정 로드
    try:
        config = load_config()
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    db_config = config.get('database', {})
    if not db_config:
        logger.error("❌ config.yaml에 'database' 섹션이 없습니다.")
        sys.exit(1)

    # DB 연결
    db_manager = DBManager(db_config, logger)
    if not args.dry_run:
        if not db_manager.connect():
            logger.error("❌ DB 연결 실패")
            sys.exit(1)

    # 키움 클라이언트 초기화
    try:
        kiwoom_client = KiwoomAPIClient()
    except Exception as e:
        logger.error(f"❌ KiwoomAPIClient 초기화 실패: {e}")
        if not args.dry_run:
            db_manager.disconnect()
        sys.exit(1)

    # 저장 실행
    results = {}
    try:
        results['account_balance'] = save_account_balance(
            kiwoom_client, db_manager, target_date, logger, args.dry_run
        )
        results['portfolio_history'] = save_portfolio_history(
            kiwoom_client, db_manager, target_date, logger, args.dry_run
        )
    finally:
        if not args.dry_run:
            db_manager.disconnect()

    # 결과 요약
    logger.info("=" * 60)
    success_all = all(results.values())
    for table, ok in results.items():
        status = "✅" if ok else "❌"
        logger.info(f"  {status} {table}")
    logger.info(f"{'✅ 전체 완료' if success_all else '⚠️ 일부 실패'}: {target_date}")
    logger.info("=" * 60)

    sys.exit(0 if success_all else 1)


if __name__ == '__main__':
    main()
