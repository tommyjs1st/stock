# 🌐 Apache 웹서버에 포트폴리오 모니터링 앱 배포

기존 워드프레스 + Apache 환경에 Streamlit 앱 통합하기

---

## 📋 전제 조건

- Apache 웹서버 실행 중
- SSH로 서버 접속 가능
- Python 3.8+ 설치됨
- 워드프레스 정상 작동 중

---

## 🚀 배포 단계

### 1단계: 서버에 앱 파일 업로드

#### 로컬에서 파일 압축

```bash
cd /Users/jsshin/RESTAPI/trading_system

# 필요한 파일만 압축
tar -czf portfolio-app.tar.gz \
    portfolio_monitor_app.py \
    requirements_app.txt \
    config.yaml \
    config/ \
    data/ \
    notification/ \
    trading/ \
    utils/
```

#### 서버로 업로드

```bash
# SCP로 업로드
scp portfolio-app.tar.gz user@your-server.com:/tmp/

# SSH 접속
ssh user@your-server.com
```

#### 서버에서 압축 해제

```bash
# 앱 디렉토리 생성
sudo mkdir -p /var/www/portfolio-monitor
sudo chown $USER:$USER /var/www/portfolio-monitor

# 파일 압축 해제
cd /var/www/portfolio-monitor
tar -xzf /tmp/portfolio-app.tar.gz
rm /tmp/portfolio-app.tar.gz

# 권한 설정
chmod 755 /var/www/portfolio-monitor
```

---

### 2단계: Python 환경 설정

```bash
cd /var/www/portfolio-monitor

# 가상환경 생성 (선택사항, 권장)
python3 -m venv venv
source venv/bin/activate

# 필요한 패키지 설치
pip3 install -r requirements_app.txt

# 설치 확인
pip3 list | grep -E "streamlit|plotly|pandas"
```

---

### 3단계: systemd 서비스 생성

Streamlit 앱을 백그라운드 서비스로 실행

```bash
sudo nano /etc/systemd/system/portfolio-monitor.service
```

다음 내용 입력:

```ini
[Unit]
Description=Portfolio Monitor Streamlit App
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/portfolio-monitor

# 환경변수 설정
Environment="APP_PASSWORD=your_secure_password_here"
Environment="PATH=/var/www/portfolio-monitor/venv/bin:/usr/bin:/bin"

# Streamlit 실행 (포트 8501, localhost만 접속 가능)
ExecStart=/var/www/portfolio-monitor/venv/bin/streamlit run portfolio_monitor_app.py \
    --server.port=8501 \
    --server.address=127.0.0.1 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=true

# 자동 재시작
Restart=always
RestartSec=10

# 로그 설정
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**서비스 활성화:**

```bash
# systemd 리로드
sudo systemctl daemon-reload

# 서비스 시작
sudo systemctl start portfolio-monitor

# 부팅 시 자동 시작
sudo systemctl enable portfolio-monitor

# 상태 확인
sudo systemctl status portfolio-monitor

# 로그 확인
sudo journalctl -u portfolio-monitor -f
```

---

### 4단계: Apache 모듈 활성화

Streamlit의 WebSocket 지원을 위해 필요한 모듈들:

```bash
# 프록시 모듈 활성화
sudo a2enmod proxy
sudo a2enmod proxy_http
sudo a2enmod proxy_wstunnel
sudo a2enmod rewrite
sudo a2enmod headers

# Apache 재시작
sudo systemctl restart apache2
```

---

### 5단계: Apache VirtualHost 설정

#### 방법 A: 서브도메인 (portfolio.your-domain.com) ⭐ 추천

```bash
sudo nano /etc/apache2/sites-available/portfolio.your-domain.com.conf
```

다음 내용 입력:

```apache
<VirtualHost *:80>
    ServerName portfolio.your-domain.com
    ServerAdmin admin@your-domain.com

    # HTTP를 HTTPS로 리다이렉트
    RewriteEngine On
    RewriteCond %{HTTPS} off
    RewriteRule ^(.*)$ https://%{HTTP_HOST}$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName portfolio.your-domain.com
    ServerAdmin admin@your-domain.com

    # SSL 설정 (Let's Encrypt - 나중에 자동 추가됨)
    # SSLEngine on
    # SSLCertificateFile /etc/letsencrypt/live/portfolio.your-domain.com/fullchain.pem
    # SSLCertificateKeyFile /etc/letsencrypt/live/portfolio.your-domain.com/privkey.pem

    # 로그 설정
    ErrorLog ${APACHE_LOG_DIR}/portfolio_error.log
    CustomLog ${APACHE_LOG_DIR}/portfolio_access.log combined

    # Streamlit 프록시 설정
    ProxyPreserveHost On
    ProxyRequests Off

    # WebSocket 지원 (Streamlit 필수!)
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} =websocket [NC]
    RewriteRule /(.*)           ws://127.0.0.1:8501/$1 [P,L]
    RewriteCond %{HTTP:Upgrade} !=websocket [NC]
    RewriteRule /(.*)           http://127.0.0.1:8501/$1 [P,L]

    # 일반 프록시
    ProxyPass / http://127.0.0.1:8501/
    ProxyPassReverse / http://127.0.0.1:8501/

    # 헤더 설정
    <Location />
        ProxyPassReverse /
        ProxyPreserveHost On
        RequestHeader set X-Forwarded-Proto "https"
        RequestHeader set X-Forwarded-Port "443"
    </Location>
</VirtualHost>
```

**사이트 활성화:**

```bash
# 설정 활성화
sudo a2ensite portfolio.your-domain.com.conf

# Apache 설정 테스트
sudo apache2ctl configtest

# Apache 재시작
sudo systemctl restart apache2
```

---

#### 방법 B: 서브 경로 (your-domain.com/portfolio)

기존 워드프레스 VirtualHost 파일 수정:

```bash
# 기존 워드프레스 설정 파일 편집
sudo nano /etc/apache2/sites-available/your-domain.com.conf
```

**기존 VirtualHost 내부에 추가:**

```apache
<VirtualHost *:443>
    ServerName your-domain.com
    DocumentRoot /var/www/wordpress

    # 기존 워드프레스 설정...
    <Directory /var/www/wordpress>
        Options FollowSymLinks
        AllowOverride All
        Require all granted
    </Directory>

    # ============================================
    # 포트폴리오 앱 프록시 (새로 추가)
    # ============================================

    # /portfolio 경로로 접속 시 Streamlit으로 프록시
    <Location /portfolio>
        ProxyPreserveHost On
        ProxyPass http://127.0.0.1:8501/
        ProxyPassReverse http://127.0.0.1:8501/

        # WebSocket 지원
        RewriteEngine On
        RewriteCond %{HTTP:Upgrade} =websocket [NC]
        RewriteRule /portfolio/(.*)  ws://127.0.0.1:8501/$1 [P,L]
        RewriteCond %{HTTP:Upgrade} !=websocket [NC]
        RewriteRule /portfolio/(.*)  http://127.0.0.1:8501/$1 [P,L]

        # 헤더 설정
        RequestHeader set X-Forwarded-Proto "https"
        RequestHeader set X-Forwarded-Port "443"
    </Location>

    # 기존 SSL 설정...
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/your-domain.com/fullchain.pem
    SSLCertificateKeyKey /etc/letsencrypt/live/your-domain.com/privkey.pem
</VirtualHost>
```

**서브 경로용 Streamlit 실행 (systemd 수정):**

```bash
sudo nano /etc/systemd/system/portfolio-monitor.service
```

ExecStart 부분을 다음으로 변경:

```ini
ExecStart=/var/www/portfolio-monitor/venv/bin/streamlit run portfolio_monitor_app.py \
    --server.port=8501 \
    --server.address=127.0.0.1 \
    --server.baseUrlPath="/portfolio" \
    --server.headless=true
```

재시작:

```bash
sudo systemctl daemon-reload
sudo systemctl restart portfolio-monitor
sudo systemctl restart apache2
```

---

### 6단계: SSL 인증서 설정 (Let's Encrypt)

#### 서브도메인 방식:

```bash
# Certbot 설치 (Ubuntu/Debian)
sudo apt update
sudo apt install certbot python3-certbot-apache

# SSL 인증서 발급
sudo certbot --apache -d portfolio.your-domain.com

# 자동 갱신 테스트
sudo certbot renew --dry-run
```

#### 기존 도메인에 추가 (서브 경로 방식):

이미 SSL이 있다면 추가 작업 불필요!

---

### 7단계: 방화벽 설정 확인

```bash
# 방화벽 상태 확인
sudo ufw status

# 필요한 포트 열기 (이미 열려있을 수 있음)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 8501 포트는 외부 접근 차단 (localhost만)
# 이미 127.0.0.1로 바인딩되어 있으므로 추가 작업 불필요
```

---

## ✅ 테스트

### 1. 서비스 상태 확인

```bash
# Streamlit 앱 상태
sudo systemctl status portfolio-monitor

# Apache 상태
sudo systemctl status apache2

# 로그 확인
sudo journalctl -u portfolio-monitor -n 50
sudo tail -f /var/log/apache2/portfolio_error.log
```

### 2. 로컬에서 테스트

```bash
# 서버 내부에서 테스트
curl http://127.0.0.1:8501
```

### 3. 외부에서 접속

- **서브도메인**: `https://portfolio.your-domain.com`
- **서브 경로**: `https://your-domain.com/portfolio`

비밀번호 입력 → 앱 화면 표시!

---

## 🔒 보안 강화 (선택)

### Apache에서 IP 제한

```apache
<Location /portfolio>
    # 특정 IP만 허용
    Require ip 1.2.3.4      # 집 IP
    Require ip 5.6.7.8      # 회사 IP

    # 나머지는 차단
    Require all denied

    # ... 프록시 설정
</Location>
```

### Apache Basic Auth 추가 (이중 보안)

```bash
# htpasswd 생성
sudo apt install apache2-utils
sudo htpasswd -c /etc/apache2/.htpasswd yourusername

# Apache 설정에 추가
<Location /portfolio>
    AuthType Basic
    AuthName "Restricted Access"
    AuthUserFile /etc/apache2/.htpasswd
    Require valid-user

    # ... 프록시 설정
</Location>
```

---

## 🐛 문제 해결

### 1. "502 Bad Gateway" 오류

**원인**: Streamlit 앱이 실행되지 않음

```bash
# 서비스 상태 확인
sudo systemctl status portfolio-monitor

# 수동 실행 테스트
cd /var/www/portfolio-monitor
source venv/bin/activate
streamlit run portfolio_monitor_app.py

# 로그 확인
sudo journalctl -u portfolio-monitor -n 100
```

### 2. WebSocket 연결 실패

**증상**: 앱이 로드되지만 데이터 업데이트 안 됨

**해결**:
```bash
# Apache 모듈 확인
sudo apache2ctl -M | grep proxy

# proxy_wstunnel 없으면 활성화
sudo a2enmod proxy_wstunnel
sudo systemctl restart apache2
```

### 3. 권한 오류

```bash
# 파일 권한 설정
sudo chown -R www-data:www-data /var/www/portfolio-monitor
sudo chmod -R 755 /var/www/portfolio-monitor

# config.yaml 읽기 권한 확인
sudo chmod 644 /var/www/portfolio-monitor/config.yaml
```

### 4. 모듈 임포트 실패

```bash
# Python 경로 확인
cd /var/www/portfolio-monitor
source venv/bin/activate
python3 -c "import sys; print('\n'.join(sys.path))"

# 패키지 재설치
pip3 install --upgrade -r requirements_app.txt
```

---

## 📱 모바일 접속

1. 모바일 브라우저에서 URL 접속
   - 서브도메인: `https://portfolio.your-domain.com`
   - 서브 경로: `https://your-domain.com/portfolio`

2. 비밀번호 입력

3. **홈 화면에 추가**
   - iOS Safari: 공유 → 홈 화면에 추가
   - Android Chrome: 메뉴 → 홈 화면에 추가

4. 앱 아이콘처럼 사용! 🎉

---

## 🔄 업데이트 방법

새 버전 배포 시:

```bash
# 로컬에서 새 파일 업로드
scp portfolio_monitor_app.py user@your-server.com:/var/www/portfolio-monitor/

# 서버에서 재시작
ssh user@your-server.com
sudo systemctl restart portfolio-monitor
```

---

## 📊 모니터링

```bash
# 실시간 로그 확인
sudo journalctl -u portfolio-monitor -f

# Apache 접속 로그
sudo tail -f /var/log/apache2/portfolio_access.log

# 에러 로그
sudo tail -f /var/log/apache2/portfolio_error.log

# 리소스 사용량
htop
```

---

## ⚙️ systemd 명령어 정리

```bash
# 시작
sudo systemctl start portfolio-monitor

# 중지
sudo systemctl stop portfolio-monitor

# 재시작
sudo systemctl restart portfolio-monitor

# 상태 확인
sudo systemctl status portfolio-monitor

# 부팅 시 자동 시작 활성화
sudo systemctl enable portfolio-monitor

# 부팅 시 자동 시작 비활성화
sudo systemctl disable portfolio-monitor

# 로그 보기
sudo journalctl -u portfolio-monitor -n 50  # 최근 50줄
sudo journalctl -u portfolio-monitor -f     # 실시간
```

---

완료! 이제 외부에서도 안전하게 포트폴리오를 모니터링할 수 있습니다! 🚀
