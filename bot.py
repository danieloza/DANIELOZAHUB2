# -*- coding: utf-8 -*-
import logging
from logging.handlers import RotatingFileHandler

from telegram.ext import ApplicationBuilder

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
        RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
    )


setup_logging()
log = logging.getLogger("danex")


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

    app = ApplicationBuilder().token(must(ENV_TG)).build()

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
