# Forex Risk Manager - Installation Guide

Production deployment guide for Forex Risk Manager.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Local Development](#local-development)
3. [Production Deployment](#production-deployment)
   - [VPS (Ubuntu/Debian)](#option-1-vps-ubuntudebian)
   - [Docker](#option-2-docker-deployment)
   - [PaaS](#option-3-platform-as-a-service)
4. [Configuration](#configuration)
5. [Admin Setup](#admin-setup)
6. [SSL Certificate](#ssl-certificate)
7. [Troubleshooting](#troubleshooting)

---

## Requirements

### System Requirements
- Python 3.10 or higher
- 1GB RAM minimum (2GB recommended)
- 10GB disk space

### Python Dependencies
```
flask
yfinance
pandas
numpy
scipy
statsmodels
scikit-learn
reportlab
requests
```

---

## Local Development

### 1. Clone Repository

```bash
git clone <repository-url>
cd forex-risk-manager
```

### 2. Create Virtual Environment

```bash
# Create venv
python -m venv .venv

# Activate - Windows
.venv\Scripts\activate

# Activate - Linux/Mac
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run Application

```bash
python app.py
```

### 5. Access Application

```
http://localhost:5000
```

### 6. Create Admin Account

```
http://localhost:5000/admin/create-admin
```

---

## Production Deployment

### Option 1: VPS (Ubuntu/Debian)

#### Step 1: Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
sudo apt install python3 python3-pip python3-venv nginx supervisor -y
```

#### Step 2: Create App User

```bash
# Create dedicated user
sudo useradd -m -s /bin/bash frm
sudo passwd frm
```

#### Step 3: Clone and Setup Application

```bash
# Create app directory
sudo mkdir -p /var/www/frm
cd /var/www/frm

# Clone repository
sudo git clone <repository-url> .

# Set ownership
sudo chown -R frm:frm /var/www/frm

# Switch to app user
sudo su - frm
cd /var/www/frm

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install gunicorn

# Exit back to root
exit
```

#### Step 4: Create Gunicorn Service

Create `/etc/supervisor/conf.d/frm.conf`:

```ini
[program:frm]
directory=/var/www/frm
command=/var/www/frm/.venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 app:app
user=frm
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stderr_logfile=/var/log/frm/error.log
stdout_logfile=/var/log/frm/access.log
environment=LANG=en_US.UTF-8,LC_ALL=en_US.UTF-8
```

```bash
# Create log directory
sudo mkdir -p /var/log/frm
sudo chown frm:frm /var/log/frm

# Reload supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start frm

# Check status
sudo supervisorctl status frm
```

#### Step 5: Configure Nginx

Create `/etc/nginx/sites-available/frm`:

```nginx
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_connect_timeout 300s;
        proxy_read_timeout 300s;
    }

    location /static {
        alias /var/www/frm/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Deny access to sensitive files
    location ~ /\. {
        deny all;
    }

    location ~ \.db$ {
        deny all;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/frm /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
```

#### Step 6: Set Permissions

```bash
# Set correct permissions
sudo chown -R frm:frm /var/www/frm
sudo chmod -R 755 /var/www/frm
sudo chmod 664 /var/www/frm/database.db

# Allow nginx to read static files
sudo usermod -a -G frm www-data
```

#### Step 7: Configure Firewall

```bash
# Allow HTTP and HTTPS
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

---

### Option 2: Docker Deployment

#### Step 1: Create Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application
COPY . .

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Set permissions for database
RUN chmod 664 database.db || true

EXPOSE 8000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
```

#### Step 2: Create docker-compose.yml

```yaml
version: '3.8'

services:
  frm:
    build: .
    container_name: frm_app
    ports:
      - "8000:8000"
    volumes:
      - ./database.db:/app/database.db
      - ./static:/app/static
    restart: unless-stopped
    environment:
      - FLASK_ENV=production

  nginx:
    image: nginx:alpine
    container_name: frm_nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - frm
    restart: unless-stopped
```

#### Step 3: Create nginx.conf for Docker

```nginx
server {
    listen 80;
    server_name localhost;

    location / {
        proxy_pass http://frm:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }

    location /static {
        alias /app/static;
        expires 30d;
    }
}
```

#### Step 4: Deploy

```bash
# Build and start
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

---

### Option 3: Platform as a Service

#### Railway.app

1. Create account at [railway.app](https://railway.app)
2. Connect GitHub repository
3. Add environment variables if needed
4. Deploy automatically on push

#### Render.com

1. Create account at [render.com](https://render.com)
2. Create new Web Service
3. Connect repository
4. Configure:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
5. Deploy

#### Heroku

```bash
# Login
heroku login

# Create Procfile
echo "web: gunicorn app:app" > Procfile

# Create app
heroku create your-app-name

# Deploy
git push heroku main

# Open app
heroku open
```

---

## Configuration

### Environment Variables

Create `.env` file (optional):

```env
# Flask
SECRET_KEY=your-super-secret-key-change-this
FLASK_ENV=production

# Database (if using MySQL)
DB_TYPE=sqlite
MYSQL_HOST=localhost
MYSQL_DATABASE=frm_db
MYSQL_USER=frm_user
MYSQL_PASSWORD=your-password
```

### Update Secret Key

In `app.py`, change:

```python
app.secret_key = os.environ.get('SECRET_KEY', 'your-default-secret-key')
```

### Database Backup

```bash
# Manual backup
cp /var/www/frm/database.db /backups/frm_$(date +%Y%m%d).db

# Automated backup (add to crontab)
crontab -e

# Add this line (backup at 2 AM daily)
0 2 * * * cp /var/www/frm/database.db /backups/frm_$(date +\%Y\%m\%d).db
```

---

## Admin Setup

### 1. Create First Admin

Visit: `https://yourdomain.com/admin/create-admin`

- Enter admin name, email, password
- This page only works if no admin exists

### 2. Configure Site URL

1. Go to Admin → Settings
2. In "Site Settings" section
3. Enter your domain: `https://yourdomain.com`
4. Save (required for email links to work correctly)

### 3. Configure Email (Zoho)

1. Go to Admin → Settings
2. Enable Email Sending
3. Enter SMTP settings:
   - Host: `smtp.zoho.com`
   - Port: `587`
   - Email: `your-email@yourdomain.com`
   - App Password: (from Zoho security settings)
   - Sender Name: `Forex Risk Manager`
4. Send test email to verify

### 4. Configure Midtrans

1. Go to Admin → Settings
2. Enter Midtrans Server Key and Client Key
3. Toggle Production/Sandbox mode
4. Set exchange rate (live or manual)
5. Test connection

### 5. Midtrans Webhook Setup

In Midtrans Dashboard:
1. Go to Settings → Configuration
2. Set Payment Notification URL: `https://yourdomain.com/payment-notification`
3. Enable HTTP notification

---

## SSL Certificate

### Using Let's Encrypt (Certbot)

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx -y

# Get certificate
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Auto-renewal (already set up by certbot)
sudo certbot renew --dry-run
```

### Using Cloudflare

1. Add domain to Cloudflare
2. Update nameservers
3. Enable "Full (strict)" SSL mode
4. Cloudflare handles SSL automatically

---

## Troubleshooting

### 1. Application Won't Start

```bash
# Check supervisor logs
sudo tail -f /var/log/frm/error.log

# Check supervisor status
sudo supervisorctl status frm

# Restart application
sudo supervisorctl restart frm
```

### 2. Database Locked Error

```bash
# Fix permissions
sudo chown frm:frm /var/www/frm/database.db
sudo chmod 664 /var/www/frm/database.db

# Restart app
sudo supervisorctl restart frm
```

### 3. Static Files Not Loading

```bash
# Check nginx config
sudo nginx -t

# Check file permissions
ls -la /var/www/frm/static/

# Restart nginx
sudo systemctl restart nginx
```

### 4. 502 Bad Gateway

```bash
# Check if gunicorn is running
sudo supervisorctl status frm

# Check if port 8000 is listening
sudo netstat -tlnp | grep 8000

# Restart both services
sudo supervisorctl restart frm
sudo systemctl restart nginx
```

### 5. Email Not Sending

- Check Zoho App Password (not regular password)
- Verify SMTP port (587 for TLS, 465 for SSL)
- Enable 2FA in Zoho and generate App Password
- Check spam folder

### 6. Password Reset Link Wrong Domain

1. Go to Admin → Settings
2. Set Site URL: `https://yourdomain.com`
3. Or ensure Nginx passes these headers:
   ```nginx
   proxy_set_header Host $host;
   proxy_set_header X-Forwarded-Proto $scheme;
   proxy_set_header X-Forwarded-Host $host;
   ```

### 7. Midtrans Webhook Not Working

- Verify webhook URL is HTTPS
- Check server logs for errors
- Test with Midtrans sandbox first
- Ensure firewall allows incoming connections

---

## Security Checklist

- [ ] Change default secret key
- [ ] Use HTTPS in production
- [ ] Set secure cookie flags
- [ ] Configure firewall (UFW)
- [ ] Regular database backups
- [ ] Keep dependencies updated
- [ ] Use strong admin password
- [ ] Set Site URL in admin settings
- [ ] Enable Midtrans production mode only when ready
- [ ] Restrict database file permissions

---

## Useful Commands

```bash
# View application logs
sudo tail -f /var/log/frm/error.log
sudo tail -f /var/log/frm/access.log

# Restart services
sudo supervisorctl restart frm
sudo systemctl restart nginx

# Check status
sudo supervisorctl status
sudo systemctl status nginx

# Update application
cd /var/www/frm
sudo -u frm git pull
sudo supervisorctl restart frm
```

---

*Last updated: December 2024*
