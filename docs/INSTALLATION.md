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

### Option 1: VPS (Ubuntu/Debian) with systemd

This is the recommended method for a standard Linux server. It uses `systemd` to manage the application and scheduler processes.

#### Step 1: Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python, Nginx, and other required tools
sudo apt install python3 python3-pip python3-venv nginx -y
```

#### Step 2: Create Application User

```bash
# Create a dedicated non-root user for the application
sudo useradd -m -s /bin/bash frm
sudo passwd frm
```

#### Step 3: Clone and Setup Application

```bash
# Create application directory
sudo mkdir -p /var/www/frm
cd /var/www/frm

# Clone the repository into the directory
sudo git clone <repository-url> .

# Set correct ownership for the application directory
sudo chown -R frm:frm /var/www/frm

# Switch to the new application user
sudo su - frm
cd /var/www/frm

# Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies, including gunicorn for production
pip install -r requirements.txt
pip install gunicorn

# Exit back to your root/sudo user
exit
```

#### Step 4: Create systemd Services

You need two services: one for the web application (Gunicorn) and one for the scheduler.

**1. Web Service (`frm-web.service`)**

Create a service file for Gunicorn:
```bash
sudo nano /etc/systemd/system/frm-web.service
```

Paste the following content:
```ini
[Unit]
Description=Gunicorn instance for Forex Risk Manager Web App
After=network.target

[Service]
User=frm
Group=www-data
WorkingDirectory=/var/www/frm
Environment="PATH=/var/www/frm/.venv/bin"
ExecStart=/var/www/frm/.venv/bin/gunicorn --workers 4 --bind 127.0.0.1:8000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

**2. Scheduler Service (`frm-scheduler.service`)**

Create a service file for the auto-scheduler:
```bash
sudo nano /etc/systemd/system/frm-scheduler.service
```

Paste the following content:
```ini
[Unit]
Description=Scheduler for Forex Risk Manager
After=network.target

[Service]
User=frm
WorkingDirectory=/var/www/frm
Environment="PATH=/var/www/frm/.venv/bin"
ExecStart=/var/www/frm/.venv/bin/python auto_scheduler.py
Restart=always

[Install]
WantedBy=multi-user.target
```

**3. Start and Enable the Services**

```bash
# Reload systemd to recognize the new services
sudo systemctl daemon-reload

# Start both services
sudo systemctl start frm-web.service
sudo systemctl start frm-scheduler.service

# Enable them to start on boot
sudo systemctl enable frm-web.service
sudo systemctl enable frm-scheduler.service

# Check their status to ensure they are running
sudo systemctl status frm-web.service
sudo systemctl status frm-scheduler.service
```

#### Step 5: Configure Nginx as a Reverse Proxy

Create an Nginx configuration file:
```bash
sudo nano /etc/nginx/sites-available/frm
```

Paste the following configuration, replacing `yourdomain.com` with your actual domain name.
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
# Enable the site by creating a symlink
sudo ln -s /etc/nginx/sites-available/frm /etc/nginx/sites-enabled/

# It's a good idea to remove the default Nginx site
sudo rm /etc/nginx/sites-enabled/default

# Test your Nginx configuration for syntax errors
sudo nginx -t

# Restart Nginx to apply the changes
sudo systemctl restart nginx
```

#### Step 6: Final Permissions & Firewall

```bash
# Add the web server user to the app group to allow access
sudo usermod -a -G frm www-data

# Set correct permissions for the database file
sudo chown frm:frm /var/www/frm/database.db
sudo chmod 664 /var/www/frm/database.db

# Allow Nginx through the firewall
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

---

### Option 2: Docker Deployment

#### Step 1: Create Dockerfile

This `Dockerfile` will serve as the base for both the web and scheduler services.

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY . .

# Create a non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Set permissions for database (might fail if file doesn't exist yet, so `|| true` is used)
RUN chmod 664 database.db || true

# Expose port for Gunicorn
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
```

#### Step 2: Create docker-compose.yml

This file defines the web, scheduler, and Nginx services.

```yaml
version: '3.8'

services:
  frm-web:
    build: .
    container_name: frm_web
    command: ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:app"]
    volumes:
      - ./database.db:/app/database.db
      - ./static:/app/static
    restart: unless-stopped
    environment:
      - FLASK_ENV=production

  frm-scheduler:
    build: .
    container_name: frm_scheduler
    command: ["python", "auto_scheduler.py"]
    volumes:
      - ./database.db:/app/database.db
    restart: unless-stopped
    depends_on:
      - frm-web

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
      - frm-web
    restart: unless-stopped
```

#### Step 3: Create nginx.conf for Docker

Note the `proxy_pass` directive points to the `frm-web` service.

```nginx
server {
    listen 80;
    server_name localhost;

    location / {
        proxy_pass http://frm-web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /app/static;
        expires 30d;
    }
}
```

#### Step 4: Deploy with Docker Compose

```bash
# Build and start all services in detached mode
docker-compose up -d --build

# View logs for all services
docker-compose logs -f

# View logs for a specific service (e.g., scheduler)
docker-compose logs -f frm-scheduler

# Stop and remove containers
docker-compose down
```

---

### Option 3: Platform as a Service (PaaS)

#### Heroku

1.  **Create a `Procfile`** in your project root. This tells Heroku how to run your processes.
    ```
    web: gunicorn app:app
    worker: python auto_scheduler.py
    ```

2.  **Deploy your application.**
    ```bash
    # Login to Heroku
    heroku login

    # Create a new Heroku app
    heroku create your-app-name

    # Push your code to deploy
    git push heroku main
    ```

3.  **Scale your processes.** By default, only the `web` process runs. You need to enable the `worker`.
    ```bash
    heroku ps:scale worker=1
    ```

#### Render.com

1.  Create a new **Web Service** for the main application:
    -   **Repository**: Connect your GitHub repository.
    -   **Build Command**: `pip install -r requirements.txt gunicorn`
    -   **Start Command**: `gunicorn app:app`

2.  Create a new **Background Worker** for the scheduler:
    -   **Repository**: Connect the same GitHub repository.
    -   **Build Command**: `pip install -r requirements.txt`
    -   **Start Command**: `python auto_scheduler.py`
    -   Ensure the Background Worker has access to the same database if you are using a managed database service on Render.

#### Railway.app

Railway can often auto-detect a `Procfile` (see Heroku instructions). If you configure your services manually:

1.  Create two services pointing to the same GitHub repository.
2.  **Service 1 (Web)**: Set the start command to `gunicorn app:app`. Expose port 80/443.
3.  **Service 2 (Scheduler)**: Set the start command to `python auto_scheduler.py`. Do not expose any port.

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
# Check the logs for the web and scheduler services
sudo journalctl -u frm-web.service -f
sudo journalctl -u frm-scheduler.service -f

# Check the status of the services
sudo systemctl status frm-web.service
sudo systemctl status frm-scheduler.service

# Restart the services
sudo systemctl restart frm-web frm-scheduler
```

### 2. Database Locked Error

This can happen if multiple processes are trying to write to the SQLite database simultaneously. The new `systemd` setup with a single scheduler should minimize this.

```bash
# Fix permissions
sudo chown frm:frm /var/www/frm/database.db
sudo chmod 664 /var/www/frm/database.db

# Restart the applications
sudo systemctl restart frm-web frm-scheduler
```

### 3. Static Files Not Loading (404 errors)

```bash
# Ensure your Nginx configuration is correct
sudo nginx -t

# Check that the file permissions allow the `www-data` user to read them
ls -la /var/www/frm/static/

# Restart Nginx
sudo systemctl restart nginx
```

### 4. 502 Bad Gateway

This error means Nginx cannot communicate with the Gunicorn process.

```bash
# Check if the web service is running
sudo systemctl status frm-web.service

# Check that Gunicorn is listening on the correct port
sudo netstat -tlnp | grep 8000

# Restart both the web service and Nginx
sudo systemctl restart frm-web
sudo systemctl restart nginx
```

### 5. Email Not Sending

- Check Zoho App Password (it should not be your regular login password).
- Verify SMTP port (587 for TLS, 465 for SSL).
- Ensure you have enabled 2FA in Zoho and generated an App Password.
- Check your email's spam folder.

### 6. Password Reset Link Wrong Domain

This happens when the application doesn't know its public URL.

1. Go to **Admin → Settings**.
2. Set the **Site URL** to `https://yourdomain.com`.
3. Alternatively, ensure your Nginx config includes the `X-Forwarded-*` headers as shown in the setup guide.

### 7. Midtrans Webhook Not Working

- Verify your webhook URL in the Midtrans dashboard is correct and uses `https`.
- Check the application logs (`journalctl -u frm-web.service -f`) for errors when a payment occurs.
- Test with the Midtrans sandbox environment first.
- Ensure your firewall (UFW) allows incoming HTTPS connections.

---

## Security Checklist

- [ ] Change default `SECRET_KEY` in your environment.
- [ ] Use HTTPS in production with a valid SSL certificate.
- [ ] Configure firewall (UFW) to only allow necessary ports (e.g., 80, 443, 22).
- [ ] Set up regular, automated database backups.
- [ ] Keep system packages and Python dependencies updated.
- [ ] Use a strong, unique password for the admin account.
- [ ] Set the correct Site URL in the admin settings.
- [ ] Restrict database file permissions (`chmod 664`).

---

## Useful Commands

```bash
# View live logs for the web app
sudo journalctl -u frm-web.service -f

# View live logs for the scheduler
sudo journalctl -u frm-scheduler.service -f

# Restart both services
sudo systemctl restart frm-web frm-scheduler

# Restart just Nginx
sudo systemctl restart nginx

# Check status of services
sudo systemctl status frm-web
sudo systemctl status frm-scheduler
sudo systemctl status nginx

# Update the application from git
cd /var/www/frm
sudo -u frm git pull
pip install -r requirements.txt # As the 'frm' user in the venv
sudo systemctl restart frm-web frm-scheduler
```

---

*Last updated: December 2024*
