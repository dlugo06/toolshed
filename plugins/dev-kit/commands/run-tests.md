---
name: run-tests
description: Run and configure test suites.
---

# Command: Run Tests

Execute test suites with various options.

## Basic Usage

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_example.py  # TODO: your test file

# Run specific test function
pytest tests/test_example.py::test_function_name
```

## Test Categories

```bash
# Unit tests only (fast, no external dependencies)
pytest -m unit

# Integration tests (with external dependencies)
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

Automated end-to-end UI/browser testing is retired. Integration tests (`@pytest.mark.integration`, externals mocked) are the primary automated gate; the owner verifies manually in production after deploy.

## Coverage Reports

```bash
# Terminal coverage
pytest --cov=src --cov-report=term

# HTML coverage report (opens in browser)
pytest --cov=src --cov-report=html && open htmlcov/index.html

# Fail if coverage below threshold
pytest --cov=src --cov-fail-under=70  # TODO: adjust threshold
```

## Debugging Tests

```bash
# Show print statements
pytest -s

# Show full diff on assertion failure
pytest -vv

# Stop on first failure
pytest -x

# Drop into debugger on failure
pytest --pdb

# Show local variables on failure
pytest -l
```

## Common Workflows

### Quick Feedback (Development)

```bash
# Run only fast unit tests
pytest -m unit -v
```

### Pre-Commit Check

```bash
# Run unit tests with coverage
pytest -m unit --cov=src --cov-report=term-missing
```

### Full Test Suite (CI/CD)

```bash
# Run all tests with coverage report
pytest --cov=src --cov-report=html --cov-fail-under=70
```

## Test Output

### Successful Run
```
tests/test_example.py::test_function_name PASSED [100%]

====== 15 passed in 2.43s ======
```

### Failed Test
```
tests/test_example.py::test_function_name FAILED [66%]

FAILED tests/test_example.py::test_function_name
AssertionError: assert actual == expected
```

### Coverage Report
```
Name                           Stmts   Miss  Cover
--------------------------------------------------
src/module/file.py               45      3    93%
src/module/other.py              32      8    75%
--------------------------------------------------
TOTAL                            144     23    84%
```

## Troubleshooting

### Tests Can't Import Modules

```bash
# Install dependencies (use venv directly — never source activate)
./venv/bin/pip install -r requirements.txt

# Install project in editable mode
./venv/bin/pip install -e .
```

### Database Connection Errors

```bash
# Ensure PostgreSQL running
pg_isready

# Create test database
createdb {your_db_test}  # TODO: your test DB name

# Run migrations
alembic upgrade head  # TODO: your migration command
```

## Configuration

### pytest.ini
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    --verbose
    --strict-markers
markers =
    unit: Unit tests (fast, isolated)
    integration: Integration tests (require database)
    slow: Slow tests (can be skipped)
```
