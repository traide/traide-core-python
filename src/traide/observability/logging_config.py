import logging
import sys
from dataclasses import dataclass
from enum import StrEnum

import structlog
from google.cloud.logging.handlers import StructuredLogHandler


class LogType(StrEnum):
    GCP = "GCP"
    JSON = "JSON"
    CONSOLE = "CONSOLE"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LoggerConfig:
    name: str
    level: LogLevel


@dataclass
class LoggingConfig:
    log_type: LogType
    log_level: LogLevel
    loggers_to_configure: list[LoggerConfig]


def configure_structlog(
    logging_config: LoggingConfig,
) -> None:
    # https://www.structlog.org/en/stable/standard-library.html#rendering-using-structlog-based-formatters-within-logging
    # Explains most of the code below

    shared_processors: list[structlog.types.Processor] = [
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
    ]

    match logging_config.log_type:
        case LogType.CONSOLE:
            structlog.configure(
                processors=[structlog.contextvars.merge_contextvars] + shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
                wrapper_class=structlog.stdlib.BoundLogger,
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )

            formatter = structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.dev.ConsoleRenderer(colors=True, force_colors=True),
                ],
            )

            handler = logging.StreamHandler(stream=sys.stdout)
            handler.setFormatter(formatter)

        case LogType.JSON:
            structlog.configure(
                processors=[structlog.contextvars.merge_contextvars] + shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
                wrapper_class=structlog.stdlib.BoundLogger,
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                cache_logger_on_first_use=True,
            )

            formatter = structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.dict_tracebacks,
                    structlog.processors.JSONRenderer(),
                ],
            )

            handler = logging.StreamHandler(stream=sys.stdout)
            handler.setFormatter(formatter)

        case _:
            handler = StructuredLogHandler()  # type: ignore
            formatter = structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared_processors
                + [
                    structlog.processors.EventRenamer("message"),  # google cloud logging expects message
                ],
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer(),
                ],
            )
            handler = StructuredLogHandler()  # type: ignore
            handler.setFormatter(formatter)

    logging.basicConfig(handlers=[handler], level=logging_config.log_level.value)
    logging.captureWarnings(True)

    for logger_config in logging_config.loggers_to_configure:
        logger = logging.getLogger(logger_config.name)
        logger.handlers.clear()
        logger.handlers.append(handler)
        logger.setLevel(logger_config.level.value)
        if logger_config.name in ["uvicorn.error", "uvicorn.access"]:
            logger.propagate = False
