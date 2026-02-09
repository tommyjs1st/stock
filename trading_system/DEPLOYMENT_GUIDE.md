# 📱 포트폴리오 모니터링 앱 배포 가이드

개인용 + 외부 접속 가능한 배포 방법 3가지

---

## 🚀 방법 1: Streamlit Cloud (추천 ⭐⭐⭐)

**가장 쉽고 빠른 방법 - 5분 내 완료**

### 장점
- ✅ 무료
- ✅ 외부 어디서든 접속 가능
- ✅ HTTPS 자동
- ✅ 서버 관리 불필요
- ✅ Git push만 하면 자동 재배포

### 단계

#### 1. GitHub 리포지토리 생성

```bash
cd /Users/jsshin/RESTAPI/trading_system

# Git 초기화 (이미 있으면 스킵)
git init

# .gitignore 생성 (중요!)
cat > .gitignore << 'EOF'
config.yaml
*.log
__pycache__/
.env
kiwoom_token.json
stock_names.json
purchased_stocks_*.json
EOF

# 파일 추가
git add portfolio_monitor_app.py requirements_app.txt
git commit -m "Add portfolio monitoring app"

# GitHub에 푸시 (리포지토리 생성 후)
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

#### 2. Streamlit Cloud 배포

1. [streamlit.io/cloud](https://share.streamlit.io/) 접속
2. GitHub 계정으로 로그인
3. "New app" 클릭
4. 리포지토리 선택: `YOUR_USERNAME/YOUR_REPO`
5. Main file path: `portfolio_monitor_app.py`
6. **Settings → Secrets** 클릭 후 다음 입력:

```toml
# Streamlit Secrets (TOML 형식)
APP_PASSWORD = "your_secure_password_here"

[kis]
app_key = "YOUR_KIS_APP_KEY"
app_secret = "YOUR_KIS_APP_SECRET"
base_url = "https://openapi.koreainvestment.com:9443"
account_no = "YOUR_ACCOUNT_NO"

[kiwoom]
app_key = "YOUR_KIWOOM_APP_KEY"
app_secret = "YOUR_KIWOOM_APP_SECRET"
```

7. Deploy 클릭!

#### 3. 코드 수정 (Secrets 사용)

```python
# config.yaml 대신 Streamlit secrets 사용
@st.cache_resource
def init_clients():
    # Streamlit Cloud에서는 st.secrets 사용
    if "kis" in st.secrets:
        kis_config = st.secrets["kis"]
    else:
        # 로컬에서는 config.yaml 사용
        config_manager = ConfigManager("config.yaml")
        kis_config = config_manager.get_kis_config()

    # ... (나머지 코드)
```

#### 4. 접속

생성된 URL: `https://your-username-portfolio.streamlit.app`

모바일에서 접속 → 홈 화면에 추가 → 앱처럼 사용!

---

## 🌐 방법 2: Cloudflare Tunnel (보안 ⭐⭐)

**포트포워딩 없이 안전하게 외부 노출**

### 장점
- ✅ 무료
- ✅ 포트포워딩 불필요
- ✅ HTTPS 자동
- ✅ 보안 터널
- ✅ 집 IP 노출 안 됨

### 단계

#### 1. Cloudflare Tunnel 설치

```bash
# macOS
brew install cloudflare/cloudflare/cloudflared

# 인증
cloudflared tunnel login
```

#### 2. 터널 생성

```bash
# 터널 생성
cloudflared tunnel create portfolio-monitor

# 터널 라우트 설정
cloudflared tunnel route dns portfolio-monitor portfolio.your-domain.com

# 설정 파일 생성
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: portfolio-monitor
credentials-file: /Users/jsshin/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  - hostname: portfolio.your-domain.com
    service: http://localhost:8501
  - service: http_status:404
EOF
```

#### 3. Streamlit 실행 + 터널 연결

```bash
# Terminal 1: Streamlit 실행
cd /Users/jsshin/RESTAPI/trading_system
streamlit run portfolio_monitor_app.py

# Terminal 2: Cloudflare Tunnel 실행
cloudflared tunnel run portfolio-monitor
```

#### 4. systemd 서비스로 자동 실행 (선택)

```bash
# Streamlit 서비스
sudo tee /etc/systemd/system/portfolio-monitor.service > /dev/null << 'EOF'
[Unit]
Description=Portfolio Monitor Streamlit App
After=network.target

[Service]
Type=simple
User=jsshin
WorkingDirectory=/Users/jsshin/RESTAPI/trading_system
ExecStart=/usr/local/bin/streamlit run portfolio_monitor_app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 서비스 시작
sudo systemctl enable portfolio-monitor
sudo systemctl start portfolio-monitor

# Cloudflare Tunnel도 자동 시작
cloudflared service install
```

---

## 🏠 방법 3: 기존 워드프레스 서버에 통합 (고급 ⭐)

**기존 서버에 서브 경로로 통합**

### 전제 조건
- nginx 또는 Apache 사용 중
- 서버에 SSH 접속 가능
- Python 3.8+ 설치

### 단계 (nginx 기준)

#### 1. 서버에 앱 배포

```bash
# 서버 SSH 접속
ssh user@your-server.com

# 앱 디렉토리 생성
mkdir -p /var/www/portfolio-monitor
cd /var/www/portfolio-monitor

# 파일 업로드 (로컬에서)
scp portfolio_monitor_app.py user@your-server.com:/var/www/portfolio-monitor/
scp requirements_app.txt user@your-server.com:/var/www/portfolio-monitor/
scp config.yaml user@your-server.com:/var/www/portfolio-monitor/

# 서버에서 패키지 설치
pip3 install -r requirements_app.txt
```

#### 2. systemd 서비스 생성

```bash
sudo tee /etc/systemd/system/portfolio-monitor.service > /dev/null << 'EOF'
[Unit]
Description=Portfolio Monitor App
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/portfolio-monitor
Environment="APP_PASSWORD=your_secure_password"
ExecStart=/usr/bin/streamlit run portfolio_monitor_app.py --server.port=8501 --server.address=127.0.0.1
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable portfolio-monitor
sudo systemctl start portfolio-monitor
```

#### 3. nginx 리버스 프록시 설정

```bash
sudo nano /etc/nginx/sites-available/your-site
```

**서브도메인 방식 (portfolio.your-domain.com):**

```nginx
server {
    server_name portfolio.your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 지원 (Streamlit 필수)
        proxy_read_timeout 86400;
    }

    # SSL은 Let's Encrypt로 자동 생성
    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/portfolio.your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/portfolio.your-domain.com/privkey.pem;
}

server {
    if ($host = portfolio.your-domain.com) {
        return 301 https://$host$request_uri;
    }

    listen 80;
    server_name portfolio.your-domain.com;
    return 404;
}
```

**서브 경로 방식 (your-domain.com/portfolio):**

```nginx
server {
    server_name your-domain.com;

    # 기존 워드프레스
    location / {
        # 기존 설정...
    }

    # 포트폴리오 앱
    location /portfolio/ {
        proxy_pass http://127.0.0.1:8501/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;

        # 경로 재작성
        rewrite ^/portfolio$ /portfolio/ permanent;
    }
}
```

**Streamlit 실행 (서브 경로용):**

```bash
streamlit run portfolio_monitor_app.py \
    --server.port=8501 \
    --server.address=127.0.0.1 \
    --server.baseUrlPath="/portfolio"
```

#### 4. nginx 재시작 & SSL 설정

```bash
# nginx 설정 테스트
sudo nginx -t

# nginx 재시작
sudo systemctl restart nginx

# Let's Encrypt SSL 발급 (서브도메인)
sudo certbot --nginx -d portfolio.your-domain.com
```

---

## 🔒 보안 강화 (추가 옵션)

### 1. nginx에서 Basic Auth 추가

```bash
# htpasswd 설치
sudo apt install apache2-utils

# 비밀번호 파일 생성
sudo htpasswd -c /etc/nginx/.htpasswd yourusername

# nginx 설정에 추가
location /portfolio/ {
    auth_basic "Restricted Access";
    auth_basic_user_file /etc/nginx/.htpasswd;

    proxy_pass http://127.0.0.1:8501/;
    # ... (나머지 설정)
}
```

### 2. IP 화이트리스트

```nginx
location /portfolio/ {
    # 허용할 IP만 접속 가능
    allow 1.2.3.4;      # 집 IP
    allow 5.6.7.8;      # 회사 IP
    deny all;

    proxy_pass http://127.0.0.1:8501/;
}
```

---

## 📱 모바일에서 앱처럼 사용하기

### iOS (Safari)

1. Safari로 URL 접속
2. 공유 버튼 탭
3. "홈 화면에 추가" 선택
4. 아이콘처럼 사용 가능!

### Android (Chrome)

1. Chrome으로 URL 접속
2. 메뉴 → "홈 화면에 추가"
3. 앱처럼 실행 가능!

---

## 🧪 로컬 테스트 (배포 전)

```bash
cd /Users/jsshin/RESTAPI/trading_system

# 비밀번호 환경변수 설정
export APP_PASSWORD="test123"

# 실행
streamlit run portfolio_monitor_app.py

# 브라우저에서 http://localhost:8501 접속
# 비밀번호: test123
```

---

## ⚡ 권장 배포 방법

| 상황 | 추천 방법 |
|------|----------|
| 빠르게 시작 | **Streamlit Cloud** |
| 보안 중요 | **Cloudflare Tunnel** |
| 기존 서버 활용 | **nginx 리버스 프록시** |
| 개인용만 | 로컬 실행 + VPN |

개인적으로는 **Streamlit Cloud**를 추천합니다! 가장 쉽고 관리도 편합니다. 🚀
