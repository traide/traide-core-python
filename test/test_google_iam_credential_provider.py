import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from google.auth.exceptions import RefreshError
from structlog.testing import capture_logs

from traide.redis.google_iam_credential_provider import GoogleIamCredentialProvider

REFRESH_THRESHOLD = timedelta(minutes=3, seconds=45)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class StubCredentials:
    def __init__(self, refresh_duration_seconds: float = 0) -> None:
        self._refresh_duration_seconds = refresh_duration_seconds
        self.token: str | None = None
        self.expiry: datetime | None = None
        self.refresh_count = 0
        self.attempt_count = 0
        self.fail_next_refresh = False
        self.issue_empty_token = False
        self.refresh_thread: threading.Thread | None = None

    @property
    def valid(self) -> bool:
        return self.token is not None and self.expiry is not None and self.expiry - REFRESH_THRESHOLD > _now()

    def refresh(self, request: Any) -> None:
        self.refresh_thread = threading.current_thread()
        self.attempt_count += 1
        time.sleep(self._refresh_duration_seconds)
        if self.fail_next_refresh:
            self.fail_next_refresh = False
            raise RefreshError("refresh failed")
        if self.issue_empty_token:
            return
        self.refresh_count += 1
        self.token = f"token-{self.refresh_count}"
        self.expiry = _now() + timedelta(hours=1)


@pytest.fixture
def credentials() -> StubCredentials:
    return StubCredentials()


@pytest.fixture
def loader_calls() -> list[None]:
    return []


@pytest.fixture
def provider(credentials: StubCredentials, loader_calls: list[None]) -> GoogleIamCredentialProvider:
    return _provider(credentials=credentials, loader_calls=loader_calls)


def _provider(credentials: StubCredentials, loader_calls: list[None]) -> GoogleIamCredentialProvider:
    def load() -> StubCredentials:
        loader_calls.append(None)
        return credentials

    return GoogleIamCredentialProvider(credentials_loader=load)


def _expire_in(credentials: StubCredentials, remaining: timedelta) -> None:
    credentials.expiry = _now() + remaining


def test_first_call_refreshes_and_returns_the_default_username_with_the_token(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    assert provider.get_credentials() == ("default", "token-1")
    assert credentials.refresh_count == 1


def test_reuses_the_token_while_more_than_five_minutes_remain(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    _expire_in(credentials, timedelta(minutes=10))
    assert provider.get_credentials() == ("default", "token-1")


def test_refreshes_the_token_when_less_than_five_minutes_remain(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    _expire_in(credentials, timedelta(minutes=3))
    assert provider.get_credentials() == ("default", "token-2")


def test_loads_credentials_once(provider: GoogleIamCredentialProvider, loader_calls: list[None]) -> None:
    for _ in range(3):
        provider.get_credentials()
    assert len(loader_calls) == 1


def test_loads_nothing_until_credentials_are_requested(provider: GoogleIamCredentialProvider, loader_calls: list[None]) -> None:
    assert loader_calls == []


def test_keeps_the_cached_token_when_a_refresh_fails_before_expiry(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    _expire_in(credentials, timedelta(minutes=3))
    credentials.fail_next_refresh = True
    assert provider.get_credentials() == ("default", "token-1")


def test_raises_when_a_refresh_fails_after_expiry(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    _expire_in(credentials, timedelta(seconds=-1))
    credentials.fail_next_refresh = True
    with pytest.raises(RefreshError):
        provider.get_credentials()


def test_concurrent_callers_share_one_refresh() -> None:
    slow_credentials = StubCredentials(refresh_duration_seconds=0.2)
    provider = _provider(credentials=slow_credentials, loader_calls=[])
    results: list[tuple[str, str]] = []
    threads = [threading.Thread(target=lambda: results.append(provider.get_credentials())) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert slow_credentials.refresh_count == 1
    assert results == [("default", "token-1")] * 20


def test_async_credentials_refresh_off_the_event_loop_thread(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    assert asyncio.run(provider.get_credentials_async()) == ("default", "token-1")
    assert credentials.refresh_thread is not threading.main_thread()


def test_logs_a_warning_when_a_refresh_fails_before_expiry(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    _expire_in(credentials, timedelta(minutes=3))
    credentials.fail_next_refresh = True
    with capture_logs() as logs:
        provider.get_credentials()
    assert [(log["event"], log["log_level"]) for log in logs] == [("google_iam_token_refresh_failed", "warning")]


def test_does_not_retry_a_failed_refresh_within_the_retry_delay(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    _expire_in(credentials, timedelta(minutes=3))
    credentials.fail_next_refresh = True
    provider.get_credentials()
    assert provider.get_credentials() == ("default", "token-1")
    assert credentials.attempt_count == 2


def test_retries_a_failed_refresh_after_the_retry_delay(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    _expire_in(credentials, timedelta(minutes=3))
    credentials.fail_next_refresh = True
    provider.get_credentials()
    provider._retry_not_before = _now() - timedelta(seconds=1)  # pyright: ignore[reportPrivateUsage]
    assert provider.get_credentials() == ("default", "token-2")


def test_attempts_a_refresh_once_the_token_has_expired_even_within_the_retry_delay(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    provider.get_credentials()
    _expire_in(credentials, timedelta(seconds=10))
    credentials.fail_next_refresh = True
    provider.get_credentials()
    _expire_in(credentials, timedelta(seconds=-5))
    assert provider.get_credentials() == ("default", "token-2")


def test_raises_when_a_refresh_yields_no_token(provider: GoogleIamCredentialProvider, credentials: StubCredentials) -> None:
    credentials.issue_empty_token = True
    with pytest.raises(RefreshError):
        provider.get_credentials()
