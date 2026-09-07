# Quick Start

## Commands

```bash
pytest                    # TODO: your test command
ruff check src/ tests/    # TODO: your lint command
ruff format src/ tests/   # TODO: your format command
python src/main.py        # TODO: your run command
```

## Virtual Environment

<!-- TODO: Adjust for your setup (venv, poetry, conda, etc.) -->

If `pytest` is not found, use `./venv/bin/pytest` directly.
Do NOT prepend `source venv/bin/activate &&` before every command.

## Database

<!-- TODO: Remove this section if your project has no database -->

```bash
psql -d {your_db_dev}     # TODO: Database shell
alembic upgrade head       # TODO: Run migrations
```

## Linting & Formatting

<!-- TODO: Adjust linter/formatter and style preferences -->

Ruff (pre-commit hooks auto-run): `ruff check src/ tests/` and `ruff format src/ tests/`.
Style: Google docstrings, double quotes, 88-char lines.
