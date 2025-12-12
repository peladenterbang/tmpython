# Database Migration Guide

Migrate Forex Risk Manager from SQLite to MySQL.

---

## Table of Contents

1. [Why Migrate?](#why-migrate-to-mysql)
2. [Prerequisites](#prerequisites)
3. [Migration Steps](#migration-steps)
4. [Update Application](#update-application-code)
5. [Testing](#testing)
6. [Rollback](#rollback-plan)

---

## Why Migrate to MySQL?

### Comparison

| Feature | SQLite | MySQL |
|---------|--------|-------|
| Architecture | Single file | Client-server |
| Concurrent writes | Limited | Excellent |
| Scalability | Small/Medium | Large scale |
| User management | None | Full permissions |
| Max practical size | ~1GB | Unlimited |
| Backup options | File copy | Multiple methods |
| Replication | Not built-in | Master-slave support |

### When to Migrate

- Multiple users accessing simultaneously
- Database size exceeds 500MB
- Need better backup/replication
- Require user-level permissions
- High-traffic production environment

---

## Prerequisites

- MySQL 8.0+ installed
- Python MySQL connector
- Backup of SQLite database
- Application downtime window (10-30 minutes)

---

## Migration Steps

### Step 1: Install MySQL Server

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install mysql-server mysql-client -y
sudo mysql_secure_installation
```

#### Start MySQL
```bash
sudo systemctl start mysql
sudo systemctl enable mysql
```

### Step 2: Create Database & User

```bash
sudo mysql -u root -p
```

```sql
-- Create database
CREATE DATABASE frm_db 
  CHARACTER SET utf8mb4 
  COLLATE utf8mb4_unicode_ci;

-- Create user
CREATE USER 'frm_user'@'localhost' 
  IDENTIFIED BY 'YourStrongPassword123!';

-- Grant privileges
GRANT ALL PRIVILEGES ON frm_db.* TO 'frm_user'@'localhost';
FLUSH PRIVILEGES;

EXIT;
```

### Step 3: Install Python MySQL Connector

```bash
source .venv/bin/activate
pip install mysql-connector-python pymysql
```

### Step 4: Create MySQL Schema

Create file `mysql_schema.sql`:

```sql
USE frm_db;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password BLOB NOT NULL,
    is_admin TINYINT(1) DEFAULT 0,
    subscription_plan VARCHAR(20) DEFAULT 'free',
    subscription_expires DATETIME,
    telegram_bot_token VARCHAR(100),
    telegram_chat_id VARCHAR(50),
    reset_token VARCHAR(100),
    reset_token_expires DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email (email),
    INDEX idx_subscription (subscription_plan)
) ENGINE=InnoDB;

-- Account table
CREATE TABLE IF NOT EXISTS account (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    initial_balance DECIMAL(15,2) NOT NULL,
    current_balance DECIMAL(15,2) NOT NULL,
    max_drawdown_percent DECIMAL(5,2) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user (user_id)
) ENGINE=InnoDB;

-- Trades table
CREATE TABLE IF NOT EXISTS trades (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    pair VARCHAR(20) NOT NULL,
    trade_type VARCHAR(10) NOT NULL,
    lot_size DECIMAL(10,4) NOT NULL,
    entry_price DECIMAL(20,6) NOT NULL,
    exit_price DECIMAL(20,6),
    stop_loss DECIMAL(20,6),
    take_profit DECIMAL(20,6),
    profit_loss DECIMAL(15,2) DEFAULT 0,
    risk_percent DECIMAL(5,2),
    status VARCHAR(20) DEFAULT 'open',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_status (user_id, status),
    INDEX idx_pair (pair)
) ENGINE=InnoDB;

-- Payments table
CREATE TABLE IF NOT EXISTS payments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    order_id VARCHAR(100),
    plan VARCHAR(20) DEFAULT 'basic',
    amount DECIMAL(10,2) DEFAULT 0,
    amount_usd DECIMAL(10,2) DEFAULT 0,
    amount_idr BIGINT DEFAULT 0,
    exchange_rate DECIMAL(10,2) DEFAULT 15500,
    status VARCHAR(20) DEFAULT 'pending',
    payment_type VARCHAR(50),
    payment_method VARCHAR(50),
    transaction_id VARCHAR(100),
    midtrans_transaction_id VARCHAR(100),
    midtrans_status VARCHAR(50),
    fraud_status VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    paid_at DATETIME,
    expires_at DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_order (order_id),
    INDEX idx_status (status),
    INDEX idx_user (user_id)
) ENGINE=InnoDB;

-- Usage tracking table
CREATE TABLE IF NOT EXISTS usage_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    action_type VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_date (user_id, created_at)
) ENGINE=InnoDB;

-- Analysis cache table
CREATE TABLE IF NOT EXISTS analysis_cache (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    analysis_type VARCHAR(20),
    pair VARCHAR(20),
    timeframe VARCHAR(10),
    signal VARCHAR(10),
    strength DECIMAL(5,2),
    entry_price DECIMAL(20,6),
    trend_score DECIMAL(5,2),
    rsi DECIMAL(5,2),
    confidence DECIMAL(5,2),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_type (user_id, analysis_type),
    INDEX idx_pair_tf (pair, timeframe)
) ENGINE=InnoDB;

-- App settings table
CREATE TABLE IF NOT EXISTS app_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) UNIQUE NOT NULL,
    setting_value TEXT,
    INDEX idx_key (setting_key)
) ENGINE=InnoDB;

-- Auto settings table
CREATE TABLE IF NOT EXISTS auto_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT UNIQUE,
    enabled TINYINT(1) DEFAULT 0,
    selected_pairs TEXT,
    max_trades_per_day INT DEFAULT 5,
    risk_per_trade DECIMAL(5,2) DEFAULT 1.0,
    min_probability DECIMAL(5,2) DEFAULT 70.0,
    telegram_alerts TINYINT(1) DEFAULT 1,
    trading_method VARCHAR(20) DEFAULT 'ML',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Auto executions table
CREATE TABLE IF NOT EXISTS auto_executions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    pair VARCHAR(20),
    direction VARCHAR(10),
    entry_price DECIMAL(20,6),
    current_price DECIMAL(20,6),
    stop_loss DECIMAL(20,6),
    take_profit DECIMAL(20,6),
    lots DECIMAL(10,4),
    probability DECIMAL(5,2),
    pnl DECIMAL(15,2) DEFAULT 0,
    pnl_pips DECIMAL(10,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'open',
    exit_reason VARCHAR(50),
    is_correct TINYINT(1),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_status (user_id, status),
    INDEX idx_pair (pair)
) ENGINE=InnoDB;

-- Auto execution logs table
CREATE TABLE IF NOT EXISTS auto_execution_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    action VARCHAR(50),
    pair VARCHAR(20),
    details TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_date (user_id, created_at)
) ENGINE=InnoDB;
```

Run the schema:
```bash
mysql -u frm_user -p frm_db < mysql_schema.sql
```

### Step 5: Create Migration Script

Create file `migrate_to_mysql.py`:

```python
#!/usr/bin/env python3
"""
Migration script: SQLite to MySQL
"""

import sqlite3
import mysql.connector
from mysql.connector import Error
import sys

# Configuration - UPDATE THESE
SQLITE_DB = 'database.db'
MYSQL_CONFIG = {
    'host': 'localhost',
    'database': 'frm_db',
    'user': 'frm_user',
    'password': 'YourStrongPassword123!'
}

# Tables to migrate (order matters for foreign keys)
TABLES = [
    'users',
    'account',
    'trades',
    'payments',
    'usage_tracking',
    'analysis_cache',
    'app_settings',
    'auto_settings',
    'auto_executions',
    'auto_execution_logs'
]


def get_sqlite_connection():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_mysql_connection():
    return mysql.connector.connect(**MYSQL_CONFIG)


def get_columns(sqlite_cursor, table):
    sqlite_cursor.execute(f"PRAGMA table_info({table})")
    return [col[1] for col in sqlite_cursor.fetchall()]


def migrate_table(table):
    print(f"\nMigrating: {table}")
    
    sqlite_conn = get_sqlite_connection()
    sqlite_cursor = sqlite_conn.cursor()
    
    mysql_conn = get_mysql_connection()
    mysql_cursor = mysql_conn.cursor()
    
    try:
        # Get data from SQLite
        sqlite_cursor.execute(f"SELECT * FROM {table}")
        rows = sqlite_cursor.fetchall()
        
        if not rows:
            print(f"  No data in {table}")
            return 0
        
        # Get column names
        columns = get_columns(sqlite_cursor, table)
        
        # Prepare INSERT statement
        placeholders = ', '.join(['%s'] * len(columns))
        columns_str = ', '.join(columns)
        insert_sql = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"
        
        # Insert data
        count = 0
        for row in rows:
            try:
                values = tuple(row)
                mysql_cursor.execute(insert_sql, values)
                count += 1
            except Error as e:
                print(f"  Error inserting row: {e}")
                continue
        
        mysql_conn.commit()
        print(f"  Migrated {count} rows")
        return count
        
    except Exception as e:
        print(f"  Error: {e}")
        return 0
    finally:
        sqlite_conn.close()
        mysql_conn.close()


def reset_auto_increment():
    """Reset auto increment values after migration"""
    print("\nResetting auto increment values...")
    
    mysql_conn = get_mysql_connection()
    mysql_cursor = mysql_conn.cursor()
    
    for table in TABLES:
        try:
            mysql_cursor.execute(f"SELECT MAX(id) FROM {table}")
            max_id = mysql_cursor.fetchone()[0]
            if max_id:
                mysql_cursor.execute(
                    f"ALTER TABLE {table} AUTO_INCREMENT = {max_id + 1}"
                )
                print(f"  {table}: AUTO_INCREMENT = {max_id + 1}")
        except:
            pass
    
    mysql_conn.commit()
    mysql_conn.close()


def verify_migration():
    """Verify row counts match"""
    print("\nVerifying migration...")
    
    sqlite_conn = get_sqlite_connection()
    sqlite_cursor = sqlite_conn.cursor()
    
    mysql_conn = get_mysql_connection()
    mysql_cursor = mysql_conn.cursor()
    
    all_match = True
    for table in TABLES:
        try:
            sqlite_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            sqlite_count = sqlite_cursor.fetchone()[0]
            
            mysql_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            mysql_count = mysql_cursor.fetchone()[0]
            
            status = "OK" if sqlite_count == mysql_count else "MISMATCH"
            if sqlite_count != mysql_count:
                all_match = False
            
            print(f"  {table}: SQLite={sqlite_count}, MySQL={mysql_count} [{status}]")
        except Exception as e:
            print(f"  {table}: Error - {e}")
            all_match = False
    
    sqlite_conn.close()
    mysql_conn.close()
    
    return all_match


def main():
    print("=" * 50)
    print("SQLite to MySQL Migration")
    print("=" * 50)
    
    # Test connections
    print("\nTesting connections...")
    try:
        conn = get_sqlite_connection()
        conn.close()
        print("  SQLite: OK")
    except Exception as e:
        print(f"  SQLite: FAILED - {e}")
        sys.exit(1)
    
    try:
        conn = get_mysql_connection()
        conn.close()
        print("  MySQL: OK")
    except Exception as e:
        print(f"  MySQL: FAILED - {e}")
        sys.exit(1)
    
    # Migrate each table
    total_rows = 0
    for table in TABLES:
        total_rows += migrate_table(table)
    
    # Reset auto increment
    reset_auto_increment()
    
    # Verify
    success = verify_migration()
    
    print("\n" + "=" * 50)
    if success:
        print("Migration COMPLETED SUCCESSFULLY")
    else:
        print("Migration COMPLETED WITH WARNINGS")
    print(f"Total rows migrated: {total_rows}")
    print("=" * 50)


if __name__ == '__main__':
    main()
```

Run the migration:
```bash
python migrate_to_mysql.py
```

---

## Update Application Code

### Step 1: Create Database Config

Create file `db_config.py`:

```python
"""Database configuration module"""

import os

# Database type: 'sqlite' or 'mysql'
DB_TYPE = os.environ.get('DB_TYPE', 'sqlite')

# MySQL Configuration
MYSQL_CONFIG = {
    'host': os.environ.get('MYSQL_HOST', 'localhost'),
    'database': os.environ.get('MYSQL_DATABASE', 'frm_db'),
    'user': os.environ.get('MYSQL_USER', 'frm_user'),
    'password': os.environ.get('MYSQL_PASSWORD', ''),
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci',
    'autocommit': False
}

# SQLite Configuration
SQLITE_PATH = 'database.db'
```

### Step 2: Update app.py

Add at top of `app.py`:

```python
from db_config import DB_TYPE, MYSQL_CONFIG, SQLITE_PATH

if DB_TYPE == 'mysql':
    import mysql.connector
    from mysql.connector import Error
```

Replace the `get_db()` function:

```python
def get_db():
    """Get database connection based on DB_TYPE"""
    if DB_TYPE == 'mysql':
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        conn.autocommit = False
        return conn
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def dict_from_row(row, cursor=None):
    """Convert database row to dictionary"""
    if DB_TYPE == 'mysql':
        if cursor:
            columns = [col[0] for col in cursor.description]
            return dict(zip(columns, row))
        return row
    else:
        return dict(row)
```

### Step 3: Handle Parameter Placeholders

SQLite uses `?`, MySQL uses `%s`. Create a wrapper:

```python
def execute_query(conn, query, params=None):
    """Execute query with proper placeholder conversion"""
    if DB_TYPE == 'mysql':
        query = query.replace('?', '%s')
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    return cursor
```

### Step 4: Set Environment Variables

```bash
# Linux/Mac
export DB_TYPE=mysql
export MYSQL_HOST=localhost
export MYSQL_DATABASE=frm_db
export MYSQL_USER=frm_user
export MYSQL_PASSWORD=YourStrongPassword123!
```

For Supervisor, add to config:
```ini
environment=DB_TYPE="mysql",MYSQL_HOST="localhost",MYSQL_DATABASE="frm_db",MYSQL_USER="frm_user",MYSQL_PASSWORD="YourPassword"
```

---

## Testing

### 1. Test Database Connection

```python
python -c "from app import get_db; conn = get_db(); print('Connection OK'); conn.close()"
```

### 2. Test All Features

- [ ] User login/register
- [ ] Dashboard loads
- [ ] Trade journal CRUD
- [ ] Technical analysis
- [ ] ICT analysis
- [ ] ML predictions
- [ ] ARIMA forecasting
- [ ] Auto execution
- [ ] Payment processing
- [ ] Admin panel

### 3. Performance Test

```bash
# Install Apache Bench
sudo apt install apache2-utils

# Test homepage (100 requests, 10 concurrent)
ab -n 100 -c 10 http://localhost:8000/
```

---

## MySQL Optimization

Add to `/etc/mysql/mysql.conf.d/mysqld.cnf`:

```ini
[mysqld]
# InnoDB settings
innodb_buffer_pool_size = 256M
innodb_log_file_size = 64M
innodb_flush_log_at_trx_commit = 2

# Connection settings
max_connections = 100
wait_timeout = 600

# Character set
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
```

Restart MySQL:
```bash
sudo systemctl restart mysql
```

---

## MySQL Backup

### Manual Backup

```bash
mysqldump -u frm_user -p frm_db > backup_$(date +%Y%m%d).sql
```

### Restore from Backup

```bash
mysql -u frm_user -p frm_db < backup_20241212.sql
```

### Automated Backup (Cron)

```bash
crontab -e
```

Add:
```
0 2 * * * mysqldump -u frm_user -pYourPassword frm_db > /backups/frm_$(date +\%Y\%m\%d).sql
```

---

## Rollback Plan

If migration fails, rollback to SQLite:

### Step 1: Switch Back to SQLite

```bash
export DB_TYPE=sqlite
```

Or remove environment variables.

### Step 2: Restart Application

```bash
sudo supervisorctl restart frm
```

### Step 3: Verify

Your SQLite database (`database.db`) remains untouched during migration.

---

## Migration Checklist

Pre-Migration:
- [ ] Backup SQLite database
- [ ] Install MySQL server
- [ ] Create database and user
- [ ] Install Python MySQL connector
- [ ] Test MySQL connection

Migration:
- [ ] Create MySQL schema
- [ ] Run migration script
- [ ] Verify row counts

Post-Migration:
- [ ] Update application code
- [ ] Set environment variables
- [ ] Restart application
- [ ] Test all features
- [ ] Setup MySQL backups
- [ ] Monitor for errors

---

## Common Issues

### 1. Connection Refused

```bash
# Check MySQL is running
sudo systemctl status mysql

# Check user can connect
mysql -u frm_user -p frm_db
```

### 2. Access Denied

```sql
-- Grant proper permissions
GRANT ALL PRIVILEGES ON frm_db.* TO 'frm_user'@'localhost';
FLUSH PRIVILEGES;
```

### 3. Character Set Issues

```sql
-- Fix character set
ALTER DATABASE frm_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 4. Foreign Key Errors

Migrate tables in correct order (users first, then dependent tables).

---

*Last updated: December 2024*
