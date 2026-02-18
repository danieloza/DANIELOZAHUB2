# -*- coding: utf-8 -*-
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from domain.secrets import secret_env


load_dotenv(".env", override=True)


def env(k: str, default: str = "") -> str:
    return secret_env(k, default).strip()


def must(k: str) -> str:
    v = env(k)
    if not v:
        raise RuntimeError(f"Missing env: {k}")
    return v


# --- ENV keys ---
ENV_TG = "TELEGRAM_BOT_TOKEN"
ENV_SHEET_ID = "SPREADSHEET_ID"
ENV_SHEET_NAME = "SHEET_NAME"
ENV_SA = "GOOGLE_SERVICE_ACCOUNT_JSON"
ENV_DRIVE = "DRIVE_FOLDER_ID"
ENV_TESS = "TESSERACT_CMD"
ENV_ALLOWED = "ALLOWED_USER_IDS"
ENV_ADMIN = "ADMIN_USER_IDS"
ENV_OPERATOR = "OPERATOR_USER_IDS"
ENV_VIEWER = "VIEWER_USER_IDS"
ENV_MAMA = "MAMA_USER_IDS"
ENV_SAFE_MODE = "SAFE_MODE"
ENV_RUN_GSHEETS_INTEGRATION = "RUN_GSHEETS_INTEGRATION"
ENV_REMINDER_HOUR = "TODO_REMINDER_HOUR"
ENV_REMINDER_MINUTE = "TODO_REMINDER_MINUTE"
ENV_WEEKLY_REPORT_HOUR = "WEEKLY_REPORT_HOUR"
ENV_WEEKLY_REPORT_MINUTE = "WEEKLY_REPORT_MINUTE"
ENV_WEEKLY_REPORT_WEEKDAY = "WEEKLY_REPORT_WEEKDAY"
ENV_MAX_UPLOAD_BYTES = "MAX_UPLOAD_BYTES"
ENV_MAX_OCR_PDF_PAGES = "MAX_OCR_PDF_PAGES"
ENV_HEALTH_ALERTS_ENABLED = "HEALTH_ALERTS_ENABLED"
ENV_HEALTH_ALERT_COOLDOWN_MIN = "HEALTH_ALERT_COOLDOWN_MIN"
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_MAMA_VOICE_ENABLED = "MAMA_VOICE_ENABLED"
ENV_MAMA_FAVORITE_SHOPS = "MAMA_FAVORITE_SHOPS"
ENV_MAMA_STUCK_ALERT_MIN = "MAMA_STUCK_ALERT_MIN"
ENV_MAMA_CANCEL_ALERT_STREAK = "MAMA_CANCEL_ALERT_STREAK"

SAFE_MODE = env(ENV_SAFE_MODE, "1") == "1"
RUN_GSHEETS_INTEGRATION = env(ENV_RUN_GSHEETS_INTEGRATION, "0") == "1"
REMINDER_HOUR = int(env(ENV_REMINDER_HOUR, "18") or "18")
REMINDER_MINUTE = int(env(ENV_REMINDER_MINUTE, "0") or "0")
WEEKLY_REPORT_HOUR = int(env(ENV_WEEKLY_REPORT_HOUR, str(REMINDER_HOUR)) or str(REMINDER_HOUR))
WEEKLY_REPORT_MINUTE = int(env(ENV_WEEKLY_REPORT_MINUTE, str(REMINDER_MINUTE)) or str(REMINDER_MINUTE))
WEEKLY_REPORT_WEEKDAY = int(env(ENV_WEEKLY_REPORT_WEEKDAY, "0") or "0")
MAX_UPLOAD_BYTES = int(env(ENV_MAX_UPLOAD_BYTES, str(10 * 1024 * 1024)) or str(10 * 1024 * 1024))
MAX_OCR_PDF_PAGES = int(env(ENV_MAX_OCR_PDF_PAGES, "2") or "2")
HEALTH_ALERTS_ENABLED = env(ENV_HEALTH_ALERTS_ENABLED, "1") == "1"
HEALTH_ALERT_COOLDOWN_MIN = int(env(ENV_HEALTH_ALERT_COOLDOWN_MIN, "30") or "30")
MAMA_VOICE_ENABLED = env(ENV_MAMA_VOICE_ENABLED, "0") == "1"
MAMA_STUCK_ALERT_MIN = int(env(ENV_MAMA_STUCK_ALERT_MIN, "15") or "15")
MAMA_CANCEL_ALERT_STREAK = int(env(ENV_MAMA_CANCEL_ALERT_STREAK, "3") or "3")

# --- Paths ---
BASE_DIR = Path(__file__).parent
INV_DIR = BASE_DIR / "invoices"
INV_DIR.mkdir(exist_ok=True)

BACKUPS_DIR = BASE_DIR / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

SA_JSON_DEFAULT = BASE_DIR / "danex-faktury-bot.json"

# --- Sheets columns ---
COL_DATE = 1
COL_NO = 2
COL_COMP = 3
COL_GROSS = 4
COL_TYPE = 5
COL_VAT = 6
COL_NET = 7
COL_CAT = 8
COL_USER = 9
COL_STATUS = 10
COL_FILE = 11

# --- Values ---
TYPE_VAT = "VAT"
TYPE_NO_VAT = "Bez VAT"

STATUS_NEW = "Nowa"
STATUS_TODO = "Do sprawdzenia"
STATUS_OK = "Sprawdzona"
STATUS_SENT = "Wyslana do ksiegowej"
DEFAULT_CATEGORY = "inne"

# --- Runtime state (per-user) ---
STATE = {}


def parse_csv_list(raw: str, default: list[str] | None = None) -> list[str]:
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    if parts:
        return parts
    return list(default or [])


MAMA_FAVORITE_SHOPS = parse_csv_list(
    env(ENV_MAMA_FAVORITE_SHOPS, ""),
    default=["Biedronka", "Apteka", "Lidl", "Rossmann", "Carrefour"],
)


def parse_user_id_set(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    s = set()
    for p in raw.split(","):
        p = p.strip()
        if p.isdigit():
            s.add(int(p))
    return s if s else None


ALLOWED = parse_user_id_set(env(ENV_ALLOWED, ""))
ADMIN = parse_user_id_set(env(ENV_ADMIN, ""))
OPERATORS = parse_user_id_set(env(ENV_OPERATOR, ""))
VIEWERS = parse_user_id_set(env(ENV_VIEWER, ""))
MAMA_USERS = parse_user_id_set(env(ENV_MAMA, ""))


def _uid(update):
    return update.effective_user.id if update and update.effective_user else None


def is_allowed(update) -> bool:
    uid = _uid(update)
    if uid is None:
        return False
    if ALLOWED is None:
        return True
    return uid in ALLOWED


def is_admin(update) -> bool:
    uid = _uid(update)
    if uid is None or not is_allowed(update):
        return False
    if ADMIN is None:
        return False
    return uid in ADMIN


def is_mama(update) -> bool:
    uid = _uid(update)
    if uid is None or not is_allowed(update):
        return False
    if not MAMA_USERS:
        return False
    return uid in MAMA_USERS


def user_role(update) -> str:
    uid = _uid(update)
    if uid is None or not is_allowed(update):
        return "blocked"
    if ADMIN and uid in ADMIN:
        return "admin"
    if MAMA_USERS and uid in MAMA_USERS:
        return "mama"
    if OPERATORS is not None:
        if uid in OPERATORS:
            return "operator"
        if VIEWERS is None or uid in VIEWERS:
            return "viewer"
        return "blocked"
    if VIEWERS and uid in VIEWERS:
        return "viewer"
    return "operator"


def is_operator(update) -> bool:
    return user_role(update) in {"admin", "operator"}


def admin_ids() -> set[int]:
    if ADMIN:
        return set(ADMIN)
    if ALLOWED:
        return set(ALLOWED)
    return set()


def mama_ids() -> set[int]:
    if MAMA_USERS:
        return set(MAMA_USERS)
    return set()


def backup_env_file() -> Path | None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return None
    dst = BACKUPS_DIR / f"env_backup_{datetime.now():%Y%m%d_%H%M%S}.env"
    dst.write_text(env_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    return dst


def validate_startup_env() -> tuple[list[str], list[str]]:
    missing_required = []
    missing_recommended = []

    if not env(ENV_TG):
        missing_required.append(ENV_TG)

    for k in (ENV_SHEET_ID, ENV_DRIVE):
        if not env(k):
            missing_recommended.append(k)

    sa = env(ENV_SA, str(SA_JSON_DEFAULT))
    if sa and not sa.startswith("sm://") and not sa.startswith("{") and not Path(sa).exists():
        missing_recommended.append(f"{ENV_SA} file missing: {sa}")

    return missing_required, missing_recommended




