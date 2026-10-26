import asyncio
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog
from google.auth.credentials import Credentials, TokenState
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request

from redis.credentials import CredentialProvider
from redis.exceptions import AuthenticationError
from traide.google_cloud import cloud_platform_default_credentials

IAM_USERNAME = "default"
REFRESH_RETRY_DELAY = timedelta(seconds=30)
TOKEN_REQUEST_DEFAULT_TIMEOUT_SECONDS = 10
REFRESH_WAIT_TIMEOUT_SECONDS = 10
EXPIRY_SAFETY_MARGIN = timedelta(seconds=30)

logger = structlog.get_logger()


class DefaultTimeoutRequest(Request):
    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: int = TOKEN_REQUEST_DEFAULT_TIMEOUT_SECONDS,
        **kwargs: Any,
    ) -> Any:
        return super().__call__(url, method=method, body=body, headers=headers, timeout=timeout, **kwargs)  # pyright: ignore[reportUnknownMemberType]


class GoogleIamCredentialProvider(CredentialProvider):
    def __init__(self, credentials_loader: Callable[[], Credentials] | None = None) -> None:
        self._credentials_loader = credentials_loader or self._load_cloud_platform_credentials
        self._credentials: Credentials | None = None
        self._refresh_lock = threading.Lock()
        self._retry_not_before: datetime | None = None
        self._request = DefaultTimeoutRequest()

    def get_credentials(self) -> tuple[str, str]:
        token_state = self._token_state()
        if token_state is TokenState.INVALID:
            return self._wait_for_refresh()
        if token_state is TokenState.STALE and not self._refresh_held_off() and self._refresh_lock.acquire(blocking=False):
            try:
                self._refresh_stale_token()
            finally:
                self._refresh_lock.release()
        return self._cached_credentials()

    async def get_credentials_async(self) -> tuple[str, str]:
        token_state = self._token_state()
        if token_state is TokenState.FRESH or (token_state is TokenState.STALE and (self._refresh_held_off() or self._refresh_lock.locked())):
            return self._cached_credentials()
        return await asyncio.to_thread(self.get_credentials)

    def _token_state(self) -> TokenState:
        if self._credentials is None:
            return TokenState.INVALID
        token_state = self._credentials.token_state
        expiry = cast(datetime | None, self._credentials.expiry)
        if token_state is TokenState.STALE and expiry is not None and expiry - EXPIRY_SAFETY_MARGIN <= self._naive_utc_now():
            return TokenState.INVALID
        return token_state

    def _cached_credentials(self) -> tuple[str, str]:
        token = cast(str | None, self._credentials.token) if self._credentials is not None else None
        if token is None:
            raise AuthenticationError("google iam token missing")
        return IAM_USERNAME, token

    def _wait_for_refresh(self) -> tuple[str, str]:
        if not self._refresh_lock.acquire(timeout=REFRESH_WAIT_TIMEOUT_SECONDS):
            raise AuthenticationError("timed out waiting for a google iam token refresh")
        try:
            return self._refresh_invalid_token()
        except Exception as error:
            raise AuthenticationError("google iam credentials unavailable") from error
        finally:
            self._refresh_lock.release()

    def _refresh_invalid_token(self) -> tuple[str, str]:
        if self._token_state() is not TokenState.INVALID:
            return self._cached_credentials()
        if self._refresh_held_off():
            raise RefreshError("google iam token refresh held off after a failed attempt")
        self._refresh_unless_fresh()
        return self._cached_credentials()

    def _refresh_stale_token(self) -> None:
        try:
            self._refresh_unless_fresh()
        except Exception:
            logger.warning("google_iam_token_refresh_failed", exc_info=True)

    def _loaded_credentials(self) -> Credentials:
        if self._credentials is None:
            self._credentials = self._credentials_loader()
        return self._credentials

    def _refresh_unless_fresh(self) -> None:
        try:
            credentials = self._loaded_credentials()
            if self._token_state() is not TokenState.FRESH:
                credentials.refresh(self._request)  # pyright: ignore[reportUnknownMemberType]
            if self._token_state() is TokenState.INVALID:
                raise RefreshError("credentials refresh returned no usable token")
        except Exception:
            self._retry_not_before = self._naive_utc_now() + REFRESH_RETRY_DELAY
            raise
        self._retry_not_before = None

    def _refresh_held_off(self) -> bool:
        retry_not_before = self._retry_not_before
        return retry_not_before is not None and self._naive_utc_now() < retry_not_before

    @staticmethod
    def _load_cloud_platform_credentials() -> Credentials:
        return cloud_platform_default_credentials()[0]

    @staticmethod
    def _naive_utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
