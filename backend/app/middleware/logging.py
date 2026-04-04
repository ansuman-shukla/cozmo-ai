"""Logging helpers for the backend service."""

import logging

NOISY_LOGGERS: dict[str, int] = {
    "pymongo": logging.WARNING,
    "pymongo.command": logging.WARNING,
    "pymongo.connection": logging.WARNING,
    "pymongo.serverSelection": logging.WARNING,
    "pymongo.topology": logging.WARNING,
}


def resolve_log_level(environment: str, configured_level: str | None = None) -> int:
    """Resolve the effective application log level."""

    if configured_level:
        level_name = configured_level.strip().upper()
        if hasattr(logging, level_name):
            resolved = getattr(logging, level_name)
            if isinstance(resolved, int):
                return resolved

    return logging.DEBUG if environment == "development" else logging.INFO


def configure_logging(environment: str, configured_level: str | None = None) -> None:
    """Install a simple structured logging baseline."""

    level = resolve_log_level(environment, configured_level)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    for logger_name, logger_level in NOISY_LOGGERS.items():
        logging.getLogger(logger_name).setLevel(logger_level)
