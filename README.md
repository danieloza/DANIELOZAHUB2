# Danex Faktury Bot

Telegram bot for invoice handling (PDF/images): OCR, validation workflow, and export/integration layer.

## What It Does
- Accepts invoices as `PDF/JPG/PNG`
- Extracts key fields (date, number, company, gross amount)
- Prevents duplicates (file hash + OCR content hash)
- Supports review statuses and operator/admin workflows
- Includes audit trail, retry queue, retention tasks, and health checks

## Core Features
- OCR-driven data extraction
- Role-based access (`ADMIN`, `OPERATOR`, `VIEWER`, optional `MAMA` flow)
- Storage routing (Sheets/API)
- Diagnostics and metrics commands
- Backup/restore test flow

## Tech Stack
- Python 3.11+
- `python-telegram-bot`
- OCR pipeline + storage adapters
- Pytest test suite

## Run Local
```powershell
cd C:\Users\syfsy\danex-faktury-bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\.venv\Scripts\python.exe bot.py
```

## Tests
```powershell
cd C:\Users\syfsy\danex-faktury-bot
.\.venv\Scripts\python.exe -m pytest -q tests
```

## Security Before Publishing
Do not publish secrets or production data.

Required checks before push:
1. Ensure `.env` and credentials files are excluded from git.
2. Remove any real tokens/keys from config and history.
3. Use sanitized sample data only.

Suggested `.gitignore` entries:
- `.env`
- `.env.*`
- `.venv/`
- `logs/`
- `data/`
- `*.json` (if credentials)

## Repo Structure
- `bot.py` - app entrypoint
- `handlers/` - command and message handlers
- `domain/` - audit, backup, retention, retry logic
- `storage_*.py` - storage layer
- `tests/` - automated tests

## Portfolio Note
This repository is suitable for portfolio as a sanitized technical showcase.
If connected to real client operations, keep the GitHub repo private.
