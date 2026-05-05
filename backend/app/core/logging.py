import logging
import sys
from loguru import logger


class _InterceptHandler(logging.Handler):
    """Bridge standard library logging → loguru.

    SQLAlchemy (and uvicorn) emit via stdlib logging. This handler
    forwards every record into loguru so all logs land in one place.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.opt(exception=record.exc_info).patch(
            lambda r: r.update(name=record.name)  # type: ignore[arg-type]
        ).log(level, record.getMessage())


def setup_logging() -> None:
    logger.remove()

    # ── Console — coloured, human-readable ───────────────────────────────────
    logger.add(
        sys.stdout,
        level="DEBUG",
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
            "{message}"
        ),
    )

    # ── File — JSON, rotated daily, 14-day retention ─────────────────────────
    logger.add(
        "logs/hiring.log",
        level="INFO",
        rotation="00:00",
        retention="14 days",
        compression="zip",
        serialize=True,
        enqueue=True,
    )

    # ── Intercept stdlib logging (SQLAlchemy, uvicorn, asyncpg) → loguru ─────
    intercept = _InterceptHandler()
    intercept.setLevel(logging.DEBUG)

    # Route SQLAlchemy engine queries — these appear on sqlalchemy.engine
    for name in (
        "sqlalchemy.engine",
        "sqlalchemy.engine.Engine",
        "sqlalchemy.pool",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [intercept]
        std_logger.propagate = False

    # Silence noisy sub-loggers that produce duplicate lines
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.INFO)