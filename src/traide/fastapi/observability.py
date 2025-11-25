from traide.observability.logging_config import LoggerConfig, LoggingConfig, LogLevel, configure_structlog
from traide.observability.observability_config import ObservabilityConfig, ObservabilityConfigurationResult
from traide.observability.sentry_config import configure_sentry
from traide.observability.tracing_config import configure_tracing


def configure_observability(observability_config: ObservabilityConfig) -> ObservabilityConfigurationResult:
    configure_structlog(
        logging_config=LoggingConfig(
            log_level=observability_config.log_level,
            log_type=observability_config.log_type,
            loggers_to_configure=[
                LoggerConfig(name="uvicorn", level=LogLevel.INFO),
                LoggerConfig(name="uvicorn.access", level=LogLevel.WARNING),
                LoggerConfig(name="uvicorn.error", level=LogLevel.INFO),
                LoggerConfig(name="faststream.client", level=LogLevel.ERROR),
                LoggerConfig(name="httpx", level=LogLevel.WARNING),
            ],
        )
    )
    tracer_provider = configure_tracing(service_name=observability_config.service_name, hostname=observability_config.hostname, tracing_type=observability_config.tracing_type)
    if observability_config.sentry_config:
        configure_sentry(observability_config.sentry_config)

    return ObservabilityConfigurationResult(tracer_provider=tracer_provider)
