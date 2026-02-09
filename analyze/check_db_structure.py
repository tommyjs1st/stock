"""
DB 테이블 구조 확인
"""
import pymysql
import yaml


def load_config():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config.get('database', {})


def main():
    db_config = load_config()

    conn = pymysql.connect(
        host=db_config.get('host', 'localhost'),
        port=db_config.get('port', 3306),
        user=db_config.get('user'),
        password=db_config.get('password'),
        database=db_config.get('database'),
        charset=db_config.get('charset', 'utf8mb4'),
        cursorclass=pymysql.cursors.DictCursor
    )

    cursor = conn.cursor()

    print("\n=== stock_info 테이블 구조 ===")
    cursor.execute("DESCRIBE stock_info")
    for row in cursor.fetchall():
        print(row)

    print("\n=== daily_stock_prices 테이블 구조 ===")
    cursor.execute("DESCRIBE daily_stock_prices")
    for row in cursor.fetchall():
        print(row)

    print("\n=== 데이터 개수 확인 ===")
    cursor.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_info")
    print(f"종목 수: {cursor.fetchone()}")

    cursor.execute("SELECT COUNT(*) FROM daily_stock_prices")
    print(f"일봉 데이터 수: {cursor.fetchone()}")

    cursor.execute("""
    SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date
    FROM daily_stock_prices
    """)
    print(f"일봉 데이터 기간: {cursor.fetchone()}")

    conn.close()


if __name__ == "__main__":
    main()
