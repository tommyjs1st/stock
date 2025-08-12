"""
도우미 함수들
"""
import os


def check_dependencies():
    """필수 라이브러리 확인"""
    print("  📦 필수 라이브러리 확인 중...")
    required_modules = ['requests', 'pandas', 'numpy', 'yaml']
    missing_modules = []
    
    for module in required_modules:
        try:
            __import__(module)
            print(f"    ✅ {module}")
        except ImportError:
            missing_modules.append(module)
            print(f"    ❌ {module}")
    
    if missing_modules:
        print(f"❌ 필수 라이브러리가 설치되지 않았습니다: {', '.join(missing_modules)}")
        print("다음 명령어로 설치하세요:")
        print(f"pip install {' '.join(missing_modules)}")
        return False
    
    return True


def create_logs_directory():
    """로그 디렉토리 생성"""
    logs_dir = 'logs'
    print(f"  📁 로그 디렉토리 확인: {logs_dir}")
    os.makedirs(logs_dir, exist_ok=True)
    print(f"  ✅ 로그 디렉토리 준비됨")


def safe_float_conversion(value, default=0.0):
    """안전한 float 변환"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int_conversion(value, default=0):
    """안전한 int 변환"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def format_currency(amount):
    """통화 포맷팅"""
    try:
        return f"{int(amount):,}원"
    except (ValueError, TypeError):
        return "0원"


def format_percentage(value, decimals=2):
    """퍼센트 포맷팅"""
    try:
        return f"{value:.{decimals}f}%"
    except (ValueError, TypeError):
        return "0.00%"
