"""
로깅 유틸리티 모듈
"""
import os
import logging
from logging.handlers import TimedRotatingFileHandler


def setup_logger(log_dir="logs", log_filename="autotrader.log", 
                when="midnight", backup_count=30, level=logging.INFO):
    """로깅 설정 - 일단위로 로그 파일 생성"""
    os.makedirs(log_dir, exist_ok=True)
    
    # TimedRotatingFileHandler 설정
    file_handler = TimedRotatingFileHandler(
        filename=os.path.join(log_dir, log_filename),
        when=when,        # 자정에 로테이션
        interval=1,       # 1일마다
        backupCount=backup_count,  # 최대 30개 백업 파일 유지 (30일치)
        encoding='utf-8',
        delay=False,
        utc=False
    )
    
    # 로테이션된 파일명 형식 설정 (YYYY-MM-DD 형식)
    file_handler.suffix = "%Y-%m-%d"
    file_handler.namer = lambda name: name.replace('.log', '') + '.log'
    
    # 로그 포맷 설정
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    
    # 콘솔 핸들러 설정
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # 기본 로깅 설정
    logging.basicConfig(
        level=level,
        handlers=[file_handler, console_handler]
    )
    
    return logging.getLogger(__name__)
