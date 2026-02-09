# ✅ Apache 배포 체크리스트

간단한 단계별 체크리스트

---

## 📦 1. 파일 준비 (로컬)

```bash
cd /Users/jsshin/RESTAPI/trading_system

# ✅ 파일 압축
tar -czf portfolio-app.tar.gz \
    portfolio_monitor_app.py \
    requirements_app.txt \
    config.yaml \
    config/ data/ notification/ trading/ utils/

# ✅ 서버 업로드
scp portfolio-app.tar.gz user@your-server.com:/tmp/
```

---

## 🖥️ 2. 서버 설정

```bash
# ✅ SSH 접속
ssh user@your-server.com

# ✅ 디렉토리 생성 및 압축 해제
sudo mkdir -p /var/www/portfolio-monitor
sudo chown $USER:$USER /var/www/portfolio-monitor
cd /var/www/portfolio-monitor
tar -xzf /tmp/portfolio-app.tar.gz

# ✅ Python 패키지 설치
python3 -m venv venv
source venv/bin/activate
pip3 install streamlit plotly pandas pyyaml requests beautifulsoup4 pymysql
```

---

## ⚙️ 3. systemd 서비스 생성

```bash
# ✅ 서비스 파일 생성
sudo nano /etc/systemd/system/portfolio-monitor.service
```

**내용 붙여넣기 (비밀번호 변경!):**

```ini
[Unit]
Description=Portfolio Monitor Streamlit App
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/portfolio-monitor
Environment="APP_PASSWORD=YOUR_PASSWORD_HERE"
Environment="PATH=/var/www/portfolio-monitor/venv/bin:/usr/bin:/bin"
ExecStart=/var/www/portfolio-monitor/venv/bin/streamlit run portfolio_monitor_app.py --server.port=8501 --server.address=127.0.0.1 --server.headless=true
Restart=always

[Install]
WantedBy=multi-user.target
```

**서비스 시작:**

```bash
# ✅ 서비스 활성화
sudo systemctl daemon-reload
sudo systemctl start portfolio-monitor
sudo systemctl enable portfolio-monitor
sudo systemctl status portfolio-monitor  # 확인
```

---

## 🌐 4. Apache 설정

```bash
# ✅ 모듈 활성화
sudo a2enmod proxy proxy_http proxy_wstunnel rewrite headers

# ✅ VirtualHost 설정
sudo nano /etc/apache2/sites-available/portfolio.your-domain.com.conf
```

**서브도메인 설정 (추천):**

```apache
<VirtualHost *:80>
    ServerName portfolio.your-domain.com
    RewriteEngine On
    RewriteRule ^(.*)$ https://%{HTTP_HOST}$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName portfolio.your-domain.com

    # Streamlit 프록시
    ProxyPreserveHost On
    ProxyRequests Off

    # WebSocket 지원
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} =websocket [NC]
    RewriteRule /(.*)  ws://127.0.0.1:8501/$1 [P,L]
    RewriteCond %{HTTP:Upgrade} !=websocket [NC]
    RewriteRule /(.*)  http://127.0.0.1:8501/$1 [P,L]

    ProxyPass / http://127.0.0.1:8501/
    ProxyPassReverse / http://127.0.0.1:8501/

    <Location />
        RequestHeader set X-Forwarded-Proto "https"
    </Location>
</VirtualHost>
```

**활성화:**

```bash
# ✅ 사이트 활성화
sudo a2ensite portfolio.your-domain.com.conf
sudo apache2ctl configtest  # 설정 테스트
sudo systemctl restart apache2
```

---

## 🔐 5. SSL 설정

```bash
# ✅ Certbot 설치
sudo apt update
sudo apt install certbot python3-certbot-apache

# ✅ SSL 인증서 발급
sudo certbot --apache -d portfolio.your-domain.com

# ✅ 자동 갱신 확인
sudo certbot renew --dry-run
```

---

## ✅ 6. 테스트

```bash
# ✅ 서비스 상태
sudo systemctl status portfolio-monitor

# ✅ 로컬 테스트
curl http://127.0.0.1:8501

# ✅ 로그 확인
sudo journalctl -u portfolio-monitor -n 50
```

**브라우저 접속:**
- https://portfolio.your-domain.com

---

## 🎉 완료!

모바일에서도 접속 → 홈 화면 추가 → 앱처럼 사용!

---

## 🔧 자주 쓰는 명령어

```bash
# 재시작
sudo systemctl restart portfolio-monitor
sudo systemctl restart apache2

# 로그 보기
sudo journalctl -u portfolio-monitor -f
sudo tail -f /var/log/apache2/error.log

# 업데이트 (로컬에서)
scp portfolio_monitor_app.py user@server:/var/www/portfolio-monitor/
ssh user@server "sudo systemctl restart portfolio-monitor"
```
