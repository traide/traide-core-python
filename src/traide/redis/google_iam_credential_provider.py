import asyncio
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import google.auth
from google.auth.transport.requests import Request

from redis.credentials import CredentialProvider

IAM_USERNAME = "default"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
TOKEN_REFRESH_MARGIN = timedelta(minutes=5)


class RefreshableCredentials(Protocol):
    token: str | None
    expiry: datetime | None

    def refresh(self, request: Any) -> None: ...


def load_cloud_platform_credentials() -> RefreshableCredentials:
    return cast(RefreshableCredentials, google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])[0])  # pyright: ignore[reportUnknownMemberType]


def naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class GoogleIamCredentialProvider(CredentialProvider):
    def __init__(
        self,
        credentials_loader: Callable[[], RefreshableCredentials] = load_cloud_platform_credentials,
        clock: Callable[[], datetime] = naive_utc_now,
    ) -> None:
        self._credentials_loader = credentials_loader
        self._clock = clock
        self._credentials: RefreshableCredentials | None = None
        self._lock = threading.Lock()

    def get_credentials(self) -> tuple[str, str]:
        with self._lock:
            if self._credentials is None:
                self._credentials = self._credentials_loader()
            if self._refresh_due(self._credentials):
                self._refresh(self._credentials)
            assert self._credentials.token is not None
            return IAM_USERNAME, self._credentials.token

    async def get_credentials_async(self) -> tuple[str, str]:
        return await asyncio.to_thread(self.get_credentials)

    def _refresh_due(self, credentials: RefreshableCredentials) -> bool:
        return credentials.token is None or credentials.expiry is None or credentials.expiry - self._clock() < TOKEN_REFRESH_MARGIN

    def _refresh(self, credentials: RefreshableCredentials) -> None:
        try:
            credentials.refresh(Request())
        except Exception:
            if credentials.token is None or credentials.expiry is None or credentials.expiry <= self._clock():
                raise
