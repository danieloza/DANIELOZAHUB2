# -*- coding: utf-8 -*-
import logging
import structlog
from logging.handlers import RotatingFileHandler

from telegram.ext import ApplicationBuilder, ContextTypes
from datetime import datetime

from config import ENV_TG, LOGS_DIR, backup_env_file, must, validate_startup_env
from domain.retention import apply_retention
from handlers.callbacks import register as register_callbacks
from handlers.commands import register as register_commands
from handlers.errors import on_error
from handlers.files import register as register_files
from handlers.messages import register as register_messages
from handlers.reminders import register_reminders


def setup_logging() -> None:
    log_file = LOGS_DIR / "bot.log"
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=handlers,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


setup_logging()
log = structlog.get_logger("danex.faktury")

async def heartbeat_task(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Senior IT: Regular sign of life."""
    log.info("bot_heartbeat", status="alive", timestamp=datetime.now().isoformat())


def main():
    must(ENV_TG)

    backed = backup_env_file()
    if backed:
        log.info(".env backup saved: %s", backed)

    missing_required, missing_recommended = validate_startup_env()
    if missing_required:
        raise RuntimeError(f"Missing required env: {', '.join(missing_required)}")
    if missing_recommended:
        log.warning("Startup env warnings: %s", "; ".join(missing_recommended))

    ret = apply_retention()
    log.info("Retention startup run: %s", ret)
    
    # Senior IT: Startup Health Check
    from domain.integrity import get_system_health_checklist
    checks = get_system_health_checklist()
    for name, ok, det in checks:
        if ok:
            log.info(f"STARTUP CHECK: {name} ... OK")
        else:
            log.error(f"STARTUP CHECK: {name} ... FAIL ({det})")

    app = ApplicationBuilder().token(must(ENV_TG)).build()

    # Senior IT: Pulse heartbeat every hour
    if app.job_queue:
        app.job_queue.run_repeating(heartbeat_task, interval=3600, first=10)

    register_commands(app)
    register_callbacks(app)
    register_files(app)
    register_messages(app)
    register_reminders(app)
    app.add_error_handler(on_error)

    log.info("Danex Faktury dziala. /start otwiera menu, /backup robi ZIP.")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
