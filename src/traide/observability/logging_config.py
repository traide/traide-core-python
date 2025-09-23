import logging
import sys
from dataclasses import dataclass
from enum import IntEnum, StrEnum

import structlog
from google.cloud.logging.handlers import StructuredLogHandler
from google.cloud.logging_v2.handlers import setup_logging  #  type: ignore


class LogType(StrEnum):
    GCP = "GCP"
    JSON = "JSON"
    CONSOLE = "CONSOLE"


class LogLevel(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


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

            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            root_logger.setLevel(logging_config.log_level)
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

            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            root_logger.setLevel(logging_config.log_level)
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
            setup_logging(handler, log_level=logging_config.log_level)  # type: ignore

    for logger_config in logging_config.loggers_to_configure:
        logger = logging.getLogger(logger_config.name)
        logger.addHandler(handler)
        logger.setLevel(logger_config.level)
