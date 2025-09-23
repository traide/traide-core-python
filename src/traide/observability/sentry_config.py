import logging
from dataclasses import dataclass

import sentry_sdk

logger = logging.getLogger(__name__)


@dataclass
class SentryConfig:
    dsn: str | None
    enabled: bool
    environment: str
    traces_sample_rate: float
    profiles_sample_rate: float
    api_version: str

def configure_sentry(sentry_config: SentryConfig) -> None:
    logger.info(
        "Configuring Sentry",
        extra={
            "release": sentry_config.api_version,
            "is_enabled": sentry_config.enabled,
            "environment": sentry_config.environment,
            "traces_sample_rate": sentry_config.traces_sample_rate,
            "profiles_sample_rate": sentry_config.profiles_sample_rate,
        },
    )
    if sentry_config.dsn and sentry_config.enabled:
        sentry_sdk.init(
            dsn=sentry_config.dsn,
            traces_sample_rate=sentry_config.traces_sample_rate,
            profiles_sample_rate=sentry_config.profiles_sample_rate,
            environment=sentry_config.environment,
            release=sentry_config.api_version,
        )
