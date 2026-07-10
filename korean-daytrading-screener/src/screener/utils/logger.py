from pathlib import Path

from loguru import logger

_CONFIGURED = False


def setup_logger(log_dir: Path, level: str = "INFO", retention_days: int = 90) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        log_dir / "screener_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention=f"{retention_days} days",
        level=level,
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )
    logger.add(lambda msg: print(msg, end=""), level=level, colorize=True)
    _CONFIGURED = True


__all__ = ["logger", "setup_logger"]
