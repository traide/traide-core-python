from dataclasses import dataclass

from opentelemetry.sdk.trace import TracerProvider

from traide.observability.logging_config import LogLevel, LogType
from traide.observability.sentry_config import SentryConfig
from traide.observability.tracing_config import TracingType


@dataclass
class ObservabilityConfig:
    service_name: str
    hostname: str
    log_level: LogLevel = LogLevel.INFO
    log_type: LogType = LogType.GCP
    tracing_type: TracingType = TracingType.GCP
    sentry_config: SentryConfig | None = None


@dataclass
class ObservabilityConfigurationResult:
    tracer_provider: TracerProvider
