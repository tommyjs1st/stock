#!/bin/bash
# 데이터 수집 상태 확인 스크립트

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 색상 정의
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  데이터 수집 상태 확인 도구${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
echo ""

# 인자가 없으면 메뉴 표시
if [ $# -eq 0 ]; then
    echo "사용법을 선택하세요:"
    echo ""
    echo "  1) 전체 현황 확인 (일봉 + 분봉 + 배치 이력)"
    echo "  2) 일봉 데이터만 확인"
    echo "  3) 분봉 데이터만 확인"
    echo "  4) 상세 리포트 (데이터 품질 포함)"
    echo "  5) 특정 종목 조회"
    echo "  6) 종료"
    echo ""
    read -p "선택 (1-6): " choice

    case $choice in
        1)
            echo -e "${GREEN}전체 현황을 확인합니다...${NC}"
            python check_collection_status.py
            ;;
        2)
            echo -e "${GREEN}일봉 데이터를 확인합니다...${NC}"
            python check_collection_status.py --daily
            ;;
        3)
            echo -e "${GREEN}분봉 데이터를 확인합니다...${NC}"
            python check_collection_status.py --minute
            ;;
        4)
            echo -e "${GREEN}상세 리포트를 생성합니다...${NC}"
            python check_collection_status.py --detailed
            ;;
        5)
            read -p "종목코드 입력 (예: 005930): " stock_code
            if [ -n "$stock_code" ]; then
                echo -e "${GREEN}${stock_code} 종목을 조회합니다...${NC}"
                python check_collection_status.py --stock "$stock_code"
            else
                echo -e "${YELLOW}종목코드가 입력되지 않았습니다.${NC}"
            fi
            ;;
        6)
            echo "종료합니다."
            exit 0
            ;;
        *)
            echo -e "${YELLOW}잘못된 선택입니다.${NC}"
            exit 1
            ;;
    esac
else
    # 인자가 있으면 직접 실행
    python check_collection_status.py "$@"
fi

echo ""
echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
