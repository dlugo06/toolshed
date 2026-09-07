---
name: debug-workflow
description: Systematic approach to debugging application issues.
---

# Command: Debug Workflow

Systematic approach to debugging application issues.

## Quick Diagnosis

### 1. Check System Health

```bash
# Service health checks
# TODO: Add your service-specific health checks

# Database connectivity
psql -d {your_db_dev} -c "SELECT 1"  # TODO: your DB name

# Environment variables loaded
python -c "import os; print('Config loaded:', bool(os.getenv('DATABASE_URL')))"  # TODO: your key env vars
```

### 2. Check Recent Logs

```bash
# View application logs
tail -f logs/app.log  # TODO: your log file path

# Filter for errors
grep "ERROR" logs/app.log | tail -20

# Filter by timestamp (last hour)
grep "$(date -u -d '1 hour ago' '+%Y-%m-%d %H')" logs/app.log
```

### 3. Check Database State

```bash
# Recent records
psql -d {your_db_dev} -c "  # TODO: your DB name and tables
  SELECT id, status, created_at
  FROM {your_table}
  ORDER BY created_at DESC
  LIMIT 10;
"
```

## Common Issues

### Issue: External Service Disconnected

**Symptoms**:
- No data being processed
- Log shows connection errors

**Debug Steps**:
```bash
# 1. Check service status
# TODO: your service health check

# 2. Check configuration
# TODO: verify config files

# 3. Restart the service
# TODO: your restart commands
```

---

### Issue: Data Fetching Fails

**Symptoms**:
- Records stuck in "pending" status
- Log shows timeout or fetch errors

**Debug Steps**:
```bash
# 1. Test with a sample request
python -c "
# TODO: Replace with your data fetching test
from src.module import Fetcher
fetcher = Fetcher()
result = fetcher.fetch('test-input')
print(result)
"

# 2. Check configuration
# TODO: your config file check

# 3. Run in debug mode
# TODO: your debug mode command
```

---

### Issue: API Errors

**Symptoms**:
- Processing completes but API calls fail
- Log shows API errors or rate limit responses

**Debug Steps**:
```bash
# 1. Check API key is valid
python -c "
import os
print('API key set:', bool(os.getenv('API_KEY')))  # TODO: your API key env var
"

# 2. Check recent API usage
grep "api" logs/app.log | tail -20

# 3. Test with sample data
python -c "
# TODO: Replace with your API test
from src.module import Client
client = Client()
result = client.call('test')
print(result)
"
```

---

### Issue: Database Connection Lost

**Symptoms**:
- Data not saving
- Log shows database connection errors

**Debug Steps**:
```bash
# 1. Check PostgreSQL running
pg_isready

# 2. Test connection
psql -d {your_db_dev} -c "SELECT version()"  # TODO: your DB name

# 3. Check connection pool
python -c "
from src.database.connection import engine  # TODO: your connection module
with engine.connect() as conn:
    result = conn.execute('SELECT 1')
    print('Connection OK:', result.fetchone())
"
```

**Common Fixes**:
- PostgreSQL not running → `brew services start postgresql`
- Database doesn't exist → `createdb {your_db_dev}`
- Wrong credentials → Check `DATABASE_URL` in `.env`

---

## Systematic Debugging Workflow

### Step 1: Gather Context

```bash
# 1. Read relevant code
# TODO: your key source files

# 2. Check recent records
psql -d {your_db_dev} -c "  # TODO: your DB name
  SELECT * FROM {your_table}
  WHERE created_at > NOW() - INTERVAL '1 hour'
  ORDER BY created_at DESC;
"
```

### Step 2: Reproduce Issue

```bash
# Run failing test
pytest tests/test_module.py::test_function -vv  # TODO: your test

# Or test directly
python -c "
# TODO: Your reproduction code
"
```

### Step 3: Add Debug Logging

```python
# Temporarily add to code
# TODO: Use your project's logging library
import logging
logger = logging.getLogger(__name__)

def process(self, input):
    logger.debug("processing", extra={"input": input})
    # ... rest of code
```

### Step 4: Validate Fix

```bash
# 1. Run specific test
pytest tests/test_module.py -v  # TODO: your test

# 2. Check data created correctly
psql -d {your_db_dev} -c "  # TODO: your DB name
  SELECT * FROM {your_table}
  ORDER BY created_at DESC
  LIMIT 1;
"
```

## Database Debugging

### View Query Performance

```sql
-- Enable query logging
ALTER DATABASE {your_db_dev} SET log_statement = 'all';  -- TODO: your DB name

-- View slow queries
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY total_time DESC
LIMIT 10;
```

### Rollback Failed Migration

```bash
# Check current migration
alembic current  # TODO: your migration tool

# View migration history
alembic history

# Rollback last migration
alembic downgrade -1
```

## Emergency Recovery

### Stop All Processes

```bash
# Kill application processes
pkill -f "python src/main.py"  # TODO: your process names
```

### Reset Database

```bash
# Backup current data
pg_dump {your_db_dev} > backup_$(date +%Y%m%d_%H%M%S).sql  # TODO: your DB name

# Drop and recreate
dropdb {your_db_dev}
createdb {your_db_dev}

# Run migrations
alembic upgrade head  # TODO: your migration command
```
