import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import google.auth
import structlog
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request

from redis.credentials import CredentialProvider

IAM_USERNAME = "default"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
REFRESH_RETRY_DELAY = timedelta(seconds=30)

logger = structlog.get_logger()


class RefreshableCredentials(Protocol):
    token: str | None
    expiry: datetime | None

    @property
    def valid(self) -> bool: ...

    def refresh(self, request: Any) -> None: ...


class GoogleIamCredentialProvider(CredentialProvider):
    def __init__(
        self,
        credentials_loader: Callable[[], RefreshableCredentials] | None = None,
    ) -> None:
        self._credentials_loader = credentials_loader or self._load_cloud_platform_credentials
        self._credentials: RefreshableCredentials | None = None
        self._lock = threading.Lock()
        self._retry_not_before: datetime | None = None

    def get_credentials(self) -> tuple[str, str]:
        with self._lock:
            if self._credentials is None:
                self._credentials = self._credentials_loader()
            if self._refresh_due(self._credentials):
                self._refresh(self._credentials)
            if self._credentials.token is None:
                raise RefreshError("credentials refresh returned no token")
            return IAM_USERNAME, self._credentials.token

    async def get_credentials_async(self) -> tuple[str, str]:
        return await asyncio.to_thread(self.get_credentials)

    def _refresh_due(self, credentials: RefreshableCredentials) -> bool:
        if self._is_expired(credentials):
            return True
        if self._retry_not_before is not None and self._naive_utc_now() < self._retry_not_before:
            return False
        return not credentials.valid

    def _is_expired(self, credentials: RefreshableCredentials) -> bool:
        return credentials.token is None or credentials.expiry is None or credentials.expiry <= self._naive_utc_now()

    def _refresh(self, credentials: RefreshableCredentials) -> None:
        try:
            credentials.refresh(Request())
        except Exception:
            if self._is_expired(credentials):
                raise
            self._retry_not_before = self._naive_utc_now() + REFRESH_RETRY_DELAY
            logger.warning("google_iam_token_refresh_failed", exc_info=True)
        else:
            self._retry_not_before = None

    @staticmethod
    def _load_cloud_platform_credentials() -> RefreshableCredentials:
        return cast(RefreshableCredentials, google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])[0])  # pyright: ignore[reportUnknownMemberType]

    @staticmethod
    def _naive_utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
